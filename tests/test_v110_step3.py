"""v1.1 step 3: 12/24-hour time (everywhere) and the first day of the week (Week view only)."""
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import calendar_panel  # noqa: E402
import fileops  # noqa: E402
import mpanels  # noqa: E402
from calendar_panel import core  # noqa: E402
from calendar_panel import settings as cal_settings  # noqa: E402


def pump(app, n=15):
    for _ in range(n):
        app.root.update()


def at(h, m=0):
    return datetime(2026, 11, 22, h, m)


class TestFormat(unittest.TestCase):
    def test_24h(self):
        self.assertEqual(core.fmt_time(at(0, 0)), "00:00")
        self.assertEqual(core.fmt_time(at(9, 5), "24h"), "09:05")
        self.assertEqual(core.fmt_time(at(23, 59), "24h"), "23:59")

    def test_12h_edges(self):
        f = lambda h, m=0, c=False: core.fmt_time(at(h, m), "12h", compact=c)       # noqa: E731
        self.assertEqual(f(0), "12 AM")
        self.assertEqual(f(0, 30), "12:30 AM")
        self.assertEqual(f(9), "9 AM")
        self.assertEqual(f(11, 59), "11:59 AM")
        self.assertEqual(f(12), "12 PM")
        self.assertEqual(f(12, 30), "12:30 PM")
        self.assertEqual(f(14, 30), "2:30 PM")
        self.assertEqual(f(23, 59), "11:59 PM")

    def test_12h_compact(self):
        f = lambda h, m=0: core.fmt_time(at(h, m), "12h", compact=True)             # noqa: E731
        self.assertEqual((f(9), f(0), f(12), f(14, 30), f(23)), ("9a", "12a", "12p", "2:30p", "11p"))

    def test_hour_labels(self):
        self.assertEqual(core.fmt_hour_label(7), "07")
        self.assertEqual(core.fmt_hour_label(7, "12h"), "7a")
        self.assertEqual(core.fmt_hour_label(12, "12h"), "12p")
        self.assertEqual(core.fmt_hour_label(0, "12h"), "12a")
        self.assertEqual(core.fmt_hour_label(24, "12h"), "12a")

    def test_unknown_format_is_24h(self):
        self.assertEqual(core.fmt_time(at(14, 30), "x"), "14:30")

    def test_sample_is_the_widest(self):
        self.assertEqual(core.time_sample("24h"), "12:30")
        self.assertEqual(core.time_sample("12h"), "12:30 PM")


class TestWeekStart(unittest.TestCase):
    def test_monday(self):
        self.assertEqual(core.week_start_of(date(2026, 11, 22)), date(2026, 11, 16))   # Sunday -> previous Monday
        self.assertEqual(core.week_start_of(date(2026, 11, 16)), date(2026, 11, 16))
        self.assertEqual(core.week_start_of(date(2026, 11, 18), "monday"), date(2026, 11, 16))

    def test_sunday(self):
        self.assertEqual(core.week_start_of(date(2026, 11, 22), "sunday"), date(2026, 11, 22))
        self.assertEqual(core.week_start_of(date(2026, 11, 21), "sunday"), date(2026, 11, 15))
        self.assertEqual(core.week_start_of(date(2026, 11, 16), "sunday"), date(2026, 11, 15))

    def test_year_edges(self):
        self.assertEqual(core.week_start_of(date(2027, 1, 1), "monday"), date(2026, 12, 28))     # Friday
        self.assertEqual(core.week_start_of(date(2027, 1, 1), "sunday"), date(2026, 12, 27))
        self.assertEqual(core.week_start_of(date(2026, 1, 1), "monday"), date(2025, 12, 29))     # Thursday
        self.assertEqual(core.week_start_of(date(2024, 12, 31), "sunday"), date(2024, 12, 29))

    def test_always_within_seven_days_and_right_weekday(self):
        d = date(2026, 1, 1)
        for i in range(800):
            x = d + timedelta(days=i)
            for ws, wd in (("monday", 0), ("sunday", 6)):
                s = core.week_start_of(x, ws)
                self.assertEqual(s.weekday(), wd)
                self.assertTrue(0 <= (x - s).days <= 6)


class TestSanitize(unittest.TestCase):
    def test_defaults_and_bad_values(self):
        s = cal_settings.sanitize(None)
        self.assertEqual((s["time_format"], s["week_start"]), ("24h", "monday"))
        s = cal_settings.sanitize({})                                              # old config without the keys
        self.assertEqual((s["time_format"], s["week_start"]), ("24h", "monday"))
        s = cal_settings.sanitize({"time_format": "12h", "week_start": "sunday"})
        self.assertEqual((s["time_format"], s["week_start"]), ("12h", "sunday"))
        s = cal_settings.sanitize({"time_format": "13h", "week_start": 3})
        self.assertEqual((s["time_format"], s["week_start"]), ("24h", "monday"))
        s = cal_settings.sanitize({"time_format": ["12h"], "week_start": None})
        self.assertEqual((s["time_format"], s["week_start"]), ("24h", "monday"))


