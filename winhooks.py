"""The Tasks section's ears (v1.2 step 2): the shell hook and five WinEvent hooks. They say only "something may have
changed"; what changed is found by a full comparison (tasks.py).

Both must be installed AND removed by the thread that runs the message loop (shellmsg.MessageWindow's thread): an
out-of-context WinEvent hook delivers through that thread's messages. Every callback is cheap and never raises.

Noise (measured, docs/PLAN.md): of ~240 object events per minute almost all belong to child windows and non-window
objects. The callback drops them first: only idObject == OBJID_WINDOW and idChild == CHILDID_SELF, only top-level
windows, and our own process's events are never delivered (WINEVENT_SKIPOWNPROCESS). The LOCATIONCHANGE event is not
hooked at all (it floods)."""
import ctypes
from ctypes import wintypes as wt

# (min, max): FOREGROUND, MINIMIZESTART..END, OBJECT CREATE..HIDE, NAMECHANGE, CLOAKED..UNCLOAKED
RANGES = ((0x0003, 0x0003), (0x0016, 0x0017), (0x8000, 0x8003), (0x800C, 0x800C), (0x8017, 0x8018))
WINEVENT_OUTOFCONTEXT, WINEVENT_SKIPOWNPROCESS = 0x0000, 0x0002
OBJID_WINDOW, CHILDID_SELF, GA_ROOT = 0, 0, 2
# SHELLHOOK wParam values that can change the list: CREATED, DESTROYED, WINDOWACTIVATED, REDRAW (title/flash), the
# REPLACED pair, RUDEAPPACTIVATED. GETMINRECT's lParam is a pointer, not a window: it is never looked at.
SHELL_DIRTY = frozenset((1, 2, 4, 6, 13, 14, 0x8004))


class Win32Hooks:
    """The real calls, with their types spelled out (a 64-bit handle or pointer must never go through a default
    32-bit `int` argument: that was the OverflowError seen in the listening experiment)."""

    def __init__(self):
        self.proc_t = ctypes.WINFUNCTYPE(None, wt.HANDLE, wt.DWORD, wt.HWND, ctypes.c_long, ctypes.c_long,
                                         wt.DWORD, wt.DWORD)
        u = self._u = ctypes.WinDLL("user32", use_last_error=True)
        u.SetWinEventHook.argtypes = [wt.DWORD, wt.DWORD, wt.HANDLE, self.proc_t, wt.DWORD, wt.DWORD, wt.DWORD]
        u.SetWinEventHook.restype = wt.HANDLE
        u.UnhookWinEvent.argtypes = [wt.HANDLE]
        u.UnhookWinEvent.restype = wt.BOOL
        u.RegisterShellHookWindow.argtypes = [wt.HWND]
        u.RegisterShellHookWindow.restype = wt.BOOL
        u.DeregisterShellHookWindow.argtypes = [wt.HWND]
        u.DeregisterShellHookWindow.restype = wt.BOOL
        u.GetAncestor.argtypes = [wt.HWND, wt.UINT]
        u.GetAncestor.restype = wt.HWND

    def make_proc(self, fn):
        return self.proc_t(fn)

    def set_hook(self, lo, hi, proc):
        return self._u.SetWinEventHook(lo, hi, None, proc, 0, 0, WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS)

    def unhook(self, handle):
        return bool(self._u.UnhookWinEvent(handle))

    def register_shell(self, hwnd):
        return bool(self._u.RegisterShellHookWindow(hwnd))

    def deregister_shell(self, hwnd):
        return bool(self._u.DeregisterShellHookWindow(hwnd))

    def is_top_level(self, hwnd):
        return int(self._u.GetAncestor(hwnd, GA_ROOT) or 0) == int(hwnd or 0)


class Hooks:
    """Installs/removes the shell hook for `hwnd` and the WinEvent hooks. `on_event()` is called (on the hook thread)
    for anything that may change the list. Not thread-safe by itself: only the message-loop thread calls it."""

    def __init__(self, hwnd, on_event, api=None):
        self.hwnd, self._on_event = hwnd, on_event
        self.api = api or Win32Hooks()
        self._handles, self._proc, self.shell_ok = [], None, False

    @property
    def installed(self):
        return bool(self._handles) or self.shell_ok

    def _callback(self, hook, event, hwnd, id_object, id_child, thread, ms):
        try:
            if id_object != OBJID_WINDOW or id_child != CHILDID_SELF or not hwnd:
                return                                          # menus, carets, scroll bars...: not windows
            if event >= 0x8000 and event <= 0x8003 and not self.api.is_top_level(hwnd):
                return                                          # child windows: CREATE/DESTROY/SHOW/HIDE flood
            self._on_event()
        except Exception:                                       # noqa: BLE001  (never raise into the hook)
            pass

    def shell_message(self, wparam):
        """The SHELLHOOK window message. Only wParam is used; lParam (a window or, for GETMINRECT, a pointer) is not."""
        if wparam in SHELL_DIRTY:
            self._on_event()

    def install(self):
        """True when at least the WinEvent hooks are in. Whatever was installed is removed again by remove()."""
        if self.installed:
            return True
        self._proc = self.api.make_proc(self._callback)          # kept alive here while the hooks exist
        for lo, hi in RANGES:
            h = self.api.set_hook(lo, hi, self._proc)
            if h:
                self._handles.append(h)
        self.shell_ok = self.api.register_shell(self.hwnd)
        return bool(self._handles)

    def remove(self):
        """UnhookWinEvent for every hook, DeregisterShellHookWindow. Idempotent."""
        handles, self._handles = self._handles, []
        for h in handles:
            self.api.unhook(h)
        if self.shell_ok:
            self.shell_ok = False
            self.api.deregister_shell(self.hwnd)
        self._proc = None
