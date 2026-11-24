"""v1.2 step 5: the Start button. Config, the Win key press (made-up SendInput), the controller (made-up clock, search and
actions), the four-tile icon button (3x3 dots only as the fallback; the same drawing as the tray icon), the spacing, the button on the real BarWindow, and the Settings field.
Nothing here sends a key, touches the real foreground, registers a real shortcut key or opens a real color chooser: the
Windows call is handed in (StartActions(send=...), FakeStartActions); the shared Base patches search._real_send and fails any
test in which it is reached. A source scan checks that startmenu.py uses nothing but that one call."""
import inspect
import json
import os
import re
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import barwin  # noqa: E402
import infoclock  # noqa: E402
import mpanels  # noqa: E402
import search  # noqa: E402
import startmenu  # noqa: E402
import strings as ui  # noqa: E402
import theme  # noqa: E402
from fakedisplays import FakeClock  # noqa: E402
from test_v120_step1 import ON, pump  # noqa: E402
from test_v120_step3 import Clicks, ev  # noqa: E402
from test_v120_step4 import HK  # noqa: E402

E, UP = search.KEYEVENTF_EXTENDEDKEY, search.KEYEVENTF_KEYUP
DOWN_EV = (search.VK_LWIN, 0, E)
UP_EV = (search.VK_LWIN, 0, E | UP)


# --------------------------------------------------------------------------- config
class TestConfigPure(unittest.TestCase):
    def test_defaults_are_on(self):
        self.assertEqual(startmenu.defaults(), {"enabled": True})
        self.assertEqual(infoclock.defaults()["start"], {"enabled": True})

    def test_sanitize(self):
        self.assertEqual(startmenu.sanitize(None), {"enabled": True})
        self.assertEqual(startmenu.sanitize(5), {"enabled": True})
        self.assertEqual(startmenu.sanitize({"enabled": "no"}), {"enabled": True})
        self.assertEqual(startmenu.sanitize({"enabled": 0}), {"enabled": True})
        self.assertEqual(startmenu.sanitize({"enabled": False}), {"enabled": False})
        self.assertEqual(startmenu.sanitize({"enabled": False, "x": 1}), {"enabled": False, "x": 1})

    def test_differences_only(self):
        self.assertEqual(startmenu.differences({"enabled": True}), {})
        self.assertEqual(startmenu.differences(None), {})
        self.assertEqual(startmenu.differences({"enabled": False}), {"enabled": False})
        self.assertEqual(startmenu.differences({"enabled": False, "x": 1}), {"enabled": False, "x": 1})

    def test_the_bar_config_carries_it(self):
        self.assertEqual(infoclock.sanitize({})["start"], {"enabled": True})
        self.assertEqual(infoclock.sanitize({"start": {"enabled": False}})["start"], {"enabled": False})
        self.assertEqual(infoclock.sanitize({"start": "junk"})["start"], {"enabled": True})


# --------------------------------------------------------------------------- the Win key press
class TestActions(unittest.TestCase):
    def make(self, taken=None, raises=None, retry_raises=False):
        self.sent = []

        def send(events):
            self.sent.append(list(events))
            if len(self.sent) == 1:
                if raises is not None:
                    raise raises
                return len(events) if taken is None else taken
            if retry_raises:
                raise OSError("again")
            return len(events)
        return startmenu.StartActions(send=send)

    def test_one_call_holds_down_and_up(self):
        a = self.make()
        self.assertTrue(a.open_start())
        self.assertEqual(self.sent, [[DOWN_EV, UP_EV]])                    # ONE call, down first, up second

    def test_keys_are_the_left_win_key(self):
        self.assertEqual(search.VK_LWIN, 0x5B)
        self.assertEqual(startmenu.WIN_DOWN, DOWN_EV)
        self.assertEqual(startmenu.WIN_UP, UP_EV)

    def test_win_is_released_when_windows_takes_fewer_events(self):
        for taken in (0, 1):
            a = self.make(taken=taken)
            self.assertFalse(a.open_start(), taken)
            self.assertEqual(self.sent, [[DOWN_EV, UP_EV], [UP_EV]], taken)

    def test_win_is_released_when_the_call_raises(self):
        a = self.make(raises=OSError("boom"))
        with self.assertRaises(OSError):
            a.open_start()
        self.assertEqual(self.sent, [[DOWN_EV, UP_EV], [UP_EV]])

    def test_a_failing_release_is_logged_not_raised(self):
        a = self.make(taken=1, retry_raises=True)
        with mock.patch.object(startmenu.LOG, "exception") as log:
            try:
                taken = a.open_start()
            except Exception as e:                                          # noqa: BLE001
                self.fail("the failing release escaped: %r" % (e,))
            self.assertFalse(taken)
        log.assert_called_once()

    def test_the_release_is_in_a_finally(self):
        src = inspect.getsource(startmenu.StartActions.open_start)
        self.assertIn("finally:", src)
        self.assertGreater(src.index("finally:"), src.index("WIN_DOWN"))

    def test_the_real_call_is_the_default(self):
        self.assertIs(startmenu.StartActions()._send, search._real_send)

    def test_fake_actions_only_record(self):
        f = startmenu.FakeStartActions()
        self.assertTrue(f.open_start())
        f.fail = OSError(5, "x")
        with self.assertRaises(OSError):
            f.open_start()
        self.assertEqual(f.calls, [("win",), ("win",)])