@unittest.skipUnless(calendar_panel.AVAILABLE, "calendar libraries not installed")
class TestUi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mpanels_t110d_")
        self.desk, self.pub, self.data = (os.path.join(self.tmp, n) for n in ("Desktop", "Public", "veri"))
        os.makedirs(self.desk)
        os.makedirs(self.pub)
        p = mock.patch("calendar_panel.model.CalendarModel.refresh", lambda *a, **k: None)
        p.start()
        self.addCleanup(p.stop)
        self.app = mpanels.App(fileops.Ctx(self.desk, self.pub), self.data, test_mode=True, use_tray=False,
                               instance_name="t110d_%d" % os.getpid())
        self.addCleanup(self.app.quit)
        self.cp = self.app.new_panel("Cal", "calendar")
        pump(self.app)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ev(self, day, h, m, title):
        st = datetime(day.year, day.month, day.day, h, m)
        en = st + timedelta(hours=1)
        return {"day": day, "all_day": False, "first": True, "title": title, "start": st, "end": en,
                "seg_start": st, "seg_end": en, "location": "", "color": None, "cal": "c"}

    def texts(self, cv):
        return [cv.itemcget(i, "text") for i in cv.find_all() if cv.type(i) == "text"]

    def draw(self, view, events, **settings):
        cal, cv = self.cp.cal, self.cp.cal_cv
        cal.s.update(settings, view=view)
        cal.anchor = date.today()
        cal.model.events_between = lambda d0, d1: [dict(e) for e in events]
        cv.delete("all")
        cal.tips = []
        if view == "list":
            cal._draw_list(cv, 700)
        else:
            cal._draw_grid(cv, 700, 7 if view == "week" else 1)
        return cv

    def test_times_follow_the_setting_in_all_views_and_tooltip(self):
        today = date.today()
        ev = [self.ev(today, 14, 30, "Meet")]
        cv = self.draw("day", ev, time_format="12h")
        t = self.texts(cv)
        self.assertIn("7a", t)                                                      # grid label (start hour 7)
        self.assertNotIn("07", t)
        self.assertTrue(any(x.startswith("2:30 PM Meet") for x in t))              # Day: full time in the box
        self.assertTrue(any("2:30 PM–3:30 PM" in tip[4] for tip in self.cp.cal.tips))
        cv = self.draw("week", ev, time_format="12h")
        self.assertTrue(any(x.startswith("2:30p Meet") for x in self.texts(cv)))   # Week: compact in narrow boxes
        cv = self.draw("list", ev, time_format="12h")
        self.assertIn("2:30 PM", self.texts(cv))
        cv = self.draw("list", ev, time_format="24h")
        self.assertIn("14:30", self.texts(cv))
        cv = self.draw("day", ev, time_format="24h")
        t = self.texts(cv)
        self.assertIn("07", t)
        self.assertTrue(any(x.startswith("14:30 Meet") for x in t))

    def test_week_starts_on_the_chosen_day_and_list_does_not_change(self):
        cal = self.cp.cal
        self.cp.cfg["calendar"]["week_start"] = "sunday"
        cal.s["view"] = "week"
        cal.anchor = date(2026, 11, 18)                                            # a Wednesday
        d0, d1, days = cal._range()
        self.assertEqual((d0, d1), (date(2026, 11, 15), date(2026, 11, 22)))
        self.assertEqual(days[0].weekday(), 6)
        self.cp.cfg["calendar"]["week_start"] = "monday"
        self.assertEqual(cal._range()[0], date(2026, 11, 16))
        cal.s["view"] = "day"
        self.assertEqual(cal._range()[2], [date(2026, 11, 18)])                    # Day never depends on it

    def test_week_header_order_and_fixed_empty_width(self):
        cal = self.cp.cal
        cv = self.draw("week", [], week_start="sunday")
        order = [t for t in self.texts(cv) if t in mpanels.ui.CAL_DAYS_SHORT]
        self.assertEqual(order, ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"])
        cv = self.draw("week", [], week_start="monday")
        order = [t for t in self.texts(cv) if t in mpanels.ui.CAL_DAYS_SHORT]
        self.assertEqual(order[0], "Mon")
        # the empty-column width does not depend on the week start
        f = cal._fonts()
        w1 = cal._empty_col_w(f)
        cal.s["week_start"] = "sunday"
        self.assertEqual(cal._empty_col_w(f), w1)

    def test_settings_dropdowns_apply_and_dirty(self):
        self.app.open_settings("Cal")
        pump(self.app)
        S = self.app.settings_win
        s = self.cp.cfg["calendar"]
        self.assertEqual((S.v_cal_tf.get(), S.v_cal_ws.get()), ("24-hour", "Monday"))
        self.assertFalse(S.dirty())
        S.v_cal_tf.set("12-hour")
        S.v_cal_ws.set("Sunday")
        self.assertTrue(S.dirty())
        self.assertEqual((s["time_format"], s["week_start"]), ("24h", "monday"))   # nothing before Apply
        self.assertTrue(S.apply())
        s = self.cp.cfg["calendar"]
        self.assertEqual((s["time_format"], s["week_start"]), ("12h", "sunday"))
        self.assertFalse(S.dirty())
        self.assertEqual((S.v_cal_tf.get(), S.v_cal_ws.get()), ("12-hour", "Sunday"))


if __name__ == "__main__":
    unittest.main()
