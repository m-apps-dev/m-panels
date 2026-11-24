"""v1.2 step 3b: the bar's menus and the foreground window. A pop-up menu closes on Escape / an outside click only when its
owner is the foreground window, so the bar takes the foreground just before a menu opens; the window that was active is
noted first (never one of OUR windows) and is given back when the menu closes without a command.
No test here changes the real foreground (winutil.take_foreground is replaced in Base); "real:" tests only read."""
import os
import sys
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import tasks  # noqa: E402
import winutil  # noqa: E402
from test_v120_step2 import FT, Clock, FakeLoader, Src, W  # noqa: E402
from test_v120_step3 import Clicks, ev  # noqa: E402

OWN_MIN = 9000                                        # made-up window handles >= this belong to "our" process


def settle(win, ms=120):
    """Let the 60 ms 'menu closed' decision run."""
    end = time.time() + ms / 1000
    while time.time() < end:
        win.top.update()
        time.sleep(0.01)


class Menus(Clicks):
    def setUp(self):
        super().setUp()
        self.src.is_own = lambda h: h >= OWN_MIN
        self.popups = []

    def bar(self, **kw):
        app, win = super().bar(**kw)
        app._tick()                                   # one scan: fg = Beta (2), the last external window
        return app, win

    def stub_popup(self, win, during=None):
        """The menu 'opens': the bar owns the foreground meanwhile; `during(menu)` can act (invoke a row...)."""
        def popup(m, x, y):
            self.events.append("POPUP")
            self.popups.append(m)
            self.src.fg = OWN_MIN                     # the bar (or its menu) holds the foreground while the menu is open
            if during:
                during(m)
        win._popup = popup

    def right_click(self, win):
        win.cv.event_generate("<Button-3>", x=5, y=5)
        win.top.update()


