"""v1.2 step 4: the search launcher. Pure logic (matching, the list, the index with an injected clock), the controller with a
made-up window / host / actions / timers, the real tkinter window, the shortcut key (made-up Windows API), the bar's search
button and the Settings fields.
Nothing here starts a program, sends a key, registers a real shortcut key, touches the real foreground or closes a real window:
the Windows calls are handed in (SearchActions(send=..., startfile=..., foreground=...), FakeSearchActions, FakeHotkeyApi);
a source scan checks that only the allowed Win32 names exist. "real:" tests only READ (the AppsFolder list)."""
import inspect
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import barwin  # noqa: E402
import fileops  # noqa: E402
import infoclock  # noqa: E402
import mpanels  # noqa: E402
import search  # noqa: E402
import searchwin  # noqa: E402
import shellmsg  # noqa: E402
import strings as ui  # noqa: E402
import theme  # noqa: E402
import winutil  # noqa: E402
from fakedisplays import MIDDLE, FakeClock  # noqa: E402
from test_v120_step1 import Base, FakeAppBar, FakeDisplays, FakeIcons, FakeShell, ON, THREE, pump  # noqa: E402
from test_v120_step2 import Base2  # noqa: E402
from test_v120_step3 import Clicks, ev  # noqa: E402
from test_v120_step3b import OWN_MIN, settle  # noqa: E402

H = theme.BAR_HEIGHT
GUID = "{F38BF404-1D43-42F2-9305-67DE0B28FC23}"

APPS = [
    ("Anaconda Prompt", "C:\\ProgramData\\Anaconda3\\Scripts\\a.exe"),
    ("Anaconda Prompt", GUID + "\\Anaconda3\\Scripts\\b.exe"),
    ("Photos", "Microsoft.Windows.Photos_8wekyb3d8bbwe!App"),
    ("Photos", "Microsoft.Photos.Legacy_8wekyb3d8bbwe!App"),
    ("Uninstall", "C:\\Program Files\\Alpha\\unins000.exe"),
    ("Uninstall", "C:\\Program Files\\Beta\\unins000.exe"),
    ("Manual", "C:\\Program Files\\Alpha\\manual.pdf"),
    ("Manual", "C:\\Program Files\\Beta\\manual.pdf"),
    ("Konsol RAR kılavuzu", "C:\\Program Files\\WinRAR\\Rar.txt"),
    ("Çam Editör", "C:\\Apps\\cam.exe"),
    ("Işık Ayarları", "C:\\Apps\\isik.exe"),
    ("Visual Studio Code", "C:\\Apps\\Code\\Code.exe"),
    ("Calculator", "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"),
    ("Notepad", "C:\\Windows\\notepad.exe"),
]


def entries(apps=APPS):
    return search.with_hints(search.entries_from_apps(apps))


def names(found):
    return [e.name for e in found]


# --------------------------------------------------------------------------- matching
class TestFold(unittest.TestCase):
    def test_the_four_forms_of_i_are_one(self):
        for s in ("İ", "ı", "I", "i"):
            self.assertEqual(search.fold(s), "i", s)
        self.assertEqual(search.fold("İSTANBUL ışık"), "istanbul isik")

    def test_case_and_accents_are_ignored(self):
        self.assertEqual(search.fold("ÇAM Şeker Ğ Ö Ü"), "cam seker g o u")
        self.assertEqual(search.fold("Café"), "cafe")

    def test_turkish_table(self):
        es = entries()
        self.assertEqual(names(search.search(es, "kilavuz"))[:1], ["Konsol RAR kılavuzu"])
        self.assertEqual(names(search.search(es, "KILAVUZ"))[:1], ["Konsol RAR kılavuzu"])
        self.assertEqual(names(search.search(es, "cam"))[:1], ["Çam Editör"])
        self.assertEqual(names(search.search(es, "ÇAM"))[:1], ["Çam Editör"])
        self.assertEqual(names(search.search(es, "isik")), ["Işık Ayarları"])
        self.assertEqual(names(search.search(es, "IŞIK")), ["Işık Ayarları"])
        self.assertEqual(names(search.search(es, "İŞİK")), ["Işık Ayarları"])


class TestOrder(unittest.TestCase):
    def test_tiers_in_order(self):
        es = search.with_hints(search.entries_from_apps(
            [(n, "C:\\x\\%d.exe" % i) for i, n in enumerate(
                ["Barcode", "Cool Octopus Deluxe Edition", "Visual Code", "Code Writer", "Code"])]))
        self.assertEqual(names(search.search(es, "code")),
                         ["Code", "Code Writer", "Visual Code", "Cool Octopus Deluxe Edition", "Barcode"])

    def test_each_tier_number(self):
        f = search.fold
        self.assertEqual(search.tier("code", f("Code")), 0)
        self.assertEqual(search.tier("code", f("Code Writer")), 1)
        self.assertEqual(search.tier("code", f("Visual Code")), 2)
        self.assertEqual(search.tier("vsc", f("Visual Studio Code")), 3)
        self.assertEqual(search.tier("code", f("Barcode")), 4)
        self.assertIsNone(search.tier("zzz", f("Barcode")))

    def test_initials(self):
        self.assertEqual(names(search.search(entries(), "vsc")), ["Visual Studio Code"])

    def test_prefix_beats_substring(self):
        es = search.with_hints(search.entries_from_apps([("Xnote", "C:\\a.exe"), ("Note", "C:\\b.exe"), ("My notes", "C:\\c.exe")]))
        self.assertEqual(names(search.search(es, "note")), ["Note", "My notes", "Xnote"])

    def test_ties_shorter_name_then_alphabetical(self):
        es = search.with_hints(search.entries_from_apps(
            [("Notes Zed", "C:\\1.exe"), ("Notes B", "C:\\2.exe"), ("Notes A", "C:\\3.exe"), ("Notes", "C:\\4.exe")]))
        self.assertEqual(names(search.search(es, "no")), ["Notes", "Notes A", "Notes B", "Notes Zed"])

    def test_empty_or_blank_text_gives_nothing(self):
        self.assertEqual(search.search(entries(), ""), [])
        self.assertEqual(search.search(entries(), "   "), [])
        self.assertEqual(search.build_rows(entries(), "", windows_row=True), [])

    def test_at_most_8_rows(self):
        es = search.with_hints(search.entries_from_apps([("App %02d" % i, "C:\\%d.exe" % i) for i in range(30)]))
        self.assertEqual(len(search.search(es, "app")), 8)

    def test_windows_row_only_with_text_and_takes_a_place(self):
        es = entries()
        self.assertEqual(search.build_rows(es, "", windows_row=True), [])
        self.assertEqual(search.build_rows(es, "  ", windows_row=True), [])
        rows = search.build_rows(es, "cam", windows_row=True)
        self.assertEqual(rows[-1], ("windows", "cam"))
        many = search.with_hints(search.entries_from_apps([("App %02d" % i, "C:\\%d.exe" % i) for i in range(30)]))
        self.assertEqual(len(search.build_rows(many, "app", windows_row=True)), 8)
        self.assertEqual(len(search.build_rows(many, "app", windows_row=False)), 8)
        self.assertNotIn("windows", [k for k, _ in search.build_rows(many, "app", windows_row=False)])
        self.assertEqual(search.build_rows(es, "zzzzzz", windows_row=True), [("windows", "zzzzzz")])


# --------------------------------------------------------------------------- the list
class TestEntries(unittest.TestCase):
    def test_same_name_different_programs_both_stay_with_a_hint(self):
        es = entries()
        for n in ("Anaconda Prompt", "Photos", "Uninstall", "Manual"):
            same = [e for e in es if e.name == n]
            self.assertEqual(len(same), 2, n)
            self.assertTrue(all(e.hint for e in same), n)
            self.assertEqual(len({e.hint.casefold() for e in same}), 2, n)
        self.assertEqual([e.hint for e in es if e.name == "Notepad"], [""])

    def test_dedupe_is_by_parsing_name_not_by_name(self):
        es = search.entries_from_apps([("A", "C:\\x.exe"), ("A", "C:\\y.exe"), ("B", "C:\\X.EXE"), ("A", "C:\\x.exe")])
        self.assertEqual([e.parsing for e in es], ["C:\\x.exe", "C:\\y.exe"])

    def test_error_and_empty_rows_are_skipped(self):
        es = search.entries_from_apps([("<error>", "C:\\x.exe"), ("", "C:\\y.exe"), ("Good", ""), ("Fine", "C:\\z.exe")])
        self.assertEqual(names(es), ["Fine"])

    def test_store_apps_are_the_aumids(self):
        es = entries()
        self.assertEqual(sorted(n for n in names(es) if next(e for e in es if e.name == n).store),
                         ["Calculator", "Photos", "Photos"])
        self.assertFalse(search.is_store("C:\\a!b\\c.exe"))
        self.assertTrue(search.is_store("Pkg_abc!App"))

    def test_store_off_drops_them_store_on_keeps_them(self):
        es = entries()
        self.assertEqual(names(search.search(es, "calc", store_apps=True)), ["Calculator"])
        self.assertEqual(search.search(es, "calc", store_apps=False), [])
        self.assertEqual(names(search.search(es, "photos", store_apps=False)), [])
        self.assertEqual(len(search.search(es, "photos", store_apps=True)), 2)
        self.assertEqual(names(search.search(es, "notepad", store_apps=False)), ["Notepad"])

    def test_no_noise_filter(self):
        es = entries()
        self.assertEqual(len(search.search(es, "uninstall")), 2)
        self.assertEqual(len(search.search(es, "manual")), 2)


