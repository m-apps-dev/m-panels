"""Generates the M Panels icon: assets/m_panels.png and assets/m_panels.ico (the bundled placeholder).
M Calendar family: dark background, thin cyan/blue edge, a glow from the center.
Run: python tools/ikon_uret.py   (does not touch the shared _ikonlar icon folder)
"""
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
S = 1024                       # drawn at 2x, then scaled down
TILES = [("#3aa0ff", (0, 0)), ("#3ddc84", (1, 0)), ("#ff9a3c", (0, 1)), ("#a56bff", (1, 1))]


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rounded_mask(size, box, radius):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle(box, radius=radius, fill=255)
    return m


def build():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # background: black at the edge, a dark blue glow in the center
    rg = Image.radial_gradient("L").resize((S, S), Image.BICUBIC)
    bg = Image.composite(Image.new("RGB", (S, S), (6, 9, 14)), Image.new("RGB", (S, S), (22, 44, 66)), rg)
    outer = rounded_mask(S, (24, 24, S - 24, S - 24), 190)
    inner = rounded_mask(S, (40, 40, S - 40, S - 40), 176)
    ring = Image.new("RGB", (S, S), (58, 160, 255))
    img.paste(ring, (0, 0), outer)
    img.paste(bg, (0, 0), inner)

    # four colored panel tiles (2x2) - each carries a small icon grid
    gap, margin = 44, 170
    tile = (S - 2 * margin - gap) // 2
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    for hexcol, (cx, cy) in TILES:
        x0, y0 = margin + cx * (tile + gap), margin + cy * (tile + gap)
        col = rgb(hexcol)
        gl = ImageDraw.Draw(glow)
        gl.rounded_rectangle((x0 - 6, y0 - 6, x0 + tile + 6, y0 + tile + 6), radius=70, fill=col + (150,))
    glow = glow.filter(ImageFilter.GaussianBlur(34))
    img = Image.alpha_composite(img, glow)
    d = ImageDraw.Draw(img)
    for hexcol, (cx, cy) in TILES:
        x0, y0 = margin + cx * (tile + gap), margin + cy * (tile + gap)
        col = rgb(hexcol)
        # vertical gradient body
        body = Image.new("RGB", (tile, tile))
        bd = ImageDraw.Draw(body)
        top = tuple(min(255, int(c * 1.0 + 40)) for c in col)
        bot = tuple(int(c * 0.45) for c in col)
        for y in range(tile):
            t = y / tile
            bd.line([(0, y), (tile, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bot)))
        m = rounded_mask(tile, (0, 0, tile - 1, tile - 1), 64)
        img.paste(body, (x0, y0), m)
        # bright top edge line
        d.arc((x0, y0, x0 + 130, y0 + 130), 180, 270, fill=(255, 255, 255, 150), width=8)
        # the small icon grid inside (3x3 dark rounded squares)
        n, g = 3, 14
        cell = (tile - 2 * 58 - (n - 1) * g) // n
        for i in range(n):
            for j in range(n):
                ix = x0 + 58 + i * (cell + g)
                iy = y0 + 58 + j * (cell + g)
                d.rounded_rectangle((ix, iy, ix + cell, iy + cell), radius=14, fill=(10, 16, 24, 215))
    return img.resize((512, 512), Image.LANCZOS)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    icon = build()
    icon.save(os.path.join(OUT, "m_panels.png"))
    icon.save(os.path.join(OUT, "m_panels.ico"), sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print("written:", OUT)