class TestRightClickMenu(Menus):
    def test_the_bar_takes_the_foreground_just_before_the_menu_opens(self):
        app, win = self.bar()
        self.stub_popup(win)
        self.right_click(win)
        self.assertIn("TAKE_FG", self.events)             # a clean FAIL (not a ValueError) if the bar never asked
        tail = self.events[self.events.index("TAKE_FG"):]
        self.assertEqual([e for e in tail if e in ("TAKE_FG", "POPUP", "WM_NULL")], ["TAKE_FG", "POPUP", "WM_NULL"])

    def test_closed_without_a_command_gives_the_foreground_back_to_the_window_that_was_active(self):
        app, win = self.bar()
        self.stub_popup(win)
        self.right_click(win)
        settle(win)
        self.assertEqual(self.actions.calls, [("front", 2)])

    def test_settings_chosen_nothing_is_given_back(self):
        app, win = self.bar()
        self.stub_popup(win, during=lambda m: m.invoke(0))
        called = []
        win._menu.entryconfigure(0, command=win._cmd(lambda: called.append(1)))
        self.right_click(win)
        settle(win)
        self.assertEqual(called, [1])
        self.assertEqual(self.actions.calls, [])

    def test_a_command_that_runs_just_after_the_menu_returned_is_still_seen(self):
        """Tk may run the chosen command from the idle loop right after tk_popup returned."""
        app, win = self.bar()
        self.stub_popup(win)
        win._menu.entryconfigure(0, command=win._cmd(lambda: None))
        self.right_click(win)
        win._menu.invoke(0)                           # arrives before the 60 ms decision
        settle(win)
        self.assertEqual(self.actions.calls, [])

    def test_real_settings_command_is_wrapped_and_opens_settings(self):
        app, win = self.bar()
        opened = []
        app._open_bar_settings = lambda: opened.append(1)
        win2 = type(win)(app.root, lambda: opened.append(1), app.popup)
        self.addCleanup(win2.destroy)
        win2._menu.invoke(0)
        self.assertEqual(opened, [1])
        self.assertTrue(win2._chosen)

    def test_if_the_user_clicked_another_window_to_close_the_menu_that_window_keeps_the_foreground(self):
        app, win = self.bar()
        self.stub_popup(win, during=lambda m: setattr(self, "later", True))
        self.right_click(win)
        self.src.fg = 3                               # the dismissing click landed on Gamma
        settle(win)
        self.assertEqual(self.actions.calls, [])

    def test_a_window_that_closed_meanwhile_is_not_an_error(self):
        app, win = self.bar()
        self.actions.run = lambda action, hwnd: False  # Win32Actions says: not a window any more
        self.stub_popup(win)
        self.right_click(win)
        settle(win)                                    # nothing raises

    def off(self):
        return self.open(bar=dict(__import__("test_v120_step1").ON, tasks={"enabled": False}), window=False)

    def test_tasks_off_the_menu_takes_the_foreground_and_gives_it_back(self):
        """Closing the sapma: with 'Show open windows' off the menu goes the same way (bar first, then give back)."""
        app = self.off()
        win = app.bar.win
        self.assertIsNone(app.bar.tasks)
        self.src.fg = 2                                # right click time: Beta is active (read from the system)
        self.stub_popup(win)
        self.right_click(win)
        settle(win)
        self.assertIn("TAKE_FG", self.events)             # a clean FAIL (not a ValueError) if the bar never asked
        tail = self.events[self.events.index("TAKE_FG"):]
        self.assertEqual([e for e in tail if e in ("TAKE_FG", "POPUP", "WM_NULL")], ["TAKE_FG", "POPUP", "WM_NULL"])
        self.assertEqual(self.actions.calls, [("front", 2)])

    def test_tasks_off_a_chosen_command_is_not_given_back(self):
        app = self.off()
        win = app.bar.win
        self.src.fg = 2
        self.stub_popup(win, during=lambda m: m.invoke(0))
        win._menu.entryconfigure(0, command=win._cmd(lambda: None))
        self.right_click(win)
        settle(win)
        self.assertEqual(self.actions.calls, [])

    def test_tasks_off_our_own_window_in_front_at_the_right_click_is_never_given_back(self):
        app = self.off()
        win = app.bar.win
        self.src.fg = OWN_MIN                          # a panel / Settings is active when the menu opens
        self.stub_popup(win)
        self.right_click(win)
        settle(win)
        self.assertEqual(self.actions.calls, [])

    def test_tasks_off_if_the_user_clicked_another_window_that_one_keeps_the_foreground(self):
        app = self.off()
        win = app.bar.win
        self.src.fg = 2
        self.stub_popup(win)
        self.right_click(win)
        self.src.fg = 3
        settle(win)
        self.assertEqual(self.actions.calls, [])

    def test_tasks_off_a_window_that_closed_meanwhile_is_not_an_error(self):
        app = self.off()
        win = app.bar.win
        self.src.fg = 2
        self.actions.run = lambda action, hwnd: False
        self.stub_popup(win)
        self.right_click(win)
        settle(win)

    def test_tasks_off_a_source_that_raises_never_breaks_the_menu(self):
        app = self.off()
        win = app.bar.win
        self.src.foreground = mock.Mock(side_effect=OSError("x"))
        self.stub_popup(win)
        self.right_click(win)
        settle(win)
        self.assertEqual(len(self.popups), 1)
        self.assertEqual(self.actions.calls, [])

    def test_toggling_tasks_keeps_the_menu_foreground_handling_on(self):
        app = self.off()
        self.assertTrue(app.bar.win.menu_foreground)
        app.bar.set_tasks({"enabled": True})
        self.assertTrue(app.bar.win.menu_foreground)
        app.bar.set_tasks({"enabled": False})
        self.assertTrue(app.bar.win.menu_foreground)
        self.src.fg = 2
        self.stub_popup(app.bar.win)
        self.right_click(app.bar.win)
        settle(app.bar.win)
        self.assertEqual(self.actions.calls, [("front", 2)])

    def test_the_decision_after_the_bar_is_gone_does_nothing(self):
        app, win = self.bar()
        self.stub_popup(win)
        self.right_click(win)
        app.stop_bar()
        win._finish_menu(2)                            # the pending 60 ms job meets a stopped bar: no error, no action
        self.assertEqual(self.actions.calls, [])

    def test_a_failing_take_foreground_never_breaks_the_menu(self):
        app, win = self.bar()
        self.stub_popup(win)
        with mock.patch.object(winutil, "take_foreground", side_effect=OSError("x")):
            self.right_click(win)
        self.assertEqual(len(self.popups), 1)


class TestPreviousActive(Menus):
    def test_a_press_while_the_foreground_is_ours_uses_the_last_external_window(self):
        """The reported bug: the bar/menu holds the foreground, the click on Beta's button must still see Beta as active."""
        app, win = self.bar()
        self.src.fg = OWN_MIN
        self.click(win, "Beta")
        self.assertEqual(self.actions.calls, [("minimize", 2)])

    def test_without_the_fix_a_normal_foreground_is_still_used(self):
        app, win = self.bar()
        self.src.fg = 1
        self.click(win, "Beta")
        self.assertEqual(self.actions.calls, [("front", 2)])

    def test_our_window_is_never_the_remembered_one(self):
        app, win = self.bar()
        t = app.bar.tasks
        for fg in (OWN_MIN, OWN_MIN + 5, 0):
            self.src.fg = fg
            t.scan()
        self.assertEqual(t.last_external, 2)
        self.src.fg = 3
        t.scan()
        self.assertEqual(t.last_external, 3)

    def test_nothing_external_seen_yet_gives_zero_not_our_window(self):
        t = tasks.Tasks(Src(), FakeLoader(), lambda: None, own_pid=5, now=Clock(), make_photo=lambda i: i,
                        actions=tasks.FakeActions())
        t.source.is_own = lambda h: True
        t.source.fg = 123
        self.assertEqual(t.previous_active(), 0)

    def test_the_plus_n_row_after_a_menu_that_took_the_foreground(self):
        app, win = self.bar()
        self.src.procs.update({100 + i: ("p%d.exe" % i, FT + 10 + i) for i in range(60)})
        self.src.wins = [W(100 + i, "Window %d" % i) for i in range(60)]
        self.src.fg = 100
        app._tick()
        more = win.buttons[-1]
        self.assertEqual(more["kind"], "more")
        self.stub_popup(win)
        win._on_press(ev(more["x"] + 3))
        win._on_release(ev(more["x"] + 3))
        self.assertEqual(self.events.count("TAKE_FG"), 1)
        menu = self.popups[0]
        settle(win)
        self.assertEqual(self.actions.calls, [("front", 100)])      # closed with no row chosen: back to Window 0
        del self.actions.calls[:]
        # a row chosen: that row decides, nothing is given back
        self.src.fg = 100
        win._on_press(ev(more["x"] + 3))
        win._on_release(ev(more["x"] + 3))
        menu2 = self.popups[1]
        menu2.invoke(0)
        settle(win)
        self.assertEqual(self.actions.calls, [("front", more["rest"][0].hwnd)])     # the row's own action, no give-back


