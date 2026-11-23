"""v1.1 step 5: per-key calendar color overrides (Settings > Calendar > Colors) + cal_open_google False -> log."""
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import applog  # noqa: E402
import calendar_panel  # noqa: E402
import fileops  # noqa: E402
import mpanels  # noqa: E402
import strings as ui  # noqa: E402
from calendar_panel import settings as cs  # noqa: E402
from calendar_panel import view as cv  # noqa: E402

KEYS = ("text", "dim", "accent", "event", "event_text", "now", "now_line", "grid", "warn")


def pump(app, n=15):
    for _ in range(n):
        app.root.update()


class TestPure(unittest.TestCase):
    def test_keys_are_the_real_palette_keys_without_bg(self):
        pal = cv.make_palette("#3a5f8a", "#ffffff")
        self.assertEqual(set(pal) - {"bg"}, set(cs.COLOR_KEYS))
        self.assertEqual(tuple(cs.COLOR_KEYS), KEYS)

    def test_override_replaces_only_that_key(self):
        base = cv.make_palette("#3a5f8a", "#ffffff")
        pal = cv.make_palette("#3a5f8a", "#ffffff", {"event": "#112233"})
        self.assertEqual(pal["event"], "#112233")
        self.assertEqual({k: v for k, v in pal.items() if k != "event"}, {k: v for k, v in base.items() if k != "event"})

    def test_bg_cannot_be_overridden(self):
        base = cv.make_palette("#3a5f8a", "#ffffff")
        self.assertEqual(cv.make_palette("#3a5f8a", "#ffffff", {"bg": "#ff0000"})["bg"], base["bg"])

    def test_non_overridden_follow_panel_color_overridden_stay(self):
        ov = {"event": "#112233"}
        a = cv.make_palette("#3a5f8a", "#ffffff", ov)
        b = cv.make_palette("#8a3a3a", "#ffffff", ov)
        self.assertEqual(a["event"], b["event"])
        self.assertNotEqual(a["now"], b["now"])
        self.assertNotEqual(a["accent"], b["accent"])

    def test_sanitize_default_is_empty(self):
        self.assertEqual(cs.sanitize({})["colors"], {})
        self.assertEqual(cs.sanitize(None)["colors"], {})

    def test_sanitize_keeps_valid_normalises_case(self):
        self.assertEqual(cs.sanitize({"colors": {"event": "#AABBCC", "now": " #001122 "}})["colors"],
                         {"event": "#aabbcc", "now": "#001122"})

    def test_sanitize_drops_broken_values_and_unknown_keys(self):
        bad = {"event": "red", "now": "#12345", "grid": "#1234567", "dim": 5, "text": None, "accent": "#gggggg",
               "bg": "#ffffff", "head_bg": "#ffffff", "nonsense": "#ffffff", "warn": ["#ffffff"]}
        self.assertEqual(cs.sanitize({"colors": bad})["colors"], {})
        for junk in ("x", 5, None, ["#ffffff"]):
            self.assertEqual(cs.sanitize({"colors": junk})["colors"], {})

    def test_sanitize_is_idempotent(self):
        once = cs.sanitize({"colors": {"event": "#AABBCC", "zzz": "#ffffff"}})
        self.assertEqual(cs.sanitize(once), once)


