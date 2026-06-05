"""Structural tests for config.build_sing_box_config.

These pin the parts of the generated sing-box config that are easy to break and
expensive to debug at runtime — above all the DNS hijack rule ordering, which
was the hardest-won fix of the routing work.
"""
import pytest

from models import VlessProfile
from config import (
    build_sing_box_config,
    _build_tls,
    _build_transport,
    _split_csv,
    _prune_none_values,
)


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


# --- TLS block ----------------------------------------------------------------

def test_tls_reality_block():
    tls = _build_tls(_profile(security="reality", public_key="PK", short_id="ab", fp="firefox"))
    assert tls["enabled"] is True
    assert tls["server_name"] == "srv.example.com"   # falls back to server
    assert tls["utls"] == {"enabled": True, "fingerprint": "firefox"}
    assert tls["reality"] == {"enabled": True, "public_key": "PK", "short_id": "ab"}


def test_tls_standard_has_utls_and_split_alpn():
    tls = _build_tls(_profile(security="tls", sni="sni.example.com", fp="", alpn="h2,http/1.1"))
    assert tls["server_name"] == "sni.example.com"
    assert tls["utls"]["fingerprint"] == "chrome"     # empty fp -> default
    assert tls["alpn"] == ["h2", "http/1.1"]


def test_tls_none_is_disabled():
    assert _build_tls(_profile(security="none")) == {"enabled": False}


# --- transport block ----------------------------------------------------------

def test_transport_ws_with_path_and_host():
    t = _build_transport(_profile(type="ws", path="/ws", host="cdn.example.com"))
    assert t == {"type": "ws", "path": "/ws", "headers": {"Host": "cdn.example.com"}}


def test_transport_ws_minimal_prunes_empties():
    assert _build_transport(_profile(type="ws")) == {"type": "ws"}


def test_transport_grpc():
    assert _build_transport(_profile(type="grpc", service_name="svc")) == {
        "type": "grpc", "service_name": "svc"
    }


def test_transport_http_host_is_list():
    t = _build_transport(_profile(type="http", host="h.example.com", path="/p"))
    assert t == {"type": "http", "host": ["h.example.com"], "path": "/p"}


def test_transport_httpupgrade_prunes_empty_headers():
    t = _build_transport(_profile(type="httpupgrade", host="h", path="/p"))
    assert t == {"type": "httpupgrade", "host": "h", "path": "/p"}


def test_transport_quic():
    assert _build_transport(_profile(type="quic")) == {"type": "quic"}


def test_transport_tcp_is_empty():
    assert _build_transport(_profile(type="tcp")) == {}


# --- _prune_none_values -------------------------------------------------------

def test_prune_removes_none_scalar():
    assert _prune_none_values({"a": None, "b": 1}) == {"b": 1}


def test_prune_keeps_false_zero_and_empty_string():
    # Only None is stripped at scalar level; False/0/"" carry meaning and stay.
    assert _prune_none_values({"a": False, "b": 0, "c": ""}) == {"a": False, "b": 0, "c": ""}


def test_prune_removes_empty_collections():
    assert _prune_none_values({"a": {}, "b": [], "c": 1}) == {"c": 1}


def test_prune_filters_list_items_and_drops_nested_empty_dict():
    assert _prune_none_values({"a": ["x", None, "", "y"], "b": {"c": None}}) == {"a": ["x", "y"]}


def test_split_csv():
    assert _split_csv("a, b ,,c ") == ["a", "b", "c"]
    assert _split_csv("") == []


# --- outbound integration -----------------------------------------------------

def test_vless_tcp_outbound_has_no_transport_key():
    proxy = _proxy(_profile(type="tcp"))
    assert "transport" not in proxy


def test_vless_ws_outbound_keeps_transport():
    proxy = _proxy(_profile(type="ws", path="/ws"))
    assert proxy["transport"]["type"] == "ws"


def test_shadowsocks_outbound_has_no_tls():
    proxy = _proxy(_profile(protocol="shadowsocks", method="aes-256-gcm", password="p"))
    assert proxy["method"] == "aes-256-gcm"
    assert proxy["password"] == "p"
    assert "tls" not in proxy


