"""v1.1 step 7c: multiple monitors. HOME place (what the user chose, the only thing saved) vs SHOWN place (what the
monitors that exist now allow). All screens here are MADE UP (fakedisplays), the real windows are really moved and
read back (winfo_x / winfo_y), and the config file is read from disk."""
import json
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
sys.path.insert(0, os.path.join(ROOT, "tests"))

import displays  # noqa: E402
import fileops  # noqa: E402
import mpanels  # noqa: E402
import stack  # noqa: E402
import winutil  # noqa: E402
from fakedisplays import (LEFT, MIDDLE, MISALIGNED, ONE, RIGHT, THREE, TWO_LEFT, FakeClock,  # noqa: E402
                          FakeDisplays, M)

GAP = 2
_counter = [0]


def pump(app, n=10):
    for _ in range(n):
        app.root.update()


def ev(x, y, ex=5):
    return types.SimpleNamespace(x_root=x, y_root=y, x=ex, y=5)


# --------------------------------------------------------------------------- pure geometry (displays.py)
class TestPure(unittest.TestCase):
    def test_present_monitor_shows_the_home(self):
        self.assertEqual(displays.place(THREE, 2500, 300, 300, 30, RIGHT.rect), (2500, 300))
        self.assertEqual(displays.place(THREE, -1500, 100, 300, 30, LEFT.rect), (-1500, 100))

    def test_missing_monitor_keeps_the_place_relative_to_it_on_the_primary(self):
        # the right monitor is gone: (2500, 300) was 580 px from its left edge -> 580 px from the primary's left edge
        self.assertEqual(displays.place(ONE, 2500, 300, 300, 30, RIGHT.rect), (580, 300))
        self.assertEqual(displays.place(ONE, -1500, 100, 300, 30, LEFT.rect), (420, 100))
        # two units from the SAME missing monitor keep their layout relative to each other
        a = displays.place(ONE, 2500, 300, 300, 30, RIGHT.rect)
        b = displays.place(ONE, 2600, 450, 300, 30, RIGHT.rect)
        self.assertEqual((b[0] - a[0], b[1] - a[1]), (100, 150))

    def test_missing_monitor_without_a_remembered_monitor_goes_to_the_nearest_edge(self):
        x, y = displays.place(ONE, 2500, 300, 300, 30, None)
        self.assertTrue(displays.reachable(ONE, x, y, 300, 30))

    def test_the_result_never_depends_on_history(self):
        """Pure function: gone and back = the same answer as never gone."""
        before = displays.place(THREE, 2500, 300, 300, 30, RIGHT.rect)
        displays.place(ONE, 2500, 300, 300, 30, RIGHT.rect)
        self.assertEqual(displays.place(THREE, 2500, 300, 300, 30, RIGHT.rect), before)

    def test_clamp_uses_the_work_area_not_the_whole_monitor(self):
        x, y = displays.clamp_head(THREE, 100, 5000, 300, 30)
        self.assertEqual(y, 1032 - 30)                                   # the head stays above the taskbar
        self.assertEqual(displays.clamp_head(THREE, 100, -50, 300, 30)[1], 0)

    def test_clamp_keeps_80_px_on_the_monitor_the_head_is_on(self):
        self.assertEqual(displays.clamp_head(ONE, 5000, 100, 300, 30)[0], 1920 - 80)
        self.assertEqual(displays.clamp_head(ONE, -5000, 100, 300, 30)[0], -300 + 80)
        # a head that sits mostly on the right monitor is clamped to THAT monitor, not to the whole virtual box
        self.assertEqual(displays.clamp_head(THREE, 9000, 100, 300, 30)[0], 3840 - 80)

    def test_reachable_head_is_never_moved(self):
        for x in range(-2300, 4000, 97):
            for y in range(-40, 1100, 53):
                if displays.reachable(THREE, x, y, 300, 30):
                    self.assertEqual(displays.clamp_head(THREE, x, y, 300, 30), (x, y))

    def test_clamp_result_is_always_reachable_also_with_dead_areas(self):
        for layout in (ONE, TWO_LEFT, THREE, MISALIGNED):
            for x in range(-3000, 5000, 131):
                for y in range(-600, 1500, 71):
                    for w in (60, 300, 700):
                        cx, cy = displays.clamp_head(layout, x, y, w, 30)
                        self.assertTrue(displays.reachable(layout, cx, cy, w, 30), (layout, x, y, w, cx, cy))

    def test_dead_area_is_not_reachable(self):
        # MISALIGNED: the second monitor starts at y=400; (2000, 100) is above it, where there is no monitor
        self.assertFalse(displays.reachable(MISALIGNED, 2200, 100, 300, 30))
        self.assertTrue(displays.reachable(MISALIGNED, 2200, 500, 300, 30))
        x, y = displays.clamp_head(MISALIGNED, 2200, 100, 300, 30)
        self.assertTrue(displays.reachable(MISALIGNED, x, y, 300, 30))
        self.assertGreaterEqual(y, 400)                                  # pulled onto the monitor, not left in the gap

    def test_place_into_a_dead_area_ends_on_a_monitor(self):
        x, y = displays.place(MISALIGNED, 2200, 100, 300, 30, M((1920, 400, 3200, 1120)).rect)
        self.assertTrue(displays.reachable(MISALIGNED, x, y, 300, 30))

    def test_monitor_for_picks_the_one_with_most_overlap_and_the_nearest_when_none(self):
        self.assertEqual(displays.monitor_for(THREE, -100, 10, 300, 30).rect, (0, 0, 1920, 1080))     # 200 px vs 100
        self.assertEqual(displays.monitor_for(THREE, -250, 10, 300, 30).rect, (-1920, 0, 0, 1080))
        self.assertEqual(displays.monitor_for(ONE, 9000, 10, 300, 30).rect, (0, 0, 1920, 1080))

    def test_signature_changes_with_monitors_and_work_area(self):
        s3 = displays.signature(THREE)
        self.assertNotEqual(s3, displays.signature(ONE))
        taskbar_moved = [M((0, 0, 1920, 1080), (0, 0, 1920, 1000), True), LEFT, RIGHT]
        self.assertNotEqual(s3, displays.signature(taskbar_moved))
        self.assertEqual(s3, displays.signature(list(reversed(THREE))))

    def test_real_snapshot_is_sane(self):
        mons = displays.snapshot()
        self.assertGreaterEqual(len(mons), 1)
        self.assertEqual(sum(1 for m in mons if m.primary), 1)
        for m in mons:
            l, t, r, b = m.rect
            self.assertTrue(r > l and b > t)
            wl, wt, wr, wb = m.work
            self.assertTrue(l <= wl < wr <= r and t <= wt < wb <= b)

    def test_displays_probe_failure_is_not_monitors_gone(self):
        def broken():
            raise OSError("no")
        d = displays.Displays(lambda: THREE)
        self.assertEqual(len(d.monitors()), 3)
        d._source = broken
        self.assertIsNone(d.probe())
        self.assertEqual(len(d.monitors()), 3)                           # the committed layout is untouched

    def test_choose_drop_skips_a_side_spot_that_is_off_the_screen(self):
        target = ("T", 1820, 100, 100, 200)                              # flush against the right edge of a 1920 screen
        dragged = ("D", 1930, 110, 100, 200)
        ok = lambda x, y, w: displays.reachable(ONE, x, y, w, 30)        # noqa: E731
        self.assertEqual(stack.choose_drop(dragged, [], [target], 24, GAP)[0], "side")      # without the check: snaps
        self.assertIsNone(stack.choose_drop(dragged, [], [target], 24, GAP, None, ok))      # with it: the spot is no candidate
        ok3 = lambda x, y, w: displays.reachable(THREE, x, y, w, 30)     # noqa: E731
        self.assertEqual(stack.choose_drop(dragged, [], [target], 24, GAP, None, ok3)[0], "side")   # a monitor there


