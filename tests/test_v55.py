"""v0.5.5: 'Hide desktop icons' in Settings > General is applied only by Apply; X / no Apply changes nothing."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tkinter as tk  # noqa: E402

import deskicons  # noqa: E402
import mpanels  # noqa: E402


class FakeBackend:
    """Stands in for Explorer: records every set_hidden call; never touches the real desktop."""
    def __init__(self):
        self.hidden, self.calls = False, []

    def get_hidden(self):
        return self.hidden

    def set_hidden(self, hide):
        self.calls.append(bool(hide))
        self.hidden = bool(hide)
        return True


class FakeApp:
    def __init__(self, root, test_mode=False):
        self.root = root
        self.test_mode = test_mode
        self.panels = {}
        self.locked = False
        self.cfg = {"general": {"autostart": True, "lock_panels": False, "hide_desktop_icons": False,
                                "hide_icons_restore": None, "snap_enabled": True, "snap_preview": True,
                                "snap_distance": 24, "stack_gap": 8}}
        self.backend = FakeBackend()
        self.saves = 0
        self.icons = deskicons.IconHider(self.cfg["general"], None if test_mode else self.backend, self._save)

    def _save(self):
        self.saves += 1

    def save(self):
        self._save()

    def set_autostart(self, on):
        self.cfg["general"]["autostart"] = bool(on)

    def set_snapping(self, vals):
        self.cfg["general"].update(vals)

    def set_lock(self, on):
        self.cfg["general"]["lock_panels"] = bool(on)


class TestHideIconsNeedsApply(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as e:           # no display
            raise unittest.SkipTest(str(e))
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def open(self, app):
        w = mpanels.SettingsWindow(app)
        self.addCleanup(lambda: w.win.winfo_exists() and w.win.destroy())
        return w

    def test_click_does_not_apply(self):
        app = FakeApp(self.root)
        w = self.open(app)
        w.cb_hide.invoke()                                   # the user ticks the box
        self.assertTrue(w.v_hide.get())
        self.assertEqual(app.backend.calls, [], "icons were hidden before Apply")
        self.assertFalse(app.cfg["general"]["hide_desktop_icons"])
        self.assertEqual(app.saves, 0, "config was written before Apply")

    def test_close_with_x_changes_nothing(self):
        app = FakeApp(self.root)
        w = self.open(app)
        w.cb_hide.invoke()
        w.win.destroy()                                      # window X (no Apply)
        self.assertEqual(app.backend.calls, [])
        self.assertFalse(app.cfg["general"]["hide_desktop_icons"])
        self.assertFalse(app.backend.hidden)
        w2 = self.open(app)                                  # reopening shows the stored state, not the dropped click
        self.assertFalse(w2.v_hide.get())

    def test_apply_hides_and_writes_config(self):
        app = FakeApp(self.root)
        w = self.open(app)
        w.cb_hide.invoke()
        w.apply()
        self.assertEqual(app.backend.calls, [True])
        self.assertTrue(app.backend.hidden)
        self.assertTrue(app.cfg["general"]["hide_desktop_icons"])
        self.assertGreater(app.saves, 0)

    def test_open_apply_close_open_apply(self):
        """open -> tick -> Apply -> close -> open -> untick -> Apply restores; a second Apply does nothing."""
        app = FakeApp(self.root)
        w = self.open(app)
        w.cb_hide.invoke()
        w.apply()
        w.win.destroy()
        w = self.open(app)
        self.assertTrue(w.v_hide.get())                      # state survived the close
        w.apply()                                            # unchanged: no extra Explorer call
        self.assertEqual(app.backend.calls, [True])
        w.cb_hide.invoke()                                   # untick
        self.assertTrue(app.backend.hidden, "restored before Apply")
        self.assertTrue(app.cfg["general"]["hide_desktop_icons"])
        w.apply()
        self.assertFalse(app.backend.hidden)
        self.assertFalse(app.cfg["general"]["hide_desktop_icons"])
        w.apply()
        self.assertEqual(app.backend.calls, [True, False])

    def test_untick_then_x_keeps_hidden(self):
        app = FakeApp(self.root)
        w = self.open(app)
        w.cb_hide.invoke()
        w.apply()
        w.cb_hide.invoke()                                   # untick, then X
        w.win.destroy()
        self.assertTrue(app.backend.hidden)
        self.assertTrue(app.cfg["general"]["hide_desktop_icons"])

    def test_test_mode_never_touches_icons(self):
        app = FakeApp(self.root, test_mode=True)
        w = self.open(app)
        w.v_hide.set(True)
        w.apply()
        self.assertEqual(app.backend.calls, [])
        self.assertFalse(app.cfg["general"]["hide_desktop_icons"])


if __name__ == "__main__":
    unittest.main()
