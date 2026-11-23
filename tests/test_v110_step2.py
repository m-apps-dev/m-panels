"""v1.1 step 2: a calendar panel remembers its own width per view (List / Day / Week); the height stays shared.
Width is read from ONE function (PanelWin.target_width) so the stack rule (step 7) can plug in there."""
import copy
import os
import shutil
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import calendar_panel  # noqa: E402
import fileops  # noqa: E402
import mpanels  # noqa: E402
from calendar_panel import settings as cal_settings  # noqa: E402


def pump(app, n=15):
    for _ in range(n):
        app.root.update()


class TestWidthsSanitize(unittest.TestCase):
    def test_default_is_empty_and_not_shared(self):
        a = cal_settings.sanitize(None)
        self.assertEqual(a["widths"], {})
        a["widths"]["list"] = 500
        self.assertEqual(cal_settings.sanitize(None)["widths"], {})           # DEFAULTS was not mutated

    def test_valid_values_kept_and_clamped(self):
        s = cal_settings.sanitize({"widths": {"list": 420, "day": 50, "week": 99999}})
        self.assertEqual(s["widths"], {"list": 420, "day": cal_settings.WIDTH_MIN, "week": cal_settings.WIDTH_MAX})

    def test_broken_unknown_and_wrong_types_mean_not_recorded(self):
        s = cal_settings.sanitize({"widths": {"list": "abc", "day": None, "week": True, "month": 500}})
        self.assertEqual(s["widths"], {})
        self.assertEqual(cal_settings.sanitize({"widths": [1, 2]})["widths"], {})
        self.assertEqual(cal_settings.sanitize({"widths": "x"})["widths"], {})
        self.assertEqual(cal_settings.sanitize({"widths": {"list": "640"}})["widths"], {"list": 640})

    def test_min_width_matches_panel_minimum(self):
        self.assertEqual(cal_settings.WIDTH_MIN, mpanels.MIN_W)

    def test_height_is_not_a_per_view_setting(self):
        self.assertNotIn("heights", cal_settings.DEFAULTS)


