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


def contrast_mark(fill):
    """A mark color that shows on `fill` (#rrggbb): dark on light colors, light on dark ones."""
    r, g, b = hex_rgb(fill)
    return "#000000" if 0.299 * r + 0.587 * g + 0.114 * b > 140 else "#ffffff"


# ------------------------------------------------------------------ bar (v1.2): a flat strip; its buttons have rounded corners
BAR_HEIGHT = 32                 # px, the space the bar reserves at the top of the main monitor
BAR_PAD_X = 12                  # px between the text and the screen edge
# Tasks section (v1.2 step 2)
BAR_BTN_MAX_W = 180            # px, widest task button
BAR_BTN_MIN_W = 40             # px, narrowest task button while titles are shown
BAR_ICON_ONLY_W = 32           # px, width of every button while titles are off (BAR_BTN_PAD + icon + BAR_BTN_PAD)
BAR_BTN_GAP = 4                # px between task buttons (the rounded corners need air)
BAR_BTN_PAD = 8                # px inside a task button, left and right
BAR_BTN_TOP = 3                # px from the top of the bar to the top of a button
BAR_BTN_H = 26                 # px, button height (the bar is 32: 3 above, 2 below, then the 1 px bottom line)
BAR_BTN_RADIUS = 6             # px, corner radius (the panels use 14 on a 30 px title bar)
BAR_BTN_BORDER = 1             # px, frame width (panels: 2)
BAR_ICON = 16                  # px, the icon of a task button
BAR_ICON_GAP = 6               # px between the icon and the title
BAR_TEXT_MIN_ROOM = 30         # px: a button shows its title only when at least this much room is left for it
BAR_DIM_ICON_ALPHA = 0.5       # minimized windows: the icon is drawn this opaque
BAR_TIP_DELAY_MS = 500
BAR_COLOR_KEYS = ("background", "button", "border", "text", "active")     # what the user may change (bar.colors)
BAR_BORDER_MIX = 0.55          # default frame: bar background -> DEFAULT_COLOR (the panel blue, muted)
BAR_BUTTON_MIX = 0.06          # default button: bar background -> text color
BAR_HOVER_MIX = 0.10           # hover fill: button -> text color
BAR_HOVER_BORDER_MIX = 0.35    # hover frame: frame -> text color
BAR_ACTIVE_MIX = 0.14          # active fill: button -> text color
BAR_FAINT_MIX = 0.55           # minimized: frame and text fade this far toward the bar background
BAR_LINE_MIX = 0.60            # bottom line: bar background -> frame
BAR_TIP_MIX = 0.10             # tooltip: bar background -> text color
BTN_STATES = ("normal", "hover", "active", "minimized")
# Left end of the bar (steps 4, 5; spacing changed in step 5, 24.11): the Start place is 32 px (its hit area is all of it),
# the icon sits centered in it, then BAR_BTN_GAP, the search button, BAR_BTN_GAP, and the window buttons. All derived.
BAR_START_W = 32               # px, the Start place (x 0-31)
BAR_START_ICON = 28            # px, the Start icon (square): ONE fixed value, not a setting (30 looked too big on the real bar)
BAR_START_PAD = (BAR_START_W - BAR_START_ICON) // 2              # 2 px left of the icon (and (BAR_HEIGHT - icon) // 2 above it)
BAR_START_BTN_X = 0
BAR_START_BTN_W = BAR_START_W
BAR_START_GLOW = 1.28          # hover: the icon is brightened by this factor (no frame, no pressed/active look)
BAR_SEARCH_X = BAR_START_W + BAR_BTN_GAP                          # 36
BAR_SEARCH_W = 32              # px, the search zone (= its button)
BAR_SEARCH_BTN_W = BAR_SEARCH_W
BAR_SEARCH_BTN_X = BAR_SEARCH_X
BAR_LEFT_RESERVE = BAR_SEARCH_X + BAR_SEARCH_W + BAR_BTN_GAP     # 72: the window buttons start here
# The search window (step 4)
SEARCH_W = 460                 # px, window width
SEARCH_ROWS = 8                # most rows shown under the text box
SEARCH_ROW_H = 28              # px, one row
SEARCH_ENTRY_H = 40            # px, the text box area (box + padding)
SEARCH_NOTICE_H = 22           # px, the one-line notice under the rows (only while there is one)
SEARCH_PAD = 8                 # px inside a row, left
SEARCH_ICON = 16               # px


