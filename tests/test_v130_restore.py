"""v1.3: restore from a settings backup (Settings > General > Restore from backup...).
B1 backup.py (list, 'same as any backup', prepare_restore, write_restore), B2 App (pending_restore written as the very
last step of quit), B3 the Settings window (list dialog, confirmation, texts).
Everything runs in temporary folders with a made-up desktop; the real config.json, backups\\, desktop and windows are never
touched; every dialog (list, confirmation, warning, color chooser) is replaced or driven by the test."""
import datetime
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import backup  # noqa: E402
import mpanels  # noqa: E402
import strings as ui  # noqa: E402
from test_v120_step1 import Base as AppBase  # noqa: E402

T0 = datetime.datetime(2026, 11, 25, 8, 51, 0)


def cfg_bytes(panels=("Sample",), **general):
    d = {"panels": {n: {"x": 10, "y": 10} for n in panels}, "general": dict(general)}
    return json.dumps(d, indent=2).encode("utf-8")


class Folder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mpanels_t130r_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cfg = os.path.join(self.tmp, "config.json")
        self.bdir = backup.backup_dir(self.cfg)

    def put(self, name, data):
        os.makedirs(self.bdir, exist_ok=True)
        with open(os.path.join(self.bdir, name), "wb") as f:
            f.write(data)

    def write_cfg(self, data):
        with open(self.cfg, "wb") as f:
            f.write(data)

    def read(self, path):
        with open(path, "rb") as f:
            return f.read()


# --------------------------------------------------------------------------- B1: list_backups
class TestListBackups(Folder):
    def test_newest_first_with_flags_names_and_time(self):
        self.put("config-20261123-100000.json", cfg_bytes(("A",)))
        self.put("config-20261125-085100.json", cfg_bytes(("Sample", "Notes", "Calendar")))
        self.put("config-20261124-120000.json", cfg_bytes(()))
        got = backup.list_backups(self.bdir)
        self.assertEqual([e["name"] for e in got], ["config-20261125-085100.json", "config-20261124-120000.json",
                                                    "config-20261123-100000.json"])
        self.assertEqual([e["newest"] for e in got], [True, False, False])
        self.assertEqual(got[0]["when"], T0)
        self.assertEqual((got[0]["readable"], got[0]["panel_count"], got[0]["panel_names"]),
                         (True, 3, ["Sample", "Notes", "Calendar"]))
        self.assertEqual((got[1]["readable"], got[1]["panel_count"]), (True, 0))
        self.assertEqual(got[0]["path"], os.path.join(self.bdir, "config-20261125-085100.json"))

    def test_unreadable_kinds_never_raise(self):
        self.put("config-20261101-000001.json", b"{not json")
        self.put("config-20261101-000002.json", b"[1, 2, 3]")
        self.put("config-20261101-000003.json", b'{"general": {}}')
        self.put("config-20261101-000004.json", b'{"panels": [1]}')
        self.put("config-20261101-000005.json", b"\xff\xfe\x00bad")
        self.put("config-20261101-000006.json", b"")
        got = backup.list_backups(self.bdir)
        self.assertEqual(len(got), 6)
        for e in got:
            self.assertFalse(e["readable"], e["name"])
            self.assertEqual((e["panel_count"], e["panel_names"]), (0, []))

    def test_empty_missing_and_foreign_files(self):
        self.assertEqual(backup.list_backups(self.bdir), [])                 # folder does not exist
        os.makedirs(self.bdir)
        self.assertEqual(backup.list_backups(self.bdir), [])                 # folder is empty
        self.put("notes.txt", b"x")
        self.put("config-2026.json", cfg_bytes())
        os.makedirs(os.path.join(self.bdir, "config-20261101-000001.json"))  # a folder with our kind of name
        self.assertEqual(backup.list_backups(self.bdir), [])

    def test_only_one_entry_is_newest(self):
        for i in range(1, 6):
            self.put("config-2026110%d-000000.json" % i, cfg_bytes())
        self.assertEqual([e["newest"] for e in backup.list_backups(self.bdir)], [True] + [False] * 4)


