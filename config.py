from __future__ import annotations

import random
from typing import Any, Dict, List

from models import VlessProfile


def build_sing_box_config(
    profiles,
    bypass_ru: bool = False,
    process_rules: List[Dict[str, str]] | None = None,
    use_urltest: bool = True,
    urltest_interval: str = "5m",
) -> Dict[str, Any]:
    # Accept a single profile (legacy) or a list (URLTest/selector).
    if isinstance(profiles, VlessProfile):
        profile_list = [profiles]
    else:
        profile_list = list(profiles)
    if not profile_list:
        raise ValueError("build_sing_box_config requires at least one profile")

    proxy_outbounds: List[Dict[str, Any]] = []
    if len(profile_list) == 1:
        outbound = _build_outbound(profile_list[0])
        outbound["tag"] = "proxy"
        proxy_outbounds.append(_prune_none_values(outbound))
    else:
        member_tags: List[str] = []
        for index, profile in enumerate(profile_list):
            out = _build_outbound(profile)
            out["tag"] = f"proxy-{index}"
            proxy_outbounds.append(_prune_none_values(out))
            member_tags.append(out["tag"])
        if use_urltest:
            proxy_outbounds.insert(0, {
                "type": "urltest",
                "tag": "proxy",
                "outbounds": member_tags,
                "url": "https://www.gstatic.com/generate_204",
                "interval": urltest_interval,
                "tolerance": 50,
            })
        else:
            proxy_outbounds.insert(0, {
                "type": "selector",
                "tag": "proxy",
                "outbounds": member_tags,
                "default": member_tags[0],
                "interrupt_exist_connections": False,
            })

    api_port = random.randint(19090, 19990)
    tun_name = f"singtun{random.randint(0, 9999)}"

    rules: List[Dict[str, Any]] = [
        {"action": "sniff"},
        {"protocol": "dns", "action": "hijack-dns"},
        {"ip_is_private": True, "outbound": "direct"},
    ]
    rule_sets: List[Dict[str, Any]] = []
    dns_rules: List[Dict[str, Any]] = []

    for proc_rule in (process_rules or []):
        name = (proc_rule.get("process_name") or "").strip()
        direction = proc_rule.get("outbound") or "direct"
        if not name or direction not in ("direct", "proxy"):
            continue
        rules.append({"process_name": name, "outbound": direction})

    if bypass_ru:
        rules.append({"rule_set": ["geosite-ru", "geoip-ru"], "outbound": "direct"})
        dns_rules.append({"rule_set": "geosite-ru", "server": "dns-local"})
        rule_sets.extend([
            {
                "type": "remote",
                "tag": "geosite-ru",
                "format": "binary",
                "url": "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-category-ru.srs",
                "download_detour": "direct",
            },
            {
                "type": "remote",
                "tag": "geoip-ru",
                "format": "binary",
                "url": "https://raw.githubusercontent.com/SagerNet/sing-geoip/rule-set/geoip-ru.srs",
                "download_detour": "direct",
            },
        ])

    route: Dict[str, Any] = {
        "auto_detect_interface": True,
        "final": "proxy",
        "rules": rules,
    }
    if rule_sets:
        route["rule_set"] = rule_sets
        route["default_domain_resolver"] = "dns-local"

    dns_block: Dict[str, Any] = {
        "servers": [{"type": "local", "tag": "dns-local"}],
        "final": "dns-local",
    }
    if dns_rules:
        dns_block["rules"] = dns_rules

    return {
        "log": {
            "level": "warn",
        },
        "dns": dns_block,
        "inbounds": [
            {
                "type": "tun",
                "tag": "tun-in",
                "interface_name": tun_name,
                "address": ["172.19.0.1/30"],
                "auto_route": True,
                "strict_route": True,
                "stack": "system",
            }
        ],
        "outbounds": proxy_outbounds + [
            {
                "type": "direct",
                "tag": "direct",
            },
        ],
        "route": route,
        "experimental": {
            "clash_api": {
                "external_controller": f"127.0.0.1:{api_port}",
                "external_ui": "",
                "secret": "medved",
                "default_mode": "rule",
            }
        },
    }


