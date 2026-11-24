"""v1.2 step 3d: right-click on a window button -> "Close window", separator, "Settings…". The empty bar and the "+N" button keep
only "Settings…". Close = WM_CLOSE posted to that window (never TerminateProcess). It counts as a command (step 3b: the
foreground is not given back), the button leaves the list by the normal scan, a window that is already gone or refuses
(elevated) is only logged. No test closes a real window: PostMessageW is made up, FakeActions only records."""
import ctypes
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import tasks  # noqa: E402
import test_v120_step3b as s3b  # noqa: E402
import strings as ui  # noqa: E402
from test_v120_step2 import FT, W  # noqa: E402
from test_v120_step3b import Menus, settle  # noqa: E402


def labels(menu):
    out = []
    last = menu.index("end")
    if last is None:                    # an EMPTY menu: no rows (the tests then fail on their assertion, not with an error)
        return out
    for i in range(last + 1):
        out.append("-" if menu.type(i) == "separator" else menu.entrycget(i, "label"))
    return out


class Base3d(Menus):
    def right_click_on(self, win, title):
        b = self.btn(win, title)
        win.cv.event_generate("<Button-3>", x=b["x"] + 5, y=10)
        win.top.update()


class TestMenuContent(Base3d):
    def test_a_window_button_gets_close_only(self):
        app, win = self.bar()
        self.stub_popup(win)
        self.right_click_on(win, "Beta")
        self.assertEqual(len(self.popups), 1)
        self.assertEqual(labels(self.popups[0]), ["Close window"])          # no separator, no Settings… (step 3e)
        self.assertEqual(ui.BAR_MENU_CLOSE, "Close window")
        self.assertEqual(win._task_menu.index("end"), 0)

    def test_the_empty_bar_keeps_settings_only(self):
        app, win = self.bar()
        self.stub_popup(win)
        self.right_click(win)                                   # x=5: the reserved left end, no button
        self.assertEqual(len(self.popups), 1)                   # (a clean FAIL if no menu opened at all)
        self.assertEqual(labels(self.popups[0]), ["Settings…"])
        win.cv.event_generate("<Button-3>", x=1500, y=10)       # right of the buttons, left of the date
        win.top.update()
        self.assertEqual(len(self.popups), 2)
        self.assertEqual(labels(self.popups[1]), ["Settings…"])

    def test_the_date_text_keeps_settings_only(self):
        app, win = self.bar()
        self.stub_popup(win)
        win.cv.event_generate("<Button-3>", x=1900, y=10)
        win.top.update()
        self.assertEqual(len(self.popups), 1)
        self.assertEqual(labels(self.popups[0]), ["Settings…"])

    def test_the_plus_n_button_keeps_settings_only(self):
        app, win = self.bar()
        self.src.procs.update({100 + i: ("p%d.exe" % i, FT + 10 + i) for i in range(60)})
        self.src.wins = [W(100 + i, "Window %d" % i) for i in range(60)]
        app._tick()
        more = win.buttons[-1]
        self.assertEqual(more["kind"], "more")
        self.stub_popup(win)
        win.cv.event_generate("<Button-3>", x=more["x"] + 3, y=10)
        win.top.update()
        self.assertEqual(len(self.popups), 1)
        self.assertEqual(labels(self.popups[0]), ["Settings…"])

    def test_the_plus_n_menu_rows_have_no_close(self):
        app, win = self.bar()
        self.src.procs.update({100 + i: ("p%d.exe" % i, FT + 10 + i) for i in range(60)})
        self.src.wins = [W(100 + i, "Window %d" % i) for i in range(60)]
        app._tick()
        more = win.buttons[-1]
        popped = []
        win._popup = lambda m, x, y: popped.append(m)
        win._on_press(s3b.ev(more["x"] + 3))
        win._on_release(s3b.ev(more["x"] + 3))
        self.assertEqual(len(popped), 1)
        self.assertNotIn("Close window", labels(popped[0]))

    def test_settings_of_the_empty_bar_menu_still_works(self):
        app, win = self.bar()
        called = []
        win._menu.entryconfigure(0, command=win._cmd(lambda: called.append(1)))
        self.stub_popup(win, during=lambda m: m.invoke(0))
        self.right_click(win)                                   # the empty bar
        settle(win)
        self.assertEqual(called, [1])
        self.assertEqual(self.actions.calls, [])                # a command: no give-back


