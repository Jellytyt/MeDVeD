"""Round-trip tests for parser.py.

A share-link parsed into a profile and exported back via profile_to_link must
re-parse to the same key fields. This guards the parse/export pair against
regressions across all six supported protocols (the 'Copy link' button and
subscription import both depend on it).
"""
import base64
import json

import pytest

from parser import parse_link, profile_to_link


def _roundtrip(link):
    p1 = parse_link(link)
    p2 = parse_link(profile_to_link(p1))
    return p1, p2


def _assert_same(p1, p2, attrs):
    for attr in attrs:
        assert getattr(p1, attr) == getattr(p2, attr), (
            f"{attr}: {getattr(p1, attr)!r} != {getattr(p2, attr)!r}"
        )


def test_vless_roundtrip():
    link = (
        "vless://11111111-1111-1111-1111-111111111111@example.com:443"
        "?security=tls&type=ws&path=%2Fws&host=cdn.example.com&sni=example.com&fp=chrome#My%20VLESS"
    )
    p1, p2 = _roundtrip(link)
    assert p1.protocol == "vless"
    assert p1.name == "My VLESS"
    _assert_same(p1, p2, ["protocol", "uuid", "server", "port", "security", "type", "path", "host", "sni"])


def test_vmess_roundtrip():
    data = {
        "v": "2", "ps": "My VMess", "add": "vm.example.com", "port": "443",
        "id": "22222222-2222-2222-2222-222222222222", "aid": "0", "net": "ws",
        "host": "h.example.com", "path": "/p", "tls": "tls", "sni": "vm.example.com",
    }
    link = "vmess://" + base64.b64encode(json.dumps(data).encode()).decode()
    p1, p2 = _roundtrip(link)
    assert p1.protocol == "vmess"
    _assert_same(p1, p2, ["protocol", "uuid", "server", "port", "type", "host", "path", "alter_id"])


def test_trojan_roundtrip():
    link = "trojan://secret%40pass@t.example.com:8443?security=tls&type=tcp&sni=t.example.com#Trojan"
    p1, p2 = _roundtrip(link)
    assert p1.protocol == "trojan"
    assert p1.password == "secret@pass"
    _assert_same(p1, p2, ["protocol", "password", "server", "port", "security", "type", "sni"])


def test_shadowsocks_roundtrip():
    userinfo = base64.b64encode(b"aes-256-gcm:ss-password").decode()
    link = f"ss://{userinfo}@s.example.com:8388#SS%20Node"
    p1, p2 = _roundtrip(link)
    assert p1.protocol == "shadowsocks"
    assert p1.method == "aes-256-gcm"
    assert p1.password == "ss-password"
    _assert_same(p1, p2, ["protocol", "method", "password", "server", "port"])


def test_hysteria2_roundtrip():
    link = "hysteria2://hy-pass@h2.example.com:443?sni=h2.example.com&obfs=salamander&obfs-password=op#HY2"
    p1, p2 = _roundtrip(link)
    assert p1.protocol == "hysteria2"
    _assert_same(p1, p2, ["protocol", "password", "server", "port", "sni", "obfs", "obfs_password"])


def test_tuic_roundtrip():
    link = (
        "tuic://33333333-3333-3333-3333-333333333333:tuic-pass@tu.example.com:443"
        "?congestion_control=bbr&udp_relay_mode=native&alpn=h3#TUIC"
    )
    p1, p2 = _roundtrip(link)
    assert p1.protocol == "tuic"
    _assert_same(p1, p2, ["protocol", "uuid", "password", "server", "port", "congestion_control", "udp_relay_mode"])


def test_hy2_alias_normalizes_to_hysteria2():
    p = parse_link("hy2://pw@h2.example.com:443#x")
    assert p.protocol == "hysteria2"
    assert p.server == "h2.example.com"


def test_unknown_scheme_raises():
    with pytest.raises(ValueError):
        parse_link("ftp://nope")


