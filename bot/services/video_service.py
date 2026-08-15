"""
Сервис анализа видеофайлов (MP4/MOV) на максимальное количество метаданных.

Без ffprobe — чистый Python-парсер MP4-атомов (ISO BMFF / QuickTime):
  * moov/mvhd, mdia/mdhd — даты создания, таймскейл, длительность;
  * udta/meta/ilst      — метаданные iTunes/QuickTime: ©mak, ©mod, ©day,
                          ©xyz (GPS!), ©nam, ©cmt, ©swr, ©too и т.д.

GPS из ©xyz (iPhone-формат "+55.7558+037.6173/") конвертируется в десятичные
градусы → ссылки на карты → точный адрес через Nominatim (OSM).
"""
from __future__ import annotations

import datetime
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from bot.exceptions import ServiceError
from bot.services.devices import recognize_device
from bot.services.photo_service import build_maps_link, reverse_geocode
from bot.utils.formatting import esc

# атомы-контейнеры, внутрь которых нужно заходить
_CONTAINERS = {
    b"moov", b"udta", b"trak", b"mdia", b"minf", b"stbl", b"edts",
    b"dinf", b"mvex", b"moof", b"traf", b"mfra", b"tref", b"meta",
}

# атомы метаданных ilst, которые нас интересуют
_ILST_KEYS = {
    b"\xa9mak": "Производитель",
    b"\xa9mod": "Модель",
    b"\xa9day": "Дата создания",
    b"\xa9nam": "Название",
    b"\xa9alb": "Альбом",
    b"\xa9ART": "Артист",
    b"\xa9aART": "Композитор",
    b"\xa9gen": "Жанр",
    b"\xa9cmt": "Комментарий",
    b"\xa9des": "Описание",
    b"\xa9swr": "ПО записи",
    b"\xa9too": "Кодировщик",
    b"\xa9cpy": "Авторские права",
    b"\xa9wrt": "Автор",
    b"\xa9xyz": "__GPS__",
}


@dataclass
class VideoReport:
    """Готовый отчёт по видеофайлу."""

    file: dict
    container: dict
    metadata: dict[str, str]
    gps: Optional[dict]
    maps: Optional[dict]
    reverse: dict
    gps_text: list[str]
    device: Optional[dict]


class _Atoms:
    """Поток по атомам внутри буфера."""

    __slots__ = ("buf", "off", "end")

    def __init__(self, buf: bytes, off: int, end: int):
        self.buf = buf
        self.off = off
        self.end = end

    def __iter__(self):
        return self

    def __next__(self):
        buf, off, end = self.buf, self.off, self.end
        if off + 8 > end:
            raise StopIteration
        size = int.from_bytes(buf[off:off + 4], "big")
        typ = buf[off + 4:off + 8]
        hdr = 8
        if size == 1:  # 64-bit extended size
            if off + 16 > end:
                raise StopIteration
            size = int.from_bytes(buf[off + 8:off + 16], "big")
            hdr = 16
        elif size == 0:  # размер до конца файла
            size = end - off
        if size < hdr or off + size > end:
            raise StopIteration
        self.off = off + size
        return typ, off + hdr, off + hdr + len(buf[off + hdr:off + size])  # noqa: B023


def _parse_mp4(raw: bytes, data: dict) -> None:
    if len(raw) < 8 or raw[4:8] != b"ftyp":
        raise ServiceError("Файл не похож на MP4/MOV (нет заголовка ftyp)")

    def walk(off: int, end: int, inside_ilst: bool = False) -> None:
        while off + 8 <= end:
            size = int.from_bytes(raw[off:off + 4], "big")
            typ = raw[off + 4:off + 8]
            hdr = 8
            if size == 1:
                if off + 16 > end:
                    return
                size = int.from_bytes(raw[off + 8:off + 16], "big")
                hdr = 16
            elif size == 0:
                size = end - off
            if size < hdr or off + size > end:
                return
            payload_start = off + hdr
            payload_end = off + size

            if typ in _CONTAINERS:
                child_start = payload_start
                # у атома «meta» сперва идут 4 байта версии
                if typ == b"meta" and raw[payload_start:payload_start + 4] == b"\x00\x00\x00\x00":
                    child_start = payload_start + 4
                walk(child_start, payload_end, inside_ilst)
            elif typ in (b"mvhd", b"mdhd"):
                _parse_time_header(raw[payload_start:payload_end], data, typ)
            elif typ == b"hdlr":
                _parse_hdlr(raw[payload_start:payload_end], data)
            elif typ == b"ilst":
                _parse_ilst(raw[payload_start:payload_end], data)
            elif typ in _ILST_KEYS:
                _parse_ilst_item(typ, raw[payload_start:payload_end], data)

            off += size

    walk(0, len(raw))


