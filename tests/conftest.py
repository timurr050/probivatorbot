"""Общие фикстуры Pytest. Все тесты работают оффлайн (без сети)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# добавляем проект в sys.path (на случай запуска не из корня)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def structured_photo_url(tmp_path_factory):
    """Пустой плейсхолдер-фикстура для структуры; см. test_photo_service."""
    return tmp_path_factory.getbasetemp()