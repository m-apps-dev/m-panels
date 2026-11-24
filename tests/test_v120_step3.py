"""v1.2 step 3: clicking a Tasks button (restore / bring forward / minimize), the "+N" menu rows, the click actions, the
icon order for packaged apps, and "a failing log never breaks a Tk callback".
No test here ever touches a real window except where a name starts with "real:" (read-only calls)."""
import ctypes
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import barwin  # noqa: E402
import tasks  # noqa: E402
import winutil  # noqa: E402
from test_v120_step1 import ON  # noqa: E402
from test_v120_step2 import FT, Base2, Clock, FakeLoader, Src, W  # noqa: E402


def ev(x):
    return mock.Mock(x=x, x_root=x)


# --------------------------------------------------------------------------- the rule
class TestDecide(unittest.TestCase):
    def test_table(self):
        self.assertEqual(tasks.decide(False, 7, 3), "front")                 # another window was active
        self.assertEqual(tasks.decide(False, 3, 3), "minimize")              # the active window's own button
        self.assertEqual(tasks.decide(False, 0, 3), "front")                 # nothing was active
        self.assertEqual(tasks.decide(True, 7, 3), "restore")                # minimized: restore (and bring forward)
        self.assertEqual(tasks.decide(True, 3, 3), "restore")                # (a minimized window is never "active")


# --------------------------------------------------------------------------- Tasks.activate on made-up parts
class TestActivate(unittest.TestCase):
    def make(self, actions=None, schedule=True):
        self.src, self.loader, self.clock = Src(), FakeLoader(), Clock()
        self.src.procs = {1: ("a.exe", FT), 2: ("b.exe", FT + 1), 3: ("c.exe", FT + 2)}
        self.src.wins = [W(1, "A"), W(2, "B"), W(3, "C", iconic=True)]
        self.actions = actions if actions is not None else tasks.FakeActions()
        self.jobs = []
        self.t = tasks.Tasks(self.src, self.loader, lambda: None, own_pid=5, now=self.clock, make_photo=lambda i: i,
                             actions=self.actions, schedule=(lambda ms, fn: self.jobs.append((ms, fn))) if schedule else None)
        self.t.start()
        return self.t

    def test_front_minimize_restore(self):
        self.make()
        self.assertTrue(self.t.activate(1, 2))                               # B was active, click A
        self.assertTrue(self.t.activate(2, 2))                               # click the active one
        self.assertTrue(self.t.activate(3, 2))                               # a minimized one
        self.assertEqual(self.actions.calls, [("front", 1), ("minimize", 2), ("restore", 3)])

    def test_a_gone_window_does_nothing(self):
        self.make()
        self.assertFalse(self.t.activate(99, 1))
        self.assertEqual(self.actions.calls, [])

    def test_no_actions_object_does_nothing(self):
        self.make()
        self.t.actions = None
        self.assertFalse(self.t.activate(1, 2))

    def test_the_list_is_rescanned_after_a_click(self):
        self.make()
        self.clock.t += 1
        self.src.wins = [W(1, "A"), W(2, "B"), W(3, "C")]                     # C got restored
        self.t.activate(3, 2)
        self.clock.t += 0.2
        self.t.pump()
        self.assertFalse(self.t.model.entries[2].minimized)

    def test_front_is_checked_150_ms_later_and_only_logged(self):
        self.make()
        self.src.fg = 2
        self.t.activate(1, 2)
        self.assertEqual([ms for ms, _ in self.jobs], [150])
        with self.assertLogs("mpanels", "INFO") as lg:
            self.jobs[0][1]()                                                # still B in front: A did not come forward
        self.assertIn("could not bring window 1 forward (front)", lg.output[0])

    def test_front_that_worked_logs_nothing(self):
        self.make()
        self.t.activate(1, 2)
        self.src.fg = 1
        with mock.patch.object(tasks, "LOG") as lg:
            self.jobs[0][1]()
        lg.info.assert_not_called()

    def test_minimize_is_not_checked(self):
        self.make()
        self.t.activate(2, 2)
        self.assertEqual(self.jobs, [])

    def test_a_refused_action_is_logged_quietly_and_returns_false(self):
        self.make(actions=mock.Mock(run=mock.Mock(return_value=False)))
        with self.assertLogs("mpanels", "INFO") as lg:
            self.assertFalse(self.t.activate(1, 2))
        self.assertIn("could not bring window 1 forward (front)", lg.output[0])
        self.assertEqual(self.jobs, [])

    def test_an_exception_in_the_action_is_contained(self):
        self.make(actions=mock.Mock(run=mock.Mock(side_effect=OSError("boom"))))
        with self.assertLogs("mpanels", "ERROR"):
            self.assertFalse(self.t.activate(1, 2))

    def test_a_failing_log_file_never_escapes(self):
        """PermissionError while writing the log (seen in the experiment) must not break the caller."""
        self.make(actions=mock.Mock(run=mock.Mock(return_value=False)))
        bad = mock.Mock()
        for name in ("info", "warning", "error", "exception"):
            getattr(bad, name).side_effect = PermissionError("log file locked")
        with mock.patch.object(tasks, "LOG", bad):
            self.assertFalse(self.t.activate(1, 2))                           # refused action + failing log
            self.t.actions = mock.Mock(run=mock.Mock(side_effect=OSError("boom")))
            self.assertFalse(self.t.activate(1, 2))                           # failing action + failing log
            self.t._check_front(1, "front")                                   # the 150 ms check with a failing log
            tasks.safe_log("info", "x")
        self.assertTrue(bad.info.called and bad.exception.called)             # (the log WAS tried, and failed)