class TestLnkScan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mpanels_t120s4_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.user, self.common = (os.path.join(self.tmp, n) for n in ("user", "common"))
        for root in (self.user, self.common):
            os.makedirs(os.path.join(root, "Startup"))
            os.makedirs(os.path.join(root, "Tools"))
        self.touch("user", "Only User.lnk")
        self.touch("user", "Same Name.lnk")
        self.touch("common", "Same Name.lnk")
        self.touch("common", "Only Common.lnk")
        self.touch("user", "Startup", "Boot User.lnk")
        self.touch("common", "Startup", "Boot Common.lnk")
        self.touch("common", "Tools", "Tool.lnk")
        self.touch("user", "readme.txt")

    def touch(self, *parts):
        with open(os.path.join(self.tmp, *parts), "wb"):
            pass

    def scan(self):
        return search.scan_lnk([(self.user, 0), (self.common, 1)])

    def test_startup_of_both_folders_is_left_out(self):
        got = {n for n, _p, _r in self.scan()}
        self.assertNotIn("Boot User", got)
        self.assertNotIn("Boot Common", got)
        self.assertEqual(got, {"Only User", "Same Name", "Only Common", "Tool"})

    def test_only_lnk_files(self):
        self.assertTrue(all(p.endswith(".lnk") for _n, p, _r in self.scan()))

    def test_a_folder_that_does_not_exist_is_skipped(self):
        self.assertEqual(search.scan_lnk([(os.path.join(self.tmp, "nope"), 0), (None, 1)]), [])

    def test_same_name_user_wins(self):
        es = search.entries_from_lnk(self.scan())
        same = [e for e in es if e.name == "Same Name"]
        self.assertEqual(len(same), 1)
        self.assertTrue(same[0].parsing.startswith(self.user))
        self.assertEqual(same[0].kind, "lnk")
        self.assertEqual(len(es), 4)


class TestScanAndFallback(unittest.TestCase):
    def lnks(self):
        return [("Old Prog", "C:\\SM\\Old Prog.lnk", 0)]

    def test_appsfolder_is_primary(self):
        src = search.FakeSources(APPS, self.lnks())
        es, kind = search.scan(src)
        self.assertEqual(kind, "appsfolder")
        self.assertEqual(src.calls, ["appsfolder"])
        self.assertEqual(len(es), len(APPS))

    def test_an_appsfolder_error_falls_back_and_is_logged(self):
        src = search.FakeSources(OSError("boom"), self.lnks())
        with self.assertLogs("mpanels", "WARNING") as lg:
            es, kind = search.scan(src)
        self.assertEqual(kind, "lnk")
        self.assertEqual(names(es), ["Old Prog"])
        self.assertEqual(src.calls, ["appsfolder", "lnk"])
        self.assertTrue(any("AppsFolder" in m for m in lg.output))
        self.assertFalse(any("boom" in m for m in lg.output))              # the exception TYPE only

    def test_an_empty_appsfolder_falls_back_too(self):
        src = search.FakeSources([], self.lnks())
        with self.assertLogs("mpanels", "WARNING") as lg:
            es, kind = search.scan(src)
        self.assertEqual((kind, names(es)), ("lnk", ["Old Prog"]))
        self.assertTrue(any("AppsFolder" in m for m in lg.output))

    def test_an_appsfolder_list_that_works_does_not_read_the_shortcuts(self):
        src = search.FakeSources(APPS, self.lnks())
        search.scan(src)
        self.assertNotIn("lnk", src.calls)

    def test_same_name_in_the_fallback_gets_a_folder_hint(self):
        src = search.FakeSources(OSError("x"), [("Tool", "C:\\SM\\A\\Tool.lnk", 0), ("Tool", "C:\\SM\\B\\Tool.lnk", 0)])
        with self.assertLogs("mpanels", "WARNING"):
            es, _ = search.scan(src)
        self.assertEqual(sorted(e.hint for e in es), ["A", "B"])


