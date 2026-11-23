"""v0.5.6: Settings consistency - nothing changes without Apply; 'Unsaved changes' question on X / panel switch;
confirmation before Revert to defaults / Factory settings; CHANGELOG section name."""
import copy
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tkinter as tk  # noqa: E402

import deskicons  # noqa: E402
import mpanels  # noqa: E402
import theme  # noqa: E402


class FakeBackend:
    def __init__(self):
        self.hidden = False

    def get_hidden(self):
        return self.hidden

    def set_hidden(self, hide):
        self.hidden = bool(hide)
        return True


class FakePanel:
    is_note = False
    is_calendar = False

    def __init__(self, **over):
        self.cfg = theme.sanitize_style(copy.deepcopy(mpanels.PANEL_FACTORY))
        self.cfg.update(over)
        self.applied = 0

    def apply_cfg(self):
        self.applied += 1


class FakeApp:
    """Just enough of App for SettingsWindow; never touches the real desktop, registry or config file."""
    def __init__(self, root):
        self.root = root
        self.test_mode = False
        self.panels = {"One": FakePanel(), "Two": FakePanel(opacity=0.5)}
        self.cfg = {"general": {"autostart": True, "lock_panels": False, "hide_desktop_icons": False,
                                "hide_icons_restore": None, "snap_enabled": True, "snap_preview": True,
                                "snap_distance": 24, "stack_gap": 8}}
        self.backend = FakeBackend()
        self.saves = 0
        self.icons = deskicons.IconHider(self.cfg["general"], self.backend, self.save)
        self.defaults_path = os.path.join(ROOT, "_no_such_defaults.json")

    @property
    def locked(self):
        return bool(self.cfg["general"].get("lock_panels"))

    def save(self):
        self.saves += 1

    def set_autostart(self, on):
        self.cfg["general"]["autostart"] = bool(on)
        self.save()

    def set_snapping(self, vals):
        self.cfg["general"].update(vals)

    def set_lock(self, on):
        self.cfg["general"]["lock_panels"] = bool(on)
        self.save()

    def snapping_defaults(self, factory=False):
        return {"snap_enabled": True, "snap_preview": True, "snap_distance": 24, "stack_gap": 2}

    def defaults(self, factory=False):
        d = {k: copy.deepcopy(v) for k, v in mpanels.PANEL_FACTORY.items()}
        return theme.sanitize_style(d)

    def do_rename(self, p, new):
        raise AssertionError("rename not expected")


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as e:
            raise unittest.SkipTest(str(e))
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def open(self, app=None, name="One"):
        app = app or FakeApp(self.root)
        w = mpanels.SettingsWindow(app, name)
        self.addCleanup(lambda: w.win.winfo_exists() and w.win.destroy())
        return app, w

    def answer(self, w, choice):
        """Make the 'Unsaved changes' question answer `choice`; returns the mock (to count calls)."""
        m = mock.Mock(return_value=choice)
        w.ask_unsaved = m
        return m


class TestNothingChangesWithoutApply(Base):
    def test_autostart_and_lock_wait_for_apply(self):
        app, w = self.open()
        w.cb_auto.invoke()
        w.cb_lock.invoke()
        self.assertTrue(app.cfg["general"]["autostart"], "autostart changed on click")
        self.assertFalse(app.cfg["general"]["lock_panels"], "lock changed on click")
        self.assertEqual(app.saves, 0, "config written before Apply")

    def test_apply_applies_and_writes(self):
        app, w = self.open()
        w.cb_auto.invoke()
        w.cb_lock.invoke()
        w.apply()
        self.assertFalse(app.cfg["general"]["autostart"])
        self.assertTrue(app.cfg["general"]["lock_panels"])
        self.assertGreater(app.saves, 0)
        self.assertFalse(w.dirty())

    def test_x_with_discard_changes_nothing(self):
        app, w = self.open()
        w.cb_auto.invoke()
        w.cb_lock.invoke()
        self.answer(w, "discard")
        w.close()
        self.assertFalse(w.win.winfo_exists())
        self.assertTrue(app.cfg["general"]["autostart"])
        self.assertFalse(app.cfg["general"]["lock_panels"])
        self.assertEqual(app.saves, 0)

    def test_test_mode_autostart_is_not_applied(self):
        app = FakeApp(self.root)
        app.test_mode = True
        _, w = self.open(app)
        w.v_auto.set(False)
        w.apply()
        self.assertTrue(app.cfg["general"]["autostart"])