def _parse_time_header(payload: bytes, data: dict, atom: bytes) -> None:
    if len(payload) < 16:
        return
    version = payload[0]
    base = 4  # version + flags
    if version == 1:
        if len(payload) < base + 24:
            return
        creation = struct.unpack(">Q", payload[base:base + 8])[0]
        timescale = struct.unpack(">I", payload[base + 16:base + 20])[0]
        duration = struct.unpack(">Q", payload[base + 24:base + 32])[0] if len(payload) >= base + 32 else 0
    else:
        if len(payload) < base + 12:
            return
        creation = struct.unpack(">I", payload[base:base + 4])[0]
        timescale = struct.unpack(">I", payload[base + 8:base + 12])[0]
        duration = struct.unpack(">I", payload[base + 12:base + 16])[0] if len(payload) >= base + 16 else 0

    key = "mvhd" if atom == b"mvhd" else "mdhd"
    try:
        dt = datetime.datetime(1904, 1, 1) + datetime.timedelta(seconds=creation)
        data[f"{key}.creation"] = dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OverflowError):
        pass
    if timescale:
        data[f"{key}.duration_s"] = round(duration / timescale, 2)


def _parse_hdlr(payload: bytes, data: dict) -> None:
    if len(payload) < 12:
        return
    handler = payload[8:12]
    names = {
        b"vide": "видеодорожка",
        b"soun": "аудиодорожка",
        b"meta": "метаданные",
        b"text": "текст",
    }
    data.setdefault("tracks", []).append(names.get(handler, handler.decode(errors="replace")))


def _parse_ilst(payload: bytes, data: dict) -> None:
    _walk_ilst(payload, 0, len(payload), data)


def _walk_ilst(payload: bytes, off: int, end: int, data: dict) -> None:
    while off + 8 <= end:
        size = int.from_bytes(payload[off:off + 4], "big")
        typ = payload[off + 4:off + 8]
        if size < 8 or off + size > end:
            return
        _parse_ilst_item(typ, payload[off + 8:off + size], data)
        off += size


def _parse_ilst_item(typ: bytes, item_payload: bytes, data: dict) -> None:
    label = _ILST_KEYS.get(typ)
    if label is None:
        return
    value = _extract_text(item_payload)
    if value is None:
        return
    if label == "__GPS__":
        data["gps_raw"] = value
    else:
        data.setdefault("metadata", {})[label] = value


def _extract_text(item_payload: bytes) -> Optional[str]:
    """Достаёт текст из item: обычно внутри лежит атом 'data' с текстом."""
    if len(item_payload) >= 8 and item_payload[4:8] == b"data":
        # size(4) + 'data'(4) + type_code(4) + locale(4) = 16 байт заголовка
        body = item_payload[16:]
    else:
        body = item_payload
    return _decode(body)


def _decode(body: bytes) -> Optional[str]:
    text = body.rstrip(b"\x00").strip()
    if not text:
        return None
    try:
        return text.decode("utf-8", errors="replace").strip()
    except Exception:  # noqa: BLE001
        return None


_XYX_RE = re.compile(r"[+-]\d+(?:\.\d+)?")


def parse_xyz(raw: str) -> Optional[tuple[float, float]]:
    """Парсит GPS-строку QuickTime ("+55.7558+037.6173/") → (lat, lng)."""
    m = _XYX_RE.findall(raw)
    if len(m) < 2:
        return None
    try:
        lat, lng = float(m[0]), float(m[1])
    except ValueError:
        return None
    if -90 <= lat <= 90 and -180 <= lng <= 180:
        return lat, lng
    return None


