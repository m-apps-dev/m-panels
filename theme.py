"""Shared theme: color, font, corner and title-bar values and background rendering, in one place.

Does NOT depend on tkinter (Pillow only): it is separate from the application so M Calendar can use the
same module. Applications read color/text/size constants from here and do not hard-code their own.
"""
import re

from PIL import Image, ImageDraw

# ------------------------------------------------------------------ color
ACCENT = "#4da3ff"               # accent: the snap preview frame and the highlighted target edge
KEY = "#010203"                 # transparent color key (window shape)
KEY_RGB = (1, 2, 3)
EDGE_HEX = "#05070a"            # the "black" at the panel edge
EDGE_RGB = (5, 7, 10)
DEFAULT_COLOR = "#3aa0ff"
TEXT_COLOR = "#e8e8ec"
GLOW_MIX = 0.42                 # center glow: mix of black and the panel color
# (key, hex). Display names live in strings.COLOR_NAMES.
PRESETS = [("blue", "#3aa0ff"), ("green", "#3ddc84"), ("orange", "#ff9a3c"), ("purple", "#a56bff"),
           ("cyan", "#2ad4d4"), ("red", "#ff5a6a"), ("pink", "#ff6bb5"), ("yellow", "#f2c94c")]
OPACITY = 0.95

# ------------------------------------------------------------------ metrics (corner, title bar)
HEAD_H = 30                     # title bar height (px)
RADIUS = 14                     # corner radius
BORDER = 2                      # colored border width
HEAD_PAD = 12                   # when the title text grows, bar height = line height + this
HEAD_GLYPH_FONT = ("Segoe UI", 11)           # collapse/expand arrow
HEAD_MENU_FONT = ("Segoe UI", 14, "bold")    # the ⋯ button

# ------------------------------------------------------------------ highlights / helper surfaces
WHITE = "#ffffff"
BRIGHT_MIX = 0.45               # title glyphs: panel color -> white
GRIP_MIX = 0.30                 # resize grip
HILITE_MIX = 0.40               # item under the pointer
SELECT_MIX = 0.62               # selected item
BROKEN_MIX = 0.60               # broken shortcut text (faded)
NOTE_BG_MIX = 0.16              # note text box background
NOTE_SEL_MIX = 0.55             # note text selection
DROP_HIGHLIGHT = WHITE          # drag-and-drop target frame
SURFACE = "#14171c"             # notification / preview background
ERROR_TEXT = "#ff9aa6"
DIALOG_ERROR_TEXT = "#b00020"   # error line inside light dialog windows
ICON_FALLBACK_RGBA = (120, 130, 150, 255)    # item whose icon could not be fetched
APP_ICON_BG_RGBA = (20, 28, 40, 255)         # application icon (fallback drawing)
APP_ICON_EDGE_RGBA = (58, 160, 255, 255)

# ------------------------------------------------------------------ calendar panel
CAL_NOW_LINE = "#f7768e"        # the "now" line in Day/Week
CAL_WARN = "#e0af68"            # short error/notice text inside a calendar panel
TIP_BG, TIP_FG = "#ffffe1", "#000000"   # settings-window tooltips (classic light tooltip colors)
CAL_BG_MIX = 0.20               # approximate panel background (edge black -> panel color), the fade target
CAL_EVENT_MIX = 0.62            # default event box color (edge black -> panel color)
CAL_NOW_MIX = 0.38              # highlight of the event happening now
CAL_GRID_MIX = 0.16             # grid lines (background -> white)
CAL_BUSY_MIN_W = 64             # Week: narrowest column that has events (px) while empty days shrink
CAL_EMPTY_MIN_W = 22            # Week: narrowest column without events (px)
CAL_HEAD_PAD = 8                # Week: padding around the day header text of a shrunken empty column (px, total)

# ------------------------------------------------------------------ text
FONT_FAMILY = "Segoe UI"
FONT_SIZE = 9
SIZE_MIN, SIZE_MAX = 6, 72

# Title and content text are configured SEPARATELY. Key prefix: "title_" / "content_".
STYLE_FIELDS = ("font", "size", "color", "bold", "italic")
TITLE_STYLE = {"font": FONT_FAMILY, "size": FONT_SIZE, "color": TEXT_COLOR, "bold": True, "italic": False}
CONTENT_STYLE = {"font": FONT_FAMILY, "size": FONT_SIZE, "color": TEXT_COLOR, "bold": False, "italic": False}


