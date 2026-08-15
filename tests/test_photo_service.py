"""Тесты сервиса анализа изображений (EXIF/GPS) — оффлайн.

Примечание: Pillow умеет записывать в JPEG только «плоские» теги (Make,
Model, Software, DateTimeOriginal). GPS-IFD из Pillow в JPEG не переносится,
поэтому парсинг GPS тестируется напрямую на структуре тегов exifread.
"""
from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from bot.exceptions import ServiceError
from bot.services.photo_service import (
    _gps_alt_v,
    _parse_gps,
    _parse_rational_decimal,
    build_maps_link,
    extract_photo,
    format_photo_report,
)


def _make_jpeg_with_exif(path):
    """Создаёт JPEG с плоским EXIF (Make/Model/Software/DateTimeOriginal)."""
    img = Image.new("RGB", (640, 480), color=(10, 20, 30))
    ImageDraw.Draw(img).rectangle([10, 10, 100, 100], fill=(200, 100, 50))

    exif = img.getexif()
    exif[0x010F] = "TestCam123"           # Make
    exif[0x0110] = "Model-X"              # Model
    exif[0x0131] = "ProbivBotTest/1.0"    # Software
    exif[0x9003] = "2023:05:01 12:30:45"  # DateTimeOriginal

    img.save(path, format="JPEG", exif=exif.tobytes())


GPS_SAMPLE = {
    "GPS GPSLatitude": "[55/1, 45/1, 0/1]",
    "GPS GPSLatitudeRef": "N",
    "GPS GPSLongitude": "[37/1, 36/1, 0/1]",
    "GPS GPSLongitudeRef": "E",
    "GPS GPSAltitude": "[253/1]",
    "GPS GPSAltitudeRef": "0",
    "GPS GPSTimeStamp": "[12/1, 26/1, 34/1]",
    "GPS GPSDateStamp": "2023:05:01",
}


def test_rational_parse():
    assert _parse_rational_decimal("[55/1, 45/1, 0/1]") == pytest.approx(55.75)
    assert _parse_rational_decimal("37.6") == pytest.approx(37.6)
    assert _parse_rational_decimal("[1/1]") == pytest.approx(1.0)
    assert _parse_rational_decimal("") is None


def test_rational_parse_integer_format():
    """exifread отдаёт целые числа без '/' (знаменатель = 1): '[53, 53, 60]'."""
    assert _parse_rational_decimal("[53, 53, 60]") == pytest.approx(53.9)
    assert _parse_rational_decimal("[27, 34, 3/25]") == pytest.approx(27.5667)
    assert _parse_rational_decimal("[12, 26, 34]") == pytest.approx(12.44277778)


def test_parse_gps_tags_integer_format():
    """GPS без явных знаменателей — реальный вывод exifread из JPG-файла."""
    data = {
        "GPS GPSLatitude": "[53, 53, 60]",
        "GPS GPSLatitudeRef": "N",
        "GPS GPSLongitude": "[27, 34, 3/25]",
        "GPS GPSLongitudeRef": "E",
    }
    gps, text, maps = _parse_gps(data)
    assert gps is not None
    assert gps["lat"] == pytest.approx(53.9)
    assert gps["lng"] == pytest.approx(27.5667)
    assert maps and "google" in maps and "yandex" in maps
    assert any("Широта" in line for line in text)
    assert any("Долгота" in line for line in text)


def test_parse_gps_tags():
    gps, text, maps = _parse_gps(GPS_SAMPLE)
    assert gps is not None
    assert gps["lat"] == pytest.approx(55.75)
    assert gps["lng"] == pytest.approx(37.6)
    assert gps["alt"] == pytest.approx(253.0)
    assert gps["date"] == "2023:05:01"
    assert maps and "google" in maps
    assert any("Широта" in line for line in text)


def test_gps_south_west_ref():
    data = dict(GPS_SAMPLE)
    data["GPS GPSLatitudeRef"] = "S"
    data["GPS GPSLongitudeRef"] = "W"
    gps, _, _ = _parse_gps(data)
    assert gps["lat"] == pytest.approx(-55.75)
    assert gps["lng"] == pytest.approx(-37.6)


def test_rational_parse_zero_denominator():
    """Битые GPS-значения с нулевым знаменателем не должны ронять отчёт."""
    assert _parse_rational_decimal("3/0") is None
    assert _parse_rational_decimal("[53/1, 53/1, 60/0]") is None
    assert _parse_rational_decimal("[0/0, 1/1, 2/1]") is None
    assert _parse_rational_decimal("[5/2, 3/1, 0/0]") is None
    assert _gps_alt_v("1/0") is None
    assert _gps_alt_v("0/0") is None
    assert _gps_alt_v("253/1") == pytest.approx(253.0)


