"""Распознавание устройства съёмки по EXIF/MP4-тегам Make/Model.

Значения Make/Model из тегов бывают нечитаемыми (коды Samsung «SM-G991B»,
заглавные буквы, лишние пробелы). Здесь они превращаются в человеческое имя:
«Samsung Galaxy S21», «Apple iPhone 15 Pro», «Google Pixel 7» и т.д.
"""
from __future__ import annotations

import re
from typing import Optional

# Коды Samsung → читаемое имя. Ключ — префикс кода (совпадает с началом Model).
_SAMSUNG_MODELS: dict[str, str] = {
    # S-серия
    "SM-G930": "Galaxy S7",
    "SM-G935": "Galaxy S7 Edge",
    "SM-G950": "Galaxy S8",
    "SM-G955": "Galaxy S8+",
    "SM-G960": "Galaxy S9",
    "SM-G965": "Galaxy S9+",
    "SM-G970": "Galaxy S10e",
    "SM-G973": "Galaxy S10",
    "SM-G975": "Galaxy S10+",
    "SM-G977": "Galaxy S10 5G",
    "SM-G780": "Galaxy S20 FE",
    "SM-G781": "Galaxy S20 FE 5G",
    "SM-G980": "Galaxy S20",
    "SM-G981": "Galaxy S20 5G",
    "SM-G986": "Galaxy S20+",
    "SM-G988": "Galaxy S20 Ultra",
    "SM-G991": "Galaxy S21",
    "SM-G996": "Galaxy S21+",
    "SM-G998": "Galaxy S21 Ultra",
    "SM-G990": "Galaxy S21 FE",
    "SM-S901": "Galaxy S22",
    "SM-S906": "Galaxy S22+",
    "SM-S908": "Galaxy S22 Ultra",
    "SM-S901E": "Galaxy S22",
    "SM-S911": "Galaxy S23",
    "SM-S916": "Galaxy S23+",
    "SM-S918": "Galaxy S23 Ultra",
    "SM-S711": "Galaxy S23 FE",
    "SM-S921": "Galaxy S24",
    "SM-S926": "Galaxy S24+",
    "SM-S928": "Galaxy S24 Ultra",
    "SM-S721": "Galaxy S24 FE",
    "SM-S931": "Galaxy S25",
    "SM-S936": "Galaxy S25+",
    "SM-S938": "Galaxy S25 Ultra",
    "SM-S931B": "Galaxy S25",
    "SM-S937": "Galaxy S25 Edge",
    # Note
    "SM-N960": "Galaxy Note 9",
    "SM-N970": "Galaxy Note 10",
    "SM-N975": "Galaxy Note 10+",
    "SM-N976": "Galaxy Note 10+ 5G",
    "SM-N980": "Galaxy Note 20",
    "SM-N981": "Galaxy Note 20 5G",
    "SM-N985": "Galaxy Note 20 Ultra",
    "SM-N986": "Galaxy Note 20 Ultra 5G",
    # Z Fold / Z Flip
    "SM-F900": "Galaxy Fold",
    "SM-F700": "Galaxy Z Flip",
    "SM-F707": "Galaxy Z Flip 5G",
    "SM-F711": "Galaxy Z Flip3",
    "SM-F721": "Galaxy Z Flip4",
    "SM-F731": "Galaxy Z Flip5",
    "SM-F741": "Galaxy Z Flip6",
    "SM-F916": "Galaxy Z Fold2",
    "SM-F926": "Galaxy Z Fold3",
    "SM-F936": "Galaxy Z Fold4",
    "SM-F946": "Galaxy Z Fold5",
    "SM-F956": "Galaxy Z Fold6",
    # A-серия (хиты)
    "SM-A105": "Galaxy A10",
    "SM-A115": "Galaxy A11",
    "SM-A125": "Galaxy A12",
    "SM-A135": "Galaxy A13",
    "SM-A145": "Galaxy A14",
    "SM-A155": "Galaxy A15",
    "SM-A165": "Galaxy A16",
    "SM-A202": "Galaxy A20",
    "SM-A205": "Galaxy A20",
    "SM-A210": "Galaxy A21s",
    "SM-A217": "Galaxy A21s",
    "SM-A225": "Galaxy A22",
    "SM-A226": "Galaxy A22 5G",
    "SM-A235": "Galaxy A23",
    "SM-A245": "Galaxy A24",
    "SM-A256": "Galaxy A25",
    "SM-A315": "Galaxy A31",
    "SM-A325": "Galaxy A32",
    "SM-A326": "Galaxy A32 5G",
    "SM-A335": "Galaxy A33",
    "SM-A345": "Galaxy A34",
    "SM-A346": "Galaxy A34 5G",
    "SM-A355": "Galaxy A35",
    "SM-A426": "Galaxy A42 5G",
    "SM-A505": "Galaxy A50",
    "SM-A515": "Galaxy A51",
    "SM-A516": "Galaxy A51 5G",
    "SM-A525": "Galaxy A52",
    "SM-A526": "Galaxy A52 5G",
    "SM-A535": "Galaxy A53 5G",
    "SM-A545": "Galaxy A54 5G",
    "SM-A556": "Galaxy A55",
    "SM-A600": "Galaxy A6",
    "SM-A605": "Galaxy A6+",
    "SM-A705": "Galaxy A70",
    "SM-A715": "Galaxy A71",
    "SM-A716": "Galaxy A71 5G",
    "SM-A725": "Galaxy A72",
    "SM-A725F": "Galaxy A72",
    "SM-A805": "Galaxy A80",
    "SM-A908": "Galaxy A90 5G",
    # M-серия
    "SM-M115": "Galaxy M11",
    "SM-M215": "Galaxy M21",
    "SM-M315": "Galaxy M31",
    "SM-M515": "Galaxy M51",
    "SM-M625": "Galaxy M62",
    "SM-M127": "Galaxy M12",
    "SM-M135": "Galaxy M13",
    "SM-M235": "Galaxy M23",
    # J-серия
    "SM-J530": "Galaxy J5 (2017)",
    "SM-J730": "Galaxy J7 (2017)",
    "SM-J330": "Galaxy J3 (2017)",
    "SM-J415": "Galaxy J4+",
    "SM-J610": "Galaxy J6+",
    # Планшеты
    "SM-T860": "Galaxy Tab S6",
    "SM-T865": "Galaxy Tab S6",
    "SM-T870": "Galaxy Tab S7",
    "SM-T875": "Galaxy Tab S7",
    "SM-X700": "Galaxy Tab S8",
    "SM-X800": "Galaxy Tab S8+",
    "SM-X900": "Galaxy Tab S8 Ultra",
    "SM-X710": "Galaxy Tab S9",
    "SM-X810": "Galaxy Tab S9+",
    "SM-X910": "Galaxy Tab S9 Ultra",
}

