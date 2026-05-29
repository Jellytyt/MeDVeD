from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List

from models import AppSettings, VlessProfile

APP_DIR_NAME = "vless_manager"


def get_user_data_root() -> Path:
    if os.name == "nt":
        base_dir = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
        if base_dir:
            return Path(base_dir) / APP_DIR_NAME
    return Path.home() / f".{APP_DIR_NAME}"


def get_data_dir(settings: AppSettings | None = None) -> Path:
    if settings and settings.data_dir:
        custom_dir = Path(settings.data_dir)
        if custom_dir.is_absolute():
            return custom_dir
        return get_user_data_root() / custom_dir
    return get_user_data_root()


def ensure_data_dir(settings: AppSettings | None = None) -> Path:
    data_dir = get_data_dir(settings)
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_profiles_path(settings: AppSettings | None = None) -> Path:
    return ensure_data_dir(settings) / "profiles.json"


def get_settings_path(_settings: AppSettings | None = None) -> Path:
    root = get_user_data_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / "settings.json"


def load_profiles(settings: AppSettings | None = None) -> List[VlessProfile]:
    path = get_profiles_path(settings)
    if not path.exists():
        return []

    try:
        with path.open("r", encoding="utf-8") as file:
            raw_items = json.load(file)
    except (json.JSONDecodeError, OSError):
        return []

    if not isinstance(raw_items, list):
        return []

    return [VlessProfile.from_dict(item) for item in raw_items if isinstance(item, dict)]


def _atomic_write_json(path: Path, payload: object) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def save_profiles(profiles: List[VlessProfile], settings: AppSettings | None = None) -> None:
    path = get_profiles_path(settings)
    payload = [profile.to_dict() for profile in profiles]
    _atomic_write_json(path, payload)


def load_settings() -> AppSettings:
    path = get_settings_path()
    legacy = get_user_data_root() / "data" / "settings.json"
    if not path.exists() and legacy.exists():
        try:
            path.write_bytes(legacy.read_bytes())
        except OSError:
            pass

    if not path.exists():
        return AppSettings()

    try:
        with path.open("r", encoding="utf-8") as file:
            raw_data = json.load(file)
    except (json.JSONDecodeError, OSError):
        return AppSettings()

    if not isinstance(raw_data, dict):
        return AppSettings()

    return AppSettings.from_dict(raw_data)


def save_settings(settings: AppSettings) -> None:
    path = get_settings_path(settings)
    _atomic_write_json(path, settings.to_dict())