@unittest.skipUnless(calendar_panel.AVAILABLE, "calendar libraries not installed")
class TestUi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mpanels_t110s5_")
        desk, pub, self.data = (os.path.join(self.tmp, n) for n in ("Desktop", "Public", "veri"))
        os.makedirs(desk)
        os.makedirs(pub)
        p = mock.patch("calendar_panel.model.CalendarModel.refresh", lambda *a, **k: None)
        p.start()
        self.addCleanup(p.stop)
        self.app = mpanels.App(fileops.Ctx(desk, pub), self.data, test_mode=True, use_tray=False,
                               instance_name="t110s5_%d" % os.getpid())
        self.cp = self.app.new_panel("Cal", "calendar")
        pump(self.app)
        self.app.open_settings("Cal")
        pump(self.app)
        self.S = self.app.settings_win
        self.S.nb.select(self.S.tab["calendar"])                       # swatches must be mapped to take clicks
        pump(self.app, 20)

    def tearDown(self):
        try:
            self.app.quit()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def s(self):
        return self.cp.cfg["calendar"]

    def pick(self, key, color):
        with mock.patch("mpanels.colorchooser.askcolor", return_value=((0, 0, 0), color)):
            self.S.cal_col_ui[key][0].event_generate("<Button-1>")      # the swatch is the picker
            self.S.win.update()

    def test_one_picker_per_real_key(self):
        self.assertEqual(tuple(self.S.cal_col_ui), KEYS)
        self.assertNotIn("bg", self.S.cal_col_ui)
        self.assertNotIn("head_bg", self.S.cal_col_ui)
        for key, (sw, mark, rb) in self.S.cal_col_ui.items():
            self.assertEqual(str(sw.winfo_toplevel()), str(self.S.win))
            self.assertEqual(mark.cget("text"), "")                      # nothing overridden: no marker
            self.assertIn("disabled", rb.state())

    def test_pick_does_nothing_until_apply_and_is_dirty(self):
        S = self.S
        self.assertFalse(S.dirty())
        self.pick("event", "#112233")
        self.assertEqual(self.s()["colors"], {})                         # Apply rule
        self.assertEqual(self.cp.cal_palette()["event"], cv.make_palette(self.cp.cfg["color"], self.cp.cfg["content_color"])["event"])
        self.assertTrue(S.dirty())
        self.assertEqual(S.cal_col_ui["event"][1].cget("text"), ui.CAL_COLOR_MARK)
        self.assertNotIn("disabled", S.cal_col_ui["event"][2].state())
        self.assertEqual(S.cal_col_ui["event"][0].cget("bg"), "#112233")

    def test_unsaved_prompt_cancel_discard_apply(self):
        S = self.S
        self.pick("now", "#445566")
        with mock.patch.object(S, "ask_unsaved", return_value="cancel") as q:
            self.assertFalse(S._resolve_unsaved())
            q.assert_called_once()
        with mock.patch.object(S, "ask_unsaved", return_value="discard"):
            self.assertTrue(S._resolve_unsaved())
        self.assertEqual(self.s()["colors"], {})
        S.select("Cal")                                                  # Discard then reload: form is back to applied
        self.assertEqual(S.cal_colors, {})
        self.assertFalse(S.dirty())
        self.pick("now", "#445566")
        with mock.patch.object(S, "ask_unsaved", return_value="apply"):
            self.assertTrue(S._resolve_unsaved())
        self.assertEqual(self.s()["colors"], {"now": "#445566"})

    def test_apply_writes_and_reads_back_only_overrides(self):
        S = self.S
        self.pick("event", "#112233")
        self.pick("grid", "#AABBCC")
        S.apply()
        self.assertEqual(self.s()["colors"], {"event": "#112233", "grid": "#aabbcc"})
        self.assertFalse(S.dirty())
        self.app.save()
        import json
        with open(self.app.cfg_path if hasattr(self.app, "cfg_path") else os.path.join(self.data, "config.json"), encoding="utf-8") as f:
            raw = json.load(f)
        saved = next(p for p in raw["panels"].values() if p.get("type") == "calendar") if isinstance(raw["panels"], dict) \
            else next(p for p in raw["panels"] if p.get("type") == "calendar")
        self.assertEqual(saved["calendar"]["colors"], {"event": "#112233", "grid": "#aabbcc"})   # only the overrides
        S.select("Cal")                                                  # form reads them back
        self.assertEqual(S.cal_colors, {"event": "#112233", "grid": "#aabbcc"})
        self.assertEqual(S.cal_col_ui["grid"][1].cget("text"), ui.CAL_COLOR_MARK)
        self.assertEqual(S.cal_col_ui["text"][1].cget("text"), "")

    def test_non_overridden_follow_panel_color_after_apply(self):
        S = self.S
        self.pick("event", "#112233")
        S.apply()
        before = self.cp.cal_palette()
        self.cp.cfg["color"] = "#8a3a3a"
        after = self.cp.cal_palette()
        self.assertEqual(after["event"], "#112233")
        self.assertNotEqual(after["accent"], before["accent"])
        self.assertNotEqual(after["now"], before["now"])

    def test_single_reset_removes_only_that_key(self):
        S = self.S
        self.pick("event", "#112233")
        self.pick("now", "#445566")
        S.apply()
        S.reset_cal_color("event")
        self.assertEqual(self.s()["colors"], {"event": "#112233", "now": "#445566"})   # still needs Apply
        self.assertTrue(S.dirty())
        S.apply()
        self.assertEqual(self.s()["colors"], {"now": "#445566"})
        self.assertEqual(S.cal_col_ui["event"][1].cget("text"), "")
        self.assertIn("disabled", S.cal_col_ui["event"][2].state())

    def test_bulk_revert_asks_and_clears_all(self):
        S = self.S
        self.pick("event", "#112233")
        self.pick("now", "#445566")
        S.apply()
        with mock.patch("mpanels.messagebox.askyesno", return_value=False) as q:
            S.revert_cal_colors()
            q.assert_called_once()
        self.assertEqual(S.cal_colors, {"event": "#112233", "now": "#445566"})          # "No": nothing happens
        self.assertFalse(S.dirty())
        with mock.patch("mpanels.messagebox.askyesno", return_value=True) as q:
            S.revert_cal_colors()
            self.assertEqual(q.call_args[0][1], ui.CONFIRM_CAL_COLORS_REVERT)
        self.assertEqual(S.cal_colors, {})
        self.assertEqual(self.s()["colors"], {"event": "#112233", "now": "#445566"})   # Apply rule
        self.assertTrue(S.dirty())
        S.apply()
        self.assertEqual(self.s()["colors"], {})
        self.assertIn("disabled", S.btn_cal_revert.state())

    def test_cancelled_color_dialog_changes_nothing(self):
        with mock.patch("mpanels.colorchooser.askcolor", return_value=(None, None)):
            self.S.pick_cal_color("event")
        self.assertEqual(self.S.cal_colors, {})
        self.assertFalse(self.S.dirty())

    def test_broken_config_values_fall_back_to_derived(self):
        self.cp.cfg["calendar"]["colors"] = {"event": "banana", "bg": "#ff0000", "now": "#010203"}
        self.cp.cal_settings_changed()
        s = self.s()["colors"]
        self.assertEqual(s, {"now": "#010203"})
        pal = self.cp.cal_palette()
        self.assertEqual(pal["now"], "#010203")
        self.assertEqual(pal["event"], cv.make_palette(self.cp.cfg["color"], self.cp.cfg["content_color"])["event"])

    def test_drawing_uses_the_overridden_color(self):
        today = date.today()
        st = datetime(today.year, today.month, today.day, 14, 30)
        ev = {"day": today, "all_day": True, "first": True, "title": "Meet", "start": st, "end": st + timedelta(hours=1),
              "seg_start": st, "seg_end": st + timedelta(hours=1), "location": "", "color": None, "cal": "c"}
        self.pick("event", "#123456")
        self.pick("accent", "#654321")
        self.S.apply()
        cal, c = self.cp.cal, self.cp.cal_cv
        cal.s["view"] = "list"
        cal.model.events_between = lambda d0, d1: [dict(ev)]
        c.delete("all")
        cal._draw_list(c, 700)
        fills = {c.itemcget(i, "fill") for i in c.find_all() if c.type(i) in ("rectangle", "text")}
        self.assertIn("#123456", fills)                                   # event bar (no per-calendar color)
        self.assertIn("#654321", fills)                                   # today's day label uses the accent
        S = self.S
        S.reset_cal_color("event")
        S.reset_cal_color("accent")
        S.apply()
        c.delete("all")
        cal._draw_list(c, 700)
        fills = {c.itemcget(i, "fill") for i in c.find_all() if c.type(i) in ("rectangle", "text")}
        self.assertNotIn("#123456", fills)
        self.assertNotIn("#654321", fills)


