"""Monitors (v1.1 step 7c). ONE place that knows the screens: the Windows call is `snapshot()`, everything else is pure
geometry on a list of `Monitor`s, so it is tested with made-up layouts (1, 2, 3 monitors, a monitor that goes and comes
back, misaligned monitors with dead areas).

Coordinates are the process' virtual-screen coordinates (the same space the windows are placed in; the process is
system-DPI aware, so nothing here depends on a DPI value). A rectangle is (left, top, right, bottom); a panel head is
(x, y, w, head_h).

HOME vs SHOWN: a panel's HOME is where the user put it (saved in config.json). The SHOWN place is what `place()` makes
of the home for the monitors that exist NOW. It is a pure function, so when a monitor comes back the panel is simply
shown at its home again; nothing has to be remembered about the time the monitor was away."""
import collections

MIN_VISIBLE = 80            # px of a panel's head that must stay on a real monitor

Monitor = collections.namedtuple("Monitor", "rect work primary")


def monitor(rect, work=None, primary=False):
    """A Monitor from plain tuples (work area defaults to the whole monitor)."""
    rect = tuple(int(v) for v in rect)
    return Monitor(rect, tuple(int(v) for v in (work or rect)), bool(primary))


def snapshot():
    """The monitors right now (EnumDisplayMonitors + GetMonitorInfo): [Monitor], primary first, then left to right.
    Raises when Windows cannot say (a failed call must NOT look like 'monitors gone'); see `Displays`."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)]
    found = []
    proc_t = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(wintypes.RECT),
                                ctypes.c_void_p)

    def proc(h, dc, r, lp):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(ctypes.c_void_p(h), ctypes.byref(mi)):
            m, w = mi.rcMonitor, mi.rcWork
            found.append(monitor((m.left, m.top, m.right, m.bottom), (w.left, w.top, w.right, w.bottom),
                                 bool(mi.dwFlags & 1)))
        return 1
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.EnumDisplayMonitors.argtypes = [ctypes.c_void_p, ctypes.c_void_p, proc_t, ctypes.c_void_p]
    user32.EnumDisplayMonitors.restype = wintypes.BOOL
    if not user32.EnumDisplayMonitors(None, None, proc_t(proc), None):   # synchronous: the callback lives during the call
        raise OSError("EnumDisplayMonitors failed")
    if not found:
        raise OSError("no monitors reported")
    return _ordered(found)


def _ordered(mons):
    return sorted(mons, key=lambda m: (not m.primary, m.rect[0], m.rect[1]))


class Displays:
    """The app's view of the screens, in two steps so a short-lived change (a monitor that sleeps and wakes) cannot
    leak into placement before it has settled:
      monitors() = the COMMITTED layout (what clamp, snapping and placement use; cheap, called on every drag motion);
      probe()    = what the system says now, WITHOUT committing it (None when the system cannot say: keep the old);
      commit(m)  = make a probed layout the committed one (the app does this only when it re-places the panels).
    Tests give a `source` returning a made-up layout."""

    def __init__(self, source=None):
        self._source = source or snapshot
        try:
            self._mons = list(self._source())
        except Exception:                                   # noqa: BLE001  (start-up: one monitor of the primary size)
            self._mons = [monitor((0, 0, 1920, 1080), primary=True)]

    def monitors(self):
        return self._mons

    def probe(self):
        try:
            return list(self._source())
        except Exception:                                   # noqa: BLE001
            return None

    def commit(self, mons):
        self._mons = list(mons)


def signature(mons):
    """Hashable summary of a layout (monitor + work area rectangles + which is primary): what 'changed' means."""
    return tuple(sorted((m.rect, m.work, m.primary) for m in mons))


def virtual_bounds(mons):
    """(x, y, w, h) bounding box of all monitors (what GetSystemMetrics 76-79 report)."""
    l, t = min(m.rect[0] for m in mons), min(m.rect[1] for m in mons)
    r, b = max(m.rect[2] for m in mons), max(m.rect[3] for m in mons)
    return l, t, r - l, b - t


def primary(mons):
    return next((m for m in mons if m.primary), mons[0])


def _inter(a, b):
    """Area of the intersection of two (l, t, r, b) rectangles."""
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def head_rect(x, y, w, head_h):
    return int(x), int(y), int(x) + int(w), int(y) + int(head_h)


def intersects_any(mons, x, y, w, head_h):
    """Does the head touch any real monitor at all?"""
    h = head_rect(x, y, w, head_h)
    return any(_inter(h, m.rect) > 0 for m in mons)


def monitor_for(mons, x, y, w, head_h):
    """The monitor the head belongs to: the one it overlaps most (ties: the first in order); with no overlap, the nearest."""
    h = head_rect(x, y, w, head_h)
    best = max(mons, key=lambda m: _inter(h, m.rect))
    if _inter(h, best.rect) > 0:
        return best
    cx, cy = (h[0] + h[2]) / 2, (h[1] + h[3]) / 2

    def dist(m):
        dx = max(m.rect[0] - cx, 0, cx - m.rect[2])
        dy = max(m.rect[1] - cy, 0, cy - m.rect[3])
        return dx * dx + dy * dy
    return min(mons, key=dist)


def monitor_at(mons, x, y):
    """The monitor containing the point (the nearest one when outside); returns its rectangle (usable as an id)."""
    return monitor_for(mons, x, y, 1, 1).rect


def _clamp_in(m, x, y, w, head_h):
    vis = min(MIN_VISIBLE, int(w))
    l, t, r, b = m.work
    x = min(max(int(x), l - int(w) + vis), r - vis)
    y = min(max(int(y), t), max(t, b - int(head_h)))
    return x, y


def reachable(mons, x, y, w, head_h):
    """Can the user get hold of a panel head here? On some monitor's work area: at least MIN_VISIBLE px (or the whole
    width of a narrow panel) of it, and the whole head vertically. A spot in a dead area (no monitor) is not."""
    vis = min(MIN_VISIBLE, int(w))
    h = head_rect(x, y, w, head_h)
    for m in mons:
        l, t, r, b = m.work
        if min(h[2], r) - max(h[0], l) >= vis and h[1] >= t and h[3] <= b:
            return True
    return False


def clamp_head(mons, x, y, w, head_h):
    """Pull a head onto the monitor it belongs to (its work area; never under the taskbar). A spot that is already
    reachable stays exactly where it is."""
    if reachable(mons, x, y, w, head_h):
        return int(x), int(y)
    return _clamp_in(monitor_for(mons, x, y, w, head_h), x, y, w, head_h)


def monitor_rect_of(mons, x, y, w, head_h):
    """Rectangle of the monitor this head sits on, or None when it is on none (so it is no 'home monitor' to remember)."""
    if not intersects_any(mons, x, y, w, head_h):
        return None
    return monitor_for(mons, x, y, w, head_h).rect


def place(mons, hx, hy, w, head_h, mon=None):
    """THE rule: where a unit (free panel or stack top) with home (hx, hy) is shown now.
    - its head touches a monitor that exists: shown at home (pulled onto that monitor's work area when needed);
    - otherwise (its monitor is gone): it goes to the primary monitor keeping its place relative to the monitor it lived
      on (`mon`, that monitor's rectangle when it was last placed), so everything that lived there keeps its layout.
      Without `mon` it is only pulled onto the nearest monitor.
    The home is never changed by this; with the monitor back the result is the home again."""
    if intersects_any(mons, hx, hy, w, head_h):
        return clamp_head(mons, hx, hy, w, head_h)
    if mon:
        p = primary(mons)
        x, y = p.rect[0] + (int(hx) - mon[0]), p.rect[1] + (int(hy) - mon[1])
        return _clamp_in(p, x, y, w, head_h)
    return clamp_head(mons, hx, hy, w, head_h)
