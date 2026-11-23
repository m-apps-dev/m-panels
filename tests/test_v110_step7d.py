"""v1.1.0 step 7d: automatic config backup (backups\\config-YYYYMMDD-HHMMSS.json, 15 at most)."""
import datetime
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
import fileops  # noqa: E402
import mpanels  # noqa: E402
import winutil  # noqa: E402
from fakedisplays import THREE, FakeClock, FakeDisplays  # noqa: E402

T0 = datetime.datetime(2026, 11, 23, 10, 0, 0)


def content(n):
    # bytes on purpose: CRLF, non-ASCII and trailing spaces must survive byte for byte
    return ('{\r\n  "general": {},\r\n  "marker": "ğüş %d  "\r\n}\r\n' % n).encode("utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mpanels_t110s7d_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cfg = os.path.join(self.tmp, "config.json")
        self.bdir = os.path.join(self.tmp, "backups")

    def write(self, data):
        with open(self.cfg, "wb") as f:
            f.write(data)

    def names(self):
        return sorted(os.listdir(self.bdir)) if os.path.isdir(self.bdir) else []

    def read_backup(self, name):
        with open(os.path.join(self.bdir, name), "rb") as f:
            return f.read()


class TestBackupFunction(Base):
    def test_copy_is_byte_identical_and_named_by_time(self):
        self.write(content(1))
        dest = backup.make_backup(self.cfg, now=T0)
        self.assertEqual(os.path.basename(dest), "config-20261123-100000.json")
        self.assertEqual(self.read_backup("config-20261123-100000.json"), content(1))

    def test_no_config_no_backup_and_no_folder(self):
        self.assertIsNone(backup.make_backup(self.cfg, now=T0))
        self.assertFalse(os.path.exists(self.bdir))

    def test_same_content_as_the_newest_is_not_backed_up_again(self):
        self.write(content(1))
        backup.make_backup(self.cfg, now=T0)
        self.assertIsNone(backup.make_backup(self.cfg, now=T0 + datetime.timedelta(hours=1)))
        self.assertEqual(len(self.names()), 1)

    def test_changed_content_is_backed_up(self):
        self.write(content(1))
        backup.make_backup(self.cfg, now=T0)
        self.write(content(2))
        backup.make_backup(self.cfg, now=T0 + datetime.timedelta(minutes=1))
        self.assertEqual(len(self.names()), 2)
        self.assertEqual(self.read_backup(self.names()[-1]), content(2))

    def test_going_back_to_an_older_content_counts_as_new_only_against_the_newest(self):
        self.write(content(1))
        backup.make_backup(self.cfg, now=T0)
        self.write(content(2))
        backup.make_backup(self.cfg, now=T0 + datetime.timedelta(minutes=1))
        self.write(content(1))                                       # equal to the OLDER one, not the newest
        backup.make_backup(self.cfg, now=T0 + datetime.timedelta(minutes=2))
        self.assertEqual(len(self.names()), 3)

    def test_same_second_different_content_gets_the_next_free_name(self):
        self.write(content(1))
        backup.make_backup(self.cfg, now=T0)
        self.write(content(2))
        backup.make_backup(self.cfg, now=T0)
        self.assertEqual(self.names(), ["config-20261123-100000.json", "config-20261123-100001.json"])
        self.assertEqual(self.read_backup(self.names()[-1]), content(2))

    def test_the_16th_different_backup_deletes_the_oldest_and_nothing_else(self):
        os.makedirs(self.bdir)
        others = ["notes.txt", "config-abc.json", "config-20200101-000000.json.bak", "config-2020010-000000.json",
                  "xconfig-20200101-000000.json"]
        for n in others:
            with open(os.path.join(self.bdir, n), "w") as f:
                f.write("keep me")
        os.makedirs(os.path.join(self.bdir, "config-20200101-000000.json"))         # a FOLDER with a matching name
        outside = os.path.join(self.tmp, "config-20200101-000001.json")              # a matching name, wrong place
        with open(outside, "w") as f:
            f.write("keep me too")
        for i in range(16):
            self.write(content(i))
            backup.make_backup(self.cfg, now=T0 + datetime.timedelta(minutes=i))
            if i < 15:
                self.assertEqual(len(backup.list_backups(self.bdir)), i + 1)
        mine = backup.list_backups(self.bdir)
        self.assertEqual(len(mine), 15)
        self.assertNotIn("config-20261123-100000.json", mine)                        # the oldest is gone
        self.assertEqual(self.read_backup(mine[0]), content(1))
        self.assertEqual(self.read_backup(mine[-1]), content(15))
        for n in others:
            self.assertTrue(os.path.isfile(os.path.join(self.bdir, n)), n)
        self.assertTrue(os.path.isdir(os.path.join(self.bdir, "config-20200101-000000.json")))
        self.assertTrue(os.path.isfile(outside))

    def test_failure_is_swallowed_and_logged(self):
        self.write(content(1))
        with mock.patch("backup.shutil.copyfile", side_effect=PermissionError("denied")), \
                self.assertLogs("mpanels", level="WARNING") as cm:
            self.assertIsNone(backup.make_backup(self.cfg, now=T0))
        self.assertTrue(any("backup failed" in m for m in cm.output), cm.output)
        self.assertEqual(backup.list_backups(self.bdir), [])

    def test_unreadable_folder_is_not_an_error(self):
        self.write(content(1))
        open(self.bdir, "w").close()                                  # a FILE where the folder should be
        self.assertIsNone(backup.make_backup(self.cfg, now=T0))


class TestAtStartup(Base):
    def setUp(self):
        super().setUp()
        self.desk, self.pub = os.path.join(self.tmp, "Desktop"), os.path.join(self.tmp, "Public")
        os.makedirs(self.desk)
        os.makedirs(self.pub)
        for p in (mock.patch("calendar_panel.model.CalendarModel.refresh", lambda *a, **k: None),
                  mock.patch.object(winutil, "lbutton_down", return_value=True)):
            p.start()
            self.addCleanup(p.stop)
        self.apps = []
        self.addCleanup(lambda: [a.quit() for a in self.apps])
        self.n = 0

    def start(self):
        self.n += 1
        app = mpanels.App(fileops.Ctx(self.desk, self.pub), self.tmp, test_mode=True, use_tray=False,
                          instance_name="t7d_%d_%d" % (os.getpid(), self.n), displays_provider=FakeDisplays(THREE),
                          clock=FakeClock())
        self.apps.append(app)
        return app

    def test_start_backs_up_the_config_as_it_was_before_the_start(self):
        self.write(content(7))
        self.start()
        names = backup.list_backups(self.bdir)
        self.assertEqual(len(names), 1)
        self.assertEqual(self.read_backup(names[0]), content(7))      # not what the start wrote afterwards
        with open(self.cfg, "rb") as f:
            self.assertNotEqual(f.read(), content(7))                  # (the start does rewrite config.json)

    def test_backup_comes_before_the_config_is_read_and_before_any_save(self):
        self.write(content(7))
        seen = []
        real_load, real_save = mpanels.load_json, mpanels.App.save

        def load(path, default):
            if path.endswith("config.json"):
                seen.append(("load", backup.list_backups(self.bdir)))
            return real_load(path, default)

        def save(app):
            seen.append(("save", backup.list_backups(self.bdir)))
            return real_save(app)
        with mock.patch.object(mpanels, "load_json", load), mock.patch.object(mpanels.App, "save", save):
            self.start()
        self.assertEqual(seen[0][0], "load")
        self.assertEqual(len(seen[0][1]), 1)                           # already there when the config is first read
        saves = [s for s in seen if s[0] == "save"]
        self.assertTrue(saves)
        self.assertTrue(all(len(s[1]) == 1 for s in saves))

    def test_second_start_with_the_same_content_adds_nothing_and_a_changed_one_adds_one(self):
        self.write(content(7))
        self.start().quit()                                            # quit saves: the config now differs from content(7)
        self.assertEqual(len(backup.list_backups(self.bdir)), 1)
        self.write(content(7))                                         # as before
        self.start().quit()
        self.assertEqual(len(backup.list_backups(self.bdir)), 1)       # identical to the newest: nothing new
        self.write(content(8))
        self.start()
        self.assertEqual(len(backup.list_backups(self.bdir)), 2)

    def test_first_installation_without_config_makes_no_backup(self):
        self.start()
        self.assertEqual(backup.list_backups(self.bdir), [])
        self.assertFalse(os.path.exists(self.bdir))

    def test_a_failing_backup_does_not_stop_the_start_and_is_logged(self):
        self.write(content(7))
        with mock.patch("backup.shutil.copyfile", side_effect=OSError("disk full")), \
                self.assertLogs("mpanels", level="WARNING") as cm:
            app = self.start()
        self.assertTrue(app.panels)                                    # it started and has its panels
        self.assertTrue(any("backup failed" in m for m in cm.output))

    def test_an_unexpected_error_in_the_backup_code_does_not_stop_the_start(self):
        self.write(content(7))
        with mock.patch("backup.list_backups", side_effect=RuntimeError("boom")):
            app = self.start()
        self.assertTrue(app.panels)


if __name__ == "__main__":
    unittest.main()
