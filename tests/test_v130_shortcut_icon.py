"""v1.3: the desktop shortcut icon (assets/m_panels_shortcut.ico, the four-tile icon).
The file is valid and holds every size; it is drawn by theme.tile_icon (the Start button drawing), once per size; kur.py gives
it to the Desktop and Startup shortcuts and falls back to assets/m_panels.ico when it is missing. Temporary folders only:
the real desktop and Startup folders are never touched."""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import ikon_uret  # noqa: E402
import kur  # noqa: E402
import theme  # noqa: E402
import winutil  # noqa: E402
from PIL import Image  # noqa: E402

SIZES = {16, 24, 32, 48, 64, 128, 256}
ICO = os.path.join(ROOT, "assets", "m_panels_shortcut.ico")
OLD = os.path.join(ROOT, "assets", "m_panels.ico")


def frames(path):
    """{size: RGBA image} for every size stored in the .ico (the file is closed again)."""
    out = {}
    with Image.open(path) as im:
        for s in sorted(im.info["sizes"]):
            im.size = s
            out[s[0]] = im.copy().convert("RGBA")
    return out


def sizes_of(path):
    with Image.open(path) as im:
        return {s[0] for s in im.info["sizes"]}, im.format


class TestIcoFile(unittest.TestCase):
    def test_file_exists_and_is_a_real_ico(self):
        self.assertTrue(os.path.isfile(ICO))
        with open(ICO, "rb") as f:
            self.assertEqual(f.read(4), b"\x00\x00\x01\x00")                  # ICONDIR: reserved 0, type 1 (icon)
        self.assertEqual(sizes_of(ICO)[1], "ICO")

    def test_every_size_is_inside(self):
        self.assertEqual(sizes_of(ICO)[0], SIZES)
        self.assertEqual(set(frames(ICO)), SIZES)
        self.assertEqual(set(ikon_uret.SHORTCUT_SIZES), SIZES)

    def test_each_size_is_the_tile_icon_drawn_at_that_size(self):
        got = frames(ICO)
        for n in SIZES:
            self.assertEqual(got[n].size, (n, n))
            self.assertEqual(got[n].tobytes(), theme.tile_icon(n).tobytes(), "size %d" % n)

    def test_has_four_colors_and_a_transparent_gap(self):
        im = frames(ICO)[256]
        gap = im.getpixel((128, 128))
        self.assertEqual(gap[3], 0)
        # the middle of each tile is opaque and leans toward its own color (blue, green, orange, purple)
        for (x, y), want in (((64, 64), "#3aa0ff"), ((192, 64), "#3ddc84"), ((64, 192), "#ff9a3c"), ((192, 192), "#a56bff")):
            px = im.getpixel((x, y))
            self.assertEqual(px[3], 255)
            w = theme.hex_rgb(want)
            self.assertEqual(px[:3].index(max(px[:3])), w.index(max(w)), (x, y, px))

    def test_the_old_icon_is_still_there(self):
        self.assertTrue(os.path.isfile(OLD))
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "assets", "m_panels.png")))

    def test_generator_writes_it_and_does_not_need_the_old_files(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.ico")
            ikon_uret.build_shortcut_ico(p)
            self.assertEqual(set(frames(p)), SIZES)
            self.assertEqual(frames(p)[32].tobytes(), frames(ICO)[32].tobytes())
        with open(os.path.join(ROOT, "tools", "ikon_uret.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("theme.tile_icon", src)                                   # the drawing is reused, not copied
        self.assertNotIn("m_panels.ico", src.split("def build_shortcut_ico")[1].split("if __name__")[0])


class TestShortcutIconPath(unittest.TestCase):
    def test_new_icon_is_chosen(self):
        self.assertEqual(os.path.normcase(winutil.shortcut_icon_path()), os.path.normcase(ICO))

    def test_missing_new_icon_falls_back_to_the_old_one(self):
        real = os.path.isfile
        with mock.patch.object(os.path, "isfile", lambda p: False if os.path.basename(p) == "m_panels_shortcut.ico" else real(p)):
            self.assertEqual(os.path.normcase(winutil.shortcut_icon_path()), os.path.normcase(OLD))

    def test_neither_icon_gives_none(self):
        with mock.patch.object(os.path, "isfile", return_value=False):
            self.assertIsNone(winutil.shortcut_icon_path())

    def test_tray_window_and_bar_icons_are_unchanged(self):
        self.assertEqual(os.path.normcase(winutil.app_icon_path()), os.path.normcase(OLD))


class TestKur(unittest.TestCase):
    def run_kur(self):
        seen = []
        real = kur.make_shortcut

        def spy(folder, pythonw, **kw):
            seen.append(kw.get("icon"))
            return real(folder, pythonw, **kw)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(kur, "write_bats", return_value=[]), \
                mock.patch.object(winutil, "get_startup_dir", side_effect=AssertionError("real Startup folder")), \
                mock.patch.object(winutil, "get_real_desktop", side_effect=AssertionError("real desktop")), \
                mock.patch.object(kur, "make_shortcut", spy), mock.patch("sys.stdout"):
            kur.main(["--target", d, "--skip-pip"])
            self.assertEqual(len(os.listdir(d)), 2)
        return seen

    def test_both_shortcuts_get_the_new_icon(self):
        seen = self.run_kur()
        self.assertEqual([os.path.normcase(s) for s in seen], [os.path.normcase(ICO)] * 2)

    def test_both_shortcuts_fall_back_to_the_old_icon(self):
        real = os.path.isfile
        with mock.patch.object(os.path, "isfile", lambda p: False if os.path.basename(p) == "m_panels_shortcut.ico" else real(p)):
            seen = self.run_kur()
        self.assertEqual([os.path.normcase(s) for s in seen], [os.path.normcase(OLD)] * 2)

    def test_the_lnk_really_points_at_the_new_icon(self):
        import pythoncom  # noqa: F401
        with tempfile.TemporaryDirectory() as d, mock.patch.object(kur, "write_bats", return_value=[]), mock.patch("sys.stdout"):
            kur.main(["--target", d, "--skip-pip"])
            sl = winutil._shelllink()
            sl.QueryInterface(pythoncom.IID_IPersistFile).Load(os.path.join(d, "M Panels.lnk"), 0)
            path, idx = sl.GetIconLocation()
        self.assertEqual(os.path.normcase(path), os.path.normcase(ICO))


if __name__ == "__main__":
    unittest.main()