@unittest.skipUnless(calendar_panel.AVAILABLE, "calendar libraries not installed")
class TestOpenGoogleFalse(unittest.TestCase):
    def test_false_return_is_logged(self):
        tmp = tempfile.mkdtemp(prefix="mpanels_t110s5b_")
        self.addCleanup(shutil.rmtree, tmp, True)
        desk, pub, data = (os.path.join(tmp, n) for n in ("Desktop", "Public", "veri"))
        os.makedirs(desk)
        os.makedirs(pub)
        with mock.patch("calendar_panel.model.CalendarModel.refresh", lambda *a, **k: None):
            app = mpanels.App(fileops.Ctx(desk, pub), data, test_mode=True, use_tray=False,
                              instance_name="t110s5b_%d" % os.getpid())
            self.addCleanup(app.quit)
            cp = app.new_panel("Cal", "calendar")
            pump(app)
            with mock.patch("mpanels.webbrowser.open", return_value=False) as op, \
                    mock.patch.object(applog.get_logger(), "warning") as lg, \
                    mock.patch("mpanels.messagebox.showwarning") as w:
                cp.cal_open_google()
            op.assert_called_once_with("https://calendar.google.com/")
            lg.assert_called_once()
            self.assertIn("no browser", str(lg.call_args))
            w.assert_not_called()
            with mock.patch("mpanels.webbrowser.open", return_value=True), \
                    mock.patch.object(applog.get_logger(), "warning") as lg:
                cp.cal_open_google()
            lg.assert_not_called()


if __name__ == "__main__":
    unittest.main()
