"""v1.1 step 2b: Week view column widths. A day without events shrinks to its header, the days with events share
the rest equally (an all-day event counts), with a lower bound; a Settings switch turns it off. Day/List untouched."""
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
import theme  # noqa: E402
from calendar_panel import core  # noqa: E402
from calendar_panel import settings as cal_settings  # noqa: E402

W = core.week_column_widths
HEAD = 30.0


def pump(app, n=15):
    for _ in range(n):
        app.root.update()


class TestColumnWidths(unittest.TestCase):
    def assertSum(self, ws, total):
        self.assertAlmostEqual(sum(ws), total, places=6)

    def test_no_events_all_equal(self):
        ws = W(700, [False] * 7, HEAD)
        self.assertEqual(ws, [100.0] * 7)

    def test_all_seven_busy_all_equal(self):
        ws = W(700, [True] * 7, HEAD)
        self.assertEqual(ws, [100.0] * 7)

    def test_one_busy_day_takes_the_rest(self):
        busy = [False, False, True, False, False, False, False]
        ws = W(700, busy, HEAD)
        self.assertEqual([ws[i] for i in (0, 1, 3, 4, 5, 6)], [30.0] * 6)      # header width only
        self.assertAlmostEqual(ws[2], 700 - 6 * 30)
        self.assertSum(ws, 700)

    def test_busy_days_share_equally_and_follow_the_panel_width(self):
        busy = [True, False, True, False, False, True, False]
        a, b = W(700, busy, HEAD), W(1000, busy, HEAD)
        self.assertAlmostEqual(a[0], a[2])
        self.assertAlmostEqual(a[2], a[5])
        self.assertAlmostEqual(a[0], (700 - 4 * 30) / 3)
        self.assertAlmostEqual(b[0], (1000 - 4 * 30) / 3)                      # grows with the panel
        self.assertSum(a, 700)
        self.assertSum(b, 1000)

    def test_all_empty_columns_have_the_same_fixed_width(self):
        busy = [True, False, True, False, False, False, True]
        for total in (700, 900):
            ws = W(total, busy, 44)
            self.assertEqual({ws[i] for i in (1, 3, 4, 5)}, {44.0})
            self.assertSum(ws, total)
        # the same empty width whichever days are the empty ones (the width does not move with the week)
        a = W(700, [True, False, False, False, False, False, False], 44)
        b = W(700, [False, False, False, False, False, False, True], 44)
        self.assertEqual(sorted(a), sorted(b))
        self.assertEqual(W(600, [True] + [False] * 6, 5)[1], float(theme.CAL_EMPTY_MIN_W))   # never below the minimum

    def test_shrink_off_is_equal(self):
        busy = [True] + [False] * 6
        self.assertEqual(W(700, busy, HEAD, shrink=False), [100.0] * 7)

    def test_narrow_panel_busy_minimum_first_then_empty_shrink(self):
        busy = [True, True, False, False, False, False, False]                 # share would be (300-150)/2 = 75 -> ok
        ws = W(300, busy, HEAD)
        self.assertAlmostEqual(ws[0], 75.0)
        busy = [True, True, True, False, False, False, False]                  # share (300-120)/3 = 60 < 64
        ws = W(300, busy, HEAD)
        self.assertEqual(ws[:3], [64.0] * 3)                                   # (a) busy stay at the minimum
        self.assertSum(ws, 300)
        self.assertAlmostEqual(ws[3], 30 * (300 - 192) / 120)                  # ...empty ones shrink together (27 px each)
        self.assertEqual(len(set(ws[3:])), 1)

    def test_below_both_minimums_empty_pinned_busy_share_the_rest(self):
        busy = [True, True, True, False, False, False, False]
        ws = W(200, busy, HEAD)
        # (a) would push the empty columns under 22 px: they are pinned at 22 and the busy ones take the rest
        self.assertEqual(ws[3:], [float(theme.CAL_EMPTY_MIN_W)] * 4)
        self.assertSum(ws, 200)
        self.assertAlmostEqual(ws[0], (200 - 4 * 22) / 3)
        self.assertLess(ws[0], theme.CAL_BUSY_MIN_W)

    def test_impossible_falls_back_to_equal(self):
        busy = [True] + [False] * 6
        ws = W(100, busy, HEAD)                                               # 6 * 22 = 132 > 100
        self.assertEqual(ws, [100 / 7] * 7)

    def test_sum_is_always_the_total(self):
        import itertools
        for total in (150, 200, 260, 400, 700, 1500):
            for mask in itertools.product([False, True], repeat=7):
                for shrink in (True, False):
                    ws = W(total, list(mask), HEAD, shrink)
                    self.assertEqual(len(ws), 7)
                    self.assertAlmostEqual(sum(ws), total, places=6, msg=(total, mask, shrink))
                    self.assertTrue(all(w > 0 for w in ws))

    def test_empty_input(self):
        self.assertEqual(W(500, [], []), [])


class TestSetting(unittest.TestCase):
    def test_default_on_and_sanitized(self):
        self.assertIs(cal_settings.sanitize(None)["shrink_empty"], True)
        self.assertIs(cal_settings.sanitize({})["shrink_empty"], True)             # an old config without the key
        self.assertIs(cal_settings.sanitize({"shrink_empty": False})["shrink_empty"], False)
        self.assertIs(cal_settings.sanitize({"shrink_empty": 0})["shrink_empty"], False)