# --------------------------------------------------------------------------- the real actions on a made-up user32
class TestWin32Actions(unittest.TestCase):
    def make(self, window=True):
        a = tasks.Win32Actions()
        a._u = mock.Mock()
        a._u.IsWindow.return_value = 1 if window else 0
        a._u.SetForegroundWindow.return_value = 1
        a._u.ShowWindowAsync.return_value = 1
        self.u = a._u
        return a

    def names(self):
        return [c[0] for c in self.u.method_calls]

    def test_front_is_a_plain_SetForegroundWindow_and_nothing_else(self):
        a = self.make()
        self.assertTrue(a.run("front", 1234))
        self.assertEqual(self.names(), ["IsWindow", "SetForegroundWindow"])

    def test_restore_then_bring_forward_in_that_order(self):
        a = self.make()
        self.assertTrue(a.run("restore", 1234))
        self.assertEqual(self.names(), ["IsWindow", "ShowWindowAsync", "SetForegroundWindow"])
        self.assertEqual(self.u.ShowWindowAsync.call_args[0][1], 9)           # SW_RESTORE

    def test_minimize_is_async_and_does_not_bring_anything_forward(self):
        a = self.make()
        self.assertTrue(a.run("minimize", 1234))
        self.assertEqual(self.names(), ["IsWindow", "ShowWindowAsync"])
        self.assertEqual(self.u.ShowWindowAsync.call_args[0][1], 6)           # SW_MINIMIZE (never the blocking ShowWindow)

    def test_a_window_that_is_gone_is_not_touched(self):
        a = self.make(window=False)
        for act in ("front", "restore", "minimize"):
            self.assertFalse(a.run(act, 1234))
        self.assertEqual(self.names(), ["IsWindow"] * 3)

    def test_a_refusal_is_a_false_not_an_exception(self):
        a = self.make()
        self.u.SetForegroundWindow.return_value = 0                           # e.g. an elevated window
        self.assertFalse(a.run("front", 1234))

    def test_no_fallback_chain_no_key_presses_no_thread_attach_no_close(self):
        a = self.make()
        self.u.SetForegroundWindow.return_value = 0
        for act in ("front", "restore", "minimize"):
            a.run(act, 77)
        used = set(self.names())
        self.assertFalse(used & {"AttachThreadInput", "keybd_event", "PostMessageW", "SendMessageW", "CloseWindow",
                                 "DestroyWindow", "SetWindowPos", "MoveWindow", "FlashWindow", "FlashWindowEx"}, used)

    def test_real_a_64_bit_handle_value_does_not_overflow(self):
        a = tasks.Win32Actions()
        self.assertFalse(a.run("front", 2 ** 40))                             # not a window: IsWindow says no, no error
        self.assertFalse(a.run("minimize", 0x7FFFFFF0))

    def test_real_own_dlls(self):
        a = tasks.Win32Actions()
        self.assertIsNot(a._u, ctypes.windll.user32)


