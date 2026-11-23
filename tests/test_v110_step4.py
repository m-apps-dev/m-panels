"""v1.1 step 4: 'Open Google Calendar' in the Calendar panel menu (only there; fixed address; never crashes)."""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import applog  # noqa: E402
import calendar_panel  # noqa: E402
import fileops  # noqa: E402
import mpanels  # noqa: E402
import strings as ui  # noqa: E402


def labels(m):
    out = []
    for i in range(m.index("end") + 1):
        out.append("-" if m.type(i) == "separator" else m.entrycget(i, "label"))
    return out


def invoke(m, label):
    for i in range(m.index("end") + 1):
        if m.type(i) != "separator" and m.entrycget(i, "label") == label:
            m.invoke(i)
            return
    raise AssertionError(label + " not in menu")


class TestConstant(unittest.TestCase):
    def test_fixed_address_and_text(self):
        self.assertEqual(ui.GOOGLE_CALENDAR_URL, "https://calendar.google.com/")
        self.assertEqual(ui.MENU_CAL_OPEN_GOOGLE, "Open Google Calendar")

    def test_address_written_in_one_place(self):
        hits = []
        for dp, _, fs in os.walk(ROOT):
            if any(x in dp for x in ("__pycache__", os.sep + "tests", os.sep + "docs", os.sep + ".")):
                continue
            for f in fs:
                if f.endswith(".py"):
                    with open(os.path.join(dp, f), encoding="utf-8") as fh:
                        if "calendar.google.com" in fh.read():
                            hits.append(f)
        self.assertEqual(hits, ["strings.py"])


@unittest.skipUnless(calendar_panel.AVAILABLE, "calendar libraries not installed")
class TestMenu(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mpanels_t110s4_")
        self.desk, self.pub, self.data = (os.path.join(self.tmp, n) for n in ("Desktop", "Public", "veri"))
        os.makedirs(self.desk)
        os.makedirs(self.pub)
        p = mock.patch("calendar_panel.model.CalendarModel.refresh", lambda *a, **k: None)
        p.start()
        self.addCleanup(p.stop)
        self.app = mpanels.App(fileops.Ctx(self.desk, self.pub), self.data, test_mode=True, use_tray=False,
                               instance_name="t110s4_%d" % os.getpid())
        self.addCleanup(self.app.quit)
        self.cal = self.app.new_panel("Cal", "calendar")
        self.sc = self.app.new_panel("Short", "shortcut")
        self.note = self.app.new_panel("Note", "note")
        for _ in range(10):
            self.app.root.update()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_item_only_in_calendar_panel(self):
        self.assertIn(ui.MENU_CAL_OPEN_GOOGLE, labels(self.cal.build_menu()))
        self.assertNotIn(ui.MENU_CAL_OPEN_GOOGLE, labels(self.sc.build_menu()))
        self.assertNotIn(ui.MENU_CAL_OPEN_GOOGLE, labels(self.note.build_menu()))

    def test_item_sits_next_to_refresh_separators_intact(self):
        lay = labels(self.cal.build_menu())
        i = lay.index(ui.MENU_CAL_REFRESH)
        self.assertEqual(lay[i + 1], ui.MENU_CAL_OPEN_GOOGLE)
        self.assertEqual(lay[i + 2], "-")
        self.assertEqual(lay[i - 1], "-")
        self.assertEqual(lay[i + 3], ui.MENU_SETTINGS)
        self.assertEqual(lay[-1], ui.MENU_COLLAPSE)
        self.assertNotIn("--", ["".join(lay[j:j + 2]) for j in range(len(lay) - 1)])

    def test_shortcut_and_note_menus_unchanged(self):
        sc = labels(self.sc.build_menu())
        self.assertEqual(sc[:2], [ui.MENU_NEW_PANEL, ui.MENU_RENAME])
        self.assertNotIn(ui.MENU_CAL_REFRESH, sc)
        self.assertNotIn(ui.MENU_CAL_REFRESH, labels(self.note.build_menu()))

    def test_click_opens_fixed_address(self):
        with mock.patch("mpanels.webbrowser.open") as op:
            invoke(self.cal.build_menu(), ui.MENU_CAL_OPEN_GOOGLE)
        op.assert_called_once_with("https://calendar.google.com/")

    def test_exception_does_not_crash_and_is_logged(self):
        with mock.patch("mpanels.webbrowser.open", side_effect=OSError("no browser")), \
                mock.patch("mpanels.messagebox.showwarning") as w, \
                mock.patch("mpanels.messagebox.showerror") as e, \
                mock.patch.object(applog.get_logger(), "warning") as lg:
            invoke(self.cal.build_menu(), ui.MENU_CAL_OPEN_GOOGLE)
        lg.assert_called_once()
        self.assertIn("no browser", str(lg.call_args))
        w.assert_not_called()
        e.assert_not_called()


if __name__ == "__main__":
    unittest.main()
