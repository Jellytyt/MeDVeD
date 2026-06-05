"""Procedurally-drawn country flags for the profile list.

Why procedural and not bundled PNGs: Tkinter on Windows can't render flag
emoji (the Segoe UI Emoji font has no flag glyphs — a 🇩🇪 shows up as "DE"),
so to display real flags we have to draw images. Rather than ship ~30 PNG
assets, we paint each flag with Pillow on demand and cache it. No binary
assets in the repo, and the set is trivial to extend.

Coverage is the European set the app targets plus a few common extras. Simple
flags (tri-bands, Nordic crosses, Swiss/Greek/Czech) are accurate; a few
complex ones (GB, EU, US, TR) are recognisable approximations at 12 px — at
that size a 5-point star and a filled dot are indistinguishable anyway. Codes
not in the registry return None and the caller just shows clean text.

`flag_image()` returns a Pillow Image (pure, unit-testable). `flag_photoimage()`
wraps it in a Tk PhotoImage and needs a live Tk root, so it's only called from
the GUI.
"""
from __future__ import annotations

import math
from typing import Callable, Dict, Optional

from PIL import Image, ImageDraw

# --- palette (approximate official colours) ----------------------------------
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GOLD = (255, 204, 0)
RED_DE = (221, 0, 0)
NL_RED, NL_BLUE = (174, 28, 40), (33, 70, 139)
RU_BLUE, RU_RED = (0, 57, 166), (213, 43, 30)
AT_RED = (237, 41, 57)
HU_RED, HU_GREEN = (206, 41, 57), (71, 112, 80)
BG_GREEN, BG_RED = (0, 150, 110), (214, 38, 18)
LT_YELLOW, LT_GREEN, LT_RED = (253, 185, 19), (0, 106, 68), (193, 39, 45)
LU_RED, LU_BLUE = (237, 41, 57), (0, 161, 228)
EE_BLUE = (0, 114, 206)
ES_RED, ES_YELLOW = (198, 11, 30), (255, 196, 0)
LV_MAROON = (158, 48, 57)
FR_BLUE, FR_RED = (0, 35, 149), (237, 41, 57)
IT_GREEN, IT_RED = (0, 140, 69), (205, 33, 42)
IE_GREEN, IE_ORANGE = (22, 155, 98), (255, 136, 62)
BE_YELLOW, BE_RED = (253, 209, 0), (239, 51, 64)
RO_BLUE, RO_YELLOW, RO_RED = (0, 43, 127), (252, 209, 22), (206, 17, 38)
PL_RED = (220, 20, 60)
UA_BLUE, UA_YELLOW = (0, 87, 183), (255, 215, 0)
SE_BLUE, SE_YELLOW = (0, 106, 167), (254, 204, 0)
FI_BLUE = (0, 53, 128)
DK_RED = (198, 12, 48)
NO_RED, NO_BLUE = (186, 12, 47), (0, 32, 91)
IS_BLUE, IS_RED = (0, 56, 151), (215, 40, 40)
CH_RED = (213, 43, 30)
GR_BLUE = (13, 94, 175)
CZ_RED, CZ_BLUE = (215, 20, 26), (17, 69, 126)
EU_BLUE, EU_YELLOW = (0, 51, 153), (255, 204, 0)
UK_BLUE, UK_RED = (1, 33, 105), (200, 16, 46)
PT_GREEN, PT_RED = (0, 102, 71), (255, 0, 0)
HR_RED, HR_BLUE = (255, 0, 0), (0, 0, 139)
SI_BLUE, SI_RED = (0, 51, 153), (237, 41, 57)
SK_BLUE, SK_RED = (11, 78, 162), (238, 28, 37)
JP_RED = (188, 0, 45)
US_RED, US_BLUE = (178, 34, 52), (60, 59, 110)
TR_RED = (227, 10, 23)

_BORDER = (90, 90, 90)