def test_vmess_non_tls_disables_tls():
    proxy = _proxy(_profile(protocol="vmess", security="none"))
    assert proxy["tls"] == {"enabled": False}


def test_tuic_default_alpn_is_h3():
    proxy = _proxy(_profile(protocol="tuic", password="p", alpn=""))
    assert proxy["tls"]["alpn"] == ["h3"]


def test_hysteria2_obfs_block_built():
    proxy = _proxy(_profile(protocol="hysteria2", password="p", obfs="salamander", obfs_password="op"))
    assert proxy["obfs"] == {"type": "salamander", "password": "op"}


def test_hysteria2_no_obfs_when_absent():
    proxy = _proxy(_profile(protocol="hysteria2", password="p"))
    assert "obfs" not in proxy


# --- top-level config invariants ----------------------------------------------

def test_clash_api_secret_and_port_range():
    api = build_sing_box_config(_profile())["experimental"]["clash_api"]
    assert api["secret"] == "medved"
    host, port = api["external_controller"].split(":")
    assert host == "127.0.0.1"
    assert 19090 <= int(port) <= 19990


def test_tun_interface_name_prefix():
    tun = build_sing_box_config(_profile())["inbounds"][0]
    assert tun["type"] == "tun"
    assert tun["interface_name"].startswith("singtun")


def test_urltest_interval_and_tolerance_passthrough():
    proxy = next(
        o for o in build_sing_box_config(
            [_profile("a"), _profile("b")], urltest_interval="2m"
        )["outbounds"] if o["tag"] == "proxy"
    )
    assert proxy["interval"] == "2m"
    assert proxy["tolerance"] == 50


def test_invalid_process_rule_direction_dropped():
    rules = build_sing_box_config(
        _profile(), process_rules=[{"process_name": "x.exe", "outbound": "bogus"}]
    )["route"]["rules"]
    assert not any(r.get("process_name") == "x.exe" for r in rules)


def test_routing_port_rule_coerced_to_int():
    rules = build_sing_box_config(
        _profile(), routing_rules=[{"kind": "port", "value": "8080", "action": "proxy"}]
    )["route"]["rules"]
    assert {"port": 8080, "outbound": "proxy"} in rules


def test_routing_invalid_port_dropped():
    rules = build_sing_box_config(
        _profile(), routing_rules=[{"kind": "port", "value": "abc", "action": "proxy"}]
    )["route"]["rules"]
    assert not any("port" in r for r in rules)


def test_routing_invalid_action_dropped():
    rules = build_sing_box_config(
        _profile(), routing_rules=[{"kind": "domain", "value": "x.com", "action": "nonsense"}]
    )["route"]["rules"]
    assert not any(r.get("domain") == "x.com" for r in rules)


def test_unsupported_protocol_raises():
    with pytest.raises(ValueError):
        build_sing_box_config(_profile(protocol="wireguard"))


# --- delay-test (dormant) outbounds for ping-while-connected ------------------

def test_delay_test_profiles_add_dormant_outbounds():
    cfg = build_sing_box_config(_profile("main"), delay_test_profiles=[_profile("a"), _profile("b")])
    tags = {o["tag"] for o in cfg["outbounds"]}
    assert "dt-0" in tags and "dt-1" in tags
    # They must NOT be wired into routing — purely for /proxies/dt-N/delay probes.
    assert cfg["route"]["final"] == "proxy"
    rule_targets = {r.get("outbound") for r in cfg["route"]["rules"]}
    assert "dt-0" not in rule_targets and "dt-1" not in rule_targets


def test_delay_test_bad_profile_skipped_index_preserved():
    bad = _profile("bad", protocol="wireguard")  # _build_outbound raises -> skipped
    cfg = build_sing_box_config(_profile("main"), delay_test_profiles=[bad, _profile("ok")])
    tags = {o["tag"] for o in cfg["outbounds"]}
    assert "dt-0" not in tags   # bad one at index 0 skipped
    assert "dt-1" in tags       # good one keeps its index-based tag


def test_no_delay_test_profiles_means_no_dt_outbounds():
    cfg = build_sing_box_config(_profile("main"))
    assert not any(o["tag"].startswith("dt-") for o in cfg["outbounds"])