# --------------------------------------------------------------------------- the real App on made-up screens
class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mpanels_t110s7c_")
        self.desk, self.pub, self.data = (os.path.join(self.tmp, n) for n in ("Desktop", "Public", "veri"))
        os.makedirs(self.desk)
        os.makedirs(self.pub)
        for p in (mock.patch("calendar_panel.model.CalendarModel.refresh", lambda *a, **k: None),
                  mock.patch.object(winutil, "lbutton_down", return_value=True)):
            p.start()
            self.addCleanup(p.stop)
        self.apps = []
        self.addCleanup(self.close_all)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def close_all(self):
        for a in self.apps:
            a.quit()

    def open(self, layout=THREE):
        _counter[0] += 1
        self.disp, self.clock = FakeDisplays(layout), FakeClock()
        app = mpanels.App(fileops.Ctx(self.desk, self.pub), self.data, test_mode=True, use_tray=False,
                          instance_name="t7c_%d_%d" % (os.getpid(), _counter[0]),
                          displays_provider=self.disp, clock=self.clock)
        self.apps.append(app)
        self.app = app
        pump(app)
        return app

    def reopen(self, layout):
        self.app.quit()
        return self.open(layout)

    def cfg_file(self):
        with open(os.path.join(self.data, "config.json"), encoding="utf-8") as f:
            return json.load(f)

    def homes_in_file(self, names):
        d = self.cfg_file()["panels"]
        return {n: (d[n]["x"], d[n]["y"]) for n in names}

    def win(self, p):
        pump(self.app, 3)
        return p.top.winfo_x(), p.top.winfo_y()

    def put(self, name, x, y, w=300, h=200):
        p = self.app.new_panel(name)
        p.cfg.update(x=x, y=y, w=w, h=h, collapsed=False)
        p.expanded = True
        p.apply_size(w, h)
        p._move_to(x, y)
        self.app.set_home(p)
        return p

    def scene(self):
        """A free panel on the right monitor, a two-panel stack on the left monitor, a free panel on the primary."""
        app = self.open(THREE)
        self.scene_on(app)
        return [app.panels[n] for n in ("A", "S1", "S2", "F")]

    def scene_on(self, app):
        self.app = app
        self.put("A", 2500, 300)
        self.put("S1", -1500, 100)
        self.put("S2", -1500, 400)
        self.put("F", 300, 200)
        app.cfg["stacks"] = [["S1", "S2"]]
        app.ensure_homes()                                   # a member has no home of its own (derived from its top)
        app.relayout_all()
        app.save()
        pump(app)

    HOMES = {"A": (2500, 300), "S1": (-1500, 100), "S2": (-1500, 302), "F": (300, 200)}

    def drag(self, p, nx, ny, steps=3):
        """Header drag with the real handlers: press on the title, move, release; the panel ends with its top-left at nx, ny."""
        x0, y0 = p.cfg["x"] + 40, p.cfg["y"] + 8
        dx, dy = nx - p.cfg["x"], ny - p.cfg["y"]
        p._head_press(ev(x0, y0, 40))
        for i in range(1, steps + 1):
            p._head_motion(ev(x0 + dx * i // steps, y0 + dy * i // steps, 40))
            pump(self.app, 2)
        p._head_release(ev(x0 + dx, y0 + dy, 40))
        pump(self.app)

    def settle(self, seconds=3.5):
        """Time passes (fake clock) and the app looks at the screens twice (2 s apart in real life)."""
        first = self.app._display_check()                    # a look now (a change is noticed at this moment) ...
        self.clock.advance(seconds)
        return self.app._display_check() or first            # ... and one after `seconds`; True when it re-placed

    def assert_homes(self, expected=None):
        self.assertEqual(self.homes_in_file(list(self.HOMES)), expected or self.HOMES)


class TestCritical(Base):
    def test_monitor_missing_at_open_save_then_monitor_back(self):
        """THE critical case: open without a monitor -> save -> the monitor is back: panels are at home, and the home
        in config.json was never different."""
        self.scene()
        self.assert_homes()
        # --- reopen with ONLY the primary monitor
        app = self.reopen(ONE)
        a, s1, s2, f = (app.panels[n] for n in ("A", "S1", "S2", "F"))
        self.assertEqual(self.win(a), (580, 300))                        # shifted onto the primary, relative to its monitor
        self.assertEqual(self.win(s1), (420, 100))                       # the stack moves AS ONE
        self.assertEqual(self.win(s2), (420, 100 + s1.cur_h + GAP))
        self.assertEqual(self.win(f), (300, 200))                        # was already on the primary
        self.assertEqual(a.cfg["_home"], (2500, 300))
        # --- everything that saves, while the monitor is missing
        app.save()
        s1.toggle()
        pump(app, 30)
        s1.toggle()
        pump(app, 30)
        app.save()
        self.assert_homes()                                              # the file still holds the HOMES
        for n in ("A", "S1", "S2", "F"):
            self.assertNotIn("_home", self.cfg_file()["panels"][n])
        # --- quit (saves again) and reopen with all three monitors
        app = self.reopen(THREE)
        a, s1, s2, f = (app.panels[n] for n in ("A", "S1", "S2", "F"))
        self.assertEqual(self.win(a), (2500, 300))
        self.assertEqual(self.win(s1), (-1500, 100))
        self.assertEqual(self.win(s2), (-1500, 100 + s1.cur_h + GAP))
        self.assertEqual(self.win(f), (300, 200))
        app.save()
        self.assert_homes()

    def test_monitor_goes_and_comes_back_while_running(self):
        app = self.open(THREE)
        self.scene_on(app)
        a, s1, s2, f = (app.panels[n] for n in ("A", "S1", "S2", "F"))
        self.disp.set(ONE)
        self.assertFalse(self.settle(1.0))                               # not stable yet: nothing moves
        self.assertEqual(self.win(a), (2500, 300))
        self.assertTrue(self.settle(3.0))                                # stable for 3+ s: re-placed
        self.assertEqual(self.win(a), (580, 300))
        self.assertEqual(self.win(s1), (420, 100))
        self.assertEqual(self.win(s2), (420, 100 + s1.cur_h + GAP))
        app.save()
        self.assert_homes()
        self.disp.set(THREE)
        self.assertFalse(self.settle(1.0))
        self.assertEqual(self.win(a), (580, 300))
        self.assertTrue(self.settle(3.0))
        self.assertEqual(self.win(a), (2500, 300))
        self.assertEqual(self.win(s1), (-1500, 100))
        self.assertEqual(self.win(s2), (-1500, 100 + s1.cur_h + GAP))
        app.save()
        self.assert_homes()

    def test_old_config_without_home_or_monitor_keys_loads_and_keeps_its_positions(self):
        """Migration: an old config (no `mon`, no home) loads untouched; home = its x/y; the bug scenario (monitor missing at
        the first start with the new version) does not destroy anything."""
        self.scene()
        self.app.quit()
        old = self.cfg_file()
        for c in old["panels"].values():
            c.pop("mon", None)
        with open(os.path.join(self.data, "config.json"), "w", encoding="utf-8") as f:
            json.dump(old, f, ensure_ascii=False, indent=2)
        before = json.loads(json.dumps(old))
        app = self.open(ONE)                                             # worst case: the monitor is missing right away
        self.assertEqual(self.win(app.panels["F"]), (300, 200))
        app.save()
        now = self.cfg_file()
        self.assertEqual(now["stacks"], before["stacks"])
        self.assertEqual(now["general"], before["general"])
        for n, c in before["panels"].items():
            for k, v in c.items():
                self.assertEqual(now["panels"][n][k], v, (n, k))         # nothing that was there changed
        self.assert_homes()
        # the monitors are back: panels return to their saved places
        app = self.reopen(THREE)
        self.assertEqual(self.win(app.panels["A"]), (2500, 300))
        self.assertEqual(self.win(app.panels["S1"]), (-1500, 100))

    def test_old_config_loads_on_all_monitors_with_only_the_new_mon_key_added(self):
        self.scene()
        self.app.quit()
        old = self.cfg_file()
        for c in old["panels"].values():
            c.pop("mon", None)
        with open(os.path.join(self.data, "config.json"), "w", encoding="utf-8") as f:
            json.dump(old, f)
        app = self.open(THREE)
        app.save()
        now = self.cfg_file()
        for n, c in old["panels"].items():
            extra = set(now["panels"][n]) - set(c)
            self.assertLessEqual(extra, {"mon"}, (n, extra))
            for k, v in c.items():
                self.assertEqual(now["panels"][n][k], v, (n, k))
        self.assertEqual(now["panels"]["A"]["mon"], list(RIGHT.rect))


class TestDisplayChanges(Base):
    def test_a_flap_shorter_than_the_settle_time_changes_nothing(self):
        """DisplayPort monitors drop out and come back when they sleep."""
        app = self.open(THREE)
        self.scene_on(app)
        a = app.panels["A"]
        with mock.patch.object(app, "relayout_displays") as relay:
            self.disp.set(ONE)
            self.settle(1.9)
            self.disp.set(THREE)                                         # back before 3 s were over
            self.settle(1.9)
            self.settle(10)
            relay.assert_not_called()
        self.assertEqual(self.win(a), (2500, 300))
        self.assertEqual(len(app.monitors()), 3)

    def test_the_new_layout_is_not_used_before_it_settled(self):
        """Clamp / snapping / placement keep seeing the COMMITTED layout until the re-placement."""
        app = self.open(THREE)
        self.scene_on(app)
        a = app.panels["A"]
        self.disp.set(ONE)
        self.settle(1.0)
        self.assertEqual(len(app.monitors()), 3)
        self.drag(a, 3000, 300)                                          # a drop on the right monitor in that window
        self.assertEqual(a.cfg["_home"], (3000, 300))                    # judged by the old (committed) layout: allowed
        self.assertEqual(self.win(a), (3000, 300))

    def test_a_change_during_a_drag_waits_for_the_drop(self):
        app = self.open(THREE)
        self.scene_on(app)
        a, f = app.panels["A"], app.panels["F"]
        x0, y0 = f.cfg["x"] + 40, f.cfg["y"] + 8
        f._head_press(ev(x0, y0, 40))
        f._head_motion(ev(x0 + 30, y0 + 20, 40))
        self.disp.set(ONE)
        self.assertFalse(self.settle(10))                                # a drag is going on: not now
        self.assertEqual(self.win(a), (2500, 300))
        f._head_release(ev(x0 + 30, y0 + 20, 40))
        pump(app)
        self.assertTrue(self.settle(0.1))                                # the next look after the drop
        self.assertEqual(self.win(a), (580, 300))
        self.assertEqual(self.homes_in_file(["F"]), {"F": (330, 220)})   # the dragged panel's drop became its home

    def test_the_system_unable_to_say_is_not_monitors_gone(self):
        app = self.open(THREE)
        self.scene_on(app)
        self.disp.fail = True
        for _ in range(5):
            self.assertFalse(self.settle(10))
        self.assertEqual(self.win(app.panels["A"]), (2500, 300))
        self.disp.fail = False
        self.assertFalse(self.settle(10))                                # same layout as before: nothing to do

    def test_work_area_change_replaces_panels_above_the_taskbar(self):
        app = self.open(THREE)
        self.scene_on(app)
        f = self.put("G", 300, 1000)                                     # head at 1000..1030, just above the 1032 taskbar
        self.assertEqual(self.win(f), (300, 1000))
        self.disp.set([M((0, 0, 1920, 1080), (0, 0, 1920, 900), True), LEFT, RIGHT])     # taskbar got taller
        self.assertTrue(self.settle(3.5))
        self.assertLessEqual(self.win(f)[1], 900 - f.head_h)
        self.assertEqual(f.cfg["_home"], (300, 1000))                    # the home did not change
        self.disp.set(THREE)
        self.assertTrue(self.settle(3.5))
        self.assertEqual(self.win(f), (300, 1000))


class TestUserActsWhileAMonitorIsMissing(Base):
    def start_missing(self):
        app = self.open(THREE)
        self.scene_on(app)
        self.disp.set(ONE)
        self.assertTrue(self.settle(3.5))
        return [app.panels[n] for n in ("A", "S1", "S2", "F")]

    def test_a_dragged_panel_keeps_where_it_was_dropped_as_its_new_home(self):
        a, s1, s2, f = self.start_missing()
        self.assertEqual(self.win(a), (580, 300))
        self.drag(a, 1000, 350)                                          # away from every other panel: no snap
        self.assertEqual(self.win(a), (1000, 350))
        self.assertEqual(self.homes_in_file(["A"]), {"A": (1000, 350)})
        self.assertEqual(self.cfg_file()["panels"]["A"]["mon"], list(MIDDLE.rect))
        self.disp.set(THREE)
        self.assertTrue(self.settle(3.5))
        self.assertEqual(self.win(a), (1000, 350))                       # does NOT go back to the right monitor
        self.assertEqual(self.win(s1), (-1500, 100))                     # the ones nobody touched go home
        self.assertEqual(self.win(s2), (-1500, 100 + s1.cur_h + GAP))
        self.assertEqual(self.homes_in_file(["A", "S1"]), {"A": (1000, 350), "S1": (-1500, 100)})

    def test_dragging_the_shifted_stack_top_makes_the_whole_stack_move_home(self):
        a, s1, s2, f = self.start_missing()
        self.drag(s1, 800, 120)
        self.assertEqual(self.homes_in_file(["S1", "S2"]), {"S1": (800, 120), "S2": (800, 120 + s1.cur_h + GAP)})
        self.disp.set(THREE)
        self.assertTrue(self.settle(3.5))
        self.assertEqual(self.win(s1), (800, 120))
        self.assertEqual(self.win(s2), (800, 120 + s1.cur_h + GAP))
        self.assertEqual(self.win(a), (2500, 300))

    def test_a_panel_snapped_under_a_shifted_stack_goes_home_with_the_stack(self):
        a, s1, s2, f = self.start_missing()
        d = self.app.new_panel("D")
        d.cfg.update(x=900, y=600, w=300, h=200, collapsed=False)
        d.expanded = True
        d.apply_size(300, 200)
        d._move_to(900, 600)
        self.app.set_home(d)
        pump(self.app)
        under = s2.cfg["y"] + s2.cur_h + GAP
        self.drag(d, s2.cfg["x"] + 6, under + 5)                         # near the spot under the stack's bottom
        self.assertEqual(self.app.cfg["stacks"], [["S1", "S2", "D"]])
        top_y = 100
        d_y = top_y + s1.cur_h + GAP + s2.cur_h + GAP
        self.assertEqual(self.win(d), (420, d_y))                        # shifted along with the stack
        self.assertEqual(self.homes_in_file(["S1", "D"]), {"S1": (-1500, 100), "D": (-1500, d_y)})   # home: left monitor
        self.assertNotIn("_home", self.cfg_file()["panels"]["D"])
        self.disp.set(THREE)
        self.assertTrue(self.settle(3.5))
        self.assertEqual(self.win(d), (-1500, d_y))                      # the new member travelled with the stack
        self.assertEqual(self.win(s1), (-1500, 100))
        app = self.reopen(THREE)
        self.assertEqual(self.win(app.panels["D"]), (-1500, d_y))

    def test_the_top_of_a_shifted_stack_removed_gives_the_next_one_its_home_not_the_shifted_place(self):
        a, s1, s2, f = self.start_missing()
        self.app.remove_panel(s1, confirm=False)
        pump(self.app)
        self.assertEqual(self.homes_in_file(["S2"]), {"S2": (-1500, 302)})     # S2's old derived home, not (420, ...)
        self.disp.set(THREE)
        self.assertTrue(self.settle(3.5))
        self.assertEqual(self.win(self.app.panels["S2"]), (-1500, 302))

    def test_renaming_a_shifted_panel_keeps_its_home(self):
        a, s1, s2, f = self.start_missing()
        r = self.app.do_rename(a, "A2")
        self.assertTrue(r.ok)
        pump(self.app)
        a2 = self.app.panels["A2"]
        self.assertEqual(self.win(a2), (580, 300))
        self.assertEqual(self.homes_in_file(["A2"]), {"A2": (2500, 300)})
        self.disp.set(THREE)
        self.assertTrue(self.settle(3.5))
        self.assertEqual(self.win(a2), (2500, 300))

    def test_locked_panels_are_still_replaced_and_homes_stay(self):
        a, s1, s2, f = self.start_missing()
        self.app.set_lock(True)
        self.disp.set(THREE)
        self.assertTrue(self.settle(3.5))
        self.assertEqual(self.win(a), (2500, 300))


class TestClampAndSnapOnScreens(Base):
    def test_drop_far_outside_is_clamped_to_the_monitor_work_area_and_becomes_the_home(self):
        app = self.open(THREE)
        self.scene_on(app)
        f = app.panels["F"]
        self.drag(f, 300, 1070)                                         # the head would sit under the taskbar
        self.assertEqual(self.win(f), (300, 1032 - f.head_h))
        self.assertEqual(f.cfg["_home"], (300, 1032 - f.head_h))

    def test_dead_area_drop_ends_on_a_monitor(self):
        app = self.open(MISALIGNED)
        f = self.put("F", 300, 200)
        self.drag(f, 2300, 100)                                          # above the small shifted monitor: nothing there
        x, y = self.win(f)
        self.assertTrue(displays.reachable(MISALIGNED, x, y, f.cfg["w"], f.head_h), (x, y))
        self.assertGreaterEqual(y, 400)

    def test_side_snap_past_the_screen_edge_is_in_neither_the_preview_nor_the_drop(self):
        app = self.open(ONE)
        t = self.put("T", 1820, 100, w=100)                              # flush against the right edge of the only monitor
        d = self.put("D", 900, 100, w=100)
        x0, y0 = d.cfg["x"] + 40, d.cfg["y"] + 8
        d._head_press(ev(x0, y0, 40))
        d._head_motion(ev(x0 + 1030, y0 + 5, 40))                        # D's left edge 1930: 8 px from the spot right of T
        pump(app, 3)
        self.assertIsNone(app._preview_shown)                            # no preview ...
        d._head_release(ev(x0 + 1030, y0 + 5, 40))
        pump(app)
        self.assertFalse(app.cfg["stacks"])
        self.assertTrue(displays.reachable(ONE, d.cfg["x"], d.cfg["y"], 100, d.head_h))   # ... and the drop was clamped
        self.assertNotEqual((d.cfg["x"], d.cfg["y"]), (1922, 100))

    def test_the_same_side_snap_works_when_a_monitor_is_there(self):
        app = self.open(THREE)
        t = self.put("T", 1820, 100, w=100)
        d = self.put("D", 900, 100, w=100)
        x0, y0 = d.cfg["x"] + 40, d.cfg["y"] + 8
        d._head_press(ev(x0, y0, 40))
        d._head_motion(ev(x0 + 1030, y0 + 5, 40))
        pump(app, 3)
        self.assertIsNotNone(app._preview_shown)
        self.assertEqual(app._preview_shown["rects"], [(1922, 100, 100, 200)])
        d._head_release(ev(x0 + 1030, y0 + 5, 40))
        pump(app)
        self.assertEqual((d.cfg["x"], d.cfg["y"]), (1922, 100))
        self.assertEqual(self.win(d), (1922, 100))

    def test_snapping_between_monitors_is_not_blocked(self):
        app = self.open(THREE)
        a = self.put("A", -300, 100)                                     # on the left monitor
        d = self.put("D", 900, 600)                                      # on the primary
        self.drag(d, -296, 100 + a.cur_h + GAP + 4)
        self.assertEqual(app.cfg["stacks"], [["A", "D"]])
        self.assertEqual(self.win(d), (-300, 100 + a.cur_h + GAP))

    def test_preview_equals_drop_for_many_positions_across_monitors(self):
        app = self.open(THREE)
        t1 = self.put("T1", -250, 100, w=200)                            # next to the left/primary border
        t2 = self.put("T2", 1900, 300, w=200)                            # straddles primary/right
        d = self.put("D", 900, 700, w=180, h=120)
        bad = []
        for x in range(-700, 2400, 173):
            for y in range(40, 700, 97):
                app.cfg["stacks"] = []
                self.put_back(d, 900, 700)
                x0, y0 = d.cfg["x"] + 40, d.cfg["y"] + 8
                d._head_press(ev(x0, y0, 40))
                d._head_motion(ev(x0 + x - 900, y0 + y - 700, 40))
                pump(app, 2)
                shown = app._preview_shown
                preview = list(shown["rects"]) if shown else None
                d._head_release(ev(x0 + x - 900, y0 + y - 700, 40))
                pump(app, 2)
                rect = (d.cfg["x"], d.cfg["y"], d.cur_w, d.cur_h)
                if preview is not None and preview != [rect]:
                    bad.append((x, y, preview, rect))
                if not displays.reachable(app.monitors(), d.cfg["x"], d.cfg["y"], d.cur_w, d.head_h):
                    bad.append((x, y, "unreachable", rect))
        self.assertEqual(bad, [])

    def put_back(self, p, x, y):
        p.cfg["x"], p.cfg["y"] = x, y
        p._move_to(x, y)
        self.app.set_home(p)


if __name__ == "__main__":
    unittest.main()