def search_icon(size, color):
    """The magnifier (PIL RGBA, size x size, transparent background) in `color` (#rrggbb), drawn 8x larger and shrunk."""
    big = size * 8
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rgba = hex_rgb(color) + (255,)
    lw = max(1, round(big * 0.11))
    r0, r1 = big * 0.12, big * 0.62                        # the lens
    d.ellipse((r0, r0, r1, r1), outline=rgba, width=lw)
    a, b = big * 0.57, big * 0.88                          # the handle, round at the far end
    d.line((a, a, b, b), fill=rgba, width=lw)
    d.ellipse((b - lw / 2, b - lw / 2, b + lw / 2, b + lw / 2), fill=rgba)
    return img.resize((size, size), Image.LANCZOS)


def start_icon(size, color):
    """The Start button's FALLBACK glyph (used only when the app icon cannot be had at all): a 3x3 grid of dots (no Windows logo). PIL RGBA, size x size, transparent background, in
    `color` (#rrggbb), drawn 8x larger and shrunk."""
    big = size * 8
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rgba = hex_rgb(color) + (255,)
    r = big * 0.075
    for i in range(3):
        for j in range(3):
            cx, cy = big * (0.2 + 0.3 * i), big * (0.2 + 0.3 * j)
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=rgba)
    return img.resize((size, size), Image.LANCZOS)


def start_icon_pos(size, bar_h=BAR_HEIGHT):
    """(x, y) of the Start icon: centered in the Start zone across, and in the bar height (the 1 px bottom line counts as the
    bottom pad: 28 px icon, 2 px above, 2 px below = 1 px + the line)."""
    return (BAR_START_W - size) // 2, (bar_h - size) // 2


START_TILES = (("#3aa0ff", 0, 0), ("#3ddc84", 1, 0), ("#ff9a3c", 0, 1), ("#a56bff", 1, 1))   # same colors/places as tools/ikon_uret.py
_TILE_ICONS = {}


def _tile_icon_draw(size, ss=4):
    S = size * ss
    tile = int(round(S / (2 + 44.0 / 320.0)))              # the four tiles fill the square; the gap keeps the old proportion
    gap = S - 2 * tile
    u = tile / 320.0
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for hexcol, cx, cy in START_TILES:
        x0, y0 = int(round(cx * (tile + gap))), int(round(cy * (tile + gap)))
        col = hex_rgb(hexcol)
        top, bot = tuple(min(255, c + 40) for c in col), tuple(int(c * 0.45) for c in col)
        body = Image.new("RGB", (tile, tile))
        bd = ImageDraw.Draw(body)
        for y in range(tile):                               # vertical gradient, light to dark
            t = y / tile
            bd.line([(0, y), (tile, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bot)))
        mask = Image.new("L", (tile, tile), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, tile - 1, tile - 1), radius=64 * u, fill=255)
        img.paste(body, (x0, y0), mask)
        d.arc((x0, y0, x0 + 130 * u, y0 + 130 * u), 180, 270, fill=(255, 255, 255, 150), width=max(1, int(8 * u)))
    return img.resize((size, size), Image.LANCZOS)


def tile_icon(size):
    """The Start button and tray icon: four colored tiles (blue, green, orange, purple; flat, no grid, no background, no rim)
    filling size x size, transparent between them. Drawn at 4x and shrunk (LANCZOS), once per size (a copy is returned)."""
    size = int(size)
    img = _TILE_ICONS.get(size)
    if img is None:
        img = _TILE_ICONS[size] = _tile_icon_draw(size)
    return img.copy()


def start_glow(img, factor=BAR_START_GLOW):
    """The hover look of the Start icon: the same RGBA image, its color channels brightened (alpha untouched)."""
    from PIL import ImageEnhance
    img = img.convert("RGBA")
    r, g, b, a = img.split()
    rgb = ImageEnhance.Brightness(Image.merge("RGB", (r, g, b))).enhance(factor)
    out = rgb.convert("RGBA")
    out.putalpha(a)
    return out


