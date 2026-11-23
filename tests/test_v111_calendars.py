"""v1.1.1: calendar addresses live in M Panels' own config (Settings > Calendar list), one-time import from an
M Calendar config file, one-time migration question for the old `source_path`, and privacy of the addresses.

Only FAKE data: fake files in a temp folder, fake addresses on *.invalid, no network, never the real desktop,
never a real M Calendar file or the real M Panels config.
"""
import json
import logging
import os
import shutil
import sys
import tempfile
import tkinter as tk
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import calendar_panel  # noqa: E402
import fileops  # noqa: E402
import mpanels  # noqa: E402
import strings as ui  # noqa: E402
import uiwidgets  # noqa: E402
from calendar_panel import core, source  # noqa: E402
from calendar_panel import settings as cs  # noqa: E402
from calendar_panel.model import CalendarModel  # noqa: E402

REAL_REFRESH = CalendarModel.refresh          # Base.setUp replaces refresh by a no-op; the model tests need the real one

SECRET_A = "https://cal.invalid/private/TOKEN-AAA-111/basic.ics"
SECRET_B = "webcal://cal.invalid/private/TOKEN-BBB-222/basic.ics"
SECRET_C = "https://cal.invalid/private/TOKEN-CCC-333/basic.ics"
TOKENS = ("TOKEN-AAA", "TOKEN-BBB", "TOKEN-CCC", "cal.invalid")
CAL_A = {"name": "Work", "url": SECRET_A, "color": "#4285f4", "enabled": True}
CAL_B = {"name": "Home", "url": SECRET_B, "color": None, "enabled": True}


def pump(app, n=15):
    for _ in range(n):
        app.root.update()


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