class TestRowText(unittest.TestCase):
    def entry(self, newest=False, readable=True, when=T0, **kinds):
        k = {"shortcut": 0, "note": 0, "calendar": 0, "other": 0}
        k.update(kinds)
        n = sum(k.values()) if readable else 0
        return {"name": "config-20261125-085100.json", "when": when, "readable": readable, "panel_count": n,
                "panel_names": ["Secret%d" % i for i in range(n)], "kinds": k, "newest": newest, "path": "x"}

    def test_the_documented_row(self):
        self.assertEqual(backup.row_text(self.entry(shortcut=9, note=6, calendar=3, when=datetime.datetime(2026, 11, 25, 11, 19))),
                         "25 Nov 2026 11:19 — 18 panels: 9 Shortcuts, 6 Notes, 3 Calendars")

    def test_panel_names_are_never_shown(self):
        self.assertNotIn("Secret", backup.row_text(self.entry(shortcut=2, note=1)))

    def test_only_kinds_with_a_count_in_a_fixed_order(self):
        self.assertEqual(backup.row_text(self.entry(calendar=2, shortcut=1)), "25 Nov 2026 08:51 — 3 panels: 1 Shortcut, 2 Calendars")
        self.assertEqual(backup.row_text(self.entry(note=4)), "25 Nov 2026 08:51 — 4 panels: 4 Notes")
        self.assertEqual(backup.row_text(self.entry(other=2, note=1, shortcut=1, calendar=1)),
                         "25 Nov 2026 08:51 — 5 panels: 1 Shortcut, 1 Note, 1 Calendar, 2 Other")

    def test_singular_and_plural(self):
        self.assertEqual(backup.row_text(self.entry(note=1, calendar=1)), "25 Nov 2026 08:51 — 2 panels: 1 Note, 1 Calendar")
        self.assertEqual(backup.row_text(self.entry(calendar=2)), "25 Nov 2026 08:51 — 2 panels: 2 Calendars")
        self.assertEqual(backup.row_text(self.entry(shortcut=1, newest=True)), "25 Nov 2026 08:51 — 1 panel: 1 Shortcut (newest)")

    def test_empty_row(self):
        self.assertEqual(backup.row_text(self.entry()), "25 Nov 2026 08:51 — 0 panels")

    def test_long_rows_are_cut_but_keep_the_newest_tag(self):
        t = backup.row_text(self.entry(newest=True, shortcut=1234567, note=1234567, calendar=1234567, other=1234567))
        self.assertTrue(t.endswith("… (newest)"), t)
        self.assertLessEqual(len(t), backup.ROW_MAX + len(" (newest)"))
        self.assertTrue(t.startswith("25 Nov 2026 08:51 — 4938268 panels: 1234567 Shortcuts"))

    def test_unreadable_row(self):
        self.assertEqual(backup.row_text(self.entry(readable=False)), "25 Nov 2026 08:51 — unreadable")
        self.assertEqual(backup.row_text(self.entry(readable=False, newest=True)), "25 Nov 2026 08:51 — unreadable (newest)")

    def test_month_names_do_not_depend_on_the_locale(self):
        e = self.entry(when=datetime.datetime(2026, 3, 2, 9, 5))
        self.assertTrue(backup.row_text(e).startswith("2 Mar 2026 09:05 — "))


class TestPanelKinds(Folder):
    def test_kinds_are_counted_from_the_backup(self):
        panels = {"a": {"type": "shortcut"}, "b": {"x": 1}, "c": {"type": "note"}, "d": {"type": "calendar"},
                  "e": {"type": "weird"}, "f": {"type": None}, "g": 5, "h": {"type": ["note"]}}
        self.put("config-20261125-085100.json", json.dumps({"panels": panels}).encode("utf-8"))
        e = backup.list_backups(self.bdir)[0]
        self.assertEqual(e["kinds"], {"shortcut": 2, "note": 1, "calendar": 1, "other": 4})   # a, b | c | d | e, f, g, h
        self.assertEqual(backup.row_text(e), "25 Nov 2026 08:51 — 8 panels: 2 Shortcuts, 1 Note, 1 Calendar, 4 Other (newest)")

    def test_a_panel_without_a_type_is_a_shortcut_panel(self):
        self.assertEqual(backup.panel_kind({}), "shortcut")
        self.assertEqual(mpanels.PANEL_STATE["type"], "shortcut")      # the program's default, which backup.panel_kind follows

    def test_unreadable_has_no_kinds_counted(self):
        self.put("config-20261125-085100.json", b"{nope")
        self.assertEqual(backup.list_backups(self.bdir)[0]["kinds"], {"shortcut": 0, "note": 0, "calendar": 0, "other": 0})


