"""v1.2 step 3c: the bar's buttons get a thin rounded frame (the panels' masks), user colors, hover, a faded icon for minimized
windows, and "Show window titles" off = icons only (letter tile for a window with no icon).
Real sizes and colors are checked: the pixels of theme.make_btn, the size/position of the images on the real canvas, the
colors recorded for each button. No test touches the real foreground (the base class replaces winutil.take_foreground)."""
import hashlib
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import infoclock  # noqa: E402
import mpanels  # noqa: E402
import strings as ui  # noqa: E402
import tasks  # noqa: E402
import theme  # noqa: E402
import winutil  # noqa: E402
from PIL import Image, ImageTk  # noqa: E402
from test_v120_step1 import INFO_ONLY, ON  # noqa: E402
from test_v120_step2 import Base2  # noqa: E402

MAKE_BG_HASHES = {                       # sha256 of make_bg(...).tobytes(), taken BEFORE rounded_masks was shared
    (60, 30, "#3aa0ff"): "195b2d02152e61942998b10bf95f33316fd9678d32f5564beb375063ff6d04e7",
    (380, 280, "#ff9a3c"): "5d911b3926c669b2e5ce5d7ea4e6e587176e21d7cf93e69116c016281f9095e1",
    (41, 17, "#a56bff"): "15308b1570d8fcdd86cc5643ff5e09cf11e408c6a4d87f0465699d4ccaf2bc97",
}


def rgb(h):
    return theme.hex_rgb(h)


