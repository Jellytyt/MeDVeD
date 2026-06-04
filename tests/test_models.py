"""Tests for models.py settings/profile (de)serialization.

Covers the _coerce_int helper that lets subscription_refresh_hours default to 1
while still honouring an explicit 0 (auto-refresh off), plus dataclass round-trips.
"""
from models import AppSettings, VlessProfile, _coerce_int


def test_coerce_int_preserves_explicit_zero():
    assert _coerce_int(0, 1) == 0
    assert _coerce_int("0", 1) == 0


def test_coerce_int_falls_back_on_junk():
    assert _coerce_int(None, 1) == 1
    assert _coerce_int("", 1) == 1
    assert _coerce_int("abc", 1) == 1


def test_coerce_int_parses_values():
    assert _coerce_int(5, 1) == 5
    assert _coerce_int("7", 1) == 7


def test_appsettings_default_refresh_is_one():
    assert AppSettings().subscription_refresh_hours == 1
    assert AppSettings.from_dict({}).subscription_refresh_hours == 1


def test_appsettings_respects_saved_zero():
    assert AppSettings.from_dict({"subscription_refresh_hours": 0}).subscription_refresh_hours == 0


def test_appsettings_roundtrip():
    s = AppSettings(subscriptions=["https://x"], subscription_refresh_hours=3, kill_switch=True)
    s2 = AppSettings.from_dict(s.to_dict())
    assert s2.subscriptions == ["https://x"]
    assert s2.subscription_refresh_hours == 3
    assert s2.kill_switch is True


def test_vlessprofile_roundtrip():
    p = VlessProfile(name="n", uuid="u", server="h", port=8443, protocol="trojan", password="pw")
    p2 = VlessProfile.from_dict(p.to_dict())
    assert p2.name == "n"
    assert p2.port == 8443
    assert p2.protocol == "trojan"
    assert p2.password == "pw"