class TestUnsavedChangesQuestion(Base):
    def test_x_clean_does_not_ask(self):
        app, w = self.open()
        m = self.answer(w, "cancel")
        w.close()
        m.assert_not_called()
        self.assertFalse(w.win.winfo_exists())

    def test_x_dirty_cancel_stays_open(self):
        app, w = self.open()
        w.v_op.set(40)
        m = self.answer(w, "cancel")
        w.close()
        m.assert_called_once()
        self.assertTrue(w.win.winfo_exists())
        self.assertEqual(w.v_op.get(), 40, "the edit must still be there after Cancel")
        self.assertEqual(app.panels["One"].cfg["opacity"], 0.95)

    def test_x_dirty_discard_closes_without_applying(self):
        app, w = self.open()
        w.v_op.set(40)
        self.answer(w, "discard")
        w.close()
        self.assertFalse(w.win.winfo_exists())
        self.assertEqual(app.panels["One"].cfg["opacity"], 0.95)
        self.assertEqual(app.saves, 0)

    def test_x_dirty_apply_applies_then_closes(self):
        app, w = self.open()
        w.v_op.set(40)
        self.answer(w, "apply")
        w.close()
        self.assertFalse(w.win.winfo_exists())
        self.assertAlmostEqual(app.panels["One"].cfg["opacity"], 0.40)
        self.assertGreater(app.saves, 0)

    def test_wm_delete_window_is_wired_to_close(self):
        _, w = self.open()
        self.assertNotEqual(w.win.protocol("WM_DELETE_WINDOW"), "")     # a Tcl command, not the default destroy

    def test_panel_switch_clean_does_not_ask(self):
        app, w = self.open()
        m = self.answer(w, "cancel")
        w.v["panel"].set("Two")
        w.request_select("Two")
        m.assert_not_called()
        self.assertEqual(w.cur, "Two")

    def test_panel_switch_cancel_stays(self):
        app, w = self.open()
        w.v_op.set(40)
        m = self.answer(w, "cancel")
        w.v["panel"].set("Two")                  # what the combobox does before the handler runs
        w.request_select("Two")
        m.assert_called_once()
        self.assertEqual(w.cur, "One")
        self.assertEqual(w.v["panel"].get(), "One", "combobox must go back to the current panel")
        self.assertEqual(w.v_op.get(), 40)

    def test_panel_switch_discard_drops_the_edit(self):
        app, w = self.open()
        w.v_op.set(40)
        self.answer(w, "discard")
        w.request_select("Two")
        self.assertEqual(w.cur, "Two")
        self.assertEqual(w.v_op.get(), 50)
        self.assertEqual(app.panels["One"].cfg["opacity"], 0.95)
        self.assertFalse(w.dirty())

    def test_panel_switch_apply_applies_first(self):
        app, w = self.open()
        w.v_op.set(40)
        self.answer(w, "apply")
        w.request_select("Two")
        self.assertEqual(w.cur, "Two")
        self.assertAlmostEqual(app.panels["One"].cfg["opacity"], 0.40)

    def test_general_change_alone_is_unsaved(self):
        app, w = self.open()
        w.cb_lock.invoke()
        self.assertTrue(w.dirty())
        m = self.answer(w, "cancel")
        w.request_select("Two")
        m.assert_called_once()
        self.assertEqual(w.cur, "One")

    def test_discard_also_reverts_general_checkboxes(self):
        app, w = self.open()
        w.cb_lock.invoke()
        self.answer(w, "discard")
        w.request_select("Two")
        self.assertFalse(w.v_lock.get())
        self.assertFalse(w.dirty())

    def test_fresh_window_is_clean(self):
        _, w = self.open()
        self.assertFalse(w.dirty())


class TestRealDialog(Base):
    """The real (not mocked) 'Unsaved changes' dialog: press each button by its label."""
    def press(self, w, label):
        def click():
            for top in w.win.winfo_children():
                if isinstance(top, tk.Toplevel):
                    def walk(x):
                        for c in x.winfo_children():
                            if c.winfo_class() == "TButton" and c.cget("text") == label:
                                c.invoke()
                                return True
                            if walk(c):
                                return True
                        return False
                    if walk(top):
                        return
            raise AssertionError("dialog or button not found")
        w.win.after(150, click)

    def test_buttons(self):
        for label, want in (("Apply", "apply"), ("Discard", "discard"), ("Cancel", "cancel")):
            _, w = self.open()
            self.press(w, label)
            self.assertEqual(w.ask_unsaved(), want)
            w.win.destroy()

    def test_dialog_text(self):
        _, w = self.open()
        seen = []

        def look():
            for top in w.win.winfo_children():
                if isinstance(top, tk.Toplevel):
                    seen.append(top.title())
                    for c in top.winfo_children():
                        if c.winfo_class() == "TLabel":
                            seen.append(c.cget("text"))
                    top.destroy()
        w.win.after(150, look)
        self.assertEqual(w.ask_unsaved(), "cancel")          # closing the dialog = Cancel
        self.assertIn("Unsaved changes — Apply / Discard / Cancel", seen)

    def test_x_to_apply_through_real_dialog(self):
        app, w = self.open()
        w.v_op.set(40)
        self.press(w, "Apply")
        w.close()
        self.assertFalse(w.win.winfo_exists())
        self.assertAlmostEqual(app.panels["One"].cfg["opacity"], 0.40)


class TestResetConfirmation(Base):
    def test_reset_asks_and_no_keeps_settings(self):
        for factory in (False, True):
            app, w = self.open()
            w.v_op.set(40)
            w.apply()
            w.confirm_overwrite = mock.Mock(return_value=False)
            w.reset(factory)
            w.confirm_overwrite.assert_called_once()
            self.assertAlmostEqual(app.panels["One"].cfg["opacity"], 0.40, msg="reset ran without consent")
            w.win.destroy()

    def test_reset_yes_overwrites(self):
        for factory in (False, True):
            app, w = self.open()
            w.v_op.set(40)
            w.apply()
            w.confirm_overwrite = mock.Mock(return_value=True)
            w.reset(factory)
            self.assertEqual(app.panels["One"].cfg["opacity"], mpanels.PANEL_FACTORY["opacity"])
            w.win.destroy()

    def test_confirmation_text(self):
        import strings
        self.assertEqual(strings.CONFIRM_OVERWRITE, "This will overwrite current settings. Continue?")
        self.assertEqual(strings.UNSAVED_MSG, "Unsaved changes — Apply / Discard / Cancel")
        with mock.patch.object(mpanels.messagebox, "askyesno", return_value=True) as m:
            _, w = self.open()
            self.assertTrue(w.confirm_overwrite())
            self.assertIn("overwrite current settings", m.call_args[0][1])


class TestChangelogSection(unittest.TestCase):
    def test_settings_is_a_known_section_and_used(self):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import test_v51
        self.assertIn("Settings", test_v51.SECTIONS)
        with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("### Settings", text)


if __name__ == "__main__":
    unittest.main()
