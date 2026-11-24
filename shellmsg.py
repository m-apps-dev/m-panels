"""The bar's message window (v1.2 step 1): a HIDDEN top-level pywin32 window (not message-only: broadcasts such as
TaskbarCreated never reach message-only windows) that owns the appbar and receives system messages on its own thread.
The window procedure does one thing: put a tuple on the app queue as ("bar", payload). Tk objects are never touched
here (same rule as the tray, the folder watcher and the single-instance listener). The thread is a daemon thread.

Payloads:  ("abn", wParam, lParam)  the appbar callback (appbar.ABN_*);   ("tbc",)  Explorer restarted (TaskbarCreated);
           ("time",)               the clock may have jumped (time change, resume from sleep, settings change);
           ("tasks",)              (step 2) the window list may have changed (shell hook / WinEvent hooks);
           ("hotkey",)             (step 4) the search shortcut key was pressed (WM_HOTKEY).

Step 2: the same thread also hosts the Tasks hooks (winhooks.py). They are switched on and off with a SendMessage to the
window (so they are installed and removed ON this thread, as Windows requires) and removed for good in close(), which now
WAITS for the thread to finish: after close() returns, no hook and no window exist.
Types: WPARAM/LPARAM reach the window procedure as Python ints of any size (a 64-bit pointer is normal: SHELLHOOK's
GETMINRECT lParam). Nothing here passes them on to a Windows function except DefWindowProc, and the hook code never
looks at lParam."""
import ctypes
import ctypes.wintypes as wt
import itertools
import os
import threading

import win32api
import win32con
import win32gui

import applog
import winhooks

LOG = applog.get_logger()
WM_TIMECHANGE, WM_SETTINGCHANGE, WM_POWERBROADCAST = 0x1E, 0x1A, 0x218
PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC = 0x7, 0x12
WM_APP_TASKS = win32con.WM_APP + 1             # wParam 1: install the Tasks hooks, 0: remove them (sent from the Tk thread)
WM_APP_HOTKEY = win32con.WM_APP + 2            # wParam = modifiers (0: remove the key), lParam = virtual key (sent from the Tk thread)
WM_HOTKEY, MOD_NOREPEAT = 0x312, 0x4000
HOTKEY_ID = 0x4D50                             # the one hotkey id of this window
_counter = itertools.count(1)


class HotkeyApi:
    """RegisterHotKey / UnregisterHotKey for a window. They must be called on the thread that owns the window. Tests give
    a made-up one."""

    def __init__(self):
        self._u = u = ctypes.WinDLL("user32", use_last_error=True)
        u.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
        u.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]

    def register(self, hwnd, hotkey_id, mods, vk):
        """(registered, last error). The key does not repeat while held (MOD_NOREPEAT)."""
        ok = self._u.RegisterHotKey(hwnd, hotkey_id, mods | MOD_NOREPEAT, vk)
        return bool(ok), ctypes.get_last_error()

    def unregister(self, hwnd, hotkey_id):
        return bool(self._u.UnregisterHotKey(hwnd, hotkey_id))


