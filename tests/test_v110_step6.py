"""v1.1 step 6: 'Make current Calendar look the default' (defaults.json > calendar_look), new panels, Revert, Factory."""
import json
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
from calendar_panel import settings as cs  # noqa: E402

EXCLUDED = {"calendars", "view", "list_weeks", "refresh_minutes"}


CAL_A = {"name": "A", "url": "https://x.invalid/secret-a", "color": None, "enabled": True}
CAL_B = {"name": "B", "url": "https://x.invalid/secret-b", "color": None, "enabled": True}


def pump(app, n=15):
    for _ in range(n):
        app.root.update()


class TestPure(unittest.TestCase):
    def test_subset_is_defined_once_and_excludes_the_right_keys(self):
        self.assertEqual(set(cs.DEFAULTS) - set(cs.LOOK_KEYS), EXCLUDED)
        self.assertEqual(set(cs.look_of(None)), set(cs.LOOK_KEYS))
        self.assertEqual(len(cs.LOOK_KEYS), len(set(cs.LOOK_KEYS)))
        for k in ("colors", "widths", "shrink_empty", "time_format", "week_start", "past_fade", "fit_boxes",
                  "empty_hour_height", "hour_height", "start_hour", "end_hour"):
            self.assertIn(k, cs.LOOK_KEYS)

    def test_look_of_ignores_excluded_keys(self):
        look = cs.look_of({"source_path": "x.json", "view": "week", "calendars": [CAL_A], "list_weeks": 3,
                           "refresh_minutes": 9, "start_hour": 9})
        self.assertEqual(set(look), set(cs.LOOK_KEYS))
        self.assertEqual(look["start_hour"], 9)

    def test_with_look_keeps_non_look_keys_and_ignores_extras_in_look(self):
        s = cs.sanitize({"view": "week", "calendars": [CAL_A], "list_weeks": 3, "refresh_minutes": 9})
        out = cs.with_look(s, {"start_hour": 5, "view": "day", "calendars": [CAL_B], "list_weeks": 4})
        self.assertEqual((out["view"], out["calendars"], out["list_weeks"], out["refresh_minutes"]),
                         ("week", [CAL_A], 3, 9))
        self.assertNotIn("x.invalid", repr(cs.look_of(out)))            # the look never carries an address
        self.assertEqual(out["start_hour"], 5)

    def test_broken_or_missing_look_falls_back_to_builtin(self):
        builtin = {k: cs.DEFAULTS[k] for k in cs.LOOK_KEYS}
        for junk in (None, "x", 5, [], {"start_hour": "abc", "colors": "red", "widths": 3, "time_format": "13h"}):
            self.assertEqual(cs.look_of(junk), builtin, junk)

    def test_partial_look_fills_missing_with_builtin(self):
        look = cs.look_of({"hour_height": 50, "colors": {"event": "#112233", "bogus": "#ffffff", "now": "nope"}})
        self.assertEqual(look["hour_height"], 50)
        self.assertEqual(look["colors"], {"event": "#112233"})
        self.assertEqual(look["past_fade"], cs.DEFAULTS["past_fade"])


