"""v1.2 step 1: the bar (AppBar strip at the top of the main monitor) and its Info section.
Nothing here asks Windows: the AppBar backend, the owner/message window, the bar window, the monitors and the clock are
made up. The real App, real panel windows and the real Settings window are used on top of them."""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import appbar  # noqa: E402
import barwin  # noqa: E402
import displays  # noqa: E402
import fileops  # noqa: E402
import infoclock  # noqa: E402
import mpanels  # noqa: E402
import search  # noqa: E402
import startmenu  # noqa: E402
import strings as ui  # noqa: E402
import tasks  # noqa: E402
import theme  # noqa: E402
import winutil  # noqa: E402
from fakedisplays import MIDDLE, ONE, THREE, FakeClock, FakeDisplays, M  # noqa: E402

H = theme.BAR_HEIGHT
NOW = datetime(2026, 11, 24, 14, 32, 10)


def pump(app, n=10):
    for _ in range(n):
        app.root.update()


# --------------------------------------------------------------------------- pure: config, text, timer
class TestInfoclock(unittest.TestCase):
    def test_defaults_bar_is_off(self):
        d = infoclock.sanitize(None)
        self.assertEqual(d, {"enabled": False, "info": {"enabled": True, "time_format": "24h", "show_date": True},
                             "tasks": {"enabled": True, "show_titles": True}, "colors": {},
                             "search": {"enabled": True, "hotkey": "off", "store_apps": True, "windows_row": False},
                             "start": {"enabled": True}})
        self.assertEqual(infoclock.sanitize("junk"), d)
        self.assertEqual(infoclock.sanitize({"info": 5}), d)

    def test_wrong_types_fall_back_unknown_keys_stay(self):
        d = infoclock.sanitize({"enabled": "yes", "extra": 1, "info": {"enabled": 0, "time_format": "13h",
                                                                         "show_date": None, "later": [1]}})
        self.assertEqual(d["enabled"], False)
        self.assertEqual(d["info"], {"enabled": True, "time_format": "24h", "show_date": True, "later": [1]})
        self.assertEqual(d["extra"], 1)
        self.assertEqual(infoclock.sanitize({"enabled": True, "info": {"time_format": "12h", "show_date": False}}),
                         {"enabled": True, "info": {"enabled": True, "time_format": "12h", "show_date": False},
                          "tasks": {"enabled": True, "show_titles": True}, "colors": {},
                          "search": {"enabled": True, "hotkey": "off", "store_apps": True, "windows_row": False},
                          "start": {"enabled": True}})

    def test_no_reserved_key_is_written(self):
        self.assertNotIn("reserved", infoclock.sanitize({}))

    def test_text(self):
        self.assertEqual(infoclock.format_info(datetime(2026, 11, 24, 14, 32)), "Tuesday 24 November · 14:32")
        self.assertEqual(infoclock.format_info(datetime(2026, 11, 24, 14, 32), "24h", False), "14:32")
        self.assertEqual(infoclock.format_info(datetime(2026, 11, 24, 14, 32), "12h"), "Tuesday 24 November · 2:32 PM")
        self.assertEqual(infoclock.format_info(datetime(2026, 11, 24, 0, 5)), "Tuesday 24 November · 00:05")
        self.assertEqual(infoclock.format_info(datetime(2026, 11, 24, 0, 0), "12h", False), "12 AM")
        self.assertEqual(infoclock.format_info(datetime(2028, 2, 29, 23, 59)), "Tuesday 29 February · 23:59")
        self.assertEqual(infoclock.format_info(datetime(2026, 12, 31, 23, 59)), "Thursday 31 December · 23:59")
        self.assertEqual(infoclock.format_info(datetime(2027, 1, 1, 0, 0)), "Friday 1 January · 00:00")   # midnight

    def test_no_seconds_in_the_text(self):
        self.assertEqual(infoclock.format_info(datetime(2026, 11, 24, 14, 32, 59)),
                         infoclock.format_info(datetime(2026, 11, 24, 14, 32, 0)))

    def test_next_delay_is_just_after_the_minute_boundary(self):
        self.assertEqual(infoclock.next_delay_ms(datetime(2026, 11, 24, 14, 32, 30, 500000)), 29530)
        self.assertEqual(infoclock.next_delay_ms(datetime(2026, 11, 24, 14, 32, 0, 0)), 60030)     # never 0
        self.assertEqual(infoclock.next_delay_ms(datetime(2026, 11, 24, 14, 32, 59, 999999)), 31)
        for s in range(60):
            for us in (0, 1, 499999, 999999):
                d = infoclock.next_delay_ms(datetime(2026, 11, 24, 14, 32, s, us))
                self.assertTrue(30 < d <= 60030, (s, us, d))