class TestSourceScan(unittest.TestCase):
    def test_startmenu_uses_only_the_one_send_call(self):
        src = inspect.getsource(startmenu)
        self.assertEqual(len(re.findall(r"_real_send", src)), 1)
        for banned in ("user32", "WinDLL", "ctypes", "keybd_event", "SetForegroundWindow", "AttachThreadInput", "PostMessage",
                       "SendMessage", "startfile", "subprocess", "os.system", "RegisterHotKey", "ShellExecute"):
            self.assertNotIn(banned, src, banned)

    def test_no_other_module_sends_the_win_key_for_start(self):
        for mod in (barwin, mpanels):
            self.assertNotIn("VK_LWIN", inspect.getsource(mod), mod.__name__)


# --------------------------------------------------------------------------- the controller
class TestController(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.acts = startmenu.FakeStartActions()
        self.order = []
        self.dbl = 500
        real_open = self.acts.open_start
        self.acts.open_start = lambda: (self.order.append("win"), real_open())[1]
        self.s = startmenu.Start(self.acts, self.clock, lambda: self.order.append("close_search"),
                                 double_click=lambda: self.dbl)

    def test_a_click_sends_the_win_key_once(self):
        self.assertTrue(self.s.click())
        self.assertEqual(self.acts.calls, [("win",)])

    def test_the_search_window_is_closed_before_the_key_is_sent(self):
        self.s.click()
        self.assertEqual(self.order, ["close_search", "win"])

    def test_a_click_inside_the_double_click_time_is_ignored(self):
        self.s.click()
        self.clock.advance(0.3)
        self.assertFalse(self.s.click())
        self.assertEqual(self.acts.calls, [("win",)])

    def test_a_click_after_the_double_click_time_is_a_new_click(self):
        self.s.click()
        self.clock.advance(0.6)
        self.assertTrue(self.s.click())
        self.assertEqual(self.acts.calls, [("win",), ("win",)])

    def test_the_double_click_time_is_read_from_the_system_value(self):
        self.dbl = 200
        self.s.click()
        self.clock.advance(0.25)
        self.assertTrue(self.s.click())

    def test_an_ignored_click_does_not_extend_the_guard(self):
        self.s.click()
        self.clock.advance(0.4)
        self.s.click()                                                      # ignored
        self.clock.advance(0.2)                                             # 0.6 s after the first click
        self.assertTrue(self.s.click())

    def test_a_failing_search_close_does_not_stop_the_key(self):
        def boom():
            raise RuntimeError("x")
        with mock.patch.object(startmenu.LOG, "exception"):
            s = startmenu.Start(self.acts, self.clock, boom, double_click=lambda: 500)
            self.assertTrue(s.click())
        self.assertEqual(self.acts.calls, [("win",)])

    def test_a_failing_key_never_raises_into_tk(self):
        self.acts.fail = OSError(5, "denied")
        with mock.patch.object(startmenu.LOG, "exception"):
            self.assertFalse(self.s.click())

    def test_the_default_double_click_time_is_the_systems(self):
        self.assertIs(startmenu.Start.__init__.__defaults__[0], search.double_click_ms)


# --------------------------------------------------------------------------- the icon
class TestIcon(unittest.TestCase):
    def test_size_mode_and_color(self):
        im = theme.start_icon(16, "#ffffff")
        self.assertEqual(im.size, (16, 16))
        self.assertEqual(im.mode, "RGBA")
        px = [p for p in (im.getpixel((x, y)) for x in range(16) for y in range(16)) if p[3] > 200]
        self.assertTrue(px and all(p[:3] == (255, 255, 255) for p in px))
        self.assertEqual(theme.start_icon(24, "#ff0000").size, (24, 24))

    def test_it_is_a_3x3_grid_of_dots(self):
        size = 48
        im = theme.start_icon(size, "#ffffff")
        centers = [0.2, 0.5, 0.8]
        for cx in centers:
            for cy in centers:
                self.assertGreater(im.getpixel((round(size * cx), round(size * cy)))[3], 200, (cx, cy))
        for gx in (0.35, 0.65):                                             # between the dots: transparent
            for cy in centers:
                self.assertEqual(im.getpixel((round(size * gx), round(size * cy)))[3], 0, (gx, cy))
        for cx in centers:
            for gy in (0.35, 0.65):
                self.assertEqual(im.getpixel((round(size * cx), round(size * gy)))[3], 0, (cx, gy))
        self.assertEqual(im.getpixel((0, 0))[3], 0)                         # nothing in the corners

    def test_the_dots_are_separate(self):
        """9 separate blobs (not one filled square, no Windows logo made of 4 panes)."""
        size = 48
        im = theme.start_icon(size, "#ffffff")
        on = {(x, y) for x in range(size) for y in range(size) if im.getpixel((x, y))[3] > 128}
        seen, blobs = set(), 0
        for start in sorted(on):
            if start in seen:
                continue
            blobs += 1
            todo = [start]
            while todo:
                p = todo.pop()
                if p in seen or p not in on:
                    continue
                seen.add(p)
                todo += [(p[0] + 1, p[1]), (p[0] - 1, p[1]), (p[0], p[1] + 1), (p[0], p[1] - 1)]
        self.assertEqual(blobs, 9)


class TestTileIcon(unittest.TestCase):
    COLORS = {"tl": (0x3a, 0xa0, 0xff), "tr": (0x3d, 0xdc, 0x84), "bl": (0xff, 0x9a, 0x3c), "br": (0xa5, 0x6b, 0xff)}

    def test_size_mode_and_a_fresh_copy(self):
        for n in (16, 24, 30, 32):
            im = theme.tile_icon(n)
            self.assertEqual((im.size, im.mode), ((n, n), "RGBA"))
        a, b = theme.tile_icon(30), theme.tile_icon(30)
        self.assertIsNot(a, b)
        a.putpixel((15, 15), (1, 2, 3, 4))
        self.assertNotEqual(theme.tile_icon(30).getpixel((15, 15)), (1, 2, 3, 4))   # a caller cannot damage the cache

    def test_drawn_once_per_size(self):
        theme._TILE_ICONS.clear()
        with mock.patch.object(theme, "_tile_icon_draw", wraps=theme._tile_icon_draw) as draw:
            for _ in range(4):
                theme.tile_icon(30)
            theme.tile_icon(16)
        self.assertEqual([c.args[0] for c in draw.call_args_list], [30, 16])

    def test_four_colored_tiles_fill_the_square_with_a_transparent_cross_between(self):
        n = 120
        im = theme.tile_icon(n)

        def c(fx, fy):
            return im.getpixel((int(n * fx), int(n * fy)))
        for key, (fx, fy) in {"tl": (0.25, 0.25), "tr": (0.75, 0.25), "bl": (0.25, 0.75), "br": (0.75, 0.75)}.items():
            r, g, b, a = c(fx, fy)
            self.assertEqual(a, 255, key)
            want = self.COLORS[key]
            self.assertEqual(max(range(3), key=lambda i: (r, g, b)[i]), max(range(3), key=lambda i: want[i]), key)   # same hue family
        self.assertEqual(c(0.5, 0.5)[3], 0)                                         # the gap between the tiles
        self.assertEqual(c(0.5, 0.25)[3], 0)
        self.assertEqual(c(0.25, 0.5)[3], 0)

    def test_it_reaches_the_edge_and_has_no_background_and_no_rim(self):
        n = 120
        im = theme.tile_icon(n)
        self.assertEqual(im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox(), (0, 0, n, n))   # no transparent margin
        self.assertEqual(im.getpixel((0, 0))[3], 0)                                 # rounded corners: transparent
        self.assertEqual(im.getpixel((n - 1, n - 1))[3], 0)
        opaque = [p for p in im.getdata() if p[3] > 200]
        self.assertFalse([p for p in opaque if sum(p[:3]) < 90])                    # nothing dark: no black background, no grid

    def test_no_grid_the_tile_is_flat_inside(self):
        n = 120
        im = theme.tile_icon(n)
        row = [im.getpixel((x, 30)) for x in range(10, 50)]                         # across the top-left tile at one height
        self.assertTrue(all(p[3] == 255 for p in row))
        self.assertLessEqual(max(abs(row[i][0] - row[0][0]) + abs(row[i][1] - row[0][1]) + abs(row[i][2] - row[0][2])
                                 for i in range(len(row))), 12)                     # one color across (a grid would break it)

    def test_the_colors_are_the_ones_of_the_icon_script(self):
        src = open(os.path.join(ROOT, "tools", "ikon_uret.py"), encoding="utf-8").read()
        for hexcol, _, _ in theme.START_TILES:
            self.assertIn('"%s"' % hexcol, src)


# --------------------------------------------------------------------------- the tray icon
class TestTray(unittest.TestCase):
    def handle_size(self, h):
        import ctypes

        class ICONINFO(ctypes.Structure):
            _fields_ = [("fIcon", ctypes.c_int), ("xHot", ctypes.c_uint), ("yHot", ctypes.c_uint),
                        ("hbmMask", ctypes.c_void_p), ("hbmColor", ctypes.c_void_p)]

        class BM(ctypes.Structure):
            _fields_ = [("t", ctypes.c_long), ("w", ctypes.c_long), ("h", ctypes.c_long), ("wb", ctypes.c_long),
                        ("p", ctypes.c_ushort), ("b", ctypes.c_ushort), ("bits", ctypes.c_void_p)]
        u = ctypes.windll.user32
        u.GetIconInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(ICONINFO)]
        ii = ICONINFO()
        self.assertTrue(u.GetIconInfo(h, ctypes.byref(ii)))
        bm = BM()
        ctypes.windll.gdi32.GetObjectW(ctypes.c_void_p(ii.hbmColor), ctypes.sizeof(bm), ctypes.byref(bm))
        return bm.w, bm.h

    def test_small_icon_size_is_sane_and_falls_back_to_16(self):
        self.assertIn(mpanels.winutil.small_icon_size(), range(12, 65))
        broken = mock.Mock()
        broken.user32.GetSystemMetrics.side_effect = OSError("no")
        with mock.patch.object(mpanels.winutil.ctypes, "windll", broken):
            self.assertEqual(mpanels.winutil.small_icon_size(), 16)
        zero = mock.Mock()
        zero.user32.GetSystemMetrics.return_value = 0
        with mock.patch.object(mpanels.winutil.ctypes, "windll", zero):
            self.assertEqual(mpanels.winutil.small_icon_size(), 16)

    @unittest.skipUnless(mpanels.HAS_TRAY, "pystray is not installed")
    def test_the_image_is_the_tile_drawing_at_exactly_that_size(self):
        icon = mpanels.make_tray_icon("MPanelsTest", 16, "tip", None)
        self.assertEqual(icon.icon.size, (16, 16))
        self.assertEqual(list(icon.icon.getdata()), list(theme.tile_icon(16).getdata()))

    @unittest.skipUnless(mpanels.HAS_TRAY, "pystray is not installed")
    def test_the_loaded_windows_icon_is_exactly_that_size_not_32(self):
        """pystray alone loads whatever it is given as a 32 px icon (LR_DEFAULTSIZE); ours must come out at the asked size."""
        for size in (16, 24):
            icon = mpanels.make_tray_icon("MPanelsTest", size, "tip", None)
            icon._assert_icon_handle()
            try:
                self.assertEqual(self.handle_size(icon._icon_handle), (size, size))
            finally:
                mpanels.pystray._util.win32.DestroyIcon(icon._icon_handle)

    @unittest.skipUnless(mpanels.HAS_TRAY, "pystray is not installed")
    def test_the_stock_pystray_loads_32_which_is_why_it_is_replaced(self):
        from pystray._util import serialized_image
        from pystray._util import win32 as w32
        with serialized_image(theme.tile_icon(16), "ICO") as path:
            h = w32.LoadImage(None, path, w32.IMAGE_ICON, 0, 0, w32.LR_DEFAULTSIZE | w32.LR_LOADFROMFILE)
        try:
            self.assertEqual(self.handle_size(h), (32, 32))
        finally:
            w32.DestroyIcon(h)

    def test_setup_tray_uses_it_with_the_small_icon_size(self):
        src = inspect.getsource(mpanels.App._setup_tray)
        self.assertIn("make_tray_icon(", src)
        self.assertIn("small_icon_size()", src)
        self.assertNotIn("app_icon_image", src)