class TestFakeActions(unittest.TestCase):
    def test_records_only(self):
        a = tasks.FakeActions()
        self.assertTrue(a.run("front", 5))
        self.assertEqual(a.calls, [("front", 5)])


# --------------------------------------------------------------------------- the real BarWindow with a made-up source
class Clicks(Base2):
    def setUp(self):
        super().setUp()
        self.actions = tasks.FakeActions()
        p = mock.patch.object(winutil, "overlay_show", return_value=True)
        p.start()
        self.addCleanup(p.stop)

    def bar(self, **kw):
        app = self.open(bar=ON, window=False, **kw)
        return app, app.bar.win

    def btn(self, win, title):
        return next(b for b in win.buttons if b["title"] == title)

    def click(self, win, title, fg_between=None):
        b = self.btn(win, title)
        x = b["x"] + 5
        win._on_press(ev(x))
        if fg_between is not None:
            self.src.fg = fg_between                                         # something changed the foreground meanwhile
        win._on_release(ev(x))


class TestClicking(Clicks):
    def test_click_inactive_active_minimized(self):
        app, win = self.bar()
        self.src.wins = [W(1, "Alpha"), W(2, "Beta"), W(3, "Gamma", iconic=True)]
        app._tick()
        self.src.fg = 2
        self.click(win, "Alpha")
        self.click(win, "Beta")
        self.click(win, "Gamma")
        self.assertEqual(self.actions.calls, [("front", 1), ("minimize", 2), ("restore", 3)])

    def test_the_foreground_of_the_moment_of_the_press_counts(self):
        """A menu (or anything) that changes the foreground between press and release must not change the decision."""
        app, win = self.bar()
        self.src.fg = 2
        self.click(win, "Beta", fg_between=1)                                # at press Beta was active: minimize
        self.assertEqual(self.actions.calls, [("minimize", 2)])

    def test_release_on_another_button_or_without_a_press_is_not_a_click(self):
        app, win = self.bar()
        a, b = self.btn(win, "Alpha"), self.btn(win, "Beta")
        win._on_press(ev(a["x"] + 5))
        win._on_release(ev(b["x"] + 5))
        win._on_release(ev(a["x"] + 5))                                      # no press any more
        win._on_press(ev(5))                                                 # the empty left end
        win._on_release(ev(5))
        self.assertEqual(self.actions.calls, [])

    def test_a_click_on_a_window_that_just_closed_does_nothing(self):
        app, win = self.bar()
        old = dict(self.btn(win, "Alpha"))                                   # the button as it was when the mouse went down
        self.src.wins = [W(2, "Beta"), W(3, "Gamma")]                         # Alpha closed before the release
        app._tick()
        win._clicked(old, 2)
        self.assertEqual(self.actions.calls, [])

    def test_right_click_is_the_bar_menu_and_middle_click_is_nothing(self):
        app, win = self.bar()
        self.assertTrue(win.cv.bind("<Button-3>"))                           # the bar's menu ("Settings…" only)
        self.assertEqual(win._menu.index("end"), 0)
        self.assertEqual(win._menu.entrycget(0, "label"), "Settings…")
        self.assertEqual(win.cv.bind("<Button-2>"), "")                      # middle: no handler
        self.assertEqual(win.cv.bind("<ButtonPress-2>"), "")
        self.assertEqual(win.cv.bind("<ButtonRelease-2>"), "")
        self.assertEqual(win.cv.bind("<ButtonRelease-3>"), "")
        self.assertEqual(self.actions.calls, [])

    def test_the_overflow_menu_rows_use_the_same_path_with_the_prev_foreground_of_the_press(self):
        app, win = self.bar()
        self.src.procs.update({100 + i: ("p%d.exe" % i, FT + 10 + i) for i in range(60)})
        self.src.wins = [W(100 + i, "Window %d" % i, iconic=(i == 59)) for i in range(60)]
        self.src.fg = 100
        app._tick()
        more = win.buttons[-1]
        self.assertEqual(more["kind"], "more")
        popped = []
        win._popup = lambda m, x, y: popped.append(m)
        win._on_press(ev(more["x"] + 3))
        self.src.fg = 7777                                                   # the menu changed the foreground
        win._on_release(ev(more["x"] + 3))
        menu = popped[0]
        rest = more["rest"]
        menu.invoke(0)                                                       # first hidden row
        menu.invoke(menu.index("end"))                                       # the last row: the minimized window
        self.assertEqual(self.actions.calls, [("front", rest[0].hwnd), ("restore", 159)])
        # a hidden window that was ACTIVE when the "+N" button was pressed: its row minimizes it (same rule as a button)
        del self.actions.calls[:]
        self.src.fg = rest[0].hwnd
        app._tick()
        win._on_press(ev(more["x"] + 3))
        self.src.fg = 7777
        win._on_release(ev(more["x"] + 3))
        popped[1].invoke(0)
        self.assertEqual(self.actions.calls, [("minimize", rest[0].hwnd)])

    def test_a_failing_handler_and_a_failing_log_never_break_the_tk_callback(self):
        app, win = self.bar()
        b = self.btn(win, "Alpha")
        win.on_task = mock.Mock(side_effect=RuntimeError("boom"))
        bad = mock.Mock()
        for n in ("info", "warning", "error", "exception"):
            getattr(bad, n).side_effect = PermissionError("log file locked")
        with mock.patch.object(tasks, "LOG", bad):
            win._on_press(ev(b["x"] + 5))
            win._on_release(ev(b["x"] + 5))                                  # handler raises, log raises: nothing escapes
            win.foreground = mock.Mock(side_effect=OSError("x"))
            win._on_press(ev(b["x"] + 5))                                    # even the foreground read failing is contained
            win._on_release(ev(b["x"] + 5))
        self.assertTrue(bad.exception.called)

    def test_a_failure_in_the_click_itself_is_contained_too(self):
        """The release handler's own guard (not the inner one): e.g. building the "+N" menu fails."""
        app, win = self.bar()
        b = self.btn(win, "Alpha")
        bad = mock.Mock()
        for n in ("info", "warning", "error", "exception"):
            getattr(bad, n).side_effect = PermissionError("log file locked")
        with mock.patch.object(win, "_clicked", side_effect=RuntimeError("menu failed")),                 mock.patch.object(tasks, "LOG", bad):
            win._on_press(ev(b["x"] + 5))
            win._on_release(ev(b["x"] + 5))
        self.assertTrue(bad.exception.called)

    def test_tk_does_not_see_an_exception_through_the_real_event_machinery(self):
        app, win = self.bar()
        errors = []
        app.root.report_callback_exception = lambda *a: errors.append(a)
        win.on_task = mock.Mock(side_effect=RuntimeError("boom"))
        b = self.btn(win, "Alpha")
        with mock.patch.object(tasks, "LOG", mock.Mock(exception=mock.Mock(side_effect=PermissionError("x")))):
            win.cv.event_generate("<ButtonPress-1>", x=b["x"] + 5, y=10)
            win.cv.event_generate("<ButtonRelease-1>", x=b["x"] + 5, y=10)
            app.root.update()
        self.assertEqual(errors, [])


