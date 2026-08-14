"""Тесты MP4/MOV-парсера и обратного геокодирования адресов — оффлайн.

Валидный MP4 собирается руками из атомов (ISO BMFF): ftyp + moov,
внутри moov — mvhd (версия 0), udta → meta (с 4-байтным префиксом версии)
→ hdlr + ilst с тегами ©mak, ©mod, ©day, ©xyz (GPS).
"""
from __future__ import annotations

import datetime
import struct

import pytest

from bot.exceptions import ServiceError
from bot.services.photo_service import compose_address
from bot.services.video_service import (
    extract_video,
    format_video_report,
    parse_xyz,
)

MAC_EPOCH = datetime.datetime(1904, 1, 1)


def _atom(typ: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + typ + payload


def _data_item(text: str) -> bytes:
    """Атом 'data' внутри элемента ilst: type_code(21=UTF-8) + locale(0) + текст."""
    return _atom(b"data", struct.pack(">II", 21, 0) + text.encode("utf-8"))


def _ilst_item(typ: bytes, text: str) -> bytes:
    return _atom(typ, _data_item(text))


def _build_gps_mp4(creation: datetime.datetime | None = None,
                   xyz: str = "+55.7558+037.6173/") -> bytes:
    """Собирает минимальный валидный MP4 с GPS-метаданными."""
    creation = creation or datetime.datetime(2024, 6, 1, 12, 0, 0)
    epoch = int((creation - MAC_EPOCH).total_seconds())

    # mvhd v0: ver+flags(4) creation(4) modification(4) timescale(4) duration(4)
    mvhd = _atom(
        b"mvhd",
        b"\x00\x00\x00\x00"
        + struct.pack(">I", epoch)
        + struct.pack(">I", epoch)
        + struct.pack(">II", 1000, 10000),
    )

    ilst = _atom(
        b"ilst",
        _ilst_item(b"\xa9mak", "Apple")
        + _ilst_item(b"\xa9mod", "iPhone 15 Pro")
        + _ilst_item(b"\xa9day", "2024-06-01T12:00:00+0300")
        + _ilst_item(b"\xa9xyz", xyz),
    )
    hdlr = _atom(b"hdlr", b"\x00\x00\x00\x00\x00\x00\x00\x00video\x00\x00")
    meta = _atom(b"meta", b"\x00\x00\x00\x00" + hdlr + ilst)
    udta = _atom(b"udta", meta)
    moov = _atom(b"moov", mvhd + udta)

    ftyp = _atom(b"ftyp", b"isom\x00\x00\x02\x00isomiso2")
    return ftyp + moov


def test_parse_xyz_ok():
    assert parse_xyz("+55.7558+037.6173/") == pytest.approx((55.7558, 37.6173))
    assert parse_xyz("+55.7558+037.6173") == pytest.approx((55.7558, 37.6173))
    assert parse_xyz("-33.8688-151.2093/") == pytest.approx((-33.8688, -151.2093))


def test_parse_xyz_bad():
    assert parse_xyz("") is None
    assert parse_xyz("garbage") is None
    assert parse_xyz("+200.0+037.0/") is None   # широта вне диапазона
    assert parse_xyz("+55.7") is None           # одна координата


def test_extract_video_gps(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(_build_gps_mp4())

    report = extract_video(path)

    assert report.file["Имя"] == "clip.mp4"
    assert report.gps is not None
    assert report.gps["lat"] == pytest.approx(55.7558)
    assert report.gps["lng"] == pytest.approx(37.6173)
    assert report.maps and "google" in report.maps
    assert "Широта" in report.gps_text[0]

    assert report.metadata.get("Производитель") == "Apple"
    assert report.metadata.get("Модель") == "iPhone 15 Pro"
    assert report.metadata.get("Дата создания") == "2024-06-01T12:00:00+0300"
    assert report.container.get("Дата создания (mvhd)") == "2024-06-01 12:00:00"
    assert "10.0" in report.container.get("Длительность (сек)", "")


def test_format_video_report(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(_build_gps_mp4())
    report = extract_video(path)
    text = format_video_report(report, path)

    assert "<b>🎬 ОТЧЁТ ПО ВИДЕО</b>" in text
    assert "GPS-координаты" in text
    assert "Метаданные (3 шт.)" in text
    assert "Google Maps" in text
    assert "yandex.ru" in text


def test_extract_video_no_gps(tmp_path):
    mp4 = _build_gps_mp4(xyz="")
    path = tmp_path / "plain.mp4"
    path.write_bytes(mp4)
    report = extract_video(path)
    assert report.gps is None
    assert report.metadata.get("Производитель") == "Apple"
    text = format_video_report(report, path)
    assert "Метаданные (3 шт.)" in text


def test_not_mp4(tmp_path):
    path = tmp_path / "fake.mp4"
    path.write_bytes(b"PK\x03\x04 not a mp4 at all")
    with pytest.raises(ServiceError):
        extract_video(path)


def test_missing_file(tmp_path):
    with pytest.raises(ServiceError):
        extract_video(tmp_path / "nope.mp4")


def test_compose_address_order():
    parts = {
        "country": "Россия",
        "state": "Москва",
        "city": "Москва",
        "road": "Тверская",
        "house_number": "12",
        "postcode": "125009",
    }
    addr = compose_address(parts)
    assert "Россия" in addr
    assert "Тверская" in addr
    assert "д. 12" in addr
    assert addr.index("Россия") < addr.index("Тверская")


def test_compose_address_unknown_fields():
    addr = compose_address({"something_custom": "value1", "road": "Ленина"})
    assert "Ленина" in addr
    assert "value1" in addr


def test_compose_address_empty():
    assert compose_address({}) == ""