def bar_palette(colors=None):
    """Every bar color: the five the user may change (`colors` holds only the changed ones) and what follows from them."""
    c = colors if isinstance(colors, dict) else {}

    def pick(k, default):
        return c[k] if k in c and is_hex_color(c[k]) else default
    bg = pick("background", SURFACE)
    text = pick("text", TEXT_COLOR)
    button = pick("button", blend(bg, text, BAR_BUTTON_MIX))
    border = pick("border", blend(bg, DEFAULT_COLOR, BAR_BORDER_MIX))
    active = pick("active", ACCENT)
    return {"background": bg, "button": button, "border": border, "text": text, "active": active,
            "line": blend(bg, border, BAR_LINE_MIX), "hover_bg": blend(button, text, BAR_HOVER_MIX),
            "hover_border": blend(border, text, BAR_HOVER_BORDER_MIX), "active_bg": blend(button, text, BAR_ACTIVE_MIX),
            "faint_border": blend(border, bg, BAR_FAINT_MIX), "dim_text": blend(text, bg, BAR_FAINT_MIX),
            "tip_bg": blend(bg, text, BAR_TIP_MIX)}


def btn_colors(pal, state):
    """(fill, frame) of a button in one of BTN_STATES."""
    if state == "active":
        return pal["active_bg"], pal["active"]
    if state == "hover":
        return pal["hover_bg"], pal["hover_border"]
    if state == "minimized":
        return pal["button"], pal["faint_border"]
    return pal["button"], pal["border"]


_BTN_CACHE = {}


def make_btn(w, h, fill, border, radius=BAR_BTN_RADIUS, border_w=BAR_BTN_BORDER):
    """A bar button background: RGBA, rounded, `border` frame and `fill` inside, the corners fully transparent (the bar
    shows through). Same masks as the panels (rounded_masks). Cached by its arguments."""
    key = (w, h, fill.lower(), border.lower(), radius, border_w)
    img = _BTN_CACHE.get(key)
    if img is None:
        if len(_BTN_CACHE) > 256:
            _BTN_CACHE.clear()
        outer, inner = rounded_masks(w, h, radius, border_w)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        img.paste(Image.new("RGBA", (w, h), hex_rgb(border) + (255,)), (0, 0), outer)
        img.paste(Image.new("RGBA", (w, h), hex_rgb(fill) + (255,)), (0, 0), inner)
        _BTN_CACHE[key] = img
    return img


BAR_BG = bar_palette()["background"]                  # the defaults, for code that needs no user colors
BAR_LINE = bar_palette()["line"]


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
def rounded_masks(w, h, radius, border):
    """(outer, inner) hard 0/255 masks of a rounded rectangle and of the same shape inset by `border` (3x supersampled:
    smooth corners, no half-transparent pixels). Panels (make_bg) and bar buttons (make_btn) share this."""
    S = 3

    def mask(inset):
        m = Image.new("L", (w * S, h * S), 0)
        ImageDraw.Draw(m).rounded_rectangle(
            (inset * S, inset * S, (w - inset) * S - 1, (h - inset) * S - 1),
            radius=max(1, (radius - inset) * S), fill=255)
        return m.resize((w, h), Image.LANCZOS).point(lambda v: 255 if v >= 128 else 0)
    return mask(0), mask(border)


def make_bg(w, h, color, radius=RADIUS, border=BORDER):
    """Rounded panel background: thin colored border + a radial glow opening from black at the edge to the center.
    The outer shape uses a hard mask so the transparent color key cannot bleed color at the edge."""
    outer, inner = rounded_masks(w, h, radius, border)
    rg = Image.radial_gradient("L").resize((w, h), Image.BICUBIC).point(lambda v: int(255 * (v / 255) ** 1.35))
    center = Image.new("RGB", (w, h), hex_rgb(blend("#000000", color, GLOW_MIX)))
    edge = Image.new("RGB", (w, h), EDGE_RGB)
    glow = Image.composite(edge, center, rg)
    base = Image.new("RGB", (w, h), KEY_RGB)
    base.paste(Image.new("RGB", (w, h), hex_rgb(color)), (0, 0), outer)
    base.paste(glow, (0, 0), inner)
    return base