def extract_video(path: Path) -> VideoReport:
    """Анализирует MP4/MOV и возвращает структурированный отчёт."""
    if not path.exists():
        raise ServiceError("Файл не найден на диске")

    size = path.stat().st_size
    file_info = {
        "Имя": path.name,
        "Размер (Б)": size,
        "Размер (МБ)": round(size / 1024 / 1024, 2),
    }

    data: dict = {}
    raw = path.read_bytes()
    try:
        _parse_mp4(raw, data)
    except ServiceError:
        raise

    container: dict = {}
    if "mvhd.creation" in data or "mdhd.creation" in data:
        container["Дата создания (mvhd)"] = data.get("mvhd.creation", "")
        container["Дата создания (mdhd)"] = data.get("mdhd.creation", "")
    if "mvhd.duration_s" in data or "mdhd.duration_s" in data:
        container["Длительность (сек)"] = str(
            data.get("mvhd.duration_s") or data.get("mdhd.duration_s")
        )
    if data.get("tracks"):
        container["Дорожки"] = ", ".join(data["tracks"])

    metadata = data.get("metadata", {})

    gps, gps_text, maps = None, [], None
    if data.get("gps_raw"):
        coords = parse_xyz(data["gps_raw"])
        if coords:
            lat, lng = coords
            gps = {"lat": lat, "lng": lng}
            gps_text = [f"Широта: {lat:.7f}", f"Долгота: {lng:.7f}"]
            maps = build_maps_link(lat, lng)

    reverse: dict = {}
    if gps:
        try:
            reverse = reverse_geocode(gps["lat"], gps["lng"])
        except Exception as exc:  # noqa: BLE001
            reverse = {"error": str(exc)}

    device = recognize_device(metadata.get("Производитель"), metadata.get("Модель"))

    return VideoReport(
        file=file_info,
        container=container,
        metadata=metadata,
        gps=gps,
        maps=maps,
        reverse=reverse,
        gps_text=gps_text,
        device=device,
    )


def format_video_report(report: VideoReport, path: Path) -> str:
    """Собирает текстовый отчёт по видео."""
    lines: list[str] = []
    add = lines.append
    add("<b>🎬 ОТЧЁТ ПО ВИДЕО</b>")
    add(f"<blockquote>{esc(str(path.name))}</blockquote>")
    add("")

    add("<b>▫ Файл</b>")
    for k, v in report.file.items():
        add(f"│ {str(k)}: <code>{str(v)}</code>")
    if report.container:
        add("<b>▫ Контейнер</b>")
        for k, v in report.container.items():
            add(f"│ {str(k)}: <code>{str(v)}</code>")
    add("")

    if report.device:
        add("<b>📱 Устройство съёмки</b>")
        add(f"│ Название: <blockquote>{str(report.device['name'])}</blockquote>")
        if report.device.get("make"):
            add(f"│ Производитель: <code>{str(report.device['make'])}</code>")
        if report.device.get("model"):
            add(f"│ Модель (тег): <code>{str(report.device['model'])}</code>")
        add("")

    if report.gps:
        add("<b>📍 GPS-координаты</b>")
        add("<blockquote>")
        for line in report.gps_text:
            add(esc(line))
        add("</blockquote>")
        if report.maps:
            add(f"│ Google Maps: <a href='{report.maps['google']}'>открыть</a>")
            add(f"│ Яндекс Карты: <a href='{report.maps['yandex']}'>открыть</a>")
        if report.reverse and report.reverse.get("label"):
            add(f"│ Адрес: <blockquote>{str(report.reverse['label'])}</blockquote>")
            if report.reverse.get("parts"):
                add("│ Детали: "
                    + ", ".join(f"{k}: {v}" for k, v in list(report.reverse["parts"].items())[:8]))
        elif report.reverse and report.reverse.get("address"):
            add(f"│ Адрес (OSM): <blockquote>{str(report.reverse['address'])}</blockquote>")
        elif report.reverse and report.reverse.get("error"):
            add("│ Адрес: ⚠️ не определён (геокодер недоступен). "
                "Точка показана на картах выше.")
        add("")

    add(f"<b>🔬 Метаданные ({len(report.metadata)} шт.)</b>")
    for k, v in report.metadata.items():
        add(f"│ {str(k)}: <code>{str(v)[:180]}</code>")
    if not report.metadata:
        add("│ (метаданных не найдено)")
    if not report.metadata and not report.gps:
        add("")
        add(
            "⚠️ Если вы отправляли видео как «Видео», Telegram мог пережать файл.\n"
            "Отправьте оригинал как <b>Документ</b> — тогда сохранятся теги "
            "(©mak/©mod/©day/©xyz-GPS)."
        )
    add("")
    add("⚡ Метаданные из открытых источников. Используйте только в законных целях.")
    return "\n".join(lines)