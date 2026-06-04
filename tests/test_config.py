"""Structural tests for config.build_sing_box_config.

These pin the parts of the generated sing-box config that are easy to break and
expensive to debug at runtime — above all the DNS hijack rule ordering, which
was the hardest-won fix of the routing work.
"""
import pytest

from models import VlessProfile
from config import build_sing_box_config


def _profile(name="S", protocol="vless", **kw):
    base = dict(
        name=name, uuid="11111111-1111-1111-1111-111111111111",
        server="srv.example.com", port=443, protocol=protocol, security="tls", type="tcp",
    )
    base.update(kw)
    return VlessProfile(**base)


def test_dns_hijack_rules_come_first():
    # sniff -> hijack-dns -> LAN bypass MUST be the first three route rules, or
    # DNS to the TUN resolver (172.19.0.2:53) leaks to direct and times out.
    cfg = build_sing_box_config(_profile())
    rules = cfg["route"]["rules"]
    assert rules[0] == {"action": "sniff"}
    assert rules[1] == {"protocol": "dns", "action": "hijack-dns"}
    assert rules[2] == {"ip_is_private": True, "outbound": "direct"}


def test_single_profile_structure():
    cfg = build_sing_box_config(_profile())
    proxies = [o for o in cfg["outbounds"] if o.get("tag") == "proxy"]
    assert len(proxies) == 1
    assert proxies[0]["type"] == "vless"
    assert cfg["route"]["final"] == "proxy"
    assert any(i["type"] == "tun" for i in cfg["inbounds"])
    assert any(o.get("tag") == "direct" for o in cfg["outbounds"])


def test_multiple_profiles_make_urltest():
    cfg = build_sing_box_config([_profile("a"), _profile("b")])
    proxy = next(o for o in cfg["outbounds"] if o["tag"] == "proxy")
    assert proxy["type"] == "urltest"
    assert proxy["outbounds"] == ["proxy-0", "proxy-1"]


def test_selector_when_urltest_disabled():
    cfg = build_sing_box_config([_profile("a"), _profile("b")], use_urltest=False)
    proxy = next(o for o in cfg["outbounds"] if o["tag"] == "proxy")
    assert proxy["type"] == "selector"
    assert proxy["default"] == "proxy-0"


def test_empty_profiles_raises():
    with pytest.raises(ValueError):
        build_sing_box_config([])


def test_bypass_ru_rule_after_dns_rules():
    cfg = build_sing_box_config(_profile(), bypass_ru=True)
    rules = cfg["route"]["rules"]
    assert rules[1] == {"protocol": "dns", "action": "hijack-dns"}
    ru_idx = next(i for i, r in enumerate(rules) if r.get("rule_set") == ["geosite-ru", "geoip-ru"])
    assert ru_idx > 2  # comes after the three mandatory dns/LAN rules
    assert "rule_set" in cfg["route"]


@pytest.mark.parametrize("proto, extra", [
    ("vless", {}),
    ("vmess", {}),
    ("trojan", {"password": "p"}),
    ("shadowsocks", {"method": "aes-256-gcm", "password": "p"}),
    ("tuic", {"password": "p"}),
    ("hysteria2", {"password": "p"}),
])
def test_each_protocol_outbound_type(proto, extra):
    cfg = build_sing_box_config(_profile(protocol=proto, **extra))
    proxy = next(o for o in cfg["outbounds"] if o["tag"] == "proxy")
    assert proxy["type"] == proto


def test_process_and_routing_rules_injected():
    cfg = build_sing_box_config(
        _profile(),
        process_rules=[{"process_name": "telegram.exe", "outbound": "proxy"}],
        routing_rules=[{"kind": "domain_suffix", "value": "example.org", "action": "block"}],
    )
    rules = cfg["route"]["rules"]
    assert {"process_name": "telegram.exe", "outbound": "proxy"} in rules
    assert {"domain_suffix": "example.org", "action": "reject"} in rules
