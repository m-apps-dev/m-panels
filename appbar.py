"""AppBar (v1.2 step 1): reserve a strip along the TOP edge of the primary monitor, so maximized windows stop below it.

Three parts, so everything but the Windows calls can be tested with a made-up backend:
  bar_rect()       pure: the strip's rectangle from the monitor list;
  Win32AppBar      the real backend (SHAppBarMessage through ctypes: pywin32 does not have it);
  NullAppBar       the TEST-mode backend: accepts everything, reserves nothing (the real work area is never touched);
  AppBarSession    the order of the calls: NEW -> QUERYPOS -> SETPOS, re-position, re-register, REMOVE (idempotent).

Measured on this machine (docs/PLAN.md, "Deneme sonuclari"): a hidden pywin32 window is accepted as the owner, the work
area changes at once, and Windows drops the reservation by itself when the process is killed. Calls are made on the
Tk thread; the owner window's messages only arrive in the app queue (shellmsg.py).
"""
import ctypes
from ctypes import wintypes

import displays

ABM_NEW, ABM_REMOVE, ABM_QUERYPOS, ABM_SETPOS = 0, 1, 2, 3
ABE_TOP = 1
# lParam of the owner's callback message (wParam)
ABN_STATECHANGE, ABN_POSCHANGED, ABN_FULLSCREENAPP, ABN_WINDOWARRANGE = 0, 1, 2, 3


def bar_rect(mons, height):
    """(left, top, right, bottom) of the strip: the primary monitor's whole width (rcMonitor, not rcWork), `height` tall."""
    m = displays.primary(mons).rect
    return (int(m[0]), int(m[1]), int(m[2]), int(m[1]) + int(height))


class _APPBARDATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", ctypes.c_void_p), ("uCallbackMessage", wintypes.UINT),
                ("uEdge", wintypes.UINT), ("rc", wintypes.RECT), ("lParam", wintypes.LPARAM)]


class Win32AppBar:
    """The real thing. new/query_pos/set_pos/remove map to ABM_NEW/QUERYPOS/SETPOS/REMOVE."""

    def __init__(self):
        self._fn = ctypes.windll.shell32.SHAppBarMessage
        self._fn.argtypes = [wintypes.DWORD, ctypes.POINTER(_APPBARDATA)]
        self._fn.restype = ctypes.c_size_t

    def _call(self, msg, hwnd, callback=0, rect=None):
        d = _APPBARDATA()
        d.cbSize = ctypes.sizeof(d)
        d.hWnd = hwnd
        d.uCallbackMessage = callback
        d.uEdge = ABE_TOP
        if rect is not None:
            d.rc = wintypes.RECT(*[int(v) for v in rect])
        ret = int(self._fn(msg, ctypes.byref(d)))
        return ret, (d.rc.left, d.rc.top, d.rc.right, d.rc.bottom)

    def new(self, hwnd, callback):
        return bool(self._call(ABM_NEW, hwnd, callback)[0])

    def query_pos(self, hwnd, rect):
        return self._call(ABM_QUERYPOS, hwnd, rect=rect)[1]

    def set_pos(self, hwnd, rect):
        return self._call(ABM_SETPOS, hwnd, rect=rect)[1]

    def remove(self, hwnd):
        self._call(ABM_REMOVE, hwnd)


class NullAppBar:
    """TEST mode: the same calls, no effect on Windows. The bar is drawn where it would be, nothing is reserved."""

    def new(self, hwnd, callback):
        return True

    def query_pos(self, hwnd, rect):
        return tuple(rect)

    def set_pos(self, hwnd, rect):
        return tuple(rect)

    def remove(self, hwnd):
        pass


class AppBarSession:
    """One appbar. `monitors()` must return the monitors as they are NOW (a fresh probe), not the committed layout.
    Every Windows call is guarded: a failure answers None/False, it never raises."""

    def __init__(self, backend, owner, callback, height, monitors, log=None):
        self.backend, self.owner, self.callback, self.height = backend, owner, callback, int(height)
        self._monitors, self._log = monitors, log or (lambda *a: None)
        self.registered = False
        self.rect = None

    def _desired(self):
        return bar_rect(self._monitors(), self.height)

    def _fit(self, rc):
        """The system may move the strip (another appbar above it); the height stays ours."""
        return (int(rc[0]), int(rc[1]), int(rc[2]), int(rc[1]) + self.height)

    def register(self):
        """NEW -> QUERYPOS -> SETPOS. Returns the strip's rectangle, or None when Windows refused (nothing stays registered)."""
        try:
            if not self.backend.new(self.owner, self.callback):
                self._log("appbar: ABM_NEW refused")
                return None
            self.registered = True
            q = self._fit(self.backend.query_pos(self.owner, self._desired()))
            self.rect = self._fit(self.backend.set_pos(self.owner, q))
            self._log("appbar: registered rect=%s", self.rect)
            return self.rect
        except Exception as e:                                          # noqa: BLE001
            self._log("appbar: register failed: %r", e)
            self.unregister()
            return None

    def reposition(self):
        """ABN_POSCHANGED: ask where the strip belongs now; SETPOS only if that is not where it already is (our own
        SETPOS makes Windows send POSCHANGED again: answering every one with a SETPOS could chase its own tail).
        Returns the new rectangle, or None when nothing changed."""
        if not self.registered:
            return None
        try:
            q = self._fit(self.backend.query_pos(self.owner, self._desired()))
            if q == self.rect:
                return None
            self.rect = self._fit(self.backend.set_pos(self.owner, q))
            self._log("appbar: moved rect=%s", self.rect)
            return self.rect
        except Exception as e:                                          # noqa: BLE001
            self._log("appbar: reposition failed: %r", e)
            return None

    def reregister(self):
        """TaskbarCreated: Explorer restarted and its appbar list is empty; register again from scratch."""
        self.registered = False
        self.rect = None
        return self.register()

    def unregister(self):
        """ABM_REMOVE, once; calling it again (or when never registered) does nothing."""
        if not self.registered:
            return
        self.registered = False
        self.rect = None
        try:
            self.backend.remove(self.owner)
            self._log("appbar: removed")
        except Exception as e:                                          # noqa: BLE001
            self._log("appbar: remove failed: %r", e)