class MessageWindow:
    """Creates the window on its own thread. `hwnd` is None when that failed (the caller then shows no bar).
    `hooks_factory(hwnd, on_event)` makes the Tasks hooks object (tests give a made-up one)."""

    def __init__(self, put, hooks_factory=None, hotkey_api=None):
        self._put = put
        self._hooks_factory = hooks_factory
        self._hotkey_api = hotkey_api
        self._hotkey = None                       # (modifiers, virtual key) registered now
        self.callback = win32gui.RegisterWindowMessage("MPanelsBarCallback")
        self._taskbar_created = win32gui.RegisterWindowMessage("TaskbarCreated")
        self._shellhook = win32gui.RegisterWindowMessage("SHELLHOOK")
        self.hwnd = None
        self._hooks = None
        self._tasks_pending = False
        self._closed = False
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,), daemon=True)
        self._thread.start()
        ready.wait(5)

    # ---- the Tasks hooks
    def _tasks_event(self):
        """Any hook callback. One queue entry per burst: more are put only after the app has taken the last one."""
        if not self._tasks_pending:
            self._tasks_pending = True
            self._put(("bar", ("tasks",)))

    def ack_tasks(self):
        """The app took the ("tasks",) entry and marked the list dirty: the next event may queue a new one."""
        self._tasks_pending = False

    def _switch_hooks(self, hwnd, on):                          # runs on the window's thread
        try:
            if on:
                if self._hooks is None:
                    factory = self._hooks_factory or winhooks.Hooks
                    self._hooks = factory(hwnd, self._tasks_event)
                ok = self._hooks.install()
                if not ok:
                    LOG.warning("tasks: the window hooks could not be installed")
                return 1 if ok else 0
            if self._hooks is not None:
                self._hooks.remove()
            return 1
        except Exception:                                       # noqa: BLE001
            LOG.exception("tasks: switching the hooks failed")
            return 0

    def set_tasks_hooks(self, on):
        """Install (True) or remove (False) the Tasks hooks; returns when it is done. True if they are in."""
        hwnd = self.hwnd
        if not hwnd or self._closed:
            return False
        try:
            return bool(win32gui.SendMessage(hwnd, WM_APP_TASKS, 1 if on else 0, 0))
        except Exception:                                       # noqa: BLE001
            return False

    # ---- the search shortcut key
    def _switch_hotkey(self, hwnd, mods, vk):                   # runs on the window's thread
        """Register (mods != 0) or remove (mods == 0) the key. A key that cannot be registered leaves the old one in force.
        Returns 1 when the wanted state was reached."""
        try:
            api = self._hotkey_api
            if api is None:
                api = self._hotkey_api = HotkeyApi()
            prev = self._hotkey
            if prev is not None:
                api.unregister(hwnd, HOTKEY_ID)
                self._hotkey = None
            if not mods:
                return 1
            ok, err = api.register(hwnd, HOTKEY_ID, mods, vk)
            if ok:
                self._hotkey = (mods, vk)
                return 1
            LOG.warning("search: RegisterHotKey failed (error %s)", err)
            if prev is not None and api.register(hwnd, HOTKEY_ID, prev[0], prev[1])[0]:
                self._hotkey = prev
            return 0
        except Exception:                                       # noqa: BLE001
            LOG.exception("search: switching the shortcut key failed")
            return 0

    def set_hotkey(self, mods, vk):
        """Register the search shortcut key (modifiers, virtual key), or remove it with (0, 0); returns when done. True if
        the wanted state was reached."""
        hwnd = self.hwnd
        if not hwnd or self._closed:
            return not mods
        try:
            return bool(win32gui.SendMessage(hwnd, WM_APP_HOTKEY, int(mods), int(vk)))
        except Exception:                                       # noqa: BLE001
            return False

    @property
    def hotkey_registered(self):
        return self._hotkey is not None

    @property
    def hooks_installed(self):
        return bool(self._hooks is not None and self._hooks.installed)

    # ---- the window procedure
    def _proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == self.callback:
                self._put(("bar", ("abn", wparam, lparam)))
            elif msg == self._shellhook:
                if self._hooks is not None:
                    self._hooks.shell_message(wparam)
            elif msg == WM_APP_TASKS:
                return self._switch_hooks(hwnd, bool(wparam))
            elif msg == WM_APP_HOTKEY:
                return self._switch_hotkey(hwnd, wparam, lparam)
            elif msg == WM_HOTKEY:
                if wparam == HOTKEY_ID:
                    self._put(("bar", ("hotkey",)))
            elif msg == self._taskbar_created:
                self._put(("bar", ("tbc",)))
            elif msg in (WM_TIMECHANGE, WM_SETTINGCHANGE) or (
                    msg == WM_POWERBROADCAST and wparam in (PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC)):
                self._put(("bar", ("time",)))
            elif msg == win32con.WM_DESTROY:
                self._switch_hotkey(hwnd, 0, 0)                 # the key and the hooks go on THIS thread, before the loop ends
                self._switch_hooks(hwnd, False)
                win32gui.PostQuitMessage(0)
        except Exception:                                       # noqa: BLE001  (never raise into Windows)
            pass
        try:
            return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)
        except Exception:                                       # noqa: BLE001
            return 0

    def _run(self, ready):
        try:
            wc = win32gui.WNDCLASS()
            wc.lpszClassName = "MPanelsBarWindow%d_%d" % (os.getpid(), next(_counter))
            wc.hInstance = win32api.GetModuleHandle(None)
            wc.lpfnWndProc = self._proc
            atom = win32gui.RegisterClass(wc)
            self.hwnd = win32gui.CreateWindowEx(0, atom, "", win32con.WS_POPUP, 0, 0, 0, 0, 0, 0, wc.hInstance, None)
        except Exception:                                       # noqa: BLE001
            self.hwnd = None
        ready.set()
        if self.hwnd:
            win32gui.PumpMessages()

    def close(self):
        """Destroy the window (its WM_DESTROY removes the hooks) and WAIT until the thread is done."""
        hwnd, self.hwnd = self.hwnd, None
        self._closed = True
        if hwnd:
            try:
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:                                   # noqa: BLE001
                pass
            if threading.current_thread() is not self._thread:
                self._thread.join(3)
                if self._thread.is_alive():
                    LOG.warning("tasks: the message window did not stop in time")
