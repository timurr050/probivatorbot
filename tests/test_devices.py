"""Тесты распознавания устройства съёмки (EXIF Make/Model → читаемое имя)."""
from __future__ import annotations

from bot.services.devices import recognize_device


def test_apple_iphone_name():
    dev = recognize_device("Apple", "iPhone 15 Pro")
    assert dev is not None
    assert dev["name"] == "Apple iPhone 15 Pro"
    assert dev["brand"] == "Apple"


def test_apple_iphone_17():
    dev = recognize_device("Apple", "iPhone 17 Pro Max")
    assert dev["name"] == "Apple iPhone 17 Pro Max"


def test_apple_model_case_normalized():
    dev = recognize_device("Apple", "IPHONE 12 MINI")
    assert dev["name"].lower().startswith("apple iphone 12")


def test_samsung_code_to_galaxy():
    dev = recognize_device("samsung", "SM-G991B")
    assert dev["name"] == "Samsung Galaxy S21"
    assert dev["brand"] == "Samsung"


def test_samsung_s24_ultra():
    dev = recognize_device("samsung", "SM-S928B")
    assert dev["name"] == "Samsung Galaxy S24 Ultra"


def test_samsung_z_flip():
    dev = recognize_device("samsung", "SM-F731B")
    assert dev["name"] == "Samsung Galaxy Z Flip5"


def test_samsung_unknown_code():
    dev = recognize_device("samsung", "SM-Z999X")
    assert dev["name"].startswith("Samsung")


def test_google_pixel():
    dev = recognize_device("Google", "Pixel 7")
    assert dev["name"] == "Google Pixel 7"


def test_xiaomi():
    dev = recognize_device("Xiaomi", "Redmi Note 10 Pro")
    assert "Xiaomi" in dev["name"]
    assert "Redmi Note 10 Pro" in dev["name"]


def test_camera_canon():
    dev = recognize_device("Canon", "Canon EOS R5")
    assert dev["name"] == "Canon EOS R5"


def test_nikon_no_duplicate_brand():
    dev = recognize_device("Nikon", "NIKON D850")
    assert dev["name"].lower().startswith("nikon")


def test_no_data():
    assert recognize_device("", "") is None
    assert recognize_device(None, None) is None
