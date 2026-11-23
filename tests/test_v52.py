"""v0.5.2: Quit path (source-level guards + helpers) and the status text; the real-process Quit test is in smoke.py."""
import ast
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import winutil  # noqa: E402
from calendar_panel import model  # noqa: E402


def poll_source():
    src = open(os.path.join(ROOT, "mpanels.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_poll":
            return node
    raise AssertionError("_poll not found")


class TestQuitRouting(unittest.TestCase):
    def test_quit_is_a_branch_of_cmd_not_of_cal(self):
        """The v0.5 bug: the 'quit' branch was nested under the 'cal' message kind and never ran."""
        fn = poll_source()
        for node in ast.walk(fn):
            if isinstance(node, ast.If) and "'cal'" in ast.unparse(node.test) and "kind" in ast.unparse(node.test):
                self.assertNotIn("quit", ast.unparse(node), "quit handled inside the 'cal' branch")
        self.assertIn("self.quit()", ast.unparse(fn))

    def test_quit_has_guard_steps_and_watchdog(self):
        src = open(os.path.join(ROOT, "mpanels.py"), encoding="utf-8").read()
        self.assertIn("os._exit(0)", src)
        self.assertIn("HARD_EXIT_SECONDS", src)
        self.assertIn("release_single_instance", src)
        self.assertIn("_quit_listener", src)


class TestHelpers(unittest.TestCase):
    def test_release_single_instance_is_idempotent(self):
        name = f"MPanels_Test_release_{os.getpid()}"
        self.assertTrue(winutil.acquire_single_instance(name))
        winutil.release_single_instance()
        winutil.release_single_instance()
        # after releasing, the name is free again
        self.assertTrue(winutil.acquire_single_instance(name))
        winutil.release_single_instance()

    def test_quit_event_is_separate_from_raise(self):
        name = f"MPanels_Test_evt_{os.getpid()}"
        import threading
        got_raise, got_quit = threading.Event(), threading.Event()
        a = winutil.start_instance_listener(name, got_raise.set)
        b = winutil.start_instance_listener(name, got_quit.set, winutil.QUIT)
        try:
            self.assertTrue(winutil.signal_running_instance(name, retries=3, kind=winutil.QUIT))
            self.assertTrue(got_quit.wait(3))
            self.assertFalse(got_raise.is_set())
        finally:
            a.stop()
            b.stop()

    def test_model_stop_silences_notifications(self):
        calls = []
        m = model.CalendarModel(notify=lambda: calls.append(1))
        m.stop()
        m._notify()
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