class _Collect(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


class Base(unittest.TestCase):
    def make_app(self, name="t111"):
        self.tmp = getattr(self, "tmp", None) or tempfile.mkdtemp(prefix="mpanels_t111_")
        desk, pub, self.data = (os.path.join(self.tmp, n) for n in ("Desktop", "Public", "veri"))
        os.makedirs(desk, exist_ok=True)
        os.makedirs(pub, exist_ok=True)
        app = mpanels.App(fileops.Ctx(desk, pub), self.data, test_mode=True, use_tray=False,
                          instance_name="%s_%d_%d" % (name, os.getpid(), id(self)))
        self.addCleanup(app.quit)
        return app

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mpanels_t111_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch("calendar_panel.model.CalendarModel.refresh", lambda *a, **k: None)
        p.start()
        self.addCleanup(p.stop)
        self.log = _Collect()
        logging.getLogger("mpanels").addHandler(self.log)
        self.addCleanup(logging.getLogger("mpanels").removeHandler, self.log)

    def assert_no_secret(self, text, where=""):
        for tok in TOKENS:
            self.assertNotIn(tok, str(text), where)


@unittest.skipUnless(calendar_panel.AVAILABLE, "calendar libraries not installed")
class TestSettingsList(Base):
    def setUp(self):
        super().setUp()
        self.app = self.make_app("t111s")
        self.cp = self.app.new_panel("Cal", "calendar")
        self.cp.cfg["calendar"]["calendars"] = [dict(CAL_A)]
        pump(self.app)
        self.app.open_settings("Cal")
        pump(self.app, 25)
        self.S = self.app.settings_win
        self.S.nb.select(self.S.tab["calendar"])
        pump(self.app)

    def cfg_cals(self):
        return self.cp.cfg["calendar"]["calendars"]

    # ---- list shows names, never addresses
    def test_list_shows_name_and_state_but_no_address(self):
        tree = self.S.cal_tree
        rows = [tree.item(i, "values") for i in tree.get_children()]
        self.assertEqual([r[1] for r in rows], ["Work"])
        self.assertEqual(rows[0][0], "✓")
        self.assert_no_secret(rows)

    # ---- add / edit / remove, nothing before Apply
    def test_add_edit_remove_change_nothing_until_apply(self):
        S = self.S
        self.assertFalse(S.dirty())
        with mock.patch.object(S, "ask_calendar", return_value=dict(CAL_B)):
            S.cal_add()
        self.assertEqual(len(S.cal_tree.get_children()), 2)
        self.assertTrue(S.dirty())
        self.assertEqual(self.cfg_cals(), [CAL_A])                         # the panel still has the old list
        S.cal_tree.selection_set("0")
        edited = dict(CAL_A, name="Work 2", enabled=False, color=None)
        with mock.patch.object(S, "ask_calendar", return_value=edited) as ask:
            S.cal_edit()
        self.assertEqual(ask.call_args[0][0]["url"], SECRET_A)             # the edit window gets the entry
        S.cal_tree.selection_set("1")
        S.cal_remove()
        self.assertEqual([c["name"] for c in S.cal_list], ["Work 2"])
        self.assertEqual(self.cfg_cals(), [CAL_A])
        S.apply()
        pump(self.app)
        self.assertEqual(self.cfg_cals(), [dict(edited)])
        self.assertFalse(S.dirty())
        with open(self.app.config_path, encoding="utf-8") as f:                 # saved to M Panels' own config
            saved = json.load(f)
        self.assertEqual(saved["panels"]["Cal"]["calendar"]["calendars"], [dict(edited)])

    def test_cancelled_dialog_changes_nothing(self):
        with mock.patch.object(self.S, "ask_calendar", return_value=None):
            self.S.cal_add()
            self.S.cal_tree.selection_set("0")
            self.S.cal_edit()
        self.assertFalse(self.S.dirty())

    def test_discard_throws_the_edits_away_and_cancel_keeps_them(self):
        S = self.S
        with mock.patch.object(S, "ask_calendar", return_value=dict(CAL_B)):
            S.cal_add()
        with mock.patch.object(S, "ask_unsaved", return_value="cancel"):
            S.close()
        self.assertTrue(S.win.winfo_exists())
        self.assertEqual(len(S.cal_list), 2)                                # Cancel: window and edits stay
        with mock.patch.object(S, "ask_unsaved", return_value="discard"):
            S.close()
        self.assertEqual(self.cfg_cals(), [CAL_A])                          # Discard: nothing applied
        self.app.open_settings("Cal")
        pump(self.app)
        self.assertEqual([c["name"] for c in self.app.settings_win.cal_list], ["Work"])

    def test_apply_via_unsaved_prompt(self):
        S = self.S
        with mock.patch.object(S, "ask_calendar", return_value=dict(CAL_B)):
            S.cal_add()
        with mock.patch.object(S, "ask_unsaved", return_value="apply"):
            S.close()
        self.assertEqual([c["name"] for c in self.cfg_cals()], ["Work", "Home"])

    def test_disabled_calendar_is_not_fetched(self):
        calls = []
        m = CalendarModel(fetch=lambda u: calls.append(u) or core.parse_calendar(
            b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:x\r\nEND:VCALENDAR\r\n"))
        REAL_REFRESH(m, [dict(CAL_A, enabled=False), dict(CAL_B)], sync=True)
        self.assertEqual(calls, [SECRET_B])

    # ---- import from a (fake) M Calendar file
    def test_import_adds_to_the_list_and_remembers_no_path(self):
        fake = write_json(os.path.join(self.tmp, "any-name.json"), {"calendars": [
            {"name": "Imp1", "url": SECRET_B, "color": "#112233", "enabled": True},
            {"name": "Dup", "url": SECRET_A, "enabled": True}, {"name": "NoUrl", "url": ""}]})
        before = read_bytes(fake)
        S = self.S
        with mock.patch.object(mpanels.filedialog, "askopenfilename", return_value=fake) as ask, \
                mock.patch.object(mpanels.messagebox, "showinfo") as info:
            S.cal_import()
        self.assertNotIn("initialfile", ask.call_args.kwargs)               # no default file, no default folder
        self.assertNotIn("initialdir", ask.call_args.kwargs)
        self.assertEqual([c["name"] for c in S.cal_list], ["Work", "Imp1"])  # the duplicate address was skipped
        self.assertEqual(self.cfg_cals(), [CAL_A])                          # still needs Apply
        self.assertTrue(S.dirty())
        self.assertIn("1", info.call_args[0][1])
        self.assert_no_secret(info.call_args[0][1])
        S.apply()
        self.assertEqual(len(self.cfg_cals()), 2)
        self.assertEqual(read_bytes(fake), before)                   # the file was only read
        with open(self.app.config_path, encoding="utf-8") as f:
            self.assertNotIn(os.path.basename(fake), f.read())              # its path is not stored anywhere
        self.assertNotIn(fake, json.dumps(self.cp.cfg["calendar"]))

    def test_import_failure_message_has_no_address(self):
        bad = os.path.join(self.tmp, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write('{"calendars": [{"url": "' + SECRET_A + '" BROKEN')
        with mock.patch.object(mpanels.filedialog, "askopenfilename", return_value=bad), \
                mock.patch.object(mpanels.messagebox, "showerror") as err:
            self.S.cal_import()
        err.assert_called_once()
        self.assert_no_secret(err.call_args[0][1])
        self.assertEqual([c["name"] for c in self.S.cal_list], ["Work"])
        with mock.patch.object(mpanels.filedialog, "askopenfilename", return_value=""), \
                mock.patch.object(mpanels.messagebox, "showerror") as err2:
            self.S.cal_import()                                              # dialog cancelled
        err2.assert_not_called()

    def test_import_button_text(self):
        self.assertEqual(self.S.btn_cal_import.cget("text"), "Import from M Calendar config…")


@unittest.skipUnless(calendar_panel.AVAILABLE, "calendar libraries not installed")
class TestDialog(Base):
    def setUp(self):
        super().setUp()
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def dlg(self, initial=None):
        d = uiwidgets.CalendarDialog(self.root, initial)
        self.addCleanup(lambda: d.win.winfo_exists() and d.win.destroy())
        return d

    def test_address_is_masked_until_show(self):
        d = self.dlg(dict(CAL_A))
        self.assertEqual(str(d.en_url.cget("show")), "•")
        self.assertEqual(ui.CAL_ADDRESS_MASK, "•")
        self.assertEqual(d.btn_show.cget("text"), ui.BTN_CAL_SHOW)
        d.toggle_show()
        self.assertEqual(str(d.en_url.cget("show")), "")
        self.assertEqual(d.btn_show.cget("text"), ui.BTN_CAL_HIDE)
        d.toggle_show()
        self.assertEqual(str(d.en_url.cget("show")), "•")
        self.assertEqual(d.btn_show.cget("text"), ui.BTN_CAL_SHOW)

    def test_name_field_is_not_masked_and_address_never_in_a_label(self):
        d = self.dlg(dict(CAL_A))
        self.assertEqual(str(d.en_name.cget("show")), "")
        self.assertEqual(d.win.title(), ui.DLG_CAL_EDIT)
        labels = []

        def walk(w):
            for c in w.winfo_children():
                try:
                    labels.append(str(c.cget("text")))
                except tk.TclError:
                    pass
                walk(c)
        walk(d.win)
        self.assert_no_secret(" ".join(labels) + d.win.title())

    def test_ok_returns_a_clean_entry(self):
        d = self.dlg()
        self.assertEqual(d.win.title(), ui.DLG_CAL_ADD)
        d.v_name.set("  Mine ")
        d.v_url.set("  " + SECRET_C + " ")
        d.v_on.set(False)
        d.color = "#abcdef"
        d.ok()
        self.assertEqual(d.result, {"name": "Mine", "url": SECRET_C, "color": "#abcdef", "enabled": False})

    def test_bad_address_is_refused_without_echo(self):
        for bad in ("", "   ", "ftp://cal.invalid/TOKEN-CCC", "not a url TOKEN-CCC", "https://a b"):
            d = self.dlg()
            d.v_url.set(bad)
            d.ok()
            self.assertIsNone(d.result, bad)
            self.assertEqual(d.lbl_err.cget("text"), ui.ERR_CAL_ADDRESS)
            self.assert_no_secret(d.lbl_err.cget("text"))
            d.win.destroy()

    def test_blank_name_gets_a_default_and_color_can_be_reset(self):
        d = self.dlg(dict(CAL_A))
        d.v_name.set("")
        d.reset_color()
        d.ok()
        self.assertEqual((d.result["name"], d.result["color"]), (ui.CAL_NEW_NAME, None))


@unittest.skipUnless(calendar_panel.AVAILABLE, "calendar libraries not installed")
class TestMigration(Base):
    """Old config: calendar.source_path (+ ticked names). One question per panel, never twice."""

    def old_file(self, name="takvim-ayar.json"):
        return write_json(os.path.join(self.tmp, name), {"calendars": [
            {"name": "Work", "url": SECRET_A, "color": "#4285f4", "enabled": True},
            {"name": "Home", "url": SECRET_B, "color": None, "enabled": True},
            {"name": "Sport", "url": SECRET_C, "color": None, "enabled": True}]})

    def start(self, source_path, ticked=("Home",)):
        app = self.make_app("t111m")
        cp = app.new_panel("Cal", "calendar")
        cp.cfg["calendar"] = cs.sanitize({"source_path": source_path, "calendars": list(ticked)})
        app.save()
        return app, cp

    def test_yes_imports_once_and_removes_the_old_setting(self):
        f = self.old_file()
        before = read_bytes(f)
        app, cp = self.start(f)
        with mock.patch.object(mpanels.messagebox, "askyesno", return_value=True) as q:
            app.migrate_calendar_sources()
            q.assert_called_once()
            msg = q.call_args[0][1]
            self.assertIn("takvim-ayar.json", msg)                           # the file NAME, not the folder
            self.assertNotIn(self.tmp, msg)
            self.assert_no_secret(msg)
            app.migrate_calendar_sources()                                  # second time: no question
            q.assert_called_once()
        s = cp.cfg["calendar"]
        self.assertNotIn("source_path", s)
        self.assertNotIn("legacy_names", s)
        self.assertEqual([(c["name"], c["enabled"]) for c in s["calendars"]],
                         [("Work", False), ("Home", True), ("Sport", False)])   # old ticked selection kept
        self.assertEqual(read_bytes(f), before)
        with open(app.config_path, encoding="utf-8") as fh:
            saved = fh.read()
        self.assertNotIn("source_path", saved)
        self.assertNotIn(self.tmp.replace("\\", "\\\\"), saved)

    def test_no_imports_nothing_removes_the_setting_and_never_asks_again(self):
        f = self.old_file()
        app, cp = self.start(f)
        with mock.patch.object(mpanels.messagebox, "askyesno", return_value=False) as q:
            app.migrate_calendar_sources()
            app.migrate_calendar_sources()
            q.assert_called_once()
        s = cp.cfg["calendar"]
        self.assertEqual(s["calendars"], [])
        self.assertNotIn("source_path", s)
        with open(app.config_path, encoding="utf-8") as fh:
            self.assertNotIn("source_path", fh.read())

    def test_unreadable_file_warns_without_address_and_still_asks_only_once(self):
        bad = os.path.join(self.tmp, "kaput.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write('{"calendars": [{"url": "' + SECRET_A + '" BROKEN')
        app, cp = self.start(bad)
        with mock.patch.object(mpanels.messagebox, "askyesno", return_value=True) as q, \
                mock.patch.object(mpanels.messagebox, "showwarning") as warn:
            app.migrate_calendar_sources()
            app.migrate_calendar_sources()
        q.assert_called_once()
        warn.assert_called_once()
        self.assert_no_secret(warn.call_args[0][1])
        self.assertEqual(cp.cfg["calendar"]["calendars"], [])
        self.assertNotIn("source_path", cp.cfg["calendar"])

    def test_missing_file_behaves_like_unreadable(self):
        app, cp = self.start(os.path.join(self.tmp, "yok.json"))
        with mock.patch.object(mpanels.messagebox, "askyesno", return_value=True), \
                mock.patch.object(mpanels.messagebox, "showwarning") as warn:
            app.migrate_calendar_sources()
        warn.assert_called_once()
        self.assertNotIn("source_path", cp.cfg["calendar"])

    def test_the_question_survives_a_restart_until_answered_then_never_returns(self):
        f = self.old_file()
        app, cp = self.start(f)
        app.quit()
        pump(app)
        app2 = self.make_app("t111r")                                        # same data folder: reads the saved config
        cp2 = app2.panels["Cal"]
        self.assertEqual(cs.pending_migration(cp2.cfg["calendar"])[0], f)
        with mock.patch.object(mpanels.messagebox, "askyesno", return_value=True) as q:
            app2.migrate_calendar_sources()
        q.assert_called_once()
        app2.quit()
        app3 = self.make_app("t111x")
        with mock.patch.object(mpanels.messagebox, "askyesno", return_value=True) as q3:
            app3.migrate_calendar_sources()
        q3.assert_not_called()
        self.assertEqual([c["name"] for c in app3.panels["Cal"].cfg["calendar"]["calendars"]], ["Work", "Home", "Sport"])

    def test_new_panels_and_other_panel_types_are_not_asked(self):
        app = self.make_app("t111n")
        app.new_panel("Cal", "calendar")
        app.new_panel("Notes", "note")
        with mock.patch.object(mpanels.messagebox, "askyesno") as q:
            app.migrate_calendar_sources()
        q.assert_not_called()

    def test_default_has_no_source_path_anywhere(self):
        self.assertNotIn("source_path", cs.DEFAULTS)
        self.assertNotIn("source_path", cs.sanitize(None))
        self.assertNotIn("source_path", cs.look_of(None))


@unittest.skipUnless(calendar_panel.AVAILABLE, "calendar libraries not installed")
class TestPrivacy(Base):
    """The address must not reach the log, an error message, a window title, a tooltip, the look or the example."""

    def setUp(self):
        super().setUp()
        self.app = self.make_app("t111p")
        self.cp = self.app.new_panel("Cal", "calendar")
        self.cp.cfg["calendar"]["calendars"] = [dict(CAL_A), dict(CAL_B)]
        pump(self.app)

    def refresh_with_failures(self):

        def fetch(url):
            raise OSError("connect failed for " + url)        # a real error text may contain the address
        m = CalendarModel(fetch=fetch)
        REAL_REFRESH(m, self.cp.cfg["calendar"]["calendars"], sync=True)
        return m

    def test_fetch_errors_reach_neither_message_nor_log(self):
        m = self.refresh_with_failures()
        err = m.snapshot()["error"]
        self.assertIn("Work (OSError)", err)
        self.assert_no_secret(err, "error message")
        self.assert_no_secret("\n".join(self.log.lines), "log")

    def test_panel_title_tooltip_and_status_text_have_no_address(self):
        self.cp.model.error = ui.CAL_ERR_FETCH.format(names="Work (OSError)")
        self.cp.model.metas = [{"name": "Work", "url": SECRET_A, "color": None}]
        self.assert_no_secret(self.cp.cal.status_text(), "tooltip")
        self.assert_no_secret(self.cp.top.title(), "panel window title")
        self.assert_no_secret(self.cp.title_text if hasattr(self.cp, "title_text") else "", "title text")

    def test_settings_window_title_and_texts_have_no_address(self):
        self.app.open_settings("Cal")
        pump(self.app, 20)
        S = self.app.settings_win
        self.assert_no_secret(S.win.title(), "settings title")
        found = []

        def walk(w):
            for c in w.winfo_children():
                for opt in ("text", "textvariable"):
                    try:
                        v = str(c.cget(opt))
                        found.append(c.getvar(v) if opt == "textvariable" else v)
                    except tk.TclError:
                        pass
                walk(c)
        walk(S.win)
        self.assert_no_secret(" ".join(found), "settings widgets")
        for iid in S.cal_tree.get_children():
            self.assert_no_secret(S.cal_tree.item(iid), "list row")

    def test_actions_write_nothing_secret_to_the_log(self):
        self.app.open_settings("Cal")
        pump(self.app, 20)
        S = self.app.settings_win
        with mock.patch.object(S, "ask_calendar", return_value=dict(CAL_B, url=SECRET_C)):
            S.cal_add()
        S.apply()
        pump(self.app)
        self.app.migrate_calendar_sources()
        self.refresh_with_failures()
        self.assert_no_secret("\n".join(self.log.lines), "log")

    def test_look_default_and_example_config_have_no_address(self):
        look = cs.look_of(self.cp.cfg["calendar"])
        self.assertTrue(set(look) <= set(cs.LOOK_KEYS))
        self.assert_no_secret(json.dumps(look), "look")
        self.app.save_defaults(**{mpanels.CAL_LOOK_KEY: look})
        with open(self.app.defaults_path, encoding="utf-8") as f:
            self.assert_no_secret(f.read(), "defaults.json")
        with open(os.path.join(ROOT, "config.example.json"), encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("://", text)
        self.assertNotIn('"url"', text)

    def test_user_strings_are_english_and_have_no_personal_paths(self):
        for name in dir(ui):
            if name.startswith(("BTN_CAL", "CAL_", "MSG_CAL", "ASK_CAL", "DLG_CAL", "ERR_CAL", "LBL_CAL", "CHK_CAL")):
                v = getattr(ui, name)
                if isinstance(v, str):
                    self.assertFalse([c for c in v if c in "ğüşöçıİĞÜŞÖÇ"], name)
                    self.assertNotIn("config.json", v)


if __name__ == "__main__":
    unittest.main()