# --- anti-DPI: uTLS fingerprint + TLS fragmentation ---------------------------

def test_fingerprint_auto_keeps_profile_value():
    assert _build_tls(_profile(security="tls", fp="firefox"))["utls"]["fingerprint"] == "firefox"
    assert _build_tls(_profile(security="tls", fp=""))["utls"]["fingerprint"] == "chrome"


def test_fingerprint_explicit_override_wins():
    tls = _build_tls(_profile(security="tls", fp="chrome"), utls_fingerprint="randomized")
    assert tls["utls"]["fingerprint"] == "randomized"


def test_fingerprint_override_applies_to_reality_too():
    tls = _build_tls(_profile(security="reality", public_key="PK", short_id="ab"), utls_fingerprint="firefox")
    assert tls["utls"]["fingerprint"] == "firefox"


def test_tls_fragment_adds_record_fragment():
    assert _build_tls(_profile(security="tls"), tls_fragment=True).get("record_fragment") is True


def test_tls_fragment_off_by_default():
    assert "record_fragment" not in _build_tls(_profile(security="tls"))


def test_reality_is_never_fragmented():
    # Reality borrows a real handshake — fragmenting it would break it.
    tls = _build_tls(_profile(security="reality", public_key="PK", short_id="ab"), tls_fragment=True)
    assert "record_fragment" not in tls


def test_build_config_threads_fragment_and_fingerprint_to_proxy():
    proxy = _proxy_with(_profile(protocol="vless", security="tls", fp="chrome"),
                        utls_fingerprint="firefox", tls_fragment=True)
    assert proxy["tls"]["record_fragment"] is True
    assert proxy["tls"]["utls"]["fingerprint"] == "firefox"


def _proxy_with(profile, **kw):
    cfg = build_sing_box_config(profile, **kw)
    return next(o for o in cfg["outbounds"] if o.get("tag") == "proxy")


def test_fragment_aggressive_uses_packet_fragment():
    tls = _build_tls(_profile(security="tls"), tls_fragment=True, tls_fragment_aggressive=True)
    assert tls.get("fragment") is True
    assert tls.get("fragment_fallback_delay") == "500ms"
    assert "record_fragment" not in tls


def test_fragment_normal_uses_record_fragment():
    tls = _build_tls(_profile(security="tls"), tls_fragment=True, tls_fragment_aggressive=False)
    assert tls.get("record_fragment") is True
    assert "fragment" not in tls


# --- DoH (encrypted DNS) ------------------------------------------------------

def test_doh_dns_block_and_bootstrap():
    cfg = build_sing_box_config(_profile(), doh_dns=True)
    servers = {s["tag"]: s for s in cfg["dns"]["servers"]}
    assert cfg["dns"]["final"] == "dns-doh"
    assert servers["dns-doh"]["type"] == "https"
    assert servers["dns-doh"]["detour"] == "proxy"
    assert "dns-local" in servers  # bootstrap resolver kept
    # outbound server domains must resolve directly to avoid a DoH bootstrap loop
    assert cfg["route"]["default_domain_resolver"] == "dns-local"


def test_no_doh_by_default():
    cfg = build_sing_box_config(_profile())
    assert cfg["dns"]["final"] == "dns-local"
    assert not any(s.get("type") == "https" for s in cfg["dns"]["servers"])
    assert "default_domain_resolver" not in cfg["route"]


def test_doh_coexists_with_bypass_ru():
    cfg = build_sing_box_config(_profile(), bypass_ru=True, doh_dns=True)
    assert cfg["dns"]["final"] == "dns-doh"
    assert cfg["route"]["default_domain_resolver"] == "dns-local"
    # geosite-ru DNS rule still present (routes RU domains to the local resolver)
    assert any(r.get("rule_set") == "geosite-ru" for r in cfg["dns"].get("rules", []))


def _proxy(profile):
    """The single 'proxy' outbound produced for one profile."""
    cfg = build_sing_box_config(profile)
    return next(o for o in cfg["outbounds"] if o.get("tag") == "proxy")
