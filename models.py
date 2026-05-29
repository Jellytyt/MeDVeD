from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List  # noqa: F401


@dataclass
class VlessProfile:
    name: str
    uuid: str
    server: str
    port: int
    security: str = "tls"
    flow: str = ""
    sni: str = ""
    fp: str = "chrome"
    type: str = "tcp"
    host: str = ""
    path: str = ""
    service_name: str = ""
    alpn: str = ""
    public_key: str = ""
    short_id: str = ""
    spider_x: str = ""
    remark: str = ""
    enabled: bool = True
    source_url: str = ""
    protocol: str = "vless"
    password: str = ""
    method: str = ""
    alter_id: int = 0
    insecure: bool = False
    obfs: str = ""
    obfs_password: str = ""
    congestion_control: str = ""
    udp_relay_mode: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["port"] = int(self.port)
        data["enabled"] = bool(self.enabled)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VlessProfile":
        return cls(
            name=str(data.get("name", "")),
            uuid=str(data.get("uuid", "")),
            server=str(data.get("server", "")),
            port=int(data.get("port", 443)),
            security=str(data.get("security", "tls")),
            flow=str(data.get("flow", "")),
            sni=str(data.get("sni", "")),
            fp=str(data.get("fp", "chrome")),
            type=str(data.get("type", "tcp")),
            host=str(data.get("host", "")),
            path=str(data.get("path", "")),
            service_name=str(data.get("service_name", "")),
            alpn=str(data.get("alpn", "")),
            public_key=str(data.get("public_key", "")),
            short_id=str(data.get("short_id", "")),
            spider_x=str(data.get("spider_x", "")),
            remark=str(data.get("remark", "")),
            enabled=bool(data.get("enabled", True)),
            source_url=str(data.get("source_url", "")),
            protocol=str(data.get("protocol", "vless")),
            password=str(data.get("password", "")),
            method=str(data.get("method", "")),
            alter_id=int(data.get("alter_id", 0) or 0),
            insecure=bool(data.get("insecure", False)),
            obfs=str(data.get("obfs", "")),
            obfs_password=str(data.get("obfs_password", "")),
            congestion_control=str(data.get("congestion_control", "")),
            udp_relay_mode=str(data.get("udp_relay_mode", "")),
        )


@dataclass
class AppSettings:
    sing_box_path: str = "sing-box"
    data_dir: str = "data"
    subscriptions: List[str] = field(default_factory=list)
    auto_connect_enabled: bool = False
    auto_connect_key: str = ""
    minimize_to_tray: bool = True
    subscription_refresh_hours: int = 0
    notifications_enabled: bool = True
    bypass_ru: bool = False
    kill_switch: bool = False
    urltest_auto_switch: bool = True
    auto_start_with_windows: bool = False
    start_minimized: bool = False
    appearance_mode: str = "dark"
    language: str = "ru"
    subscription_info: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    process_rules: List[Dict[str, str]] = field(default_factory=list)
    routing_rules: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["subscriptions"] = list(self.subscriptions)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppSettings":
        raw_subscriptions = data.get("subscriptions", [])
        subscriptions = [str(item).strip() for item in raw_subscriptions if str(item).strip()]
        return cls(
            sing_box_path=str(data.get("sing_box_path", "sing-box")),
            data_dir=str(data.get("data_dir", "data")),
            subscriptions=subscriptions,
            auto_connect_enabled=bool(data.get("auto_connect_enabled", False)),
            auto_connect_key=str(data.get("auto_connect_key", "")),
            minimize_to_tray=bool(data.get("minimize_to_tray", True)),
            subscription_refresh_hours=int(data.get("subscription_refresh_hours", 0) or 0),
            notifications_enabled=bool(data.get("notifications_enabled", True)),
            bypass_ru=bool(data.get("bypass_ru", False)),
            kill_switch=bool(data.get("kill_switch", False)),
            urltest_auto_switch=bool(data.get("urltest_auto_switch", True)),
            auto_start_with_windows=bool(data.get("auto_start_with_windows", False)),
            start_minimized=bool(data.get("start_minimized", False)),
            appearance_mode=str(data.get("appearance_mode", "dark")),
            language=str(data.get("language", "ru")),
            subscription_info={
                str(k): dict(v) for k, v in (data.get("subscription_info") or {}).items()
                if isinstance(v, dict)
            },
            process_rules=[
                {"process_name": str(r.get("process_name", "")), "outbound": str(r.get("outbound", "direct"))}
                for r in (data.get("process_rules") or [])
                if isinstance(r, dict)
            ],
            routing_rules=[
                {
                    "kind": str(r.get("kind", "domain_suffix")),
                    "value": str(r.get("value", "")),
                    "action": str(r.get("action", "direct")),
                }
                for r in (data.get("routing_rules") or [])
                if isinstance(r, dict) and r.get("value")
            ],
        )