@unittest.skipUnless(calendar_panel.AVAILABLE, "calendar libraries not installed")
class TestWidthPerView(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mpanels_t110b_")
        self.desk, self.pub, self.data = (os.path.join(self.tmp, n) for n in ("Desktop", "Public", "veri"))
        os.makedirs(self.desk)
        os.makedirs(self.pub)
        p = mock.patch("calendar_panel.model.CalendarModel.refresh", lambda *a, **k: None)   # no source file / network
        p.start()
        self.addCleanup(p.stop)
        self.apps = []
        self.app = self.open_app()
        self.cp = self.app.new_panel("Cal", "calendar")
        pump(self.app)

    def open_app(self):
        app = mpanels.App(fileops.Ctx(self.desk, self.pub), self.data, test_mode=True, use_tray=False,
                          instance_name="t110b_%d_%d" % (os.getpid(), len(self.apps)))
        self.apps.append(app)
        return app

    def tearDown(self):
        for a in self.apps:
            try:
                a.quit()
            except Exception:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def resize_to(self, p, w, h=None):
        """A real press-drag-release on the corner grip so that the width goes through the normal code path."""
        pump(self.app)
        cv = p.cal_cv
        p._cal_press(types.SimpleNamespace(x=cv.winfo_width() - 5, y=cv.winfo_height() - 5, x_root=100, y_root=100))
        p._body_drag(types.SimpleNamespace(x_root=100 + (w - p.cfg["w"]), y_root=100 + ((h or p.cfg["h"]) - p.cfg["h"])))
        p._body_release(types.SimpleNamespace(x_root=0, y_root=0))
        pump(self.app)

    def widths(self):
        return self.cp.cfg["calendar"]["widths"]

    def assert_width(self, w):
        pump(self.app)
        self.assertEqual((self.cp.cfg["w"], self.cp.cur_w, self.cp.top.winfo_width()), (w, w, w))

    def test_her_gorunum_kendi_genisligini_hatirlar(self):
        cp = self.cp
        x0 = cp.cfg["x"]
        self.resize_to(cp, 500)                                       # List
        self.assertEqual(self.widths(), {"list": 500})
        cp.cal.set_view("day")                                        # Day has no record: the width is kept
        self.assert_width(500)
        self.assertEqual(self.widths().get("list"), 500)
        self.resize_to(cp, 700)                                       # Day
        self.assertEqual(self.widths(), {"list": 500, "day": 700})
        cp.cal.set_view("list")                                       # back to List: its own width
        self.assert_width(500)
        cp.cal.set_view("week")                                       # no Week record: keep the current width
        self.assert_width(500)
        self.resize_to(cp, 900)
        cp.cal.set_view("day")
        self.assert_width(700)
        cp.cal.set_view("week")
        self.assert_width(900)
        self.assertEqual(self.widths(), {"list": 500, "day": 700, "week": 900})
        self.assertEqual(cp.cfg["x"], x0)                             # the left edge never moves

    def test_yukseklik_ortak(self):
        cp = self.cp
        self.resize_to(cp, 500, 400)
        h = cp.cfg["h"]
        self.assertEqual(h, 400)
        cp.cal.set_view("day")
        self.resize_to(cp, 700, 450)
        cp.cal.set_view("list")
        pump(self.app)
        self.assertEqual(cp.cfg["h"], 450)                            # shared: it follows the last resize
        self.assertEqual(cp.cur_h, 450)

    def test_ayarlar_apply_gorunumu_degistirince_genislik_gecer(self):
        cp = self.cp
        self.resize_to(cp, 500)
        cp.cfg["calendar"]["widths"]["week"] = 800
        self.app.open_settings("Cal")
        pump(self.app)
        S = self.app.settings_win
        S.v["cal_view"].set(S.cal_view_labels["week"])
        self.assertTrue(S.apply())
        self.assertEqual(cp.cfg["calendar"]["view"], "week")
        self.assert_width(800)
        self.assertEqual(self.widths()["list"], 500)                  # the width of the view we left was remembered

    def test_kapaliyken_genislik_degisir_yukseklik_baslik_kalir(self):
        cp = self.cp
        cp.cfg["calendar"]["widths"]["day"] = 640
        cp.toggle()
        end = time.time() + 1.0                                       # the collapse animation runs on timers
        while time.time() < end:
            self.app.root.update()
            time.sleep(0.01)
        self.assertFalse(cp.expanded)
        head = cp.cur_h
        self.assertEqual(head, cp.head_h)
        cp.cal.set_view("day")
        pump(self.app)
        self.assertEqual((cp.cfg["w"], cp.cur_w), (640, 640))
        self.assertEqual(cp.cur_h, head)                              # still collapsed

    def test_kilitliyken_gorunum_degisince_kayitli_genislik_gecer(self):
        cp = self.cp
        cp.cfg["calendar"]["widths"]["day"] = 610
        self.app.set_lock(True)
        cp.cal.set_view("day")
        self.assert_width(610)
        self.assertFalse(cp._in_cal_grip(cp.cal_cv.winfo_width() - 5, cp.cal_cv.winfo_height() - 5))   # no manual resize

    def test_genislik_tek_fonksiyondan_okunur(self):
        cp = self.cp
        self.assertEqual(cp.target_width(), cp.cfg["w"])              # nothing recorded: the panel's own width
        cp.cfg["calendar"]["widths"]["list"] = 555
        self.assertEqual(cp.target_width(), 555)
        cp.cfg["calendar"]["view"] = "day"
        self.assertEqual(cp.target_width(), cp.cfg["w"])              # Day has no record
        sc = self.app.new_panel("Docs", "shortcut")
        self.assertEqual(sc.target_width(), sc.cfg["w"])              # other panel types are untouched
        # apply_cfg (start-up / Settings > Apply) goes through the same function
        cp.cfg["calendar"]["widths"]["day"] = 480
        cp.apply_cfg()
        self.assert_width(480)

    def test_kayit_yeniden_acilista_korunur(self):
        cp = self.cp
        self.resize_to(cp, 520)
        cp.cal.set_view("week")
        self.resize_to(cp, 950)
        self.app.quit()
        self.apps.remove(self.app)
        app2 = self.open_app()
        pump(app2)
        p2 = app2.panels["Cal"]
        self.assertEqual(p2.cfg["calendar"]["view"], "week")
        self.assertEqual(p2.cfg["calendar"]["widths"], {"list": 520, "week": 950})
        pump(app2)
        self.assertEqual((p2.cfg["w"], p2.cur_w, p2.top.winfo_width()), (950, 950, 950))
        p2.cal.set_view("list")
        pump(app2)
        self.assertEqual(p2.cur_w, 520)

    def test_eski_config_widths_yokken_degismez(self):
        cp = self.cp
        w0 = cp.cfg["w"]
        raw = copy.deepcopy(self.app.cfg["panels"]["Cal"])
        raw["calendar"].pop("widths", None)                           # a pre-1.1 config entry
        self.app.cfg["panels"]["Cal"] = raw
        self.app.save()
        self.app.quit()
        self.apps.remove(self.app)
        app2 = self.open_app()
        pump(app2)
        p2 = app2.panels["Cal"]
        self.assertEqual(p2.cfg["calendar"]["widths"], {})
        self.assertEqual(p2.cur_w, w0)


if __name__ == "__main__":
    unittest.main()
