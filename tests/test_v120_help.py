"""v1.2 Help/About update: the Help text (sections, length, language, no stale values, interface names that match
strings.py), the two About lines, the Settings tab order (General first and shown), and the "no panels" behaviour
(bar stays, the program keeps running, New panel works). Nothing asks Windows: the fakes of test_v120_step1 are used."""
import os
import re
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import calendar_panel  # noqa: E402
import fileops  # noqa: E402
import mpanels  # noqa: E402
import strings as ui  # noqa: E402
import test_v120_step1 as s1  # noqa: E402
from version import __version__  # noqa: E402

HEADINGS = ("What M Panels does", "Shortcut panels", "Note panels", "Calendar panels", "Snapping and stacks",
            "Several monitors", "The bar", "Open windows", "Search", "Start button", "General", "Known limitations")


def help_items():
    return [i for _, items in ui.HELP_SECTIONS for i in items]


def help_blob():
    return "\n".join(help_items())


def all_ui_strings():
    """Every user-visible string in strings.py (plain strings, and the strings inside dicts, lists and tuples)."""
    out = []

    def add(v):
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                add(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                add(x)

    for k, v in vars(ui).items():
        if k.isupper() and k != "HELP_SECTIONS":
            add(v)
    return out


def exists_in_strings(name):
    for v in all_ui_strings():
        if v == name or v.startswith(name + " (") or v.replace("{text}", "…") == name:
            return True
    return name == "Apply / Discard / Cancel" and "Apply / Discard / Cancel" in ui.UNSAVED_MSG


# every interface name the Help uses; each must be in the Help text AND be a real string of strings.py
UI_NAMES = ("Close window", "Settings…", "Show Start button", "Show bar", "Show open windows", "Show window titles",
            "Show 'Search Windows' row", "Include Store apps", "Reset", "Reset colors", "Open Google Calendar",
            "Import from M Calendar config…", "Make current Calendar look the default", "Show / Hide", "New panel",
            "Quit", "Apply / Discard / Cancel", "Search Windows for '…'", "Win+Alt+Space", "Ctrl+Shift+Space", "Off",
            "Shortcut key", "Lock panels", "Hide desktop icons", "Start with Windows", "Open file location", "Rename…",
            "Return to desktop", "Clear formatting", "Snapping", "Colors", "Search", "General", "Bar", "Calendar",
            "List", "Day", "Week", "Open", "Bold", "Italic", "Underline", "Color…", "Font…", "Size")
# Settings paths in the Help: tab, then the group / checkbox / button on it
SETTINGS_PATHS = ("Settings › Bar › Show bar", "Settings › Bar › Colors", "Settings › Bar › Search",
                  "Settings › Bar › Show Start button", "Settings › General › Snapping", "Settings › Calendar",
                  "Settings › Calendar › Import from M Calendar config…")


class TestHelpText(unittest.TestCase):
    def test_headings_and_order(self):
        self.assertEqual(tuple(h for h, _ in ui.HELP_SECTIONS), HEADINGS)

    def test_general_stays_last_but_known_limitations(self):
        heads = [h for h, _ in ui.HELP_SECTIONS]
        self.assertEqual(heads[-2:], ["General", "Known limitations"])

    def test_every_bullet_is_short_and_not_empty(self):
        for h, items in ui.HELP_SECTIONS:
            self.assertTrue(items, h)
            for i in items:
                self.assertLess(len(i), 140, i)
                self.assertTrue(i.strip(), h)

    def test_english_only(self):
        self.assertFalse([c for c in help_blob() if c in "ğüşöçıİĞÜŞÖÇ"])

    def test_no_version_number(self):
        self.assertNotRegex(help_blob(), r"\d+\.\d+\.\d+")

    def test_known_limitations_has_seven_items(self):
        self.assertEqual(len(dict(ui.HELP_SECTIONS)["Known limitations"]), 7)

    def test_no_stale_values_or_internal_terms(self):
        blob = help_blob()
        for bad in ("96", "AppBar", "SendInput", "NOACTIVATE", "WM_CLOSE", "px"):
            self.assertNotIn(bad, blob)

    def test_the_deleted_sentence_is_gone_and_the_true_one_is_there(self):
        blob = help_blob()
        self.assertNotIn("Nothing is ever permanently deleted", blob)
        self.assertIn("Your files and notes are never deleted by the program; only the oldest settings backups are.", blob)

    def test_use_it_your_way_items(self):
        items = dict(ui.HELP_SECTIONS)["What M Panels does"]
        self.assertIn("Use it your way: panels only, the bar only, or both.", items)
        self.assertIn("Panels only: leave the bar off (the default). Bar only: turn on Settings › Bar › Show bar and "
                      "delete the %s panel." % ui.DEFAULT_PANEL_NAME, items)
        self.assertEqual(ui.DEFAULT_PANEL_NAME, "Sample")

    def test_nothing_says_the_general_panel_comes_back(self):
        blob = help_blob()
        self.assertNotIn("'General' panel", blob)
        self.assertNotIn("created at the first start", blob)
        self.assertNotIn("again at any start", blob)

    def test_open_windows_has_no_look_item(self):
        self.assertFalse([i for i in dict(ui.HELP_SECTIONS)["Open windows"] if "looks dim" in i or "colored frame" in i])

    def test_interface_names_are_in_the_help_and_in_strings(self):
        blob = help_blob()
        for name in UI_NAMES:
            self.assertTrue(exists_in_strings(name), "not a real interface text in strings.py: %r" % name)
        for name in UI_NAMES[:UI_NAMES.index("Shortcut key") + 1]:
            self.assertIn(name, blob, "the Help should name %r" % name)

    def test_settings_paths_use_real_tab_and_group_names(self):
        blob = help_blob()
        for p in SETTINGS_PATHS:
            self.assertIn(p, blob)
            parts = p.split(" › ")[1:]
            self.assertIn(parts[0], (ui.TAB_BAR, ui.TAB_GENERAL, ui.TAB_CALENDAR))
            if len(parts) > 1:
                self.assertTrue(exists_in_strings(parts[1]), parts[1])
        for tab in set(re.findall(r"Settings › (\w+)", blob)):
            self.assertIn(tab, (ui.TAB_BAR, ui.TAB_GENERAL, ui.TAB_CALENDAR), tab)

    def test_the_tray_menu_names_are_the_real_ones(self):
        tray = "Tray icon: %s, %s, %s and %s." % (ui.TRAY_SHOW_HIDE, ui.TRAY_NEW, ui.TRAY_SETTINGS, ui.TRAY_QUIT)
        self.assertTrue(any(i.startswith(tray) for i in dict(ui.HELP_SECTIONS)["General"]))

    def test_shortcut_names_are_the_real_labels(self):
        blob = help_blob()
        for label in ui.SEARCH_HOTKEY_LABELS.values():
            self.assertIn(label, blob)

    def test_backup_count_is_the_real_one(self):
        import backup
        self.assertEqual(backup.KEEP, 15)
        self.assertIn("the last %d are kept" % backup.KEEP, help_blob())


class TestAboutLines(s1.Base):
    def test_lines_come_from_strings_and_the_version_label_is_untouched(self):
        app = self.open()
        app.open_settings()
        w = app.settings_win
        self.addCleanup(lambda: w.win.winfo_exists() and w.win.destroy())
        self.assertEqual(ui.ABOUT_LICENSE_LINE, "MIT License · Copyright (c) 2026 M-Apps")
        self.assertEqual(ui.ABOUT_REPO_LINE, "github.com/m-apps-dev/m-panels")
        self.assertEqual(w.about_license.cget("text"), ui.ABOUT_LICENSE_LINE)
        self.assertEqual(w.about_repo.cget("text"), ui.ABOUT_REPO_LINE)
        self.assertEqual(w.about_ver.cget("text"), ui.ABOUT_VER_PREFIX + __version__)
        self.assertNotIn("http", ui.ABOUT_REPO_LINE)                  # plain text, never a link

    def test_help_is_what_the_about_text_shows(self):
        app = self.open()
        app.open_settings()
        w = app.settings_win
        self.addCleanup(lambda: w.win.winfo_exists() and w.win.destroy())
        w.v_about.set("help")
        w.show_about()
        shown = w.about_text.get("1.0", "end")
        for h in HEADINGS:
            self.assertIn(h, shown)

    def test_whats_new_starts_with_the_current_version(self):
        """The first line of What's new is the running version (an '## Unreleased' heading would be skipped and
        leave the previous release on top)."""
        app = self.open()
        app.open_settings()
        w = app.settings_win
        self.addCleanup(lambda: w.win.winfo_exists() and w.win.destroy())
        w.v_about.set("news")
        w.show_about()
        first = w.about_text.get("1.0", "end").splitlines()[0]
        self.assertTrue(first.startswith(ui.ABOUT_VER_PREFIX + __version__ + ui.ABOUT_DATE_SEP), first)
        self.assertNotIn("Unreleased", w.about_text.get("1.0", "end"))


class TestTabOrder(s1.Base):
    def names(self, w):
        return [w.nb.tab(t, "text") for t in w.nb.tabs()]

    def test_general_is_first_and_selected_for_a_shortcut_panel(self):
        app = self.open()
        app.new_panel("Docs")
        app.open_settings("Docs")
        w = app.settings_win
        self.addCleanup(lambda: w.win.winfo_exists() and w.win.destroy())
        self.assertEqual(self.names(w), ["General", "Panel", "Title", "Content", "Bar", "About"])
        self.assertEqual(w.nb.index(w.nb.select()), 0)
        self.assertEqual(w.nb.select(), str(w.tab["general"]))

    def test_general_is_selected_when_opened_from_the_tray_and_with_no_panel_name(self):
        app = self.open()
        app.open_settings()
        w = app.settings_win
        self.addCleanup(lambda: w.win.winfo_exists() and w.win.destroy())
        self.assertEqual(w.nb.select(), str(w.tab["general"]))

    @unittest.skipUnless(calendar_panel.AVAILABLE, "calendar libraries not installed")
    def test_calendar_tab_sits_after_content_and_before_bar_and_general_stays_first(self):
        app = self.open()
        app.new_panel("Cal", "calendar")
        app.new_panel("Docs")
        app.open_settings("Cal")
        w = app.settings_win
        self.addCleanup(lambda: w.win.winfo_exists() and w.win.destroy())
        self.assertEqual(self.names(w), ["General", "Panel", "Title", "Content", "Calendar", "Bar", "About"])
        self.assertEqual(w.nb.select(), str(w.tab["general"]))
        w.select("Docs")                                           # leaving the calendar panel removes the tab
        self.assertEqual(self.names(w), ["General", "Panel", "Title", "Content", "Bar", "About"])
        w.select("Cal")
        self.assertEqual(self.names(w), ["General", "Panel", "Title", "Content", "Calendar", "Bar", "About"])

    def test_tab_contents_did_not_change(self):
        app = self.open()
        app.open_settings()
        w = app.settings_win
        self.addCleanup(lambda: w.win.winfo_exists() and w.win.destroy())
        self.assertEqual([k for k, _ in w.TABS], ["general", "panel", "title", "content", "calendar", "bar", "about"])
        for key in ("cb_lock", "cb_auto", "cb_hide"):
            self.assertTrue(hasattr(w, key), key)


# --------------------------------------------------------------------------- B: no panels at all
class TestNoPanels(s1.Base):
    def remove_all(self, app):
        for p in list(app.panels.values()):
            r = app.remove_panel(p, confirm=False)
            self.assertTrue(r.ok)
        s1.pump(app)

    def test_first_start_without_a_config_creates_the_sample_panel(self):
        app = self.open()
        self.assertEqual(list(app.panels), ["Sample"])
        self.assertEqual(ui.DEFAULT_PANEL_NAME, "Sample")

    def test_with_a_config_and_no_shortcut_panel_no_panel_is_made(self):
        self.write_cfg({})
        app = self.open()
        self.assertEqual(app.panels, {})
        self.assertFalse(os.path.isdir(app.ctx.panel_path("Sample")))

    def test_only_a_note_panel_means_no_new_panel_at_the_next_start(self):
        app = self.open()
        self.remove_all(app)
        app.new_panel("Only a note", "note")
        app.save()
        app.quit()
        self.apps.remove(app)
        app2 = self.open()
        self.assertEqual(list(app2.panels), ["Only a note"])

    def test_removing_every_panel_stays_empty_after_a_restart(self):
        app = self.open()
        self.remove_all(app)
        app.save()
        app.quit()
        self.apps.remove(app)
        app2 = self.open()
        self.assertEqual(app2.panels, {})

    def test_an_existing_general_panel_is_left_alone_and_no_sample_is_added(self):
        self.write_cfg({})
        os.makedirs(self.desk, exist_ok=True)
        ctx = fileops.Ctx(self.desk, self.pub)
        fileops.ensure_panels_root(ctx)
        fileops.create_panel(ctx, "General")
        app = self.open()
        self.assertEqual(list(app.panels), ["General"])

    def test_bar_stays_and_the_program_keeps_running_with_zero_panels(self):
        app = self.open(s1.THREE, bar=s1.ON)
        self.assertIsNotNone(app.bar)
        self.remove_all(app)
        self.assertEqual(app.panels, {})
        self.assertIsNotNone(app.bar)                                  # the bar is still there
        self.assertEqual(self.windows[0].shows[-1][:2], (0, 0))        # it was not hidden or moved
        self.assertNotIn("REMOVE", self.be.names())                   # the screen strip was not given back
        self.assertEqual(self.disp.system[0].work[1], s1.H)           # the work area still starts below the bar
        self.assertFalse(app._quitting)
        self.assertTrue(app.root.winfo_exists())
        app._displays_now()                                            # a screen re-check with no panels: no error
        app.relayout_all()
        s1.pump(app, 20)
        self.assertIsNotNone(app.bar)
        self.assertFalse(app._quitting)

    def test_new_panel_works_after_the_last_panel_is_gone(self):
        app = self.open(s1.THREE, bar=s1.ON)
        self.remove_all(app)
        p = app.new_panel("Again")
        s1.pump(app)
        self.assertIsNotNone(p)
        self.assertEqual(list(app.panels), ["Again"])
        self.assertIsNotNone(app.bar)
        n = app.new_panel("Notes", "note")
        self.assertIsNotNone(n)
        self.assertEqual(sorted(app.panels), ["Again", "Notes"])

    def test_the_removed_panels_items_go_back_to_the_desktop_and_the_folder_is_moved_not_deleted(self):
        app = self.open()
        p = app.panels[ui.DEFAULT_PANEL_NAME]
        item = os.path.join(app.ctx.panel_path(p.name), "keep.txt")
        with open(item, "w") as f:
            f.write("x")
        r = app.remove_panel(p, confirm=False)
        self.assertTrue(r.ok)
        self.assertTrue(os.path.isfile(os.path.join(self.desk, "keep.txt")))             # the file is back, not deleted
        self.assertTrue(os.path.isdir(app.ctx.trash))
        self.assertTrue(os.listdir(app.ctx.trash))                                       # the folder was moved there

    def test_hide_desktop_icons_default_is_off(self):
        app = self.open()
        self.assertFalse(app.cfg["general"]["hide_desktop_icons"])


class TestResetWithoutAPanel(s1.Base):
    """Settings > Revert to defaults / Factory settings work with no panel: the general boxes are reset, the
    panel-only fields are skipped, and the confirmation question is still asked."""

    def open_empty(self):
        self.write_cfg({"bar": s1.ON})
        app = self.open()
        self.assertEqual(app.panels, {})
        app.open_settings()
        w = app.settings_win
        self.addCleanup(lambda: w.win.winfo_exists() and w.win.destroy())
        self.assertEqual(w.cur, "")
        return app, w

    def edit(self, w):
        w.v_snap_dist.set("40")
        w.v_stack_gap.set("9")
        w.v_snap.set(False)
        w.v_bar_date.set(False)

    def test_revert_to_defaults_resets_snapping_and_leaves_the_bar_boxes(self):
        app, w = self.open_empty()
        self.edit(w)
        with mock.patch.object(w, "confirm_overwrite", return_value=True) as ask:
            w.reset(False)
        ask.assert_called_once()
        self.assertEqual((w.v_snap_dist.get(), w.v_stack_gap.get(), bool(w.v_snap.get())), ("24", "2", True))
        self.assertFalse(w.v_bar_date.get())                          # Revert never touches the bar
        self.assertIn(ui.MSG_DEFAULTS_LOADED, w.msg.cget("text"))

    def test_factory_settings_reset_snapping_and_the_bar_boxes_and_apply_decides(self):
        app, w = self.open_empty()
        self.edit(w)
        with mock.patch.object(w, "confirm_overwrite", return_value=True):
            w.reset(True)
        self.assertEqual((w.v_snap_dist.get(), w.v_stack_gap.get(), bool(w.v_snap.get())), ("24", "2", True))
        self.assertFalse(w.v_bar.get())                               # the factory bar is off
        self.assertTrue(w.v_bar_date.get())
        self.assertIn(ui.MSG_FACTORY_LOADED, w.msg.cget("text"))
        self.assertIn(ui.MSG_BAR_PENDING.strip(), w.msg.cget("text"))
        self.assertIsNotNone(app.bar)                                 # only loaded into the boxes
        w.apply()
        self.assertIsNone(app.bar)
        self.assertEqual(app.cfg["bar"], s1.infoclock.defaults())

    def test_the_question_is_still_asked_and_no_answers_changes_nothing(self):
        app, w = self.open_empty()
        self.edit(w)
        for factory in (False, True):
            with mock.patch.object(w, "confirm_overwrite", return_value=False) as ask:
                w.reset(factory)
            ask.assert_called_once()
            self.assertEqual(w.v_snap_dist.get(), "40")
            self.assertFalse(w.v_bar_date.get())


if __name__ == "__main__":
    unittest.main()