class TestForegroundKeeper(unittest.TestCase):
    def make(self, fg):
        self.src = Src()
        self.src.fg = fg
        self.src.is_own = lambda h: h >= OWN_MIN
        self.actions = tasks.FakeActions()
        return tasks.ForegroundKeeper(self.src, self.actions)

    def test_previous_active_is_the_system_foreground_unless_it_is_ours(self):
        self.assertEqual(self.make(2).previous_active(), 2)
        self.assertEqual(self.make(OWN_MIN).previous_active(), 0)
        self.assertEqual(self.make(0).previous_active(), 0)

    def test_give_back_rules_are_the_tasks_rules(self):
        k = self.make(OWN_MIN)
        self.assertTrue(k.give_back(2))
        self.src.fg = 1
        self.assertFalse(k.give_back(2))
        self.assertFalse(k.give_back(0))
        self.assertEqual(self.actions.calls, [("front", 2)])


class TestTasksGiveBack(unittest.TestCase):
    def make(self):
        self.src = Src()
        self.src.procs = {1: ("a.exe", FT), 2: ("b.exe", FT + 1)}
        self.src.wins = [W(1, "A"), W(2, "B")]
        self.src.fg = 2
        self.src.is_own = lambda h: h >= OWN_MIN
        self.actions = tasks.FakeActions()
        t = tasks.Tasks(self.src, FakeLoader(), lambda: None, own_pid=5, now=Clock(), make_photo=lambda i: i,
                        actions=self.actions)
        t.start()
        return t

    def test_gives_back_only_while_the_foreground_is_ours(self):
        t = self.make()
        self.src.fg = OWN_MIN
        self.assertTrue(t.give_back(2))
        self.src.fg = 1
        self.assertFalse(t.give_back(2))
        self.src.fg = 0
        self.assertTrue(t.give_back(2))
        self.assertEqual(self.actions.calls, [("front", 2), ("front", 2)])

    def test_nothing_to_give_back(self):
        t = self.make()
        self.src.fg = OWN_MIN
        self.assertFalse(t.give_back(0))
        t.stop()
        self.assertFalse(t.give_back(2))
        self.assertEqual(self.actions.calls, [])

    def test_a_source_that_raises_never_raises_out(self):
        t = self.make()
        self.src.foreground = mock.Mock(side_effect=OSError("x"))
        self.assertEqual(t.previous_active(), 0)
        self.assertFalse(t.give_back(2))

    def test_a_failing_log_never_breaks_it(self):
        t = self.make()
        self.src.fg = OWN_MIN
        bad = mock.Mock()
        for n in ("info", "warning", "error", "exception"):
            getattr(bad, n).side_effect = PermissionError("locked")
        with mock.patch.object(tasks, "LOG", bad):
            self.assertTrue(t.give_back(2))


class TestRealRead(unittest.TestCase):
    def test_real_is_own_reads_the_owner_process(self):
        """real (read-only): a window of this process is ours, the shell window is not."""
        import tkinter as tk
        import ctypes
        src = tasks.Win32Source()
        root = tk.Tk()
        try:
            root.update()
            ours = int(ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id())
            self.assertTrue(src.is_own(ours))
            self.assertFalse(src.is_own(int(ctypes.windll.user32.GetShellWindow())))
        finally:
            root.destroy()

    def test_take_foreground_and_post_null_never_raise_on_a_dead_window(self):
        class Dead:
            def winfo_id(self):
                raise RuntimeError("gone")

            def frame(self):
                raise RuntimeError("gone")
        self.assertFalse(winutil.take_foreground(Dead()))
        winutil.post_null(Dead())


if __name__ == "__main__":
    unittest.main()
