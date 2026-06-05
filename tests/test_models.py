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


# --- AppSettings: input sanitising -------------------------------------------

def test_subscriptions_strip_blanks_and_whitespace():
    s = AppSettings.from_dict({"subscriptions": ["https://a", "", "   ", "https://b"]})
    assert s.subscriptions == ["https://a", "https://b"]


def test_routing_rules_without_value_dropped():
    s = AppSettings.from_dict({"routing_rules": [
        {"kind": "domain_suffix", "value": "example.com", "action": "proxy"},
        {"kind": "domain_suffix", "value": "", "action": "proxy"},   # no value -> dropped
    ]})
    assert s.routing_rules == [{"kind": "domain_suffix", "value": "example.com", "action": "proxy"}]


def test_routing_rule_defaults_filled():
    s = AppSettings.from_dict({"routing_rules": [{"value": "x.com"}]})
    assert s.routing_rules == [{"kind": "domain_suffix", "value": "x.com", "action": "direct"}]


def test_process_rules_mapped():
    s = AppSettings.from_dict({"process_rules": [{"process_name": "tg.exe", "outbound": "proxy"}]})
    assert s.process_rules == [{"process_name": "tg.exe", "outbound": "proxy"}]


def test_subscription_info_drops_non_dict_entries():
    s = AppSettings.from_dict({"subscription_info": {"u1": {"used": 1}, "u2": "bad"}})
    assert s.subscription_info == {"u1": {"used": 1}}


def test_subscription_titles_roundtrip_and_coercion():
    s = AppSettings(subscription_titles={"https://x": "My Sub"})
    assert AppSettings.from_dict(s.to_dict()).subscription_titles == {"https://x": "My Sub"}
    # Values coerced to str on load.
    assert AppSettings.from_dict({"subscription_titles": {"u": 123}}).subscription_titles == {"u": "123"}


def test_subscription_titles_default_empty():
    assert AppSettings().subscription_titles == {}
    assert AppSettings.from_dict({}).subscription_titles == {}


def test_last_seen_version_default_empty():
    assert AppSettings().last_seen_version == ""
    assert AppSettings.from_dict({}).last_seen_version == ""


def test_appsettings_ignores_unknown_keys():
    # Forward/backward compatibility: an unknown key from a newer build must not crash load.
    s = AppSettings.from_dict({"language": "en", "totally_new_field": 123})
    assert s.language == "en"


# --- VlessProfile: coercion and tolerance ------------------------------------

def test_alter_id_coercion():
    assert VlessProfile.from_dict({"name": "n", "uuid": "u", "server": "h", "port": 443}).alter_id == 0
    assert VlessProfile.from_dict({"name": "n", "uuid": "u", "server": "h", "port": 443,
                                   "alter_id": None}).alter_id == 0
    assert VlessProfile.from_dict({"name": "n", "uuid": "u", "server": "h", "port": 443,
                                   "alter_id": "3"}).alter_id == 3


def test_vlessprofile_from_dict_ignores_unknown_keys():
    p = VlessProfile.from_dict({"name": "n", "uuid": "u", "server": "h", "port": 443, "bogus": "x"})
    assert p.name == "n"
    assert p.server == "h"


def test_to_dict_coerces_port_and_enabled():
    p = VlessProfile(name="n", uuid="u", server="h", port=443)
    d = p.to_dict()
    assert isinstance(d["port"], int)
    assert isinstance(d["enabled"], bool)