# --------------------------------------------------------------------------- B1: 'same as ANY backup'
class TestSameAsAnyBackup(Folder):
    def test_content_equal_to_an_older_backup_is_not_saved_again(self):
        self.write_cfg(cfg_bytes(("A",)))
        backup.make_backup(self.cfg, now=T0)
        self.write_cfg(cfg_bytes(("B",)))
        backup.make_backup(self.cfg, now=T0 + datetime.timedelta(minutes=1))
        self.write_cfg(cfg_bytes(("A",)))                        # equal to the OLDEST, not to the newest
        self.assertIsNone(backup.make_backup(self.cfg, now=T0 + datetime.timedelta(minutes=2)))
        self.assertEqual(len(backup.backup_names(self.bdir)), 2)

    def test_new_content_is_still_saved(self):
        self.write_cfg(cfg_bytes(("A",)))
        backup.make_backup(self.cfg, now=T0)
        self.write_cfg(cfg_bytes(("C",)))
        self.assertIsNotNone(backup.make_backup(self.cfg, now=T0 + datetime.timedelta(minutes=1)))
        self.assertEqual(len(backup.backup_names(self.bdir)), 2)


# --------------------------------------------------------------------------- B1: prepare_restore / write_restore
class TestPrepareRestore(Folder):
    def test_selected_content_survives_even_when_the_rotation_deletes_that_backup(self):
        keep = backup.KEEP
        for i in range(keep):                                   # a full folder; the OLDEST one is chosen
            self.put("config-20260101-0000%02d.json" % i, cfg_bytes(("Old%d" % i,)))
        oldest = os.path.join(self.bdir, "config-20260101-000000.json")
        want = self.read(oldest)
        self.write_cfg(cfg_bytes(("Current",)))
        got = backup.prepare_restore(self.cfg, oldest)
        self.assertFalse(os.path.exists(oldest))                # the backup of the current config pushed it out
        self.assertEqual(got, want)                             # ...but its bytes were read first
        self.assertEqual(len(backup.backup_names(self.bdir)), keep)
        newest = self.read(os.path.join(self.bdir, backup.backup_names(self.bdir)[-1]))
        self.assertEqual(newest, cfg_bytes(("Current",)))       # the current config is now a backup

    def test_the_chosen_file_is_checked_before_anything_else_happens(self):
        self.write_cfg(cfg_bytes(("Current",)))
        self.put("config-20261101-000001.json", b"{broken")
        with self.assertRaises(ValueError):
            backup.prepare_restore(self.cfg, os.path.join(self.bdir, "config-20261101-000001.json"))
        self.assertEqual(backup.backup_names(self.bdir), ["config-20261101-000001.json"])   # no backup was made
        with self.assertRaises(ValueError):
            backup.prepare_restore(self.cfg, os.path.join(self.bdir, "config-20990101-000000.json"))
        self.assertEqual(self.read(self.cfg), cfg_bytes(("Current",)))                      # config untouched

    def test_hide_icons_restore_of_the_current_config_is_kept(self):
        self.put("config-20261101-000001.json", cfg_bytes(("Old",), hide_icons_restore=None, autostart=False))
        self.write_cfg(cfg_bytes(("Now",), hide_icons_restore=True))
        got = json.loads(backup.prepare_restore(self.cfg, os.path.join(self.bdir, "config-20261101-000001.json")))
        self.assertIs(got["general"]["hide_icons_restore"], True)
        self.assertIs(got["general"]["autostart"], False)        # everything else comes from the backup
        self.assertEqual(list(got["panels"]), ["Old"])

    def test_current_none_replaces_a_recorded_value_of_the_backup(self):
        self.put("config-20261101-000001.json", cfg_bytes(("Old",), hide_icons_restore=False))
        self.write_cfg(cfg_bytes(("Now",), hide_icons_restore=None))
        got = json.loads(backup.prepare_restore(self.cfg, os.path.join(self.bdir, "config-20261101-000001.json")))
        self.assertIsNone(got["general"]["hide_icons_restore"])

    def test_bytes_are_untouched_when_the_value_already_matches(self):
        raw = cfg_bytes(("Old",), hide_icons_restore=True)
        self.put("config-20261101-000001.json", raw)
        self.write_cfg(cfg_bytes(("Now",), hide_icons_restore=True))
        self.assertEqual(backup.prepare_restore(self.cfg, os.path.join(self.bdir, "config-20261101-000001.json")), raw)


