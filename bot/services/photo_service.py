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

# Интересные теги, которые не должны потеряться среди мусора
_PRIORITY_PREFIXES = ("Image ", "EXIF ", "GPS ", "MakerNote ", "Thumbnail ", "Interop ")


def _val(tag) -> str:
    if isinstance(tag, bytes):
        try:
            return tag.decode("utf-8", errors="replace").strip()
        except Exception:  # noqa: BLE001
            return repr(tag)
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
        "Модифицирован": _readable_time(path),
    }

    # ---- Pillow ----
    try:
        from PIL import Image
        with Image.open(path) as img:
            img_info = {
                "Формат": img.format or "?",
                "Ширина": img.width,
                "Высота": img.height,
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
    with path.open("rb") as f:
        tags = exifread.process_file(f, details=True, debug=False, strict=True)

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

    return PhotoReport(
        file=file_info,
        image=img_info,
        groups=groups,
        gps=gps,
        gps_text=gps_text,
        maps=maps,
        reverse=reverse,
        raw_count=raw_count,
    )


def _readable_time(path: Path) -> str:
    try:
        import datetime
        ts = path.stat().st_mtime
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:  # noqa: BLE001
        return "—"


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
    if len(m) < 3:
        if len(m) == 1:
            return float(m[0][0]) / float(m[0][1])
        return None
    deg = float(m[0][0]) / float(m[0][1])
    minute = float(m[1][0]) / float(m[1][1])
    sec = float(m[2][0]) / float(m[2][1])
    return deg + minute / 60.0 + sec / 3600.0


def _gps_alt_v(raw: str) -> Optional[float]:
    import re
    m = re.findall(r"([\d]+)/([\d]+)", raw)
    if m:
        return float(m[0][0]) / float(m[0][1])
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


def format_photo_report(report: PhotoReport, path: Path) -> str:
    """Собирает текстовый отчёт по изображению."""
    lines: list[str] = []
    add = lines.append
    add("<b>🖼 ОТЧЁТ ПО ИЗОБРАЖЕНИЮ</b>")
    add(f"└ <code>{str(path.name)}</code>")
    add("")

    add("<b>▫ Файл</b>")
    for k, v in report.file.items():
        add(f"│ {str(k)}: <code>{str(v)}</code>")
    add("<b>▫ Изображение</b>")
    for k, v in report.image.items():
        add(f"│ {str(k)}: <code>{str(v)}</code>")
    add("")

    if report.gps:
        add("<b>📍 GPS-координаты</b>")
        for line in report.gps_text:
            add(f"│ {str(line)}")
        if report.maps:
            add(f"│ Google Maps: <a href='{report.maps['google']}'>открыть</a>")
            add(f"│ Яндекс Карты: <a href='{report.maps['yandex']}'>открыть</a>")
        if report.reverse and report.reverse.get("label"):
            add(f"│ Адрес: <blockquote>{str(report.reverse['label'])}</blockquote>")
            if report.reverse.get("parts"):
                pts = report.reverse["parts"]
                add("│ Детали: "
                    + ", ".join(f"{k}: {v}" for k, v in list(pts.items())[:8]))
        elif report.reverse and report.reverse.get("address"):
            add(f"│ Адрес (OSM): <blockquote>{str(report.reverse['address'])}</blockquote>")
        elif report.reverse and report.reverse.get("error"):
            add("│ Адрес: ⚠️ не определён (геокодер недоступен). "
                "Точка показана на картах выше.")
        add("")

    total_tags = report.raw_count
    add(f"<b>🔬 EXIF-теги ({total_tags} шт.)</b>")
    for group, tags in report.groups.items():
        add(f" — <b>{str(group)}</b>")
        for tag, value in list(tags.items())[:40]:
            add(f"  │ {str(tag)}: <code>{str(value)[:180]}</code>")
        if len(tags) > 40:
            add(f"  │ … ещё {len(tags) - 40}")
    add("")
    if report.raw_count == 0 and report.gps is None:
        add(
            "⚠️ <b>Метаданных не найдено.</b>\n"
            "Если вы прислали фото как «Фото» — Telegram сжал его и вырезал EXIF/GPS.\n"
            "Отправьте файл как <b>Документ</b> — тогда бот вытащит максимум "
            "(модель камеры, дату, GPS-координаты, адрес)."
        )
        add("")
    add("⚡ Метаданные из открытых источников. Используйте только в законных целях.")
    return "\n".join(lines)