def test_vless_missing_uuid_raises():
    with pytest.raises(ValueError):
        parse_link("vless://@example.com:443#x")


# --- defaults, aliases and field mapping -------------------------------------

def test_vless_defaults_when_query_empty():
    p = parse_link("vless://uuid-1@example.com:443")
    assert p.port == 443
    assert p.security == "tls"      # default
    assert p.type == "tcp"          # default
    assert p.fp == "chrome"         # default
    assert p.name == "Imported"     # no #fragment -> default_name


def test_vless_default_port_is_443():
    p = parse_link("vless://uuid-1@example.com")
    assert p.port == 443


def test_vless_sni_falls_back_to_peer():
    p = parse_link("vless://uuid-1@example.com:443?peer=sni.example.com")
    assert p.sni == "sni.example.com"


def test_vless_reality_fields_roundtrip():
    link = (
        "vless://uuid-1@example.com:443?security=reality&type=grpc&serviceName=grpcsvc"
        "&pbk=PUBKEY123&sid=ab12&flow=xtls-rprx-vision&fp=firefox#Reality"
    )
    p1, p2 = _roundtrip(link)
    assert p1.security == "reality"
    assert p1.public_key == "PUBKEY123"
    assert p1.short_id == "ab12"
    assert p1.flow == "xtls-rprx-vision"
    _assert_same(p1, p2, ["security", "public_key", "short_id", "flow", "service_name", "fp"])


def test_vless_ipv6_host():
    p = parse_link("vless://uuid-1@[2001:db8::1]:443#v6")
    assert p.server == "2001:db8::1"
    assert p.port == 443


def test_fragment_url_decoding():
    p = parse_link("vless://uuid-1@example.com:443#%D0%9C%D0%BE%D0%B9%20%D1%83%D0%B7%D0%B5%D0%BB")
    assert p.name == "Мой узел"


def test_hy2_alias_normalizes_and_roundtrips():
    p1 = parse_link("hy2://pw@h2.example.com:443?sni=h2.example.com#X")
    p2 = parse_link(profile_to_link(p1))
    assert p1.protocol == "hysteria2"
    _assert_same(p1, p2, ["protocol", "password", "server", "port", "sni"])


def test_trojan_allow_insecure_flag():
    p = parse_link("trojan://pw@t.example.com:443?allowInsecure=1#T")
    assert p.insecure is True


def test_tuic_insecure_alias():
    p = parse_link("tuic://uuid-1:pw@tu.example.com:443?allow_insecure=1#T")
    assert p.insecure is True


def test_ss_legacy_format():
    # Legacy: ss://BASE64(method:password@host:port)#name
    raw = base64.b64encode(b"aes-256-gcm:pw@s.example.com:8388").decode()
    p = parse_link(f"ss://{raw}#Legacy")
    assert p.protocol == "shadowsocks"
    assert p.method == "aes-256-gcm"
    assert p.password == "pw"
    assert p.server == "s.example.com"
    assert p.port == 8388


def test_ss_sip002_with_query_after_host():
    userinfo = base64.b64encode(b"chacha20-ietf-poly1305:pw").decode()
    p = parse_link(f"ss://{userinfo}@s.example.com:8388?plugin=obfs#Q")
    assert p.server == "s.example.com"
    assert p.port == 8388
    assert p.method == "chacha20-ietf-poly1305"


def test_vmess_base64_without_padding():
    data = {"v": "2", "ps": "n", "add": "v.example.com", "port": "443", "id": "uuid-1", "net": "tcp"}
    encoded = base64.b64encode(json.dumps(data).encode()).decode().rstrip("=")
    p = parse_link("vmess://" + encoded)
    assert p.protocol == "vmess"
    assert p.server == "v.example.com"


# --- malformed input rejection ------------------------------------------------

def test_vmess_invalid_base64_raises():
    with pytest.raises(ValueError):
        parse_link("vmess://!!!not-base64!!!")


