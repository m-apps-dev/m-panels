"""v1.1 step 1: Settings > Calendar controls for the Day/Week look (first/last hour, hour height, empty hour height,
fit boxes) and past-event fading. Apply rule (nothing changes without Apply, unsaved-changes question covers them),
Day/Week redraw after Apply, validation, and the CHANGELOG '## Unreleased' section."""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import calendar_panel  # noqa: E402
import changelog  # noqa: E402
import fileops  # noqa: E402
import mpanels  # noqa: E402
import version  # noqa: E402
from calendar_panel import settings as cal_settings  # noqa: E402


def pump(app, n=15):
    for _ in range(n):
        app.root.update()


def texts(cv):
    return [cv.itemcget(i, "text") for i in cv.find_all() if cv.type(i) == "text"]


class TestChangelogUnreleased(unittest.TestCase):
    TXT = """# Changelog

## Unreleased

### Calendar
- in progress

## 1.2.3 — 2026-01-01

### General
- released
"""

    def test_unreleased_is_not_a_release_and_is_skipped(self):
        r = changelog.parse(self.TXT)
        self.assertEqual([x["version"] for x in r], ["1.2.3"])
        self.assertEqual(r[0]["sections"], [("General", ["released"])])

    def test_unreleased_in_the_middle_does_not_leak_into_the_previous_release(self):
        txt = "## 1.0.0 — 2026-01-01\n\n### General\n- a\n\n## Unreleased\n\n### General\n- wip\n\n## 0.9.0 — 2025-01-01\n\n### General\n- b\n"
        r = changelog.parse(txt)
        self.assertEqual([x["version"] for x in r], ["1.0.0", "0.9.0"])
        self.assertEqual(r[0]["sections"], [("General", ["a"])])

    def test_real_changelog_has_the_entry_for_this_step_in_the_release(self):
        # v1.1.0 was released (7c): its section holds the step 1 entry. (An '## Unreleased' section may exist again
        # while the next version is in progress: the parser skips it, see the test below.)
        with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
            text = f.read()
        rel = text.split("## 1.1.0", 1)[1].split("\n## ", 1)[0]
        self.assertIn("Settings > Calendar", rel)
        self.assertNotIn("Unreleased", [r["version"] for r in changelog.load()])
        self.assertEqual(changelog.load()[0]["version"], version.__version__)   # newest real release = current version


