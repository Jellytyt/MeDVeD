from __future__ import annotations

import base64
import binascii
import json
from typing import Dict
from urllib.parse import parse_qs, quote, unquote, urlparse

from models import VlessProfile


_SUPPORTED_PREFIXES = ("vless://", "vmess://", "trojan://", "ss://", "hysteria2://", "hy2://")


def parse_link(link: str, default_name: str = "Imported", source_url: str = "") -> VlessProfile:
    """Detect protocol by URL scheme and dispatch to the right parser."""
    text = link.strip()
    if text.startswith("vless://"):
        return parse_vless_link(text, default_name, source_url)
    if text.startswith("vmess://"):
        return parse_vmess_link(text, default_name, source_url)
    if text.startswith("trojan://"):
        return parse_trojan_link(text, default_name, source_url)
    if text.startswith("ss://"):
        return parse_ss_link(text, default_name, source_url)
    if text.startswith(("hysteria2://", "hy2://")):
        return parse_hysteria2_link(text, default_name, source_url)
    raise ValueError(f"Unsupported link scheme. Expected one of: {', '.join(_SUPPORTED_PREFIXES)}")


def parse_vless_link(link: str, default_name: str = "Imported VLESS", source_url: str = "") -> VlessProfile:
    text = link.strip()
    if not text.startswith("vless://"):
        raise ValueError("Link must start with vless://")

    parsed = urlparse(text)
    uuid = parsed.username or ""
    if not uuid:
        raise ValueError("Missing UUID in VLESS link")

    server = parsed.hostname or ""
    if not server:
        raise ValueError("Missing server host in VLESS link")

    port = parsed.port or 443
    remark = unquote(parsed.fragment or "") or default_name
    query = _get_query_map(parsed.query)

    return VlessProfile(
        name=remark,
        uuid=uuid,
        server=server,
        port=port,
        security=query.get("security", "tls"),
        flow=query.get("flow", ""),
        sni=query.get("sni", query.get("peer", "")),
        fp=query.get("fp", "chrome"),
        type=query.get("type", "tcp"),
        host=query.get("host", ""),
        path=query.get("path", ""),
        service_name=query.get("serviceName", ""),
        alpn=query.get("alpn", ""),
        public_key=query.get("pbk", ""),
        short_id=query.get("sid", ""),
        spider_x=query.get("spx", ""),
        remark=remark,
        enabled=True,
        source_url=source_url,
        protocol="vless",
    )


def parse_vmess_link(link: str, default_name: str = "Imported VMess", source_url: str = "") -> VlessProfile:
    """VMess link: vmess://BASE64(JSON). The JSON has v2rayN-style fields."""
    text = link.strip()
    if not text.startswith("vmess://"):
        raise ValueError("Link must start with vmess://")
    payload = text[len("vmess://"):]
    try:
        padding = (4 - len(payload) % 4) % 4
        decoded = base64.b64decode(payload + "=" * padding, validate=False).decode("utf-8", errors="ignore")
        data = json.loads(decoded)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"Invalid VMess link payload: {error}") from error
    if not isinstance(data, dict):
        raise ValueError("VMess JSON must be an object")

    server = str(data.get("add", "")).strip()
    if not server:
        raise ValueError("Missing server host in VMess link")
    uuid = str(data.get("id", "")).strip()
    if not uuid:
        raise ValueError("Missing UUID in VMess link")

    name = str(data.get("ps", "")).strip() or default_name
    return VlessProfile(
        name=name,
        uuid=uuid,
        server=server,
        port=int(data.get("port", 443) or 443),
        security=str(data.get("tls", "") or "none") or "none",
        flow="",
        sni=str(data.get("sni", "") or ""),
        fp=str(data.get("fp", "") or "chrome"),
        type=str(data.get("net", "tcp") or "tcp"),
        host=str(data.get("host", "") or ""),
        path=str(data.get("path", "") or ""),
        service_name="",
        alpn=str(data.get("alpn", "") or ""),
        public_key="",
        short_id="",
        spider_x="",
        remark=name,
        enabled=True,
        source_url=source_url,
        protocol="vmess",
        alter_id=int(data.get("aid", 0) or 0),
    )


def parse_trojan_link(link: str, default_name: str = "Imported Trojan", source_url: str = "") -> VlessProfile:
    text = link.strip()
    if not text.startswith("trojan://"):
        raise ValueError("Link must start with trojan://")
    parsed = urlparse(text)
    password = unquote(parsed.username or "")
    if not password:
        raise ValueError("Missing password in Trojan link")
    server = parsed.hostname or ""
    if not server:
        raise ValueError("Missing server host in Trojan link")
    port = parsed.port or 443
    remark = unquote(parsed.fragment or "") or default_name
    query = _get_query_map(parsed.query)

    return VlessProfile(
        name=remark,
        uuid="",
        server=server,
        port=port,
        security=query.get("security", "tls"),
        flow="",
        sni=query.get("sni", query.get("peer", "")),
        fp=query.get("fp", "chrome"),
        type=query.get("type", "tcp"),
        host=query.get("host", ""),
        path=query.get("path", ""),
        service_name=query.get("serviceName", ""),
        alpn=query.get("alpn", ""),
        public_key="",
        short_id="",
        spider_x="",
        remark=remark,
        enabled=True,
        source_url=source_url,
        protocol="trojan",
        password=password,
        insecure=query.get("allowInsecure", "") in ("1", "true"),
    )