def _img(w: int, h: int, fill=(0, 0, 0, 0)) -> Image.Image:
    return Image.new("RGBA", (w, h), fill)


def _safe_rect(d, box, fill) -> None:
    """Draw a rectangle only if it's non-degenerate — at ~12 px a many-striped
    flag (US has 13) can round to a band with y1 < y0, which PIL rejects."""
    x0, y0, x1, y1 = box
    if x1 >= x0 and y1 >= y0:
        d.rectangle(box, fill=fill)


def _horizontal(w, h, colors, ratios=None):
    img = _img(w, h)
    d = ImageDraw.Draw(img)
    ratios = ratios or [1] * len(colors)
    total = float(sum(ratios))
    acc, y0 = 0.0, 0
    for i, (color, r) in enumerate(zip(colors, ratios)):
        acc += r
        y1 = h - 1 if i == len(colors) - 1 else round(h * acc / total) - 1
        d.rectangle([0, y0, w - 1, y1], fill=color)
        y0 = y1 + 1
    return img


def _vertical(w, h, colors, ratios=None):
    img = _img(w, h)
    d = ImageDraw.Draw(img)
    ratios = ratios or [1] * len(colors)
    total = float(sum(ratios))
    acc, x0 = 0.0, 0
    for i, (color, r) in enumerate(zip(colors, ratios)):
        acc += r
        x1 = w - 1 if i == len(colors) - 1 else round(w * acc / total) - 1
        d.rectangle([x0, 0, x1, h - 1], fill=color)
        x0 = x1 + 1
    return img