@unittest.skipUnless(calendar_panel.AVAILABLE, "calendar libraries not installed")
class TestWeekDrawAndSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mpanels_t110c_")
        self.desk, self.pub, self.data = (os.path.join(self.tmp, n) for n in ("Desktop", "Public", "veri"))
        os.makedirs(self.desk)
        os.makedirs(self.pub)
        p = mock.patch("calendar_panel.model.CalendarModel.refresh", lambda *a, **k: None)
        p.start()
        self.addCleanup(p.stop)
        self.app = mpanels.App(fileops.Ctx(self.desk, self.pub), self.data, test_mode=True, use_tray=False,
                               instance_name="t110c_%d" % os.getpid())
        self.addCleanup(self.app.quit)
        self.cp = self.app.new_panel("Cal", "calendar")
        self.cp.cfg["calendar"]["view"] = "week"
        pump(self.app)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ev(self, day, hour, title, all_day=False, dur=1):
        st = datetime(day.year, day.month, day.day, hour)
        en = st + timedelta(hours=dur)
        return {"day": day, "all_day": all_day, "first": True, "title": title, "start": st, "end": en,
                "seg_start": st, "seg_end": en, "location": "", "color": None, "cal": "c"}

    def week_days(self):
        d = date.today()
        mon = d - timedelta(days=d.weekday())
        return [mon + timedelta(days=i) for i in range(7)]

    def draw(self, events, w=700, **settings):
        cal = self.cp.cal
        cal.s.update(settings)
        cal.anchor = date.today()
        cv = self.cp.cal_cv
        cal.model.events_between = lambda d0, d1: [dict(e) for e in events]
        cv.delete("all")
        cal.tips = []
        cal._draw_grid(cv, w, 7)
        xs = sorted({round(cv.coords(i)[0], 3) for i in cv.find_all()
                     if cv.type(i) == "line" and len(cv.coords(i)) == 4 and cv.coords(i)[0] == cv.coords(i)[2]})
        return [b - a for a, b in zip(xs, xs[1:])], cv

    def test_week_draws_shrunken_columns(self):
        days = self.week_days()
        events = [self.ev(days[2], 9, "Meeting"), self.ev(days[2], 9, "Overlap"),      # overlapping lanes
                  self.ev(days[4], 0, "Holiday", all_day=True)]                       # all-day = busy
        cws, cv = self.draw(events)
        self.assertEqual(len(cws), 7)
        self.assertAlmostEqual(sum(cws), 700 - 40 - 8, delta=0.01)
        busy = {2, 4}
        for i in range(7):
            if i not in busy:
                self.assertLess(cws[i], 60)
        self.assertAlmostEqual(cws[2], cws[4], delta=0.01)
        empties = [cws[i] for i in range(7) if i not in busy]
        self.assertLess(max(empties) - min(empties), 0.01)                            # all empty columns: one fixed width
        f = self.cp.cal._fonts()
        wd = max(f["tiny"].measure(n) for n in mpanels.ui.CAL_DAYS_SHORT)
        wn = max(f["day"].measure(str(n)) for n in range(1, 32))
        self.assertAlmostEqual(empties[0], max(wd, wn) + theme.CAL_HEAD_PAD, delta=0.01)
        self.assertGreater(cws[2], 150)
        # the all-day box lies inside its own column, the two lanes split column 2 in half
        rects = [cv.coords(i) for i in cv.find_all() if cv.type(i) == "rectangle"]
        self.assertTrue(rects)
        self.assertTrue(all(r[0] < r[2] for r in rects))

    def test_no_events_is_equal_and_off_is_equal(self):
        cws, _ = self.draw([])
        self.assertTrue(all(abs(c - cws[0]) < 0.01 for c in cws))
        days = self.week_days()
        cws, _ = self.draw([self.ev(days[1], 10, "x")], shrink_empty=False)
        self.assertTrue(all(abs(c - cws[0]) < 0.01 for c in cws))

    def test_narrow_panel_and_other_views_do_not_break(self):
        days = self.week_days()
        events = [self.ev(days[i], 9, "e%d" % i) for i in range(3)]
        cws, _ = self.draw(events, w=240)
        self.assertAlmostEqual(sum(cws), 240 - 48, delta=0.01)
        cal = self.cp.cal
        cal.s["view"] = "day"
        cv = self.cp.cal_cv
        cv.delete("all")
        cal._draw_grid(cv, 700, 1)                                                    # Day: one equal column
        xs = sorted({round(cv.coords(i)[0], 3) for i in cv.find_all()
                     if cv.type(i) == "line" and len(cv.coords(i)) == 4 and cv.coords(i)[0] == cv.coords(i)[2]})
        self.assertEqual(len(xs), 2)
        self.assertAlmostEqual(xs[1] - xs[0], 700 - 48, delta=0.01)

    def test_settings_checkbox_apply_and_dirty(self):
        self.app.open_settings("Cal")
        pump(self.app)
        S = self.app.settings_win
        self.assertTrue(S.v_cal_shrink.get())
        self.assertFalse(S.dirty())
        S.v_cal_shrink.set(False)
        self.assertTrue(S.dirty())
        self.assertTrue(self.cp.cfg["calendar"]["shrink_empty"])                       # nothing changes without Apply
        self.assertTrue(S.apply())
        self.assertIs(self.cp.cfg["calendar"]["shrink_empty"], False)
        self.assertFalse(S.dirty())
        S.v_cal_shrink.set(True)
        self.assertTrue(S.apply())
        self.assertIs(self.cp.cfg["calendar"]["shrink_empty"], True)


if __name__ == "__main__":
    unittest.main()
