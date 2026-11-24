"""v1.2 step 3e: Settings fixes.
(a) Settings > Bar > Colors: no "Color…" buttons; the color box is the picker (same code as the Calendar colors).
(b) The menu of a window button is "Close window" only; the empty bar, the date and "+N" keep "Settings…" only
    (the menu tests are in test_v120_step3d).
(c) Settings > Calendar list: a color picture (tree column #0) instead of the hex text; a click on it opens the picker,
    a double-click on the row still opens the edit window.
No test opens a real color chooser (askcolor is made up) and none closes a real window."""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import calendar_panel  # noqa: E402
import fileops  # noqa: E402
import mpanels  # noqa: E402
import strings as ui  # noqa: E402
import theme  # noqa: E402
from test_v120_step1 import ON  # noqa: E402
from test_v120_step3c import Look  # noqa: E402

PICK = "mpanels.colorchooser.askcolor"


def pump(app, n=15):
    for _ in range(n):
        app.root.update()


def texts(w):
    out = []
    for c in w.winfo_children():
        try:
            out.append(str(c.cget("text")))
        except Exception:
            pass
        out += texts(c)
    return out


class TestBarColors(Look):
    def open_settings(self, bar=ON):
        app = self.open(bar=bar, window=False)
        app.open_settings()
        w = app.settings_win
        self.addCleanup(self._close, w)
        w.nb.select(w.tab["bar"])
        pump(app)
        return app, w

    @staticmethod
    def _close(w):
        try:
            if w.win.winfo_exists():
                w.win.destroy()
        except Exception:
            pass

    def test_there_are_no_color_buttons(self):
        app, w = self.open_settings()
        self.assertNotIn(ui.BTN_COLOR, texts(w.tab["bar"]))
        self.assertEqual(texts(w.tab["bar"]).count(ui.BTN_BAR_COLOR_RESET), 5)         # a Reset per row stays
        self.assertIn(ui.BTN_BAR_COLORS_RESET, texts(w.tab["bar"]))                   # and "Reset colors"

    def test_the_box_has_a_hand_cursor_and_a_tooltip_like_the_calendar_boxes(self):
        app, w = self.open_settings()
        for key, (sw, rb) in w.bar_col_ui.items():
            self.assertEqual(str(sw.cget("cursor")), "hand2", key)
            self.assertTrue(sw.cget("takefocus"))
        cal_sw = next(iter(w.cal_col_ui.values()))[0]
        self.assertEqual(str(cal_sw.cget("cursor")), "hand2")

    def test_a_click_on_the_box_opens_the_picker_and_sets_the_color_only_in_the_form(self):
        app, w = self.open_settings()
        for key in w.bar_col_ui:
            with mock.patch(PICK, return_value=((0, 0, 0), "#102030")) as q:
                w.bar_col_ui[key][0].event_generate("<Button-1>")
                w.win.update()
            q.assert_called_once()
            self.assertEqual(w.bar_colors.get(key), "#102030", key)
            self.assertEqual(w.bar_col_ui[key][0].cget("bg"), "#102030")               # the box shows the color
        self.assertTrue(w.dirty())
        self.assertEqual(app.cfg["bar"].get("colors") or {}, {})                       # nothing before Apply

    def test_enter_and_space_open_the_picker(self):
        app, w = self.open_settings()
        for seq in ("<Return>", "<space>"):
            sw = w.bar_col_ui["text"][0]
            with mock.patch(PICK, return_value=((0, 0, 0), "#0a0b0c")) as q:
                sw.focus_force()
                w.win.update()
                sw.event_generate(seq)
                w.win.update()
            q.assert_called_once()
            self.assertEqual(w.bar_colors.get("text"), "#0a0b0c")

    def test_a_cancelled_picker_changes_nothing(self):
        app, w = self.open_settings()
        with mock.patch(PICK, return_value=(None, None)) as q:
            w.bar_col_ui["border"][0].event_generate("<Button-1>")
            w.win.update()
        q.assert_called_once()
        self.assertEqual(w.bar_colors, {})
        self.assertFalse(w.dirty())

    def test_reset_buttons_and_the_apply_rule_are_unchanged(self):
        app, w = self.open_settings()
        with mock.patch(PICK, return_value=((0, 0, 0), "#336699")):
            w.bar_col_ui["button"][0].event_generate("<Button-1>")
            w.win.update()
        self.assertTrue(w.bar_col_ui["button"][1].instate(["!disabled"]))
        w.bar_col_ui["button"][1].invoke()                                              # row Reset
        self.assertEqual(w.bar_colors, {})
        with mock.patch(PICK, return_value=((0, 0, 0), "#336699")):
            w.bar_col_ui["button"][0].event_generate("<Button-1>")
            w.win.update()
        w.btn_bar_colors_reset.invoke()                                                 # "Reset colors"
        self.assertEqual(w.bar_colors, {})
        with mock.patch(PICK, return_value=((0, 0, 0), "#336699")):
            w.bar_col_ui["button"][0].event_generate("<Button-1>")
            w.win.update()
        w.apply()
        pump(app)
        self.assertEqual(app.cfg["bar"]["colors"], {"button": "#336699"})