class TestBackupMustSucceedForARestore(Folder):
    def setUp(self):
        super().setUp()
        self.write_cfg(cfg_bytes(("Now",)))
        self.put("config-20261101-000001.json", cfg_bytes(("Old",)))
        self.chosen = os.path.join(self.bdir, "config-20261101-000001.json")

    def test_copy_error_raises_in_strict_mode_only(self):
        with mock.patch.object(backup.shutil, "copyfile", side_effect=OSError("disk full")):
            with self.assertRaises(backup.BackupFailed):
                backup.make_backup(self.cfg, strict=True)
            self.assertIsNone(backup.make_backup(self.cfg))             # the start-up path still swallows it

    def test_a_copy_that_leaves_no_file_or_a_different_file_is_a_failure(self):
        with mock.patch.object(backup.shutil, "copyfile", lambda a, b: None):          # "succeeds", writes nothing
            with self.assertRaises(backup.BackupFailed):
                backup.make_backup(self.cfg, strict=True)

        def short(a, b):
            with open(b, "wb") as f:
                f.write(b"{")
        with mock.patch.object(backup.shutil, "copyfile", short):
            with self.assertRaises(backup.BackupFailed):
                backup.make_backup(self.cfg, strict=True)

    def test_prepare_restore_stops_when_the_backup_fails_and_changes_nothing(self):
        before = self.read(self.cfg)
        with mock.patch.object(backup.shutil, "copyfile", side_effect=OSError("denied")):
            with self.assertRaises(backup.BackupFailed):
                backup.prepare_restore(self.cfg, self.chosen)
        self.assertEqual(self.read(self.cfg), before)
        self.assertEqual(backup.backup_names(self.bdir), ["config-20261101-000001.json"])

    def test_an_unwritable_backup_folder_is_a_failure_too(self):
        with mock.patch.object(backup.os, "makedirs", side_effect=PermissionError("no")):
            with self.assertRaises(backup.BackupFailed):
                backup.prepare_restore(self.cfg, self.chosen)

    def test_skipped_because_an_identical_backup_exists_is_a_success(self):
        self.put("config-20261102-000001.json", cfg_bytes(("Now",)))                  # same bytes as the current config
        with mock.patch.object(backup.shutil, "copyfile", side_effect=OSError("must not be called")):
            self.assertIsNone(backup.make_backup(self.cfg, strict=True))
            self.assertEqual(backup.prepare_restore(self.cfg, self.chosen), cfg_bytes(("Old",)))

    def test_no_current_config_is_a_success(self):
        os.remove(self.cfg)
        self.assertEqual(backup.prepare_restore(self.cfg, self.chosen), cfg_bytes(("Old",)))

    def test_a_rotation_error_after_a_good_copy_does_not_stop_a_restore(self):
        with mock.patch.object(backup.os, "remove", side_effect=OSError("locked")):
            keep = 1                                                                  # the chosen file is "too old"
            self.assertTrue(backup.make_backup(self.cfg, keep=keep, strict=True))


