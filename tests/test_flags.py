"""Tests for flags.py — the procedural flag images for the profile list.

flag_image() is pure Pillow (no Tk root needed), so it's unit-testable; the
Tk PhotoImage wrapper is exercised only in the GUI. We check the emoji→ISO
decoding, the name cleanup, image dimensions, the unknown-code fallback, and
that every registered flag renders without error.
"""
import flags


# --- emoji / name helpers -----------------------------------------------------

def test_iso_from_flag_emoji():
    assert flags.iso_from_flag_emoji("🇩🇪 Германия 1") == "DE"
    assert flags.iso_from_flag_emoji("🇫🇮 Finland") == "FI"
    assert flags.iso_from_flag_emoji("no flag here") == ""


def test_strip_flag_emoji_removes_only_flags():
    assert flags.strip_flag_emoji("🇩🇪 Германия 1") == "Германия 1"
    assert flags.strip_flag_emoji("ℹ️ info") == "ℹ️ info"  # non-flag emoji kept
    assert flags.strip_flag_emoji("🇳🇱") == ""


# --- image generation ---------------------------------------------------------

def test_flag_image_dimensions_and_mode():
    img = flags.flag_image("DE", height=12)
    assert img is not None
    assert img.size == (18, 12)  # 3:2 ratio
    assert img.mode == "RGBA"


def test_flag_image_germany_band_colours():
    img = flags.flag_image("DE", height=12)
    # interior pixels in each third (avoiding the 1px border)
    assert img.getpixel((9, 2))[:3] == flags.BLACK
    assert img.getpixel((9, 6))[:3] == flags.RED_DE
    assert img.getpixel((9, 10))[:3] == flags.GOLD


def test_flag_image_code_is_case_insensitive():
    assert flags.flag_image("de") is not None


def test_flag_image_unknown_and_empty_return_none():
    assert flags.flag_image("ZZ") is None
    assert flags.flag_image("") is None


def test_every_registered_flag_renders():
    for code in flags._REGISTRY:
        img = flags.flag_image(code, height=12)
        assert img is not None, code
        assert img.size == (18, 12), code


def test_flag_image_returns_independent_copies():
    a = flags.flag_image("FR", height=12)
    a.putpixel((0, 0), (1, 2, 3, 255))
    b = flags.flag_image("FR", height=12)
    assert b.getpixel((0, 0))[:3] != (1, 2, 3)  # cache not mutated