class TestClose(Base3d):
    def test_close_goes_to_the_window_of_the_button_that_was_clicked(self):
        for title, hwnd in (("Alpha", 1), ("Beta", 2), ("Gamma", 3)):
            app, win = self.bar()
            self.stub_popup(win, during=lambda m: m.invoke(0))
            self.right_click_on(win, title)
            settle(win)
            self.assertEqual(self.actions.calls, [("close", hwnd)], title)
            self.actions.calls.clear()
            app.quit()
            self.apps.remove(app)

    def test_close_is_a_command_so_the_foreground_is_not_given_back(self):
        app, win = self.bar()
        self.src.fg = 1                                          # Alpha active; the bar takes it while the menu is open
        self.stub_popup(win, during=lambda m: m.invoke(0))
        self.right_click_on(win, "Gamma")
        settle(win, 250)
        self.assertEqual(self.actions.calls, [("close", 3)])     # no ("front", ...) afterwards

    def test_a_menu_closed_without_close_still_gives_the_foreground_back_and_closes_nothing(self):
        app, win = self.bar()
        self.stub_popup(win)
        self.right_click_on(win, "Gamma")
        settle(win)
        self.assertEqual(self.actions.calls, [("front", 2)])
        self.assertNotIn(("close", 3), self.actions.calls)

    def test_the_button_stays_until_the_normal_scan_drops_it(self):
        app, win = self.bar()
        self.stub_popup(win, during=lambda m: m.invoke(0))
        self.right_click_on(win, "Beta")
        settle(win)
        self.assertEqual([b["title"] for b in win.buttons], ["Alpha", "Beta", "Gamma"])      # nothing removed by hand
        self.src.wins = [W(1, "Alpha"), W(3, "Gamma")]                                       # the window really closes
        app._tick()
        self.assertEqual([b["title"] for b in win.buttons], ["Alpha", "Gamma"])

    def test_a_window_that_is_gone_or_refuses_is_only_logged(self):
        app, win = self.bar()
        self.actions.run = lambda action, hwnd: False
        self.stub_popup(win, during=lambda m: m.invoke(0))
        with mock.patch.object(tasks, "safe_log") as log:
            self.right_click_on(win, "Beta")
            settle(win)
        log.assert_any_call("info", "tasks: could not ask window %d to close", 2)
        self.assertEqual(len(self.popups), 1)

    def test_an_exception_in_the_action_never_reaches_tk(self):
        app, win = self.bar()
        self.actions.run = mock.Mock(side_effect=OSError("x"))
        self.stub_popup(win, during=lambda m: m.invoke(0))
        with mock.patch.object(tasks, "safe_log") as log:
            self.right_click_on(win, "Beta")
            settle(win)
        log.assert_any_call("exception", "tasks: close request failed")

    def test_a_failing_log_never_breaks_the_menu(self):
        app, win = self.bar()
        self.actions.run = lambda action, hwnd: False
        bad = mock.Mock()
        for n in ("info", "warning", "error", "exception"):
            getattr(bad, n).side_effect = PermissionError("locked")
        self.stub_popup(win, during=lambda m: m.invoke(0))
        with mock.patch.object(tasks, "LOG", bad):
            self.right_click_on(win, "Beta")
            settle(win)

    def test_close_while_the_bar_is_gone_does_nothing(self):
        app, win = self.bar()
        self.stub_popup(win, during=lambda m: m.invoke(0))
        app.stop_bar()
        win.on_close = None
        win._close(2)                                            # no handler: no error
        self.assertEqual(self.actions.calls, [])

    def test_tasks_off_there_is_no_button_to_close_and_nothing_breaks(self):
        app = self.open(bar=dict(__import__("test_v120_step1").ON, tasks={"enabled": False}), window=False)
        win = app.bar.win
        self.stub_popup(win)
        win.cv.event_generate("<Button-3>", x=200, y=10)
        win.top.update()
        self.assertEqual(len(self.popups), 1)
        self.assertEqual(labels(self.popups[0]), ["Settings…"])