class TestWriteRestore(Folder):
    def test_writes_atomically_and_leaves_no_temp_file(self):
        self.write_cfg(cfg_bytes(("Now",)))
        data = cfg_bytes(("Restored",))
        self.assertTrue(backup.write_restore(self.cfg, data))
        self.assertEqual(self.read(self.cfg), data)
        self.assertEqual(os.listdir(self.tmp), ["config.json"])

    def test_a_write_error_leaves_the_current_config_alone(self):
        keep = cfg_bytes(("Now",))
        self.write_cfg(keep)
        with mock.patch.object(backup.os, "replace", side_effect=OSError("disk full")):
            self.assertFalse(backup.write_restore(self.cfg, cfg_bytes(("Restored",))))
        self.assertEqual(self.read(self.cfg), keep)
        self.assertEqual(os.listdir(self.tmp), ["config.json"])      # the temp file is removed too

    def test_an_error_while_writing_the_temp_file_leaves_the_config_alone(self):
        keep = cfg_bytes(("Now",))
        self.write_cfg(keep)
        with mock.patch.object(backup.os, "fsync", side_effect=OSError("io")):
            self.assertFalse(backup.write_restore(self.cfg, cfg_bytes(("Restored",))))
        self.assertEqual(self.read(self.cfg), keep)

    def test_hide_icons_restore_is_taken_from_the_config_as_it_is_at_write_time(self):
        self.write_cfg(cfg_bytes(("Now",), hide_icons_restore=None))          # quit's icon restore already cleared it
        data = cfg_bytes(("Restored",), hide_icons_restore=True)             # what prepare_restore saw earlier
        backup.write_restore(self.cfg, data)
        self.assertIsNone(json.loads(self.read(self.cfg))["general"]["hide_icons_restore"])


# --------------------------------------------------------------------------- B2/B3: the real App (test mode)
class AppCase(AppBase):
    def setUp(self):
        super().setUp()
        for p in (mock.patch.object(mpanels.colorchooser, "askcolor", return_value=(None, None)),
                  mock.patch.object(mpanels.messagebox, "askyesno", return_value=False),
                  mock.patch.object(mpanels.messagebox, "showinfo"),
                  mock.patch.object(mpanels.messagebox, "showwarning")):
            p.start()
            self.addCleanup(p.stop)
        self.cfg_path = os.path.join(self.data, "config.json")
        self.bdir = os.path.join(self.data, "backups")

    def put(self, name, data):
        os.makedirs(self.bdir, exist_ok=True)
        with open(os.path.join(self.bdir, name), "wb") as f:
            f.write(data)
        return os.path.join(self.bdir, name)

    def disk(self):
        with open(self.cfg_path, "rb") as f:
            return f.read()

    def start(self, panels=("Now",), **general):
        os.makedirs(self.data, exist_ok=True)
        with open(self.cfg_path, "wb") as f:
            f.write(cfg_bytes(panels, **general))
        return self.open(test_mode=True)