class TestTestMode(Clicks):
    def test_test_mode_records_and_never_touches_a_real_window(self):
        self.default_source = self.default_actions = True
        with mock.patch.object(tasks, "Win32Actions", side_effect=AssertionError("real actions in TEST mode")), \
                mock.patch.object(tasks, "Win32Source", side_effect=AssertionError("real source in TEST mode")):
            app = self.open(bar=ON, window=False, test_mode=True)
            win = app.bar.win
            b = win.buttons[1]
            self.assertIsInstance(app.bar.tasks.actions, tasks.FakeActions)
            win._on_press(ev(b["x"] + 5))
            win._on_release(ev(b["x"] + 5))
            self.assertEqual(app.bar.tasks.actions.calls, [("front", b["hwnd"])])

    def test_real_mode_builds_the_real_actions(self):
        self.default_actions = True                                          # (the source stays the made-up one)
        real = mock.Mock()
        with mock.patch.object(tasks, "Win32Actions", return_value=real) as w:
            app = self.open(bar=ON, test_mode=False)
            w.assert_called_once()
        self.assertIsNotNone(app.bar)


# --------------------------------------------------------------------------- the icon order
class TestIconOrder(unittest.TestCase):
    def make(self, packaged, cls="SomeClass", results=None):
        src = tasks.Win32Source()
        self.order = []
        results = results or {}

        def step(name):
            def f(*a):
                self.order.append(name)
                return results.get(name)
            return f
        src._text = lambda fn, h: cls
        src._packaged_window = lambda hwnd: packaged
        src._icon_window, src._icon_class, src._icon_exe = step("window"), step("class"), step("exe")
        return src

    def test_packaged_process_exe_then_window_then_class(self):
        src = self.make(True)
        self.assertIsNone(src.fetch_icon(5, "x.exe", 16))
        self.assertEqual(self.order, ["exe", "window", "class"])

    def test_plain_process_window_then_class_then_exe(self):
        src = self.make(False)
        self.assertIsNone(src.fetch_icon(5, "x.exe", 16))
        self.assertEqual(self.order, ["window", "class", "exe"])

    def test_the_first_icon_found_wins(self):
        src = self.make(True, results={"exe": "EXE", "window": "WIN"})
        self.assertEqual(src.fetch_icon(5, "x.exe", 16), "EXE")
        self.assertEqual(self.order, ["exe"])
        src = self.make(False, results={"class": "CLS", "exe": "EXE"})
        self.assertEqual(src.fetch_icon(5, "x.exe", 16), "CLS")
        self.assertEqual(self.order, ["window", "class"])

    def test_a_packaged_window_without_an_exe_icon_falls_through_to_its_own_icons(self):
        src = self.make(True, results={"window": "WIN"})
        self.assertEqual(src.fetch_icon(5, "x.exe", 16), "WIN")
        self.assertEqual(self.order, ["exe", "window"])

    def test_uwp_frame_asks_only_for_the_exe_icon_and_never_checks_packaging(self):
        src = self.make(True, cls=tasks.APP_FRAME_CLASS, results={"exe": "EXE"})
        src._packaged_window = mock.Mock(side_effect=AssertionError("not needed for a frame"))
        self.assertEqual(src.fetch_icon(5, "calc.exe", 16), "EXE")
        self.assertEqual(self.order, ["exe"])
        src = self.make(True, cls=tasks.APP_FRAME_CLASS)
        self.assertIsNone(src.fetch_icon(5, None, 16))
        self.assertEqual(self.order, ["exe"])                                # no window/class icon, ever

    def test_real_packaging_check_of_this_process_and_of_nothing(self):
        import tkinter as tk
        src = tasks.Win32Source()
        r = tk.Tk()
        self.addCleanup(r.destroy)
        r.update()
        self.assertFalse(src._packaged_window(r.winfo_id()))                 # python.exe is a plain exe
        self.assertFalse(src._packaged_window(0))
        self.assertFalse(src._packaged_window(2 ** 40))

    def test_real_packaging_answer_codes(self):
        """122 (insufficient buffer) and 0 mean packaged; 15700 (no application) means plain."""
        src = tasks.Win32Source()
        src._u = mock.Mock()
        src._k = mock.Mock()
        src._k.OpenProcess.return_value = 99
        # the pid comes back through a ctypes out-parameter: the made-up user32 fills it in
        src._u.GetWindowThreadProcessId.side_effect = lambda h, ref: setattr(ref._obj, "value", 4321) or 1
        for rc, want in ((122, True), (0, True), (15700, False), (87, False)):
            src._k.GetApplicationUserModelId.return_value = rc
            self.assertEqual(src._packaged_window(5), want, rc)
        src._k.CloseHandle.assert_called()


if __name__ == "__main__":
    unittest.main()