class TestWin32Close(unittest.TestCase):
    """The real Win32Actions with a made-up user32: what is sent, and what is never called."""

    def make(self, is_window=1, post=1):
        a = tasks.Win32Actions()
        u = mock.Mock()
        u.IsWindow.return_value = is_window
        u.PostMessageW.return_value = post
        a._u = u
        return a, u

    def test_close_posts_wm_close_and_nothing_else(self):
        a, u = self.make()
        self.assertTrue(a.run("close", 4242))
        (h, msg, wp, lp), _ = u.PostMessageW.call_args
        self.assertEqual((h.value, msg, wp, lp), (4242, 0x0010, 0, 0))
        self.assertEqual([c[0] for c in u.method_calls], ["IsWindow", "PostMessageW"])    # no SetForegroundWindow, no ShowWindow

    def test_a_window_that_is_gone_is_refused_without_posting(self):
        a, u = self.make(is_window=0)
        self.assertFalse(a.run("close", 4242))
        u.PostMessageW.assert_not_called()

    def test_a_refused_post_returns_false(self):
        a, u = self.make(post=0)                                 # UIPI: an elevated window
        self.assertFalse(a.run("close", 4242))

    def test_other_actions_do_not_post_wm_close(self):
        for action in ("front", "minimize", "restore"):
            a, u = self.make()
            a.run(action, 7)
            u.PostMessageW.assert_not_called()

    def test_the_source_never_ends_a_process(self):
        import inspect
        src = inspect.getsource(tasks)
        self.assertNotIn("TerminateProcess", src)
        self.assertNotIn("TerminateProcess", inspect.getsource(sys.modules["barwin"]))

    def test_real_a_dead_handle_is_refused_by_the_real_api(self):
        a = tasks.Win32Actions()
        self.assertFalse(a.run("close", 0x7FFFFFF0))             # not a window: IsWindow says no, nothing is posted
        self.assertIs(a._u.PostMessageW.argtypes[1], ctypes.c_uint)


class TestTasksCloseWindow(unittest.TestCase):
    def test_close_window_uses_the_close_action_and_leaves_the_model_alone(self):
        actions = tasks.FakeActions()
        t = tasks.Tasks(tasks.FakeSource(["A", "B"]), mock.Mock(), lambda: None, make_photo=lambda i: i, actions=actions)
        t.start()
        before = list(t.model.entries)
        self.assertTrue(t.close_window(before[1].hwnd))
        self.assertEqual(actions.calls, [("close", before[1].hwnd)])
        self.assertEqual(list(t.model.entries), before)
        self.assertFalse(t.close_window(0))
        t2 = tasks.Tasks(tasks.FakeSource(["A"]), mock.Mock(), lambda: None, make_photo=lambda i: i)
        self.assertFalse(t2.close_window(5))                     # no actions object: nothing to do, no error


class TestQuitWithTheMenu(Base3d):
    def test_quit_order_is_unchanged(self):
        app, win = self.bar()
        orig = app.root.destroy
        app.root.destroy = lambda: (self.events.append("destroy"), orig())[1]
        app.quit()
        tail = self.events[self.events.index("HOOKS_ON"):]
        self.assertEqual([e for e in tail if e in ("REMOVE", "SHELLCLOSE", "destroy")], ["REMOVE", "SHELLCLOSE", "destroy"])


if __name__ == "__main__":
    unittest.main()
