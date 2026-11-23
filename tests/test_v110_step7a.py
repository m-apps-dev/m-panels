"""v1.1 step 7a: snapping under the bottom of a stack, stacks (push on open/close, drag, shared width, persistence).
Side snapping (7b) and multi-monitor handling (7c) are NOT part of this step."""
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

import calendar_panel  # noqa: E402
import displays  # noqa: E402
import fileops  # noqa: E402
import mpanels  # noqa: E402
import stack  # noqa: E402
import theme  # noqa: E402
import winutil  # noqa: E402
from fakedisplays import THREE, FakeClock, FakeDisplays  # noqa: E402

GAP, DIST = 2, 24


def pump(app, sec=0.0, n=10):
    for _ in range(n):
        app.root.update()
    end = time.time() + sec
    while time.time() < end:
        app.root.update()
        time.sleep(0.005)


def ev(x, y, ex=5):
    return types.SimpleNamespace(x_root=x, y_root=y, x=ex, y=5)


class TestPure(unittest.TestCase):
    def test_general_defaults_and_garbage(self):
        g = stack.sanitize_general({})
        self.assertEqual((g["snap_distance"], g["stack_gap"], g["snap_enabled"]), (24, 2, True))
        for junk in ("x", None, 3.5, True, [], -1, 9999):
            g = stack.sanitize_general({"snap_distance": junk, "stack_gap": junk, "snap_enabled": junk})
            self.assertEqual((g["snap_distance"], g["stack_gap"], g["snap_enabled"]), (24, 2, True), junk)
        for v, want in ((3, 24), (4, 4), (64, 64), (65, 24)):                                  # snap distance 4..64
            self.assertEqual(stack.sanitize_general({"snap_distance": v})["snap_distance"], want, v)
        for v, want in ((-1, 2), (0, 0), (24, 24), (25, 2)):                                   # stack gap 0..24
            self.assertEqual(stack.sanitize_general({"stack_gap": v})["stack_gap"], want, v)
        g = stack.sanitize_general({"snap_distance": 30, "stack_gap": 0, "snap_enabled": False})
        self.assertEqual((g["snap_distance"], g["stack_gap"], g["snap_enabled"]), (30, 0, False))
        self.assertEqual(stack.sanitize_general({"stack_gap": 12.0})["stack_gap"], 12)

    def test_stacks_sanitize(self):
        known = {"A", "B", "C", "D"}
        self.assertEqual(stack.sanitize_stacks(None, known), [])
        self.assertEqual(stack.sanitize_stacks("x", known), [])
        self.assertEqual(stack.sanitize_stacks([["A", "B"], "junk", [1, 2], None], known), [["A", "B"]])
        self.assertEqual(stack.sanitize_stacks([["A", "ghost", "B"]], known), [["A", "B"]])          # unknown id dropped
        self.assertEqual(stack.sanitize_stacks([["A", "A", "B"]], known), [["A", "B"]])              # repeat dropped
        self.assertEqual(stack.sanitize_stacks([["A", "ghost"], ["B", "C"]], known), [["B", "C"]])   # too short: removed
        self.assertEqual(stack.sanitize_stacks([["A", "B"], ["B", "C", "D"]], known), [["A", "B"], ["C", "D"]])  # one stack per panel

    def test_remove_and_add(self):
        self.assertEqual(stack.remove([["A", "B", "C"]], "B"), [["A", "C"]])
        self.assertEqual(stack.remove([["A", "B"]], "B"), [])
        self.assertEqual(stack.add_below([["A", "B"]], "B", "C"), [["A", "B", "C"]])
        self.assertEqual(stack.add_below([], "A", "B"), [["A", "B"]])
        self.assertEqual(stack.add_below([["A", "B", "C"]], "B", "D"), [["A", "B", "C"]])           # never into the middle
        self.assertEqual(stack.positions(10, [100, 30, 50], 8), [10, 118, 156])

    def test_find_snap_threshold_and_overlap(self):
        c = [("A", 100, 100, 200, 150)]                       # bottom edge = 250, target position = 250 + gap = 252
        for dy, ok in ((252 + 23, True), (252 + 24, True), (252 + 25, False), (252 - 24, True), (252 - 25, False),
                       (250 + 26, True)):                           # measured from the bottom edge itself 26 would be too far
            self.assertEqual(stack.find_snap(("D", 100, dy, 200, 50), c, DIST, GAP), "A" if ok else None, dy)
        self.assertEqual(stack.find_snap(("D", 100, 300, 200, 50), c, DIST, 0), None)                # gap 0: target = 250
        self.assertEqual(stack.find_snap(("D", 100, 274, 200, 50), c, DIST, 0), "A")
        self.assertIsNone(stack.find_snap(("D", 300, 252, 100, 50), c, DIST, GAP))                   # touching only: no overlap
        self.assertEqual(stack.find_snap(("D", 250, 252, 100, 50), c, DIST, GAP), "A")               # overlap 50 = half of 100: enough
        self.assertIsNone(stack.find_snap(("D", 251, 252, 100, 50), c, DIST, GAP))                   # 49 px: a mere 1 px-ish overlap
        self.assertIsNone(stack.find_snap(("D", 299, 252, 100, 50), c, DIST, GAP))                   # 1 px is not enough any more
        self.assertEqual(stack.find_snap(("D", 0, 252, 100, 50), c, DIST, GAP), None)                # no overlap at all
        self.assertEqual(stack.find_snap(("D", 50, 252, 100, 50), c, DIST, GAP), "A")                # 50 px from the left: enough
        self.assertIsNone(stack.find_snap(("D", 49, 252, 100, 50), c, DIST, GAP))                    # 49 px: not enough
        # the NARROWER panel counts: a 300 px panel over a 200 px one needs 100 px, not 150
        self.assertEqual(stack.find_snap(("D", 200, 252, 300, 50), c, DIST, GAP), "A")               # shares 100 of A's 200
        self.assertIsNone(stack.find_snap(("D", 201, 252, 300, 50), c, DIST, GAP))

    def test_find_side_thresholds_both_edges(self):
        c = [("B", 100, 100, 300, 200)]                          # right edge 400, left edge 100
        right = 400 + GAP                                        # target x for D's LEFT edge
        for dx, ok in ((right + 23, True), (right + 24, True), (right + 25, False),
                       (right - 24, True), (right - 25, False)):
            got = stack.find_side(("D", dx, 130, 250, 100), c, DIST, GAP)
            self.assertEqual(got, ("B", right, 100) if ok else None, dx)
        left = 100 - GAP - 250                                   # target x for D's RIGHT edge to sit left of B
        for dx, ok in ((left + 24, True), (left - 24, True), (left + 25, False), (left - 25, False)):
            got = stack.find_side(("D", dx, 130, 250, 100), c, DIST, GAP)
            self.assertEqual(got, ("B", left, 100) if ok else None, dx)

    def test_find_side_needs_vertical_overlap(self):
        c = [("B", 100, 100, 300, 200)]                          # y 100..300
        d = lambda y: ("D", 400 + GAP, y, 250, 100)               # noqa: E731
        self.assertEqual(stack.find_side(d(250), c, DIST, GAP), ("B", 402, 100))        # shares 50 = half of the LOWER one (D, 100)
        self.assertIsNone(stack.find_side(d(251), c, DIST, GAP))                          # 49 px: not enough
        self.assertIsNone(stack.find_side(d(299), c, DIST, GAP))                          # 1 px is not an intention
        self.assertIsNone(stack.find_side(d(300), c, DIST, GAP))                          # touching only
        self.assertEqual(stack.find_side(d(50), c, DIST, GAP), ("B", 402, 100))         # shares 50 above
        self.assertIsNone(stack.find_side(d(49), c, DIST, GAP))
        # the LOWER panel counts (a bar): a 32 px bar needs 16 px of overlap, whatever the other panel's height
        bar = [("B", 100, 100, 300, 32)]
        self.assertEqual(stack.find_side(("D", 402, 116, 250, 200), bar, DIST, GAP), ("B", 402, 100))   # shares 16 of 32
        self.assertIsNone(stack.find_side(("D", 402, 117, 250, 200), bar, DIST, GAP))                      # shares 15

    def test_find_side_nearest_and_tie(self):
        c = [("B", 100, 100, 300, 200), ("C", 700, 100, 300, 200)]
        # D between them: left of C (target x = 700 - 2 - 250 = 448) and right of B (402)
        self.assertEqual(stack.find_side(("D", 430, 150, 250, 100), c, DIST, GAP)[0], "C")   # |430-448| = 18 < |430-402| = 28 (too far anyway)
        self.assertEqual(stack.find_side(("D", 410, 150, 250, 100), c, DIST, GAP)[0], "B")   # 8 vs 38
        self.assertEqual(stack.find_side(("D", 425, 150, 250, 100), c, DIST, GAP)[0], "B")   # 23 vs 23: first wins

    def test_choose_drop_priority(self):
        bottoms = [("A", 100, 100, 300, 200)]                    # snap-under target: y 302, x overlap with A
        others = [("A", 100, 100, 300, 200), ("C", 500, 400, 300, 200)]    # side target for D: x = 500 - 2 - 300 = 198
        def drop(dx, dy):
            return stack.choose_drop(("D", 198 + dx, 302 + dy, 300, 200), bottoms, others, DIST, GAP)
        self.assertEqual(drop(5, 10), ("side", "C", 198, 400))      # side distance 5 < under distance 10
        self.assertEqual(drop(10, 5), ("below", "A"))
        self.assertEqual(drop(7, 7), ("below", "A"))                # tie: snapping under wins
        self.assertEqual(drop(30, 30), None)
        self.assertEqual(drop(30, 5), ("below", "A"))
        self.assertEqual(drop(5, 30), ("side", "C", 198, 400))
        self.assertEqual(stack.choose_drop(("D", 198, 302, 300, 200), [], others, DIST, GAP), ("side", "C", 198, 400))