class TestQuit(Look):
    def test_quit_order_is_unchanged(self):
        app = self.open(bar=dict(ON, tasks={"enabled": True}))
        orig = app.root.destroy
        app.root.destroy = lambda: (self.events.append("destroy"), orig())[1]
        app.quit()
        tail = self.events[self.events.index("HOOKS_ON"):]
        self.assertEqual([e for e in tail if e in ("REMOVE", "SHELLCLOSE", "destroy")], ["REMOVE", "SHELLCLOSE", "destroy"])


@unittest.skipUnless(calendar_panel.AVAILABLE, "calendar libraries not installed")
class TestCalendarList(unittest.TestCase):
    CALS = [{"name": "Work", "url": "https://fake.invalid/work", "color": "#ff0000", "enabled": True},
            {"name": "Home", "url": "https://fake.invalid/home", "color": None, "enabled": False}]

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mpanels_t120s3e_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        desk, pub, data = (os.path.join(self.tmp, n) for n in ("Desktop", "Public", "veri"))
        os.makedirs(desk)
        os.makedirs(pub)
        p = mock.patch("calendar_panel.model.CalendarModel.refresh", lambda *a, **k: None)
        p.start()
        self.addCleanup(p.stop)
        self.app = mpanels.App(fileops.Ctx(desk, pub), data, test_mode=True, use_tray=False,
                               instance_name="t120s3e_%d" % os.getpid())
        self.addCleanup(self.app.quit)
        self.cp = self.app.new_panel("Cal", "calendar")
        self.cp.cfg["calendar"]["calendars"] = [dict(c) for c in self.CALS]
        pump(self.app)
        self.app.open_settings("Cal")
        pump(self.app, 25)
        self.S = self.app.settings_win
        self.S.nb.select(self.S.tab["calendar"])
        pump(self.app, 25)
        self.tree = self.S.cal_tree

    def pixel(self, i):
        """The color of row i's picture inside its frame, as 'r g b'."""
        img = self.S._cal_imgs[i]
        self.assertEqual(str(self.tree.item(str(i), "image")[0]), str(img))            # the row really shows this picture
        return tuple(int(v) for v in img.get(3, 3)[:3]) if not isinstance(img.get(3, 3), str) \
            else tuple(int(v) for v in img.get(3, 3).split())

    def click_cell(self, i, col):
        x, y, w, h = self.tree.bbox(str(i), col)
        self.tree.event_generate("<Button-1>", x=x + 5, y=y + h // 2)
        self.S.win.update()

    def test_no_hex_text_and_the_color_is_a_picture_in_the_first_column(self):
        self.assertEqual(list(self.tree["columns"]), ["on", "name"])                    # no text color column any more
        self.assertEqual(self.tree.heading("#0", "text"), ui.CAL_COL_COLOR)
        rows = [self.tree.item(i, "values") for i in self.tree.get_children()]
        self.assertEqual([r[1] for r in rows], ["Work", "Home"])
        self.assertNotIn("#ff0000", str(rows))
        self.assertNotIn(ui.CAL_COLOR_DEFAULT, str(rows))
        for i in self.tree.get_children():
            self.assertTrue(self.tree.item(i, "image"))

    def test_the_picture_shows_the_calendar_color(self):
        self.assertEqual(self.pixel(0), (255, 0, 0))
        derived = self.S._derived_cal_palette()["event"]
        self.assertEqual(self.pixel(1), theme.hex_rgb(derived))                         # no color: what the panel really uses

    def test_only_a_row_without_a_color_has_the_dash(self):
        def px(i):
            v = self.S._cal_imgs[i].get(11, 6)
            return tuple(int(x) for x in (v.split() if isinstance(v, str) else v)[:3])
        derived = self.S._derived_cal_palette()["event"]
        self.assertEqual(px(1), theme.hex_rgb(theme.contrast_mark(derived)))             # the dash, in the middle
        self.assertEqual(px(0), (255, 0, 0))                                             # an own color: plain square
        self.assertEqual(theme.contrast_mark("#ffffff"), "#000000")
        self.assertEqual(theme.contrast_mark("#101010"), "#ffffff")

    def test_a_click_on_the_picture_opens_the_picker_and_the_picture_changes(self):
        with mock.patch(PICK, return_value=((0, 0, 0), "#00ff00")) as q:
            self.click_cell(0, "#0")
        q.assert_called_once()
        self.assertEqual(self.S.cal_list[0]["color"], "#00ff00")
        self.assertEqual(self.pixel(0), (0, 255, 0))                                    # shows the chosen color
        self.assertEqual(self.tree.selection(), ("0",))
        self.assertTrue(self.S.dirty())
        self.assertEqual(self.cp.cfg["calendar"]["calendars"][0]["color"], "#ff0000")  # Apply rule: nothing before Apply
        self.S.apply()
        pump(self.app)
        self.assertEqual(self.cp.cfg["calendar"]["calendars"][0]["color"], "#00ff00")

    def test_a_row_without_a_color_can_get_one(self):
        with mock.patch(PICK, return_value=((0, 0, 0), "#0000FF")):
            self.click_cell(1, "#0")
        self.assertEqual(self.S.cal_list[1]["color"], "#0000ff")
        self.assertEqual(self.pixel(1), (0, 0, 255))
        self.assertEqual(self.S.cal_list[0]["color"], "#ff0000")                        # the other row is untouched

    def test_the_picker_starts_on_the_current_color(self):
        with mock.patch(PICK, return_value=(None, None)) as q:
            self.click_cell(0, "#0")
        self.assertEqual(q.call_args.kwargs["color"], "#ff0000")

    def test_a_cancelled_picker_changes_nothing(self):
        with mock.patch(PICK, return_value=(None, None)) as q:
            self.click_cell(0, "#0")
        q.assert_called_once()
        self.assertEqual(self.S.cal_list[0]["color"], "#ff0000")
        self.assertFalse(self.S.dirty())

    def test_a_click_on_another_column_or_the_heading_does_not_open_the_picker(self):
        with mock.patch(PICK, return_value=((0, 0, 0), "#123456")) as q:
            self.click_cell(0, "name")
            self.click_cell(0, "on")
            self.tree.event_generate("<Button-1>", x=5, y=3)                            # the heading row
            self.S.win.update()
        q.assert_not_called()
        self.assertFalse(self.S.dirty())

    def test_double_click_still_opens_the_edit_window(self):
        self.tree.selection_set("0")
        with mock.patch.object(self.S, "ask_calendar", return_value=None) as ask:
            x, y, w, h = self.tree.bbox("0", "name")
            for _ in range(2):                                                          # two quick clicks = a double-click
                self.tree.event_generate("<ButtonPress-1>", x=x + 5, y=y + h // 2, time=1000)
                self.tree.event_generate("<ButtonRelease-1>", x=x + 5, y=y + h // 2, time=1010)
            self.S.win.update()
        ask.assert_called_once()
        self.assertEqual(ask.call_args[0][0]["name"], "Work")

    def test_the_hand_cursor_shows_over_the_picture_only(self):
        x, y, w, h = self.tree.bbox("0", "#0")
        self.tree.event_generate("<Motion>", x=x + 5, y=y + h // 2)
        self.assertEqual(str(self.tree.cget("cursor")), "hand2")
        x, y, w, h = self.tree.bbox("0", "name")
        self.tree.event_generate("<Motion>", x=x + 5, y=y + h // 2)
        self.assertEqual(str(self.tree.cget("cursor")), "")

    def test_the_list_never_shows_an_address(self):
        for iid in self.tree.get_children():
            self.assertNotIn("fake.invalid", str(self.tree.item(iid)))

    def test_pictures_are_kept_alive_after_the_list_is_rebuilt(self):
        for _ in range(3):
            self.S._refresh_cal_list(0)
        self.assertEqual(len(self.S._cal_imgs), 2)
        self.assertEqual(self.pixel(0), (255, 0, 0))


if __name__ == "__main__":
    unittest.main()
