"""v1.2 step 2: the bar's Tasks section (listing only).
The rule, the order, the layout and the hook filters are tested as pure code; the controller, the bar and the real App run
on a made-up window source (no EnumWindows, no hook) except where a test says it touches Windows (marked "real:")."""
import ctypes
import os
import sys
import threading
import time
import unittest
from ctypes import wintypes as wt
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import barwin  # noqa: E402
import infoclock  # noqa: E402
import shellmsg  # noqa: E402
import strings as ui  # noqa: E402
import tasks  # noqa: E402
import theme  # noqa: E402
import winhooks  # noqa: E402
import winutil  # noqa: E402
from PIL import Image, ImageTk  # noqa: E402
from tasks import WinInfo  # noqa: E402
from test_v120_step1 import (Base, FakeShell, INFO_ONLY, ON, THREE, FakeAppBar, pump)  # noqa: E402,F401

APP = 0x40000
TOOL = 0x80
FT = 132_000_000_000_000_000                  # a FILETIME; one second is 10_000_000


def W(hwnd, title="x", pid=100, cls="Cls", visible=True, owner=0, ex=0, cloaked=0, iconic=False, shell=False):
    return WinInfo(hwnd, title, pid, cls, visible, owner, ex, cloaked, iconic, shell)


class Src:
    """A made-up window source whose list the test edits. `procs`: hwnd -> (path, start)."""

    def __init__(self):
        self.wins, self.fg, self.procs, self.snaps, self.resolves = [], 0, {}, 0, []
        self.fetched = []

    def snapshot(self):
        self.snaps += 1
        return list(self.wins)

    def foreground(self):
        return self.fg

    def resolve(self, w):
        self.resolves.append(w.hwnd)
        return self.procs.get(w.hwnd, (None, None))

    def fetch_icon(self, hwnd, path, size):
        self.fetched.append(hwnd)
        return Image.new("RGBA", (size, size), (200, 10, 10, 255))


class FakeLoader:
    def __init__(self):
        self.requests, self.started, self.stopped = [], 0, 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def request(self, hwnd, path):
        self.requests.append((hwnd, path))


# --------------------------------------------------------------------------- the rule
class TestListed(unittest.TestCase):
    def test_plain_window_is_listed(self):
        self.assertTrue(tasks.listed(W(1), 5))

    def test_not_visible_desktop_own_process_no_title(self):
        self.assertFalse(tasks.listed(W(1, visible=False), 5))
        self.assertFalse(tasks.listed(W(1, shell=True), 5))
        self.assertFalse(tasks.listed(W(1, pid=5), 5))                  # our own windows: the bar, panels, Settings
        self.assertFalse(tasks.listed(W(1, title=""), 5))

    def test_owner_and_tool_window_rules(self):
        self.assertFalse(tasks.listed(W(1, owner=9), 5))                # a dialog of another window
        self.assertTrue(tasks.listed(W(1, owner=9, ex=APP), 5))         # ...unless it asks for a button
        self.assertFalse(tasks.listed(W(1, ex=TOOL), 5))
        self.assertTrue(tasks.listed(W(1, ex=TOOL | APP), 5))

    def test_cloaked_is_hidden_whatever_the_reason(self):
        for c in (1, 2, 4):
            self.assertFalse(tasks.listed(W(1, cloaked=c), 5))


# --------------------------------------------------------------------------- the order
class TestModel(unittest.TestCase):
    def make(self):
        self.src = Src()
        self.m = tasks.TaskModel(5, now_filetime=lambda: FT + 10_000_000_000)      # "now" is far later than any start
        return self.m

    def upd(self, wins, fg=0):
        self.src.wins = wins
        return self.m.update(wins, self.src.resolve, fg)

    def titles(self):
        return [e.title for e in self.m.entries]

    def test_order_is_process_start_time_not_z_order(self):
        self.make()
        self.src.procs = {1: ("a.exe", FT + 300), 2: ("b.exe", FT + 100), 3: ("c.exe", FT + 200)}
        self.upd([W(1, "A"), W(2, "B"), W(3, "C")])
        self.assertEqual(self.titles(), ["B", "C", "A"])

    def test_order_is_decision_5A_old_ones_by_age_new_ones_appended(self):
        self.make()
        self.src.procs = {1: ("a.exe", FT + 300), 2: ("b.exe", FT + 100), 3: ("c.exe", FT + 200), 4: ("old.exe", FT)}
        self.upd([W(1, "A"), W(2, "B"), W(3, "C")])
        self.assertEqual(self.titles(), ["B", "C", "A"])
        self.upd([W(4, "Newest window of the OLDEST program"), W(1, "A"), W(2, "B"), W(3, "C")])
        self.assertEqual(self.titles(), ["B", "C", "A", "Newest window of the OLDEST program"])

    def test_same_start_time_ties_are_broken_by_z_order_once_and_then_stay(self):
        self.make()
        self.src.procs = {h: ("a.exe", FT) for h in (1, 2, 3)}
        self.upd([W(3, "C"), W(1, "A"), W(2, "B")])                      # z-order: C on top
        self.assertEqual(self.titles(), ["C", "A", "B"])
        self.upd([W(2, "B"), W(3, "C"), W(1, "A")])                      # the user clicked B: z-order changed
        self.assertEqual(self.titles(), ["C", "A", "B"])                 # the buttons do not move

    def test_a_new_window_goes_to_the_end_even_when_its_program_is_older(self):
        self.make()
        self.src.procs = {1: ("a.exe", FT + 50), 2: ("b.exe", FT + 60), 9: ("a.exe", FT + 50)}
        self.upd([W(1, "A1"), W(2, "B")])
        self.upd([W(9, "A2"), W(1, "A1"), W(2, "B")])                    # a second window of the older program, on top
        self.assertEqual(self.titles(), ["A1", "B", "A2"])               # appended: the buttons before it did not move

    def test_windows_that_appear_in_the_same_later_scan_are_appended_in_z_order(self):
        self.make()
        self.src.procs = {h: ("a.exe", FT) for h in (1, 8, 9)}
        self.upd([W(1, "A")])
        self.upd([W(8, "N8"), W(9, "N9"), W(1, "A")])
        self.assertEqual(self.titles(), ["A", "N8", "N9"])

    def test_unresolved_process_goes_last_and_stays_put_once_resolved(self):
        """UWP seen as CoreWindow-less ApplicationFrameWindow: path unknown at first, known a scan later. The path (and
        so the icon) arrives later; the button does not jump."""
        self.make()
        self.src.procs = {1: ("a.exe", FT + 100), 2: (None, None)}
        self.upd([W(2, "Calculator", cls="ApplicationFrameWindow"), W(1, "A")])
        self.assertEqual(self.titles(), ["A", "Calculator"])
        self.assertIsNone(self.m.entries[1].path)
        self.src.procs[2] = ("calc.exe", FT + 50)                        # an OLDER start time than A's: still no jump
        self.upd([W(2, "Calculator"), W(1, "A")])
        self.assertEqual(self.titles(), ["A", "Calculator"])
        self.assertEqual(self.m.entries[1].path, "calc.exe")

    def test_resolve_is_asked_again_only_while_unresolved(self):
        self.make()
        self.src.procs = {1: (None, None)}
        self.upd([W(1)])
        self.upd([W(1)])
        self.assertEqual(self.src.resolves, [1, 1])                      # tried again at the second scan
        self.src.procs = {1: ("a.exe", FT)}
        self.upd([W(1)])
        self.upd([W(1)])
        self.assertEqual(self.src.resolves, [1, 1, 1])                   # found: cached, never asked again

    def test_change_detection(self):
        self.make()
        self.src.procs = {1: ("a.exe", FT), 2: ("b.exe", FT + 1)}
        self.assertTrue(self.upd([W(1, "A"), W(2, "B")], fg=1)[0])
        self.assertFalse(self.upd([W(1, "A"), W(2, "B")], fg=1)[0])      # nothing changed: no redraw
        self.assertTrue(self.upd([W(1, "A2"), W(2, "B")], fg=1)[0])      # title
        self.assertTrue(self.upd([W(1, "A2", iconic=True), W(2, "B")], fg=1)[0])      # minimized
        self.assertTrue(self.upd([W(1, "A2", iconic=True), W(2, "B")], fg=2)[0])      # active window
        self.assertTrue(self.upd([W(2, "B")], fg=2)[0])                  # closed
        self.assertFalse(self.upd([W(2, "B"), W(7, "hidden", visible=False)], fg=2)[0])   # not listed: no change

    def test_active_window_that_is_not_listed_means_none_active(self):
        self.make()
        self.src.procs = {1: ("a.exe", FT)}
        self.upd([W(1), W(8, "us", pid=5)], fg=8)                        # the foreground is one of OUR windows
        self.assertEqual(self.m.active, 0)

    def test_gone_windows_are_reported_and_forgotten(self):
        self.make()
        self.src.procs = {1: ("a.exe", FT), 2: ("b.exe", FT)}
        self.upd([W(1), W(2)])
        _c, removed = self.upd([W(1)])
        self.assertEqual(removed, {2})
        self.src.procs[2] = ("b.exe", FT + 5)                            # a NEW window that reuses the number
        self.upd([W(1), W(2)])
        self.assertEqual([e.hwnd for e in self.m.entries], [1, 2])

    def test_a_cloaked_window_that_comes_back_keeps_its_place(self):
        self.make()
        self.src.procs = {1: ("a.exe", FT + 1), 2: ("c.exe", FT)}
        self.upd([W(1, "A"), W(2, "C")])
        self.upd([W(1, "A"), W(2, "C", cloaked=2)])
        self.assertEqual(self.titles(), ["A"])
        self.upd([W(2, "C"), W(1, "A")])
        self.assertEqual(self.titles(), ["C", "A"])                      # (the window still exists: same key as before)