class Base(unittest.TestCase):
    CAL = False

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mpanels_t110s7a_")
        self.desk, self.pub, self.data = (os.path.join(self.tmp, n) for n in ("Desktop", "Public", "veri"))
        os.makedirs(self.desk)
        os.makedirs(self.pub)
        p = mock.patch("calendar_panel.model.CalendarModel.refresh", lambda *a, **k: None)
        p.start()
        self.addCleanup(p.stop)
        # drags in these tests are synthetic: the real left button is not down, so the "release lost" safety net
        # (GetAsyncKeyState) is told it is. Its own tests (TestDropFix) control this themselves.
        self.btn = mock.patch.object(winutil, "lbutton_down", return_value=True)
        self.btn.start()
        self.addCleanup(self.btn.stop)
        self.app = self.open_app()

    def open_app(self):
        self.disp = FakeDisplays(THREE)                      # never the real screens: tests must not depend on them (7c)
        app = mpanels.App(fileops.Ctx(self.desk, self.pub), self.data, test_mode=True, use_tray=False,
                          instance_name="t110s7a_%d_%d" % (os.getpid(), id(self)),
                          displays_provider=self.disp, clock=FakeClock())
        self.addCleanup(app.quit)
        app.monitor_of = lambda x, y: 1                       # one monitor, deterministic
        return app

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def park(self):
        """Move every existing panel far away so it cannot be a snap candidate."""
        for i, p in enumerate(self.app.panels.values()):
            p.cfg["x"], p.cfg["y"] = 2500 + 10 * i, 900
            p.top.geometry(f"+{p.cfg['x']}+{p.cfg['y']}")

    def mk(self, names, x=100, y=100, w=300, h=200):
        self.park()
        out = []
        for i, n in enumerate(names):
            p = self.app.new_panel(n)
            p.cfg.update(x=x + 400 * i, y=y, w=w, h=h, collapsed=False)
            p.cfg["collapsed"] = False
            p.expanded = True
            p.apply_size(w, h)
            p.top.geometry(f"+{p.cfg['x']}+{p.cfg['y']}")
            self.app.set_home(p)                    # the test put it here "as the user": that is its home (7c)
            out.append(p)
        pump(self.app)
        return out

    def stack_up(self, *panels):
        """Put panels (already created) into one stack under the first one."""
        self.app.cfg["stacks"] = [[p.name for p in panels]]
        self.app.relayout_all()
        pump(self.app)

    def drag(self, p, dx, dy, steps=3):
        """Header drag with real handlers: press on the title, move, release."""
        x0, y0 = p.cfg["x"] + 40, p.cfg["y"] + 8
        p._head_press(ev(x0, y0, 40))
        for i in range(1, steps + 1):
            p._head_motion(ev(x0 + dx * i // steps, y0 + dy * i // steps, 40))
        p._head_release(ev(x0 + dx, y0 + dy, 40))
        pump(self.app)

    def geo(self, p):
        return p.top.winfo_x(), p.top.winfo_y(), p.top.winfo_width(), p.top.winfo_height()

    def assert_chain(self, names):
        """Every panel under the first: same left edge and width, exactly `gap` between them."""
        ps = [self.app.panels[n] for n in names]
        for a, b in zip(ps, ps[1:]):
            self.assertEqual(b.cfg["y"], a.cfg["y"] + a.cur_h + GAP, (a.name, b.name))
            self.assertEqual((b.cfg["x"], b.cfg["w"], b.cur_w), (a.cfg["x"], a.cfg["w"], a.cfg["w"]))
        return ps


class TestSnap(Base):
    def drop_under(self, a, d, dy, dx=0):
        """Drop D with its top edge `dy` px away from the TARGET position (A's bottom + stack_gap)."""
        d.cfg["x"], d.cfg["y"] = a.cfg["x"] + dx, a.cfg["y"] + a.cur_h + GAP + dy
        return self.app.drop_snap(d)

    def test_threshold_23_24_25(self):
        for dy, ok in ((23, True), (24, True), (25, False), (-23, True), (-24, True), (-25, False)):
            self.app.cfg["stacks"] = []
            a, d = self.mk(["A%d" % dy, "D%d" % dy])                   # mk() parks the panels of earlier rounds
            self.assertEqual(self.drop_under(a, d, dy), ok, dy)
            self.assertEqual(self.app.cfg["stacks"], [[a.name, d.name]] if ok else [], dy)

    def test_no_horizontal_overlap_no_snap(self):
        a, d = self.mk(["A", "D"])
        self.assertFalse(self.drop_under(a, d, 5, dx=a.cfg["w"] + 20))
        self.assertEqual(self.app.cfg["stacks"], [])

    def test_left_and_width_equalised_and_gap(self):
        a, d = self.mk(["A", "D"], w=300)
        d.apply_size(200, 120)
        d.cfg["w"] = 200
        self.assertTrue(self.drop_under(a, d, 10, dx=30))
        pump(self.app)
        self.assertEqual((d.cfg["x"], d.cfg["w"], d.cfg["y"]), (a.cfg["x"], a.cfg["w"], a.cfg["y"] + a.cur_h + GAP))
        x, y, w, _ = self.geo(d)
        self.assertEqual((x, y, w), (d.cfg["x"], d.cfg["y"], a.cfg["w"]))                # the real window moved/resized

    def test_snap_by_real_drag_and_release(self):
        a, d = self.mk(["A", "D"])
        self.drag(d, a.cfg["x"] - d.cfg["x"] + 15, a.cfg["y"] + a.cur_h + 12 - d.cfg["y"])
        self.assertEqual(self.app.cfg["stacks"], [["A", "D"]])
        self.assert_chain(["A", "D"])

    def test_only_to_the_bottom_not_the_middle(self):
        a, b, c, d = self.mk(["A", "B", "C", "D"])
        self.stack_up(a, b, c)
        self.assertFalse(self.drop_under(b, d, 3))                                      # B is in the middle
        self.assertEqual(self.app.cfg["stacks"], [["A", "B", "C"]])
        self.assertTrue(self.drop_under(c, d, 3))                                       # C is the bottom
        self.assertEqual(self.app.cfg["stacks"], [["A", "B", "C", "D"]])
        self.assert_chain(["A", "B", "C", "D"])

    def test_nearest_candidate_wins(self):
        a, b, d = self.mk(["A", "B", "D"], x=100)
        b.cfg["x"], b.cfg["y"] = 150, a.cfg["y"] + 60                                    # a second free panel overlapping A
        b.top.geometry(f"+{b.cfg['x']}+{b.cfg['y']}")
        d.cfg["x"], d.cfg["y"] = 100, b.cfg["y"] + b.cur_h + 4                           # 4 px under B, far from A's bottom edge
        self.assertTrue(self.app.drop_snap(d))
        self.assertEqual(self.app.cfg["stacks"], [["B", "D"]])

    def test_panel_from_another_monitor_snaps_and_ends_on_the_stack_monitor(self):
        a, d = self.mk(["A", "D"], w=300)                                                # A: x 100..400 (monitor 1)
        self.app.monitor_of = lambda x, y: 1 if x < 400 else 2                           # fake: two monitors side by side
        d.cfg["x"], d.cfg["y"] = a.cfg["x"] + 150, a.cfg["y"] + a.cur_h + GAP + 5        # D's centre (x 400) is on monitor 2
        self.assertEqual(self.app.monitor_of(d.cfg["x"] + d.cur_w // 2, d.cfg["y"]), 2)
        self.assertTrue(self.app.drop_snap(d))                                           # the origin monitor does not block it
        pump(self.app)
        self.assertEqual(self.app.cfg["stacks"], [["A", "D"]])
        self.assertEqual(d.cfg["x"], a.cfg["x"])                                         # left edge and width follow the top ...
        self.assertEqual(self.app.stack_monitor("D"), 1)                                 # ... so D is now on the top's monitor
        self.assertEqual(self.app.stack_monitor("A"), self.app.stack_monitor("D"))
        self.assertEqual(self.app.monitor_of(d.cfg["x"] + d.cur_w // 2, d.cfg["y"]), 1)

    def test_locked_no_snap_and_no_detach(self):
        a, b, d = self.mk(["A", "B", "D"])
        self.stack_up(a, b)
        self.app.set_lock(True)
        self.assertFalse(self.drop_under(b, d, 3))
        self.drag(b, 0, 300)                                                             # locked: the header does not move
        self.assertEqual(self.app.cfg["stacks"], [["A", "B"]])
        self.assert_chain(["A", "B"])

    def test_snap_disabled_blocks_new_snaps_only(self):
        a, b, d = self.mk(["A", "B", "D"])
        self.stack_up(a, b)
        self.app.cfg["general"]["snap_enabled"] = False
        self.assertFalse(self.drop_under(b, d, 3))
        self.assertEqual(self.app.cfg["stacks"], [["A", "B"]])
        a.toggle()                                                                       # existing stacks still push
        pump(self.app, 0.4)
        self.assert_chain(["A", "B"])
        self.drag(b, 0, 200)                                                             # and still detach
        self.assertEqual(self.app.cfg["stacks"], [])


class TestStack(Base):
    def test_push_on_every_frame_while_opening_and_closing(self):
        a, b, c = self.mk(["A", "B", "C"])
        self.stack_up(a, b, c)
        frames = []
        orig = b.apply_size

        def spy(w, h, first=False):
            orig(w, h, first)
            frames.append(c.cfg["y"] - (b.cfg["y"] + b.cur_h))
        b.apply_size = spy
        b.toggle()                                                                       # collapse (animated)
        pump(self.app, 0.4)
        self.assertGreaterEqual(len(frames), 7)
        self.assertEqual(set(frames), {GAP})                                             # C kept the gap on EVERY frame
        self.assertEqual(b.cur_h, b.head_h)
        self.assert_chain(["A", "B", "C"])
        self.assertEqual(self.geo(c)[1], c.cfg["y"])                                     # the real window followed too
        frames.clear()
        b.toggle()                                                                       # expand
        pump(self.app, 0.4)
        self.assertEqual(set(frames), {GAP})
        self.assertEqual(b.cur_h, 200)
        self.assert_chain(["A", "B", "C"])

    def test_top_collapse_pushes_everything(self):
        a, b, c = self.mk(["A", "B", "C"])
        self.stack_up(a, b, c)
        a.toggle()
        pump(self.app, 0.4)
        self.assertEqual(a.cur_h, a.head_h)
        self.assert_chain(["A", "B", "C"])
        self.assertEqual(b.cfg["y"], a.cfg["y"] + a.head_h + GAP)

    def test_height_resize_pushes(self):
        a, b, c = self.mk(["A", "B", "C"])
        self.stack_up(a, b, c)
        b.cfg["h"] = 320
        b.apply_size(b.cfg["w"], 320)
        self.assert_chain(["A", "B", "C"])

    def test_top_drag_moves_whole_stack(self):
        a, b, c = self.mk(["A", "B", "C"])
        self.stack_up(a, b, c)
        y0 = [p.cfg["y"] for p in (a, b, c)]
        self.drag(a, 60, 40)
        self.assertEqual(self.app.cfg["stacks"], [["A", "B", "C"]])
        self.assertEqual([p.cfg["y"] for p in (a, b, c)], [y + 40 for y in y0])
        self.assert_chain(["A", "B", "C"])
        self.assertEqual(self.geo(c)[:2], (c.cfg["x"], c.cfg["y"]))

    def test_middle_leaves_and_gap_closes(self):
        a, b, c, d = self.mk(["A", "B", "C", "D"])
        self.stack_up(a, b, c, d)
        self.drag(b, 700, 200)                                                           # far away from every panel
        self.assertEqual(self.app.cfg["stacks"], [["A", "C", "D"]])
        self.assertEqual(c.cfg["y"], a.cfg["y"] + a.cur_h + GAP)                         # C moved up, gap closed
        self.assert_chain(["A", "C", "D"])
        self.assertIsNone(self.app.stack_pos("B"))
        self.assertGreater(b.cfg["x"], 600)

    def test_bottom_leaves_and_can_snap_under_another_stack(self):
        a, b, c, x, y = self.mk(["A", "B", "C", "X", "Y"])
        self.stack_up(a, b, c)
        self.app.cfg["stacks"].append(["X", "Y"])
        self.app.relayout_all()
        self.drag(c, x.cfg["x"] - c.cfg["x"], y.cfg["y"] + y.cur_h + 10 - c.cfg["y"])
        self.assertEqual(self.app.cfg["stacks"], [["A", "B"], ["X", "Y", "C"]])
        self.assert_chain(["X", "Y", "C"])

    def slot_drag(self, p, dys, release=True):
        """Press the title of a member, move it by each dy (px from the press point), optionally release."""
        x0, y0 = p.cfg["x"] + 40, p.cfg["y"] + 8
        p._head_press(ev(x0, y0, 40))
        for dy in dys:
            p._head_motion(ev(x0, y0 + dy, 40))
        if release:
            p._head_release(ev(x0, y0 + dys[-1], 40))
        pump(self.app)

    def test_member_leaves_only_beyond_snap_distance(self):
        a, b, c = self.mk(["A", "B", "C"])
        self.stack_up(a, b, c)
        slot = (b.cfg["x"], b.cfg["y"])
        cy = c.cfg["y"]
        self.slot_drag(b, [10, 24], release=False)                                       # 24 px: still in its slot's range
        self.assertEqual(self.app.cfg["stacks"], [["A", "B", "C"]])
        self.assertEqual(c.cfg["y"], cy)                                                 # the panel below has NOT moved
        self.assertEqual(b.cfg["y"], slot[1] + 24)                                       # B itself follows the mouse
        b._head_motion(ev(b.cfg["x"] + 40 - 0, slot[1] + 8 + 25, 40))                    # 25 px: pulled out
        self.assertEqual(self.app.cfg["stacks"], [["A", "C"]])
        self.assertEqual(c.cfg["y"], a.cfg["y"] + a.cur_h + GAP)                         # gap closed at that moment
        b._head_release(ev(b.cfg["x"] + 40, slot[1] + 33, 40))
        pump(self.app)
        self.assertEqual(self.app.cfg["stacks"], [["A", "C"]])                           # stays out after the drop (far enough from A/C)
        self.assertIsNone(self.app.stack_pos("B"))

    def test_member_dropped_within_threshold_returns_and_stack_unchanged(self):
        a, b, c = self.mk(["A", "B", "C"])
        self.stack_up(a, b, c)
        slot = (b.cfg["x"], b.cfg["y"])
        ys = (a.cfg["y"], c.cfg["y"])
        self.slot_drag(b, [8, 18, 12])                                                   # wanders, released 12 px from the slot
        self.assertEqual(self.app.cfg["stacks"], [["A", "B", "C"]])
        self.assertEqual((b.cfg["x"], b.cfg["y"]), slot)
        self.assertEqual((a.cfg["y"], c.cfg["y"]), ys)
        self.assertEqual(self.geo(b)[:2], slot)                                          # the real window is back too
        self.assert_chain(["A", "B", "C"])
        self.assertFalse(b._held)

    def test_sideways_pull_also_counts(self):
        a, b, c = self.mk(["A", "B", "C"])
        self.stack_up(a, b, c)
        x0, y0 = b.cfg["x"] + 40, b.cfg["y"] + 8
        b._head_press(ev(x0, y0, 40))
        b._head_motion(ev(x0 + 24, y0, 40))
        self.assertEqual(self.app.cfg["stacks"], [["A", "B", "C"]])
        b._head_motion(ev(x0 + 40, y0, 40))
        self.assertEqual(self.app.cfg["stacks"], [["A", "C"]])
        b._head_release(ev(x0 + 40, y0, 40))

    def test_held_member_is_not_moved_by_a_push(self):
        a, b, c = self.mk(["A", "B", "C"])
        self.stack_up(a, b, c)
        b._head_press(ev(b.cfg["x"] + 40, b.cfg["y"] + 8, 40))
        b._head_motion(ev(b.cfg["x"] + 40, b.cfg["y"] + 18, 40))
        y = b.cfg["y"]
        a.toggle()                                                                       # the stack above changes while B is held
        pump(self.app, 0.4)
        self.assertEqual(b.cfg["y"], y)
        self.assertEqual(c.cfg["y"], a.cfg["y"] + a.head_h + GAP + b.cur_h + GAP)
        b._head_release(ev(b.cfg["x"] + 40, b.cfg["y"] + 18, 40))
        pump(self.app)
        self.assert_chain(["A", "B", "C"])

    def test_two_panel_stack_disappears_when_one_leaves(self):
        a, b = self.mk(["A", "B"])
        self.stack_up(a, b)
        self.drag(b, 700, 300)
        self.assertEqual(self.app.cfg["stacks"], [])

    def test_shared_width(self):
        a, b, c = self.mk(["A", "B", "C"])
        self.stack_up(a, b, c)
        b.resizing, b.press = True, (500, 500, None)
        b._body_drag(ev(540, 520))                                                       # +40 wide, +20 high (member B)
        pump(self.app)
        self.assertEqual({p.cfg["w"] for p in (a, b, c)}, {340})
        self.assertEqual({p.cur_w for p in (a, b, c)}, {340})
        self.assertEqual((a.cfg["h"], b.cfg["h"], c.cfg["h"]), (200, 220, 200))          # height stays per panel
        self.assert_chain(["A", "B", "C"])
        b.resizing = False
        a.resizing, a.press = True, (500, 500, None)
        a._body_drag(ev(480, 500))                                                       # the top: -20
        self.assertEqual({p.cfg["w"] for p in (a, b, c)}, {320})

    def test_clamp_only_the_top(self):
        a, b, c = self.mk(["A", "B", "C"], y=100)
        self.stack_up(a, b, c)
        work_bottom = 1032                                                               # fake monitors: rcWork bottom (taskbar)
        self.drag(a, 0, 1080 - 150 - a.cfg["y"] + 400)                                   # drop the top far below the screen
        self.assertEqual(a.cfg["y"], work_bottom - a.head_h)                             # the top is clamped to the work area
        self.assertGreater(c.cfg["y"], work_bottom)                                      # the bottom ones overflow, not clamped
        self.assert_chain(["A", "B", "C"])

    def test_locked_still_pushes(self):
        a, b, c = self.mk(["A", "B", "C"])
        self.stack_up(a, b, c)
        self.app.set_lock(True)
        b.toggle()
        pump(self.app, 0.4)
        self.assert_chain(["A", "B", "C"])
        self.assertEqual(b.cur_h, b.head_h)

    def test_remove_and_rename_update_stacks(self):
        a, b, c = self.mk(["A", "B", "C"])
        self.stack_up(a, b, c)
        self.app.rename_panel(b, "B2")
        pump(self.app)
        self.assertEqual(self.app.cfg["stacks"], [["A", "B2", "C"]])
        self.assert_chain(["A", "B2", "C"])
        self.app.remove_panel(self.app.panels["B2"], confirm=False)
        pump(self.app)
        self.assertEqual(self.app.cfg["stacks"], [["A", "C"]])
        self.assert_chain(["A", "C"])
        self.app.remove_panel(self.app.panels["C"], confirm=False)
        self.assertEqual(self.app.cfg["stacks"], [])

    def test_frame_cost_with_17_panels(self):
        ps = self.mk(["P%02d" % i for i in range(17)], h=120)
        self.stack_up(*ps)
        top = ps[0]
        n, t0 = 60, time.perf_counter()
        for i in range(n):
            top.cfg["y"] += 1                                                            # forces every window to move
            self.app.stack_changed(top)
            self.app.root.update_idletasks()                                             # the real window moves happen here
        ms = (time.perf_counter() - t0) * 1000 / n
        print("\n  17-panel stack: %.2f ms per frame (PLAN measured ~5.3 ms)" % ms)
        self.assertLess(ms, 15.0)


class TestPersistence(Base):
    def read_cfg(self):
        with open(self.app.config_path, encoding="utf-8") as f:
            return json.load(f)

    def test_save_and_reload_recomputes_gaps(self):
        a, b, c = self.mk(["A", "B", "C"])
        self.stack_up(a, b, c)
        c.toggle()
        pump(self.app, 0.4)
        self.app.save()
        saved = self.read_cfg()
        self.assertEqual(saved["stacks"], [["A", "B", "C"]])
        self.assertEqual(saved["general"]["snap_distance"], 24)
        self.assertEqual(saved["general"]["stack_gap"], 2)
        self.assertIs(saved["general"]["snap_enabled"], True)
        # corrupt the saved member positions: only the top's position may matter
        saved["panels"]["B"].update(x=-5000, y=7777, w=111)
        saved["panels"]["C"].update(x=9999, y=-3, w=999)
        with open(self.app.config_path, "w", encoding="utf-8") as f:
            json.dump(saved, f)
        self.app.quit()
        app2 = self.open_app()
        pump(app2, 0.2)
        self.assertEqual(app2.cfg["stacks"], [["A", "B", "C"]])
        a2, b2, c2 = (app2.panels[n] for n in "ABC")
        self.assertEqual((b2.cfg["x"], b2.cfg["w"]), (a2.cfg["x"], a2.cfg["w"]))
        self.assertEqual(b2.cfg["y"], a2.cfg["y"] + a2.cur_h + GAP)
        self.assertEqual(c2.cfg["y"], b2.cfg["y"] + b2.cur_h + GAP)
        self.assertEqual((b2.top.winfo_x(), b2.top.winfo_y()), (b2.cfg["x"], b2.cfg["y"]))

    def test_saved_members_are_at_their_settled_place_even_mid_animation(self):
        a, b, c = self.mk(["A", "B", "C"])
        self.stack_up(a, b, c)
        b.toggle()                                                                       # saves immediately, animation just began
        saved = self.read_cfg()
        self.assertEqual(saved["panels"]["C"]["y"], a.cfg["y"] + 200 + GAP + b.head_h + GAP)
        pump(self.app, 0.4)

    def test_garbage_stacks_in_config_are_cleaned_on_load(self):
        self.app.new_panel("A")
        self.app.new_panel("B")
        self.app.cfg["stacks"] = [["A", "ghost", "B", "A"], "junk", ["B", "A"]]
        self.app.cfg["general"].update(snap_distance="abc", stack_gap=-4, snap_enabled="yes")
        self.app.save()
        self.app.quit()
        app2 = self.open_app()
        self.assertEqual(app2.cfg["stacks"], [["A", "B"]])
        g = app2.cfg["general"]
        self.assertEqual((g["snap_distance"], g["stack_gap"], g["snap_enabled"]), (24, 2, True))


class TestSnappingSettings(Base):
    """Settings > General > Snapping (three boxes, Apply rule, Make default / Revert / Factory)."""

    def setUp(self):
        super().setUp()
        self.ps = self.mk(["A", "B", "C"])
        self.app.open_settings("A")
        pump(self.app)
        self.S = self.app.settings_win

    def g(self):
        return self.app.cfg["general"]

    def saved(self):
        with open(self.app.defaults_path, encoding="utf-8") as f:
            return json.load(f)

    def test_boxes_show_the_config_and_window_is_clean(self):
        S = self.S
        self.assertEqual((S.v_snap.get(), S.v_snap_dist.get(), S.v_stack_gap.get()), (True, "24", "2"))
        self.assertFalse(S.dirty())
        self.assertEqual(S.cb_snap.cget("text"), "Snap panels")
        S.win.update()
        S.nb.select(S.tab["general"])
        S.win.update()
        ys = {w.winfo_y() for w in (S.cb_snap, S.sp_snap_dist, S.sp_stack_gap)}            # one tight row
        self.assertEqual(len(ys), 1)

    def test_nothing_changes_without_apply_and_each_box_makes_it_dirty(self):
        S = self.S
        for var, val in ((S.v_snap, False), (S.v_snap_dist, "30"), (S.v_stack_gap, "12")):
            old = var.get()
            var.set(val)
            self.assertTrue(S.dirty())
            self.assertEqual((self.g()["snap_enabled"], self.g()["snap_distance"], self.g()["stack_gap"]), (True, 24, 2))
            var.set(old)
            self.assertFalse(S.dirty())

    def test_apply_writes_config(self):
        S = self.S
        S.v_snap.set(False)
        S.v_snap_dist.set("30")
        S.v_stack_gap.set("12")
        S.apply()
        g = self.g()
        self.assertEqual((g["snap_enabled"], g["snap_distance"], g["stack_gap"]), (False, 30, 12))
        with open(self.app.config_path, encoding="utf-8") as f:
            gs = json.load(f)["general"]
        self.assertEqual((gs["snap_enabled"], gs["snap_distance"], gs["stack_gap"]), (False, 30, 12))
        self.assertFalse(S.dirty())

    def test_range_edges(self):
        S = self.S
        for dist, gap, ok in (("4", "0", True), ("64", "24", True), ("3", "8", False), ("65", "8", False),
                              ("24", "-1", False), ("24", "25", False), ("abc", "8", False), ("", "8", False),
                              ("24", "", False), ("2.5", "8", False)):
            self.g().update(snap_distance=24, stack_gap=8)
            S._load_general()
            S.v_snap_dist.set(dist)
            S.v_stack_gap.set(gap)
            S.apply()
            if ok:
                self.assertEqual((self.g()["snap_distance"], self.g()["stack_gap"]), (int(dist), int(gap)), (dist, gap))
            else:
                self.assertEqual((self.g()["snap_distance"], self.g()["stack_gap"]), (24, 8), (dist, gap))
                self.assertIn("must be a whole number", S.msg.cget("text"))
                self.assertEqual((S.v_snap_dist.get(), S.v_stack_gap.get()), ("24", "8"))      # boxes return to what is applied
            self.assertFalse(S.dirty())

    def test_invalid_value_warns_but_valid_part_applies(self):
        S = self.S
        S.v_snap_dist.set("30")
        S.v_stack_gap.set("99")
        S.apply()
        self.assertEqual((self.g()["snap_distance"], self.g()["stack_gap"]), (30, 2))
        self.assertIn("Stack gap must be a whole number from 0 to 24", S.msg.cget("text"))

    def test_new_gap_restacks_from_the_top(self):
        a, b, c = self.ps
        self.stack_up(a, b, c)
        top = (a.cfg["x"], a.cfg["y"])
        S = self.S
        S.v_stack_gap.set("20")
        S.apply()
        pump(self.app)
        self.assertEqual((a.cfg["x"], a.cfg["y"]), top)                                  # the top stays
        self.assertEqual(b.cfg["y"], a.cfg["y"] + a.cur_h + 20)
        self.assertEqual(c.cfg["y"], b.cfg["y"] + b.cur_h + 20)
        self.assertEqual(self.geo(c)[1], c.cfg["y"])                                     # real windows moved too
        S.v_stack_gap.set("0")
        S.apply()
        self.assertEqual(c.cfg["y"], b.cfg["y"] + b.cur_h)

    def test_snap_unticked_stops_new_snaps_keeps_stacks(self):
        a, b, c = self.ps
        self.stack_up(a, b)
        self.S.v_snap.set(False)
        self.S.apply()
        c.cfg["x"], c.cfg["y"] = b.cfg["x"], b.cfg["y"] + b.cur_h + GAP + 2
        self.assertFalse(self.app.drop_snap(c))
        b.toggle()
        pump(self.app, 0.4)
        self.assertEqual(self.app.cfg["stacks"], [["A", "B"]])
        self.assertEqual(b.cur_h, b.head_h)

    def test_distance_setting_is_used_by_snapping(self):
        a, b, c = self.ps
        self.S.v_snap_dist.set("10")
        self.S.apply()
        for dy, ok in ((10, True), (11, False)):
            self.app.cfg["stacks"] = []
            b.cfg["x"], b.cfg["y"] = a.cfg["x"], a.cfg["y"] + a.cur_h + GAP + dy
            self.assertEqual(self.app.drop_snap(b), ok, dy)

    def test_make_default_revert_and_factory(self):
        S = self.S
        S.v_snap.set(False)
        S.v_snap_prev.set(False)
        S.v_snap_dist.set("40")
        S.v_stack_gap.set("16")
        S.make_default()                                                                 # applies, then saves
        self.assertEqual(self.saved()[mpanels.SNAPPING_KEY],
                         {"snap_enabled": False, "snap_preview": False, "snap_distance": 40, "stack_gap": 16})
        self.assertIn("color", self.saved())                                             # the look is still saved too
        self.app.cfg["general"].update(snap_enabled=True, snap_distance=10, stack_gap=5)     # what is in force now
        S._load_general()
        self.assertFalse(S.dirty())
        with mock.patch.object(S, "confirm_overwrite", return_value=True):
            S.reset(False)                                                               # Revert to defaults
        g = self.g()
        self.assertEqual((g["snap_enabled"], g["snap_distance"], g["stack_gap"]), (True, 10, 5))   # NOT applied
        self.assertEqual((S.v_snap.get(), S.v_snap_dist.get(), S.v_stack_gap.get()), (False, "40", "16"))   # loaded
        self.assertTrue(S.dirty())
        self.assertIn("press Apply", S.msg.cget("text"))
        S.apply()
        g = self.g()
        self.assertEqual((g["snap_enabled"], g["snap_distance"], g["stack_gap"]), (False, 40, 16))
        self.assertFalse(S.dirty())
        with mock.patch.object(S, "confirm_overwrite", return_value=True):
            S.reset(True)                                                                # Factory: built-in, saved default kept
        g = self.g()
        self.assertEqual((g["snap_enabled"], g["snap_distance"], g["stack_gap"]), (False, 40, 16))   # still NOT applied
        self.assertEqual((S.v_snap.get(), S.v_snap_dist.get(), S.v_stack_gap.get()), (True, "24", "2"))
        self.assertTrue(S.dirty())
        S.apply()
        self.assertEqual((g["snap_enabled"], g["snap_distance"], g["stack_gap"]), (True, 24, 2))
        self.assertEqual(self.saved()[mpanels.SNAPPING_KEY]["snap_distance"], 40)

    def test_revert_declined_loads_nothing(self):
        S = self.S
        S.make_default()
        S.v_snap_dist.set("50")
        with mock.patch.object(S, "confirm_overwrite", return_value=False):
            S.reset(True)
        self.assertEqual(S.v_snap_dist.get(), "50")                                      # the edit is still there

    def test_revert_keeps_stacks_until_apply(self):
        a, b, c = self.ps
        self.stack_up(a, b, c)
        self.g()["stack_gap"] = 5
        self.app.relayout_all()
        S = self.S
        S._load_general()
        with mock.patch.object(S, "confirm_overwrite", return_value=True):
            S.reset(True)
        pump(self.app)
        self.assertEqual(b.cfg["y"], a.cfg["y"] + a.cur_h + 5)                           # not re-stacked yet
        S.apply()
        self.assertEqual(b.cfg["y"], a.cfg["y"] + a.cur_h + 2)                           # now the factory gap

    def test_builtin_default_gap_is_2_and_existing_value_is_kept(self):
        self.assertEqual(stack.DEFAULT_STACK_GAP, 2)
        self.assertEqual(stack.sanitize_general({})["stack_gap"], 2)
        self.assertEqual(self.app.snapping_defaults(factory=True)["stack_gap"], 2)
        self.g()["stack_gap"] = 8                                                        # an explicit value from an older config
        self.app.save()
        self.app.quit()
        app2 = self.open_app()
        self.assertEqual(app2.cfg["general"]["stack_gap"], 8)

    def test_garbage_saved_default_falls_back(self):
        self.app.save_defaults(**{mpanels.SNAPPING_KEY: {"snap_distance": 999, "stack_gap": "x", "snap_enabled": 5}})
        self.assertEqual(self.app.snapping_defaults(), {"snap_enabled": True, "snap_preview": True, "snap_distance": 24, "stack_gap": 2})
        self.app.save_defaults(**{mpanels.SNAPPING_KEY: "junk"})
        self.assertEqual(self.app.snapping_defaults(), {"snap_enabled": True, "snap_preview": True, "snap_distance": 24, "stack_gap": 2})

    def test_discard_reloads_the_boxes(self):
        S = self.S
        S.v_snap_dist.set("50")
        S.ask_unsaved = lambda: "discard"
        self.assertTrue(S._resolve_unsaved())
        self.assertEqual(S.v_snap_dist.get(), "24")
        self.assertEqual(self.g()["snap_distance"], 24)


class TestSideSnap(Base):
    """Step 7b: snap sideways (alignment only: same width, tops aligned, nothing remembered)."""

    def place(self, p, x, y, w=None, h=None):
        if w or h:
            p.cfg["w"], p.cfg["h"] = w or p.cfg["w"], h or p.cfg["h"]
            p.apply_size(p.cfg["w"], p.cfg["h"])
        p.cfg["x"], p.cfg["y"] = x, y
        p.top.geometry(f"+{x}+{y}")

    def test_thresholds_follow_the_target_position(self):
        right_t, left_t = 100 + 300 + GAP, 100 - GAP - 250
        for tx, d, ok in ((right_t, 23, True), (right_t, 24, True), (right_t, 25, False), (right_t, -24, True),
                          (right_t, -25, False), (left_t, 24, True), (left_t, -24, True), (left_t, 25, False),
                          (left_t, -25, False)):
            b, d_ = self.mk(["B%d_%d" % (tx, d), "D%d_%d" % (tx, d)])
            self.place(b, 100, 100)
            self.place(d_, tx + d, 130, w=250, h=100)
            self.assertEqual(self.app.drop_snap(d_), ok, (tx, d))
            self.assertEqual(d_.cfg["x"], tx if ok else tx + d, (tx, d))
            self.assertEqual(d_.cfg["y"], 100 if ok else 130, (tx, d))
            self.assertEqual(self.app.cfg["stacks"], [])

    def test_no_vertical_overlap_no_snap(self):
        b, d = self.mk(["B", "D"])
        self.place(b, 100, 100)                                                          # y 100..300
        self.place(d, 100 + 300 + GAP, 300, w=250, h=100)                                # starts exactly where B ends
        self.assertFalse(self.app.drop_snap(d))
        self.place(d, 100 + 300 + GAP, 299)                                              # 1 px of overlap: not an intention
        self.assertFalse(self.app.drop_snap(d))
        self.place(d, 100 + 300 + GAP, 250)                                              # shares 50 = half of D's 100
        self.assertTrue(self.app.drop_snap(d))
        self.place(d, 100 + 300 + GAP, 600)                                              # far below
        self.assertFalse(self.app.drop_snap(d))

    def test_tops_aligned_and_width_unchanged(self):
        b, d = self.mk(["B", "D"])
        self.place(b, 100, 100)
        self.place(d, 410, 160, w=250, h=100)
        self.assertTrue(self.app.drop_snap(d))
        pump(self.app)
        self.assertEqual((d.cfg["x"], d.cfg["y"]), (402, 100))
        self.assertEqual((d.cfg["w"], d.cur_w, d.top.winfo_width()), (250, 250, 250))    # width did NOT change
        self.assertEqual(self.geo(d)[:2], (402, 100))
        self.assertEqual(b.cfg["w"], 300)

    def test_real_drag_and_release_snaps_sideways(self):
        b, d = self.mk(["B", "D"])
        self.place(b, 100, 100)
        self.place(d, 900, 500, w=250, h=100)
        self.drag(d, (100 - GAP - 250 + 7) - d.cfg["x"], 140 - d.cfg["y"])               # to the LEFT of B, 7 px off, 40 px low
        self.assertEqual((d.cfg["x"], d.cfg["y"]), (100 - GAP - 250, 100))
        self.assertEqual(self.app.cfg["stacks"], [])

    def test_no_lasting_relation(self):
        b, d = self.mk(["B", "D"])
        self.app.save()
        with open(self.app.config_path, encoding="utf-8") as f:
            before = json.load(f)
        self.place(b, 100, 100)
        self.place(d, 410, 160, w=250, h=100)
        self.assertTrue(self.app.drop_snap(d))
        self.app.save()
        with open(self.app.config_path, encoding="utf-8") as f:
            after = json.load(f)
        self.assertEqual(set(after), set(before))                                        # no new top-level key (no group)
        self.assertEqual(after["stacks"], [])
        self.assertEqual({n: set(c) for n, c in after["panels"].items()}, {n: set(c) for n, c in before["panels"].items()})
        self.assertEqual(set(after["general"]), set(before["general"]))
        dx, dy = d.cfg["x"], d.cfg["y"]
        self.place(b, 300, 400)                                                          # moving B does not bring D
        pump(self.app)
        self.assertEqual((d.cfg["x"], d.cfg["y"]), (dx, dy))
        b.toggle()                                                                       # B collapsing does not push D
        pump(self.app, 0.4)
        self.assertEqual((d.cfg["x"], d.cfg["y"]), (dx, dy))
        self.assertEqual(self.geo(d)[:2], (dx, dy))

    def test_stack_top_snaps_sideways_and_the_whole_stack_follows(self):
        a, b, c, t = self.mk(["A", "B", "C", "T"])
        self.stack_up(a, b, c)
        self.place(t, 900, 300)
        self.drag(a, (900 - GAP - 300 + 5) - a.cfg["x"], 330 - a.cfg["y"])               # A's right edge 5 px off T's left edge
        self.assertEqual((a.cfg["x"], a.cfg["y"]), (900 - GAP - 300, 300))               # top aligned with T
        self.assertEqual(self.app.cfg["stacks"], [["A", "B", "C"]])                      # the stack is unchanged
        self.assert_chain(["A", "B", "C"])                                               # and moved as one
        self.assertEqual(self.geo(c)[:2], (c.cfg["x"], c.cfg["y"]))
        self.assertEqual(a.cfg["w"], 300)

    def test_snaps_beside_a_stack_member_using_its_top_edge(self):
        a, b, c, d = self.mk(["A", "B", "C", "D"])
        self.stack_up(a, b, c)
        self.place(d, 100 + 300 + GAP + 6, b.cfg["y"] + 20, w=250, h=100)
        self.assertTrue(self.app.drop_snap(d))
        self.assertEqual((d.cfg["x"], d.cfg["y"]), (100 + 300 + GAP, b.cfg["y"]))       # the target's own top edge
        self.assertEqual(self.app.cfg["stacks"], [["A", "B", "C"]])                      # D did not join the stack
        self.assert_chain(["A", "B", "C"])

    def test_nearer_of_below_and_side_wins_tie_goes_below(self):
        a, c, d = self.mk(["A", "C", "D"])
        self.place(a, 100, 100)
        self.place(c, 500, 400)
        under_y, left_x = 100 + a.cur_h + GAP, 500 - GAP - 300
        for dx, dy, want in ((5, 10, "side"), (10, 5, "below"), (7, 7, "below")):
            self.app.cfg["stacks"] = []
            self.place(d, left_x + dx, under_y + dy)
            self.assertTrue(self.app.drop_snap(d), (dx, dy))
            if want == "side":
                self.assertEqual((d.cfg["x"], d.cfg["y"]), (left_x, 400))
                self.assertEqual(self.app.cfg["stacks"], [])
            else:
                self.assertEqual(self.app.cfg["stacks"], [["A", "D"]])
                self.assertEqual((d.cfg["x"], d.cfg["y"]), (100, under_y))

    def test_snap_disabled_and_locked(self):
        b, d = self.mk(["B", "D"])
        self.place(b, 100, 100)
        self.place(d, 410, 160, w=250, h=100)
        self.app.cfg["general"]["snap_enabled"] = False
        self.assertFalse(self.app.drop_snap(d))
        self.assertEqual((d.cfg["x"], d.cfg["y"]), (410, 160))
        self.app.cfg["general"]["snap_enabled"] = True
        self.app.set_lock(True)
        self.assertFalse(self.app.drop_snap(d))
        self.drag(d, -5, 0)                                                              # locked: no move, no snap
        self.assertEqual((d.cfg["x"], d.cfg["y"]), (410, 160))
        self.app.set_lock(False)
        self.assertTrue(self.app.drop_snap(d))


class TestClosedTargetBug(Base):
    """Seen on a real screen: an open panel A, a CLOSED panel B (title bar only) snapped beside it (right),
    then a third panel dropped beside B snapped UNDER B's bar instead of beside it (and could overlap others)."""

    place = TestSideSnap.place

    def setup_ab(self):
        a, b, c = self.mk(["A", "B", "C"])
        a.cfg["x"], a.cfg["y"] = 100, 100
        a.top.geometry("+100+100")
        b.toggle()                                                                       # B is closed: only its bar is visible
        pump(self.app, 0.4)
        self.assertEqual(b.cur_h, b.head_h)
        b.cfg["x"], b.cfg["y"] = 100 + 300 + GAP + 6, 100 + 9                            # dropped near the right of A, a bit low
        self.assertTrue(self.app.drop_snap(b))                                           # (this part always worked)
        self.assertEqual((b.cfg["x"], b.cfg["y"]), (100 + 300 + GAP, 100))
        self.assertEqual(self.app.cfg["stacks"], [])
        c.apply_size(250, 200)
        c.cfg["w"], c.cfg["h"] = 250, 200
        return a, b, c

    def test_third_panel_beside_the_closed_one_snaps_beside_not_under(self):
        a, b, c = self.setup_ab()
        right = b.cfg["x"] + b.cur_w                                                     # 702
        # C overlaps B's bar horizontally by 20 px and starts 14 px below B's top: wants "beside B"
        c.cfg["x"], c.cfg["y"] = right - 20, b.cfg["y"] + 14
        self.assertTrue(self.app.drop_snap(c))
        self.assertEqual(self.app.cfg["stacks"], [], "snapped UNDER B's bar (formed a stack) instead of beside it")
        self.assertEqual((c.cfg["x"], c.cfg["y"]), (right + GAP, b.cfg["y"]))            # beside B, top aligned with B
        self.assertEqual(c.cfg["w"], 250)


    # ---- intention: 50 % overlap, visible rectangles, closed targets
    def test_closed_target_uses_the_bar_height(self):
        a, b, c = self.setup_ab()
        self.assertEqual(b.cur_h, b.head_h)
        right = b.cfg["x"] + b.cur_w
        # 50 % of the bar (the lower panel) is enough for a side snap; one px less is not
        half = b.head_h // 2
        c.cfg["x"], c.cfg["y"] = right + GAP + 3, b.cfg["y"] + b.head_h - half
        self.assertTrue(self.app.drop_snap(c))
        self.assertEqual((c.cfg["x"], c.cfg["y"]), (right + GAP, b.cfg["y"]))
        c.cfg["x"], c.cfg["y"] = right + GAP + 3, b.cfg["y"] + b.head_h - half + 1       # less than half of the bar
        self.assertFalse(self.app.drop_snap(c))
        self.assertEqual(self.app.cfg["stacks"], [])

    def test_open_target_after_opening_the_bar(self):
        a, b, c = self.setup_ab()
        b.toggle()                                                                       # B opens again: 200 px high
        pump(self.app, 0.4)
        right = b.cfg["x"] + b.cur_w
        c.cfg["x"], c.cfg["y"] = right - 20, b.cfg["y"] + 14                             # same drop as the bug scenario
        self.assertTrue(self.app.drop_snap(c))
        self.assertEqual(self.app.cfg["stacks"], [])
        self.assertEqual((c.cfg["x"], c.cfg["y"]), (right + GAP, b.cfg["y"]))

    def test_under_a_closed_panel_still_works_with_real_overlap(self):
        a, b, c = self.setup_ab()
        c.cfg["x"], c.cfg["y"] = b.cfg["x"] + 40, b.cfg["y"] + b.head_h + GAP + 6        # clearly under the bar (overlap 260/250)
        self.assertTrue(self.app.drop_snap(c))
        self.assertEqual(self.app.cfg["stacks"], [["B", "C"]])
        self.assertEqual(c.cfg["y"], b.cfg["y"] + b.head_h + GAP)
        self.assertEqual((c.cfg["x"], c.cfg["w"]), (b.cfg["x"], b.cfg["w"]))

    def test_colliding_below_spot_is_dropped_and_the_panel_stays(self):
        a, c, x = self.mk(["A", "C", "X"])
        self.place(a, 100, 100)                                                          # A: 100..400 x 100..300
        self.place(x, 100, 320, w=300, h=100)                                            # X sits in the spot under A
        self.place(c, 103, 100 + 200 + GAP + 2, w=300, h=200)                            # asks for "under A": that spot is taken
        self.assertFalse(self.app.drop_snap(c))                                          # no free candidate: stays where dropped
        self.assertEqual((c.cfg["x"], c.cfg["y"]), (103, 100 + 200 + GAP + 2))
        self.assertEqual(self.app.cfg["stacks"], [])

    def test_colliding_nearest_is_skipped_and_the_next_one_wins(self):
        a, c, d, x = self.mk(["A", "C", "D", "X"])
        self.place(a, 100, 100)                                                          # A: x 100..400, y 100..300
        self.place(c, 500, 400)                                                          # C: x 500..800, y 400..600
        self.place(x, 100, 320, w=300, h=60)                                             # X sits in the spot under A (y 302..502 for D)
        under_y, left_x = 100 + a.cur_h + GAP, 500 - GAP - 300
        self.place(d, left_x + 9, under_y + 2)                                           # below is nearer (2 < 9) but collides with X
        self.assertTrue(self.app.drop_snap(d))
        self.assertEqual(self.app.cfg["stacks"], [])                                     # not under A ...
        self.assertEqual((d.cfg["x"], d.cfg["y"]), (left_x, 400))                        # ... beside C, top aligned with C

    def test_colliding_side_spot_is_dropped(self):
        a, b, d, x = self.mk(["A", "B", "D", "X"])
        self.place(b, 100, 100)
        self.place(x, 100 + 300 + GAP, 120, w=100, h=100)                                # something already beside B
        self.place(d, 100 + 300 + GAP + 4, 110, w=250, h=100)
        self.assertFalse(self.app.drop_snap(d))                                          # the beside-B spot is taken: stays
        self.assertEqual((d.cfg["x"], d.cfg["y"]), (100 + 300 + GAP + 4, 110))

    def test_stack_dragged_sideways_must_not_overlap_anything_with_any_member(self):
        a, b, c, t, y = self.mk(["A", "B", "C", "T", "Y"])
        self.stack_up(a, b, c)                                                           # 3 stacked panels, 100..300 wide
        self.place(t, 900, 100)
        self.place(y, 900 - GAP - 300, 520, w=300, h=100)                                # lies where C (the 3rd member) would land
        # A (top) would go to x = 900 - 2 - 300 = 598, y = 100; B at y 302.., C at y 504..704 collides with Y (520..620)
        self.place(a, 598 + 6, 104)
        self.app.stack_changed(a)                                                        # the members follow the top (as while dragging)
        self.assertFalse(self.app.drop_snap(a))
        self.assertEqual((a.cfg["x"], a.cfg["y"]), (604, 104))
        self.assert_chain(["A", "B", "C"])
        y.cfg["y"] = 900                                                                 # remove the blocker
        y.top.geometry(f"+{y.cfg['x']}+900")
        self.assertTrue(self.app.drop_snap(a))
        self.assertEqual((a.cfg["x"], a.cfg["y"]), (598, 100))
        self.assert_chain(["A", "B", "C"])

    def test_result_never_overlaps_any_panel(self):
        """Brute force over many drop positions: whenever something snaps, the dropped panel ends up free."""
        ps = self.mk(["A", "B", "C", "D", "E"])
        self.place(ps[0], 100, 100)
        self.place(ps[1], 100 + 300 + GAP, 100, h=60)
        self.place(ps[2], 100 + 300 + GAP, 200, h=80)
        self.place(ps[3], 100, 400, w=200, h=90)
        d = ps[4]
        snapped, bad = 0, []
        for x in range(60, 760, 37):
            for y in range(60, 560, 29):
                self.app.cfg["stacks"] = []
                self.place(d, x, y, w=250, h=120)
                if not self.app.drop_snap(d):
                    continue
                snapped += 1
                self.app.relayout_all()
                r = (d.cfg["x"], d.cfg["y"], d.cur_w, d.cur_h)
                for p in ps[:4]:
                    if stack.rects_collide(r, (p.cfg["x"], p.cfg["y"], p.cur_w, p.cur_h)):
                        bad.append((x, y, p.name))
        self.assertGreater(snapped, 5)                                                   # the grid does exercise snapping
        self.assertEqual(bad, [])


class TestSnapPreview(Base):
    """Step 7b-2: while dragging, a frame shows where the panel would land and the target's edge is highlighted."""

    place = TestSideSnap.place

    def grab(self, p):
        self.sx, self.sy = p.cfg["x"], p.cfg["y"]
        self.gx, self.gy = self.sx + 40, self.sy + 8
        p._head_press(ev(self.gx, self.gy, 40))

    def move(self, p, nx, ny):
        p._head_motion(ev(self.gx + nx - self.sx, self.gy + ny - self.sy, 40))
        pump(self.app, n=3)

    def let_go(self, p, nx, ny):
        p._head_release(ev(self.gx + nx - self.sx, self.gy + ny - self.sy, 40))
        pump(self.app, n=3)

    def shown(self):
        return self.app._preview_shown

    def ghost_visible(self):
        return self.app.preview_visible()

    def actual(self, *panels):
        return [(p.cfg["x"], p.cfg["y"], p.cur_w, p.cur_h) for p in panels]

    def scene_ab(self):
        a, d = self.mk(["A", "D"])
        self.place(a, 100, 100)
        self.place(d, 900, 500, w=250, h=120)
        return a, d

    # ---- preview position == drop position
    def test_below_preview_is_where_the_drop_lands(self):
        a, d = self.scene_ab()
        self.grab(d)
        self.move(d, 110, 100 + a.cur_h + GAP + 10)                                      # 10 px off the spot under A
        under = 100 + a.cur_h + GAP
        self.assertEqual(self.shown()["rects"], [(100, under, 300, 120)])               # A's left edge and width
        self.assertEqual(self.shown()["edge"], (100, 100 + a.cur_h, 400, 100 + a.cur_h))   # A's bottom edge
        self.assertTrue(self.ghost_visible())
        preview = list(self.shown()["rects"])
        self.let_go(d, 110, 100 + a.cur_h + GAP + 10)
        self.assertEqual(self.actual(d), preview)                                        # it sat down exactly there
        self.assertEqual(self.app.cfg["stacks"], [["A", "D"]])
        self.assertFalse(self.ghost_visible())

    def test_side_preview_is_where_the_drop_lands(self):
        a, d = self.scene_ab()
        for side, nx, edge in (("right", 100 + 300 + GAP + 9, (400, 100, 400, 100 + a.cur_h)),
                               ("left", 100 - GAP - 250 - 9, (100, 100, 100, 100 + a.cur_h))):
            self.place(d, 900, 500)
            self.grab(d)
            self.move(d, nx, 100 + 25)
            self.assertEqual(self.shown()["rects"], [(nx - (9 if side == "right" else -9), 100, 250, 120)], side)
            self.assertEqual(self.shown()["edge"], edge, side)
            preview = list(self.shown()["rects"])
            self.let_go(d, nx, 100 + 25)
            self.assertEqual(self.actual(d), preview, side)
            self.assertEqual(self.app.cfg["stacks"], [])

    def test_stack_top_preview_shows_the_whole_stack_and_matches_the_drop(self):
        a, b, c, t = self.mk(["A", "B", "C", "T"])
        self.stack_up(a, b, c)
        self.place(t, 900, 300)
        self.grab(a)
        self.move(a, 900 - GAP - 300 + 5, 330)
        rects = list(self.shown()["rects"])
        self.assertEqual(len(rects), 3)                                                  # one frame per panel of the stack
        self.assertEqual(rects[0], (900 - GAP - 300, 300, 300, 200))
        self.assertEqual([r[1] for r in rects], [300, 300 + 200 + GAP, 300 + 2 * (200 + GAP)])
        self.let_go(a, 900 - GAP - 300 + 5, 330)
        self.assertEqual(self.actual(a, b, c), rects)
        self.assertEqual(self.app.cfg["stacks"], [["A", "B", "C"]])

    def test_preview_matches_drop_for_many_positions(self):
        """The same function decides both: for a grid of drop positions, preview rect == final rect (or no preview and
        no snap)."""
        a, b, d = self.mk(["A", "B", "D"])
        self.place(a, 100, 100)
        self.place(b, 560, 100, h=60)                                                    # a closed-looking short panel
        mism = []
        for x in range(40, 760, 61):
            for y in range(40, 520, 47):
                self.app.cfg["stacks"] = []
                self.place(d, 1000, 600, w=250, h=120)
                self.grab(d)
                self.move(d, x, y)
                shown = self.shown()
                preview = list(shown["rects"]) if shown else None
                self.let_go(d, x, y)
                if preview is None:
                    if self.app.cfg["stacks"] or (d.cfg["x"], d.cfg["y"]) not in {(x, y), self.clamped(x, y)}:
                        mism.append((x, y, "snapped without preview"))
                elif self.actual(d) != preview:
                    mism.append((x, y, preview, self.actual(d)))
        self.assertEqual(mism, [])

    def clamped(self, x, y):
        return displays.clamp_head(self.disp.monitors(), x, y, 250, 30)

    # ---- when there is no preview
    def test_no_candidate_no_preview(self):
        a, d = self.scene_ab()
        self.grab(d)
        self.move(d, 700, 700)
        self.assertIsNone(self.shown())
        self.assertFalse(self.ghost_visible())
        self.let_go(d, 700, 700)

    def test_candidate_change_moves_the_frame_and_leaving_removes_it(self):
        a, d = self.scene_ab()
        self.grab(d)
        self.move(d, 100, 100 + a.cur_h + GAP + 4)
        r1 = list(self.shown()["rects"])
        self.move(d, 100 + 300 + GAP + 4, 130)                                           # now the side candidate
        r2 = list(self.shown()["rects"])
        self.assertNotEqual(r1, r2)
        self.assertEqual(r2, [(402, 100, 250, 120)])
        self.move(d, 700, 700)                                                           # no candidate any more
        self.assertIsNone(self.shown())
        self.assertFalse(self.ghost_visible())
        self.let_go(d, 700, 700)

    def test_same_candidate_is_not_redrawn(self):
        a, d = self.scene_ab()
        self.grab(d)
        with mock.patch.object(self.app, "_show_preview", wraps=self.app._show_preview) as sp:
            for dy in (4, 6, 8, 5, 3):                                                   # always the same candidate/spot
                self.move(d, 100 + dy, 100 + a.cur_h + GAP + dy)
            self.assertEqual(sp.call_count, 1)
        self.let_go(d, 100, 100 + a.cur_h + GAP)

    def test_removed_on_release_escape_lock_and_snap_off(self):
        a, d = self.scene_ab()
        spot = (100, 100 + a.cur_h + GAP + 6)
        # release
        self.grab(d)
        self.move(d, *spot)
        self.assertTrue(self.ghost_visible())
        self.let_go(d, *spot)
        self.assertFalse(self.ghost_visible())
        # Esc: the move is cancelled completely (see TestEscCancel); here: preview gone, panel back, nothing snaps
        self.app.cfg["stacks"] = []
        self.place(d, 900, 500)
        self.grab(d)
        self.move(d, *spot)
        self.assertTrue(self.ghost_visible())
        with mock.patch.object(winutil, "esc_down", return_value=True):
            d._esc_check()
        self.assertFalse(self.ghost_visible())
        self.move(d, spot[0] + 3, spot[1] + 1)                                           # button still down: no effect
        self.assertFalse(self.ghost_visible())
        self.let_go(d, spot[0] + 3, spot[1] + 1)
        self.assertEqual(self.app.cfg["stacks"], [])
        self.assertEqual((d.cfg["x"], d.cfg["y"]), (900, 500))
        self.grab(d)                                                                     # the next drag works again
        self.move(d, *spot)
        self.assertTrue(self.ghost_visible())
        self.let_go(d, *spot)
        self.assertEqual(self.app.cfg["stacks"], [["A", "D"]])
        # snap off
        self.app.cfg["stacks"] = []
        self.app.cfg["general"]["snap_enabled"] = False
        self.place(d, 900, 500)
        self.grab(d)
        self.move(d, *spot)
        self.assertFalse(self.ghost_visible())
        self.let_go(d, *spot)
        self.app.cfg["general"]["snap_enabled"] = True
        # locked: a locked panel does not move, so there is nothing to preview and nothing is shown
        self.app.set_lock(True)
        self.place(d, 900, 500)
        self.grab(d)
        d._head_motion(ev(self.gx - 800, self.gy - 400, 40))
        self.assertFalse(self.ghost_visible())
        self.assertIsNone(self.app.drop_plan(d))
        self.let_go(d, 900, 500)
        self.assertFalse(self.ghost_visible())

    def test_preview_setting_off_hides_it_but_snapping_stays(self):
        a, d = self.scene_ab()
        self.app.cfg["general"]["snap_preview"] = False
        self.grab(d)
        self.move(d, 100, 100 + a.cur_h + GAP + 5)
        self.assertFalse(self.ghost_visible())
        self.let_go(d, 100, 100 + a.cur_h + GAP + 5)
        self.assertEqual(self.app.cfg["stacks"], [["A", "D"]])

    # ---- the window itself
    def test_window_is_a_click_through_topmost_frame_with_the_accent(self):
        a, d = self.scene_ab()
        self.grab(d)
        self.move(d, 100, 100 + a.cur_h + GAP + 4)
        g, cv = self.app._ghost, self.app._ghost_cv
        self.assertTrue(g.overrideredirect())
        self.assertTrue(g.attributes("-topmost"))
        self.assertEqual(str(g.attributes("-transparentcolor")), theme.KEY)
        self.assertTrue(winutil.overlay_style_ok(g))                                     # no taskbar, no focus, mouse goes through
        bx, by, bw, bh = self.shown()["box"]
        self.assertEqual((g.winfo_x(), g.winfo_y(), g.winfo_width(), g.winfo_height()), (bx, by, bw, bh))
        rects = [i for i in cv.find_all() if cv.type(i) == "rectangle"]
        lines = [i for i in cv.find_all() if cv.type(i) == "line"]
        self.assertEqual((len(rects), len(lines)), (1, 1))
        for i in rects + lines:
            self.assertEqual(float(cv.itemcget(i, "width")), 2.0)
        self.assertEqual(cv.itemcget(rects[0], "outline").lower(), theme.ACCENT)
        self.assertEqual(cv.itemcget(rects[0], "fill"), "")                              # empty inside
        self.assertEqual(cv.itemcget(lines[0], "fill").lower(), theme.ACCENT)
        self.let_go(d, 100, 100 + a.cur_h + GAP + 4)

    def test_target_panel_is_never_changed(self):
        import copy
        a, d = self.scene_ab()
        before = copy.deepcopy(a.cfg)
        self.grab(d)
        self.move(d, 100, 100 + a.cur_h + GAP + 4)
        self.assertEqual(a.cfg, before)                                                  # highlight is only the overlay line
        self.assertEqual((a.top.attributes("-alpha"), a.cur_w, a.cur_h), (a.cfg["opacity"], 300, 200))
        self.move(d, 700, 700)
        self.assertEqual(a.cfg, before)
        self.let_go(d, 700, 700)
        self.assertEqual(a.cfg, before)
        self.assertFalse(self.ghost_visible())

    # ---- cost
    def test_cost_per_move_with_17_panels(self):
        *ps, d = self.mk(["P%02d" % i for i in range(17)] + ["D"], h=120)      # one call: mk() parks earlier panels
        for i, p in enumerate(ps):                                                       # a grid of free panels
            self.place(p, 60 + (i % 6) * 330, 40 + (i // 6) * 300)
        self.place(d, 2200, 900, w=250, h=120)
        target = ps[0]
        under = target.cfg["y"] + target.cur_h + GAP
        n = 60
        # (a) same candidate: the decision is computed every move, nothing is redrawn
        self.grab(d)
        t0 = time.perf_counter()
        for i in range(n):
            self.place(d, target.cfg["x"] + 3, under + 2 + i % 3)
            self.app.update_preview(d)
            self.app.root.update_idletasks()
            self.assertIsNotNone(self.shown(), i)
        same = (time.perf_counter() - t0) * 1000 / n
        # (b) worst case: the candidate changes on every move (redraw + window move)
        spots = [(target.cfg["x"] + 3, under + 2), (ps[1].cfg["x"] + 3, ps[1].cfg["y"] + ps[1].cur_h + GAP + 2)]
        t0 = time.perf_counter()
        for i in range(n):
            self.place(d, *spots[i % 2])
            self.app.update_preview(d)
            self.app.root.update_idletasks()
            self.assertIsNotNone(self.shown(), i)
        changing = (time.perf_counter() - t0) * 1000 / n
        print("\n  preview with 17 panels: %.2f ms per move (same candidate), %.2f ms (candidate changes every move)"
              % (same, changing))
        self.assertLess(same, 5.0)
        self.assertLess(changing, 10.0)
        self.let_go(d, 700, 700)


class TestPreviewSetting(Base):
    def setUp(self):
        super().setUp()
        self.ps = self.mk(["A", "B"])
        self.app.open_settings("A")
        pump(self.app)
        self.S = self.app.settings_win

    def test_checkbox_default_on_apply_rule_and_persistence(self):
        S, g = self.S, self.app.cfg["general"]
        self.assertTrue(g["snap_preview"])
        self.assertEqual(S.cb_snap_prev.cget("text"), "Preview")
        self.assertTrue(S.v_snap_prev.get())
        self.assertFalse(S.dirty())
        S.v_snap_prev.set(False)
        self.assertTrue(S.dirty())
        self.assertTrue(g["snap_preview"])                                               # nothing changes before Apply
        S.apply()
        self.assertFalse(g["snap_preview"])
        self.assertFalse(S.dirty())
        with open(self.app.config_path, encoding="utf-8") as f:
            self.assertIs(json.load(f)["general"]["snap_preview"], False)
        self.app.quit()
        app2 = self.open_app()
        self.assertIs(app2.cfg["general"]["snap_preview"], False)                        # kept after a restart

    def test_one_row_with_the_other_snapping_controls(self):
        S = self.S
        S.win.update()
        S.nb.select(S.tab["general"])
        S.win.update()
        ys = {w.winfo_y() for w in (S.cb_snap, S.cb_snap_prev, S.sp_snap_dist, S.sp_stack_gap)}
        self.assertEqual(len(ys), 1)

    def test_make_default_revert_factory_follow_the_snapping_rule(self):
        S, g = self.S, self.app.cfg["general"]
        S.v_snap_prev.set(False)
        S.make_default()
        with open(self.app.defaults_path, encoding="utf-8") as f:
            self.assertIs(json.load(f)[mpanels.SNAPPING_KEY]["snap_preview"], False)
        g["snap_preview"] = True
        S._load_general()
        with mock.patch.object(S, "confirm_overwrite", return_value=True):
            S.reset(False)                                                               # Revert: loaded into the box only
        self.assertIs(g["snap_preview"], True)
        self.assertIs(S.v_snap_prev.get(), False)
        self.assertTrue(S.dirty())
        S.apply()
        self.assertIs(g["snap_preview"], False)
        with mock.patch.object(S, "confirm_overwrite", return_value=True):
            S.reset(True)                                                                # Factory: built-in = on
        self.assertIs(g["snap_preview"], False)
        self.assertIs(S.v_snap_prev.get(), True)
        S.apply()
        self.assertIs(g["snap_preview"], True)

    def test_garbage_value_is_sanitized(self):
        self.assertIs(stack.sanitize_general({"snap_preview": "no"})["snap_preview"], True)
        self.assertIs(stack.sanitize_general({"snap_preview": False})["snap_preview"], False)
        self.assertIs(stack.sanitize_general({})["snap_preview"], True)


class TestPlanRects(unittest.TestCase):
    def test_rects_and_edges(self):
        rect_of = {"A": ("A", 100, 100, 300, 200)}
        d = ("D", 0, 0, 250, 120)
        self.assertEqual(stack.plan_rects(("below", "A"), d, None, rect_of, 2), ([(100, 302, 300, 120)], (100, 300, 400, 300)))
        self.assertEqual(stack.plan_rects(("side", "A", 402, 100), d, None, rect_of, 2), ([(402, 100, 250, 120)], (400, 100, 400, 300)))
        self.assertEqual(stack.plan_rects(("side", "A", -152, 100), d, None, rect_of, 2), ([(-152, 100, 250, 120)], (100, 100, 100, 300)))
        group = [(0, 0, 250, 120), (0, 122, 250, 50)]                                    # a stack: members move together
        self.assertEqual(stack.plan_rects(("side", "A", 402, 100), d, group, rect_of, 2)[0],
                         [(402, 100, 250, 120), (402, 222, 250, 50)])


@unittest.skipUnless(calendar_panel.AVAILABLE, "calendar libraries not installed")
class TestSettingsFromTray(Base):
    """Settings opened from the tray (no panel named): the panel picker is there, the first panel is selected, and
    choosing a Calendar panel brings the Calendar tab."""

    def tabs(self, S):
        return [S.nb.tab(t, "text") for t in S.nb.tabs()]

    def test_picker_first_panel_and_calendar_tab_on_selection(self):
        self.app.new_panel("Zed Cal", "calendar")
        self.app.new_panel("Alpha")
        pump(self.app)
        self.app.open_settings()                                                         # what the tray menu does
        pump(self.app)
        S = self.app.settings_win
        self.assertTrue(S.cb_panel.winfo_ismapped())                                     # the "Panel" picker is visible
        self.assertEqual(list(S.cb_panel["values"]), list(self.app.panels))
        self.assertEqual(S.cur, next(iter(self.app.panels)))                             # the first panel is selected
        self.assertEqual(S.v["panel"].get(), S.cur)
        self.assertNotIn("Calendar", self.tabs(S))                                       # it is a shortcut panel
        S.cb_panel.set("Zed Cal")
        S.cb_panel.event_generate("<<ComboboxSelected>>")
        pump(self.app)
        self.assertEqual(S.cur, "Zed Cal")
        self.assertIn("Calendar", self.tabs(S))
        S.cb_panel.set("Alpha")
        S.cb_panel.event_generate("<<ComboboxSelected>>")
        pump(self.app)
        self.assertNotIn("Calendar", self.tabs(S))                                       # back to a shortcut panel

    def test_switching_panel_with_unapplied_edit_asks(self):
        self.app.new_panel("Zed Cal", "calendar")
        pump(self.app)
        self.app.open_settings()
        pump(self.app)
        S = self.app.settings_win
        S.v["name"].set("Renamed")                                                       # unapplied edit
        asked = []
        S.ask_unsaved = lambda: asked.append(1) or "cancel"
        S.request_select("Zed Cal")
        self.assertEqual(asked, [1])
        self.assertEqual(S.cur, "General")                                               # Cancel: stays
        self.assertEqual(S.v["panel"].get(), "General")
        S.ask_unsaved = lambda: "discard"
        S.request_select("Zed Cal")
        self.assertEqual(S.cur, "Zed Cal")
        self.assertIn("Calendar", self.tabs(S))

    def test_open_again_from_tray_keeps_the_selected_panel(self):
        self.app.new_panel("Zed Cal", "calendar")
        pump(self.app)
        self.app.open_settings("Zed Cal")
        pump(self.app)
        self.app.open_settings()                                                         # tray again: no name, no change
        self.assertEqual(self.app.settings_win.cur, "Zed Cal")


@unittest.skipUnless(calendar_panel.AVAILABLE, "calendar libraries not installed")
class TestCalendarWidth(Base):
    def test_stack_width_wins_and_widths_survive(self):
        a = self.mk(["A"])[0]
        cp = self.app.new_panel("Cal", "calendar")
        cp.cfg.update(x=100, y=700, h=300)
        cp.cfg["calendar"]["view"] = "week"
        cp.cfg["calendar"]["widths"] = {"week": 520}
        cp.cfg["w"] = 520
        cp.apply_cfg()
        pump(self.app)
        self.assertEqual(cp.cfg["w"], 520)                                               # free: its own per-view width
        self.stack_up(a, cp)
        self.assertEqual((cp.cfg["w"], cp.cur_w), (300, 300))                            # in a stack: the stack width
        cp.cal_view_changed("week")                                                      # view changes do not touch widths
        self.assertEqual(cp.cfg["calendar"]["widths"], {"week": 520})
        cp.resizing, cp.press = True, (0, 0, None)
        cp._body_drag(ev(30, 0))                                                         # resizing in a stack: stack width, not widths
        self.assertEqual({a.cfg["w"], cp.cfg["w"]}, {330})
        self.assertEqual(cp.cfg["calendar"]["widths"], {"week": 520})
        cp.resizing = False
        self.drag(cp, 700, 100)                                                          # leaves the stack
        self.assertEqual(self.app.cfg["stacks"], [])
        self.assertEqual((cp.cfg["w"], cp.cur_w), (520, 520))                            # back to its own width
        self.assertEqual(cp.cfg["calendar"]["widths"], {"week": 520})

    def test_settings_note_in_calendar_tab(self):
        cp = self.app.new_panel("Cal", "calendar")
        self.app.open_settings("Cal")
        pump(self.app)
        S = self.app.settings_win
        self.assertEqual(S.lbl_cal_stack_note.cget("text"), "In a stack: stack width is used")


class TestDropFix(Base):
    """v1.1 step 7b-3: dropping a panel must really seat its WINDOW on the previewed rectangle, on the real event path
    (press -> motion ... -> release), also for a panel that was in a stack before.

    Found with the real mouse (SendInput): a panel pulled out of a stack and dropped back near its old slot got its
    stack entry and cfg position right, but the window stayed where it was dropped, because relayout skips a move when
    PanelWin._shown_xy already equals the target and the drag moved the window without updating _shown_xy."""

    place = TestSideSnap.place

    def grab(self, p):
        self.sx, self.sy = p.cfg["x"], p.cfg["y"]
        self.gx, self.gy = self.sx + 40, self.sy + 8
        p._head_press(ev(self.gx, self.gy, 40))

    def move(self, p, nx, ny):
        p._head_motion(ev(self.gx + nx - self.sx, self.gy + ny - self.sy, 40))
        pump(self.app, n=3)

    def let_go(self, p, nx, ny):
        p._head_release(ev(self.gx + nx - self.sx, self.gy + ny - self.sy, 40))
        pump(self.app, n=3)

    def scene(self):
        a, d = self.mk(["A", "D"])
        self.place(a, 100, 100)
        self.place(d, 900, 500, w=250, h=120)
        return a, d

    def window(self, p):
        return p.top.winfo_x(), p.top.winfo_y()

    def assert_seated(self, p):
        """cfg, the memory of where the window is, and the real window all agree."""
        self.assertEqual(self.window(p), (p.cfg["x"], p.cfg["y"]))
        self.assertEqual(p._shown_xy, (p.cfg["x"], p.cfg["y"]))

    # ---- the bug found with the real mouse
    def test_dropped_back_near_the_old_slot_the_window_sits_on_the_preview(self):
        a, d = self.scene()
        slot = (100, 100 + a.cur_h + GAP)
        self.grab(d)
        self.move(d, slot[0] + 10, slot[1] + 10)
        self.let_go(d, slot[0] + 10, slot[1] + 10)
        self.assertEqual(self.app.cfg["stacks"], [["A", "D"]])
        self.assertEqual(self.window(d), slot)
        # second drag: pull it out of the stack (> 24 px), then bring it back near the same slot and drop
        self.grab(d)
        self.move(d, slot[0] + 300, slot[1] + 150)
        self.assertEqual(self.app.cfg["stacks"], [])
        self.move(d, slot[0] + 5, slot[1] + 12)
        want = list(self.app._preview_shown["rects"])
        self.assertEqual(want[0][:2], slot)
        self.let_go(d, slot[0] + 5, slot[1] + 12)
        self.assertEqual(self.app.cfg["stacks"], [["A", "D"]])
        self.assertEqual(self.window(d), slot)                                           # the WINDOW, not only cfg
        self.assert_seated(d)
        self.assertEqual([(*self.window(d), d.top.winfo_width(), d.top.winfo_height())], want)

    def test_window_and_memory_agree_after_every_kind_of_drop(self):
        a, d = self.scene()
        under = 100 + a.cur_h + GAP
        for case, spot in (("below", (110, under + 9)), ("side", (100 + 300 + GAP + 7, 130)), ("nothing", (700, 700))):
            self.app.cfg["stacks"] = []
            self.place(d, 900, 500, w=250, h=120)
            d._shown_xy = (900, 500)
            self.grab(d)
            self.move(d, *spot)
            self.let_go(d, *spot)
            self.assert_seated(d)
            if case == "nothing":
                self.assertEqual((d.cfg["x"], d.cfg["y"]), spot)
        # a held member dropped within the snap distance of its slot goes back: window == slot
        self.stack_up(a, d)
        self.grab(d)
        slot = (d.cfg["x"], d.cfg["y"])
        self.move(d, slot[0] + 10, slot[1] + 6)
        self.let_go(d, slot[0] + 10, slot[1] + 6)
        self.assertEqual(self.window(d), slot)
        self.assert_seated(d)

    # ---- the real event order, with the preview showing
    def test_release_with_the_preview_showing_seats_the_panel_below_beside_and_stack_top(self):
        a, d, t1, t2 = self.mk(["A", "D", "T1", "T2"])
        self.place(a, 100, 100)
        self.place(d, 900, 500, w=250, h=120)
        self.place(t1, 900, 800)
        self.place(t2, 900, 1000)
        self.stack_up(t1, t2)
        for who, spot in ((d, (110, 100 + a.cur_h + GAP + 8)), (d, (100 + 300 + GAP + 6, 150)), (t1, (100 + 300 + GAP + 4, 120))):
            self.app.cfg["stacks"] = [["T1", "T2"]]
            self.place(d, 900, 500, w=250, h=120)
            if who is t1:
                self.place(d, 1500, 900)                                 # out of the way of the stack top's side candidate
            self.grab(who)
            self.move(who, *spot)
            self.assertTrue(self.app.preview_visible())
            want = list(self.app._preview_shown["rects"])
            seen = []
            real = self.app.drop_snap

            def spy(panel, *a_, **k_):
                seen.append(self.app.preview_visible())              # the preview is still there when the drop is applied
                return real(panel, *a_, **k_)
            with mock.patch.object(self.app, "drop_snap", spy):
                self.let_go(who, *spot)
            self.assertEqual(seen, [True])
            group = [who] if who is d else [t1, t2]
            self.assertEqual(self.actual_win(group), want)
            self.assertFalse(self.app.preview_visible())
            self.assertIsNone(self.app._drag_plan)
            self.assertIsNone(who.moving)

    def actual_win(self, ps):
        return [(*self.window(p), p.top.winfo_width(), p.top.winfo_height()) for p in ps]

    def test_the_drop_applies_exactly_the_stored_candidate(self):
        a, d = self.scene()
        spot = (110, 100 + a.cur_h + GAP + 8)
        self.grab(d)
        self.move(d, *spot)
        want = list(self.app._preview_shown["rects"])
        with mock.patch.object(self.app, "drop_plan", side_effect=AssertionError("must not decide again")):
            self.let_go(d, *spot)
        self.assertEqual(self.actual_win([d]), want)
        self.assertEqual(self.app.cfg["stacks"], [["A", "D"]])

    def test_with_the_preview_off_the_same_candidate_is_applied(self):
        a, d = self.scene()
        self.app.cfg["general"]["snap_preview"] = False
        spot = (110, 100 + a.cur_h + GAP + 8)
        self.grab(d)
        self.move(d, *spot)
        self.assertFalse(self.app.preview_visible())                                     # not drawn ...
        self.assertEqual(self.app._drag_plan[1]["res"], ("below", "A"))                  # ... but the candidate exists
        with mock.patch.object(self.app, "drop_plan", side_effect=AssertionError("must not decide again")):
            self.let_go(d, *spot)
        self.assertEqual(self.window(d), (100, 100 + a.cur_h + GAP))
        self.assertEqual(self.app.cfg["stacks"], [["A", "D"]])

    def test_clamp_only_when_nothing_snapped(self):
        a, d = self.scene()
        self.grab(d)
        self.move(d, 100 + 300 + GAP + 6, 150)                                           # side candidate
        with mock.patch.object(d, "clamp") as clamp:
            self.let_go(d, 100 + 300 + GAP + 6, 150)
        clamp.assert_not_called()
        self.place(d, 900, 500)
        self.grab(d)
        self.move(d, 700, 700)                                                           # no candidate
        with mock.patch.object(d, "clamp") as clamp:
            self.let_go(d, 700, 700)
        clamp.assert_called_once()

    # ---- the preview window: created once, Win32 only
    def test_preview_window_is_created_once_and_never_deiconified_lifted_or_focused(self):
        a, d = self.scene()
        g = self.app._ghost
        self.assertIsNotNone(g)                                                          # exists before any drag
        self.assertFalse(self.app.preview_visible())
        calls = []
        for name in ("deiconify", "lift", "focus_force", "focus_set", "withdraw", "wm_deiconify"):
            setattr(g, name, lambda *a_, _n=name, **k: calls.append(_n))                  # instance-level spies
        shows = []
        real = winutil.overlay_show
        with mock.patch.object(winutil, "overlay_show", lambda *a_: (shows.append(a_[1:]), real(*a_))[1]):
            for spot in ((110, 100 + a.cur_h + GAP + 8), (100 + 300 + GAP + 6, 150), (700, 700)):
                self.app.cfg["stacks"] = []
                self.place(d, 900, 500)
                self.grab(d)
                self.move(d, *spot)
                self.let_go(d, *spot)
        self.assertIs(self.app._ghost, g)
        self.assertEqual(calls, [])
        self.assertGreaterEqual(len(shows), 2)
        self.assertTrue(winutil.overlay_style_ok(g))

    # ---- GetAsyncKeyState: only the "down now" bit counts
    def test_key_state_bit_mask(self):
        def state(value):
            return mock.patch.object(winutil, "_key_state", lambda vk: value)
        with state(0x0001):                                                              # only "pressed since last call"
            self.assertFalse(winutil.esc_down())
            self.assertFalse(winutil._is_down(0x01))
        with state(0x8000):
            self.assertTrue(winutil.esc_down())
        with state(0x8001):
            self.assertTrue(winutil.esc_down())
        with state(0):
            self.assertFalse(winutil.esc_down())

    def test_a_stale_escape_bit_does_not_cancel_the_drag_but_a_held_escape_does(self):
        a, d = self.scene()
        spot = (110, 100 + a.cur_h + GAP + 8)
        stale = lambda vk: 0x0001 if vk == 0x1B else 0x8000          # Esc pressed earlier (low bit), not now; button down
        with mock.patch.object(winutil, "_key_state", stale):
            self.btn.stop()
            self.grab(d)
            self.move(d, *spot)
            d._esc_check()
            self.assertFalse(d._aborted)
            self.assertTrue(self.app.preview_visible())
            self.let_go(d, *spot)
        self.assertEqual(self.app.cfg["stacks"], [["A", "D"]])
        self.app.cfg["stacks"] = []
        self.place(d, 900, 500)
        held = lambda vk: 0x8000                                      # Esc really down (and the button)
        with mock.patch.object(winutil, "_key_state", held):
            self.grab(d)
            self.move(d, *spot)
            d._esc_check()
            self.assertTrue(d._aborted)
            self.assertFalse(self.app.preview_visible())
            self.let_go(d, *spot)
        self.assertEqual(self.app.cfg["stacks"], [])
        self.btn.start()

    # ---- a release that never arrives
    def test_lost_release_is_ended_by_the_timer_with_the_stored_candidate(self):
        a, d = self.scene()
        spot = (110, 100 + a.cur_h + GAP + 8)
        self.grab(d)
        self.move(d, *spot)
        want = list(self.app._preview_shown["rects"])
        self.assertTrue(self.app.preview_visible())
        self.btn.stop()
        with mock.patch.object(winutil, "_key_state", lambda vk: 0):                    # the button is up, no release came
            d._esc_check()
        self.btn.start()
        pump(self.app, n=3)
        self.assertIsNone(d.moving)
        self.assertEqual(self.actual_win([d]), want)
        self.assertEqual(self.app.cfg["stacks"], [["A", "D"]])
        self.assertFalse(self.app.preview_visible())
        self.assertIsNone(d._esc_job)
        d._head_release(ev(0, 0, 40))                                                    # the late real release: harmless
        self.assertEqual(self.actual_win([d]), want)
        self.assertEqual(self.app.cfg["stacks"], [["A", "D"]])

    def test_lost_release_is_ended_by_the_next_motion(self):
        a, d = self.scene()
        spot = (110, 100 + a.cur_h + GAP + 8)
        self.grab(d)
        self.move(d, *spot)
        want = list(self.app._preview_shown["rects"])
        self.btn.stop()
        with mock.patch.object(winutil, "_key_state", lambda vk: 0):
            self.move(d, spot[0] + 200, spot[1] + 90)                                    # pointer moves on, button is up
        self.btn.start()
        self.assertIsNone(d.moving)
        self.assertEqual(self.actual_win([d]), want)                                     # NOT dragged along: it sat down
        self.assertEqual(self.app.cfg["stacks"], [["A", "D"]])
        self.assertFalse(self.app.preview_visible())

    def test_lost_release_with_no_candidate_leaves_the_panel_and_clears_the_state(self):
        a, d = self.scene()
        self.grab(d)
        self.move(d, 700, 700)
        self.btn.stop()
        with mock.patch.object(winutil, "_key_state", lambda vk: 0):
            d._esc_check()
        self.btn.start()
        pump(self.app, n=3)
        self.assertIsNone(d.moving)
        self.assertEqual(self.app.cfg["stacks"], [])
        self.assertEqual(self.window(d), (700, 700))

    def test_drag_state_never_reaches_the_next_click(self):
        a, d = self.scene()
        spot = (110, 100 + a.cur_h + GAP + 8)
        self.grab(d)
        self.move(d, *spot)
        # the release is lost and the timer has not run yet: the next press finishes the old drag first
        self.grab_again = (d.cfg["x"] + 40, d.cfg["y"] + 8)
        d._head_press(ev(*self.grab_again, 40))
        self.assertEqual(self.app.cfg["stacks"], [["A", "D"]])
        self.assertFalse(d.moving[3])                                                    # a fresh press, not a drag
        self.assertIsNone(self.app._drag_plan)
        before = (d.cfg["x"], d.cfg["y"], dict(d.cfg))
        d._head_release(ev(*self.grab_again, 40))                                        # that click's release: no snapping
        self.assertEqual(self.app.cfg["stacks"], [["A", "D"]])
        self.assertEqual((d.cfg["x"], d.cfg["y"]), before[:2])

    def test_double_click_on_the_header_applies_no_snap(self):
        a, d = self.scene()
        # park D close to a candidate, but dropped with Esc so it did not snap
        spot = (110, 100 + a.cur_h + GAP + 8)
        self.grab(d)
        self.move(d, *spot)
        d.cancel_drag()
        self.let_go(d, *spot)
        self.assertEqual(self.app.cfg["stacks"], [])
        pos = (d.cfg["x"], d.cfg["y"])
        x, y = pos[0] + 120, pos[1] + 8                                                  # on the title, away from both ends
        for _ in range(2):                                                               # press, release, press, release
            d._head_press(ev(x, y, 120))
            d._head_release(ev(x, y, 120))
        pump(self.app)
        self.assertEqual(self.app.cfg["stacks"], [])
        self.assertEqual((d.cfg["x"], d.cfg["y"]), pos)
        self.assertEqual(self.window(d), pos)
        self.assertIsNone(d.moving)
        self.assertIsNone(self.app._drag_plan)
        self.assertFalse(self.app.preview_visible())


class TestEscCancel(Base):
    """Esc during a header drag cancels the MOVE completely (like Windows): the layout taken at the press is put back
    (cfg, stacks, the real windows); with the button still down, moves and the release do nothing."""

    place = TestSideSnap.place
    grab, move, let_go = TestDropFix.grab, TestDropFix.move, TestDropFix.let_go
    window = TestDropFix.window

    def state(self):
        return {"stacks": [list(s) for s in self.app.cfg["stacks"]],
                "cfg": {n: (p.cfg["x"], p.cfg["y"], p.cfg["w"]) for n, p in self.app.panels.items()},
                "win": {n: (p.top.winfo_x(), p.top.winfo_y(), p.top.winfo_width(), p.top.winfo_height())
                        for n, p in self.app.panels.items()}}

    def esc(self, p):
        with mock.patch.object(winutil, "esc_down", return_value=True):
            p._esc_check()
        pump(self.app, n=3)

    def saved(self):
        with open(self.app.config_path, encoding="utf-8") as f:
            return json.load(f)

    def assert_cancelled_cleanly(self, p, before, far):
        self.assertEqual(self.state(), before)                                           # cfg, stacks AND real windows
        self.assertFalse(self.app.preview_visible())
        self.assertIsNone(self.app._drag_plan)
        self.move(p, *far)                                                               # button still down: no effect
        self.assertEqual(self.state(), before)
        self.let_go(p, *far)                                                             # release: nothing at all
        self.assertEqual(self.state(), before)
        self.assertIsNone(p.moving)
        self.assertFalse(self.app.preview_visible())

    def test_single_panel(self):
        a, d = self.mk(["A", "D"])
        self.place(a, 100, 100)
        self.place(d, 900, 500, w=250, h=120)
        pump(self.app)
        self.app.save()
        saved = self.saved()
        before = self.state()
        self.grab(d)
        self.move(d, 700, 400)
        self.assertNotEqual(self.window(d), (900, 500))
        self.esc(d)
        self.assert_cancelled_cleanly(d, before, (50, 50))
        self.assertEqual(self.saved(), saved)                                            # config identical to before the press

    def test_stack_top_takes_the_whole_stack_back(self):
        a, b, c = self.mk(["A", "B", "C"])
        self.stack_up(a, b, c)
        pump(self.app)
        before = self.state()
        self.grab(a)
        self.move(a, 600, 500)
        self.assertNotEqual(self.window(b), before["win"]["B"][:2])                      # B followed
        self.esc(a)
        self.assert_cancelled_cleanly(a, before, (30, 30))

    def test_middle_panel_pulled_out_goes_back_into_the_stack(self):
        a, b, c = self.mk(["A", "B", "C"])
        self.stack_up(a, b, c)
        pump(self.app)
        before = self.state()
        self.grab(b)
        self.move(b, b.cfg["x"] + 300, b.cfg["y"] + 150)
        self.assertEqual(self.app.cfg["stacks"], [["A", "C"]])                           # it left, C moved up
        self.esc(b)
        self.assertEqual(self.app.cfg["stacks"], [["A", "B", "C"]])
        self.assert_cancelled_cleanly(b, before, (40, 40))

    def test_bottom_panel_held_but_not_yet_pulled_out(self):
        a, b = self.mk(["A", "B"])
        self.stack_up(a, b)
        pump(self.app)
        before = self.state()
        self.grab(b)
        self.move(b, b.cfg["x"] + 10, b.cfg["y"] + 5)
        self.esc(b)
        self.assert_cancelled_cleanly(b, before, (40, 40))

    def test_preview_showing_below_and_beside_then_esc(self):
        a, d = self.mk(["A", "D"])
        self.place(a, 100, 100)
        for spot in ((110, 100 + a.cur_h + GAP + 8), (100 + 300 + GAP + 6, 150)):
            self.app.cfg["stacks"] = []
            self.place(d, 900, 500, w=250, h=120)
            pump(self.app)
            before = self.state()
            self.grab(d)
            self.move(d, *spot)
            self.assertTrue(self.app.preview_visible())
            self.esc(d)
            self.assertFalse(self.app.preview_visible())
            self.assert_cancelled_cleanly(d, before, spot)
            self.assertEqual(self.app.cfg["stacks"], [])

    def test_stack_top_with_preview_then_esc(self):
        a, t1, t2 = self.mk(["A", "T1", "T2"])
        self.place(a, 100, 100)
        self.place(t1, 900, 500)
        self.stack_up(t1, t2)
        pump(self.app)
        before = self.state()
        self.grab(t1)
        self.move(t1, 100 + 300 + GAP + 4, 120)
        self.assertTrue(self.app.preview_visible())
        self.esc(t1)
        self.assert_cancelled_cleanly(t1, before, (100 + 300 + GAP + 4, 120))

    def test_a_new_press_after_esc_is_a_normal_drag(self):
        a, d = self.mk(["A", "D"])
        self.place(a, 100, 100)
        self.place(d, 900, 500, w=250, h=120)
        spot = (110, 100 + a.cur_h + GAP + 8)
        self.grab(d)
        self.move(d, *spot)
        self.esc(d)
        self.let_go(d, *spot)
        self.grab(d)                                                                     # new press, same panel
        self.assertFalse(d._aborted)
        self.move(d, *spot)
        self.assertTrue(self.app.preview_visible())                                      # the box comes again
        self.let_go(d, *spot)
        self.assertEqual(self.app.cfg["stacks"], [["A", "D"]])
        self.assertEqual(self.window(d), (100, 100 + a.cur_h + GAP))

    def test_release_after_esc_does_nothing_at_all(self):
        a, d = self.mk(["A", "D"])
        self.place(a, 100, 100)
        self.place(d, 900, 500, w=250, h=120)
        spot = (110, 100 + a.cur_h + GAP + 8)
        self.grab(d)
        self.move(d, *spot)
        self.esc(d)
        with mock.patch.object(d, "clamp") as clamp, mock.patch.object(self.app, "save") as save,                 mock.patch.object(self.app, "drop_snap") as snap, mock.patch.object(self.app, "return_to_slot") as back:
            self.let_go(d, *spot)
        clamp.assert_not_called()
        save.assert_not_called()
        snap.assert_not_called()
        back.assert_not_called()

    def test_esc_without_a_drag_does_nothing(self):
        a, d = self.mk(["A", "D"])
        pump(self.app)
        before = self.state()
        with mock.patch.object(winutil, "esc_down", return_value=True):
            d._esc_check()                                                               # no drag: nothing
            d.cancel_drag()
        pump(self.app, n=3)
        self.assertEqual(self.state(), before)
        x, y = d.cfg["x"] + 40, d.cfg["y"] + 8
        d._head_press(ev(x, y, 40))                                                      # a plain click with Esc held
        with mock.patch.object(winutil, "esc_down", return_value=True):
            d.cancel_drag()                                                              # not dragging yet: ignored
        d._head_release(ev(x, y, 40))
        pump(self.app, n=3)
        self.assertEqual(self.state(), before)

    def test_esc_works_while_locked(self):
        a, d = self.mk(["A", "D"])
        self.place(d, 900, 500, w=250, h=120)
        pump(self.app)
        before = self.state()
        self.grab(d)
        self.move(d, 700, 400)
        self.app.set_lock(True)                                                          # locked in the middle of the drag
        self.esc(d)
        self.assertEqual(self.state(), before)
        self.let_go(d, 700, 400)
        self.assertEqual(self.state(), before)
        self.app.set_lock(False)


if __name__ == "__main__":
    unittest.main()