class TestTheme(unittest.TestCase):
    def test_make_bg_is_pixel_for_pixel_what_it_was(self):
        for (w, h, c), want in MAKE_BG_HASHES.items():
            self.assertEqual(hashlib.sha256(theme.make_bg(w, h, c).tobytes()).hexdigest(), want, (w, h, c))

    def test_the_button_uses_the_panels_masks(self):
        outer, inner = theme.rounded_masks(60, 26, theme.BAR_BTN_RADIUS, theme.BAR_BTN_BORDER)
        img = theme.make_btn(60, 26, "#102030", "#aabbcc")
        for xy in ((0, 0), (30, 0), (30, 1), (30, 13), (59, 25), (5, 3)):
            o, i = outer.getpixel(xy) == 255, inner.getpixel(xy) == 255
            px = img.getpixel(xy)
            if i:
                self.assertEqual(px, rgb("#102030") + (255,), xy)
            elif o:
                self.assertEqual(px, rgb("#aabbcc") + (255,), xy)
            else:
                self.assertEqual(px[3], 0, xy)

    def test_button_pixels_frame_fill_and_transparent_corners(self):
        w, h = theme.BAR_ICON_ONLY_W, theme.BAR_BTN_H
        img = theme.make_btn(w, h, "#102030", "#aabbcc")
        self.assertEqual(img.size, (w, h))
        self.assertEqual(img.mode, "RGBA")
        self.assertEqual(img.getpixel((w // 2, 0)), rgb("#aabbcc") + (255,))                 # the frame, 1 px
        self.assertEqual(img.getpixel((w // 2, theme.BAR_BTN_BORDER)), rgb("#102030") + (255,))
        self.assertEqual(img.getpixel((0, h // 2)), rgb("#aabbcc") + (255,))
        self.assertEqual(img.getpixel((w // 2, h // 2)), rgb("#102030") + (255,))
        for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            self.assertEqual(img.getpixel(corner)[3], 0, corner)                                 # rounded: bar shows through
        self.assertEqual((theme.BAR_BTN_RADIUS, theme.BAR_BTN_BORDER, theme.BAR_BTN_H), (6, 1, 26))

    def test_the_button_image_is_cached(self):
        self.assertIs(theme.make_btn(50, 26, "#111111", "#222222"), theme.make_btn(50, 26, "#111111", "#222222"))
        self.assertIsNot(theme.make_btn(50, 26, "#111111", "#222222"), theme.make_btn(50, 26, "#111111", "#222223"))

    def test_the_four_states_are_all_different(self):
        pal = theme.bar_palette()
        looks = [theme.btn_colors(pal, s) for s in theme.BTN_STATES]
        self.assertEqual(len(set(looks)), 4)
        self.assertEqual(theme.btn_colors(pal, "active"), (pal["active_bg"], pal["active"]))

    def test_defaults_are_the_decided_ones(self):
        pal = theme.bar_palette()
        self.assertEqual(pal["background"], theme.SURFACE)
        self.assertEqual(pal["border"], theme.blend(theme.SURFACE, theme.DEFAULT_COLOR, 0.55))
        self.assertEqual(pal["button"], theme.blend(theme.SURFACE, theme.TEXT_COLOR, 0.06))
        self.assertEqual((pal["text"], pal["active"]), (theme.TEXT_COLOR, theme.ACCENT))
        self.assertEqual(theme.BAR_BG, pal["background"])

    def test_user_colors_flow_into_the_derived_ones(self):
        base = theme.bar_palette()
        pal = theme.bar_palette({"button": "#336699", "border": "#ff0000", "text": "#ffffff", "background": "#000000",
                                 "active": "#00ff00"})
        for k, v in (("button", "#336699"), ("border", "#ff0000"), ("text", "#ffffff"), ("background", "#000000"),
                     ("active", "#00ff00")):
            self.assertEqual(pal[k], v)
        self.assertEqual(pal["hover_bg"], theme.blend("#336699", "#ffffff", theme.BAR_HOVER_MIX))
        self.assertEqual(pal["faint_border"], theme.blend("#ff0000", "#000000", theme.BAR_FAINT_MIX))
        self.assertNotEqual(pal["line"], base["line"])
        self.assertEqual(theme.bar_palette({"border": "red", "nope": "#123456"}), base)       # junk is ignored

    def test_the_icon_is_faded_to_half(self):
        img = Image.new("RGBA", (4, 4), (10, 20, 30, 200))
        d = tasks.dim_icon(img)
        self.assertEqual(d.getpixel((1, 1)), (10, 20, 30, 100))

    def test_letter_of_a_title(self):
        self.assertEqual(tasks.tile_letter("notes"), "N")
        self.assertEqual(tasks.tile_letter("  éclair"), "É")
        self.assertEqual(tasks.tile_letter(""), "")
        self.assertEqual(tasks.tile_letter("   "), "")


class TestConfig(unittest.TestCase):
    def test_colors_keep_only_valid_known_values(self):
        d = infoclock.sanitize({"colors": {"border": "#AABBCC", "text": "red", "button": 5, "nope": "#112233",
                                           "background": "#12345", "active": "#00FF00"}})
        self.assertEqual(d["colors"], {"border": "#aabbcc", "active": "#00ff00"})
        for junk in (None, "x", 5, [], {"colors": 5}):
            self.assertEqual(infoclock.sanitize(junk)["colors"], {})

    def test_an_old_config_without_the_keys_gets_the_defaults(self):
        old = {"enabled": True, "info": {"enabled": True, "time_format": "24h", "show_date": True},
               "tasks": {"enabled": True}}
        d = infoclock.sanitize(old)
        self.assertEqual(d["tasks"], {"enabled": True, "show_titles": True})
        self.assertEqual(d["colors"], {})

    def test_show_titles_must_be_a_bool_and_unknown_task_keys_stay(self):
        self.assertEqual(infoclock.sanitize({"tasks": {"show_titles": "no", "later": 1}})["tasks"],
                         {"enabled": True, "show_titles": True, "later": 1})
        self.assertFalse(infoclock.sanitize({"tasks": {"show_titles": False}})["tasks"]["show_titles"])

    def test_the_example_config_has_the_new_keys(self):
        import json
        with open(os.path.join(ROOT, "config.example.json"), encoding="utf-8") as f:
            bar = json.load(f)["bar"]
        d = infoclock.defaults()
        self.assertEqual(bar["tasks"], d["tasks"])
        self.assertEqual(bar["colors"], d["colors"])


class Look(Base2):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(winutil, "overlay_show", return_value=True)
        p.start()
        self.addCleanup(p.stop)
        self.icons = {}

    def view(self, titles, active=0, minimized=(), with_icon=True):
        ents = tuple(tasks.Entry(100 + i, t, i in minimized, "x.exe") for i, t in enumerate(titles))
        img = ImageTk.PhotoImage(Image.new("RGBA", (16, 16), (255, 0, 0, 255)))
        dim = ImageTk.PhotoImage(Image.new("RGBA", (16, 16), (255, 0, 0, 120)))
        self._keep = (img, dim)
        return tasks.View(ents, 100 + active if active is not None else 0, lambda h: img, lambda h: dim,
                          lambda h: with_icon)

    def bar(self, bar=INFO_ONLY):
        app = self.open(bar=dict(bar, tasks={"enabled": False}, search={"enabled": False},
                                  start={"enabled": False}), window=False)   # (steps 4, 5: no search / Start button here)
        return app, app.bar.win

    @staticmethod
    def images(win):
        cv = win.cv
        return [(cv.coords(i), str(cv.itemcget(i, "image"))) for i in cv.find_all() if cv.type(i) == "image"]

    @staticmethod
    def texts(win):
        cv = win.cv
        return [(cv.itemcget(i, "text"), cv.itemcget(i, "fill")) for i in cv.find_all() if cv.type(i) == "text"]


class TestButtonLook(Look):
    def test_real_size_position_and_gap_of_the_buttons(self):
        app, win = self.bar()
        win.set_tasks(self.view(["One", "Two", "Three"], active=None))
        self.assertEqual([b["w"] for b in win.buttons], [theme.BAR_BTN_MAX_W] * 3)
        self.assertEqual({b["h"] for b in win.buttons}, {26})
        xs = [b["x"] for b in win.buttons]
        self.assertEqual(xs[1] - xs[0], theme.BAR_BTN_MAX_W + theme.BAR_BTN_GAP)
        self.assertEqual(theme.BAR_BTN_GAP, 4)
        backs = [im for im in self.images(win) if im[0][1] == theme.BAR_BTN_TOP]          # the rounded backgrounds
        self.assertEqual([int(c[0][0]) for c in backs], xs)
        for c, name in backs:
            self.assertEqual((win.cv.tk.call("image", "width", name), win.cv.tk.call("image", "height", name)),
                             (theme.BAR_BTN_MAX_W, 26))
        self.assertLessEqual(theme.BAR_BTN_TOP + 26, theme.BAR_HEIGHT - 2)                  # room for the bottom line

    def test_each_state_is_drawn_with_its_own_colors(self):
        app, win = self.bar()
        win.set_tasks(self.view(["A", "B", "C"], active=1, minimized=(2,)))
        pal = theme.bar_palette()
        got = [(b["state"], b["fill"], b["frame"]) for b in win.buttons]
        self.assertEqual(got[0], ("normal",) + theme.btn_colors(pal, "normal"))
        self.assertEqual(got[1], ("active",) + theme.btn_colors(pal, "active"))
        self.assertEqual(got[2], ("minimized",) + theme.btn_colors(pal, "minimized"))
        self.assertEqual(len({g[1:] for g in got}), 3)

    def test_the_canvas_uses_the_image_of_that_state(self):
        app, win = self.bar()
        win.set_tasks(self.view(["A", "B"], active=1))
        names = {int(c[0]): n for c, n in self.images(win) if c[1] == theme.BAR_BTN_TOP}
        for b in win.buttons:
            want = str(win.painter.background(b["w"], 26, b["state"], win.pal))
            self.assertEqual(names[b["x"]], want)

    def test_user_colors_change_what_is_drawn(self):
        app, win = self.bar()
        win.set_tasks(self.view(["A"], active=None))
        before = win.buttons[0]["frame"]
        win.set_look({"border": "#ff0000", "text": "#00ff00", "background": "#101010"}, True)
        self.assertEqual(win.buttons[0]["frame"], "#ff0000")
        self.assertNotEqual(before, "#ff0000")
        self.assertEqual(win.cv.cget("bg"), "#101010")
        self.assertEqual(str(win.top.cget("bg")), "#101010")
        self.assertIn(("A", "#00ff00"), self.texts(win))
        self.assertIn(("Tuesday 24 November · 14:32", "#00ff00"), self.texts(win))             # the clock follows the text color

    def test_the_bar_controller_applies_colors_to_the_window(self):
        app, win = self.bar()
        app.bar.set_colors({"active": "#00ff00"})
        self.assertEqual(win.pal["active"], "#00ff00")

    def test_minimized_uses_the_faded_icon_and_the_dim_title(self):
        app, win = self.bar()
        v = self.view(["One", "Two"], active=None, minimized=(1,))
        win.set_tasks(v)
        icons = [n for c, n in self.images(win) if c[1] != theme.BAR_BTN_TOP]
        self.assertEqual(icons[0], str(v.icon_of(100)))
        self.assertEqual(icons[1], str(v.dim_of(101)))
        self.assertNotEqual(icons[0], icons[1])
        by = dict(self.texts(win))
        self.assertEqual((by["One"], by["Two"]), (theme.bar_palette()["text"], theme.bar_palette()["dim_text"]))

    def test_hover_shows_and_goes(self):
        app, win = self.bar()
        win.set_tasks(self.view(["A", "B"], active=0))
        b = win.buttons[1]
        win.cv.event_generate("<Motion>", x=b["x"] + 5, y=10)
        win.top.update()
        self.assertEqual(win.buttons[1]["state"], "hover")
        self.assertEqual((win.buttons[1]["fill"], win.buttons[1]["frame"]), theme.btn_colors(win.pal, "hover"))
        self.assertEqual(win.buttons[0]["state"], "active")
        win.cv.event_generate("<Leave>")
        win.top.update()
        self.assertEqual(win.buttons[1]["state"], "normal")

    def test_the_active_button_keeps_its_look_under_the_pointer(self):
        app, win = self.bar()
        win.set_tasks(self.view(["A", "B"], active=0))
        win.cv.event_generate("<Motion>", x=win.buttons[0]["x"] + 5, y=10)
        win.top.update()
        self.assertEqual(win.buttons[0]["state"], "active")

    def test_hover_on_a_minimized_button_and_back_to_faint(self):
        app, win = self.bar()
        win.set_tasks(self.view(["A", "B"], active=None, minimized=(1,)))
        win.cv.event_generate("<Motion>", x=win.buttons[1]["x"] + 5, y=10)
        win.top.update()
        self.assertEqual(win.buttons[1]["state"], "hover")
        win.cv.event_generate("<Leave>")
        win.top.update()
        self.assertEqual(win.buttons[1]["state"], "minimized")

    def test_moving_inside_one_button_does_not_redraw(self):
        app, win = self.bar()
        win.set_tasks(self.view(["A", "B"], active=0))
        b = win.buttons[1]
        win.cv.event_generate("<Motion>", x=b["x"] + 5, y=10)
        win.top.update()
        with mock.patch.object(win, "draw") as draw:
            win.cv.event_generate("<Motion>", x=b["x"] + 9, y=12)
            win.top.update()
        draw.assert_not_called()

    def test_a_click_still_works_after_the_hover_redraw(self):
        app, win = self.bar()
        win.set_tasks(self.view(["A", "B"], active=0))
        got = []
        win.on_task = lambda h, prev: got.append(h)
        b = win.buttons[1]
        win.cv.event_generate("<Motion>", x=b["x"] + 5, y=10)
        win.cv.event_generate("<ButtonPress-1>", x=b["x"] + 5, y=10)
        win.cv.event_generate("<ButtonRelease-1>", x=b["x"] + 5, y=10)
        win.top.update()
        self.assertEqual(got, [101])

    def test_the_backgrounds_are_cached_between_draws(self):
        app, win = self.bar()
        win.set_tasks(self.view(["A", "B"], active=0))
        n = len(win.painter._photos)
        for _ in range(5):
            win.draw()
        self.assertEqual(len(win.painter._photos), n)

    def test_the_plus_n_button_has_the_frame_and_hover_too(self):
        app, win = self.bar()
        win.set_tasks(self.view(["Window %d" % i for i in range(60)], active=None))
        more = win.buttons[-1]
        self.assertEqual((more["kind"], more["h"]), ("more", 26))
        self.assertEqual(more["state"], "normal")
        win.cv.event_generate("<Motion>", x=more["x"] + 5, y=10)
        win.top.update()
        self.assertEqual(win.buttons[-1]["state"], "hover")


class TestIconsOnly(Look):
    def titles_off(self, win, titles, **kw):
        win.set_look({}, False)
        win.set_tasks(self.view(titles, **kw))

    def test_every_button_is_32_wide_and_has_no_title(self):
        app, win = self.bar()
        self.titles_off(win, ["One", "Two", "Three"], active=1)
        self.assertEqual([b["w"] for b in win.buttons], [theme.BAR_ICON_ONLY_W] * 3)
        self.assertEqual(theme.BAR_ICON_ONLY_W, 2 * theme.BAR_BTN_PAD + theme.BAR_ICON)
        self.assertEqual([b["shown"] for b in win.buttons], ["", "", ""])
        titles = {t for t, _ in self.texts(win)}
        self.assertFalse({"One", "Two", "Three"} & titles)
        xs = [b["x"] for b in win.buttons]
        self.assertEqual(xs[1] - xs[0], 32 + theme.BAR_BTN_GAP)

    def test_the_icon_is_centred_in_the_button(self):
        app, win = self.bar()
        self.titles_off(win, ["One"], active=None)
        b = win.buttons[0]
        icon = [c for c, n in self.images(win) if c[1] != theme.BAR_BTN_TOP][0]
        self.assertEqual(icon[0] - b["x"], (32 - theme.BAR_ICON) // 2)

    def test_the_tooltip_still_gives_the_full_title(self):
        app, win = self.bar()
        self.titles_off(win, ["A fairly long document title.docx"], active=None)
        b = win.buttons[0]
        win.cv.event_generate("<Motion>", x=b["x"] + 5, y=10)
        win.top.update()
        self.assertIsNotNone(win._tip_job)
        win._show_tip(b, 200)
        self.addCleanup(win._hide_tip)
        self.assertEqual(win._tip.winfo_children()[0].cget("text"), "A fairly long document title.docx")

    def test_the_overflow_count_uses_the_icon_width(self):
        app, win = self.bar()
        n = 80
        self.titles_off(win, ["W%d" % i for i in range(n)], active=None)
        info_w = win._font.measure(win.text) + 2 * theme.BAR_PAD_X
        avail = 1920 - theme.BAR_PAD_X - info_w - theme.BAR_LEFT_RESERVE
        tasks_b = [b for b in win.buttons if b["kind"] == "task"]
        more = win.buttons[-1]
        self.assertEqual(more["kind"], "more")
        self.assertEqual(len(tasks_b) + len(more["rest"]), n)
        self.assertEqual({b["w"] for b in tasks_b}, {32})
        slots = (avail + theme.BAR_BTN_GAP) // (32 + theme.BAR_BTN_GAP)
        self.assertEqual(len(tasks_b), slots - 1)
        self.assertGreater(len(tasks_b), 40)                                                # 32 px buttons: far more fit than 40 px ones
        self.assertLessEqual(more["x"] + more["w"], 1920 - theme.BAR_PAD_X - info_w)

    def test_a_wide_plus_n_label_makes_only_that_button_wider(self):
        app, win = self.bar()
        self.titles_off(win, ["W%d" % i for i in range(300)], active=None)
        more = win.buttons[-1]
        label = ui.BAR_OVERFLOW.format(n=len(more["rest"]))
        self.assertGreaterEqual(len(more["rest"]), 100)
        need = win._font.measure(label) + 2 * theme.BAR_BTN_PAD
        self.assertEqual(more["w"], max(32, need))
        self.assertGreater(more["w"], 32)
        info_w = win._font.measure(win.text) + 2 * theme.BAR_PAD_X
        self.assertLessEqual(more["x"] + more["w"], 1920 - theme.BAR_PAD_X - info_w)

    def test_layout_icons_numbers(self):
        k, w, more, more_w = tasks.layout_icons(3, 500, lambda s: 10 * len(s), lambda m: "+%d" % m)
        self.assertEqual((k, w, more, more_w), (3, 32, 0, 32))
        k, w, more, more_w = tasks.layout_icons(10, 150, lambda s: 10 * len(s), lambda m: "+%d" % m)
        self.assertEqual((w, k + more), (32, 10))                                           # 150 px: 4 slots of 32 + 3 gaps
        self.assertEqual(k, 3)
        self.assertLessEqual(k * 36 + more_w, 150 + 4)
        k, w, more, more_w = tasks.layout_icons(5, 20, lambda s: 10, lambda m: "+%d" % m)
        self.assertEqual((k, more), (0, 5))

    def test_letter_tile_for_a_window_without_an_icon(self):
        app, win = self.bar()
        self.titles_off(win, ["notes", "Browser"], active=None, with_icon=False)
        self.assertEqual([b["letter"] for b in win.buttons], ["N", "B"])
        self.assertIn(("N", win.pal["text"]), self.texts(win))

    def test_no_letter_when_the_window_has_its_own_icon(self):
        app, win = self.bar()
        self.titles_off(win, ["notes"], active=None, with_icon=True)
        self.assertEqual(win.buttons[0]["letter"], "")
        self.assertNotIn("N", {t for t, _ in self.texts(win)})

    def test_an_empty_title_shows_the_generic_icon_only(self):
        app, win = self.bar()
        self.titles_off(win, [""], active=None, with_icon=False)
        self.assertEqual(win.buttons[0]["letter"], "")
        self.assertEqual(len([1 for c, n in self.images(win) if c[1] != theme.BAR_BTN_TOP]), 1)

    def test_titles_on_never_draws_a_letter(self):
        app, win = self.bar()
        win.set_tasks(self.view(["notes"], active=None, with_icon=False))
        self.assertEqual(win.buttons[0]["letter"], "")

    def test_minimized_is_still_visible_without_a_title(self):
        app, win = self.bar()
        self.titles_off(win, ["A", "B"], active=None, minimized=(1,))
        self.assertNotEqual((win.buttons[0]["fill"], win.buttons[0]["frame"]), (win.buttons[1]["fill"], win.buttons[1]["frame"]))
        icons = [n for c, n in self.images(win) if c[1] != theme.BAR_BTN_TOP]
        self.assertNotEqual(icons[0], icons[1])                                              # the icon itself is faded

    def test_titles_back_on_restores_the_wide_buttons(self):
        app, win = self.bar()
        self.titles_off(win, ["A", "B"], active=None)
        win.set_look({}, True)
        self.assertEqual([b["w"] for b in win.buttons], [theme.BAR_BTN_MAX_W] * 2)

    def test_the_real_tasks_controller_makes_the_faded_icon_and_forgets_it(self):
        made = []
        src = tasks.FakeSource(["Notes"])
        t = tasks.Tasks(src, mock.Mock(), lambda: None, make_photo=lambda im: made.append(im) or ("photo", im.size),
                        actions=tasks.FakeActions())
        t.start()
        hw = t.model.entries[0].hwnd
        self.assertFalse(t.has_icon(hw))
        t.on_icon(hw, Image.new("RGBA", (16, 16), (1, 2, 3, 255)))
        self.assertTrue(t.has_icon(hw))
        self.assertEqual(t.dim_of(hw), ("photo", (16, 16)))
        self.assertEqual(made[-1].getpixel((0, 0))[3], int(255 * theme.BAR_DIM_ICON_ALPHA))
        v = t.view()
        self.assertTrue(v.has_icon(hw))
        t.stop()
        self.assertFalse(t.has_icon(hw))


class TestSettingsLook(Look):
    def open_settings(self, bar=ON, **kw):
        app = self.open(bar=bar, window=False, **kw)
        app.open_settings()
        w = app.settings_win
        self.addCleanup(self._close_settings, w)
        return app, w

    @staticmethod
    def _close_settings(w):
        try:
            if w.win.winfo_exists():
                w.win.destroy()
        except Exception:                                                                   # the app (and Tk) may be gone
            pass

    def pick(self, w, key, color):
        with mock.patch.object(mpanels.colorchooser, "askcolor", return_value=((0, 0, 0), color)):
            w.pick_bar_color(key)

    def test_the_tab_has_the_controls_with_english_names(self):
        app, w = self.open_settings()
        self.assertEqual(w.cb_bar_titles.cget("text"), "Show window titles")
        self.assertEqual(list(w.bar_col_ui), ["background", "button", "border", "text", "active"])
        self.assertEqual([ui.BAR_COLOR_NAMES[k] for k in w.bar_col_ui],
                         ["Bar background", "Button", "Button border", "Text", "Active window"])
        self.assertEqual(w.btn_bar_colors_reset.cget("text"), "Reset colors")
        self.assertFalse(w.dirty())
        self.assertEqual(w.v_bar_titles.get(), True)

    def test_swatches_show_the_derived_defaults_and_reset_is_disabled(self):
        app, w = self.open_settings()
        pal = theme.bar_palette()
        for key, (sw, rb) in w.bar_col_ui.items():
            self.assertEqual(str(sw.cget("bg")), pal[key])
            self.assertIn("disabled", rb.state())
        self.assertIn("disabled", w.btn_bar_colors_reset.state())

    def test_picking_a_color_is_pending_until_apply(self):
        app, w = self.open_settings()
        self.pick(w, "border", "#ff0000")
        self.assertTrue(w.dirty())
        self.assertEqual(app.cfg["bar"]["colors"], {})                                      # nothing before Apply
        self.assertEqual(app.bar.win.pal["border"], theme.bar_palette()["border"])
        self.assertEqual(str(w.bar_col_ui["border"][0].cget("bg")), "#ff0000")
        self.assertNotIn("disabled", w.bar_col_ui["border"][1].state())
        w.apply()
        self.assertEqual(app.cfg["bar"]["colors"], {"border": "#ff0000"})
        self.assertEqual(app.bar.win.pal["border"], "#ff0000")
        self.assertEqual(self.cfg_file()["bar"]["colors"], {"border": "#ff0000"})
        self.assertFalse(w.dirty())

    def test_discard_brings_the_applied_colors_back(self):
        app, w = self.open_settings()
        self.pick(w, "text", "#00ff00")
        self.assertTrue(w.dirty())
        w._load_bar()                                                                       # what Discard / closing does
        self.assertFalse(w.dirty())
        self.assertEqual(w.bar_colors, {})
        self.assertEqual(str(w.bar_col_ui["text"][0].cget("bg")), theme.bar_palette()["text"])

    def test_reset_one_color_and_reset_all(self):
        app, w = self.open_settings()
        self.pick(w, "button", "#223344")
        self.pick(w, "text", "#eeeeee")
        w.apply()
        w.reset_bar_color("button")
        self.assertEqual(w.bar_colors, {"text": "#eeeeee"})
        self.assertTrue(w.dirty())
        w.reset_bar_colors()
        self.assertEqual(w.bar_colors, {})
        w.apply()
        self.assertEqual(app.cfg["bar"]["colors"], {})
        self.assertEqual(app.bar.win.pal, theme.bar_palette())

    def test_show_titles_applies_live_and_is_saved(self):
        app, w = self.open_settings()
        app.bar.tasks.scan()
        self.assertTrue(app.bar.win.show_titles)
        w.v_bar_titles.set(False)
        self.assertTrue(w.dirty())
        self.assertTrue(app.bar.win.show_titles)                                            # nothing before Apply
        w.apply()
        self.assertFalse(app.bar.win.show_titles)
        self.assertEqual({b["w"] for b in app.bar.win.buttons if b["kind"] == "task"}, {32})
        self.assertEqual(self.cfg_file()["bar"]["tasks"]["show_titles"], False)

    def test_what_was_saved_comes_back_after_a_restart(self):
        app, w = self.open_settings()
        self.pick(w, "active", "#00ff00")
        w.v_bar_titles.set(False)
        w.apply()
        app.quit()
        app2 = self.open(window=False)
        self.assertEqual(app2.bar.win.pal["active"], "#00ff00")
        self.assertFalse(app2.bar.win.show_titles)

    def test_factory_settings_clear_colors_and_titles_on_but_apply_decides(self):
        app, w = self.open_settings()
        self.pick(w, "border", "#ff0000")
        w.v_bar_titles.set(False)
        w.apply()
        with mock.patch.object(w, "confirm_overwrite", return_value=True):
            w.reset(True)
        self.assertEqual(w.bar_colors, {})
        self.assertTrue(w.v_bar_titles.get())
        self.assertEqual(app.cfg["bar"]["colors"], {"border": "#ff0000"})                   # not before Apply
        self.assertEqual(app.bar.win.pal["border"], "#ff0000")                              # the bar itself is unchanged

    def test_the_form_is_a_named_structure(self):
        app, w = self.open_settings()
        f = w._bar_form()
        self.assertIsInstance(f, mpanels.BarForm)
        self.assertEqual(f._fields, ("enabled", "info_on", "time_format", "show_date", "tasks_on", "show_titles", "colors",
                                     "search_on", "hotkey", "store_apps", "windows_row", "start_on"))
        self.assertEqual(f.colors, ("", "", "", "", ""))
        self.assertEqual(f, w._bar_applied())

    def test_the_sample_strip_follows_the_boxes(self):
        app, w = self.open_settings()
        cv = w.bar_sample
        imgs = [i for i in cv.find_all() if cv.type(i) == "image"]
        self.assertEqual(len([1 for i in imgs if cv.coords(i)[1] == theme.BAR_BTN_TOP]), 3)   # normal, active, minimized
        self.assertEqual(str(cv.cget("bg")), theme.bar_palette()["background"])
        self.pick(w, "background", "#202020")
        self.assertEqual(str(cv.cget("bg")), "#202020")
        w.v_bar_titles.set(False)
        w._draw_bar_sample()
        backs = [cv.coords(i)[0] for i in cv.find_all() if cv.type(i) == "image" and cv.coords(i)[1] == theme.BAR_BTN_TOP]
        self.assertEqual(backs[1] - backs[0], 32 + theme.BAR_BTN_GAP)
        self.assertFalse({"Window", "Active", "Minimized"} & {cv.itemcget(i, "text") for i in cv.find_all() if cv.type(i) == "text"})

    def test_an_old_config_opens_with_the_default_look(self):
        self.write_cfg({"bar": {"enabled": True, "info": {"enabled": True, "time_format": "24h", "show_date": True},
                                "tasks": {"enabled": True}}})
        app = self.open(window=False)
        self.assertEqual(app.bar.win.pal, theme.bar_palette())
        self.assertTrue(app.bar.win.show_titles)
        self.assertEqual(app.cfg["bar"]["colors"], {})

    def test_a_failing_bar_start_leaves_the_colors_as_they_were(self):
        app = self.open(bar=dict(ON, enabled=False), window=False)
        self.assertIsNone(app.bar)
        with mock.patch.object(app, "start_bar", return_value=False):
            self.assertFalse(app.apply_bar(True, ON["info"], {"enabled": True}, {"border": "#ff0000"}))
        self.assertEqual(app.cfg["bar"]["colors"], {})


class TestQuitWithALook(Look):
    def test_quit_order_is_the_same_with_custom_colors_and_titles_off(self):
        bar = dict(ON, tasks={"enabled": True, "show_titles": False}, colors={"border": "#ff0000"})
        app = self.open(bar=bar)
        orig = app.root.destroy
        app.root.destroy = lambda: (self.events.append("destroy"), orig())[1]
        app.quit()
        tail = self.events[self.events.index("HOOKS_ON"):]
        self.assertEqual([e for e in tail if e in ("REMOVE", "SHELLCLOSE", "destroy")], ["REMOVE", "SHELLCLOSE", "destroy"])


if __name__ == "__main__":
    unittest.main()