# --------------------------------------------------------------------------- the button on the real BarWindow
class Btn(Clicks):
    def setUp(self):
        self.start_acts = startmenu.FakeStartActions()       # before Base.open() builds the app
        super().setUp()

    def bar(self, **kw):
        app, win = super().bar(**kw)
        pump(app, 3)
        return app, win

    def press(self, win, x=None):
        b = win.start_button
        x = b["x"] + 5 if x is None else x
        win._on_press(ev(x))
        win._on_release(ev(x))

    def wins(self):
        return self.start_acts.calls


class TestLayout(Btn):
    def test_the_start_button_is_in_its_zone_and_search_and_tasks_stay(self):
        app, win = self.bar()
        b = win.start_button
        self.assertEqual(b["kind"], "start")
        self.assertGreaterEqual(b["x"], 0)
        self.assertLessEqual(b["x"] + b["w"], theme.BAR_START_W)
        self.assertEqual((b["x"], b["w"]), (0, theme.BAR_START_W))          # the hit area is the whole Start zone, from x=0
        self.assertEqual(win.search_button["x"], theme.BAR_SEARCH_BTN_X)
        self.assertEqual(win.buttons[0]["x"], theme.BAR_LEFT_RESERVE)
        self.assertNotIn(b, win.buttons)

    def test_spacing_is_derived_start_32_then_4_px_search_then_4_px_tasks(self):
        self.assertEqual(theme.BAR_START_W, 32)                              # the place does not shrink with the icon
        self.assertEqual(theme.BAR_SEARCH_X, theme.BAR_START_W + theme.BAR_BTN_GAP)
        self.assertEqual(theme.BAR_LEFT_RESERVE, theme.BAR_SEARCH_X + theme.BAR_SEARCH_W + theme.BAR_BTN_GAP)
        self.assertEqual((theme.BAR_START_W, theme.BAR_SEARCH_BTN_X, theme.BAR_LEFT_RESERVE), (32, 36, 72))
        app, win = self.bar()
        self.assertEqual(win.search_button["x"] - (win.start_button["x"] + win.start_button["w"]), theme.BAR_BTN_GAP)
        self.assertEqual(win.buttons[0]["x"] - (win.search_button["x"] + win.search_button["w"]), theme.BAR_BTN_GAP)
        self.assertEqual(win.buttons[1]["x"] - (win.buttons[0]["x"] + win.buttons[0]["w"]), theme.BAR_BTN_GAP)   # the same gap

    def test_the_corner_and_the_top_row_click_start(self):
        """The mouse thrown into the top-left corner of the screen hits Start: x=0 and y=0 count (the whole bar height)."""
        app, win = self.bar()
        for x, y in ((0, 0), (0, theme.BAR_HEIGHT - 1), (theme.BAR_START_W - 1, 0)):
            self.wins().clear()
            self.clock.advance(1.0)
            e = mock.Mock(x=x, y=y, x_root=x, y_root=y)
            win._on_press(e)
            win._on_release(e)
            self.assertEqual(self.wins(), [("win",)], (x, y))
        self.wins().clear()
        self.clock.advance(1.0)
        win._on_press(ev(theme.BAR_START_W))                                # the first pixel of the gap before Search: no Start
        win._on_release(ev(theme.BAR_START_W))
        self.assertEqual(self.wins(), [])

    def test_off_draws_nothing_and_search_and_tasks_do_not_move(self):
        app, win = self.bar()
        task_x = [b["x"] for b in win.buttons]
        search_x = win.search_button["x"]
        items_on = len(win.cv.find_all())
        self.assertTrue(app.apply_bar(True, ON["info"], start_cfg={"enabled": False}))
        pump(app, 3)
        self.assertIsNone(win.start_button)
        self.assertIsNone(app.bar.startmenu)
        self.assertLess(len(win.cv.find_all()), items_on)
        self.assertEqual([b["x"] for b in win.buttons], task_x)
        self.assertEqual(win.search_button["x"], search_x)
        for x in (2, 12, 30, 44):                                           # the empty place: no hit, no key
            win._on_press(ev(x))
            win._on_release(ev(x))
        self.assertEqual(self.wins(), [])

    def test_zones_do_not_overlap(self):
        app, win = self.bar()
        self.assertLessEqual(win.start_button["x"] + win.start_button["w"], win.search_button["x"])
        self.assertIs(win.hit(win.start_button["x"] + 1), win.start_button)
        self.assertIs(win.hit(win.search_button["x"] + 1), win.search_button)

    def test_search_off_start_on_leaves_the_start_button(self):
        app, win = self.bar()
        self.assertTrue(app.apply_bar(True, ON["info"], search_cfg={"enabled": False}))
        self.assertIsNotNone(win.start_button)
        self.assertIsNone(win.search_button)

    def test_no_bar_no_button(self):
        app = self.open(bar=dict(ON, enabled=False))
        self.assertIsNone(app.bar)