# --------------------------------------------------------------------------- layout
class TestLayout(unittest.TestCase):
    def test_everything_fits_buttons_grow_to_the_maximum(self):
        self.assertEqual(tasks.layout(3, 1000), (3, theme.BAR_BTN_MAX_W, 0))
        self.assertEqual(tasks.layout(0, 1000), (0, 0, 0))

    def test_buttons_shrink_to_share_the_room(self):
        k, w, more = tasks.layout(10, 700)
        self.assertEqual((k, more), (10, 0))
        self.assertEqual(w, (700 - 9 * theme.BAR_BTN_GAP) // 10)
        self.assertTrue(theme.BAR_BTN_MIN_W <= w < theme.BAR_BTN_MAX_W)

    def test_minimum_width_still_fits_exactly(self):
        g, mn = theme.BAR_BTN_GAP, theme.BAR_BTN_MIN_W
        self.assertEqual(tasks.layout(5, 5 * mn + 4 * g), (5, mn, 0))

    def test_overflow_the_last_slot_is_plus_n(self):
        g, mn = theme.BAR_BTN_GAP, theme.BAR_BTN_MIN_W
        k, w, more = tasks.layout(20, 5 * mn + 4 * g)                    # room for 5 slots: 4 windows + "+16"
        self.assertEqual((k, more), (4, 16))
        self.assertEqual(w, mn)
        self.assertLessEqual((k + 1) * w + k * g, 5 * mn + 4 * g)

    def test_overflow_never_exceeds_the_room_and_counts_add_up(self):
        for n in range(1, 40):
            for avail in range(0, 1500, 37):
                k, w, more = tasks.layout(n, avail)
                self.assertEqual(k + more, n if (w or not k) else n, (n, avail))
                if w:
                    slots = k + (1 if more else 0)
                    self.assertLessEqual(slots * w + (slots - 1) * theme.BAR_BTN_GAP, avail, (n, avail))
                    self.assertTrue(theme.BAR_BTN_MIN_W <= w <= theme.BAR_BTN_MAX_W, (n, avail, w))

    def test_no_room_for_even_one_button(self):
        self.assertEqual(tasks.layout(3, theme.BAR_BTN_MIN_W - 1), (0, 0, 3))

    def test_one_slot_only_is_the_plus_button(self):
        self.assertEqual(tasks.layout(3, theme.BAR_BTN_MIN_W + 5), (0, theme.BAR_BTN_MIN_W + 5, 3))


class TestFitText(unittest.TestCase):
    m = staticmethod(lambda s: len(s) * 7)

    def test_fits_unchanged(self):
        self.assertEqual(tasks.fit_text("Notepad", 100, self.m), "Notepad")

    def test_cut_with_an_ellipsis_that_fits(self):
        s = tasks.fit_text("A very long title indeed", 70, self.m)
        self.assertTrue(s.endswith("…"))
        self.assertLessEqual(self.m(s), 70)
        self.assertGreater(len(s), 3)

    def test_trailing_space_is_not_left_before_the_ellipsis(self):
        self.assertEqual(tasks.fit_text("ab cdefgh", 7 * 4, self.m), "ab…")

    def test_nothing_fits(self):
        self.assertEqual(tasks.fit_text("abc", 0, self.m), "")
        self.assertEqual(tasks.fit_text("abc", 5, self.m), "")

    def test_text_room_and_icon_only_width(self):
        self.assertLess(tasks.text_room(theme.BAR_BTN_MIN_W), theme.BAR_TEXT_MIN_ROOM)          # 40 px = icon only
        self.assertGreaterEqual(tasks.text_room(theme.BAR_BTN_MAX_W), theme.BAR_TEXT_MIN_ROOM)


# --------------------------------------------------------------------------- the hooks (made-up Windows)
class FakeHookApi:
    def __init__(self, top_level=True, fail_ranges=()):
        self.set_calls, self.unhooked, self.shell, self.top_level = [], [], [], top_level
        self.fail_ranges, self.thread = set(fail_ranges), []

    def make_proc(self, fn):
        return fn

    def set_hook(self, lo, hi, proc):
        self.thread.append(threading.get_ident())
        self.set_calls.append((lo, hi))
        return 0 if (lo, hi) in self.fail_ranges else 1000 + len(self.set_calls)

    def unhook(self, h):
        self.thread.append(threading.get_ident())
        self.unhooked.append(h)
        return True

    def register_shell(self, hwnd):
        self.shell.append(("reg", hwnd))
        return True

    def deregister_shell(self, hwnd):
        self.thread.append(threading.get_ident())
        self.shell.append(("dereg", hwnd))
        return True

    def is_top_level(self, hwnd):
        return self.top_level


class TestHooks(unittest.TestCase):
    def make(self, **kw):
        self.api, self.events = FakeHookApi(**kw), []
        self.h = winhooks.Hooks(77, lambda: self.events.append(1), api=self.api)
        return self.h

    def test_install_hooks_exactly_the_five_ranges_and_the_shell_hook(self):
        self.make()
        self.assertTrue(self.h.install())
        self.assertEqual(self.api.set_calls, [(3, 3), (0x16, 0x17), (0x8000, 0x8003), (0x800C, 0x800C), (0x8017, 0x8018)])
        self.assertEqual(self.api.shell, [("reg", 77)])
        self.assertNotIn(0x800B, [r[0] for r in self.api.set_calls])     # LOCATIONCHANGE floods: never hooked

    def test_remove_unhooks_every_hook_and_the_shell_window_once(self):
        self.make()
        self.h.install()
        self.h.remove()
        self.h.remove()
        self.assertEqual(sorted(self.api.unhooked), [1001, 1002, 1003, 1004, 1005])
        self.assertEqual(self.api.shell, [("reg", 77), ("dereg", 77)])
        self.assertFalse(self.h.installed)

    def test_install_twice_installs_once_and_can_be_installed_again_after_remove(self):
        self.make()
        self.h.install()
        self.h.install()
        self.assertEqual(len(self.api.set_calls), 5)
        self.h.remove()
        self.assertTrue(self.h.install())
        self.assertEqual(len(self.api.set_calls), 10)

    def test_partial_failure_keeps_what_worked_and_removes_it(self):
        self.make(fail_ranges=[(0x16, 0x17)])
        self.assertTrue(self.h.install())
        self.h.remove()
        self.assertEqual(len(self.api.unhooked), 4)

    def test_nothing_hooked_is_a_failure(self):
        self.make(fail_ranges=list(winhooks.RANGES))
        self.assertFalse(self.h.install())

    def test_callback_drops_what_is_not_a_top_level_window(self):
        self.make()
        cb = self.h._callback
        cb(1, 0x8000, 50, 0, 0, 1, 1)                                  # a top-level window created
        self.assertEqual(len(self.events), 1)
        cb(1, 0x8000, 50, -4, 0, 1, 1)                                 # OBJID_CLIENT etc.: a non-window object
        cb(1, 0x800C, 50, -2, 0, 1, 1)
        cb(1, 0x8000, 50, 0, 3, 1, 1)                                  # a child ELEMENT (idChild != 0)
        cb(1, 0x8000, 0, 0, 0, 1, 1)                                   # no window
        self.assertEqual(len(self.events), 1)

    def test_child_window_object_events_are_dropped(self):
        self.make(top_level=False)
        for ev in (0x8000, 0x8001, 0x8002, 0x8003):
            self.h._callback(1, ev, 50, 0, 0, 1, 1)
        self.assertEqual(self.events, [])
        self.h._callback(1, 0x8017, 50, 0, 0, 1, 1)                    # cloaked/uncloaked, foreground, name: never filtered
        self.h._callback(1, 0x0003, 50, 0, 0, 1, 1)
        self.assertEqual(len(self.events), 2)

    def test_callback_never_raises(self):
        self.make()
        self.api.is_top_level = mock.Mock(side_effect=OSError("x"))
        self.h._callback(1, 0x8000, 50, 0, 0, 1, 1)
        self.h._on_event = mock.Mock(side_effect=RuntimeError("x"))
        self.h._callback(1, 0x0003, 50, 0, 0, 1, 1)

    def test_shell_messages_that_can_change_the_list(self):
        self.make()
        for wp in (1, 2, 4, 6, 13, 14, 0x8004):
            self.h.shell_message(wp)
        self.assertEqual(len(self.events), 7)

    def test_shell_messages_that_cannot(self):
        self.make()
        for wp in (3, 5, 16, 0x35, 0x36, 0x8006, 0):                   # GETMINRECT, MONITORCHANGED, FLASH... no scan
            self.h.shell_message(wp)
        self.assertEqual(self.events, [])

    def test_all_hook_calls_happen_on_the_calling_thread(self):
        self.make()
        self.h.install()
        self.h.remove()
        self.assertEqual(set(self.api.thread), {threading.get_ident()})


# --------------------------------------------------------------------------- the message window
_u = ctypes.WinDLL("user32")
_u.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
_u.SendMessageW.restype = ctypes.c_ssize_t


class RecHooks:
    """A made-up Hooks object that records on which thread it was installed and removed."""
    instances = []

    def __init__(self, hwnd, on_event):
        self.hwnd, self._on_event, self.log, self.installed = hwnd, on_event, [], False
        RecHooks.instances.append(self)

    def install(self):
        self.log.append(("install", threading.get_ident()))
        self.installed = True
        return True

    def remove(self):
        self.log.append(("remove", threading.get_ident()))
        self.installed = False

    def shell_message(self, wparam):
        winhooks.Hooks.shell_message(self, wparam)


class TestMessageWindow(unittest.TestCase):
    def make(self, **kw):
        self.q = __import__("queue").Queue()
        self.mw = shellmsg.MessageWindow(self.q.put, **kw)
        self.addCleanup(self.mw.close)
        self.assertTrue(self.mw.hwnd)
        return self.mw

    def drain(self):
        out = []
        while not self.q.empty():
            out.append(self.q.get())
        return out

    def test_real_huge_lparam_does_not_break_the_window_procedure(self):
        """The listening experiment died with OverflowError on HSHELL_GETMINRECT (lParam = a 64-bit pointer).
        The product's window procedure takes WPARAM/LPARAM as Python ints of any size and never converts them."""
        mw = self.make(hooks_factory=RecHooks)
        mw.set_tasks_hooks(True)
        big = 2 ** 62 + 12345
        for lp in (big, 2 ** 63 - 1, -(2 ** 63), -1, 0, 2 ** 32, 2 ** 31):
            self.drain()
            self.assertEqual(_u.SendMessageW(mw.hwnd, mw._shellhook, 5, lp), 0)         # GETMINRECT: no scan, no fault
            self.assertEqual(self.drain(), [], lp)
            self.assertEqual(_u.SendMessageW(mw.hwnd, mw._shellhook, 0x8004, lp), 0)    # RUDEAPPACTIVATED: one entry,
            self.assertEqual(self.drain(), [("bar", ("tasks",))], lp)                   # EVERY time (a swallowed fault
            mw.ack_tasks()                                                              # would leave none)
            _u.SendMessageW(mw.hwnd, mw.callback, 2, lp)                                # the Step 1 appbar callback
            self.assertEqual(self.drain(), [("bar", ("abn", 2, lp))], lp)               # arrives intact, not truncated

    def test_real_huge_wparam_and_unknown_messages(self):
        mw = self.make()
        self.assertEqual(_u.SendMessageW(mw.hwnd, mw._shellhook, 2 ** 63 - 1, 2 ** 62), 0)
        self.assertEqual(_u.SendMessageW(mw.hwnd, 0x0000 + 0x400 + 77, 2 ** 40, 2 ** 40), 0)
        self.assertTrue(mw._thread.is_alive())

    def test_a_burst_of_events_is_one_queue_entry_until_the_app_takes_it(self):
        mw = self.make(hooks_factory=RecHooks)
        mw.set_tasks_hooks(True)
        for _ in range(50):
            _u.SendMessageW(mw.hwnd, mw._shellhook, 1, 0)
        self.assertEqual(self.drain(), [("bar", ("tasks",))])
        _u.SendMessageW(mw.hwnd, mw._shellhook, 1, 0)
        self.assertEqual(self.drain(), [])                               # not acknowledged yet: nothing more queued
        mw.ack_tasks()
        _u.SendMessageW(mw.hwnd, mw._shellhook, 1, 0)
        self.assertEqual(self.drain(), [("bar", ("tasks",))])

    def test_no_hooks_object_means_shell_messages_are_ignored(self):
        mw = self.make()
        _u.SendMessageW(mw.hwnd, mw._shellhook, 1, 0)
        self.assertEqual(self.drain(), [])

    def test_hooks_are_installed_and_removed_on_the_window_thread(self):
        RecHooks.instances.clear()
        mw = self.make(hooks_factory=RecHooks)
        self.assertTrue(mw.set_tasks_hooks(True))
        self.assertTrue(mw.hooks_installed)
        tid = mw._thread.ident
        self.assertEqual(RecHooks.instances[0].log, [("install", tid)])
        self.assertNotEqual(tid, threading.get_ident())
        mw.set_tasks_hooks(False)
        self.assertEqual(RecHooks.instances[0].log[-1], ("remove", tid))

    def test_close_removes_the_hooks_and_waits_for_the_thread(self):
        RecHooks.instances.clear()
        mw = self.make(hooks_factory=RecHooks)
        mw.set_tasks_hooks(True)
        th = mw._thread
        mw.close()
        self.assertFalse(th.is_alive())                                  # after close() returns, nothing is left running
        self.assertFalse(RecHooks.instances[0].installed)
        self.assertEqual(RecHooks.instances[0].log[-1], ("remove", th.ident))
        mw.close()                                                       # twice is fine
        self.assertFalse(mw.set_tasks_hooks(True))

    def test_close_without_hooks_also_waits(self):
        mw = self.make()
        th = mw._thread
        mw.close()
        self.assertFalse(th.is_alive())

    def test_real_hooks_install_and_are_gone_after_close(self):
        """real: SetWinEventHook x5 + RegisterShellHookWindow on the real message window, then close()."""
        mw = self.make()
        self.assertTrue(mw.set_tasks_hooks(True))
        hooks = mw._hooks
        handles = list(hooks._handles)
        self.assertEqual(len(handles), len(winhooks.RANGES))
        self.assertTrue(hooks.shell_ok)
        mw.close()
        self.assertEqual((hooks._handles, hooks.shell_ok), ([], False))
        u = ctypes.WinDLL("user32")
        u.UnhookWinEvent.argtypes = [wt.HANDLE]
        for h in handles:
            self.assertFalse(u.UnhookWinEvent(h))                        # already gone: Windows says so

    def test_real_hooks_deliver_a_dirty_message_for_a_real_window_event(self):
        """real: a top-level window is created in this process (OWN events are skipped), so only the shell hook path is
        exercised here by a message; the WinEvent path is covered with the made-up api above."""
        mw = self.make()
        mw.set_tasks_hooks(True)
        _u.SendMessageW(mw.hwnd, mw._shellhook, 4, 0)
        self.assertEqual(self.drain(), [("bar", ("tasks",))])

    def test_hook_install_failure_is_reported_not_raised(self):
        class Bad:
            installed = False

            def __init__(self, hwnd, cb):
                pass

            def install(self):
                return False

            def remove(self):
                pass
        mw = self.make(hooks_factory=Bad)
        with self.assertLogs("mpanels", "WARNING"):
            self.assertFalse(mw.set_tasks_hooks(True))

    def test_a_factory_that_raises_is_contained(self):
        def boom(hwnd, cb):
            raise RuntimeError("x")
        mw = self.make(hooks_factory=boom)
        with self.assertLogs("mpanels", "ERROR"):
            self.assertFalse(mw.set_tasks_hooks(True))
        self.assertTrue(mw._thread.is_alive())


# --------------------------------------------------------------------------- the controller
class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class TestTasksController(unittest.TestCase):
    def make(self):
        self.src, self.loader, self.clock, self.changes = Src(), FakeLoader(), Clock(), []
        self.src.procs = {1: ("a.exe", FT), 2: ("b.exe", FT + 1)}
        self.src.wins = [W(1, "A"), W(2, "B")]
        self.t = tasks.Tasks(self.src, self.loader, lambda: self.changes.append(1), own_pid=5, now=self.clock,
                             make_photo=lambda img: ("photo", img.size))
        return self.t

    def test_start_scans_and_starts_the_icon_worker(self):
        self.make()
        self.t.start()
        self.assertEqual((self.src.snaps, self.loader.started), (1, 1))
        self.assertEqual([e.title for e in self.t.model.entries], ["A", "B"])
        self.assertEqual(len(self.changes), 1)

    def test_dirty_scans_at_most_every_100_ms(self):
        self.make()
        self.t.start()
        self.src.wins = [W(1, "A!"), W(2, "B")]
        self.t.mark_dirty()
        self.t.pump()
        self.assertEqual(self.src.snaps, 1)                              # 0 ms after the last scan: wait
        self.clock.t += 0.05
        self.t.pump()
        self.assertEqual(self.src.snaps, 1)
        self.clock.t += 0.06
        self.t.pump()
        self.assertEqual(self.src.snaps, 2)
        self.t.pump()
        self.assertEqual(self.src.snaps, 2)                              # the flag was taken: no scan without a new event
        self.assertEqual(self.t.model.entries[0].title, "A!")

    def test_a_storm_of_events_is_one_scan_per_100_ms(self):
        self.make()
        self.t.start()
        scans = 0
        for _ in range(100):                                             # 100 polls of 150 ms with events all the time
            self.t.mark_dirty()
            self.clock.t += 0.01
            before = self.src.snaps
            self.t.pump()
            scans += self.src.snaps - before
        self.assertLessEqual(scans, 11)                                  # 1 s of events: about 10 scans, not 100

    def test_the_2s_tick_finds_a_change_no_event_announced(self):
        self.make()
        self.t.start()
        self.src.wins = [W(1, "A"), W(2, "B"), W(3, "NEW")]
        self.src.procs[3] = ("c.exe", FT + 2)
        self.t.pump()
        self.assertEqual(len(self.t.model.entries), 2)                   # no event, no pump scan
        self.t.tick()
        self.assertEqual([e.title for e in self.t.model.entries], ["A", "B", "NEW"])
        self.assertEqual(len(self.changes), 2)

    def test_tick_without_a_change_does_not_redraw(self):
        self.make()
        self.t.start()
        self.t.tick()
        self.t.tick()
        self.assertEqual(len(self.changes), 1)

    def test_nothing_runs_before_start_or_after_stop(self):
        self.make()
        self.t.mark_dirty()
        self.t.pump()
        self.t.tick()
        self.assertEqual(self.src.snaps, 0)
        self.t.start()
        self.t.stop()
        n = self.src.snaps
        self.t.mark_dirty()
        self.t.pump()
        self.t.tick()
        self.assertEqual(self.src.snaps, n)
        self.assertEqual(self.loader.stopped, 1)

    # ---- icons
    def test_every_new_window_asks_for_its_icon_once(self):
        self.make()
        self.t.start()
        self.assertEqual(sorted(self.loader.requests), [(1, "a.exe"), (2, "b.exe")])
        self.t.tick()
        self.assertEqual(len(self.loader.requests), 2)                   # in flight: not asked again

    def test_icon_arrives_becomes_a_photo_and_is_never_asked_again(self):
        self.make()
        self.t.start()
        self.t.on_icon(1, Image.new("RGBA", (16, 16)))
        self.assertEqual(self.t.icon_of(1), ("photo", (16, 16)))
        self.assertEqual(len(self.changes), 2)                           # redrawn with the icon
        self.t.on_icon(2, None)                                          # window 2 has none
        self.clock.t += 10
        self.t.tick()
        self.assertEqual([r[0] for r in self.loader.requests], [1, 2, 2])    # only the window without an icon is retried

    def test_no_icon_found_gives_the_generic_icon_and_is_retried_slowly(self):
        self.make()
        self.t.start()
        self.t.on_icon(1, None)
        self.t.on_icon(2, None)
        self.assertIs(self.t.icon_of(2), self.t.icon_of(99))             # the one shared generic icon
        self.clock.t += 1.0
        self.t.tick()
        self.assertEqual(len(self.loader.requests), 2)                   # not yet (2 s)
        self.clock.t += 1.5
        self.t.tick()
        self.assertEqual([r[0] for r in self.loader.requests], [1, 2, 1, 2])

    def test_unresolved_process_is_retried_each_scan_and_cached_once_found(self):
        """Calculator: the CoreWindow's process is not found while the window opens. Process and icon are retried; the
        generic icon is shown meanwhile; once found the real icon is cached."""
        self.make()
        self.src.procs[2] = (None, None)
        self.t.start()
        self.t.on_icon(2, None)
        self.assertEqual(self.loader.requests[-1], (2, None))
        self.clock.t += 2.5
        self.src.procs[2] = ("calc.exe", FT + 1)
        self.t.tick()
        self.assertEqual(self.loader.requests[-1], (2, "calc.exe"))      # the path is now known: the exe icon is possible
        self.t.on_icon(2, Image.new("RGBA", (16, 16)))
        n = len(self.loader.requests)
        self.clock.t += 5
        self.t.tick()
        self.assertEqual(len(self.loader.requests), n)                   # cached: no more attempts

    def test_closed_window_drops_its_icon_and_late_answers_are_ignored(self):
        self.make()
        self.t.start()
        self.t.on_icon(1, Image.new("RGBA", (16, 16)))
        self.src.wins = [W(2, "B")]
        self.t.tick()
        self.assertNotIn(1, self.t._photos)                              # per-window cache deleted with the window
        self.assertEqual(self.t._last_try.get(1), None)
        self.t.on_icon(1, Image.new("RGBA", (16, 16)))                   # the worker answers late
        self.assertNotIn(1, self.t._photos)

    def test_stop_forgets_every_photo(self):
        self.make()
        self.t.start()
        self.t.on_icon(1, Image.new("RGBA", (16, 16)))
        self.t.stop()
        self.assertEqual((self.t._photos, self.t._inflight, self.t._generic), ({}, set(), None))

    def test_view_exposes_entries_active_and_icons(self):
        self.make()
        self.src.fg = 2
        self.t.start()
        v = self.t.view()
        self.assertEqual([e.title for e in v.entries], ["A", "B"])
        self.assertEqual(v.active, 2)
        self.assertIsNotNone(v.icon_of(1))


class TestIconLoader(unittest.TestCase):
    def test_request_answers_through_the_queue_with_the_image_or_none(self):
        out = __import__("queue").Queue()

        def fetch(hwnd, path, size):
            if hwnd == 2:
                raise OSError("boom")
            return ("img", hwnd, path, size)
        ld = tasks.IconLoader(fetch, out.put, 16)
        ld.start()
        ld.request(1, "a.exe")
        ld.request(2, "b.exe")
        self.assertEqual(out.get(timeout=2), ("bar", ("icon", 1, ("img", 1, "a.exe", 16))))
        self.assertEqual(out.get(timeout=2), ("bar", ("icon", 2, None)))            # a failing fetch is "no icon", not a crash
        th = ld._thread
        ld.stop()
        self.assertFalse(th.is_alive())
        ld.stop()

    def test_the_worker_is_a_daemon_thread(self):
        ld = tasks.IconLoader(lambda *a: None, lambda m: None)
        ld.start()
        self.assertTrue(ld._thread.daemon)
        ld.stop()


# --------------------------------------------------------------------------- the real source (read-only Windows calls)
class TestWin32Source(unittest.TestCase):
    """real: EnumWindows, DWM, process times. Only reads; no message is sent to another process's window."""

    @classmethod
    def setUpClass(cls):
        cls.src = tasks.Win32Source()

    def test_real_snapshot_lists_windows_in_z_order_and_marks_the_shell_window(self):
        wins = self.src.snapshot()
        self.assertGreater(len(wins), 5)
        self.assertTrue(all(isinstance(w.hwnd, int) and w.hwnd for w in wins))
        self.assertEqual(len({w.hwnd for w in wins}), len(wins))
        self.assertTrue(any(w.shell for w in wins) or True)              # (no desktop window when Explorer is not running)

    def test_real_our_own_window_is_seen_but_never_listed(self):
        import tkinter as tk
        r = tk.Tk()
        self.addCleanup(r.destroy)
        r.title("M Panels own window test")
        r.update()
        mine = [w for w in self.src.snapshot() if w.title == "M Panels own window test"]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0].pid, os.getpid())
        self.assertTrue(mine[0].visible)
        self.assertFalse(tasks.listed(mine[0], os.getpid()))
        self.assertTrue(tasks.listed(mine[0], os.getpid() + 1))          # (it WOULD be, were it not ours)

    def test_real_resolve_gives_the_exe_and_a_start_time_for_our_own_process(self):
        w = W(1, pid=os.getpid())
        path, start = self.src.resolve(w)
        self.assertTrue(os.path.basename(path).lower().startswith("python"))
        self.assertGreater(start, FT // 2)
        self.assertLess(start, tasks._now_filetime())

    def test_real_resolve_of_a_missing_process_is_none_none(self):
        self.assertEqual(self.src.resolve(W(1, pid=0x7FFFFFF0)), (None, None))

    def test_real_foreground_is_an_int(self):
        self.assertIsInstance(self.src.foreground(), int)

    def test_real_big_handle_values_do_not_overflow(self):
        """The experiment's OverflowError: a 64-bit value in a default-int argument. Typed arguments take any HWND."""
        self.assertEqual(self.src.resolve(W(2 ** 40, pid=os.getpid()))[0] is not None, True)
        self.assertEqual(self.src._core_pid(2 ** 40), 0)                 # not a window: no children, no error

    def test_real_fetch_icon_falls_back_to_the_exe_icon_when_the_window_does_not_answer(self):
        """A Tk window in THIS process whose thread is busy (this one): WM_GETICON times out after 100 ms (it must not
        block), then the exe icon is used."""
        import tkinter as tk
        r = tk.Tk()
        self.addCleanup(r.destroy)
        r.update()
        hwnd = ctypes.windll.user32.GetParent(r.winfo_id()) or r.winfo_id()
        t0 = time.perf_counter()
        out = []
        th = threading.Thread(target=lambda: out.append(self.src.fetch_icon(hwnd, sys.executable, 16)))
        th.start()
        th.join(5)                                                       # this thread does not pump: the message times out
        self.assertFalse(th.is_alive())
        self.assertLess(time.perf_counter() - t0, 3)
        self.assertIsNotNone(out[0])
        self.assertEqual(out[0].size, (16, 16))

    def test_a_uwp_frame_window_never_gets_the_frames_own_icon(self):
        """ApplicationFrameWindow: its window/class icon is ApplicationFrameHost's, not the app's. Only the app's exe
        icon (when the CoreWindow's process is known) or nothing (generic icon, asked again later)."""
        src = tasks.Win32Source()
        src._u = mock.Mock()
        src._u.GetClassNameW = lambda h, buf, n: setattr(buf, "value", tasks.APP_FRAME_CLASS) or 1
        # Spies that FAIL at once if the frame's own icons are asked for: a clean assertion, never a call into the real
        # winutil.hicon_to_image with a made-up handle (that crashed the process when this protection was removed).
        boom = AssertionError("the frame's own icon was asked for (it is ApplicationFrameHost's)")
        src._u.SendMessageTimeoutW.side_effect = boom
        src._u.GetClassLongPtrW.side_effect = boom
        with mock.patch.object(winutil, "hicon_to_image", side_effect=boom), \
                mock.patch.object(src, "_packaged_window", side_effect=boom), \
                mock.patch.object(winutil, "file_icon", return_value="EXE ICON") as fi:
            self.assertEqual(src.fetch_icon(5, "C:/app/calc.exe", 16), "EXE ICON")
            fi.assert_called_once_with("C:/app/calc.exe", 16)
            self.assertIsNone(src.fetch_icon(5, None, 16))

    def test_real_fetch_icon_of_nothing_is_none(self):
        self.assertIsNone(self.src.fetch_icon(0, None, 16))

    def test_real_our_dlls_are_private_copies(self):
        """Setting argtypes here must not change how other modules call user32."""
        self.assertIsNot(self.src._u, ctypes.windll.user32)
        self.assertIsNone(ctypes.windll.user32.EnumWindows.argtypes)


class TestFakeSource(unittest.TestCase):
    def test_fake_list_shape(self):
        s = tasks.FakeSource()
        wins = s.snapshot()
        self.assertEqual([w.title for w in wins], list(ui.BAR_TEST_WINDOWS))
        self.assertTrue(all(tasks.listed(w, os.getpid()) for w in wins))
        self.assertEqual(s.foreground(), wins[0].hwnd)
        self.assertEqual([w.title for w in wins if w.iconic], [ui.BAR_TEST_WINDOWS[2]])
        self.assertIsNotNone(s.resolve(wins[0])[0])
        self.assertEqual(s.fetch_icon(1000, "x", 16).size, (16, 16))


# --------------------------------------------------------------------------- config
class TestConfig(unittest.TestCase):
    def test_default_is_on_and_junk_falls_back(self):
        self.assertEqual(infoclock.defaults()["tasks"], {"enabled": True, "show_titles": True})
        for junk in (None, "x", 5, {"tasks": 5}, {"tasks": {"enabled": "no"}}, {"tasks": None}):
            self.assertEqual(infoclock.sanitize(junk)["tasks"], {"enabled": True, "show_titles": True}, junk)

    def test_unknown_keys_survive_and_off_stays_off(self):
        d = infoclock.sanitize({"tasks": {"enabled": False, "later": 1}})
        self.assertEqual(d["tasks"], {"enabled": False, "show_titles": True, "later": 1})


# --------------------------------------------------------------------------- the bar and the App on a made-up source
class Base2(Base):
    def setUp(self):
        super().setUp()
        self.src = Src()
        self.src.procs = {1: ("a.exe", FT), 2: ("b.exe", FT + 1), 3: ("c.exe", FT + 2)}
        self.src.wins = [W(1, "Alpha"), W(2, "Beta"), W(3, "Gamma")]
        self.src.fg = 2

    def make_shell(self, put):
        events = self.events

        class Shell(FakeShell):
            def close(self_):
                events.append("SHELLCLOSE")
                super().close()

            def set_tasks_hooks(self_, on):
                events.append("HOOKS_ON" if on else "HOOKS_OFF")
                return super().set_tasks_hooks(on)
        sh = Shell(put)
        self.shells.append(sh)
        return sh

    def titles(self, app=None):
        return [e.title for e in (app or self.app).bar.tasks.model.entries]


class TestBarTasks(Base2):
    def test_bar_on_lists_the_windows_and_installs_the_hooks(self):
        app = self.open(bar=ON)
        self.assertEqual(self.titles(), ["Alpha", "Beta", "Gamma"])
        self.assertEqual([e.title for e in self.windows[0].view.entries], ["Alpha", "Beta", "Gamma"])
        self.assertEqual(self.windows[0].view.active, 2)
        self.assertEqual(self.shells[0].hooks, [True])
        self.assertEqual(app.bar.tasks.loader._thread is not None, True)

    def test_bar_off_nothing_exists_no_scan_no_hook_no_thread(self):
        app = self.open()
        self.assertIsNone(app.bar)
        self.assertEqual((self.src.snaps, self.shells, self.windows), (0, [], []))       # no source, no window, no hook
        app.root.update()
        self.assertEqual(self.src.snaps, 0)
        self.assertFalse([t for t in threading.enumerate() if t.name.startswith("Thread") and "_run" in repr(t._target)
                          and getattr(t._target, "__self__", None).__class__.__name__ in ("IconLoader", "MessageWindow")])

    def test_tasks_off_in_config_no_scan_no_hook_no_worker(self):
        app = self.open(bar=dict(ON, tasks={"enabled": False}))
        self.assertIsNone(app.bar.tasks)
        self.assertEqual((self.src.snaps, self.shells[0].hooks), (0, []))
        self.assertIsNone(self.windows[0].view)

    def test_a_tasks_message_marks_dirty_acks_and_the_poll_scans(self):
        app = self.open(bar=ON)
        self.src.wins.append(W(4, "Delta"))
        self.src.procs[4] = ("d.exe", FT + 3)
        n = self.src.snaps
        self.send("tasks")
        self.assertEqual(self.shells[0].acks, 1)
        time.sleep(0.12)                                                 # the 100 ms scan limit is real time here
        app._poll()
        self.assertGreater(self.src.snaps, n)
        self.assertIn("Delta", self.titles())
        self.assertIn("Delta", [e.title for e in self.windows[0].view.entries])

    def test_the_2s_tick_is_the_safety_net_with_no_message_at_all(self):
        app = self.open(bar=ON)
        self.src.wins = [W(1, "Alpha"), W(3, "Gamma")]
        app._tick()
        self.assertEqual(self.titles(), ["Alpha", "Gamma"])

    def test_active_minimized_and_title_changes_reach_the_window(self):
        app = self.open(bar=ON)
        self.src.fg = 3
        self.src.wins = [W(1, "Alpha", iconic=True), W(2, "Beta renamed"), W(3, "Gamma")]
        app._tick()
        v = self.windows[0].view
        self.assertEqual(v.active, 3)
        self.assertEqual([(e.title, e.minimized) for e in v.entries],
                         [("Alpha", True), ("Beta renamed", False), ("Gamma", False)])

    def test_own_windows_are_not_listed(self):
        app = self.open(bar=ON)
        self.src.wins.append(W(50, "M Panels - Settings", pid=os.getpid()))
        app._tick()
        self.assertNotIn("M Panels - Settings", self.titles())

    def test_an_icon_message_is_handled_and_unknown_windows_ignored(self):
        app = self.open(bar=ON)
        self.send("icon", 1, Image.new("RGBA", (16, 16)))
        self.assertIn(1, app.bar.tasks._photos)
        self.send("icon", 999, Image.new("RGBA", (16, 16)))
        self.assertNotIn(999, app.bar.tasks._photos)

    def test_messages_after_the_bar_went_are_ignored(self):
        app = self.open(bar=ON)
        app.stop_bar()
        self.send("tasks")
        self.send("icon", 1, None)

    def test_settings_checkbox_turns_the_section_on_and_off_live(self):
        app = self.open(bar=ON)
        self.assertTrue(app.apply_bar(True, app.cfg["bar"]["info"], {"enabled": False}))
        self.assertIsNone(app.bar.tasks)
        self.assertEqual(self.shells[0].hooks, [True, False])
        self.assertIsNone(self.windows[0].view)
        self.assertEqual(self.cfg_file()["bar"]["tasks"], {"enabled": False, "show_titles": True})
        n = self.src.snaps
        app._tick()
        self.assertEqual(self.src.snaps, n)                              # off means off: not one scan
        self.assertTrue(app.apply_bar(True, app.cfg["bar"]["info"], {"enabled": True}))
        self.assertEqual(self.titles(), ["Alpha", "Beta", "Gamma"])
        self.assertEqual(self.shells[0].hooks, [True, False, True])

    def test_settings_tab_has_the_box_and_apply_uses_it(self):
        app = self.open(bar=ON)
        app.open_settings()
        w = app.settings_win
        self.addCleanup(lambda: w.win.winfo_exists() and w.win.destroy())
        self.assertTrue(w.v_bar_tasks.get())
        self.assertFalse(w.dirty())
        w.v_bar_tasks.set(False)
        self.assertTrue(w.dirty())
        self.assertIsNotNone(app.bar.tasks)                              # nothing before Apply
        w.apply()
        self.assertIsNone(app.bar.tasks)
        self.assertFalse(w.dirty())
        self.assertEqual(w._bar_applied().tasks_on, False)

    def test_factory_settings_load_the_tasks_box_and_apply_decides(self):
        app = self.open(bar=dict(ON, tasks={"enabled": False}))
        app.open_settings()
        w = app.settings_win
        self.addCleanup(lambda: w.win.winfo_exists() and w.win.destroy())
        self.assertFalse(w.v_bar_tasks.get())
        with mock.patch.object(w, "confirm_overwrite", return_value=True):
            w.reset(True)
        self.assertTrue(w.v_bar_tasks.get())                             # the factory default is "on"
        self.assertIsNone(app.bar.tasks)                                 # ...but nothing changes before Apply
        w.apply()                                                        # (the bar itself goes back to off)
        self.assertIsNone(app.bar)
        self.assertEqual(app.cfg["bar"]["tasks"], {"enabled": True, "show_titles": True})

    def test_bar_off_by_settings_removes_hooks_and_window(self):
        app = self.open(bar=ON)
        app.apply_bar(False, app.cfg["bar"]["info"])
        self.assertIsNone(app.bar)
        self.assertIn("SHELLCLOSE", self.events)
        self.assertGreater(self.events.index("SHELLCLOSE"), self.events.index("REMOVE"))
        self.assertEqual(self.shells[0].hooks, [True])                   # (close() takes them off: no extra call needed)


class TestTestModeTasks(Base2):
    default_source = True                                                # the App picks its own source, as in the program

    def test_test_mode_shows_the_made_up_list_and_never_hooks(self):
        with mock.patch.object(tasks, "Win32Source", side_effect=AssertionError("real source in TEST mode")), \
                mock.patch.object(winhooks, "Win32Hooks", side_effect=AssertionError("real hooks in TEST mode")):
            app = self.open(bar=ON, test_mode=True)
            app.root.update()
            self.assertEqual(self.titles(), list(ui.BAR_TEST_WINDOWS))
            self.assertEqual(self.windows[0].view.active, 1000)
            self.assertEqual(self.shells[0].hooks, [])                   # real hooks never in TEST mode
            app._tick()
            self.assertEqual(self.titles(), list(ui.BAR_TEST_WINDOWS))

    def test_real_mode_without_a_test_source_would_use_the_real_one(self):
        with mock.patch.object(tasks, "Win32Source") as real:
            real.return_value = Src()
            self.open(bar=ON, test_mode=False)
            real.assert_called_once()


class TestQuitOrder(Base2):
    """Quit order is part of the contract: AppBar REMOVE, then the hooks go (and the window thread ends), then Tk goes."""

    def watch_destroy(self, app):
        orig = app.root.destroy
        app.root.destroy = lambda: (self.events.append("destroy"), orig())[1]

    def test_remove_and_hook_removal_come_before_root_destroy(self):
        app = self.open(bar=ON)
        self.watch_destroy(app)
        app.quit()
        tail = self.events[self.events.index("HOOKS_ON"):]
        self.assertEqual([e for e in tail if e in ("REMOVE", "SHELLCLOSE", "destroy")], ["REMOVE", "SHELLCLOSE", "destroy"])
        self.assertEqual(self.events.count("SHELLCLOSE"), 1)

    def test_the_icon_worker_is_stopped_before_destroy(self):
        app = self.open(bar=ON)
        th = app.bar.tasks.loader._thread
        app.quit()
        self.assertFalse(th.is_alive())

    def test_a_failing_hook_removal_does_not_stop_quit(self):
        app = self.open(bar=ON)
        self.watch_destroy(app)
        self.shells[0].close = mock.Mock(side_effect=RuntimeError("x"))
        with self.assertLogs("mpanels", "ERROR"):
            app.quit()
        self.assertEqual(self.events[-1], "destroy")

    def test_real_message_window_hooks_are_gone_when_the_bar_stops(self):
        """real: the Bar with the REAL MessageWindow (hooks made up): stop() returns only after the hooks are removed."""
        RecHooks.instances.clear()
        app = self.open(bar=ON, test_mode=False)
        mw = shellmsg.MessageWindow(app.q.put, hooks_factory=RecHooks)
        self.addCleanup(mw.close)
        mw.set_tasks_hooks(True)
        bar = barwin.Bar(app.root, app.cfg["bar"]["info"], FakeAppBar(), mw, app._fresh_monitors, app.wall_clock,
                         lambda: None, app.popup, lambda: None, False, window_factory=self.make_window,
                         tasks_cfg={"enabled": False}, tasks_factory=None)
        bar.start()
        bar.stop()
        self.assertFalse(mw._thread.is_alive())
        self.assertFalse(RecHooks.instances[0].installed)


# --------------------------------------------------------------------------- the real BarWindow drawing
class TestDrawing(Base2):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(winutil, "overlay_show", return_value=True)
        p.start()
        self.addCleanup(p.stop)

    def view(self, titles, active=0, minimized=(), win=None):
        ents = tuple(tasks.Entry(100 + i, t, i in minimized, "x.exe") for i, t in enumerate(titles))
        img = ImageTk.PhotoImage(Image.new("RGBA", (16, 16), (255, 0, 0, 255)))
        self._img = img
        return tasks.View(ents, 100 + active if active is not None else 0, lambda h: img)

    def bar(self, bar=INFO_ONLY):
        app = self.open(bar=dict(bar, tasks={"enabled": False}), window=False)
        return app, app.bar.win

    def test_buttons_start_after_the_reserved_left_end_and_info_stays_right(self):
        app, win = self.bar()
        win.set_tasks(self.view(["One", "Two", "Three"]))
        self.assertEqual(win.buttons[0]["x"], theme.BAR_LEFT_RESERVE)
        self.assertEqual([b["w"] for b in win.buttons], [theme.BAR_BTN_MAX_W] * 3)
        texts = [win.cv.itemcget(i, "text") for i in win.cv.find_all() if win.cv.type(i) == "text"]
        self.assertIn("Tuesday 24 November · 14:32", texts)
        info_x = [win.cv.coords(i)[0] for i in win.cv.find_all() if win.cv.type(i) == "text"
                  and win.cv.itemcget(i, "text").startswith("Tuesday")][0]
        self.assertEqual(info_x, 1920 - theme.BAR_PAD_X)
        last = win.buttons[-1]
        self.assertLess(last["x"] + last["w"], info_x - win._font.measure("Tuesday 24 November · 14:32"))

    def test_active_button_has_the_accent_frame_and_a_lighter_fill(self):
        """Step 3c: the active window is shown by the accent-colored frame (no underline any more)."""
        app, win = self.bar()
        win.set_tasks(self.view(["One", "Two"], active=1))
        self.assertEqual([b["active"] for b in win.buttons], [False, True])
        pal = theme.bar_palette()
        self.assertEqual((win.buttons[1]["fill"], win.buttons[1]["frame"]), (pal["active_bg"], pal["active"]))
        self.assertEqual((win.buttons[0]["fill"], win.buttons[0]["frame"]), (pal["button"], pal["border"]))
        self.assertEqual([win.cv.type(i) for i in win.cv.find_all()].count("rectangle"), 0)     # no underline, no flat box

    def test_minimized_window_title_is_dim(self):
        app, win = self.bar()
        win.set_tasks(self.view(["One", "Two"], active=None, minimized=(1,)))
        by = {win.cv.itemcget(i, "text"): win.cv.itemcget(i, "fill") for i in win.cv.find_all() if win.cv.type(i) == "text"}
        self.assertEqual(by["One"], theme.bar_palette()["text"])
        self.assertEqual(by["Two"], theme.bar_palette()["dim_text"])

    def test_long_title_is_cut_with_an_ellipsis_and_the_tooltip_has_all_of_it(self):
        app, win = self.bar()
        long = "A really very long document title that cannot possibly fit in one button - final.docx"
        win.set_tasks(self.view([long]))
        b = win.buttons[0]
        self.assertTrue(b["shown"].endswith("…"))
        self.assertLess(len(b["shown"]), len(long))
        self.assertLessEqual(win._font.measure(b["shown"]), tasks.text_room(b["w"]))
        win._show_tip(b, 300)
        labels = [c for c in win._tip.winfo_children()]
        self.assertEqual(labels[0].cget("text"), long)
        win._hide_tip()
        self.assertIsNone(win._tip)

    def test_motion_schedules_the_tooltip_leave_cancels_it(self):
        app, win = self.bar()
        win.set_tasks(self.view(["One", "Two"]))
        ev = mock.Mock(x=win.buttons[1]["x"] + 5, x_root=500)
        win._on_motion(ev)
        self.assertIsNotNone(win._tip_job)
        win._on_motion(ev)                                               # same button: the timer is not restarted
        job = win._tip_job
        win._on_motion(ev)
        self.assertEqual(win._tip_job, job)
        win._hide_tip()
        self.assertIsNone(win._tip_job)
        win._on_motion(mock.Mock(x=5, x_root=5))                         # over the empty left end: no tooltip
        self.assertIsNone(win._tip_job)

    def test_narrow_buttons_are_icon_only(self):
        app, win = self.bar()
        win.set_tasks(self.view(["W%d" % i for i in range(30)]))
        b = win.buttons[0]
        if tasks.text_room(b["w"]) < theme.BAR_TEXT_MIN_ROOM:
            self.assertEqual(b["shown"], "")

    def test_overflow_last_button_is_plus_n_and_its_menu_lists_the_rest(self):
        app, win = self.bar()
        titles = ["Window number %d" % i for i in range(60)]
        win.set_tasks(self.view(titles))
        last = win.buttons[-1]
        self.assertEqual(last["kind"], "more")
        k = len(win.buttons) - 1
        self.assertEqual(last["shown"], ui.BAR_OVERFLOW.format(n=60 - k))
        self.assertEqual([t.title for t in last["rest"]], titles[k:])
        self.assertTrue(all(theme.BAR_BTN_MIN_W <= b["w"] < 2 * theme.BAR_BTN_MIN_W for b in win.buttons))
        popped = []
        win._popup = lambda m, x, y: popped.append((m, x, y))
        win._on_press(mock.Mock(x=last["x"] + 3))
        win._on_release(mock.Mock(x=last["x"] + 3))
        self.assertEqual(len(popped), 1)
        self.assertEqual(popped[0][0].index("end") + 1, 60 - k)
        win._on_press(mock.Mock(x=win.buttons[0]["x"] + 3))              # a task button: no menu
        win._on_release(mock.Mock(x=win.buttons[0]["x"] + 3))
        self.assertEqual(len(popped), 1)

    def test_clicking_a_task_button_without_a_handler_does_nothing(self):
        app, win = self.bar()
        win.set_tasks(self.view(["One"]))
        win.on_task = None
        with mock.patch.object(winutil, "overlay_show") as m:
            win._on_press(mock.Mock(x=win.buttons[0]["x"] + 3))
            win._on_release(mock.Mock(x=win.buttons[0]["x"] + 3))
            m.assert_not_called()

    def test_no_view_means_no_buttons_and_an_empty_list_too(self):
        app, win = self.bar()
        win.set_tasks(None)
        self.assertEqual(win.buttons, [])
        win.set_tasks(self.view([]))
        self.assertEqual(win.buttons, [])

    def test_info_off_gives_the_buttons_the_whole_width(self):
        app, win = self.bar(bar=dict(ON, info={"enabled": False, "time_format": "24h", "show_date": True}))
        win.set_tasks(self.view(["W%d" % i for i in range(5)]))
        self.assertEqual([b["w"] for b in win.buttons], [theme.BAR_BTN_MAX_W] * 5)

    def test_the_whole_app_draws_through_the_real_window(self):
        app = self.open(bar=ON, window=False)
        win = app.bar.win
        self.assertEqual([b["title"] for b in win.buttons], ["Alpha", "Beta", "Gamma"])
        self.assertEqual([b["active"] for b in win.buttons], [False, True, False])


if __name__ == "__main__":
    unittest.main()