class TestBarRect(unittest.TestCase):
    def test_top_edge_of_the_primary_monitor_full_width(self):
        self.assertEqual(appbar.bar_rect(THREE, H), (0, 0, 1920, H))
        self.assertEqual(appbar.bar_rect(ONE, 40), (0, 0, 1920, 40))

    def test_primary_not_at_the_origin_and_negative_coordinates(self):
        self.assertEqual(appbar.bar_rect([M((100, 50, 2020, 1130), primary=True)], H), (100, 50, 2020, 50 + H))
        left_primary = [M((-1920, 0, 0, 1080), primary=True), M((0, 0, 1920, 1080))]
        self.assertEqual(appbar.bar_rect(left_primary, H), (-1920, 0, 0, H))

    def test_monitor_rect_not_work_area(self):
        m = M((0, 0, 1920, 1080), (0, 40, 1920, 1032), True)          # a taskbar already sits on top: work.top is 40
        self.assertEqual(appbar.bar_rect([m], H), (0, 0, 1920, H))


# --------------------------------------------------------------------------- fakes
class FakeAppBar:
    """What Windows does, made up: records every call into `events`; SETPOS moves the primary monitor's WORK area
    (in the FakeDisplays), REMOVE gives it back. `shift` makes QUERYPOS push the strip down (another appbar above)."""

    def __init__(self, disp=None, events=None, accept=True):
        self.disp, self.events, self.accept = disp, events if events is not None else [], accept
        self.shift, self.fail_remove = 0, False
        self.calls = []
        self._original = list(disp.system) if disp else None

    def _log(self, *c):
        self.calls.append(c)
        self.events.append(c[0])

    def new(self, hwnd, callback):
        self._log("NEW", hwnd, callback)
        return self.accept

    def query_pos(self, hwnd, rect):
        self._log("QUERYPOS", tuple(rect))
        return (rect[0], rect[1] + self.shift, rect[2], rect[3] + self.shift)

    def set_pos(self, hwnd, rect):
        self._log("SETPOS", tuple(rect))
        if self.disp:
            self.disp.set([displays.monitor(m.rect, (m.work[0], rect[3], m.work[2], m.work[3]), True) if m.primary else m
                           for m in self._original])
        return tuple(rect)

    def remove(self, hwnd):
        self._log("REMOVE")
        if self.fail_remove:
            raise OSError("remove failed")
        if self.disp:
            self.disp.set(self._original)

    def names(self):
        return [c[0] for c in self.calls]


class FakeShell:
    def __init__(self, put):
        self.put, self.hwnd, self.callback, self.closed = put, 777, 0x9001, 0
        self.hooks, self.acks = [], 0
        self.hotkeys, self.hotkey_ok = [], True       # step 4: every set_hotkey(mods, vk) call; False = Windows refuses

    def close(self):
        self.closed += 1

    def set_hotkey(self, mods, vk):
        self.hotkeys.append((mods, vk))
        return True if not mods else self.hotkey_ok

    def set_tasks_hooks(self, on):
        self.hooks.append(bool(on))
        return True

    def ack_tasks(self):
        self.acks += 1


class FakeWindow:
    def __init__(self, root, on_settings, popup, tag=""):
        self.tag, self.shows, self.text, self.destroyed = tag, [], "", 0
        self.view = None
        self.search_on = self.search_active = self.start_on = False

    def show(self, rect):
        self.shows.append(tuple(rect))

    def set_text(self, text):
        self.text = text

    def set_tasks(self, view):
        self.view = view

    def set_search(self, on):
        self.search_on = bool(on)

    def set_search_active(self, on):
        self.search_active = bool(on)

    def set_start(self, on):
        self.start_on = bool(on)

    def set_look(self, colors, show_titles):
        self.look = (dict(colors), show_titles)

    def destroy(self):
        self.destroyed += 1


class FakeIcons:
    def get_hidden(self):
        return False

    def set_hidden(self, hide):
        return True