@unittest.skipUnless(calendar_panel.AVAILABLE, "calendar libraries not installed")
class TestCalendarLookSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mpanels_t110_")
        desk, pub, self.data = (os.path.join(self.tmp, n) for n in ("Desktop", "Public", "veri"))
        os.makedirs(desk)
        os.makedirs(pub)
        p = mock.patch("calendar_panel.model.CalendarModel.refresh", lambda *a, **k: None)   # no source file / network
        p.start()
        self.addCleanup(p.stop)
        self.app = mpanels.App(fileops.Ctx(desk, pub), self.data, test_mode=True, use_tray=False,
                               instance_name="t110_%d" % os.getpid())
        self.cp = self.app.new_panel("Cal", "calendar")
        pump(self.app)
        self.app.open_settings("Cal")
        pump(self.app)
        self.S = self.app.settings_win

    def tearDown(self):
        try:
            self.app.quit()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def s(self):
        return self.cp.cfg["calendar"]

    def test_denetimler_calendar_sekmesinde_ve_degerleri_gosteriyor(self):
        S, s = self.S, self.s()
        self.assertEqual(len(S.cal_look_widgets), 9)               # 5 spinboxes + 2 checkboxes + 2 dropdowns
        for var, key in S.CAL_LOOK_KEYS.items():
            self.assertEqual(S.v[var].get(), str(s[key]))
        self.assertEqual(S.v_cal_fit.get(), s["fit_boxes"])
        for w in S.cal_look_widgets:
            self.assertEqual(str(w.winfo_toplevel()), str(S.win))
        self.assertIn(str(S.tab["calendar"]), S.nb.tabs())

    def test_apply_olmadan_hicbir_sey_degismez_ve_uyari_sorulur(self):
        S = self.S
        before = dict(self.s())
        self.assertFalse(S.dirty())
        S.v["cal_start"].set("9")
        S.v["cal_fade"].set("10")
        S.v_cal_fit.set(not before["fit_boxes"])
        self.assertEqual(self.s(), before)                         # nothing changed in the panel
        self.assertTrue(S.dirty())                                 # ...but the window knows it is unsaved
        with mock.patch.object(S, "ask_unsaved", return_value="cancel") as q:
            self.assertFalse(S._resolve_unsaved())                 # Cancel: stay
            q.assert_called_once()
        with mock.patch.object(S, "ask_unsaved", return_value="discard"):
            self.assertTrue(S._resolve_unsaved())                  # Discard: leave without applying
        self.assertEqual(self.s(), before)

    def test_apply_secenegi_uyarida_uygular(self):
        S = self.S
        S.v["cal_hh"].set("64")
        with mock.patch.object(S, "ask_unsaved", return_value="apply"):
            self.assertTrue(S._resolve_unsaved())
        self.assertEqual(self.s()["hour_height"], 64)

    def test_secilen_panel_degisince_form_o_panelin_degerlerini_yukler(self):
        S = self.S
        other = self.app.new_panel("Cal2", "calendar")
        pump(self.app)
        other.cfg["calendar"]["hour_height"] = 88
        S.refresh_panels()
        S.select("Cal2")
        self.assertEqual(S.v["cal_hh"].get(), "88")
        S.select("Cal")
        self.assertEqual(S.v["cal_hh"].get(), str(self.s()["hour_height"]))

    def test_apply_degerleri_kaydeder_ve_day_gorunumune_hemen_yansir(self):
        S, cp = self.S, self.cp
        S.v["cal_view"].set(S.cal_view_labels["day"])              # the Day view (through the form, like a user)
        S.v["cal_start"].set("9")
        S.v["cal_end"].set("12")
        S.v["cal_hh"].set("40")
        S.v["cal_ehh"].set("10")
        S.v["cal_fade"].set("20")
        S.v_cal_fit.set(False)
        before = texts(cp.cal_cv)
        self.assertTrue(S.apply())
        pump(self.app)
        s = self.s()
        self.assertEqual((s["start_hour"], s["end_hour"], s["hour_height"], s["empty_hour_height"], s["past_fade"],
                          s["fit_boxes"]), (9, 12, 40, 10, 20, False))
        after = texts(cp.cal_cv)
        for h in ("09", "10", "11"):
            self.assertIn(h, after)                                # hour labels follow the new range
        self.assertNotIn("08", after)
        self.assertNotIn("12", after)                              # the end hour is exclusive
        self.assertNotEqual(before, after)
        self.assertFalse(S.dirty())                                # applied = clean again
        saved = mpanels.load_json(self.app.config_path, {})["panels"]["Cal"]["calendar"]
        self.assertEqual((saved["start_hour"], saved["end_hour"], saved["past_fade"], saved["fit_boxes"]),
                         (9, 12, 20, False))

    def test_gecersiz_giris_duzeltilir_ve_uyari_verir(self):
        S = self.S
        S.v["cal_hh"].set("abc")
        S.v["cal_fade"].set("500")
        S.v["cal_start"].set("20")
        S.v["cal_end"].set("5")
        self.assertTrue(S.apply())
        s = self.s()
        self.assertEqual(s["hour_height"], cal_settings.DEFAULTS["hour_height"])     # unreadable -> default
        self.assertEqual(s["past_fade"], 90)                                          # clamped
        self.assertEqual(s["start_hour"], 20)
        self.assertGreater(s["end_hour"], s["start_hour"])                            # end > start is enforced
        msg = S.msg.cget("text")
        for word in ("Hour height", "Fade past", "Last hour"):
            self.assertIn(word, msg)
        self.assertEqual(S.v["cal_hh"].get(), str(s["hour_height"]))                  # the form shows the real value
        self.assertEqual(S.v["cal_end"].get(), str(s["end_hour"]))

    def test_gecerli_girislerde_aralik_uyarisi_yok(self):
        S = self.S
        S.v["cal_hh"].set("50")
        S.apply()
        self.assertNotIn("must be a whole number", S.msg.cget("text"))

    def test_panelde_gorunum_degisince_form_guncellenir_ve_kirli_sayilmaz(self):
        S, cp = self.S, self.cp
        snap = S._panel_snapshot()
        self.assertEqual((snap[S.SNAP_CAL_VIEW], snap[S.SNAP_CAL_WEEKS]), (S.v["cal_view"].get(), S.v["cal_weeks"].get()))
        self.assertEqual(S.v["cal_view"].get(), S.cal_view_labels["list"])
        cp.cal.set_view("day")                                      # the user clicks "Day" on the panel
        self.assertEqual(S.v["cal_view"].get(), S.cal_view_labels["day"])
        self.assertFalse(S.dirty())                                  # not an unsaved change
        S.v["cal_hh"].set("55")
        S.apply()                                                    # Apply must NOT send the view back to List
        self.assertEqual(self.s()["view"], "day")
        cp.cal.set_view("week")
        self.assertEqual(S.v["cal_view"].get(), S.cal_view_labels["week"])
        self.assertFalse(S.dirty())
        cp.cal.set_view("list")
        cp.cal.set_weeks(3)                                          # weeks (List view) are synced too
        self.assertEqual(S.v["cal_weeks"].get(), "3")
        self.assertFalse(S.dirty())
        S.apply()
        self.assertEqual((self.s()["view"], self.s()["list_weeks"]), ("list", 3))

    def test_panelde_gorunum_degisince_diger_duzenlemeler_kaydedilmemis_kalir(self):
        S, cp = self.S, self.cp
        S.v["cal_hh"].set("90")                                      # an edit not applied yet
        cp.cal.set_view("day")
        self.assertTrue(S.dirty())                                   # still unsaved (the hour height)
        self.assertEqual(S.v["cal_hh"].get(), "90")
        self.assertEqual(S.v["cal_view"].get(), S.cal_view_labels["day"])
        S.apply()
        self.assertEqual((self.s()["view"], self.s()["hour_height"]), ("day", 90))

    def test_baska_panelin_gorunum_degisikligi_formu_etkilemez(self):
        S = self.S
        other = self.app.new_panel("Cal2", "calendar")
        pump(self.app)
        other.cal.set_view("week")
        self.assertEqual(S.v["cal_view"].get(), S.cal_view_labels["list"])
        self.assertFalse(S.dirty())

    def test_panel_degistirirken_discard_yeni_panelin_degerlerini_yukler(self):
        S = self.S
        other = self.app.new_panel("Cal2", "calendar")
        pump(self.app)
        other.cfg["calendar"].update(view="week", hour_height=88)
        S.refresh_panels()
        S.v["cal_hh"].set("99")                                      # unsaved edit on "Cal"
        S.v["cal_start"].set("3")
        with mock.patch.object(S, "ask_unsaved", return_value="discard"):
            S.v["panel"].set("Cal2")
            S.request_select("Cal2")
        self.assertEqual(S.cur, "Cal2")
        self.assertEqual(S.v["cal_hh"].get(), "88")                  # the NEW panel's values
        self.assertEqual(S.v["cal_start"].get(), str(other.cfg["calendar"]["start_hour"]))
        self.assertEqual(S.v["cal_view"].get(), S.cal_view_labels["week"])
        self.assertEqual(self.s()["hour_height"], cal_settings.DEFAULTS["hour_height"])   # "Cal" was not changed
        self.assertFalse(S.dirty())

    def test_baska_panel_turunde_takvim_sekmesi_yok(self):
        S = self.S
        self.app.new_panel("Notes", "note")
        S.refresh_panels()
        S.select("Notes")
        self.assertNotIn(str(S.tab["calendar"]), S.nb.tabs())


if __name__ == "__main__":
    unittest.main()