class TestPendingRestoreInQuit(AppCase):
    def test_the_restored_file_is_written_after_every_save_in_quit(self):
        app = self.start()
        path = self.put("config-20261101-000001.json", cfg_bytes(("Old1", "Old2")))
        log = []
        real_save, real_wr = app.save, backup.write_restore
        app.save = lambda: (log.append("save"), real_save())[1]
        app.icons.on_quit = lambda: log.append("icons.on_quit")
        app.icons.save = lambda: log.append("icons.save")
        app._quit_bar = lambda: log.append("bar")
        real_destroy = app.root.destroy
        app.root.destroy = lambda: (log.append("destroy"), real_destroy())[1]
        for p in app.panels.values():
            p.save_note = lambda: log.append("note")
        with mock.patch.object(backup, "write_restore", side_effect=lambda *a: (log.append("WRITE"), real_wr(*a))[1]):
            self.assertTrue(app.request_restore(path))
        self.assertEqual(log.count("WRITE"), 1)
        self.assertEqual(log[-1], "WRITE")                                  # the very last step, even after root.destroy
        self.assertEqual(log[-2], "destroy")
        self.assertGreaterEqual(log.count("save"), 2)                       # request_restore's save + quit's save
        self.assertLess(max(i for i, x in enumerate(log) if x in ("save", "icons.on_quit", "icons.save", "bar")),
                        log.index("WRITE"))

    def test_a_real_save_during_quit_does_not_overwrite_the_restored_file(self):
        app = self.start()
        want = cfg_bytes(("Old1", "Old2"))
        path = self.put("config-20261101-000001.json", want)
        self.assertTrue(app.request_restore(path))
        self.assertEqual(self.disk(), want)
        self.assertIsNone(app.pending_restore)

    def test_the_current_settings_were_backed_up_first(self):
        app = self.start(("Now",))
        path = self.put("config-20261101-000001.json", cfg_bytes(("Old",)))
        app.request_restore(path)
        saved = []
        for n in sorted(os.listdir(self.bdir)):
            with open(os.path.join(self.bdir, n), "rb") as f:
                saved.append(json.loads(f.read()))
        self.assertTrue(any(list(d["panels"]) == ["Now"] for d in saved))

    def test_a_failed_backup_of_the_current_settings_stops_the_restore(self):
        app = self.start()
        path = self.put("config-20261101-000001.json", cfg_bytes(("Old",)))
        before = self.disk()
        with mock.patch.object(backup.shutil, "copyfile", side_effect=OSError("disk full")),                 self.assertLogs("mpanels", level="WARNING") as logs:
            self.assertFalse(app.request_restore(path))
        self.assertFalse(app._quitting)
        self.assertIsNone(app.pending_restore)
        self.assertEqual(app.restore_failure, "Could not back up the current settings, so nothing was restored.")
        self.assertTrue(any("not backed up" in m for m in logs.output), logs.output)
        self.assertIn("Now", json.loads(self.disk())["panels"])
        self.assertEqual(json.loads(self.disk())["panels"].keys(), json.loads(before)["panels"].keys())

    def test_a_restore_after_a_failure_can_be_tried_again(self):
        app = self.start()
        path = self.put("config-20261101-000001.json", cfg_bytes(("Old",)))
        with mock.patch.object(backup.shutil, "copyfile", side_effect=OSError("disk full")):
            self.assertFalse(app.request_restore(path))
        self.assertTrue(app.request_restore(path))
        self.assertIsNone(app.restore_failure)
        self.assertEqual(self.disk(), cfg_bytes(("Old",)))

    def test_skipping_the_backup_because_it_already_exists_still_restores(self):
        app = self.start()
        path = self.put("config-20261101-000001.json", cfg_bytes(("Old",)))
        app.save()
        self.put("config-20261102-000001.json", self.disk())                          # the current config is already a backup
        with mock.patch.object(backup.shutil, "copyfile", side_effect=OSError("must not be needed")):
            self.assertTrue(app.request_restore(path))
        self.assertEqual(self.disk(), cfg_bytes(("Old",)))

    def test_no_restore_without_a_request(self):
        app = self.start()
        before = self.disk()
        app.quit()
        self.assertEqual(app.pending_restore, None)
        self.assertNotEqual(json.loads(self.disk())["panels"].keys(), {"Old"})
        self.assertIn("Now", json.loads(self.disk())["panels"])
        del before

    def test_a_bad_backup_changes_nothing_and_keeps_running(self):
        app = self.start()
        bad = self.put("config-20261101-000001.json", b"{nope")
        self.assertFalse(app.request_restore(bad))
        self.assertFalse(app._quitting)
        self.assertIsNone(app.pending_restore)
        self.assertIn("Now", json.loads(self.disk())["panels"])

    def test_a_write_failure_keeps_the_current_config(self):
        app = self.start()
        path = self.put("config-20261101-000001.json", cfg_bytes(("Old",)))
        with mock.patch.object(backup.os, "replace", side_effect=OSError("denied")):
            app.request_restore(path)
        d = json.loads(self.disk())
        self.assertIn("Now", d["panels"])                                   # the config quit saved is intact and valid
        self.assertFalse(os.path.exists(self.cfg_path + ".restore.tmp"))

    def test_hide_icons_restore_ends_as_the_current_config_has_it_after_quit(self):
        app = self.start(hide_icons_restore=True)
        path = self.put("config-20261101-000001.json", cfg_bytes(("Old",), hide_icons_restore=False))
        app.request_restore(path)
        d = json.loads(self.disk())
        self.assertEqual(list(d["panels"]), ["Old"])
        self.assertIs(d["general"].get("hide_icons_restore"), True)