# --------------------------------------------------------------------------- AppBarSession (no tkinter)
class TestSession(unittest.TestCase):
    def make(self, layout=THREE, **kw):
        self.disp = FakeDisplays(layout)
        self.be = FakeAppBar(self.disp, **kw)
        self.logs = []
        self.s = appbar.AppBarSession(self.be, 777, 0x9001, H, self.disp.probe, lambda *a: self.logs.append(a))
        return self.s

    def test_register_order_new_querypos_setpos(self):
        s = self.make()
        self.assertEqual(s.register(), (0, 0, 1920, H))
        self.assertEqual(self.be.names(), ["NEW", "QUERYPOS", "SETPOS"])
        self.assertEqual(self.be.calls[0][1:], (777, 0x9001))
        self.assertEqual(self.be.calls[2][1], (0, 0, 1920, H))

    def test_system_moves_the_strip_height_is_kept(self):
        s = self.make()
        self.be.shift = 40                                            # another appbar sits above ours
        self.assertEqual(s.register(), (0, 40, 1920, 40 + H))
        self.assertEqual(self.be.calls[-1], ("SETPOS", (0, 40, 1920, 40 + H)))

    def test_new_refused_leaves_nothing(self):
        s = self.make(accept=False)
        self.assertIsNone(s.register())
        self.assertFalse(s.registered)
        s.unregister()
        self.assertEqual(self.be.names(), ["NEW"])                    # no REMOVE for something never registered

    def test_exception_in_a_call_is_contained(self):
        s = self.make()
        self.be.query_pos = mock.Mock(side_effect=OSError("boom"))
        self.assertIsNone(s.register())
        self.assertFalse(s.registered)
        self.assertEqual(self.be.names(), ["NEW", "REMOVE"])          # it had been registered: it is taken back

    def test_reposition_only_sets_when_something_changed(self):
        s = self.make()
        s.register()
        del self.be.calls[:]
        self.assertIsNone(s.reposition())                             # our own SETPOS makes Windows say POSCHANGED
        self.assertEqual(self.be.names(), ["QUERYPOS"])               # ...so no SETPOS: no chasing its own tail
        self.be.shift = 40
        self.assertEqual(s.reposition(), (0, 40, 1920, 40 + H))
        self.assertEqual(self.be.names(), ["QUERYPOS", "QUERYPOS", "SETPOS"])

    def test_reposition_after_the_primary_monitor_changed(self):
        s = self.make(THREE)
        s.register()
        self.disp.set([M((0, 0, 2560, 1440), primary=True)])
        del self.be.calls[:]
        self.assertEqual(s.reposition(), (0, 0, 2560, H))
        self.assertEqual(self.be.names(), ["QUERYPOS", "SETPOS"])

    def test_reposition_when_not_registered_does_nothing(self):
        s = self.make()
        self.assertIsNone(s.reposition())
        self.assertEqual(self.be.calls, [])

    def test_reregister_after_explorer_restart(self):
        s = self.make()
        s.register()
        del self.be.calls[:]
        self.assertEqual(s.reregister(), (0, 0, 1920, H))
        self.assertEqual(self.be.names(), ["NEW", "QUERYPOS", "SETPOS"])

    def test_remove_once(self):
        s = self.make()
        s.register()
        s.unregister()
        s.unregister()
        self.assertEqual(self.be.names().count("REMOVE"), 1)
        self.assertFalse(s.registered)

    def test_null_backend_reserves_nothing(self):
        n = appbar.NullAppBar()
        s = appbar.AppBarSession(n, 1, 2, H, lambda: THREE)
        self.assertEqual(s.register(), (0, 0, 1920, H))
        s.unregister()


