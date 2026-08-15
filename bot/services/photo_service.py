"""
Сервис извлечения максимального количества метаданных из изображения.

Двигатели:
  * exifread  — полный разбор EXIF-структуры (включая MakerNote, GPS, Thumbnail);
  * Pillow    — размер/формат/DPI/цветовая модель, аватары ICC;
  * geopy     — обратное геокодирование GPS-координат (optional);
  * построение ссылок на карты по GPS.

Важно: Telegram сжимает фото, присланные как «Фото» — EXIF при этом
вырезается. Для полного извлечения отправляйте файл как «Документ».
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import exifread
from exifread.utils import Ratio

from bot.exceptions import ServiceError
from bot.services.devices import recognize_device
from bot.utils.formatting import esc

# Интересные теги, которые не должны потеряться среди мусора
_PRIORITY_PREFIXES = ("Image ", "EXIF ", "GPS ", "MakerNote ", "Thumbnail ", "Interop ")

# Русские названия групп EXIF (заголовки в «Все EXIF-теги»)
_GROUP_RU = {
    "Image": "Основные данные",
    "EXIF": "Параметры съёмки (EXIF)",
    "GPS": "GPS (сырые теги)",
    "MakerNote": "Заметки производителя",
    "Thumbnail": "Миниатюра",
    "Interop": "Совместимость",
    "Прочее": "Прочее",
}


def _val(tag) -> str:
    # exifread с details=True отдаёт IfdTag; из него берём данные напрямую
    values = getattr(tag, "values", tag)
    field_type = getattr(tag, "field_type", None)
    if isinstance(values, bytes):
        try:
            return values.decode("utf-8", errors="replace").strip()
        except Exception:  # noqa: BLE001
            return repr(values)
    # BYTE(1)/UNDEFINED(7) — байтовый массив (например, "1/1000" как byte-поле)
    if field_type in (1, 7) and isinstance(values, list) and values:
        try:
            return bytes(values).decode("utf-8", errors="replace").strip()
        except Exception:  # noqa: BLE001
            pass
    return str(tag).strip()


def _gps_coord(values) -> Optional[float]:
    """JSON GPS Rational[] → десятичные градусы (float)."""
    if isinstance(values, (list, tuple)) and len(values) == 3:
        try:
            deg, minutes, seconds = (v.float_value() if isinstance(v, Ratio) else float(v) for v in values)
            return deg + minutes / 60.0 + seconds / 3600.0
        except (AttributeError, ValueError, TypeError):
            return None
    return None


def _gps_alt(values) -> Optional[float]:
    if isinstance(values, (list, tuple)) and values:
        v = values[0]
        try:
            return v.float_value() if isinstance(v, Ratio) else float(v)
        except (AttributeError, ValueError, TypeError):
            return None
    return None


def build_maps_link(lat: float, lng: float) -> dict:
    """Готовит ссылки на карты."""
    return {
        "google": f"https://www.google.com/maps?q={lat:.7f},{lng:.7f}",
        "yandex": f"https://yandex.ru/maps/?pt={lng:.7f},{lat:.7f}&z=16",
    }


@dataclass
class PhotoReport:
    """Готовый отчёт по изображению."""

    file: dict
    image: dict
    groups: dict[str, dict[str, str]]  # group -> {tag: value}
    gps: Optional[dict]
    gps_text: list[str]
    maps: Optional[dict]
    reverse: Optional[dict]
    raw_count: int
    device: Optional[dict]


def extract_photo(path: Path) -> PhotoReport:
    """Анализирует файл изображения и возвращает структурированный отчёт."""
    if not path.exists():
        raise ServiceError("Файл не найден на диске")

    # ---- файловая метаинформация ----
    size = path.stat().st_size
    file_info = {
        "Имя": path.name,
        "Размер (Б)": size,
        "Размер (КБ)": round(size / 1024, 1),
        "Создан": _readable_time(path, "ctime"),
        "Модифицирован": _readable_time(path),
    }
    file_info.update(_file_hashes(path))

    # ---- Pillow ----
    try:
        from PIL import Image
        with Image.open(path) as img:
            w, h = img.width, img.height
            img_info = {
                "Формат": img.format or "?",
                "Ширина": w,
                "Высота": h,
                "Мегапиксели": round(w * h / 1_000_000, 2) if w and h else None,
                "Соотношение сторон": _aspect_ratio(w, h),
                "Цветовая модель": img.mode,
                "Анимированный": str(getattr(img, "is_animated", False)),
            }
            if img.info.get("dpi"):
                img_info["DPI"] = " x ".join(str(round(float(d), 1)) for d in img.info["dpi"])
            img_info["ICC-профиль"] = "есть" if img.info.get("icc_profile") else "нет"
            if getattr(img, "frames", 1) > 1:
                img_info["Кадров"] = img.frames
            comment = img.info.get("comment")
            if comment:
                if isinstance(comment, list):
                    comment = b"".join(comment)
                img_info["Комментарий (Pillow)"] = _val(comment)
    except Exception as exc:  # noqa: BLE001
        img_info = {"Ошибка Pillow": str(exc)}

    # ---- exifread :) ----
    # strict=False: битые/обрезанные файлы не роняют весь отчёт
    with path.open("rb") as f:
        tags = exifread.process_file(f, details=True, debug=False, strict=False)

    groups: dict[str, dict[str, str]] = {}
    gps_values: dict[str, Optional[str]] = {}
    priority: dict[str, str] = {}

    for tag in sorted(tags):
        key = str(tag)
        value = _val(tags[key])
        # GPS — отдельно
        if key.startswith("GPS ") and value:
            gps_values[key] = value
            continue

        # Раскладываем по группам
        for prefix in _PRIORITY_PREFIXES:
            if key.startswith(prefix):
                group = prefix.strip()
                groups.setdefault(group, {})[key[len(prefix):] or key] = value
                break
        else:
            priority[key] = value

    # ---- GPS-парсер ----
    gps, gps_text, maps = _parse_gps(gps_values)

    # ---- обратное геокодирование ----
    reverse = {}
    if gps:
        try:
            reverse = reverse_geocode(gps["lat"], gps["lng"])
        except Exception as exc:  # noqa: BLE001
            reverse = {"error": str(exc)}

    # опционально: MakerNote разворачиваем отдельной секцией
    for key in list(priority):
        if key.startswith("MakerNote"):
            groups.setdefault("MakerNote", {}).setdefault(key, priority.pop(key))

    raw_count = len(tags)
    if priority:
        groups["Прочее"] = {k: v for k, v in priority.items() if v}

    device = _find_device(tags)

    return PhotoReport(
        file=file_info,
        image=img_info,
        groups=groups,
        gps=gps,
        gps_text=gps_text,
        maps=maps,
        reverse=reverse,
        raw_count=raw_count,
        device=device,
    )


def _find_device(tags: dict) -> Optional[dict]:
    """Достаёт Make/Model из тегов exifread и распознаёт устройство."""
    make = model = ""
    for key, value in tags.items():
        name = str(key)
        if name.endswith(" Make") and not make:
            make = _val(value)
        elif name.endswith(" Model") and not model:
            model = _val(value)
    return recognize_device(make, model)


def _readable_time(path: Path, field: str = "mtime") -> str:
    try:
        import datetime
        st = path.stat()
        ts = getattr(st, field, st.st_mtime)
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:  # noqa: BLE001
        return "—"


def _file_hashes(path: Path) -> dict[str, str]:
    """MD5/SHA1/SHA256 файла — для проверки целостности и дедупликации."""
    import hashlib
    md5, sha1, sha256 = hashlib.md5(), hashlib.sha1(), hashlib.sha256()
    try:
        with path.open("rb") as f:
            while chunk := f.read(1 << 20):
                md5.update(chunk)
                sha1.update(chunk)
                sha256.update(chunk)
        return {
            "MD5": md5.hexdigest(),
            "SHA1": sha1.hexdigest(),
            "SHA256": sha256.hexdigest(),
        }
    except Exception:  # noqa: BLE001
        return {}


def _aspect_ratio(w: int, h: int) -> str:
    """Ширина/высота → '3:2', '4:3', '16:9'… (через НОД)."""
    if not w or not h:
        return "—"
    import math
    g = math.gcd(int(w), int(h))
    if g == 0:
        return "—"
    return f"{w // g}:{h // g}"


def _parse_gps(gps: dict[str, str]) -> tuple[Optional[dict], list[str], Optional[dict]]:
    """Парсит GPS-теги exifread."""
    text: list[str] = []
    lat = _coord_from_tags(gps, "GPS GPSLatitude", "GPS GPSLatitudeRef", "N", 1.0)
    lng = _coord_from_tags(gps, "GPS GPSLongitude", "GPS GPSLongitudeRef", "E", 1.0)
    altitude = _gps_alt_v(gps.get("GPS GPSAltitude", ""))

    result: dict = {}
    if lat is not None:
        result["lat"] = lat
        text.append(f"Широта: {lat:.7f}")
    if lng is not None:
        result["lng"] = lng
        text.append(f"Долгота: {lng:.7f}")
    if altitude is not None:
        ref = -1.0 if gps.get("GPS GPSAltitudeRef", "0").strip() == "1" else 1.0
        result["alt"] = altitude * ref
        text.append(f"Высота: {altitude:.1f} м")
    if gps.get("GPS GPSDateStamp"):
        result["date"] = gps["GPS GPSDateStamp"]
        text.append(f"Дата GPS: {gps['GPS GPSDateStamp']}")
    if gps.get("GPS GPSTimeStamp"):
        result["time"] = gps["GPS GPSTimeStamp"]
        text.append(f"Время GPS: {gps['GPS GPSTimeStamp']}")
    if gps.get("GPS GPSSpeed"):
        speed = _parse_rational_decimal(gps["GPS GPSSpeed"])
        if speed is not None:
            ref = gps.get("GPS GPSSpeedRef", "").strip()
            unit = {"K": "км/ч", "M": "миль/ч", "N": "узлы"}.get(ref, "")
            result["speed"] = speed
            text.append(f"Скорость: {speed:g} {unit}".rstrip())
    if gps.get("GPS GPSImgDirection"):
        heading = _parse_rational_decimal(gps["GPS GPSImgDirection"])
        if heading is not None:
            ref = gps.get("GPS GPSImgDirectionRef", "").strip()
            result["heading"] = heading
            text.append(f"Направление съёмки: {heading:.0f}° ({'истинное' if ref == 'T' else 'магнитное'})")
    if gps.get("GPS GPSHPositioningError"):
        err = _parse_rational_decimal(gps["GPS GPSHPositioningError"])
        if err is not None:
            result["gps_error"] = err
            text.append(f"Точность GPS: ±{err:g} м")
    if gps.get("GPS GPSProcessingMethod"):
        method = str(gps["GPS GPSProcessingMethod"]).replace("\x00", "").strip()
        method = method.removeprefix("ASCII").strip()
        if method and not method.startswith("[") and not method.isdigit():
            result["method"] = method
            text.append(f"Метод геопозиции: {method}")
    maps = build_maps_link(result["lat"], result["lng"]) if "lat" in result and "lng" in result else None
    return (result, text, maps) if result else (None, [], None)


def _coord_from_tags(gps: dict, value_key: str, ref_key: str, positive_ref: str, sign_base: float) -> Optional[float]:
    raw = gps.get(value_key, "")
    coord = _parse_rational_decimal(raw)
    if coord is None:
        return None
    ref = gps.get(ref_key, "").strip()
    if ref and ref.upper()[0:1] != positive_ref:
        coord *= -1.0
    return coord


def _parse_rational_decimal(raw: str) -> Optional[float]:
    """'[53, 53, 60]' или '[27, 34, 3/25]' → десятичные градусы float.

    exifread отдаёт координаты как список: целые числа (знаменатель = 1) пишутся
    без дроби — '[53, 53, 60]', остальные как '3/25'. Разбираем оба случая.
    """
    if not raw:
        return None
    import re
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1]
        parts = [p.strip() for p in inner.split(",") if p.strip()]
        values: list[float] = []
        for part in parts:
            m = re.fullmatch(r"(\d+)\s*/\s*(\d+)", part)
            if m:
                den = float(m.group(2))
                if den == 0:
                    return None
                values.append(float(m.group(1)) / den)
            elif re.fullmatch(r"\d+", part):
                values.append(float(part))
            else:
                return None
        if len(values) == 1:
            return values[0]
        if len(values) >= 3:
            deg, minute, sec = values[0], values[1], values[2]
            return deg + minute / 60.0 + sec / 3600.0
        return None

    m = re.findall(r"([\d]+)/([\d]+)", raw)
    if not m:
        try:
            return float(raw)
        except ValueError:
            return None

    def _ratio(num: str, den: str) -> Optional[float]:
        d = float(den)
        if d == 0.0:
            return None
        return float(num) / d

    if len(m) < 3:
        if len(m) == 1:
            return _ratio(m[0][0], m[0][1])
        return None
    deg = _ratio(m[0][0], m[0][1])
    minute = _ratio(m[1][0], m[1][1])
    sec = _ratio(m[2][0], m[2][1])
    if deg is None or minute is None or sec is None:
        return None
    return deg + minute / 60.0 + sec / 3600.0


def _gps_alt_v(raw: str) -> Optional[float]:
    import re
    m = re.findall(r"([\d]+)/([\d]+)", raw)
    if m:
        d = float(m[0][1])
        if d == 0.0:
            return None
        return float(m[0][0]) / d
    try:
        return float(raw)
    except ValueError:
        return None


def reverse_geocode(lat: float, lng: float) -> dict:
    """Обратный геокодинг через Nominatim (OpenStreetMap). Без ключа.

    Возвращает {address: str, label: str, parts: dict} — address — полная строка
    OSM, label — аккуратно составленный адрес, parts — разбивка по полям.
    """
    from geopy.geocoders import Nominatim
    locator = Nominatim(user_agent="probivbot-osint")
    location = locator.reverse(
        query=(lat, lng),
        language="ru",
        timeout=15,
    )
    if location is None:
        return {}
    raw = location.raw or {}
    address = raw.get("address") or {}
    parts = {k: str(v) for k, v in address.items() if v}
    return {
        "address": location.address,
        "label": compose_address(parts),
        "parts": parts,
        "raw": raw,
    }


def compose_address(parts: dict[str, str]) -> str:
    """Собирает читаемый адрес из полей address Nominatim/OSM."""
    if not parts:
        return ""
    names = {
        "region": "область",
        "state": "штат",
        "province": "провинция",
        "county": "район",
        "district": "округ",
        "city": "город",
        "town": "посёлок",
        "village": "деревня",
        "suburb": "район",
        "neighbourhood": "микрорайон",
        "road": "ул.",
        "pedestrian": "пешеходная",
        "house_number": "д.",
        "building": "здание",
        "postcode": "индекс",
        "country": "страна",
    }
    used = {}
    for key, ru in names.items():
        if key in parts and parts[key]:
            used[key] = f"{ru} {parts[key]}"

    order = ("country", "state", "region", "county", "district", "city",
             "town", "village", "suburb", "neighbourhood",
             "road", "pedestrian", "house_number", "building", "postcode")
    ordered = [used[k] for k in order if k in used]

    # всё, что не распознали, добавляем в конец
    unknown = [p for k, p in parts.items() if k not in used]
    return ", ".join(ordered + unknown)


# ----------------------------------------------------------------------------
# Русская «витрина» EXIF: нечитаемые английские теги → понятные строки
# ----------------------------------------------------------------------------

_EXIF_RU = {
    # Image
    "Software": "ПО",
    "DateTime": "Дата изменения",
    "Orientation": "Ориентация",
    "ImageDescription": "Описание",
    "Artist": "Автор",
    "Copyright": "Авторские права",
    "XResolution": "Разрешение X",
    "YResolution": "Разрешение Y",
    "ResolutionUnit": "Единицы разрешения",
    "ImageWidth": "Ширина изображения",
    "ImageLength": "Высота изображения",
    "BitsPerSample": "Бит на сэмпл",
    "PhotometricInterpretation": "Фотометрическая интерпретация",
    "SamplesPerPixel": "Сэмплов на пиксель",
    "RowsPerStrip": "Строк в полосе",
    "StripByteCounts": "Байт в полосе",
    "StripOffsets": "Смещение полосы",
    "PlanarConfiguration": "Планарная конфигурация",
    "WhitePoint": "Белая точка",
    "PrimaryChromaticities": "Основные хроматические координаты",
    "YCbCrCoefficients": "Коэффициенты YCbCr",
    "YCbCrSubSampling": "Субдискретизация YCbCr",
    "YCbCrPositioning": "Позиция YCbCr",
    "ReferenceBlackWhite": "Чёрно-белая ссылка",
    "TransferFunction": "Передаточная функция",
    "RelatedSoundFile": "Связанный звуковой файл",
    "ExifOffset": "Смещение EXIF",
    "GPSInfo": "Указатель GPS",
    "ImageHistory": "История изображения",
    "UniqueCameraModel": "Уникальная модель камеры",
    "CameraSerialNumber": "Серийный номер камеры",
    "InterColorProfile": "Цветовой профиль",
    # EXIF
    "ExposureTime": "Выдержка",
    "FNumber": "Диафрагма",
    "ISOSpeedRatings": "ISO",
    "ISO": "ISO",
    "SensitivityType": "Тип ISO",
    "RecommendedExposureIndex": "Рекомендуемое ISO",
    "FocalLength": "Фокусное расстояние",
    "FocalLengthIn35mmFilm": "Фокусное (35 мм)",
    "MaxApertureValue": "Макс. диафрагма",
    "ApertureValue": "Диафрагма (APEX)",
    "ShutterSpeedValue": "Выдержка (APEX)",
    "Flash": "Вспышка",
    "WhiteBalance": "Баланс белого",
    "LensModel": "Объектив",
    "LensMake": "Объектив (бренд)",
    "LensSpecification": "Объектив (характеристики)",
    "LensSerialNumber": "Объектив (серийный №)",
    "DateTimeOriginal": "Дата съёмки",
    "DateTimeDigitized": "Дата оцифровки",
    "OffsetTimeOriginal": "Сдвиг часового пояса",
    "SubSecTimeOriginal": "Мс. (оригинал)",
    "SubSecTimeDigitized": "Мс. (оцифровка)",
    "SubSecTime": "Мс. (файл)",
    "ExposureProgram": "Режим экспозиции",
    "ExposureBiasValue": "Экспокоррекция",
    "ExposureMode": "Режим выдержки",
    "MeteringMode": "Замер экспозиции",
    "DigitalZoomRatio": "Цифровой зум",
    "ColorSpace": "Цветовое пространство",
    "SceneCaptureType": "Тип сцены",
    "SceneType": "Тип сцены (EXIF)",
    "Contrast": "Контраст",
    "Sharpness": "Резкость",
    "Saturation": "Насыщенность",
    "GainControl": "Усиление",
    "SensingMethod": "Тип сенсора",
    "CustomRendered": "Обработка",
    "LightSource": "Источник света",
    "SubjectDistance": "Дистанция до объекта",
    "SubjectDistanceRange": "Дистанция (диапазон)",
    "BrightnessValue": "Яркость",
    "PixelXDimension": "Ширина кадра (EXIF)",
    "PixelYDimension": "Высота кадра (EXIF)",
    "ExifImageWidth": "Ширина кадра (EXIF)",
    "ExifImageHeight": "Высота кадра (EXIF)",
    "ImageUniqueID": "Уникальный ID",
    "UserComment": "Комментарий (EXIF)",
    "FileSource": "Источник файла",
    "FlashPixVersion": "FlashPix",
    "ExifVersion": "Версия EXIF",
    "ComponentsConfiguration": "Компоненты изображения",
    "CompressedBitsPerPixel": "Бит на пиксель (сжатие)",
    "SpectralSensitivity": "Спектральная чувствительность",
    "FlashEnergy": "Энергия вспышки",
    "FocalPlaneXResolution": "Разрешение фокальной плоскости X",
    "FocalPlaneYResolution": "Разрешение фокальной плоскости Y",
    "FocalPlaneResolutionUnit": "Единицы фокальной плоскости",
    "SubjectLocation": "Расположение объекта",
    "SubjectArea": "Область объекта",
    "ExposureIndex": "Индекс экспозиции",
    "OECF": "OECF",
    "CFAPattern": "Шаблон CFA",
    "DeviceSettingDescription": "Настройки устройства",
    "InteroperabilityOffset": "Смещение Interop",
    "MakerNote": "Заметки производителя",
    "CameraOwnerName": "Владелец камеры",
    "BodySerialNumber": "Серийный № корпуса",
    # GPS
    "GPSLatitude": "Широта (тег)",
    "GPSLatitudeRef": "Широта (полушарие)",
    "GPSLongitude": "Долгота (тег)",
    "GPSLongitudeRef": "Долгота (полушарие)",
    "GPSAltitude": "Высота",
    "GPSAltitudeRef": "Высота (точка отсчёта)",
    "GPSSpeed": "Скорость",
    "GPSSpeedRef": "Скорость (ед.)",
    "GPSImgDirection": "Направление съёмки",
    "GPSImgDirectionRef": "Направление (ед.)",
    "GPSHPositioningError": "Точность GPS",
    "GPSProcessingMethod": "Метод геопозиции",
    "GPSVersionID": "Версия GPS",
    "GPSTimeStamp": "Время GPS (тег)",
    "GPSDateStamp": "Дата GPS (тег)",
    "GPSSatellites": "Спутники",
    "GPSStatus": "Статус GPS",
    "GPSMeasureMode": "Режим измерения",
    "GPSDOP": "Точность (DOP)",
    "GPSTrack": "Направление движения",
    "GPSTrackRef": "Движение (ед.)",
    "GPSMapDatum": "Датум карты",
    "GPSDestLatitude": "Широта назначения",
    "GPSDestLatitudeRef": "Широта назначения (полушарие)",
    "GPSDestLongitude": "Долгота назначения",
    "GPSDestLongitudeRef": "Долгота назначения (полушарие)",
    "GPSDestBearing": "Азимут назначения",
    "GPSDestBearingRef": "Азимут (ед.)",
    "GPSDestDistance": "Расстояние до цели",
    "GPSDestDistanceRef": "Расстояние (ед.)",
    "GPSAreaInformation": "Информация об области",
    "GPSDifferential": "Дифференциальная коррекция",
    # Thumbnail
    "Compression": "Сжатие",
    "ThumbnailLength": "Размер миниатюры",
    "ThumbnailOffset": "Смещение миниатюры",
    "ThumbnailJPEGInterchangeFormat": "Формат миниатюры (JPEG)",
    "ThumbnailJPEGInterchangeFormatLength": "Размер миниатюры (JPEG)",
    "ThumbnailImage": "Миниатюра",
    "ThumbnailImageWidth": "Ширина миниатюры",
    "ThumbnailImageHeight": "Высота миниатюры",
    # Interop
    "InteroperabilityIndex": "Индекс совместимости",
    "InteroperabilityVersion": "Версия совместимости",
    "RelatedImageWidth": "Ширина связанного изображения",
    "RelatedImageHeight": "Высота связанного изображения",
}

_CAMERA_ORDER = [
    "DateTimeOriginal", "DateTimeDigitized", "OffsetTimeOriginal",
    "ExposureTime", "FNumber", "ISOSpeedRatings", "SensitivityType",
    "RecommendedExposureIndex", "FocalLength", "FocalLengthIn35mmFilm",
    "Flash", "ExposureProgram", "ExposureMode", "ExposureBiasValue",
    "MeteringMode", "WhiteBalance", "LensModel", "LensMake",
    "LensSpecification", "LensSerialNumber", "DigitalZoomRatio",
    "SceneCaptureType", "ColorSpace", "Contrast", "Sharpness", "Saturation",
    "GainControl", "CustomRendered", "SensingMethod", "LightSource",
    "SubjectDistance", "SubjectDistanceRange", "MaxApertureValue",
    "BrightnessValue", "Orientation", "Software", "ImageDescription",
    "Artist", "Copyright",
]

_EXPOSURE_PROGRAM = {
    "0": "Авто", "1": "Ручной", "2": "Программный авто", "3": "Приоритет выдержки",
    "4": "Приоритет диафрагмы", "5": "Творческий", "6": "Пейзаж",
    "7": "Портрет", "8": "Ночной",
}

_METERING = {
    "0": "Неизвестно", "1": "Средне-взвешенный", "2": "Центрально-взвешенный",
    "3": "Точечный", "5": "Матричный", "6": "Частичный", "255": "Другое",
}

_LIGHT_SOURCE = {
    "0": "Неизвестно", "1": "Дневной свет", "2": "Флуоресцентный",
    "3": "Лампа накаливания", "9": "Хорошая погода", "10": "Облачно",
    "11": "Тень", "12": "Дневной флуоресцентный",
    "13": "Холодный белый флуоресцентный", "14": "Белый флуоресцентный",
    "17": "Стандартный свет A", "21": "D65", "22": "D75", "23": "D50",
    "255": "Другое",
}

_ORIENTATION = {
    "1": "Обычная", "3": "Повёрнуто на 180°", "6": "Повёрнуто вправо (90°)",
    "8": "Повёрнуто влево (90°)",
}

_EXPOSURE_MODE = {"0": "Авто", "1": "Ручной", "2": "Брекетинг"}
_WHITE_BALANCE = {"0": "Авто", "1": "Ручной"}
_SCENE = {"0": "Стандарт", "1": "Пейзаж", "2": "Портрет", "3": "Ночной"}
_COLOR_SPACE = {"1": "sRGB", "2": "Adobe RGB", "65535": "Не калиброван"}
_CONTRAST = {"0": "Нормальный", "1": "Мягкий", "2": "Усиленный"}
_SHARPNESS = {"0": "Нормальная", "1": "Мягкая", "2": "Усиленная"}
_SATURATION = {"0": "Нормальная", "1": "Пониженная", "2": "Повышенная"}
_SENSING = {"2": "Однокристальный сенсор", "3": "Двухкристальный", "5": "Трёхкристальный"}
_FILE_SOURCE = {"3": "Цифровая камера", "1": "Фильм-сканер"}


def _to_float(value: str) -> Optional[float]:
    """'28/10' или '28.0' → float. Безопасно для нулевых знаменателей."""
    if not value:
        return None
    import re
    m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*/\s*(-?\d+(?:\.\d+)?)\s*", value)
    if m:
        num, den = float(m.group(1)), float(m.group(2))
        if den == 0.0:
            return None
        return num / den
    try:
        return float(value)
    except ValueError:
        return None


def _fmt_flash(value: str) -> str:
    f = _to_float(value)
    if f is None:
        return value
    bits = int(f)
    out = "Сработала" if bits & 0x1 else "Не сработала"
    if bits & 0x40:
        out += ", обязательная"
    if bits & 0x8:
        out += ", авто"
    if bits & 0x10:
        out += ", строб"
    return out


def _fmt_exif_value(key: str, value: str) -> str:
    """Приводит значение EXIF-тега к читаемому виду с единицами."""
    v = value.strip()
    if key in ("ExposureTime",):
        f = _to_float(v)
        if f is not None:
            if f >= 1:
                return f"{f:g} с"
            if f > 0:
                den = round(1 / f)
                if abs(1 / den - f) < 0.02:
                    return f"1/{den} с"
                return f"{f:g} с"
    if key in ("FNumber", "MaxApertureValue"):
        f = _to_float(v)
        if f is not None:
            return f"f/{f:g}"
    if key in ("FocalLength", "FocalLengthIn35mmFilm"):
        f = _to_float(v)
        if f is not None:
            return f"{f:g} мм"
    if key in ("ISOSpeedRatings", "ISO"):
        f = _to_float(v)
        if f is not None:
            return f"{f:g}"
    if key == "ExposureBiasValue":
        f = _to_float(v)
        if f is not None:
            return f"{f:+g} EV"
    if key == "DigitalZoomRatio":
        f = _to_float(v)
        if f is not None:
            return f"{f:g}×"
    if key == "BrightnessValue":
        f = _to_float(v)
        if f is not None:
            return f"{f:g} EV"
    if key == "SubjectDistance":
        f = _to_float(v)
        if f is not None:
            return f"{f:g} м"
    if key == "ShutterSpeedValue":
        # APEX-выдержка: time = 1 / 2^value
        f = _to_float(v)
        if f is not None:
            t = 1.0 / (2.0 ** f)
            if t >= 1:
                return f"{t:g} с"
            if t > 0:
                den = round(1 / t)
                if abs(1 / den - t) < 0.02:
                    return f"1/{den} с"
                return f"{t:g} с"
    if key == "ApertureValue":
        # APEX-диафрагма: f-number = 2^(value/2)
        f = _to_float(v)
        if f is not None:
            return f"f/{2.0 ** (f / 2.0):g}"
    if key == "GainControl":
        return {
            "0": "Нет", "1": "Слабое", "2": "Среднее", "3": "Сильное",
            "4": "Слабое (вверх)", "5": "Сильное (вверх)",
        }.get(v, v)
    if key == "SubjectDistanceRange":
        return {"0": "Неизвестно", "1": "Макро", "2": "Близко", "3": "Далеко"}.get(v, v)
    if key == "SensitivityType":
        return {
            "0": "Неизвестно", "1": "Стандартный выход ISO", "2": "ISO",
            "3": "ISO (рекомендация)", "4": "ISO (REI)", "5": "ISO (SOS)",
            "6": "ISO (CIPA DC-007)",
        }.get(v, v)
    if key == "ResolutionUnit":
        return {"1": "Нет", "2": "дюйм", "3": "см"}.get(v, v)
    if key == "SceneType":
        return {"1": "Прямое фото"}.get(v, v)
    if key == "GPSSpeedRef":
        return {"K": "км/ч", "M": "миль/ч", "N": "узлы"}.get(v, v)
    if key in ("GPSImgDirectionRef", "GPSTrackRef", "GPSDestBearingRef"):
        return {"T": "истинный", "M": "магнитный"}.get(v, v)
    if key == "GPSDestDistanceRef":
        return {"K": "км", "M": "мили", "N": "морские мили"}.get(v, v)
    if key == "GPSAltitudeRef":
        return {"0": "над уровнем моря", "1": "ниже уровня моря"}.get(v, v)
    if key == "GPSStatus":
        return {"A": "в процессе", "V": "нет сигнала"}.get(v, v)
    if key == "GPSMeasureMode":
        return {"2": "2D", "3": "3D"}.get(v, v)
    if key == "GPSDifferential":
        return {"0": "без коррекции", "1": "с дифференциальной коррекцией"}.get(v, v)
    if key == "GPSTrack":
        f = _to_float(v)
        if f is not None:
            return f"{f:g}°"
    if key == "GPSHPositioningError":
        f = _to_float(v)
        if f is not None:
            return f"±{f:g} м"
    if key == "FlashPixVersion":
        return f"поддерживается ({v})" if v else v
    if key in ("Flash",):
        return _fmt_flash(v)
    if key == "WhiteBalance":
        return _WHITE_BALANCE.get(v, v)
    if key == "ExposureProgram":
        return _EXPOSURE_PROGRAM.get(v, v)
    if key == "ExposureMode":
        return _EXPOSURE_MODE.get(v, v)
    if key == "MeteringMode":
        return _METERING.get(v, v)
    if key == "SceneCaptureType":
        return _SCENE.get(v, v)
    if key == "ColorSpace":
        return _COLOR_SPACE.get(v, v)
    if key == "Orientation":
        return _ORIENTATION.get(v, v)
    if key == "Contrast":
        return _CONTRAST.get(v, v)
    if key == "Sharpness":
        return _SHARPNESS.get(v, v)
    if key == "Saturation":
        return _SATURATION.get(v, v)
    if key == "SensingMethod":
        return _SENSING.get(v, v)
    if key == "LightSource":
        return _LIGHT_SOURCE.get(v, v)
    if key == "CustomRendered":
        return {"0": "Обычная", "1": "Нестандартная"}.get(v, v)
    if key == "FileSource":
        return _FILE_SOURCE.get(v, v)
    return value


def _camera_fields(groups: dict[str, dict[str, str]]) -> list[tuple[str, str]]:
    """Собирает понятные параметры съёмки из сырых групп EXIF."""
    raw: dict[str, str] = {}
    for group in ("Image", "EXIF"):
        for tag, value in groups.get(group, {}).items():
            if tag in _EXIF_RU and tag not in raw:
                raw[tag] = value
    ordered = [t for t in _CAMERA_ORDER if t in raw]
    ordered += [t for t in raw if t not in _CAMERA_ORDER]
    return [(_EXIF_RU[t], _fmt_exif_value(t, raw[t])) for t in ordered]


def _ru_tag_name(tag: str) -> str:
    """Русское название тега: словарь + простой человекочитаемый fallback."""
    if tag in _EXIF_RU:
        return _EXIF_RU[tag]
    # generic: "ThumbnailJPEGInterchangeFormat" → "Формат миниатюры (JPEG)"
    # оставляем как есть, если словаря нет
    return tag


def _full_exif_lines(groups: dict[str, dict[str, str]]) -> list[str]:
    """Все EXIF-теги читаемыми строками (переведённые названия + значения)."""
    lines: list[str] = []
    add = lines.append
    for group, tags in groups.items():
        items: list[tuple[str, str]] = []
        for tag, value in tags.items():
            if tag in ("Make", "Model"):  # уже в «Устройстве съёмки»
                continue
            if not str(value).strip():
                continue
            label = _ru_tag_name(tag)
            items.append((label, _fmt_exif_value(tag, str(value))))
        if not items:
            continue
        add(f" — <b>{esc(_GROUP_RU.get(group, group))}</b>")
        for label, value in items:
            add(f"  │ {label}: <code>{esc(value)}</code>")
    return lines


def _human_size(size: float) -> str:
    size = float(size)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if size < 1024 or unit == "ТБ":
            return f"{int(size)} Б" if unit == "Б" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} ТБ"


def _raw_exif_value(report: PhotoReport, *names: str) -> Optional[str]:
    """Ищет значение тега по группе EXIF (Image/EXIF/Прочее) по имени."""
    for group in ("Image", "EXIF", "Прочее"):
        tags = report.groups.get(group, {})
        for name in names:
            if name in tags and str(tags[name]).strip():
                return str(tags[name]).strip()
    return None


def _software_os(value: str, make: str) -> str:
    """Software → читаемая строка «ПО / ОС» (iOS/Android распознаём)."""
    v = value.strip()
    if not v:
        return v
    low = v.lower()
    if make and make.lower() in ("apple", "iphone"):
        return f"iOS {v}"
    if low.startswith("android"):
        rest = v[len("android"):].strip()
        return f"Android {rest}" if rest else "Android"
    return v


def format_photo_report(report: PhotoReport, path: Path) -> str:
    """Собирает КОРОТКИЙ отчёт по изображению: геолокация, устройство, дата,
    разрешение, размер. Без дампа всех EXIF-тегов и хэшей — чтобы влезать
    в одно сообщение Telegram без ошибки «message is too long»."""
    lines: list[str] = []
    add = lines.append
    add("<b>🖼 ОТЧЁТ ПО ИЗОБРАЖЕНИЮ</b>")
    add(f"<blockquote>{esc(path.name)}</blockquote>")
    add("")

    # ---- GPS — самый важный блок, ставим первым ----
    if report.gps:
        add("<b>📍 Геолокация</b>")
        add("<blockquote>")
        for line in report.gps_text:
            add(f"{esc(line)}")
        add("</blockquote>")
        if report.maps:
            add(f"│ Google Maps: <a href='{report.maps['google']}'>открыть</a>")
            add(f"│ Яндекс Карты: <a href='{report.maps['yandex']}'>открыть</a>")
        if report.reverse and report.reverse.get("label"):
            add(f"│ Адрес: <blockquote>{esc(report.reverse['label'])}</blockquote>")
        elif report.reverse and report.reverse.get("address"):
            add(f"│ Адрес: <blockquote>{esc(report.reverse['address'])}</blockquote>")
        elif report.reverse and report.reverse.get("error"):
            add("│ Адрес: ⚠️ не определён (геокодер недоступен), точка на картах.")
        add("")
    else:
        add("📍 GPS: <b>нет координат</b> (Telegram сжимает «Фото» и вырезает GPS — "
            "отправляйте файл как <b>Документ</b>)")
        add("")

    # ---- Устройство съёмки и ПО ----
    if report.device:
        add("<b>📱 Устройство съёмки</b>")
        add(f"│ <blockquote>{esc(report.device['name'])}</blockquote>")
        if report.device.get("make"):
            add(f"│ Производитель: <code>{esc(report.device['make'])}</code>")
        if report.device.get("model"):
            add(f"│ Модель: <code>{esc(report.device['model'])}</code>")
        software = _raw_exif_value(report, "Software")
        if software:
            add(f"│ ПО / ОС: <code>{esc(_software_os(software, report.device.get('make')))}</code>")
        serial = _raw_exif_value(
            report, "CameraSerialNumber", "BodySerialNumber", "LensSerialNumber"
        )
        if serial:
            add(f"│ Серийный №: <code>{esc(serial)}</code>")
        add("")

    # ---- Изображение и дата ----
    add("<b>▫ Изображение</b>")
    w, h = report.image.get("Ширина"), report.image.get("Высота")
    if w and h:
        mp = report.image.get("Мегапиксели")
        mp_part = f" ({esc(report.image['Мегапиксели'])} Мп)" if mp is not None else ""
        add(f"│ Разрешение: <code>{esc(w)}×{esc(h)} px</code>{mp_part}")
    if report.image.get("Соотношение сторон") and report.image.get("Соотношение сторон") != "—":
        add(f"│ Соотношение сторон: <code>{esc(report.image['Соотношение сторон'])}</code>")
    if report.image.get("Формат"):
        add(f"│ Формат: <code>{esc(report.image['Формат'])}</code>")
    add("")

    # ---- Параметры съёмки (только ключевые: дата, выдержка, ISO…) ----
    cam = _camera_fields(report.groups)
    if cam:
        add("<b>📸 Параметры съёмки</b>")
        for label, value in cam[:8]:
            add(f"│ {label}: <code>{esc(value)}</code>")
        add("")

    # ---- Файл (без хэшей) ----
    add("<b>▫ Файл</b>")
    size_b = report.file.get("Размер (Б)")
    if isinstance(size_b, (int, float)):
        add(f"│ Размер: <code>{_human_size(size_b)}</code>")
    if report.file.get("Создан") and report.file.get("Создан") != "—":
        add(f"│ Создан: <code>{esc(report.file['Создан'])}</code>")
    if report.file.get("Модифицирован"):
        add(f"│ Изменён: <code>{esc(report.file['Модифицирован'])}</code>")
    add("")

    # ---- Пустой отчёт ----
    if report.raw_count == 0 and report.gps is None and report.device is None:
        add(
            "⚠️ <b>Метаданных не найдено.</b>\n"
            "Если вы прислали фото как «Фото» — Telegram сжал его и вырезал EXIF/GPS.\n"
            "Отправьте файл как <b>Документ</b> — бот вытащит максимум."
        )
        add("")
    add("⚡ Метаданные из открытых источников. Используйте только в законных целях.")
    return "\n".join(lines)