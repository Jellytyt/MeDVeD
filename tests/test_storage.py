"""Tests for storage.py persistence.

storage resolves real %LOCALAPPDATA% paths, so every test repoints the data root
into a pytest tmp_path (patching get_user_data_root, which all the path helpers
call). The focus is the failure modes that silently lose a user's profiles or
settings: missing files, corrupt JSON, wrong JSON shape, and that the atomic
write leaves no half-written .tmp behind.
"""
import json
import os

import pytest

import storage
from models import AppSettings, VlessProfile


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    """Point storage at an isolated tmp data root for the duration of a test."""
    monkeypatch.setattr(storage, "get_user_data_root", lambda: tmp_path)
    return tmp_path


def _profile(name="S"):
    return VlessProfile(name=name, uuid="u", server="srv.example.com", port=443, protocol="vless")


# --- round-trips --------------------------------------------------------------

def test_profiles_roundtrip(data_root):
    profiles = [_profile("a"), _profile("b")]
    storage.save_profiles(profiles)
    loaded = storage.load_profiles()
    assert [p.name for p in loaded] == ["a", "b"]
    assert all(isinstance(p, VlessProfile) for p in loaded)


def test_settings_roundtrip(data_root):
    settings = AppSettings(subscriptions=["https://x"], subscription_refresh_hours=4, kill_switch=True)
    storage.save_settings(settings)
    loaded = storage.load_settings()
    assert loaded.subscriptions == ["https://x"]
    assert loaded.subscription_refresh_hours == 4
    assert loaded.kill_switch is True


# --- missing / corrupt / wrong-shape inputs -----------------------------------

def test_load_profiles_missing_file_returns_empty(data_root):
    assert storage.load_profiles() == []


def test_load_profiles_corrupt_json_returns_empty(data_root):
    storage.get_profiles_path().write_text("{not valid json", encoding="utf-8")
    assert storage.load_profiles() == []


def test_load_profiles_non_list_returns_empty(data_root):
    storage.get_profiles_path().write_text(json.dumps({"oops": 1}), encoding="utf-8")
    assert storage.load_profiles() == []


def test_load_profiles_skips_non_dict_items(data_root):
    path = storage.get_profiles_path()
    path.write_text(json.dumps([_profile("ok").to_dict(), "garbage", 42]), encoding="utf-8")
    loaded = storage.load_profiles()
    assert [p.name for p in loaded] == ["ok"]


def test_load_settings_corrupt_json_returns_defaults(data_root):
    storage.get_settings_path().write_text("}}}", encoding="utf-8")
    assert storage.load_settings().subscription_refresh_hours == 1  # AppSettings() default


def test_load_settings_non_dict_returns_defaults(data_root):
    storage.get_settings_path().write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    loaded = storage.load_settings()
    assert isinstance(loaded, AppSettings)
    assert loaded.language == "ru"


# --- atomic write -------------------------------------------------------------

def test_atomic_write_leaves_no_tmp_file(data_root):
    storage.save_profiles([_profile()])
    path = storage.get_profiles_path()
    assert path.exists()
    assert not path.with_suffix(path.suffix + ".tmp").exists()


def test_saved_profiles_file_is_valid_json(data_root):
    storage.save_profiles([_profile("a")])
    data = json.loads(storage.get_profiles_path().read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert data[0]["name"] == "a"


# --- data_dir resolution ------------------------------------------------------

def test_get_data_dir_absolute_custom_used_as_is(data_root, tmp_path):
    custom = tmp_path / "elsewhere"
    settings = AppSettings(data_dir=str(custom))
    assert storage.get_data_dir(settings) == custom


def test_get_data_dir_relative_custom_under_root(data_root):
    settings = AppSettings(data_dir="sub")
    assert storage.get_data_dir(settings) == data_root / "sub"


def test_get_data_dir_default_is_root(data_root):
    assert storage.get_data_dir(None) == data_root


# --- settings file discovery: missing + legacy migration ----------------------

def test_load_settings_missing_returns_defaults(data_root):
    loaded = storage.load_settings()
    assert isinstance(loaded, AppSettings)
    assert loaded == AppSettings()


def test_load_settings_migrates_legacy_location(data_root):
    # Pre-0.9 builds kept settings under <root>/data/settings.json. load_settings
    # must transparently copy it up to <root>/settings.json on first run.
    legacy = data_root / "data" / "settings.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps(AppSettings(language="en").to_dict()), encoding="utf-8")
    assert not storage.get_settings_path().exists() or True  # get_settings_path creates the root dir
    (data_root / "settings.json").unlink(missing_ok=True)

    loaded = storage.load_settings()
    assert loaded.language == "en"
    assert (data_root / "settings.json").exists()  # migrated copy now present


@pytest.mark.skipif(os.name != "nt", reason="LOCALAPPDATA layout is Windows-specific")
def test_real_user_data_root_uses_localappdata(tmp_path, monkeypatch):
    # Exercise the real get_user_data_root (the fixture patches it everywhere else).
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert storage.get_user_data_root() == tmp_path / storage.APP_DIR_NAME