class TestSettingsUi(AppCase):
    def settings(self):
        app = self.start()
        app.open_settings()
        w = app.settings_win
        self.addCleanup(self._close, w)
        return app, w

    @staticmethod
    def _close(w):
        try:
            if w.win.winfo_exists():
                w.win.destroy()
        except Exception:                                   # noqa: BLE001  (the app already quit and took Tk with it)
            pass

    def entry(self, name="config-20261101-000001.json"):
        return next(e for e in backup.list_backups(self.bdir) if e["name"] == name)

    def drive(self, w, fn):
        """Replace the modal wait of the list dialog by `fn(dialog)`; always closes the dialog."""
        def wait(d):
            try:
                fn(d)
            finally:
                if d.winfo_exists():
                    d.destroy()
        w.win.wait_window = wait

    def test_group_and_button_exist_and_need_no_apply(self):
        app, w = self.settings()
        self.assertEqual(w.btn_restore.cget("text"), "Restore from backup…")
        self.assertFalse(w.dirty())

    def test_empty_list_shows_the_text_and_cannot_restore(self):
        app, w = self.settings()
        seen = {}
        self.drive(w, lambda d: seen.update(box=w.restore_list))
        self.assertIsNone(w.choose_backup([]))
        self.assertIsNone(seen["box"])
        self.assertEqual(ui.RESTORE_EMPTY,
                         "No backups yet. M Panels saves a copy of your settings at start when they changed.")

    def test_unreadable_rows_are_grey_and_cannot_be_chosen(self):
        app, w = self.settings()
        self.put("config-20261101-000001.json", cfg_bytes(("Good",)))
        self.put("config-20261102-000001.json", b"{bad")                    # the newer one is unreadable
        entries = [self.entry("config-20261102-000001.json"), self.entry()]
        out = {}

        def pick(d):
            box = w.restore_list
            out["texts"] = [box.get(i) for i in range(box.size())]
            out["fg"] = [box.itemcget(i, "foreground") for i in range(box.size())]
            box.selection_set(0)                                            # the unreadable one
            w.btn_restore_go.invoke()                                       # even without the deselect: not accepted
            out["alive_raw"] = d.winfo_exists()
            w.restore_on_select()                                         # what Tk calls on <<ListboxSelect>>
            d.update()
            out["sel_bad"] = box.curselection()
            w.btn_restore_go.invoke()                                       # nothing selected: nothing happens
            out["alive"] = d.winfo_exists()
            box.selection_set(1)
            w.restore_on_select()                                         # what Tk calls on <<ListboxSelect>>
            d.update()
            w.btn_restore_go.invoke()
        self.drive(w, pick)
        got = w.choose_backup(entries)
        self.assertEqual(out["sel_bad"], ())
        self.assertTrue(out["alive"])
        self.assertTrue(out["alive_raw"])
        self.assertEqual(got["name"], "config-20261101-000001.json")
        self.assertTrue(out["texts"][0].endswith("unreadable"), out["texts"])
        self.assertEqual(out["texts"][1], "1 Nov 2026 00:00 — 1 panel: 1 Shortcut")
        self.assertNotEqual(out["fg"][0], out["fg"][1])

    def test_cancel_in_the_list_changes_nothing(self):
        app, w = self.settings()
        self.put("config-20261101-000001.json", cfg_bytes(("Old",)))
        self.drive(w, lambda d: None)                                       # the dialog is closed without a choice
        with mock.patch.object(app, "request_restore") as rr, mock.patch.object(w, "confirm_restore") as cr:
            w.restore_from_backup()
        rr.assert_not_called()
        cr.assert_not_called()
        self.assertFalse(app._quitting)

    def test_cancel_at_the_confirmation_changes_nothing(self):
        app, w = self.settings()
        before = self.disk()
        self.put_dir()
        files = sorted(os.listdir(self.bdir))
        entry = self.entry()
        w.choose_backup = lambda entries: entry
        with mock.patch.object(mpanels.messagebox, "askyesno", return_value=False) as ask, \
                mock.patch.object(app, "request_restore") as rr:
            w.restore_from_backup()
        ask.assert_called_once()
        rr.assert_not_called()
        self.assertFalse(app._quitting)
        self.assertIsNone(app.pending_restore)
        self.assertEqual(self.disk(), before)
        self.assertEqual(sorted(os.listdir(self.bdir)), files)              # no new backup either

    def put_dir(self):
        self.put("config-20261101-000001.json", cfg_bytes(("Old",)))
        return self.bdir

    def test_confirmed_restore_goes_through_request_restore(self):
        app, w = self.settings()
        self.put_dir()
        entry = self.entry()
        w.choose_backup = lambda entries: entry
        with mock.patch.object(mpanels.messagebox, "askyesno", return_value=True) as ask, \
                mock.patch.object(app, "request_restore", return_value=True) as rr:
            w.restore_from_backup()
        rr.assert_called_once_with(entry["path"])
        text = ask.call_args.args[1]
        self.assertIn("backed up first", text)
        self.assertIn("stay on disk", text)
        self.assertIn("will not be opened", text)
        self.assertIn("M Panels will close. Start it again from the desktop shortcut.", text)
        self.assertIn("1 Nov 2026 00:00", text)

    def test_a_refused_restore_shows_a_warning_and_the_app_keeps_running(self):
        app, w = self.settings()
        self.put_dir()
        entry = self.entry()
        w.choose_backup = lambda entries: entry
        with mock.patch.object(mpanels.messagebox, "askyesno", return_value=True), \
                mock.patch.object(app, "request_restore", return_value=False), \
                mock.patch.object(mpanels.messagebox, "showwarning") as warn:
            w.restore_from_backup()
        warn.assert_called_once()
        self.assertEqual(warn.call_args.args[1], ui.MSG_RESTORE_BAD)

    def test_a_failed_backup_shows_the_message_and_the_app_keeps_running(self):
        app, w = self.settings()
        self.put_dir()
        entry = self.entry()
        w.choose_backup = lambda entries: entry
        with mock.patch.object(mpanels.messagebox, "askyesno", return_value=True),                 mock.patch.object(mpanels.messagebox, "showwarning") as warn,                 mock.patch.object(backup.shutil, "copyfile", side_effect=OSError("disk full")):
            w.restore_from_backup()
        warn.assert_called_once()
        self.assertEqual(warn.call_args.args[1], ui.MSG_RESTORE_NO_BACKUP)
        self.assertFalse(app._quitting)
        self.assertIn("Now", json.loads(self.disk())["panels"])

    def test_end_to_end_through_the_settings_window(self):
        app, w = self.settings()
        want = cfg_bytes(("Old1",))
        self.put("config-20261101-000001.json", want)
        entry = self.entry()
        w.choose_backup = lambda entries: entry
        with mock.patch.object(mpanels.messagebox, "askyesno", return_value=True):
            w.restore_from_backup()
        self.assertEqual(self.disk(), want)


class TestTexts(unittest.TestCase):
    def test_help_describes_the_new_way_and_not_the_manual_copy(self):
        gen = " ".join(dict(ui.HELP_SECTIONS)["General"])
        self.assertIn("Restore from backup", gen)
        self.assertNotIn("copy a backup over", gen)

    def test_readme_and_changelog(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
            readme = f.read()
        self.assertIn("Restore from backup", readme)
        self.assertNotIn("copy a backup over", readme)
        with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
            log = f.read()
        unreleased = log.split("## 1.2.0")[0]
        self.assertIn("### Backups", unreleased)
        self.assertIn("Restore from backup", unreleased)

    def test_all_new_strings_are_english(self):
        for name in dir(ui):
            if name.startswith(("RESTORE_", "CONFIRM_RESTORE", "BTN_RESTORE", "MSG_RESTORE", "LBL_BACKUPS")):
                v = getattr(ui, name)
                self.assertFalse([c for c in v if c in "ğüşöçıİĞÜŞÖÇ"], name)


if __name__ == "__main__":
    print("python:", sys.executable)
    unittest.main()