def _nordic(w, h, field, cross, inner=None):
    img = _img(w, h, field)
    d = ImageDraw.Draw(img)
    t = max(2, round(h * 0.20))
    cx, cy = round(w * 0.36), h // 2

    def draw_cross(color, thick):
        d.rectangle([cx - thick // 2, 0, cx - thick // 2 + thick - 1, h - 1], fill=color)
        d.rectangle([0, cy - thick // 2, w - 1, cy - thick // 2 + thick - 1], fill=color)

    draw_cross(cross, t)
    if inner:
        draw_cross(inner, max(1, t // 2))
    return img


def _swiss(w, h):
    img = _img(w, h, CH_RED)
    d = ImageDraw.Draw(img)
    t = max(2, round(h * 0.20))
    cx, cy, arm = w // 2, h // 2, round(h * 0.30)
    d.rectangle([cx - t // 2, cy - arm, cx - t // 2 + t - 1, cy + arm], fill=WHITE)
    d.rectangle([cx - arm, cy - t // 2, cx + arm, cy - t // 2 + t - 1], fill=WHITE)
    return img


def _greece(w, h):
    img = _img(w, h, WHITE)
    d = ImageDraw.Draw(img)
    for i in range(9):
        if i % 2 == 0:
            _safe_rect(d, [0, round(h * i / 9), w - 1, round(h * (i + 1) / 9) - 1], GR_BLUE)
    canton = round(h * 5 / 9)
    d.rectangle([0, 0, canton - 1, canton - 1], fill=GR_BLUE)
    t = max(1, round(canton * 0.22))
    c = canton // 2
    d.rectangle([c - t // 2, 0, c - t // 2 + t - 1, canton - 1], fill=WHITE)
    d.rectangle([0, c - t // 2, canton - 1, c - t // 2 + t - 1], fill=WHITE)
    return img


def _czech(w, h):
    img = _img(w, h, WHITE)
    d = ImageDraw.Draw(img)
    d.rectangle([0, h // 2, w - 1, h - 1], fill=CZ_RED)
    d.polygon([(0, 0), (round(w * 0.5), h // 2), (0, h - 1)], fill=CZ_BLUE)
    return img


def _eu(w, h):
    img = _img(w, h, EU_BLUE)
    d = ImageDraw.Draw(img)
    cx, cy, ring = w / 2.0, h / 2.0, h * 0.32
    r = max(1, round(h * 0.06))
    for k in range(12):
        ang = math.pi / 2 - k * math.pi / 6
        x, y = cx + ring * math.cos(ang), cy - ring * math.sin(ang)
        d.ellipse([x - r, y - r, x + r, y + r], fill=EU_YELLOW)
    return img


def _uk(w, h):
    img = _img(w, h, UK_BLUE)
    d = ImageDraw.Draw(img)
    d.line([(0, 0), (w, h)], fill=WHITE, width=max(2, round(h * 0.20)))
    d.line([(0, h), (w, 0)], fill=WHITE, width=max(2, round(h * 0.20)))
    d.line([(0, 0), (w, h)], fill=UK_RED, width=max(1, round(h * 0.08)))
    d.line([(0, h), (w, 0)], fill=UK_RED, width=max(1, round(h * 0.08)))
    tw = max(2, round(h * 0.28))
    d.rectangle([w // 2 - tw // 2, 0, w // 2 - tw // 2 + tw - 1, h - 1], fill=WHITE)
    d.rectangle([0, h // 2 - tw // 2, w - 1, h // 2 - tw // 2 + tw - 1], fill=WHITE)
    tr = max(1, round(h * 0.16))
    d.rectangle([w // 2 - tr // 2, 0, w // 2 - tr // 2 + tr - 1, h - 1], fill=UK_RED)
    d.rectangle([0, h // 2 - tr // 2, w - 1, h // 2 - tr // 2 + tr - 1], fill=UK_RED)
    return img


def _japan(w, h):
    img = _img(w, h, WHITE)
    d = ImageDraw.Draw(img)
    r = round(h * 0.30)
    cx, cy = w // 2, h // 2
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=JP_RED)
    return img


def _usa(w, h):
    img = _img(w, h, WHITE)
    d = ImageDraw.Draw(img)
    for i in range(13):
        if i % 2 == 0:
            _safe_rect(d, [0, round(h * i / 13), w - 1, round(h * (i + 1) / 13) - 1], US_RED)
    cw, ch = round(w * 0.40), round(h * 7 / 13)
    d.rectangle([0, 0, cw - 1, ch - 1], fill=US_BLUE)
    for yi in range(2):
        for xi in range(3):
            x = round(cw * (0.25 + xi * 0.25))
            y = round(ch * (0.3 + yi * 0.4))
            d.ellipse([x - 1, y - 1, x + 1, y + 1], fill=WHITE)
    return img


def _turkey(w, h):
    img = _img(w, h, TR_RED)
    d = ImageDraw.Draw(img)
    r = round(h * 0.30)
    cx, cy = round(w * 0.40), h // 2
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=WHITE)
    r2 = round(r * 0.78)
    cx2 = cx + round(r * 0.32)
    d.ellipse([cx2 - r2, cy - r2, cx2 + r2, cy + r2], fill=TR_RED)
    d.ellipse([cx + r, cy - 2, cx + r + 3, cy + 1], fill=WHITE)
    return img


def _h(*colors, ratios=None):
    return lambda w, h: _horizontal(w, h, list(colors), ratios)


def _v(*colors):
    return lambda w, h: _vertical(w, h, list(colors))


def _n(field, cross, inner=None):
    return lambda w, h: _nordic(w, h, field, cross, inner)


_REGISTRY: Dict[str, Callable[[int, int], Image.Image]] = {
    # horizontal tri-bands
    "DE": _h(BLACK, RED_DE, GOLD),
    "NL": _h(NL_RED, WHITE, NL_BLUE),
    "RU": _h(WHITE, RU_BLUE, RU_RED),
    "AT": _h(AT_RED, WHITE, AT_RED),
    "HU": _h(HU_RED, WHITE, HU_GREEN),
    "BG": _h(WHITE, BG_GREEN, BG_RED),
    "LT": _h(LT_YELLOW, LT_GREEN, LT_RED),
    "LU": _h(LU_RED, WHITE, LU_BLUE),
    "EE": _h(EE_BLUE, BLACK, WHITE),
    "ES": _h(ES_RED, ES_YELLOW, ES_RED, ratios=[1, 2, 1]),
    "LV": _h(LV_MAROON, WHITE, LV_MAROON, ratios=[2, 1, 2]),
    "HR": _h(HR_RED, WHITE, HR_BLUE),
    "SI": _h(WHITE, SI_BLUE, SI_RED),
    "SK": _h(WHITE, SK_BLUE, SK_RED),
    "PL": _h(WHITE, PL_RED),
    "UA": _h(UA_BLUE, UA_YELLOW),
    # vertical tri-bands
    "FR": _v(FR_BLUE, WHITE, FR_RED),
    "IT": _v(IT_GREEN, WHITE, IT_RED),
    "IE": _v(IE_GREEN, WHITE, IE_ORANGE),
    "BE": _v(BLACK, BE_YELLOW, BE_RED),
    "RO": _v(RO_BLUE, RO_YELLOW, RO_RED),
    "PT": _v(PT_GREEN, PT_RED),
    # Nordic crosses
    "SE": _n(SE_BLUE, SE_YELLOW),
    "FI": _n(WHITE, FI_BLUE),
    "DK": _n(DK_RED, WHITE),
    "NO": _n(NO_RED, WHITE, NO_BLUE),
    "IS": _n(IS_BLUE, WHITE, IS_RED),
    # specials
    "CH": _swiss,
    "GR": _greece,
    "CZ": _czech,
    "EU": _eu,
    "GB": _uk,
    "UK": _uk,
    "JP": _japan,
    "US": _usa,
    "TR": _turkey,
}

_image_cache: Dict[tuple, Optional[Image.Image]] = {}
_photo_cache: Dict[tuple, object] = {}


def iso_from_flag_emoji(text: str) -> str:
    """Decode the first regional-indicator pair in `text` to an ISO code
    (🇩🇪 -> 'DE'). Returns '' if there's no flag emoji."""
    indicators = [c for c in text if 0x1F1E6 <= ord(c) <= 0x1F1FF]
    if len(indicators) >= 2:
        return "".join(chr(ord("A") + ord(c) - 0x1F1E6) for c in indicators[:2])
    return ""


def strip_flag_emoji(text: str) -> str:
    """Remove regional-indicator (flag) characters, leaving the rest of the name
    intact. Other emoji (ℹ️ etc.) are left alone."""
    return "".join(c for c in text if not (0x1F1E6 <= ord(c) <= 0x1F1FF)).strip()


def flag_image(code: str, height: int = 12) -> Optional[Image.Image]:
    """Pillow flag image for an ISO-3166 alpha-2 code, or None if unsupported."""
    if not code:
        return None
    code = code.upper()
    key = (code, height)
    if key in _image_cache:
        cached = _image_cache[key]
        return cached.copy() if cached is not None else None
    draw = _REGISTRY.get(code)
    if draw is None:
        _image_cache[key] = None
        return None
    width = max(2, round(height * 1.5))
    img = draw(width, height).convert("RGBA")
    ImageDraw.Draw(img).rectangle([0, 0, width - 1, height - 1], outline=_BORDER)
    _image_cache[key] = img
    return img.copy()


def flag_photoimage(code: str, height: int = 12):
    """Tk PhotoImage flag, cached, or None. Requires a live Tk root, so call
    only from the GUI thread after the main window exists."""
    if not code:
        return None
    code = code.upper()
    key = (code, height)
    if key in _photo_cache:
        return _photo_cache[key]
    img = flag_image(code, height)
    if img is None:
        _photo_cache[key] = None
        return None
    try:
        from PIL import ImageTk
        photo = ImageTk.PhotoImage(img)
    except Exception:
        photo = None
    _photo_cache[key] = photo
    return photo