def parse_ss_link(link: str, default_name: str = "Imported SS", source_url: str = "") -> VlessProfile:
    """Shadowsocks SIP002: ss://BASE64(method:password)@host:port#name
    or legacy: ss://BASE64(method:password@host:port)#name"""
    text = link.strip()
    if not text.startswith("ss://"):
        raise ValueError("Link must start with ss://")

    body = text[len("ss://"):]
    fragment = ""
    if "#" in body:
        body, fragment = body.split("#", 1)
    remark = unquote(fragment) if fragment else default_name

    method = ""
    password = ""
    server = ""
    port = 443

    if "@" in body:
        # SIP002: BASE64(method:password)@host:port[?query]
        userinfo, hostinfo = body.split("@", 1)
        try:
            padding = (4 - len(userinfo) % 4) % 4
            decoded = base64.b64decode(userinfo + "=" * padding, validate=False).decode("utf-8", errors="ignore")
        except (binascii.Error, UnicodeDecodeError) as error:
            raise ValueError(f"Invalid SS userinfo: {error}") from error
        if ":" not in decoded:
            raise ValueError("SS userinfo must contain 'method:password'")
        method, password = decoded.split(":", 1)
        host_part = hostinfo.split("?", 1)[0]
        if ":" not in host_part:
            raise ValueError("SS link missing port")
        server, port_str = host_part.rsplit(":", 1)
        port = int(port_str)
    else:
        # Legacy: BASE64(method:password@host:port)
        try:
            padding = (4 - len(body) % 4) % 4
            decoded = base64.b64decode(body + "=" * padding, validate=False).decode("utf-8", errors="ignore")
        except (binascii.Error, UnicodeDecodeError) as error:
            raise ValueError(f"Invalid SS link payload: {error}") from error
        if "@" not in decoded or ":" not in decoded:
            raise ValueError("SS legacy link must contain 'method:password@host:port'")
        userinfo, hostinfo = decoded.rsplit("@", 1)
        if ":" not in userinfo:
            raise ValueError("SS userinfo must contain 'method:password'")
        method, password = userinfo.split(":", 1)
        if ":" not in hostinfo:
            raise ValueError("SS link missing port")
        server, port_str = hostinfo.rsplit(":", 1)
        port = int(port_str)

    return VlessProfile(
        name=remark,
        uuid="",
        server=server,
        port=port,
        security="none",
        type="tcp",
        remark=remark,
        enabled=True,
        source_url=source_url,
        protocol="shadowsocks",
        password=password,
        method=method,
    )


def parse_hysteria2_link(link: str, default_name: str = "Imported Hysteria2", source_url: str = "") -> VlessProfile:
    text = link.strip()
    if text.startswith("hy2://"):
        text = "hysteria2://" + text[len("hy2://"):]
    if not text.startswith("hysteria2://"):
        raise ValueError("Link must start with hysteria2:// or hy2://")
    parsed = urlparse(text)
    password = unquote(parsed.username or "")
    if not password:
        raise ValueError("Missing password in Hysteria2 link")
    server = parsed.hostname or ""
    if not server:
        raise ValueError("Missing server host in Hysteria2 link")
    port = parsed.port or 443
    remark = unquote(parsed.fragment or "") or default_name
    query = _get_query_map(parsed.query)

    return VlessProfile(
        name=remark,
        uuid="",
        server=server,
        port=port,
        security="tls",
        sni=query.get("sni", ""),
        type="udp",
        alpn=query.get("alpn", ""),
        remark=remark,
        enabled=True,
        source_url=source_url,
        protocol="hysteria2",
        password=password,
        insecure=query.get("insecure", "") in ("1", "true"),
        obfs=query.get("obfs", ""),
        obfs_password=query.get("obfs-password", ""),
    )


def profile_to_vless_link(profile: VlessProfile) -> str:
    """Export VLESS profile back to vless:// link. Only used for the
    'Copy link' button — multi-protocol export is not implemented yet."""
    query_items = {
        "encryption": "none",
        "security": profile.security,
        "type": profile.type,
        "host": profile.host,
        "path": profile.path,
        "serviceName": profile.service_name,
        "sni": profile.sni,
        "alpn": profile.alpn,
        "fp": profile.fp,
        "flow": profile.flow,
        "pbk": profile.public_key,
        "sid": profile.short_id,
        "spx": profile.spider_x,
        "headerType": None,
        "mode": None,
        "seed": None,
    }
    query = "&".join(
        f"{key}={quote(str(value), safe='')}"
        for key, value in query_items.items()
        if value not in ("", None)
    )
    remark = profile.remark or profile.name
    encoded_remark = quote(remark, safe="")
    return f"vless://{profile.uuid}@{profile.server}:{profile.port}?{query}#{encoded_remark}"


def _get_query_map(query: str) -> Dict[str, str]:
    values = parse_qs(query, keep_blank_values=True)
    return {key: items[0] if items else "" for key, items in values.items()}