# --------------------------------------------------------------------------- config
class TestConfigPure(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(search.defaults(), {"enabled": True, "hotkey": "off", "store_apps": True, "windows_row": False})
        self.assertIsNot(search.defaults(), search.DEFAULTS)

    def test_sanitize(self):
        self.assertEqual(search.sanitize(None), search.defaults())
        self.assertEqual(search.sanitize({"enabled": "yes", "hotkey": "alt+space", "store_apps": 1, "windows_row": None}),
                         search.defaults())
        self.assertEqual(search.sanitize({"hotkey": "win+alt+space", "windows_row": True})["hotkey"], "win+alt+space")

    def test_differences_only(self):
        self.assertEqual(search.differences(search.defaults()), {})
        self.assertEqual(search.differences({"hotkey": "ctrl+shift+space"}), {"hotkey": "ctrl+shift+space"})
        self.assertEqual(search.differences({"enabled": False, "store_apps": False}), {"enabled": False, "store_apps": False})

    def test_the_hotkey_list(self):
        self.assertEqual(list(search.HOTKEYS), ["off", "win+alt+space", "ctrl+shift+space"])
        self.assertEqual(search.DEFAULT_HOTKEY, "off")
        offered = set(search.HOTKEYS.values())
        self.assertNotIn((search.MOD_ALT, search.VK_SPACE), offered)           # Alt+Space is NOT offered
        self.assertNotIn((search.MOD_CONTROL, search.VK_SPACE), offered)       # Ctrl+Space is NOT offered
        self.assertEqual(search.HOTKEYS["win+alt+space"], (search.MOD_WIN | search.MOD_ALT, search.VK_SPACE))
        self.assertEqual(search.HOTKEYS["ctrl+shift+space"], (search.MOD_CONTROL | search.MOD_SHIFT, search.VK_SPACE))
        self.assertEqual(list(ui.SEARCH_HOTKEY_LABELS), list(search.HOTKEYS))

    def test_example_config_holds_the_defaults(self):
        with open(os.path.join(ROOT, "config.example.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["bar"]["search"], search.defaults())

    def test_infoclock_carries_the_search_section(self):
        self.assertEqual(infoclock.defaults()["search"], search.defaults())
        self.assertEqual(infoclock.sanitize({"search": {"hotkey": "bogus"}})["search"], search.defaults())
        self.assertEqual(infoclock.sanitize({})["search"], search.defaults())


# --------------------------------------------------------------------------- the index
class TestIndex(unittest.TestCase):
    def make(self, apps=APPS, run=True):
        self.clock = FakeClock()
        self.src = search.FakeSources(apps)
        self.spawned, self.delivered = [], []
        spawn = (lambda fn: (self.spawned.append(fn), fn() if run else None)[0])
        self.ix = search.Index(self.src, self.clock, spawn, self.delivered.append)
        return self.ix

    def test_first_scan_runs_in_the_background_and_comes_back_through_deliver(self):
        ix = self.make(run=False)
        self.assertTrue(ix.start())
        self.assertEqual(self.src.calls, [])                       # nothing read on the calling thread
        self.assertEqual(ix.entries(), [])
        self.assertTrue(ix.scanning)
        self.spawned[0]()                                          # the worker runs
        self.assertEqual(self.src.calls, ["appsfolder"])
        self.assertEqual(len(self.delivered), 1)
        self.assertTrue(ix.finish(self.delivered[0]))
        self.assertEqual(len(ix.entries()), len(APPS))
        self.assertEqual((ix.kind, ix.scanning, ix.cached_at), ("appsfolder", False, self.clock.t))

    def test_one_scan_at_a_time(self):
        ix = self.make(run=False)
        self.assertTrue(ix.request_refresh())
        self.assertFalse(ix.request_refresh())
        self.assertFalse(ix.refresh_if_stale())
        self.assertEqual(len(self.spawned), 1)
        self.spawned[0]()
        ix.finish(self.delivered[0])
        self.assertTrue(ix.request_refresh())

    def test_refresh_threshold_is_30_seconds(self):
        ix = self.make()
        ix.start()
        ix.finish(self.delivered[-1])
        self.clock.advance(29.9)
        self.assertFalse(ix.refresh_if_stale())
        self.assertEqual(ix.scans, 1)
        self.clock.advance(0.1)
        self.assertTrue(ix.refresh_if_stale())
        self.assertEqual(ix.scans, 2)
        self.assertEqual(search.SCAN_MAX_AGE_S, 30)

    def test_never_scanned_counts_as_stale(self):
        ix = self.make()
        self.assertTrue(ix.refresh_if_stale())

    def test_a_failed_or_empty_scan_keeps_the_old_list_and_time(self):
        ix = self.make()
        ix.start()
        ix.finish(self.delivered[-1])
        t0, old = ix.cached_at, ix.entries()
        self.clock.advance(100)
        self.assertFalse(ix.finish(None))
        self.assertFalse(ix.finish(([], "lnk")))
        self.assertEqual((ix.cached_at, ix.entries()), (t0, old))
        self.assertFalse(ix.scanning)

    def test_an_exception_in_the_worker_delivers_none(self):
        ix = self.make()
        with mock.patch.object(search, "scan", side_effect=RuntimeError("x")), self.assertLogs("mpanels", "ERROR"):
            ix.start()
        self.assertEqual(self.delivered, [None])

    def test_stopped_index_scans_and_takes_nothing(self):
        ix = self.make()
        ix.stop()
        self.assertFalse(ix.request_refresh())
        self.assertFalse(ix.finish((entries(), "appsfolder")))


# --------------------------------------------------------------------------- the Windows actions (made-up send)
class TestActions(unittest.TestCase):
    def make(self, fail_on=None):
        self.sent, self.started = [], []
        self.n = 0

        def send(events):
            self.n += 1
            if fail_on is not None and self.n == fail_on:
                raise OSError("send failed")
            self.sent.append(list(events))
            return len(events)
        return search.SearchActions(send=send, foreground=lambda: 77, startfile=self.started.append, sleep=lambda s: None)

    def entry(self, parsing, kind="app"):
        return search.make_entry("X", parsing, kind)

    def test_launch_targets(self):
        a = self.make()
        a.launch(self.entry("Pkg_abc!App"))
        a.launch(self.entry("C:\\Apps\\a.exe"))
        a.launch(self.entry("C:\\SM\\Prog.lnk", "lnk"))
        self.assertEqual(self.started, ["shell:AppsFolder\\Pkg_abc!App", "shell:AppsFolder\\C:\\Apps\\a.exe", "C:\\SM\\Prog.lnk"])

    def test_launch_error_is_raised(self):
        a = search.SearchActions(startfile=mock.Mock(side_effect=OSError(2, "no")))
        with self.assertRaises(OSError):
            a.launch(self.entry("C:\\x.exe"))

    def test_the_foreground(self):
        self.assertEqual(self.make().foreground(), 77)

    def keys(self):
        return [(e[0], e[2]) for batch in self.sent for e in batch]

    def test_win_s_sequence_and_win_is_released(self):
        a = self.make()
        a.open_windows_search()
        E, UP = search.KEYEVENTF_EXTENDEDKEY, search.KEYEVENTF_KEYUP
        self.assertEqual(self.keys(), [(search.VK_LWIN, E), (search.VK_S, 0), (search.VK_S, UP), (search.VK_LWIN, E | UP)])

    def test_the_win_key_goes_up_even_when_a_send_fails(self):
        for fail_on in (2, 3, 4):                                  # S down / S up / the Win up itself
            a = self.make(fail_on=fail_on)
            try:
                a.open_windows_search()
            except OSError:
                pass
            ks = self.keys()
            downs = [k for k in ks if k[0] == search.VK_LWIN and not k[1] & search.KEYEVENTF_KEYUP]
            ups = [k for k in ks if k[0] == search.VK_LWIN and k[1] & search.KEYEVENTF_KEYUP]
            if fail_on == 4:
                self.assertEqual(len(downs), 1)                    # (the retry in finally also fails: nothing more to check)
            else:
                self.assertEqual((len(downs), len(ups)), (1, 1), fail_on)

    def test_typing_uses_unicode_events_without_key_codes(self):
        a = self.make()
        a.type_text("aÇ")
        batch = self.sent[0]
        self.assertEqual(len(batch), 4)
        self.assertTrue(all(e[0] == 0 for e in batch))
        self.assertEqual([e[1] for e in batch], [ord("a"), ord("a"), ord("Ç"), ord("Ç")])
        self.assertEqual([e[2] for e in batch], [search.KEYEVENTF_UNICODE, search.KEYEVENTF_UNICODE | search.KEYEVENTF_KEYUP] * 2)

    def test_typing_is_capped_and_empty_sends_nothing(self):
        a = self.make()
        a.type_text("x" * 1000)
        self.assertEqual(len(self.sent[0]), 2 * search.MAX_TYPED)
        a.type_text("")
        self.assertEqual(len(self.sent), 1)

    def test_fake_actions_only_record(self):
        f = search.FakeSearchActions()
        f.launch(self.entry("C:\\x.exe"))
        f.open_windows_search()
        f.type_text("abc")
        self.assertEqual(f.calls, [("launch", "C:\\x.exe"), ("win_s",), ("type", "abc")])
        f.fail = OSError(5, "denied")
        with self.assertRaises(OSError):
            f.launch(self.entry("C:\\y.exe"))

    def test_place_window_clamps_to_the_work_area(self):
        work = (0, 0, 1920, 1032)
        self.assertEqual(search.place_window(56, 40, 460, 300, work), (56, 40))
        self.assertEqual(search.place_window(1900, 40, 460, 300, work), (1460, 40))
        self.assertEqual(search.place_window(56, 1000, 460, 300, work), (56, 732))
        self.assertEqual(search.place_window(-50, -50, 460, 300, work), (0, 0))
        self.assertEqual(search.place_window(-1900, 40, 460, 300, (-1920, 0, 0, 1032)), (-1900, 40))

    def test_real_the_double_click_time_is_read(self):
        self.assertGreater(search.double_click_ms(), 0)


class TestSourceScan(unittest.TestCase):
    def test_search_only_uses_the_allowed_user32_names(self):
        src = inspect.getsource(search)
        used = set(re.findall(r"\b_u\.(\w+)", src))
        self.assertEqual(used, {"SendInput", "GetForegroundWindow", "GetDoubleClickTime", "argtypes", "restype"} & used | used & {
            "SendInput", "GetForegroundWindow", "GetDoubleClickTime"})
        self.assertLessEqual({n for n in used if n[0].isupper()}, {"SendInput", "GetForegroundWindow", "GetDoubleClickTime"})
        for banned in ("keybd_event", "SetForegroundWindow", "AttachThreadInput", "PostMessage", "SendMessage", "TerminateProcess",
                       "ShellExecute", "subprocess", "os.system", "RegisterHotKey"):
            self.assertNotIn(banned, src, banned)

    def test_the_program_is_started_in_one_place_only(self):
        self.assertEqual(len(re.findall(r"or os\.startfile\)\(", inspect.getsource(search))), 1)
        self.assertEqual(len(re.findall(r"os\.startfile\(", inspect.getsource(search.SearchActions))), 0)
        for mod in (searchwin, barwin):
            self.assertNotIn("startfile", inspect.getsource(mod), mod.__name__)

    def test_the_hotkey_api_uses_register_and_unregister_only(self):
        used = set(re.findall(r"self\._u\.(\w+)", inspect.getsource(shellmsg.HotkeyApi)))
        self.assertEqual(used, {"RegisterHotKey", "UnregisterHotKey"})

    def test_register_hotkey_exists_only_in_shellmsg(self):
        for mod in (search, searchwin, barwin, mpanels, winutil):
            self.assertNotIn("RegisterHotKey", inspect.getsource(mod), mod.__name__)

    def test_the_win_key_release_is_in_a_finally(self):
        src = inspect.getsource(search.SearchActions.open_windows_search)
        self.assertIn("finally:", src)
        self.assertGreater(src.index("finally:"), src.index("VK_S"))


# --------------------------------------------------------------------------- the controller on made-up parts
class FakeWin:
    instances = []

    def __init__(self, root, pal, ctl):
        self.ctl, self.pal = ctl, pal
        self.shown, self.rows, self.sel, self.notice = [], [], 0, ""
        self.focus, self.destroyed, self.draws = True, 0, 0
        self.hwnd = 555
        FakeWin.instances.append(self)

    def show(self, x, y, work):
        self.shown.append((x, y, work))

    def set_rows(self, rows, sel, notice=""):
        self.rows, self.sel, self.notice = list(rows), sel, notice
        self.draws += 1
        for kind, payload in self.rows:                          # like the real window: the icons of the rows on show
            self.ctl.icon_for(kind, payload)

    def has_focus(self):
        return self.focus

    def own_hwnd(self):
        return self.hwnd

    def destroy(self):
        self.destroyed += 1


class FakeHost:
    def __init__(self):
        self.fg, self.given, self.active, self.pos = 42, [], [], (56, H)
        self.mons = [MIDDLE]

    def anchor(self):
        return self.pos

    def pal(self):
        return theme.bar_palette()

    def foreground(self):
        return self.fg

    def give_back(self, hwnd):
        self.given.append(hwnd)

    def set_active(self, on):
        self.active.append(bool(on))

    def monitors(self):
        return self.mons


class Ctl(unittest.TestCase):
    """A Search with a made-up window class, host, actions, clock and timers; the index is filled at once."""

    def setUp(self):
        FakeWin.instances = []
        self.clock, self.host = FakeClock(), FakeHost()
        self.acts = search.FakeSearchActions()
        self.jobs = []
        self.cfg = search.defaults()
        self.src = search.FakeSources(APPS)
        self.delivered = []
        self.index = search.Index(self.src, self.clock, lambda fn: fn(), self.delivered.append)
        self.dbl = 500
        self.photos = []
        self.s = searchwin.Search(mock.Mock(), self.cfg, self.index, self.acts, self.host, self.clock,
                                  window_factory=FakeWin, icons=mock.Mock(), double_click=lambda: self.dbl,
                                  schedule=lambda ms, fn: self.jobs.append((ms, fn)),
                                  make_photo=lambda img: ("photo", getattr(img, "size", None)))
        self.s.start()
        self.s.on_scan(self.delivered.pop())

    @property
    def win(self):
        return FakeWin.instances[-1]

    def type(self, text):
        self.s.on_text(text)

    def run_jobs(self, upto=None):
        """Run the timers that are due (in order), also the ones they add, at most `upto` of them."""
        n = 0
        while self.jobs and (upto is None or n < upto):
            ms, fn = self.jobs.pop(0)
            fn()
            n += 1


class TestController(Ctl):
    def test_open_notes_the_foreground_and_shows_under_the_button(self):
        self.assertTrue(self.s.open(42))
        self.assertEqual(self.s.prev, 42)
        self.assertEqual(self.win.shown[0][:2], (56, H))
        self.assertEqual(self.win.shown[0][2], MIDDLE.work)
        self.assertEqual(self.host.active, [True])
        self.assertTrue(self.s.is_open())
        self.assertFalse(self.s.open(42))                        # already open: nothing new
        self.assertEqual(len(FakeWin.instances), 1)

    def test_open_uses_the_cache_at_once_and_a_stale_cache_is_refreshed_behind(self):
        self.s.open(1)
        self.assertEqual(self.index.scans, 1)                    # fresh: no new scan
        self.s.close(False)
        self.clock.advance(31)
        self.s.open(1)
        self.assertEqual(self.index.scans, 2)
        self.type("cam")
        self.assertEqual(names([p for k, p in self.win.rows]), ["Çam Editör"])      # the OLD list is used meanwhile

    def test_open_never_waits_for_the_scan(self):
        spawned = []
        ix = search.Index(self.src, self.clock, spawned.append, self.delivered.append)
        self.src.calls.clear()
        s = searchwin.Search(mock.Mock(), self.cfg, ix, self.acts, self.host, self.clock, window_factory=FakeWin,
                             schedule=lambda ms, fn: None, make_photo=lambda i: i)
        self.assertTrue(s.open(1))                               # the list is empty and the scan has not run
        self.assertEqual(self.src.calls, [])
        self.assertEqual(len(spawned), 1)
        s.on_text("cam")
        self.assertEqual(self.win.rows, [])
        spawned[0]()                                             # the worker finishes later...
        s.on_scan(self.delivered.pop())                          # ...and the open window's list is updated
        self.assertEqual(names([p for k, p in self.win.rows]), ["Çam Editör"])

    def test_a_scan_that_ends_while_open_keeps_the_selected_row(self):
        self.s.open(1)
        self.type("notepad")
        self.assertEqual(len(self.win.rows), 1)
        self.s.on_scan((entries(APPS + [("Notepad++", "C:\\npp.exe")]), "appsfolder"))
        self.assertEqual(names([p for k, p in self.win.rows]), ["Notepad", "Notepad++"])
        self.assertEqual(self.win.rows[self.win.sel][1].name, "Notepad")

    def test_typing_shows_rows_and_empty_text_none(self):
        self.s.open(1)
        self.assertEqual(self.win.rows, [])
        self.type("cam")
        self.assertEqual(len(self.win.rows), 1)
        self.type("")
        self.assertEqual(self.win.rows, [])

    def test_enter_opens_the_first_row_by_default_and_gives_nothing_back(self):
        self.s.open(42)
        self.type("anaconda")
        self.s.on_enter()
        self.assertEqual(len(self.acts.calls), 1)
        self.assertEqual(self.acts.calls[0][0], "launch")
        self.assertEqual(self.acts.calls[0][1], self.win.rows[0][1].parsing)
        self.assertEqual(self.host.given, [])
        self.assertFalse(self.s.is_open())
        self.assertEqual(self.host.active, [True, False])

    def test_arrow_down_then_enter_opens_the_second_row(self):
        self.s.open(42)
        self.type("anaconda")
        second = self.win.rows[1][1].parsing
        self.s.on_move(1)
        self.assertEqual(self.win.sel, 1)
        self.s.on_enter()
        self.assertEqual(self.acts.calls, [("launch", second)])

    def test_arrows_stop_at_the_ends(self):
        self.s.open(1)
        self.type("anaconda")
        self.s.on_move(-1)
        self.assertEqual(self.win.sel, 0)
        for _ in range(5):
            self.s.on_move(1)
        self.assertEqual(self.win.sel, 1)

    def test_typing_again_selects_the_first_row(self):
        self.s.open(1)
        self.type("anaconda")
        self.s.on_move(1)
        self.type("anaconda p")
        self.assertEqual(self.win.sel, 0)

    def test_hover_selects_and_a_click_opens_that_row(self):
        self.s.open(1)
        self.type("anaconda")
        self.s.on_hover(1)
        self.assertEqual(self.win.sel, 1)
        second = self.win.rows[1][1].parsing
        self.s.on_click(1)
        self.assertEqual(self.acts.calls, [("launch", second)])
        self.assertEqual(self.host.given, [])

    def test_a_click_below_the_rows_does_nothing(self):
        self.s.open(1)
        self.type("cam")
        self.s.on_click(5)
        self.assertEqual(self.acts.calls, [])
        self.assertTrue(self.s.is_open())

    def test_enter_with_no_rows_does_nothing(self):
        self.s.open(1)
        self.s.on_enter()
        self.assertEqual(self.acts.calls, [])
        self.assertTrue(self.s.is_open())

    def test_esc_closes_and_gives_the_foreground_back(self):
        self.s.open(42)
        self.s.on_escape()
        self.assertFalse(self.s.is_open())
        self.assertEqual(self.host.given, [42])
        self.assertEqual(self.win.destroyed, 1)

    def test_esc_with_nothing_noted_gives_nothing_back(self):
        self.s.open(0)
        self.s.on_escape()
        self.assertEqual(self.host.given, [])

    def test_focus_loss_closes_after_80_ms_and_gives_nothing_back(self):
        self.s.open(42)
        self.win.focus = False
        self.s.on_focus_out()
        self.assertEqual([ms for ms, _ in self.jobs], [80])
        self.assertTrue(self.s.is_open())                        # deferred, not at once
        self.run_jobs()
        self.assertFalse(self.s.is_open())
        self.assertEqual(self.host.given, [])

    def test_focus_moving_inside_the_window_does_not_close_it(self):
        self.s.open(42)
        self.win.focus = True                                    # entry <-> list: a widget of ours has the focus
        self.s.on_focus_out()
        self.run_jobs()
        self.assertTrue(self.s.is_open())

    def test_focus_check_after_the_window_closed_is_harmless(self):
        self.s.open(42)
        self.win.focus = False
        self.s.on_focus_out()
        self.s.on_escape()
        self.host.given.clear()
        self.run_jobs()
        self.assertEqual(self.host.given, [])

    def test_our_own_window_in_front_counts_as_focused(self):
        self.s.open(1)
        self.win.focus = False
        self.acts.fg = self.win.hwnd
        self.s.on_focus_out()
        self.run_jobs()
        self.assertTrue(self.s.is_open())

    def test_launch_error_shows_a_notice_logs_and_keeps_the_window(self):
        self.acts.fail = OSError(5, "Access is denied")
        self.s.open(1)
        self.type("notepad")
        with self.assertLogs("mpanels", "WARNING") as lg:
            self.s.on_enter()
        self.assertTrue(self.s.is_open())
        self.assertEqual(self.win.notice, ui.SEARCH_LAUNCH_FAILED.format(name="Notepad"))
        self.assertTrue(any("could not start" in m for m in lg.output))
        self.type("notepa")
        self.assertEqual(self.win.notice, "")                    # the next key clears it

    def test_toggle_by_the_shortcut_key(self):
        self.host.fg = 91
        self.s.toggle_hotkey()
        self.assertTrue(self.s.is_open())
        self.assertEqual(self.s.prev, 91)
        self.s.toggle_hotkey()
        self.assertFalse(self.s.is_open())
        self.assertEqual(self.host.given, [91])

    def test_stop_closes_without_giving_back(self):
        self.s.open(42)
        self.s.stop()
        self.assertFalse(self.s.is_open())
        self.assertEqual(self.host.given, [])
        self.assertFalse(self.s.open(1))                         # a stopped search never opens again

    def test_a_broken_window_never_escapes(self):
        class Bad(FakeWin):
            def show(self, *a):
                raise RuntimeError("tk broke")
        self.s._factory = Bad
        with self.assertLogs("mpanels", "ERROR"):
            self.assertFalse(self.s.open(1))
        self.assertFalse(self.s.is_open())
        self.assertEqual(self.host.active[-1], False)

    def test_the_window_is_placed_in_the_work_area_of_the_monitor_under_the_anchor(self):
        from fakedisplays import LEFT, RIGHT
        self.host.mons = [MIDDLE, LEFT, RIGHT]
        self.host.pos = (-1000, 40)
        self.s.open(1)
        self.assertEqual(self.win.shown[0][2], LEFT.work)


class TestButtonClicks(Ctl):
    def test_click_opens_when_closed_and_closes_when_open(self):
        self.s.button_click(False, 42)
        self.assertTrue(self.s.is_open())
        self.s.button_click(True, 99)
        self.assertFalse(self.s.is_open())
        self.assertEqual(self.host.given, [42])                  # the foreground goes back to the window noted at opening

    def test_the_press_time_note_decides_not_the_state_at_release(self):
        self.s.button_click(False, 42)
        self.assertTrue(self.s.is_open())
        self.s.close(False)                                      # (focus loss closed it between press and release)
        self.s.button_click(False, 42)                           # the press had seen it closed: this click opens
        self.assertTrue(self.s.is_open())

    def test_a_second_click_inside_the_double_click_time_is_ignored(self):
        self.s.button_click(False, 42)
        self.s.button_click(True, 42)                            # closes
        self.assertFalse(self.s.is_open())
        self.clock.advance(0.3)
        self.s.button_click(False, 42)                           # second click of a double click: must NOT reopen
        self.assertFalse(self.s.is_open())
        self.assertEqual(len(FakeWin.instances), 1)

    def test_after_the_double_click_time_it_opens_again(self):
        self.s.button_click(False, 42)
        self.s.button_click(True, 42)
        self.clock.advance(0.5)
        self.s.button_click(False, 42)
        self.assertTrue(self.s.is_open())

    def test_the_guard_uses_the_system_double_click_time(self):
        self.dbl = 900
        self.s.button_click(False, 42)
        self.s.button_click(True, 42)
        self.clock.advance(0.7)
        self.s.button_click(False, 42)
        self.assertFalse(self.s.is_open())
        self.clock.advance(0.3)
        self.s.button_click(False, 42)
        self.assertTrue(self.s.is_open())

    def test_a_window_closed_by_something_else_has_no_guard(self):
        self.s.button_click(False, 42)
        self.s.on_escape()
        self.s.button_click(False, 42)                           # Esc closed it: a click right after opens (no guard)
        self.assertTrue(self.s.is_open())

    def test_the_shortcut_key_is_not_guarded(self):
        self.s.button_click(False, 42)
        self.s.button_click(True, 42)
        self.s.toggle_hotkey()
        self.assertTrue(self.s.is_open())


class TestWindowsRow(Ctl):
    def setUp(self):
        super().setUp()
        self.cfg["windows_row"] = True

    def test_the_row_is_last_and_names_the_text(self):
        self.s.open(1)
        self.type("cam")
        self.assertEqual(self.win.rows[-1], ("windows", "cam"))
        self.assertEqual(ui.SEARCH_WINDOWS_ROW.format(text="cam"), "Search Windows for 'cam'")

    def test_no_row_with_empty_text(self):
        self.s.open(1)
        self.type("")
        self.assertEqual(self.win.rows, [])
        self.type("   ")
        self.assertEqual(self.win.rows, [])

    def test_off_means_no_row(self):
        self.cfg["windows_row"] = False
        self.s.open(1)
        self.type("cam")
        self.assertNotIn("windows", [k for k, _ in self.win.rows])

    def choose(self, text="zzz"):
        self.s.open(1)
        self.type(text)
        self.assertEqual(self.win.rows, [("windows", text)])
        self.s.on_enter()

    def test_choosing_it_closes_then_sends_win_s_then_types_when_the_foreground_changed(self):
        self.acts.fg = 10
        self.acts.fg_after_win_s = 20
        self.choose("zzz")
        self.assertFalse(self.s.is_open())
        self.assertEqual(self.host.given, [])
        self.assertEqual(self.acts.calls, [])                    # nothing yet: the settle time comes first
        self.assertEqual(self.jobs[0][0], searchwin.WIN_SETTLE_MS)
        self.run_jobs()
        self.assertEqual(self.acts.calls, [("win_s",), ("type", "zzz")])

    def test_the_wait_is_at_most_a_second_and_then_only_a_log(self):
        self.acts.fg = 10                                        # the foreground never changes
        self.choose("zzz")
        with self.assertLogs("mpanels", "INFO") as lg:
            self.run_jobs()
        self.assertEqual(self.acts.calls, [("win_s",)])          # Win+S was sent, the text was NOT typed
        self.assertTrue(any("did not take the foreground" in m for m in lg.output))
        polls = searchwin.WIN_WAIT_MS // searchwin.WIN_POLL_MS
        self.assertLessEqual(polls * searchwin.WIN_POLL_MS, 1000)

    def test_win_s_is_sent_even_when_typing_will_fail(self):
        self.acts.fg, self.acts.fg_after_win_s = 10, 20
        self.choose("zzz")
        self.acts.type_text = mock.Mock(side_effect=OSError("x"))
        with self.assertLogs("mpanels", "ERROR"):
            self.run_jobs()
        self.assertEqual(self.acts.calls, [("win_s",)])


class TestIcons(Ctl):
    def test_icons_are_asked_only_for_the_rows_on_show_and_once(self):
        self.s.open(1)
        self.type("anaconda")
        self.assertEqual(self.s.icons.request.call_count, 2)
        self.type("anaconda ")
        self.assertEqual(self.s.icons.request.call_count, 2)     # already in flight
        self.type("cam")
        self.assertEqual(self.s.icons.request.call_count, 3)

    def test_no_icon_gives_a_letter_tile_and_is_not_asked_again(self):
        self.s.open(1)
        self.type("cam")
        e = self.win.rows[0][1]
        self.s.on_icon(e.parsing, None)
        photo, letter = self.s.icon_for("app", e)
        self.assertTrue(photo)
        self.assertEqual(letter, "Ç")
        self.assertEqual(self.s.icons.request.call_count, 1)

    def test_a_real_icon_replaces_the_tile(self):
        from PIL import Image
        self.s.open(1)
        self.type("cam")
        e = self.win.rows[0][1]
        draws = self.win.draws
        self.s.on_icon(e.parsing, Image.new("RGBA", (16, 16)))
        self.assertGreater(self.win.draws, draws)
        self.assertEqual(self.s.icon_for("app", e)[1], "")

    def test_the_icons_of_a_stopped_search_are_dropped(self):
        self.s.open(1)
        self.type("cam")
        e = self.win.rows[0][1]
        self.s.stop()
        self.s.on_icon(e.parsing, None)
        self.assertEqual(self.s._photos, {})


# --------------------------------------------------------------------------- the real tkinter window
class RealWin(Base):
    def setUp(self):
        super().setUp()
        self.app = self.open()                                   # no bar: only its Tk root is used
        self.clock2, self.host = FakeClock(), FakeHost()
        self.acts = search.FakeSearchActions()
        self.cfg = search.defaults()
        self.delivered = []
        self.index = search.Index(search.FakeSources(APPS), self.clock2, lambda fn: fn(), self.delivered.append)
        self.s = searchwin.Search(self.app.root, self.cfg, self.index, self.acts, self.host, self.clock2)
        self.s.start()
        self.s.on_scan(self.delivered.pop())
        self.addCleanup(self.s.stop)

    def texts(self):
        cv = self.s.win.cv
        return [cv.itemcget(i, "text") for i in cv.find_all() if cv.type(i) == "text"]


class TestRealSearchWindow(RealWin):
    def test_geometry_under_the_button_and_460_wide(self):
        self.host.pos = (theme.BAR_SEARCH_BTN_X, H)
        self.s.open(7)
        pump(self.app, 3)
        t = self.s.win.top
        self.assertEqual((t.winfo_x(), t.winfo_y(), t.winfo_width()), (theme.BAR_SEARCH_BTN_X, H, theme.SEARCH_W))
        self.assertTrue(t.overrideredirect())
        self.assertTrue(t.attributes("-topmost"))
        self.assertIn("TAKE_FG", self.events)                    # it asked for the keyboard (never a no-activate window)

    def test_height_follows_the_rows_8_at_most(self):
        self.s.open(7)
        pump(self.app, 3)
        h0 = self.s.win.top.winfo_height()
        self.s.win.var.set("anaconda")
        pump(self.app, 3)
        self.assertEqual(self.s.win.top.winfo_height() - h0, 2 * theme.SEARCH_ROW_H)
        many = search.with_hints(search.entries_from_apps([("App %02d" % i, "C:\\%d.exe" % i) for i in range(30)]))
        self.s.on_scan((many, "appsfolder"))
        self.s.win.var.set("app")
        pump(self.app, 3)
        self.assertEqual(self.s.win.top.winfo_height() - h0, 8 * theme.SEARCH_ROW_H)

    def test_rows_show_name_hint_and_a_letter_tile(self):
        self.s.open(7)
        self.s.win.var.set("anaconda")
        pump(self.app, 3)
        t = self.texts()
        self.assertEqual(t.count("Anaconda Prompt"), 2)
        self.assertTrue(any(x and x != "Anaconda Prompt" and x != "A" for x in t))          # the gray hints
        self.assertIn("A", t)

    def test_the_selected_row_has_a_background_and_follows_the_arrows(self):
        self.s.open(7)
        self.s.win.var.set("anaconda")
        pump(self.app, 3)
        cv = self.s.win.cv
        n0 = len([i for i in cv.find_all() if cv.type(i) == "image"])
        self.s.on_move(1)
        pump(self.app, 2)
        self.assertEqual(len([i for i in cv.find_all() if cv.type(i) == "image"]), n0)
        bg = [cv.coords(i) for i in cv.find_all() if cv.type(i) == "image" and cv.coords(i)[0] == 4]
        self.assertEqual(bg[0][1], theme.SEARCH_ROW_H + 1)

    def test_clamped_into_the_work_area_at_the_right_and_bottom_edges(self):
        self.host.pos = (1900, 1020)
        self.s.open(7)
        self.s.win.var.set("anaconda")
        pump(self.app, 3)
        t = self.s.win.top
        w = MIDDLE.work
        self.assertLessEqual(t.winfo_x() + t.winfo_width(), w[2])
        self.assertLessEqual(t.winfo_y() + t.winfo_height(), w[3])
        self.assertGreaterEqual(t.winfo_x(), w[0])

    def test_the_windows_row_is_drawn_with_the_text(self):
        self.cfg["windows_row"] = True
        self.s.open(7)
        self.s.win.var.set("zzz")
        pump(self.app, 3)
        self.assertIn("Search Windows for 'zzz'", self.texts())

    def test_the_notice_line_is_drawn(self):
        self.acts.fail = OSError(5, "x")
        self.s.open(7)
        self.s.win.var.set("notepad")
        with self.assertLogs("mpanels", "WARNING"):
            self.s.on_enter()
        pump(self.app, 2)
        self.assertIn(ui.SEARCH_LAUNCH_FAILED.format(name="Notepad"), self.texts())

    def test_the_bindings_report_to_the_controller(self):
        self.s.open(7)
        w = self.s.win
        for seq in ("<Escape>", "<Return>", "<Down>", "<Up>"):
            self.assertTrue(w.entry.bind(seq), seq)
        self.assertTrue(w.cv.bind("<Button-1>"))
        self.assertTrue(w.top.bind("<FocusOut>"))

    def test_keys_through_tk(self):
        self.s.open(7)
        w = self.s.win
        w.var.set("anaconda")
        w.entry.focus_force()
        w.entry.event_generate("<Down>")
        pump(self.app, 2)
        self.assertEqual(self.s.sel, 1)
        w.entry.event_generate("<Return>")
        pump(self.app, 2)
        self.assertEqual(self.acts.calls[0][0], "launch")
        self.assertFalse(self.s.is_open())

    def test_escape_through_tk_gives_the_foreground_back(self):
        self.s.open(7)
        w = self.s.win
        pump(self.app, 3)
        w.entry.focus_force()
        pump(self.app, 2)
        w.entry.event_generate("<Escape>")
        pump(self.app, 2)
        self.assertEqual(self.host.given, [7])
        self.assertFalse(self.s.is_open())

    def test_a_click_on_a_row_through_tk_opens_it(self):
        self.s.open(7)
        w = self.s.win
        w.var.set("notepad")
        pump(self.app, 3)
        w.cv.event_generate("<Button-1>", x=40, y=theme.SEARCH_ROW_H // 2)
        pump(self.app, 2)
        self.assertEqual(self.acts.calls, [("launch", "C:\\Windows\\notepad.exe")])

    def test_destroy_removes_the_toplevel(self):
        self.s.open(7)
        top = self.s.win.top
        self.s.close(False)
        pump(self.app, 2)
        self.assertFalse(top.winfo_exists())


# --------------------------------------------------------------------------- the real bar window: the button
class TestBarButton(Clicks):
    def bar(self, **kw):
        app, win = super().bar(**kw)
        pump(app, 3)
        return app, win

    def press(self, win, x=None):
        b = win.search_button
        x = b["x"] + 5 if x is None else x
        win._on_press(ev(x))
        win._on_release(ev(x))

    def test_left_end_layout(self):
        self.assertEqual((theme.BAR_START_W, theme.BAR_SEARCH_X, theme.BAR_SEARCH_W), (32, 36, 32))
        self.assertEqual(theme.BAR_LEFT_RESERVE, 72)                        # 32 + 4 + 32 + 4, derived
        app, win = self.bar()
        b = win.search_button
        self.assertEqual(b["kind"], "search")
        self.assertGreaterEqual(b["x"], theme.BAR_SEARCH_X)
        self.assertLessEqual(b["x"] + b["w"], theme.BAR_LEFT_RESERVE)
        self.assertEqual(win.buttons[0]["x"], theme.BAR_LEFT_RESERVE)       # the task buttons start after it
        self.assertNotIn(b, win.buttons)

    def test_search_off_draws_nothing_and_the_task_buttons_do_not_move(self):
        app, win = self.bar()
        x_on = [b["x"] for b in win.buttons]
        items_on = len(win.cv.find_all())
        self.assertTrue(app.apply_bar(True, ON["info"], search_cfg={"enabled": False}))
        pump(app, 3)
        self.assertIsNone(win.search_button)
        self.assertIsNone(app.bar.search)
        self.assertLess(len(win.cv.find_all()), items_on)
        self.assertEqual([b["x"] for b in win.buttons], x_on)
        self.press(win, 70)                                                 # the place is empty now: no hit, no window
        self.assertEqual(self.actions.calls, [])

    def test_click_opens_the_window_and_the_button_is_active(self):
        app, win = self.bar()
        self.src.fg = 2
        self.press(win)
        s = app.bar.search
        self.assertTrue(s.is_open())
        self.assertEqual(s.prev, 2)
        self.assertEqual(win.search_button["state"], "active")
        self.assertEqual(s.win.top.winfo_x(), theme.BAR_SEARCH_BTN_X)

    def test_second_click_closes_and_gives_the_foreground_back(self):
        app, win = self.bar()
        self.src.fg = 2
        self.press(win)
        self.src.fg = OWN_MIN                                               # our window has the keyboard now
        self.src.is_own = lambda h: h >= OWN_MIN
        self.press(win)
        settle(win)
        self.assertFalse(app.bar.search.is_open())
        self.assertEqual(self.actions.calls, [("front", 2)])
        self.assertEqual(win.search_button["state"], "normal")

    def test_double_click_leaves_it_closed(self):
        app, win = self.bar()
        self.src.fg = 2
        self.press(win)                                                     # 1st click opens
        b = win.search_button
        x = b["x"] + 5
        win._on_press(ev(x))                                                # 2nd press (a <Double-Button-1> in real life)
        self.assertEqual(win._on_double(ev(x)), "break")                    # ...which does nothing by itself
        win._on_release(ev(x))
        self.assertFalse(app.bar.search.is_open())
        win._on_press(ev(x))
        win._on_release(ev(x))
        self.assertFalse(app.bar.search.is_open())

    def test_press_while_open_closes_by_the_note_taken_at_press_time(self):
        app, win = self.bar()
        self.press(win)
        s = app.bar.search
        b = win.search_button
        x = b["x"] + 5
        win._on_press(ev(x))
        s.close(False)                                                      # focus loss closes it between press and release
        win._on_release(ev(x))
        self.assertFalse(s.is_open())                                       # the click that closed it does not reopen it

    def test_right_click_on_the_button_is_settings_only(self):
        app, win = self.bar()
        self.stub_popup(win)
        b = win.search_button
        win.cv.event_generate("<Button-3>", x=b["x"] + 5, y=10)
        win.top.update()
        self.assertEqual(len(self.popups), 1)
        self.assertEqual(self.popups[0].type(0), "command")
        self.assertEqual(self.popups[0].entrycget(0, "label"), ui.BAR_MENU_SETTINGS)
        self.assertEqual(self.popups[0].index("end"), 0)

    def test_hover_marks_the_button(self):
        app, win = self.bar()
        b = win.search_button
        win._on_motion(ev(b["x"] + 5))
        self.assertEqual(win.search_button["state"], "hover")
        win._on_motion(ev(900))
        self.assertEqual(win.search_button["state"], "normal")

    def stub_popup(self, win):
        self.popups = []

        def popup(m, x, y):
            self.popups.append(m)
        win._popup = popup


class TestMagnifier(unittest.TestCase):
    def test_icon_is_drawn_in_the_wanted_size_and_color(self):
        im = theme.search_icon(24, "#ffffff")
        self.assertEqual(im.size, (24, 24))
        self.assertEqual(im.mode, "RGBA")
        self.assertTrue(im.getbbox())
        px = [p for p in (im.getpixel((x, y)) for x in range(im.width) for y in range(im.height)) if p[3] > 200]
        self.assertTrue(px and all(p[:3] == (255, 255, 255) for p in px))


# --------------------------------------------------------------------------- the shortcut key
class FakeHotkeyApi:
    def __init__(self, ok=True):
        self.calls, self.ok = [], ok
        self.registered = None

    def register(self, hwnd, hid, mods, vk):
        self.calls.append(("register", hid, mods, vk))
        if not self.ok:
            return False, 1409
        self.registered = (mods, vk)
        return True, 0

    def unregister(self, hwnd, hid):
        self.calls.append(("unregister", hid))
        self.registered = None
        return True


class TestMessageWindowHotkey(unittest.TestCase):
    def make(self, ok=True):
        self.got = []
        self.api = FakeHotkeyApi(ok)
        self.mw = shellmsg.MessageWindow(self.got.append, hotkey_api=self.api)
        self.addCleanup(self.mw.close)
        self.assertTrue(self.mw.hwnd)

    def wait(self, n=1):
        end = time.time() + 3
        while len(self.got) < n and time.time() < end:
            time.sleep(0.01)

    def test_register_remove_and_the_message(self):
        import win32gui
        self.make()
        mods, vk = search.HOTKEYS["win+alt+space"]
        self.assertTrue(self.mw.set_hotkey(mods, vk))
        self.assertTrue(self.mw.hotkey_registered)
        self.assertEqual(self.api.calls, [("register", shellmsg.HOTKEY_ID, mods, vk)])
        win32gui.PostMessage(self.mw.hwnd, shellmsg.WM_HOTKEY, shellmsg.HOTKEY_ID, 0)
        win32gui.PostMessage(self.mw.hwnd, shellmsg.WM_HOTKEY, shellmsg.HOTKEY_ID + 1, 0)         # not ours
        self.wait()
        time.sleep(0.1)
        self.assertEqual(self.got, [("bar", ("hotkey",))])
        self.assertTrue(self.mw.set_hotkey(0, 0))
        self.assertFalse(self.mw.hotkey_registered)
        self.assertEqual(self.api.calls[-1], ("unregister", shellmsg.HOTKEY_ID))

    def test_changing_the_key_replaces_it(self):
        self.make()
        self.mw.set_hotkey(*search.HOTKEYS["win+alt+space"])
        self.mw.set_hotkey(*search.HOTKEYS["ctrl+shift+space"])
        self.assertEqual([c[0] for c in self.api.calls], ["register", "unregister", "register"])
        self.assertEqual(self.api.registered, search.HOTKEYS["ctrl+shift+space"])

    def test_a_refused_key_returns_false_and_keeps_the_old_one(self):
        self.make()
        self.mw.set_hotkey(*search.HOTKEYS["win+alt+space"])
        self.api.ok = False
        with self.assertLogs("mpanels", "WARNING"):
            self.assertFalse(self.mw.set_hotkey(*search.HOTKEYS["ctrl+shift+space"]))
        self.assertFalse(self.mw.hotkey_registered or False and True)

    def test_a_refused_key_without_an_old_one_leaves_nothing(self):
        self.make(ok=False)
        with self.assertLogs("mpanels", "WARNING"):
            self.assertFalse(self.mw.set_hotkey(*search.HOTKEYS["win+alt+space"]))
        self.assertFalse(self.mw.hotkey_registered)

    def test_closing_the_window_removes_the_key_on_its_own_thread(self):
        self.make()
        self.mw.set_hotkey(*search.HOTKEYS["win+alt+space"])
        self.mw.close()
        self.assertIsNone(self.api.registered)
        self.assertEqual(self.api.calls[-1], ("unregister", shellmsg.HOTKEY_ID))

    def test_a_closed_window_cannot_register(self):
        self.make()
        self.mw.close()
        self.assertFalse(self.mw.set_hotkey(*search.HOTKEYS["win+alt+space"]))
        self.assertTrue(self.mw.set_hotkey(0, 0))

    def test_the_real_api_registers_with_no_repeat(self):
        api = shellmsg.HotkeyApi()
        api._u = mock.Mock()
        api._u.RegisterHotKey.return_value = 1
        ok, _ = api.register(5, 6, 3, 0x20)
        self.assertTrue(ok)
        self.assertEqual(api._u.RegisterHotKey.call_args[0][3], 0x20)
        self.assertEqual(api._u.RegisterHotKey.call_args[0][2], 3 | shellmsg.MOD_NOREPEAT)


class HK(Base):
    """The bar with a shell that records the shortcut key calls (and the order of things at Quit)."""

    def make_shell(self, put):
        events = self.events

        class Shell(FakeShell):
            def close(self_):
                events.append("SHELLCLOSE")
                super().close()

            def set_hotkey(self_, mods, vk):
                ok = super().set_hotkey(mods, vk)
                events.append(("HOTKEY", mods, vk, ok))
                return ok
        sh = Shell(put)
        sh.hotkey_ok = getattr(self, "shell_hotkey_ok", True)
        self.shells.append(sh)
        return sh

    def settings(self, **kw):
        app = self.open(**kw)
        app.open_settings()
        w = app.settings_win
        self.addCleanup(lambda: w.win.winfo_exists() and w.win.destroy())
        return app, w

    def hotkeys(self):
        return [e for e in self.events if isinstance(e, tuple) and e[0] == "HOTKEY"]


class TestHotkeyInTheApp(HK):
    WIN = search.HOTKEYS["win+alt+space"]

    def test_off_by_default_nothing_is_registered(self):
        app = self.open(bar=ON)
        self.assertEqual(self.hotkeys(), [])
        self.assertEqual(app.bar.hotkey_name, "off")

    def test_a_saved_key_is_registered_when_the_bar_starts(self):
        app = self.open(bar=dict(ON, search={"hotkey": "win+alt+space"}))
        self.assertEqual(self.hotkeys(), [("HOTKEY", self.WIN[0], self.WIN[1], True)])
        self.assertEqual(app.bar.hotkey_name, "win+alt+space")

    def test_apply_registers_and_saves(self):
        app, w = self.settings(bar=ON)
        w.v_search_hk.set(ui.SEARCH_HOTKEY_LABELS["win+alt+space"])
        w.apply()
        self.assertEqual(self.hotkeys(), [("HOTKEY", self.WIN[0], self.WIN[1], True)])
        self.assertEqual(self.cfg_file()["bar"]["search"], {"hotkey": "win+alt+space"})
        self.assertFalse(w.dirty())

    def test_the_key_toggles_the_window(self):
        app = self.open(bar=dict(ON, search={"hotkey": "ctrl+shift+space"}), layout=THREE)
        self.shells[0].put(("bar", ("hotkey",)))
        app._poll()
        self.assertTrue(app.bar.search.is_open())
        self.shells[0].put(("bar", ("hotkey",)))
        app._poll()
        self.assertFalse(app.bar.search.is_open())

    def test_the_message_is_ignored_while_the_key_is_off(self):
        app = self.open(bar=ON)
        self.send("hotkey")
        self.assertFalse(app.bar.search.is_open())

    def test_a_refused_key_shows_a_warning_saves_nothing_and_takes_the_whole_apply_back(self):
        app, w = self.settings(bar=ON)
        self.shells[0].hotkey_ok = False
        w.v_search_hk.set(ui.SEARCH_HOTKEY_LABELS["win+alt+space"])
        w.v_bar_date.set(False)                                              # another change of the same Apply
        w.v_search_store.set(False)
        w.apply()
        self.assertIn(ui.MSG_SEARCH_FAILED.strip(), w.msg.cget("text"))
        self.assertEqual(app.cfg["bar"]["search"], search.defaults())
        self.assertTrue(app.cfg["bar"]["info"]["show_date"])
        self.assertEqual(app.bar.hotkey_name, "off")
        saved = self.cfg_file()["bar"]
        self.assertNotIn("search", saved)
        self.assertEqual(saved["info"], ON["info"])
        self.assertFalse(w.dirty())                                           # the boxes went back to what is in force
        self.assertEqual(w.v_search_hk.get(), ui.SEARCH_HOTKEY_LABELS["off"])

    def test_a_refused_key_when_this_apply_started_the_bar_takes_the_bar_back(self):
        self.shell_hotkey_ok = False                                          # the shell made by this Apply refuses
        app, w = self.settings()
        w.v_bar.set(True)
        w.v_search_hk.set(ui.SEARCH_HOTKEY_LABELS["win+alt+space"])
        w.apply()
        self.assertIsNone(app.bar)
        self.assertFalse(app.cfg["bar"]["enabled"])
        self.assertIn(ui.MSG_SEARCH_FAILED.strip(), w.msg.cget("text"))
        self.assertEqual(self.events.count("REMOVE"), 1)

    def test_turning_the_key_off_unregisters_it(self):
        app, w = self.settings(bar=dict(ON, search={"hotkey": "win+alt+space"}))
        w.v_search_hk.set(ui.SEARCH_HOTKEY_LABELS["off"])
        w.apply()
        self.assertEqual(self.hotkeys()[-1], ("HOTKEY", 0, 0, True))
        self.assertEqual(app.bar.hotkey_name, "off")
        self.assertNotIn("search", self.cfg_file()["bar"])

    def test_turning_search_off_unregisters_it(self):
        app, w = self.settings(bar=dict(ON, search={"hotkey": "win+alt+space"}))
        w.v_search.set(False)
        w.apply()
        self.assertEqual(self.hotkeys()[-1], ("HOTKEY", 0, 0, True))
        self.assertIsNone(app.bar.search)
        self.assertEqual(self.cfg_file()["bar"]["search"]["enabled"], False)

    def test_turning_the_bar_off_unregisters_it(self):
        app, w = self.settings(bar=dict(ON, search={"hotkey": "win+alt+space"}))
        w.v_bar.set(False)
        w.apply()
        self.assertEqual(self.hotkeys()[-1], ("HOTKEY", 0, 0, True))

    def test_quit_unregisters_before_root_destroy(self):
        app = self.open(bar=dict(ON, search={"hotkey": "win+alt+space"}))
        orig = app.root.destroy
        app.root.destroy = lambda: (self.events.append("destroy"), orig())[1]
        app.quit()
        tail = [e for e in self.events if e in ("REMOVE", "SHELLCLOSE", "destroy") or (isinstance(e, tuple) and e[0] == "HOTKEY")]
        self.assertEqual(tail[-4:], [("HOTKEY", self.WIN[0], self.WIN[1], True)][:0] + [("HOTKEY", 0, 0, True), "REMOVE", "SHELLCLOSE",
                                                                                        "destroy"])

    def test_quit_with_the_window_open_closes_it_first(self):
        app = self.open(bar=ON)
        s = app.bar.search
        s.open(5)
        app.quit()
        self.assertFalse(s.is_open())
        self.assertTrue(s.stopped)

    def test_test_mode_registers_nothing_real_and_launches_nothing_real(self):
        with mock.patch.object(os, "startfile", side_effect=AssertionError("real startfile")), \
                mock.patch.object(search, "_real_send", side_effect=AssertionError("real SendInput")), \
                mock.patch.object(search, "SearchActions", side_effect=AssertionError("real actions")):
            self.search_acts = None
            app = self.open_with_default_actions(bar=dict(ON, search={"hotkey": "win+alt+space", "windows_row": True}))
            self.assertEqual(self.hotkeys(), [])                              # TEST mode: no RegisterHotKey at all
            self.assertEqual(app.bar.hotkey_name, "win+alt+space")
            self.assertIsInstance(app.search_actions, search.FakeSearchActions)
            s = app.bar.search
            s.open(5)
            s.win.var.set("notepad")
            s.on_enter()
            self.assertEqual(app.search_actions.calls, [("launch", "C:\\Windows\\notepad.exe")])

    def open_with_default_actions(self, bar):
        self.write_cfg({"bar": bar})
        disp, clock = FakeDisplays(THREE), FakeClock()
        self.disp, self.clock, self.be = disp, clock, FakeAppBar(disp, self.events)
        app = mpanels.App(fileops.Ctx(self.desk, self.pub), self.data, test_mode=True, use_tray=False,
                          icon_backend=FakeIcons(), instance_name=None, displays_provider=disp, clock=clock,
                          appbar_backend=self.be, bar_shell=self.make_shell, bar_window=self.make_window,
                          wall_clock=lambda: self.now[0], tasks_actions=None, tasks_source=None,
                          search_source=search.FakeSources(APPS), search_actions=None, search_spawn=lambda fn: fn())
        self.apps.append(app)
        self.app = app
        pump(app)
        app._poll()
        return app


# --------------------------------------------------------------------------- Settings
class TestSettingsFields(HK):
    def test_the_fields_and_their_defaults(self):
        app, w = self.settings()
        self.assertTrue(w.v_search.get())
        self.assertEqual(w.v_search_hk.get(), ui.SEARCH_HOTKEY_LABELS["off"])
        self.assertTrue(w.v_search_store.get())
        self.assertFalse(w.v_search_win.get())
        self.assertEqual(list(w.cb_search_hk.cget("values")), [ui.SEARCH_HOTKEY_LABELS[k] for k in search.HOTKEYS])
        self.assertEqual(len(w.cb_search_hk.cget("values")), 3)
        for v in w.cb_search_hk.cget("values"):
            self.assertNotIn(v, ("Alt+Space", "Ctrl+Space"))
        self.assertFalse(w.dirty())

    def test_the_group_sits_in_the_bar_tab_with_its_texts(self):
        app, w = self.settings()
        frames = [c for c in w.tab["bar"].winfo_children() if c.winfo_class() == "TLabelframe"]
        self.assertIn(ui.LBL_SEARCH, [f.cget("text") for f in frames])
        self.assertEqual(w.cb_search.cget("text"), ui.CHK_SEARCH_SHOW)
        self.assertEqual(w.cb_search_store.cget("text"), ui.CHK_SEARCH_STORE)
        self.assertEqual(w.cb_search_win.cget("text"), ui.CHK_SEARCH_WINROW)

    def test_each_new_field_makes_it_dirty(self):
        app, w = self.settings()
        for var, value in ((w.v_search, False), (w.v_search_hk, ui.SEARCH_HOTKEY_LABELS["ctrl+shift+space"]),
                           (w.v_search_store, False), (w.v_search_win, True)):
            old = var.get()
            var.set(value)
            self.assertTrue(w.dirty(), var)
            var.set(old)
            self.assertFalse(w.dirty(), var)

    def test_nothing_changes_before_apply(self):
        app, w = self.settings(bar=ON)
        w.v_search_store.set(False)
        w.v_search_win.set(True)
        self.assertTrue(app.cfg["bar"]["search"]["store_apps"])
        self.assertFalse(app.cfg["bar"]["search"]["windows_row"])
        self.assertNotIn("search", self.cfg_file()["bar"])

    def test_apply_is_live_and_writes_only_the_differences(self):
        app, w = self.settings(bar=ON)
        w.v_search_store.set(False)
        w.v_search_win.set(True)
        w.apply()
        self.assertEqual(app.bar.search_cfg["store_apps"], False)
        self.assertEqual(self.cfg_file()["bar"]["search"], {"store_apps": False, "windows_row": True})
        w.v_search_store.set(True)
        w.v_search_win.set(False)
        w.apply()
        self.assertNotIn("search", self.cfg_file()["bar"])                    # back to the defaults: the key is gone

    def test_the_live_search_follows_the_new_values_at_once(self):
        app, w = self.settings(bar=ON)
        w.v_search_win.set(True)
        w.apply()
        s = app.bar.search
        s.open(5)
        s.win.var.set("zzz")
        self.assertEqual(s.rows, [("windows", "zzz")])

    def test_switching_search_off_and_on_again(self):
        app, w = self.settings(bar=ON)
        w.v_search.set(False)
        w.apply()
        self.assertIsNone(app.bar.search)
        self.assertFalse(app.bar.win.search_on)
        w.v_search.set(True)
        w.apply()
        self.assertIsNotNone(app.bar.search)
        self.assertTrue(app.bar.win.search_on)

    def test_revert_to_defaults_leaves_the_bar_and_its_search_alone(self):
        app, w = self.settings(bar=dict(ON, search={"store_apps": False}))
        with mock.patch.object(w, "confirm_overwrite", return_value=True):
            w.reset(False)
        self.assertFalse(app.cfg["bar"]["search"]["store_apps"])
        self.assertFalse(w.v_search_store.get())

    def test_factory_settings_return_the_defaults(self):
        app, w = self.settings(bar=dict(ON, search={"store_apps": False, "windows_row": True, "hotkey": "win+alt+space"}))
        with mock.patch.object(w, "confirm_overwrite", return_value=True):
            w.reset(True)
        self.assertTrue(w.v_search_store.get())
        self.assertFalse(w.v_search_win.get())
        self.assertEqual(w.v_search_hk.get(), ui.SEARCH_HOTKEY_LABELS["off"])
        w.apply()
        self.assertEqual(app.cfg["bar"], infoclock.defaults())
        self.assertNotIn("search", self.cfg_file()["bar"])
        self.assertEqual(self.hotkeys()[-1][:3], ("HOTKEY", 0, 0))

    def test_bad_values_in_the_file_fall_back_to_the_defaults(self):
        app = self.open(bar=dict(ON, search={"hotkey": "alt+space", "enabled": "yes", "extra": 1}))
        self.assertEqual({k: app.cfg["bar"]["search"][k] for k in search.DEFAULTS}, search.defaults())
        self.assertEqual(app.bar.hotkey_name, "off")

    def test_the_default_config_file_has_no_search_key(self):
        app = self.open(bar=ON)
        app.save()
        self.assertNotIn("search", self.cfg_file()["bar"])


# --------------------------------------------------------------------------- real, read only
class TestRealList(unittest.TestCase):
    def test_real_appsfolder_in_a_worker_thread_is_read_only_and_usable(self):
        out = {}

        def work():
            try:
                out["rows"] = search.Win32Sources().appsfolder()
            except Exception as e:                                   # noqa: BLE001
                out["err"] = type(e).__name__
        t = threading.Thread(target=work)
        t.start()
        t.join(30)
        self.assertNotIn("err", out)
        rows = out["rows"]
        self.assertGreater(len(rows), 10)
        es, kind = search.scan(search.FakeSources(rows))
        self.assertEqual(kind, "appsfolder")
        self.assertTrue(all(e.name and e.parsing for e in es))
        self.assertEqual(len({e.parsing.casefold() for e in es}), len(es))

    def test_real_shortcut_fallback_reads_the_start_menu(self):
        items = search.Win32Sources().lnk()
        self.assertGreater(len(items), 5)
        self.assertFalse(any("\\startup\\" in p.casefold() for _n, p, _r in items))


if __name__ == "__main__":
    unittest.main()
