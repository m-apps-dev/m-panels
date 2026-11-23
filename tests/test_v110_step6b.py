"""v1.1 step 6b: compact Settings > Calendar layout (height, 2-column rows, 3-column colors, swatch = picker)."""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import calendar_panel  # noqa: E402
import fileops  # noqa: E402
import mpanels  # noqa: E402
import strings as ui  # noqa: E402

MAX_H = 720
MAX_W = 720


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


@unittest.skipUnless(calendar_panel.AVAILABLE, "calendar libraries not installed")
class TestLayout(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mpanels_t110s6b_")
        desk, pub, data = (os.path.join(self.tmp, n) for n in ("Desktop", "Public", "veri"))
        os.makedirs(desk)
        os.makedirs(pub)
        p = mock.patch("calendar_panel.model.CalendarModel.refresh", lambda *a, **k: None)
        p.start()
        self.addCleanup(p.stop)
        self.app = mpanels.App(fileops.Ctx(desk, pub), data, test_mode=True, use_tray=False,
                               instance_name="t110s6b_%d" % os.getpid())
        self.addCleanup(self.app.quit)
        self.cp = self.app.new_panel("Cal", "calendar")
        self.cp.cfg["calendar"]["calendars"] = [
            {"name": n, "url": "https://fake.invalid/" + n, "color": None, "enabled": True}
            for n in ("Work", "Home", "Family", "Sport", "Misc")]
        pump(self.app)
        self.app.open_settings("Cal")
        pump(self.app, 25)
        self.S = self.app.settings_win
        self.S.nb.select(self.S.tab["calendar"])
        pump(self.app, 25)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cell(self, w):
        i = w.grid_info()
        return int(i["row"]), int(i["column"])

    def test_requested_height_and_width_are_compact(self):
        w = self.S.win
        w.update_idletasks()
        self.assertLessEqual(w.winfo_reqheight(), MAX_H, "requested height %d" % w.winfo_reqheight())
        self.assertLessEqual(w.winfo_reqwidth(), MAX_W, "requested width %d" % w.winfo_reqwidth())

    def test_day_week_prefix_gone_and_group_heading_present(self):
        t = texts(self.S.tab["calendar"])
        self.assertFalse([x for x in t if x.startswith("Day/Week:")])
        self.assertIn(ui.LBL_CAL_DAYWEEK, t)
        for lbl in (ui.LBL_CAL_START_HOUR, ui.LBL_CAL_END_HOUR, ui.LBL_CAL_HOUR_H, ui.LBL_CAL_EMPTY_H):
            self.assertRegex(lbl, r"\d+–\d+\)")                         # ranges stay in the labels

    def test_two_column_pairs(self):
        S = self.S
        self.assertEqual(self.cell(S.cb_cal_view)[0], self.cell(S.sp_cal_weeks)[0])                  # View | Weeks on one row
        self.assertEqual(self.cell(S.sp_cal_refresh)[0], 3)
        rows = {}
        for var in ("cal_start", "cal_end", "cal_hh", "cal_ehh", "cal_fade"):
            sp = next(w for w in S.cal_look_widgets if str(w.cget("textvariable")) == str(S.v[var]) if "textvariable" in w.keys())
            rows[var] = self.cell(sp)
        self.assertEqual(rows["cal_start"][0], rows["cal_end"][0])
        self.assertEqual(rows["cal_hh"][0], rows["cal_ehh"][0])
        self.assertEqual(rows["cal_start"][1], rows["cal_hh"][1])
        self.assertLess(rows["cal_start"][0], rows["cal_hh"][0])
        self.assertLess(rows["cal_hh"][0], rows["cal_fade"][0])
        for var in ("cal_start", "cal_end", "cal_hh", "cal_ehh", "cal_fade", ):
            sp = next(w for w in S.cal_look_widgets if "textvariable" in w.keys() and str(w.cget("textvariable")) == str(S.v[var]))
            self.assertLessEqual(int(sp.cget("width")), 4)                              # narrow number boxes
        self.assertLessEqual(int(S.sp_cal_weeks.cget("width")), 4)
        self.assertLessEqual(int(S.sp_cal_refresh.cget("width")), 4)

    def test_calendar_list_with_buttons_and_note(self):
        S = self.S
        tree = S.cal_tree
        self.assertEqual(len(tree.get_children()), 5)
        self.assertEqual([tree.set(i, "name") for i in tree.get_children()], ["Work", "Home", "Family", "Sport", "Misc"])
        self.assertNotIn("fake.invalid", " ".join(str(tree.item(i, "values")) for i in tree.get_children()))
        self.assertEqual(self.cell(tree.master)[0], 0)                                   # the list is the first row
        for b in (S.btn_cal_add, S.btn_cal_edit, S.btn_cal_remove, S.btn_cal_import):
            self.assertTrue(b.winfo_ismapped())
        self.assertEqual(S.btn_cal_import.cget("text"), ui.BTN_CAL_IMPORT)
        self.assertIn(ui.CAL_LIST_NOTE, texts(S.tab["calendar"]))

    def test_colors_three_columns_swatch_is_the_picker(self):
        S = self.S
        cols = {k: int(S.cal_col_ui[k][0].master.grid_info()["column"]) for k in S.cal_col_ui}
        rows = {k: int(S.cal_col_ui[k][0].master.grid_info()["row"]) for k in S.cal_col_ui}
        self.assertEqual(set(cols.values()), {0, 1, 2})
        self.assertEqual(set(rows.values()), {0, 1, 2})                                 # 9 colors = 3 rows
        self.assertFalse([x for x in texts(S.tab["calendar"]) if x == ui.BTN_PICK_COLOR])   # no "Pick color…" buttons
        for k, (sw, mark, rb) in S.cal_col_ui.items():
            self.assertEqual(str(sw.cget("cursor")), "hand2")
            self.assertTrue(sw.cget("takefocus"))
        self.assertEqual(ui.TIP_CAL_COLOR_CHANGE, "Click to change")

    def test_revert_button_and_note_share_a_line(self):
        S = self.S
        sib = [w for w in S.btn_cal_revert.master.winfo_children()]
        self.assertEqual(len(sib), 2)
        self.assertEqual(sib[1].cget("text"), ui.CAL_COLORS_NOTE)

    def test_default_look_button_and_one_short_line(self):
        S = self.S
        sib = S.btn_cal_look_default.master.winfo_children()
        self.assertEqual(len(sib), 2)                                                   # button + one short hint
        self.assertEqual(sib[1].cget("text"), ui.CAL_LOOK_HINT)
        self.assertNotIn("\n", ui.CAL_LOOK_HINT)
        self.assertLess(len(ui.CAL_LOOK_HINT), 80)
        S.win.update_idletasks()
        self.assertLess(S.btn_cal_look_default.master.winfo_reqheight(), 40)           # a single line

    def _swatch(self, key):
        return self.S.cal_col_ui[key][0]

    def test_click_opens_the_picker_and_sets_the_color_only_in_the_form(self):
        with mock.patch("mpanels.colorchooser.askcolor", return_value=((0, 0, 0), "#102030")) as q:
            self._swatch("grid").event_generate("<Button-1>")
            self.S.win.update()
        q.assert_called_once()
        self.assertEqual(self.S.cal_colors, {"grid": "#102030"})
        self.assertEqual(self.cp.cfg["calendar"]["colors"], {})                          # Apply rule unchanged

    def test_keyboard_enter_and_space_open_the_picker(self):
        for seq in ("<Return>", "<space>"):
            with mock.patch("mpanels.colorchooser.askcolor", return_value=((0, 0, 0), "#0a0b0c")) as q:
                sw = self._swatch("now")
                sw.focus_force()
                self.S.win.update()
                sw.event_generate(seq)
                self.S.win.update()
            q.assert_called_once()
            self.assertEqual(self.S.cal_colors.get("now"), "#0a0b0c")
            self.S.reset_cal_color("now")

    def test_tooltip_shows_click_to_change(self):
        sw = self._swatch("text")
        # drive the Tip bound to the swatch: <Enter> schedules it, show() builds the window
        import uiwidgets
        t = uiwidgets.Tip(sw, ui.TIP_CAL_COLOR_CHANGE, delay=1)
        t.show()
        try:
            lbl = t.win.winfo_children()[0]
            self.assertEqual(lbl.cget("text"), "Click to change")
        finally:
            t.hide()
        self.assertIsNone(t.win)


if __name__ == "__main__":
    unittest.main()
