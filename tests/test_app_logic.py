"""Tests for the pure helper logic that lives inside app.py.

app.py is the GUI module, so importing it pulls in customtkinter / pystray / PIL.
We importorskip it: on a minimal box without the GUI stack these tests skip
rather than error (the dedicated import-smoke step in CI still guards the import
itself). What we test here has nothing to do with the GUI — it is the logic the
auto-updater and download UI depend on:

  * _parse_version  -> decides whether a release is newer (10 > 9, not "10" < "9")
  * _format_bytes / _format_speed -> the download progress readout
  * _read_changelog_section -> the "What's new" body shown after an update
  * VlessApp._sha256_file -> the checksum compared before running an installer
"""
import hashlib
import os

import pytest

app = pytest.importorskip("app")

from models import VlessProfile  # noqa: E402  (after importorskip on purpose)


def _profile(name="S", server="srv.example.com"):
    return VlessProfile(name=name, uuid="u", server=server, port=443, protocol="vless")


# --- _parse_version -----------------------------------------------------------

def test_parse_version_basic():
    assert app._parse_version("1.2.3") == (1, 2, 3)
    assert app._parse_version("v1.2.3") == (1, 2, 3)


def test_parse_version_pads_short():
    assert app._parse_version("1.2") == (1, 2, 0)
    assert app._parse_version("1") == (1, 0, 0)


def test_parse_version_strips_suffix():
    assert app._parse_version("v1.2.3-rc1") == (1, 2, 3)


def test_parse_version_garbage_is_zero():
    assert app._parse_version("garbage") == (0, 0, 0)
    assert app._parse_version("") == (0, 0, 0)


def test_parse_version_numeric_not_lexical_ordering():
    # The whole point: 0.9.10 must be newer than 0.9.9 (string compare gets this wrong).
    assert app._parse_version("0.9.10") > app._parse_version("0.9.9")
    assert app._parse_version("1.0.0") > app._parse_version("0.9.99")
    assert app._parse_version("2.0.0") > app._parse_version("1.9.9")


def test_parse_version_equal_versions_not_greater():
    assert not (app._parse_version("0.9.9") > app._parse_version("v0.9.9"))


# --- _format_bytes / _format_speed -------------------------------------------

@pytest.mark.parametrize("value, expected", [
    (0, "0 B"),
    (512, "512 B"),
    (1024, "1.0 KB"),
    (1536, "1.5 KB"),
    (1024 ** 2, "1.0 MB"),
    (int(1.5 * 1024 ** 2), "1.5 MB"),
    (1024 ** 3, "1.00 GB"),
])
def test_format_bytes(value, expected):
    assert app._format_bytes(value) == expected


def test_format_speed_appends_per_second():
    assert app._format_speed(1024) == "1.0 KB/s"
    assert app._format_speed(0) == "0 B/s"


# --- _read_changelog_section --------------------------------------------------

def test_read_changelog_section_returns_current_version_body():
    body = app._read_changelog_section(app.__version__)
    assert body, "changelog section for the current version must not be empty"


def test_read_changelog_section_accepts_v_prefix():
    assert app._read_changelog_section("v" + app.__version__) == app._read_changelog_section(app.__version__)


def test_read_changelog_section_does_not_bleed_into_next_section():
    # The body for 0.9.9 must stop at the "## v0.9.8" header, not swallow it.
    body = app._read_changelog_section("0.9.9")
    if body:  # only meaningful while 0.9.9 is in CHANGELOG.md
        assert "## v0.9.8" not in body
        assert "SHA-256" in body


def test_read_changelog_section_unknown_version_empty():
    assert app._read_changelog_section("99.99.99") == ""


# --- VlessApp._sha256_file ----------------------------------------------------

def test_sha256_file_matches_hashlib(tmp_path):
    payload = b"MeDVeD installer bytes \x00\x01\x02" * 100000  # spans multiple read chunks
    f = tmp_path / "setup.bin"
    f.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()
    assert app.VlessApp._sha256_file(f) == expected


def test_sha256_file_is_lowercase_hex(tmp_path):
    f = tmp_path / "empty.bin"
    f.write_bytes(b"")
    digest = app.VlessApp._sha256_file(f)
    assert digest == hashlib.sha256(b"").hexdigest()
    assert digest == digest.lower()


# --- _list_running_processes --------------------------------------------------

def test_list_running_processes_returns_sorted_exe_names():
    # OS integration (tasklist) — assert the contract, not specific processes:
    # a list of '.exe' base names, de-duplicated and case-insensitively sorted.
    procs = app._list_running_processes()
    assert isinstance(procs, list)
    assert all(isinstance(p, str) for p in procs)
    assert all(p.lower().endswith(".exe") for p in procs)
    assert procs == sorted(procs, key=str.lower)
    assert len(procs) == len(set(procs))
    if os.name == "nt":
        # On Windows something is always running (this test process included).
        assert procs


# --- info/stub detection (#4: inert subscription rows) ------------------------

@pytest.mark.parametrize("server", ["127.0.0.1", "0.0.0.0", "localhost", "::1"])
def test_is_fake_profile_by_stub_host(server):
    assert app.VlessApp._is_fake_profile(_profile(server=server)) is True


@pytest.mark.parametrize("name", [
    "Приложение не поддерживается",
    "App unsupported",
    "this client is not supported",
])
def test_is_fake_profile_by_name_marker(name):
    assert app.VlessApp._is_fake_profile(_profile(name=name)) is True


def test_is_fake_profile_real_server_is_false():
    assert app.VlessApp._is_fake_profile(_profile(name="🇩🇪 Germany 1", server="de1.example.com")) is False


def test_default_auto_enabled_european_in_bypass_out():
    assert app.VlessApp._default_auto_enabled("Германия 1") is True
    assert app.VlessApp._default_auto_enabled("🇫🇮 Finland") is True
    assert app.VlessApp._default_auto_enabled("Обход (Выделенный канал)") is False
    assert app.VlessApp._default_auto_enabled("Tokyo Japan") is False


# --- subscription title parsing (#3) -----------------------------------------

def _b64(text):
    import base64
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def test_try_b64_text_decodes_utf8():
    assert app._try_b64_text(_b64("Привет")) == "Привет"


def test_try_b64_text_rejects_garbage_and_binary():
    assert app._try_b64_text("!!!not base64!!!") == ""
    import base64
    assert app._try_b64_text(base64.b64encode(b"\x00\x01\x02").decode()) == ""


def test_filename_from_content_disposition_plain():
    assert app._filename_from_content_disposition('attachment; filename="My Sub.yaml"') == "My Sub"


def test_filename_from_content_disposition_rfc5987():
    assert app._filename_from_content_disposition("attachment; filename*=UTF-8''%D0%9C%D0%BE%D0%B9") == "Мой"


def test_decode_title_base64_prefixed():
    headers = {"profile-title": "base64:" + _b64("Моя подписка")}
    assert app._decode_subscription_title(headers) == "Моя подписка"


def test_decode_title_plain_text_with_space_is_literal():
    assert app._decode_subscription_title({"Profile-Title": "Premium VPN"}) == "Premium VPN"


def test_decode_title_bare_base64_token():
    assert app._decode_subscription_title({"profile-title": _b64("NL")}) == "NL"


def test_decode_title_content_disposition_fallback():
    headers = {"content-disposition": 'attachment; filename="VPN List.txt"'}
    assert app._decode_subscription_title(headers) == "VPN List"


def test_decode_title_absent_returns_empty():
    assert app._decode_subscription_title({}) == ""
