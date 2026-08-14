"""Тесты валидации ввода."""
from __future__ import annotations

import pytest

from bot.exceptions import ValidationError
from bot.utils.validators import (
    normalize_email,
    normalize_phone,
    normalize_tg_username,
    normalize_username,
)


class TestPhone:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("+375291234567", "+375291234567"),
            ("375291234567", "+375291234567"),
            ("8 029 123-45-67", "+375291234567"),
            ("+7 900 123-45-67", "+79001234567"),
            ("8 (912) 123-45-67", "+79121234567"),
            ("79123456789", "+79123456789"),
        ],
    )
    def test_valid(self, raw, expected):
        assert normalize_phone(raw) == expected

    @pytest.mark.parametrize(
        "bad",
        ["", "  ", "не номер", "123", "+11111111111111", "abcdefgh", "++7--"],
    )
    def test_invalid(self, bad):
        with pytest.raises(ValidationError):
            normalize_phone(bad)


class TestUsername:
    def test_valid_latin(self):
        assert normalize_username("ProBivBot") == "probivbot"
        assert normalize_username("@telegram_user") == "telegram_user"
        assert normalize_username("  john_doe  ") == "john_doe"

    def test_invalid(self):
        for bad in ["", "   ", "a b", "кирилица", "two\nlines"]:
            with pytest.raises(ValidationError):
                normalize_username(bad)

    def test_tg_username(self):
        assert normalize_tg_username("@telegram_user") == "telegram_user"
        with pytest.raises(ValidationError):
            normalize_tg_username("a" * 33)
        with pytest.raises(ValidationError):
            normalize_tg_username("вов@бс")


class TestEmail:
    @pytest.mark.parametrize(
        "raw",
        ["user@example.com", "User.NAME+tag@sub.domain.org", "x@y.io"],
    )
    def test_valid(self, raw):
        assert "@" in normalize_email(raw)

    @pytest.mark.parametrize(
        "bad",
        ["", "not-an-email", "a@b", "@domain.com", "spam@@domain.com", "a b@c.d"],
    )
    def test_invalid(self, bad):
        with pytest.raises(ValidationError):
            normalize_email(bad)