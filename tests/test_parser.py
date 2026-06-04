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