def test_vmess_missing_server_raises():
    data = {"v": "2", "id": "uuid-1", "port": "443"}  # no 'add'
    link = "vmess://" + base64.b64encode(json.dumps(data).encode()).decode()
    with pytest.raises(ValueError):
        parse_link(link)


def test_trojan_missing_password_raises():
    with pytest.raises(ValueError):
        parse_link("trojan://@t.example.com:443#x")


def test_tuic_missing_uuid_raises():
    with pytest.raises(ValueError):
        parse_link("tuic://@tu.example.com:443#x")


def test_hysteria2_missing_password_raises():
    with pytest.raises(ValueError):
        parse_link("hysteria2://@h2.example.com:443#x")


def test_ss_missing_port_raises():
    userinfo = base64.b64encode(b"aes-256-gcm:pw").decode()
    with pytest.raises(ValueError):
        parse_link(f"ss://{userinfo}@s.example.com#NoPort")


def test_empty_string_raises():
    with pytest.raises(ValueError):
        parse_link("")


def test_export_unsupported_protocol_raises():
    p = parse_link("vless://uuid-1@example.com:443#x")
    p.protocol = "wireguard"
    with pytest.raises(ValueError):
        profile_to_link(p)


# --- defensive guards: each parser rejects a mismatched scheme ----------------

@pytest.mark.parametrize("func_name, wrong_link", [
    ("parse_vless_link", "trojan://x@h:443"),
    ("parse_vmess_link", "vless://x@h:443"),
    ("parse_trojan_link", "vless://x@h:443"),
    ("parse_ss_link", "vless://x@h:443"),
    ("parse_hysteria2_link", "vless://x@h:443"),
    ("parse_tuic_link", "vless://x@h:443"),
])
def test_parser_rejects_wrong_scheme(func_name, wrong_link):
    import parser as parser_mod
    with pytest.raises(ValueError):
        getattr(parser_mod, func_name)(wrong_link)


# --- missing-host / malformed structural rejections ---------------------------

def test_vless_missing_server_raises():
    with pytest.raises(ValueError):
        parse_link("vless://uuid-1@:443#x")


def test_trojan_missing_server_raises():
    with pytest.raises(ValueError):
        parse_link("trojan://pw@:443#x")


def test_hysteria2_missing_server_raises():
    with pytest.raises(ValueError):
        parse_link("hysteria2://pw@:443#x")


def test_tuic_missing_server_raises():
    with pytest.raises(ValueError):
        parse_link("tuic://uuid-1:pw@:443#x")


def test_vmess_non_dict_json_raises():
    link = "vmess://" + base64.b64encode(b"[1, 2, 3]").decode()
    with pytest.raises(ValueError):
        parse_link(link)


def test_vmess_missing_uuid_raises():
    data = {"v": "2", "add": "v.example.com", "port": "443"}  # no 'id'
    link = "vmess://" + base64.b64encode(json.dumps(data).encode()).decode()
    with pytest.raises(ValueError):
        parse_link(link)


def test_ss_sip002_userinfo_without_colon_raises():
    userinfo = base64.b64encode(b"no-colon-here").decode()
    with pytest.raises(ValueError):
        parse_link(f"ss://{userinfo}@s.example.com:8388#x")


def test_ss_legacy_malformed_raises():
    raw = base64.b64encode(b"just-some-text-without-structure").decode()
    with pytest.raises(ValueError):
        parse_link(f"ss://{raw}#x")


def test_ss_legacy_userinfo_without_colon_raises():
    raw = base64.b64encode(b"nocolon@host:8388").decode()
    with pytest.raises(ValueError):
        parse_link(f"ss://{raw}#x")


def test_ss_legacy_host_without_port_raises():
    raw = base64.b64encode(b"aes-256-gcm:pw@hostnoport").decode()
    with pytest.raises(ValueError):
        parse_link(f"ss://{raw}#x")