def test_parse_gps_zero_denominator_tags():
    """Весь GPS-парсер переживает битые теги (регрессия ZeroDivisionError)."""
    data = {
        "GPS GPSLatitude": "[55/1, 45/1, 0/1]",
        "GPS GPSLatitudeRef": "N",
        "GPS GPSLongitude": "[37/1, 36/1, 0/0]",
        "GPS GPSLongitudeRef": "E",
        "GPS GPSAltitude": "1/0",
    }
    gps, text, maps = _parse_gps(data)
    assert gps is not None
    assert gps["lat"] == pytest.approx(55.75)
    assert "lng" not in gps
    assert "alt" not in gps
    assert maps is None
    assert any("Широта" in line for line in text)


def test_parse_gps_extra_fields():
    """Скорость/направление/точность/метод попадают в GPS-отчёт."""
    data = {
        "GPS GPSLatitude": "[55/1, 45/1, 0/1]",
        "GPS GPSLatitudeRef": "N",
        "GPS GPSLongitude": "[37/1, 36/1, 0/1]",
        "GPS GPSLongitudeRef": "E",
        "GPS GPSAltitude": "[253/1]",
        "GPS GPSAltitudeRef": "0",
        "GPS GPSSpeed": "[18/1]",
        "GPS GPSSpeedRef": "K",
        "GPS GPSImgDirection": "[90/1]",
        "GPS GPSImgDirectionRef": "T",
        "GPS GPSHPositioningError": "[3/1]",
    }
    gps, text, _ = _parse_gps(data)
    assert gps["speed"] == pytest.approx(18.0)
    assert gps["heading"] == pytest.approx(90.0)
    assert gps["gps_error"] == pytest.approx(3.0)
    assert any("Скорость" in line and "км/ч" in line for line in text)
    assert any("Направление" in line for line in text)
    assert any("Точность GPS" in line for line in text)


def test_report_hashes_and_mp(tmp_path):
    """Хэши файла считаются в данных, но НЕ выводятся в текст (компактность)."""
    img_path = tmp_path / "full.jpg"
    _make_jpeg_with_exif(img_path)
    report = extract_photo(img_path)

    assert len(report.file["MD5"]) == 32
    assert len(report.file["SHA1"]) == 40
    assert len(report.file["SHA256"]) == 64
    assert report.image["Мегапиксели"] == pytest.approx(0.31)
    assert report.image["Соотношение сторон"] == "4:3"

    text = format_photo_report(report, img_path)
    assert "🔐 Хэши файла" not in text
    assert "MD5:" not in text
    assert "Мп" in text
    assert "Соотношение сторон" in text
    assert "Размер" in text
    assert len(text) < 4096


def test_maps_links():
    links = build_maps_link(55.75, 37.6)
    assert "55.75" in links["google"]
    assert links["yandex"].startswith("https://yandex.ru/maps/?pt=")


def test_extract_full_report(tmp_path):
    img_path = tmp_path / "photo.jpg"
    _make_jpeg_with_exif(img_path)

    report = extract_photo(img_path)

    assert report.file["Имя"] == "photo.jpg"
    assert report.file["Размер (Б)"] > 0
    assert report.image["Формат"] == "JPEG"
    assert report.image["Ширина"] == 640

    all_tags = {k: v for g in report.groups.values() for k, v in g.items()}
    assert any("DateTimeOriginal" in k and "2023" in v for k, v in all_tags.items())
    assert all_tags.get("Make") == "TestCam123"
    assert all_tags.get("Model") == "Model-X"
    assert all_tags.get("Software") == "ProbivBotTest/1.0"

    # GPS в этом JPEG нет — но отчёт всё равно собирается
    assert report.gps is None
    text = format_photo_report(report, img_path)
    assert "<b>🖼 ОТЧЁТ ПО ИЗОБРАЖЕНИЮ</b>" in text
    assert f"<blockquote>photo.jpg</blockquote>" in text
    assert "▫ Файл" in text
    assert "▫ Изображение" in text
    assert "📱 Устройство съёмки" in text
    # сырые IfdTag-заглушки (0x829A) не должны попадать в отчёт
    assert "0x829A" not in text
    assert "Byte=[" not in text


def test_photo_report_curated_camera_params(tmp_path):
    """Параметры съёмки выводятся на русском, без сырых тегов."""
    img_path = tmp_path / "cam.jpg"
    _make_jpeg_with_exif(img_path)

    report = extract_photo(img_path)
    text = format_photo_report(report, img_path)

    assert "📸 Параметры съёмки" in text
    assert "Дата съёмки" in text
    assert "ПО" in text
    # Make/Model ушли в «Устройство съёмки», сырые теги не вываливаются
    assert "Model-X" in text.split("Устройство съёмки")[1]
    assert "Make:" not in text
    assert "Метаданных не найдено" not in text


def test_photo_without_exif(tmp_path):
    img = Image.new("RGB", (10, 10), "blue")
    path = tmp_path / "plain.png"
    img.save(path)
    report = extract_photo(path)
    assert report.gps is None
    text = format_photo_report(report, path)
    assert "ОТЧЁТ ПО ИЗОБРАЖЕНИЮ" in text


def test_missing_file(tmp_path):
    with pytest.raises(ServiceError):
        extract_photo(tmp_path / "nope.jpg")