class TestClicking(Btn):
    def test_a_click_sends_the_win_key(self):
        app, win = self.bar()
        self.press(win)
        self.assertEqual(self.wins(), [("win",)])

    def test_press_and_release_must_be_on_the_button(self):
        app, win = self.bar()
        b = win.start_button
        win._on_press(ev(b["x"] + 5))
        win._on_release(ev(300))                                            # released elsewhere: not a click
        win._on_release(ev(b["x"] + 5))                                     # no press any more
        win._on_press(ev(300))
        win._on_release(ev(b["x"] + 5))                                     # pressed elsewhere
        self.assertEqual(self.wins(), [])

    def test_double_click_acts_once(self):
        app, win = self.bar()
        x = win.start_button["x"] + 5
        self.press(win)                                                     # 1st click
        win._on_press(ev(x))                                                # the 2nd press (<Double-Button-1> in real life)
        self.assertEqual(win._on_double(ev(x)), "break")
        win._on_release(ev(x))
        self.assertEqual(self.wins(), [("win",)])

    def test_a_second_click_inside_the_double_click_time_is_ignored_and_a_later_one_toggles(self):
        app, win = self.bar()
        self.press(win)
        self.press(win)
        self.assertEqual(self.wins(), [("win",)])
        self.clock.advance(1.0)
        self.press(win)
        self.assertEqual(self.wins(), [("win",), ("win",)])

    def test_a_click_closes_the_open_search_window_without_giving_the_foreground_back(self):
        app, win = self.bar()
        self.src.fg = 2
        sb = win.search_button
        win._on_press(ev(sb["x"] + 5))
        win._on_release(ev(sb["x"] + 5))
        s = app.bar.search
        self.assertTrue(s.is_open())
        self.actions.calls.clear()
        order = []
        real_close = s.close
        s.close = lambda give_back, why="": (order.append(("close", give_back)), real_close(give_back, why))[1]
        self.start_acts.open_start = lambda: order.append("win") or True
        self.press(win)
        self.assertFalse(s.is_open())
        self.assertEqual(order, [("close", False), "win"])                  # closed first, no give_back, then the key
        self.assertFalse([c for c in self.actions.calls if c[0] == "front"])     # the foreground was not handed back
        self.assertEqual(win.search_button["state"], "normal")

    def test_a_click_with_no_search_window_does_not_touch_search(self):
        app, win = self.bar()
        s = app.bar.search
        with mock.patch.object(s, "close") as close:
            self.press(win)
        close.assert_not_called()

    def test_a_click_while_search_is_off_still_sends_the_key(self):
        app, win = self.bar()
        self.assertTrue(app.apply_bar(True, ON["info"], search_cfg={"enabled": False}))
        self.press(win)
        self.assertEqual(self.wins(), [("win",)])

    def test_the_click_never_raises_into_tk(self):
        app, win = self.bar()
        self.start_acts.fail = OSError(5, "denied")
        with mock.patch.object(startmenu.LOG, "exception"):
            self.press(win)
        self.assertEqual(self.wins(), [("win",)])

    def test_a_task_click_does_not_send_the_win_key(self):
        app, win = self.bar()
        self.click(win, "Alpha")
        self.assertEqual(self.wins(), [])

    def test_a_search_click_does_not_send_the_win_key(self):
        app, win = self.bar()
        sb = win.search_button
        win._on_press(ev(sb["x"] + 5))
        win._on_release(ev(sb["x"] + 5))
        self.assertEqual(self.wins(), [])