def _build_outbound(profile: VlessProfile) -> Dict[str, Any]:
    proto = (profile.protocol or "vless").lower()

    if proto == "vless":
        return {
            "type": "vless",
            "tag": "proxy",
            "server": profile.server,
            "server_port": profile.port,
            "uuid": profile.uuid,
            "flow": profile.flow or None,
            "packet_encoding": "xudp",
            "transport": _build_transport(profile),
            "tls": _build_tls(profile),
        }

    if proto == "vmess":
        return {
            "type": "vmess",
            "tag": "proxy",
            "server": profile.server,
            "server_port": profile.port,
            "uuid": profile.uuid,
            "security": "auto",
            "alter_id": int(profile.alter_id or 0),
            "packet_encoding": "xudp",
            "transport": _build_transport(profile),
            "tls": _build_tls(profile) if profile.security in ("tls", "reality") else {"enabled": False},
        }

    if proto == "trojan":
        return {
            "type": "trojan",
            "tag": "proxy",
            "server": profile.server,
            "server_port": profile.port,
            "password": profile.password,
            "transport": _build_transport(profile),
            "tls": _build_tls(profile),
        }

    if proto == "shadowsocks":
        return {
            "type": "shadowsocks",
            "tag": "proxy",
            "server": profile.server,
            "server_port": profile.port,
            "method": profile.method,
            "password": profile.password,
        }

    if proto == "hysteria2":
        obfs_block = None
        if profile.obfs:
            obfs_block = {"type": profile.obfs, "password": profile.obfs_password or profile.password}
        return _prune_none_values({
            "type": "hysteria2",
            "tag": "proxy",
            "server": profile.server,
            "server_port": profile.port,
            "password": profile.password,
            "obfs": obfs_block,
            "tls": {
                "enabled": True,
                "server_name": profile.sni or profile.server,
                "insecure": bool(profile.insecure),
                "alpn": _split_csv(profile.alpn) if profile.alpn else ["h3"],
            },
        })

    raise ValueError(f"Unsupported protocol: {profile.protocol!r}")


def _build_tls(profile: VlessProfile) -> Dict[str, Any]:
    if profile.security == "reality":
        return _prune_none_values(
            {
                "enabled": True,
                "server_name": profile.sni or profile.server,
                "utls": {
                    "enabled": True,
                    "fingerprint": profile.fp or "chrome",
                },
                "reality": {
                    "enabled": True,
                    "public_key": profile.public_key,
                    "short_id": profile.short_id,
                },
            }
        )

    if profile.security == "tls":
        alpn_values = _split_csv(profile.alpn)
        return _prune_none_values(
            {
                "enabled": True,
                "server_name": profile.sni or profile.server,
                "utls": {
                    "enabled": True,
                    "fingerprint": profile.fp or "chrome",
                },
                "alpn": alpn_values,
            }
        )

    return {"enabled": False}


def _build_transport(profile: VlessProfile) -> Dict[str, Any]:
    transport_type = (profile.type or "tcp").lower()

    if transport_type == "grpc":
        return _prune_none_values(
            {
                "type": "grpc",
                "service_name": profile.service_name or None,
            }
        )

    if transport_type == "ws":
        return _prune_none_values(
            {
                "type": "ws",
                "path": profile.path or None,
                "headers": {
                    "Host": profile.host or None,
                },
            }
        )

    if transport_type == "http":
        return _prune_none_values(
            {
                "type": "http",
                "host": [profile.host] if profile.host else [],
                "path": profile.path or None,
            }
        )

    if transport_type == "httpupgrade":
        return _prune_none_values(
            {
                "type": "httpupgrade",
                "host": profile.host or None,
                "path": profile.path or None,
                "headers": {},
            }
        )

    if transport_type == "quic":
        return {"type": "quic"}

    return {}


def _split_csv(text: str) -> List[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def _prune_none_values(data: Dict[str, Any]) -> Dict[str, Any]:
    cleaned: Dict[str, Any] = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, dict):
            nested = _prune_none_values(value)
            if nested:
                cleaned[key] = nested
            continue
        if isinstance(value, list):
            filtered_list = [item for item in value if item not in (None, "", [], {})]
            if filtered_list:
                cleaned[key] = filtered_list
            continue
        cleaned[key] = value
    return cleaned