def style_defaults():
    """Flat config keys: title_font, title_size, ... content_italic."""
    out = {}
    for role, st in (("title", TITLE_STYLE), ("content", CONTENT_STYLE)):
        for k in STYLE_FIELDS:
            out[f"{role}_{k}"] = st[k]
    return out


STYLE_KEYS = list(style_defaults())


# ------------------------------------------------------------------ color helpers
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def is_hex_color(v):
    return isinstance(v, str) and bool(_HEX.match(v))


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_hex(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in c)


def blend(c1, c2, t):
    a, b = hex_rgb(c1), hex_rgb(c2)
    return rgb_hex([x + (y - x) * t for x, y in zip(a, b)])


# ------------------------------------------------------------------ style: migration and validation
def normalize_font_size(v, default=FONT_SIZE):
    """Clamp a text size to 6-72; an unreadable value (text, empty, None, bool) -> default."""
    if isinstance(v, bool) or v is None:
        return default
    try:
        n = int(round(float(str(v).strip().replace(",", "."))))
    except (ValueError, TypeError, OverflowError):
        return default
    return max(SIZE_MIN, min(SIZE_MAX, n))


def migrate_style(d):
    """Old config (single `font_size` + `text_color`) -> the SAME value for title and content. Changes d in place.
    New keys that already exist are left alone; the old keys are removed."""
    size, color = d.pop("font_size", None), d.pop("text_color", None)
    for role in ("title", "content"):
        if size is not None:
            d.setdefault(f"{role}_size", size)
        if color is not None:
            d.setdefault(f"{role}_color", color)
    return d


def sanitize_style(d):
    """Coerce the title/content text fields to valid values (changes d in place)."""
    base = style_defaults()
    for key, dflt in base.items():
        v = d.get(key, dflt)
        k = key.split("_", 1)[1]
        if k == "size":
            v = normalize_font_size(v, dflt)
        elif k == "color":
            v = v if is_hex_color(v) else dflt
        elif k == "font":
            v = v.strip() if isinstance(v, str) and v.strip() else dflt
        else:                                   # bold / italic
            v = v if isinstance(v, bool) else bool(v) if isinstance(v, (int, float)) else dflt
        d[key] = v
    return d


def style_of(cfg, role):
    """From cfg: {'font','size','color','bold','italic'} (role: 'title' | 'content')."""
    return {k: cfg[f"{role}_{k}"] for k in STYLE_FIELDS}


def tk_font_spec(st):
    """tkinter font spec (name, size, styles) — st: result of style_of()."""
    styles = (["bold"] if st["bold"] else []) + (["italic"] if st["italic"] else [])
    return (st["font"], int(st["size"]), *(styles or ["normal"]))


# ------------------------------------------------------------------ background
def make_bg(w, h, color, radius=RADIUS, border=BORDER):
    """Rounded panel background: thin colored border + a radial glow opening from black at the edge to the center.
    The outer shape uses a hard mask so the transparent color key cannot bleed color at the edge."""
    S = 3

    def mask(inset):
        m = Image.new("L", (w * S, h * S), 0)
        ImageDraw.Draw(m).rounded_rectangle(
            (inset * S, inset * S, (w - inset) * S - 1, (h - inset) * S - 1),
            radius=max(1, (radius - inset) * S), fill=255)
        return m.resize((w, h), Image.LANCZOS).point(lambda v: 255 if v >= 128 else 0)
    outer, inner = mask(0), mask(border)
    rg = Image.radial_gradient("L").resize((w, h), Image.BICUBIC).point(lambda v: int(255 * (v / 255) ** 1.35))
    center = Image.new("RGB", (w, h), hex_rgb(blend("#000000", color, GLOW_MIX)))
    edge = Image.new("RGB", (w, h), EDGE_RGB)
    glow = Image.composite(edge, center, rg)
    base = Image.new("RGB", (w, h), KEY_RGB)
    base.paste(Image.new("RGB", (w, h), hex_rgb(color)), (0, 0), outer)
    base.paste(glow, (0, 0), inner)
    return base