# Бренды камер/телефонов, где имя модели уже читаемое или Make понятен сам.
_CAMERA_BRANDS = {
    "canon", "nikon", "sony", "fujifilm", "olympus", "panasonic", "leica",
    "pentax", "kodak", "gopro", "djI", "huawei", "honor", "oneplus",
    "oppo", "vivo", "xiaomi", "redmi", "poco", "realme", "nokia",
    "motorola", "asus", "lg", "htc", "zte", "lenovo", "google",
    "apple", "blackberry", "samsung",
}

_SM_RE = re.compile(r"^SM-[A-Z0-9]+", re.IGNORECASE)


def _clean(value: object) -> str:
    """Нормализует строку тега: лишние пробелы, нули-байты, регистр."""
    text = re.sub(r"\s+", " ", str(value or "").replace("\x00", "").strip())
    return text.strip()


def _samsung_name(model: str) -> Optional[str]:
    for prefix, name in sorted(_SAMSUNG_MODELS.items(), key=lambda kv: -len(kv[0])):
        if model.upper().startswith(prefix.upper()):
            return name
    return None


def _title_case(text: str) -> str:
    """iPhone 15 PRO MAX → iPhone 15 Pro Max; прецеденты сохраняются."""
    keep_upper = {"5G", "FE", "LTE", "EOS", "XR", "XS", "SE", "Plus", "Ultra"}
    words = text.split()
    out = []
    for w in words:
        if w in keep_upper:
            out.append(w)
        elif w.isupper() and len(w) <= 4:
            out.append(w.title())
        else:
            out.append(w)
    return " ".join(out)


def recognize_device(make: object, model: object) -> Optional[dict]:
    """Определяет читаемое имя устройства по Make/Model.

    Возвращает {"make", "model", "name", "brand"} либо None, если данных нет.
    """
    make = _clean(make)
    model = _clean(model)
    if not make and not model:
        return None

    make_l = make.lower()
    model_l = model.lower()

    # --- Apple iPhone (модель уже читаемая: «iPhone 12», «iPhone 15 Pro») ---
    if make_l in {"apple", "iphone"} or model_l.startswith("iphone"):
        name = model if model_l.startswith("iphone") else "iPhone"
        name = _title_case(name)
        return {"make": "Apple", "model": model, "name": f"Apple {name}" if not name.lower().startswith("apple") else name, "brand": "Apple"}

    # --- Samsung: код SM-XXXX → Galaxy-имя ---
    if "samsung" in make_l:
        galaxy = _samsung_name(model)
        if galaxy:
            return {"make": "Samsung", "model": model, "name": f"Samsung {galaxy}", "brand": "Samsung"}
        name = _title_case(model) if model else "Samsung"
        return {"make": "Samsung", "model": model, "name": f"Samsung {name}", "brand": "Samsung"}

    # --- Google Pixel ---
    if "google" in make_l:
        name = model if model_l.startswith("pixel") else f"Pixel {model}"
        return {"make": "Google", "model": model, "name": f"Google {name}", "brand": "Google"}

    # --- Остальные бренды (Xiaomi, Canon, Nikon, Huawei…) ---
    brand = None
    for b in _CAMERA_BRANDS:
        if b in make_l:
            brand = b.title()
            break
    if brand:
        name = model if model_l.startswith(brand.lower()) else f"{brand} {model}".strip()
        name = _title_case(name)
        return {"make": make, "model": model, "name": name, "brand": brand}

    # --- Универсальный случай: бренд в Make, имя в Model ---
    if make and model:
        name = model
        make_words = [w.lower() for w in re.findall(r"[a-zа-я]+", make)]
        model_words = [w.lower() for w in re.findall(r"[a-zа-я]+", model)]
        if not any(w in model_words for w in make_words if len(w) > 2):
            name = f"{make} {model}"
        return {"make": make, "model": model, "name": _title_case(name.strip()), "brand": make}
    return {"make": make, "model": model, "name": _title_case(make or model), "brand": make or model}