# --------------------------------------------------------------------------- the real App on top of the fakes
class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mpanels_t120s1_")
        self.desk, self.pub, self.data = (os.path.join(self.tmp, n) for n in ("Desktop", "Public", "veri"))
        os.makedirs(self.desk)
        os.makedirs(self.pub)
        for p in (mock.patch("calendar_panel.model.CalendarModel.refresh", lambda *a, **k: None),
                  mock.patch.object(winutil, "lbutton_down", return_value=True),
                  mock.patch.object(winutil, "take_foreground", side_effect=self._take_fg),
                  mock.patch.object(winutil, "post_null", side_effect=lambda w: self.events.append("WM_NULL"))):
            p.start()
            self.addCleanup(p.stop)
        self.apps, self.windows, self.shells, self.events = [], [], [], []
        self.real_sends = []                                  # safety net (step 5): a REAL SendInput must never happen in a test
        p = mock.patch.object(search, "_real_send", side_effect=lambda ev: self.real_sends.append(list(ev)) or len(ev))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(lambda: self.assertEqual(self.real_sends, []))
        self.now = [NOW]
        self.addCleanup(self.close_all)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _take_fg(self, window):
        """Never touch the real foreground in tests: only record that the bar asked for it."""
        self.events.append("TAKE_FG")
        return True

    def close_all(self):
        for a in self.apps:
            a.quit()

    def write_cfg(self, data):
        os.makedirs(self.data, exist_ok=True)
        with open(os.path.join(self.data, "config.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def cfg_file(self):
        with open(os.path.join(self.data, "config.json"), encoding="utf-8") as f:
            return json.load(f)

    def make_shell(self, put):
        sh = FakeShell(put)
        self.shells.append(sh)
        return sh

    def make_window(self, *a, **k):
        w = FakeWindow(*a, **k)
        self.windows.append(w)
        return w

    def open(self, layout=THREE, bar=None, test_mode=False, window=True):
        if bar is not None:
            self.write_cfg({"bar": bar})
        self.disp, self.clock = FakeDisplays(layout), FakeClock()
        self.be = FakeAppBar(self.disp, self.events)
        app = mpanels.App(fileops.Ctx(self.desk, self.pub), self.data, test_mode=test_mode, use_tray=False,
                          icon_backend=FakeIcons(), instance_name=None, displays_provider=self.disp, clock=self.clock,
                          appbar_backend=self.be, bar_shell=self.make_shell,
                          bar_window=self.make_window if window else None, wall_clock=lambda: self.now[0],
                          tasks_actions=None if getattr(self, "default_actions", False)
                          else (getattr(self, "actions", None) or tasks.FakeActions()),
                          tasks_source=None if getattr(self, "default_source", False)
                          else (getattr(self, "src", None) or tasks.FakeSource()),
                          search_source=getattr(self, "search_src", None) or search.FakeSources(),
                          search_actions=getattr(self, "search_acts", None) or search.FakeSearchActions(),
                          search_spawn=getattr(self, "search_spawn", None) or (lambda fn: fn()),
                          start_actions=getattr(self, "start_acts", None) or startmenu.FakeStartActions())
        self.apps.append(app)
        self.app = app
        pump(app)
        return app

    def send(self, *payload):
        self.app.q.put(("bar", payload))
        self.app._poll()


ON = {"enabled": True, "info": {"enabled": True, "time_format": "24h", "show_date": True}}
INFO_ONLY = dict(ON, tasks={"enabled": False})          # the Info tests look at the canvas: no Tasks buttons in it
TEXT = "Tuesday 24 November · 14:32"


class TestConfig(Base):
    def test_default_off_nothing_exists(self):
        app = self.open()
        self.assertEqual(app.cfg["bar"], infoclock.defaults())
        self.assertIsNone(app.bar)
        self.assertEqual((self.be.calls, self.shells, self.windows), ([], [], []))

    def test_old_config_without_bar_gets_the_default_at_the_next_normal_save(self):
        self.write_cfg({"general": {"autostart": True, "lock_panels": True}, "panels": {}})
        app = self.open()
        self.assertEqual(app.cfg["bar"], infoclock.defaults())
        self.assertTrue(app.locked)                                   # the rest of the old file is untouched
        app.save()
        self.assertEqual(self.cfg_file()["bar"], {k: v for k, v in infoclock.defaults().items() if k not in ("search", "start")})
        self.assertNotIn("search", self.cfg_file()["bar"])            # step 4: bar.search is written only when it differs
        self.assertNotIn("reserved", self.cfg_file()["bar"])

    def test_broken_bar_config_falls_back(self):
        app = self.open(bar="junk")
        self.assertEqual(app.cfg["bar"], infoclock.defaults())
        self.assertIsNone(app.bar)

    def test_off_means_no_hook_no_timer_no_thread_even_after_on_and_off(self):
        """Looks only at what the bar itself owns (its icon-worker thread by reference, its window hooks, its Tk timers):
        the process-wide thread count depends on threads other tests left behind, so it is not used."""
        app = self.open()
        timers = len(app.root.tk.call("after", "info"))
        self.assertTrue(app.apply_bar(True, ON["info"]))
        self.assertIsNotNone(app.bar)
        worker = app.bar.tasks.loader._thread
        self.assertIsNotNone(worker)
        self.assertTrue(worker.is_alive())                                    # the test really sees a thread to be stopped
        self.assertEqual(self.shells[0].hooks, [True])
        self.assertTrue(app.apply_bar(False, ON["info"]))
        pump(app)
        self.assertIsNone(app.bar)
        self.assertFalse(worker.is_alive())                                   # the icon worker ended with the section
        self.assertEqual(len(app.root.tk.call("after", "info")), timers)      # no timer left
        self.assertEqual(self.shells[0].closed, 1)                            # shell.close() removes the hooks (and ends its thread)
        self.assertEqual(self.windows[0].destroyed, 1)

    def test_enabled_in_file_starts_with_the_app(self):
        app = self.open(bar=ON)
        self.assertEqual(self.be.names(), ["NEW", "QUERYPOS", "SETPOS"])
        self.assertEqual(self.windows[0].shows, [(0, 0, 1920, H)])
        self.assertEqual(self.windows[0].text, TEXT)
        self.assertIsNotNone(app.bar)

    def test_start_failure_keeps_the_file_setting_and_shows_no_bar(self):
        self.write_cfg({"bar": ON})
        self.disp, self.clock = FakeDisplays(THREE), FakeClock()
        be = FakeAppBar(self.disp, accept=False)
        app = mpanels.App(fileops.Ctx(self.desk, self.pub), self.data, test_mode=False, use_tray=False,
                          icon_backend=FakeIcons(), instance_name=None, displays_provider=self.disp, clock=self.clock,
                          appbar_backend=be, bar_shell=self.make_shell, bar_window=self.make_window)
        self.apps.append(app)
        self.assertIsNone(app.bar)
        self.assertEqual(self.windows, [])
        self.assertTrue(app.cfg["bar"]["enabled"])
        self.assertEqual(self.shells[0].closed, 1)


class TestMessages(Base):
    def test_poschanged_moves_the_strip_again(self):
        self.open(bar=ON)
        del self.be.calls[:]
        self.be.shift = 40
        self.send("abn", appbar.ABN_POSCHANGED, 0)
        self.assertEqual(self.be.names(), ["QUERYPOS", "SETPOS"])
        self.assertEqual(self.windows[0].shows[-1], (0, 40, 1920, 40 + H))

    def test_poschanged_without_a_change_does_not_setpos(self):
        self.open(bar=ON)
        del self.be.calls[:]
        self.send("abn", appbar.ABN_POSCHANGED, 0)
        self.assertEqual(self.be.names(), ["QUERYPOS"])

    def test_taskbar_created_registers_again(self):
        self.open(bar=ON)
        del self.be.calls[:]
        self.send("tbc")
        self.assertEqual(self.be.names(), ["NEW", "QUERYPOS", "SETPOS"])
        self.assertEqual(self.windows[0].shows[-1], (0, 0, 1920, H))

    def test_fullscreen_is_only_logged(self):
        self.open(bar=ON)
        del self.be.calls[:]
        with self.assertLogs("mpanels", "INFO") as cm:
            self.send("abn", appbar.ABN_FULLSCREENAPP, 1)
            self.send("abn", appbar.ABN_FULLSCREENAPP, 0)
        self.assertEqual(self.be.calls, [])
        self.assertTrue(any("full-screen app opened" in l for l in cm.output))
        self.assertTrue(any("full-screen app closed" in l for l in cm.output))

    def test_messages_while_there_is_no_bar_are_ignored(self):
        self.open()
        for payload in (("abn", 1, 0), ("tbc",), ("time",), ("abn", 2, 1)):
            self.send(*payload)
        self.assertEqual(self.be.calls, [])

    def test_a_broken_message_does_not_stop_the_queue(self):
        app = self.open(bar=ON)
        with mock.patch.object(app.bar, "handle", side_effect=RuntimeError("x")), self.assertLogs("mpanels", "ERROR"):
            self.send("tbc")
        self.send("time")                                             # the next message still arrives


class TestClock(Base):
    def after_calls(self, app):
        got, orig = [], app.root.after
        app.root.after = lambda ms, fn=None, *a: (got.append(ms), orig(ms, fn, *a))[1]
        self.addCleanup(lambda: setattr(app.root, "after", orig))
        return got

    def test_minute_change_redraws_and_aims_at_the_next_minute(self):
        app = self.open(bar=ON)
        got = self.after_calls(app)
        self.now[0] = datetime(2026, 11, 24, 14, 33, 0, 30000)
        app.bar._on_minute()
        self.assertEqual(self.windows[0].text, "Tuesday 24 November · 14:33")
        self.assertEqual(got, [60000])                                # 60000 - 30 ms in + 30 ms pad

    def test_midnight_changes_the_date(self):
        app = self.open(bar=ON)
        self.now[0] = datetime(2026, 11, 25, 0, 0, 0, 30000)
        app.bar._on_minute()
        self.assertEqual(self.windows[0].text, "Wednesday 25 November · 00:00")

    def test_two_second_safety_net_fixes_a_missed_minute(self):
        app = self.open(bar=ON)
        self.now[0] = datetime(2026, 11, 24, 14, 40, 5)               # the minute timer never fired (sleep, stall)
        app._tick()
        self.assertEqual(self.windows[0].text, "Tuesday 24 November · 14:40")

    def test_clock_going_back_is_followed(self):
        app = self.open(bar=ON)
        self.now[0] = datetime(2026, 11, 24, 13, 32, 0)               # DST end / manual change
        app._tick()
        self.assertEqual(self.windows[0].text, "Tuesday 24 November · 13:32")

    def test_time_message_realigns_with_one_pending_timer(self):
        app = self.open(bar=ON)
        old = app.bar._job
        self.assertIn(old, app.root.tk.call("after", "info"))
        self.now[0] = datetime(2026, 11, 24, 14, 33, 5)
        self.send("time")
        self.assertEqual(self.windows[0].text, "Tuesday 24 November · 14:33")
        pending = app.root.tk.call("after", "info")
        self.assertNotIn(old, pending)                                # the old timer was cancelled...
        self.assertIn(app.bar._job, pending)                          # ...and exactly one new one is waiting

    def test_nothing_redrawn_when_the_text_is_the_same(self):
        app = self.open(bar=ON)
        with mock.patch.object(app.bar, "realign") as r:
            app._tick()
        r.assert_not_called()

    def test_timer_is_cancelled_when_the_bar_goes(self):
        app = self.open(bar=ON)
        n = len(app.root.tk.call("after", "info"))
        app.apply_bar(False, ON["info"])
        self.assertEqual(len(app.root.tk.call("after", "info")), n - 1)

    def test_12h_and_no_date_from_config(self):
        self.open(bar={"enabled": True, "info": {"time_format": "12h", "show_date": False}})
        self.assertEqual(self.windows[0].text, "2:32 PM")

    def test_info_off_shows_an_empty_strip(self):
        self.open(bar={"enabled": True, "info": {"enabled": False}})
        self.assertEqual(self.windows[0].text, "")


class TestQuit(Base):
    def watch_destroy(self, app):
        orig = app.root.destroy
        app.root.destroy = lambda: (self.events.append("destroy"), orig())[1]

    def test_remove_comes_before_root_destroy(self):
        app = self.open(bar=ON)
        self.watch_destroy(app)
        app.quit()
        self.assertEqual(self.events[-2:], ["REMOVE", "destroy"])
        self.assertEqual(self.events.count("REMOVE"), 1)

    def test_remove_failure_does_not_stop_quit(self):
        app = self.open(bar=ON)
        self.watch_destroy(app)
        self.be.fail_remove = True
        app.quit()
        self.assertEqual(self.events[-1], "destroy")
        self.assertEqual(self.shells[0].closed, 1)

    def test_a_failing_bar_stop_does_not_stop_quit(self):
        app = self.open(bar=ON)
        self.watch_destroy(app)
        self.shells[0].close = mock.Mock(side_effect=RuntimeError("x"))
        with self.assertLogs("mpanels", "ERROR"):
            app.quit()
        self.assertEqual(self.events[-1], "destroy")

    def test_quit_without_a_bar_makes_no_appbar_call(self):
        app = self.open()
        app.quit()
        self.assertEqual(self.be.calls, [])

    def test_stop_twice_is_one_remove(self):
        app = self.open(bar=ON)
        bar = app.bar
        bar.stop()
        bar.stop()
        self.assertEqual(self.events.count("REMOVE"), 1)


class TestTestMode(Base):
    def test_the_real_backend_is_never_built_and_the_injected_one_never_called(self):
        with mock.patch.object(appbar, "Win32AppBar", side_effect=AssertionError("real AppBar in TEST mode")):
            app = self.open(bar=ON, test_mode=True)
            self.assertIsNotNone(app.bar)
            self.assertIsInstance(app.bar.backend, appbar.NullAppBar)
            app.apply_bar(False, ON["info"])
            app.apply_bar(True, ON["info"])
        self.assertEqual(self.be.calls, [])

    def test_bar_is_drawn_but_the_work_area_stays(self):
        before = list(FakeDisplays(THREE).system)
        app = self.open(bar=ON, test_mode=True)
        self.assertEqual(self.windows[0].shows, [(0, 0, 1920, H)])
        self.assertEqual(self.windows[0].tag, ui.TEST_TAG)
        self.assertEqual(self.disp.system, before)
        self.assertEqual(app.monitors(), before)

    def test_settings_show_the_note_and_the_box_works(self):
        app = self.open(test_mode=True)
        app.open_settings()
        w = app.settings_win
        self.addCleanup(lambda: w.win.winfo_exists() and w.win.destroy())
        labels = [c.cget("text") for c in w.tab["bar"].winfo_children() if c.winfo_class() == "TLabel"]
        self.assertIn(ui.BAR_TEST_NOTE, labels)
        w.v_bar.set(True)
        w.apply()
        self.assertIsNotNone(app.bar)
        self.assertEqual(self.be.calls, [])


class TestPanelsFollowTheBar(Base):
    def put(self, name, x, y, w=300, h=200):
        p = self.app.new_panel(name)
        p.cfg.update(x=x, y=y, w=w, h=h, collapsed=False)
        p.expanded = True
        p.apply_size(w, h)
        p._move_to(x, y)
        self.app.set_home(p)
        return p

    def pos(self, p):
        pump(self.app, 3)
        return p.top.winfo_x(), p.top.winfo_y()

    def test_panels_move_at_once_and_homes_stay(self):
        self.open(THREE)
        top = self.put("Top", 100, 0)
        side = self.put("Side", 2100, 0)                              # on the right monitor: not affected
        self.assertEqual(self.pos(top)[1], 0)
        self.app.apply_bar(True, ON["info"])                          # no clock advance: no 2 s / 3 s wait
        self.assertEqual(self.pos(top)[1], H)
        self.assertEqual(self.pos(side)[1], 0)
        self.assertEqual(top.cfg["_home"], (100, 0))
        self.app.save()
        self.assertEqual((self.cfg_file()["panels"]["Top"]["x"], self.cfg_file()["panels"]["Top"]["y"]), (100, 0))
        self.app.apply_bar(False, ON["info"])
        self.assertEqual(self.pos(top), (100, 0))                     # back at once, also without waiting
        self.assertEqual(self.pos(side)[1], 0)

    def test_stack_follows_its_top(self):
        self.open(ONE)
        a = self.put("A", 100, 0)
        b = self.put("B", 100, 200)
        self.app.cfg["stacks"] = [["A", "B"]]
        self.app.relayout_all()
        pump(self.app, 3)
        ay, by = self.pos(a)[1], self.pos(b)[1]
        self.app.apply_bar(True, ON["info"])
        self.assertEqual(self.pos(a)[1], H)
        self.assertEqual(self.pos(b)[1] - self.pos(a)[1], by - ay)    # the member keeps its distance below the top

    def test_poschanged_also_re_evaluates_the_panels_at_once(self):
        self.open(THREE, bar=ON)
        top = self.put("Top", 100, 0)
        self.app.relayout_displays()
        self.assertEqual(self.pos(top)[1], H)
        self.be.shift = 20
        self.send("abn", appbar.ABN_POSCHANGED, 0)
        self.assertEqual(self.pos(top)[1], H + 20)

    def test_explorer_restart_re_evaluates_the_panels(self):
        self.open(THREE, bar=ON)
        top = self.put("Top", 100, 0)
        self.app.relayout_displays()
        self.assertEqual(self.pos(top)[1], H)
        self.disp.set(self.be._original)                              # Explorer restarted: the reservation vanished
        self.app._displays_now()
        self.assertEqual(self.pos(top)[1], 0)
        self.send("tbc")                                              # TaskbarCreated: registered again
        self.assertEqual(self.pos(top)[1], H)


class TestSettings(Base):
    def open_settings(self, **kw):
        app = self.open(**kw)
        app.open_settings()
        w = app.settings_win
        self.addCleanup(lambda: w.win.winfo_exists() and w.win.destroy())
        return app, w

    def test_bar_tab_exists_between_general_and_about(self):
        app, w = self.open_settings()
        tabs = [str(t) for t in w.nb.tabs()]
        self.assertEqual(w.nb.tab(w.tab["bar"], "text"), ui.TAB_BAR)
        self.assertLess(tabs.index(str(w.tab["general"])), tabs.index(str(w.tab["bar"])))
        self.assertLess(tabs.index(str(w.tab["bar"])), tabs.index(str(w.tab["about"])))

    def test_nothing_changes_before_apply(self):
        app, w = self.open_settings()
        w.v_bar.set(True)
        w.v_bar_tf.set(ui.BAR_TIME_12)
        self.assertTrue(w.dirty())
        self.assertIsNone(app.bar)
        self.assertEqual(self.be.calls, [])
        self.assertFalse(app.cfg["bar"]["enabled"])
        w.apply()
        self.assertIsNotNone(app.bar)
        self.assertFalse(w.dirty())
        self.assertEqual(self.windows[0].text, "Tuesday 24 November · 2:32 PM")
        saved = self.cfg_file()["bar"]
        self.assertEqual(saved, {"enabled": True, "info": {"enabled": True, "time_format": "12h", "show_date": True},
                                 "tasks": {"enabled": True, "show_titles": True}, "colors": {}})

    def test_apply_turns_the_bar_off_again(self):
        app, w = self.open_settings(bar=ON)
        w.v_bar.set(False)
        w.apply()
        self.assertIsNone(app.bar)
        self.assertEqual(self.events.count("REMOVE"), 1)
        self.assertFalse(self.cfg_file()["bar"]["enabled"])

    def test_info_boxes_apply_to_the_running_bar(self):
        app, w = self.open_settings(bar=ON)
        w.v_bar_date.set(False)
        w.apply()
        self.assertEqual(self.windows[0].text, "14:32")
        w.v_bar_info.set(False)
        w.apply()
        self.assertEqual(self.windows[0].text, "")

    def test_failed_registration_writes_nothing_and_boxes_return(self):
        app, w = self.open_settings()
        self.be.accept = False
        w.v_bar.set(True)
        w.v_bar_tf.set(ui.BAR_TIME_12)
        self.assertTrue(w.apply())
        self.assertIn(ui.MSG_BAR_FAILED.strip(), w.msg.cget("text"))
        self.assertIsNone(app.bar)
        self.assertFalse(app.cfg["bar"]["enabled"])
        self.assertEqual(app.cfg["bar"]["info"]["time_format"], "24h")
        self.assertFalse(w.v_bar.get())
        if os.path.exists(os.path.join(self.data, "config.json")):
            self.assertFalse(self.cfg_file().get("bar", {}).get("enabled", False))
        self.assertFalse(w.dirty())

    def test_unsaved_bar_change_asks_and_discard_restores(self):
        app, w = self.open_settings(bar=ON)
        w.v_bar_tf.set(ui.BAR_TIME_12)
        with mock.patch.object(w, "ask_unsaved", return_value="discard") as ask:
            self.assertTrue(w._resolve_unsaved())
        ask.assert_called_once()
        self.assertEqual(w.v_bar_tf.get(), ui.BAR_TIME_24)
        self.assertFalse(w.dirty())

    def test_revert_to_defaults_leaves_the_bar_alone(self):
        app, w = self.open_settings(bar=ON)
        w.v_bar_date.set(False)                                       # an unapplied edit stays an unapplied edit
        with mock.patch.object(w, "confirm_overwrite", return_value=True):
            w.reset(False)
        self.assertIsNotNone(app.bar)
        self.assertEqual(app.cfg["bar"], infoclock.sanitize(ON))
        self.assertFalse(w.v_bar_date.get())
        self.assertTrue(w.v_bar.get())

    def test_factory_settings_bring_the_bar_back_to_the_default_off(self):
        app, w = self.open_settings(bar={"enabled": True, "info": {"time_format": "12h", "show_date": False}})
        with mock.patch.object(w, "confirm_overwrite", return_value=True):
            w.reset(True)
        self.assertIn(ui.MSG_BAR_PENDING.strip(), w.msg.cget("text"))
        self.assertIsNotNone(app.bar)                                 # like Snapping: loaded into the boxes, Apply uses it
        w.apply()
        self.assertIsNone(app.bar)
        self.assertEqual(app.cfg["bar"], infoclock.defaults())
        self.assertEqual(self.cfg_file()["bar"], {k: v for k, v in infoclock.defaults().items() if k not in ("search", "start")})   # step 4: search only when it differs

    def test_make_default_and_defaults_file_never_hold_the_bar(self):
        app, w = self.open_settings(bar=ON)
        w.make_default()
        path = os.path.join(self.data, "defaults.json")
        with open(path, encoding="utf-8") as f:
            self.assertNotIn("bar", json.load(f))


class TestRealWindow(Base):
    """The real tkinter BarWindow (only the Win32 placement call is replaced: nothing is put on the real screen)."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(winutil, "overlay_show", return_value=True)
        self.placed = p.start()
        self.addCleanup(p.stop)

    def test_window_style_menu_and_text(self):
        app = self.open(bar=INFO_ONLY, window=False)
        win = app.bar.win
        self.assertIsInstance(win, barwin.BarWindow)
        self.placed.assert_called_with(win.top, 0, 0, 1920, H)
        self.assertTrue(winutil.bar_style_ok(win.top))                # tool window, never activated, takes the mouse
        self.assertTrue(win.top.overrideredirect())
        self.assertTrue(win.top.attributes("-topmost"))
        texts = [win.cv.itemcget(i, "text") for i in win.cv.find_all() if win.cv.type(i) == "text"]
        self.assertEqual(texts, [TEXT])
        self.assertEqual(win.cv.cget("bg"), theme.BAR_BG)
        self.assertEqual(win._menu.index("end"), 0)                   # exactly one entry
        self.assertEqual(win._menu.entrycget(0, "label"), ui.BAR_MENU_SETTINGS)

    def test_menu_opens_settings_on_the_bar_tab(self):
        app = self.open(bar=ON, window=False)
        app.bar.win._menu.invoke(0)
        w = app.settings_win
        self.addCleanup(lambda: w.win.winfo_exists() and w.win.destroy())
        self.assertEqual(str(w.nb.select()), str(w.tab["bar"]))

    def test_tray_show_hide_does_not_hide_the_bar(self):
        app = self.open(bar=ON, window=False)
        app.show_all(False)
        self.assertEqual(app.bar.win.top.state(), "normal")
        self.assertTrue(all(p.top.state() == "withdrawn" for p in app.panels.values()))
        app.show_all(True)
        self.assertEqual(app.bar.win.top.state(), "normal")

    def test_test_mode_draws_the_test_tag(self):
        app = self.open(bar=INFO_ONLY, window=False, test_mode=True)
        win = app.bar.win
        texts = sorted(win.cv.itemcget(i, "text") for i in win.cv.find_all() if win.cv.type(i) == "text")
        self.assertEqual(texts, sorted([TEXT, ui.TEST_TAG]))


if __name__ == "__main__":
    unittest.main()