class TestLook(Btn):
    def stub_popup(self, win):
        self.popups = []
        win._popup = lambda m, x, y: self.popups.append(m)

    def test_right_click_is_settings_only(self):
        app, win = self.bar()
        self.stub_popup(win)
        b = win.start_button
        win.cv.event_generate("<Button-3>", x=b["x"] + 5, y=10)
        win.top.update()
        self.assertEqual(len(self.popups), 1)
        self.assertEqual(self.popups[0].index("end"), 0)
        self.assertEqual(self.popups[0].entrycget(0, "label"), ui.BAR_MENU_SETTINGS)
        self.assertEqual(self.wins(), [])                                   # a right click is not a Start click

    def test_hover_marks_the_button_and_there_is_no_active_look(self):
        app, win = self.bar()
        win._on_motion(ev(win.start_button["x"] + 5))
        self.assertEqual(win.start_button["state"], "hover")
        win._on_motion(ev(900))
        self.assertEqual(win.start_button["state"], "normal")
        self.press(win)
        self.assertEqual(win.start_button["state"], "normal")               # clicking does not make it "active"
        self.assertFalse(hasattr(win, "start_active"))

    def test_only_one_button_hovers(self):
        app, win = self.bar()
        win._on_motion(ev(win.start_button["x"] + 5))
        self.assertEqual(win.search_button["state"], "normal")
        win._on_motion(ev(win.search_button["x"] + 5))
        self.assertEqual(win.start_button["state"], "normal")
        self.assertEqual(win.search_button["state"], "hover")

    def test_the_button_is_the_icon_itself_with_no_3c_frame(self):
        app, win = self.bar()
        b = win.start_button
        self.assertEqual(b["icon"], theme.BAR_START_ICON)
        self.assertEqual(theme.BAR_START_ICON, 28)                          # one fixed value, not a setting
        self.assertEqual((b["fill"], b["frame"]), (None, None))
        self.assertEqual(b["h"], theme.BAR_START_ICON)
        win.top.update_idletasks()
        imgs = [i for i in win.cv.find_all() if win.cv.type(i) == "image"]
        coords = [tuple(win.cv.coords(i)) for i in imgs if tuple(win.cv.coords(i))[0] < theme.BAR_START_W]
        self.assertEqual(coords, [tuple(map(float, b["icon_xy"]))])         # exactly one image in the zone: no button background

    def test_the_icon_is_one_pixel_in_from_the_edges_and_centered(self):
        app, win = self.bar()
        ix, iy = win.start_button["icon_xy"]
        size = theme.BAR_START_ICON
        h = win.rect[3] - win.rect[1]
        self.assertEqual((ix, iy), (2, 2))                                  # 2 px left, 2 px above
        self.assertEqual(h - (iy + size), 2)                                # 2 px below (the last row is the bar bottom line)
        self.assertEqual(theme.BAR_START_W - (ix + size), 2)                # 2 px right: centered in the 32 px place
        self.assertEqual((ix, iy), ((theme.BAR_START_W - size) // 2, (theme.BAR_HEIGHT - size) // 2))   # derived from the constant
        self.assertEqual(ix, theme.BAR_START_PAD)
        for x in (0, 1, theme.BAR_START_W - 1):
            self.assertIs(win.hit(x), win.start_button, x)
        self.assertIsNot(win.hit(theme.BAR_START_W), win.start_button)

    def test_the_default_icon_is_the_tile_drawing_the_tray_uses(self):
        app, win = self.bar()
        self.assertIs(win.icon_source, theme.tile_icon)

    def test_hover_brightens_the_icon_and_nothing_else(self):
        base = theme.tile_icon(theme.BAR_START_ICON)
        glow = theme.start_glow(base)
        self.assertEqual(glow.size, base.size)
        self.assertEqual(list(glow.getchannel("A").getdata()), list(base.getchannel("A").getdata()))   # shape untouched
        lum = lambda im: sum(sum(p[:3]) for p in im.getdata() if p[3] > 200)                          # noqa: E731
        self.assertGreater(lum(glow), lum(base))
        app, win = self.bar()
        win._start_photos.clear()
        with mock.patch.object(theme, "start_glow", wraps=theme.start_glow) as glow_spy:
            win.draw()
            glow_spy.assert_not_called()                                    # normal: the icon as it is
            win._on_motion(ev(win.start_button["x"] + 5))
            glow_spy.assert_called_once()                                   # hover: brightened, once (then cached)
        self.assertEqual(win.start_button["state"], "hover")
        self.assertIn(("icon", theme.BAR_START_ICON, True), win._start_photos)
        self.assertIsNot(win._start_photos[("icon", theme.BAR_START_ICON, True)],
                         win._start_photos[("icon", theme.BAR_START_ICON, False)])
        self.assertEqual((win.start_button["fill"], win.start_button["frame"]), (None, None))   # still no frame on hover

    def test_the_icon_is_made_once_per_size_and_never_re_read_on_a_draw(self):
        app, win = self.bar()
        calls = []
        real = win.icon_source
        win.icon_source = lambda size: calls.append(size) or real(size)
        win._start_photos.clear()
        for _ in range(5):
            win.draw()
        win._on_motion(ev(win.start_button["x"] + 5))
        for _ in range(5):
            win.draw()
        self.assertEqual(sorted(calls), [theme.BAR_START_ICON, theme.BAR_START_ICON])   # once normal, once hover; then cached

    def test_the_icon_does_not_follow_the_text_color(self):
        app, win = self.bar()
        photos = dict(win._start_photos)
        app.bar.set_colors({"text": "#ff8800"})
        self.assertIs(win._start_photos[("icon", theme.BAR_START_ICON, False)], photos[("icon", theme.BAR_START_ICON, False)])


class TestIconFallback(Btn):
    """The 3x3 dots are drawn only when the icon cannot be had at all; the button is still there and still works."""

    def drawn(self, win):
        b = win.start_button
        self.assertIsNotNone(b)
        self.assertIs(win.hit(5), b)
        self.press(win)
        self.assertEqual(self.wins(), [("win",)])
        return b

    def test_the_icon_needs_no_file_at_all(self):
        """The tile drawing is code: drawing the Start button reads no .ico / .png (a missing or broken one cannot matter)."""
        app, win = self.bar()
        win._start_photos.clear()
        with mock.patch.object(mpanels.winutil, "app_icon_path", side_effect=AssertionError("file looked at")),                 mock.patch.object(mpanels.Image, "open", side_effect=AssertionError("file opened")):
            win.draw()
            win._on_motion(ev(5))
        b = self.drawn(win)
        self.assertEqual(b["icon"], theme.BAR_START_ICON)

    def test_no_icon_at_all_falls_back_to_the_dots_button(self):
        app, win = self.bar()
        win.icon_source = None
        win._start_photos.clear()
        win.draw()
        b = self.drawn(win)
        self.assertEqual(b["icon"], 0)
        self.assertEqual((b["x"], b["w"]), (0, theme.BAR_START_W))
        self.assertLessEqual(b["x"] + b["w"], theme.BAR_SEARCH_X)           # the dots button stays in its zone
        pal = theme.bar_palette()
        self.assertEqual((b["fill"], b["frame"]), theme.btn_colors(pal, "normal"))
        self.assertEqual(b["h"], theme.BAR_BTN_H)
        self.assertIn(("dots", win.pal["text"]), win._start_photos)

    def test_an_icon_source_that_raises_falls_back_and_never_raises_into_tk(self):
        app, win = self.bar()

        def boom(size):
            raise OSError("broken")
        win.icon_source = boom
        win._start_photos.clear()
        with mock.patch.object(barwin.LOG, "warning"):
            win.draw()
            win._on_motion(ev(5))
        self.assertEqual(win.start_button["icon"], 0)
        self.assertEqual(win.start_button["state"], "hover")

    def test_the_fallback_dots_follow_the_text_color(self):
        app, win = self.bar()
        win.icon_source = None
        win._start_photos.clear()
        app.bar.set_colors({"text": "#ff8800"})
        self.assertIn(("dots", "#ff8800"), win._start_photos)


class TestInTheApp(Btn):
    def test_test_mode_never_sends_a_key(self):
        app = self.open(bar=ON, test_mode=True, window=False)
        app._start_actions = None
        ctl = app._make_start(app.bar)
        self.assertIsInstance(app.start_actions, startmenu.FakeStartActions)
        self.assertIsInstance(ctl, startmenu.Start)

    def test_real_mode_builds_the_real_actions(self):
        app = self.open(bar=ON, window=False)
        app._start_actions = None
        app.test_mode = False
        app._make_start(app.bar)                                            # built, never called: nothing is sent
        self.assertIsInstance(app.start_actions, startmenu.StartActions)
        self.assertEqual(self.real_sends, [])

    def test_the_default_config_has_the_button_on(self):
        app = self.open(bar=ON)
        self.assertEqual(app.cfg["bar"]["start"], {"enabled": True})
        self.assertIsNotNone(app.bar.startmenu)

    def test_quit_drops_the_button_with_the_bar(self):
        app = self.open(bar=ON)
        bar = app.bar
        app.quit()
        self.assertIsNone(bar.startmenu)


# --------------------------------------------------------------------------- Settings > Bar
class TestSettings(HK):
    def test_the_field_and_its_default(self):
        app, w = self.settings()
        self.assertTrue(w.v_bar_start.get())
        self.assertEqual(w.cb_bar_start.cget("text"), ui.CHK_START_SHOW)
        self.assertEqual(ui.CHK_START_SHOW, "Show Start button")
        self.assertEqual(str(w.cb_bar_start.winfo_parent()), str(w.tab["bar"]))
        self.assertFalse(w.dirty())

    def test_the_box_makes_the_window_dirty_and_back(self):
        app, w = self.settings()
        w.v_bar_start.set(False)
        self.assertTrue(w.dirty())
        w.v_bar_start.set(True)
        self.assertFalse(w.dirty())

    def test_nothing_changes_before_apply(self):
        app, w = self.settings(bar=ON, window=False)
        w.v_bar_start.set(False)
        self.assertTrue(app.cfg["bar"]["start"]["enabled"])
        self.assertIsNotNone(app.bar.win.start_button)
        self.assertNotIn("start", self.cfg_file()["bar"])

    def test_apply_off_is_live_and_written_apply_on_removes_the_key(self):
        app, w = self.settings(bar=ON, window=False)
        w.v_bar_start.set(False)
        w.apply()
        pump(app, 3)
        self.assertIsNone(app.bar.win.start_button)
        self.assertIsNone(app.bar.startmenu)
        self.assertEqual(self.cfg_file()["bar"]["start"], {"enabled": False})
        w.v_bar_start.set(True)
        w.apply()
        pump(app, 3)
        self.assertIsNotNone(app.bar.win.start_button)
        self.assertIsNotNone(app.bar.startmenu)
        self.assertNotIn("start", self.cfg_file()["bar"])                   # back to the default: the key is gone

    def test_the_default_config_file_has_no_start_key(self):
        app = self.open(bar=ON)
        app.save()
        self.assertNotIn("start", self.cfg_file()["bar"])

    def test_an_off_button_survives_a_restart(self):
        app = self.open(bar=dict(ON, start={"enabled": False}), window=False)
        self.assertIsNone(app.bar.win.start_button)
        app.save()
        self.assertEqual(self.cfg_file()["bar"]["start"], {"enabled": False})

    def test_a_bad_value_in_the_file_falls_back_to_on(self):
        app = self.open(bar=dict(ON, start={"enabled": "nope"}))
        self.assertEqual(app.cfg["bar"]["start"], {"enabled": True})

    def test_a_start_that_is_not_a_dict_falls_back_to_on(self):
        app = self.open(bar=dict(ON, start=7))
        self.assertEqual(app.cfg["bar"]["start"], {"enabled": True})

    def test_an_old_config_without_start_works(self):
        app = self.open(bar=ON, window=False)
        self.assertNotIn("start", ON)
        self.assertEqual(app.cfg["bar"]["start"], {"enabled": True})
        self.assertIsNotNone(app.bar.win.start_button)

    def test_discarding_the_bar_boxes_restores_the_applied_value(self):
        app, w = self.settings(bar=ON)
        w.v_bar_start.set(False)
        self.assertTrue(w.dirty())
        w._load_bar()                                                       # what Discard does for the bar boxes
        self.assertTrue(w.v_bar_start.get())
        self.assertFalse(w.dirty())

    def test_revert_to_defaults_leaves_the_bar_and_its_button_alone(self):
        app, w = self.settings(bar=dict(ON, start={"enabled": False}))
        with mock.patch.object(w, "confirm_overwrite", return_value=True):
            w.reset(False)
        self.assertFalse(app.cfg["bar"]["start"]["enabled"])
        self.assertFalse(w.v_bar_start.get())

    def test_factory_settings_load_the_default_and_apply_puts_it_in_force(self):
        app, w = self.settings(bar=dict(ON, start={"enabled": False}))
        with mock.patch.object(w, "confirm_overwrite", return_value=True):
            w.reset(True)
        self.assertTrue(w.v_bar_start.get())
        self.assertFalse(app.cfg["bar"]["start"]["enabled"])                # loaded into the box only
        w.apply()
        self.assertEqual(app.cfg["bar"], infoclock.defaults())

    def test_a_failed_search_key_takes_the_start_change_back_too(self):
        self.shell_hotkey_ok = False
        app, w = self.settings(bar=ON, window=False)
        w.v_bar_start.set(False)
        w.v_search_hk.set(ui.SEARCH_HOTKEY_LABELS["win+alt+space"])
        w.apply()
        pump(app, 3)
        self.assertTrue(app.cfg["bar"]["start"]["enabled"])
        self.assertIsNotNone(app.bar.win.start_button)
        self.assertIsNotNone(app.bar.startmenu)
        self.assertNotIn("start", self.cfg_file()["bar"])


class TestTexts(unittest.TestCase):
    def test_example_config_shows_the_default(self):
        with open(os.path.join(ROOT, "config.example.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["bar"]["start"], {"enabled": True})


if __name__ == "__main__":
    unittest.main()