@unittest.skipUnless(calendar_panel.AVAILABLE, "calendar libraries not installed")
class TestUi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mpanels_t110s6_")
        self.desk, self.pub, self.data = (os.path.join(self.tmp, n) for n in ("Desktop", "Public", "veri"))
        os.makedirs(self.desk)
        os.makedirs(self.pub)
        p = mock.patch("calendar_panel.model.CalendarModel.refresh", lambda *a, **k: None)
        p.start()
        self.addCleanup(p.stop)
        self.app = mpanels.App(fileops.Ctx(self.desk, self.pub), self.data, test_mode=True, use_tray=False,
                               instance_name="t110s6_%d" % os.getpid())
        self.addCleanup(self.app.quit)
        self.cp = self.app.new_panel("Cal", "calendar")
        pump(self.app)
        self.app.open_settings("Cal")
        pump(self.app)
        self.S = self.app.settings_win

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def s(self):
        return self.cp.cfg["calendar"]

    def saved(self):
        with open(self.app.defaults_path, encoding="utf-8") as f:
            return json.load(f)

    def customise(self):
        """Edit the form + Apply: a look that differs from the built-in one, plus non-look settings."""
        S = self.S
        S.v["cal_start"].set("9")
        S.v["cal_end"].set("20")
        S.v["cal_hh"].set("44")
        S.v["cal_fade"].set("30")
        S.v_cal_tf.set("12-hour")
        S.v_cal_ws.set("Sunday")
        S.cal_list = [dict(CAL_A)]
        S.v_cal_shrink.set(False)
        S.v["cal_weeks"].set("3")
        S.v["cal_refresh"].set("17")
        S.v["cal_view"].set("Week")
        S.cal_colors = {"event": "#112233"}
        S.apply()
        self.s()["widths"] = {"week": 777}
        pump(self.app)

    def save_default(self, answer=True):
        with mock.patch("mpanels.messagebox.askyesno", return_value=answer) as q, \
                mock.patch("mpanels.messagebox.showinfo") as info:
            self.S.make_cal_look_default()
        return q, info

    def test_button_exists_with_one_line_help(self):
        self.assertEqual(self.S.btn_cal_look_default.cget("text"), ui.BTN_CAL_MAKE_DEFAULT)
        for word in ("Factory", "Revert to defaults", "keeps your saved default"):
            self.assertIn(word, ui.CAL_LOOK_HELP)
        self.assertNotIn("\n", ui.CAL_LOOK_HELP)

    def test_saves_only_the_look_subset(self):
        self.customise()
        q, _ = self.save_default()
        q.assert_called_once()
        look = self.saved()[mpanels.CAL_LOOK_KEY]
        self.assertEqual(set(look), set(cs.LOOK_KEYS))
        self.assertTrue(EXCLUDED.isdisjoint(look))
        self.assertEqual((look["start_hour"], look["end_hour"], look["hour_height"], look["past_fade"]), (9, 20, 44, 30))
        self.assertEqual((look["time_format"], look["week_start"], look["shrink_empty"]), ("12h", "sunday", False))
        self.assertEqual(look["colors"], {"event": "#112233"})
        self.assertEqual(look["widths"], {"week": 777})
        with open(self.app.defaults_path, encoding="utf-8") as f:
            self.assertNotIn("secret-a", f.read())                       # no address in defaults.json

    def test_declined_confirmation_saves_nothing(self):
        self.customise()
        self.save_default(answer=False)
        self.assertFalse(os.path.exists(self.app.defaults_path) and mpanels.CAL_LOOK_KEY in self.saved())

    def test_unapplied_changes_warn_and_nothing_is_saved(self):
        self.customise()
        self.S.v["cal_hh"].set("99")                                     # form edit, NOT applied
        self.assertTrue(self.S.dirty())
        q, info = self.save_default()
        info.assert_called_once()
        self.assertEqual(info.call_args[0][1], ui.MSG_CAL_LOOK_APPLY_FIRST)
        q.assert_not_called()
        self.assertFalse(os.path.exists(self.app.defaults_path) and mpanels.CAL_LOOK_KEY in self.saved())

    def test_saves_the_applied_state_not_the_form(self):
        self.customise()
        self.S.apply()
        self.assertFalse(self.S.dirty())
        self.save_default()
        self.assertEqual(self.saved()[mpanels.CAL_LOOK_KEY]["hour_height"], 44)

    def test_new_calendar_panel_opens_with_the_saved_look_but_default_non_look(self):
        self.customise()
        self.save_default()
        c2 = self.app.new_panel("Cal2", "calendar")
        pump(self.app)
        s = c2.cfg["calendar"]
        self.assertEqual((s["start_hour"], s["end_hour"], s["hour_height"], s["past_fade"]), (9, 20, 44, 30))
        self.assertEqual((s["time_format"], s["week_start"], s["shrink_empty"]), ("12h", "sunday", False))
        self.assertEqual(s["colors"], {"event": "#112233"})
        self.assertEqual(s["widths"], {"week": 777})
        self.assertEqual((s["view"], s["list_weeks"], s["refresh_minutes"], s["calendars"]),
                         (cs.DEFAULTS["view"], cs.DEFAULTS["list_weeks"], cs.DEFAULTS["refresh_minutes"], []))

    def test_new_panel_without_saved_look_is_builtin(self):
        c2 = self.app.new_panel("Cal2", "calendar")
        pump(self.app)
        self.assertEqual(c2.cfg["calendar"], cs.sanitize(None))

    def test_revert_returns_to_saved_look_factory_to_builtin_and_keeps_the_saved_one(self):
        self.customise()
        self.save_default()
        cals = self.s()["calendars"]
        # change the look afterwards
        self.S.v["cal_hh"].set("70")
        self.S.v_cal_tf.set("24-hour")
        self.S.cal_colors = {"now": "#445566"}
        self.S.apply()
        self.s()["widths"] = {"list": 301}
        with mock.patch("mpanels.messagebox.askyesno", return_value=True):
            self.S.reset(False)                                          # Revert to defaults
        s = self.s()
        self.assertEqual((s["hour_height"], s["time_format"], s["colors"], s["widths"]),
                         (44, "12h", {"event": "#112233"}, {"week": 777}))
        self.assertEqual((s["view"], s["list_weeks"], s["refresh_minutes"], s["calendars"]),
                         ("week", 3, 17, cals))                     # non-look settings untouched
        self.assertEqual(self.S.v["cal_hh"].get(), "44")                 # the form shows it
        with mock.patch("mpanels.messagebox.askyesno", return_value=True):
            self.S.reset(True)                                           # Factory settings
        s = self.s()
        b = {k: cs.DEFAULTS[k] for k in cs.LOOK_KEYS}
        self.assertEqual({k: s[k] for k in cs.LOOK_KEYS}, b)
        self.assertEqual((s["view"], s["list_weeks"], s["refresh_minutes"]), ("week", 3, 17))
        look = self.saved()[mpanels.CAL_LOOK_KEY]                        # Factory does not delete the saved default
        self.assertEqual((look["hour_height"], look["colors"]), (44, {"event": "#112233"}))
        with mock.patch("mpanels.messagebox.askyesno", return_value=True):
            self.S.reset(False)                                          # ...and Revert brings it back
        self.assertEqual(self.s()["hour_height"], 44)

    def test_revert_declined_changes_nothing(self):
        self.customise()
        self.save_default()
        self.S.v["cal_hh"].set("70")
        self.S.apply()
        with mock.patch("mpanels.messagebox.askyesno", return_value=False):
            self.S.reset(False)
        self.assertEqual(self.s()["hour_height"], 70)

    def test_revert_without_saved_look_uses_builtin(self):
        self.customise()
        with mock.patch("mpanels.messagebox.askyesno", return_value=True):
            self.S.reset(False)
        self.assertEqual({k: self.s()[k] for k in cs.LOOK_KEYS}, {k: cs.DEFAULTS[k] for k in cs.LOOK_KEYS})

    def test_general_make_default_keeps_the_saved_calendar_look(self):
        self.customise()
        self.save_default()
        self.S.make_default()                                            # appearance only
        d = self.saved()
        self.assertIn(mpanels.CAL_LOOK_KEY, d)
        self.assertIn("color", d)
        self.assertEqual(d[mpanels.CAL_LOOK_KEY]["hour_height"], 44)

    def test_calendar_look_default_keeps_the_saved_appearance(self):
        self.S.make_default()
        before = {k: v for k, v in self.saved().items()}
        self.customise()
        self.save_default()
        d = self.saved()
        for k, v in before.items():
            self.assertEqual(d[k], v)

    def test_broken_defaults_file_does_not_crash(self):
        for raw in ("not json", "[]", '{"calendar_look": 5}', '{"calendar_look": {"start_hour": "x", "colors": 1}}',
                    '{"color": "#123456"}'):
            with open(self.app.defaults_path, "w", encoding="utf-8") as f:
                f.write(raw)
            look = self.app.calendar_look()
            self.assertEqual(look, {k: cs.DEFAULTS[k] for k in cs.LOOK_KEYS}, raw)
            c = self.app.new_panel("X" + str(abs(hash(raw)))[:5], "calendar")
            self.assertIsNotNone(c)
            self.app.defaults()                                          # appearance defaults still load
        self.assertEqual(self.app.calendar_look(factory=True), {k: cs.DEFAULTS[k] for k in cs.LOOK_KEYS})

    def test_old_config_without_the_key_and_shortcut_panels_unaffected(self):
        if os.path.exists(self.app.defaults_path):
            os.remove(self.app.defaults_path)
        sc = self.app.new_panel("Short", "shortcut")
        pump(self.app)
        self.assertNotIn("calendar", sc.cfg)
        self.customise()
        self.save_default()
        sc2 = self.app.new_panel("Short2", "shortcut")
        self.assertNotIn("calendar", sc2.cfg)
        self.assertNotIn(mpanels.CAL_LOOK_KEY, sc2.cfg)


if __name__ == "__main__":
    unittest.main()
