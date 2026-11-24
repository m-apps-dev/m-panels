"""The bar's Tasks section (v1.2 step 2): which windows are listed, in what order, how the buttons are laid out, where the
icons come from. Listing only: clicking a button (bring the window forward) is a later step.

Parts, so everything but the Windows calls can be tested with a made-up source:
  listed()        pure: the taskbar-like rule (diagnosis in docs/PLAN.md) plus "not one of our own windows";
  TaskModel       pure: the order (windows present at the first scan: process start time, tie -> one-time z-order;
                  every window seen later is appended at the end), change detection;
  layout(), fit_text()   pure: button widths, "+N" overflow, the "..." cut;
  Win32Source     the real thing (EnumWindows, DWM cloaked, process times; its OWN ctypes copies of the DLLs, so the
                  argument types we set cannot change how other modules call the same functions);
  FakeSource      the TEST-mode list: made up, no Windows call at all;
  IconLoader      one worker thread: WM_GETICON (with a time-out) -> class icon -> exe icon; PIL images only;
  Tasks           the controller on the Tk thread: dirty flag, at most one scan per 100 ms, the 2 s safety comparison,
                  icon cache (PhotoImage objects are made here and nowhere else).

Detection is "events + safety net": the hooks (shellmsg/winhooks) only say "something may have changed" (a dirty flag);
the list itself is always rebuilt by a full comparison, and the 2 s tick runs the same comparison, so a missed event
costs at most 2 s."""
import collections
import ctypes
import os
import queue
import threading
import time
from ctypes import wintypes as wt

import applog
import strings as ui
import theme

LOG = applog.get_logger()

WinInfo = collections.namedtuple("WinInfo", "hwnd title pid cls visible owner ex cloaked iconic shell")
Entry = collections.namedtuple("Entry", "hwnd title minimized path")

WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = 0x80, 0x40000
APP_FRAME_CLASS = "ApplicationFrameWindow"
CORE_WINDOW_CLASS = "Windows.UI.Core.CoreWindow"
SCAN_MIN_S = 0.1               # at most one scan per 100 ms, however many events arrive
ICON_RETRY_S = 2.0             # a window whose icon is not found is tried again after this long
ICON_SIZE = theme.BAR_ICON


# ------------------------------------------------------------------ the rule
def listed(w, own_pid):
    """Would the taskbar list this window? Visible, not the desktop, no owner (unless APPWINDOW), no tool window,
    not cloaked, with a title, and not one of ours (the bar, the panels, Settings)."""
    if not w.visible or w.shell or w.pid == own_pid:
        return False
    if w.owner and not (w.ex & WS_EX_APPWINDOW):
        return False
    if (w.ex & WS_EX_TOOLWINDOW) and not (w.ex & WS_EX_APPWINDOW):
        return False
    if w.cloaked:
        return False
    return bool(w.title)


def safe_log(method, msg, *args):
    """A log line that can never break the caller: a failing log file (PermissionError, a full disk...) is ignored."""
    try:
        getattr(LOG, method)(msg, *args)
    except Exception:                                                        # noqa: BLE001
        pass


def decide(minimized, active, hwnd):
    """What a click on `hwnd`'s button does (like the taskbar): minimized -> "restore" (and bring forward); the window
    that was active when the button was pressed -> "minimize"; any other -> "front"."""
    if minimized:
        return "restore"
    return "minimize" if hwnd == active else "front"


def _now_filetime():
    return int(time.time() * 10_000_000) + 116444736000000000


class TaskModel:
    """The list. `update()` takes ALL top-level windows (z-order, top first) and answers whether anything the bar shows
    changed. A window's place is its key, made ONCE (decision 5A) and kept, so a button never moves; the key is
    forgotten when the window is gone:
      first scan:  (0, process start time, z index)   - the windows that were already open, oldest program first;
      later scans: (scan number, 0, z index)          - a new window goes to the END, whatever its program's age.
    A process that cannot be found (yet) takes "now" as its start time; finding it later changes the icon, never the place."""

    def __init__(self, own_pid, now_filetime=_now_filetime):
        self.own_pid, self._now_ft = own_pid, now_filetime
        self._rec = {}                 # hwnd -> {"key": tuple, "path": str|None, "scan": int, "z": int}
        self._scan = 0
        self.entries = ()
        self.active = 0
        self._sig = None

    def update(self, wins, resolve, active):
        """-> (changed, removed): `removed` = hwnds that no longer exist (their caches may go)."""
        self._scan += 1
        alive = {w.hwnd for w in wins}
        removed = set(self._rec) - alive
        for h in removed:
            del self._rec[h]
        out = []
        for z, w in enumerate(wins):
            if not listed(w, self.own_pid):
                continue
            rec = self._rec.get(w.hwnd)
            if rec is None or rec["path"] is None:       # new, or its process could not be found before: try again
                path, start = resolve(w)
                if rec is None:
                    first = self._scan == 1
                    key = (0, start if (path and start) else self._now_ft(), z) if first else (self._scan, 0, z)
                    rec = self._rec[w.hwnd] = {"key": key, "path": path}
                elif path:
                    rec["path"] = path
            out.append((rec["key"], w.hwnd, w))
        out.sort(key=lambda t: (t[0], t[1]))
        self.entries = tuple(Entry(w.hwnd, w.title, bool(w.iconic), self._rec[w.hwnd]["path"]) for _k, _h, w in out)
        self.active = active if any(e.hwnd == active for e in self.entries) else 0
        sig = (tuple((e.hwnd, e.title, e.minimized) for e in self.entries), self.active)
        changed = sig != self._sig
        self._sig = sig
        return changed, removed


# ------------------------------------------------------------------ layout
def layout(n, avail, min_w=None, max_w=None, gap=None):
    """(k, w, more): `k` buttons of width `w` each, and when `more` > 0 one more "+more" button of the same width.
    All fit -> (n, min(max, share), 0). Otherwise as many minimum-width buttons as fit, the last slot is the "+N"."""
    min_w = theme.BAR_BTN_MIN_W if min_w is None else min_w
    max_w = theme.BAR_BTN_MAX_W if max_w is None else max_w
    gap = theme.BAR_BTN_GAP if gap is None else gap
    if n <= 0 or avail < min_w:
        return 0, 0, (n if n > 0 else 0)
    if n * min_w + (n - 1) * gap <= avail:
        return n, min(max_w, (avail - (n - 1) * gap) // n), 0
    slots = (avail + gap) // (min_w + gap)
    k = slots - 1
    return k, min(max_w, (avail - k * gap) // (k + 1)), n - k


def layout_icons(n, avail, measure, more_label):
    """Titles off: (k, w, more, more_w). Every button is BAR_ICON_ONLY_W wide; the "+N" slot is as wide as its text needs
    (never narrower). `measure(str)` -> pixels, `more_label(n)` -> "+N"."""
    w = theme.BAR_ICON_ONLY_W
    k, bw, more = layout(n, avail, min_w=w, max_w=w)
    if not more:
        return k, bw, 0, bw
    for _ in range(3):                                              # the label's width depends on N, N on the room
        need = max(w, measure(more_label(more)) + 2 * theme.BAR_BTN_PAD)
        k2, _bw, more2 = layout(n, avail - (need - w), min_w=w, max_w=w)
        if more2 == more:
            return k2, w, more, need
        more = more2
        if not more:
            return k2, w, 0, w
    return k2, w, more2, max(w, measure(more_label(more2)) + 2 * theme.BAR_BTN_PAD)


def fit_text(text, max_px, measure):
    """`text` if it fits in `max_px`, else its longest prefix + "…" that does (measure(str) -> pixels)."""
    if max_px <= 0:
        return ""
    if measure(text) <= max_px:
        return text
    cut = ui.BAR_ELLIPSIS
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if measure(text[:mid].rstrip() + cut) <= max_px:
            lo = mid
        else:
            hi = mid - 1
    s = text[:lo].rstrip() + cut
    return s if measure(s) <= max_px else ""


def text_room(w):
    """Pixels left for the title inside a button of width `w` (icon and paddings taken off)."""
    return w - 2 * theme.BAR_BTN_PAD - theme.BAR_ICON - theme.BAR_ICON_GAP


# ------------------------------------------------------------------ the real source
class Win32Source:
    def __init__(self):
        self._u = u = ctypes.WinDLL("user32", use_last_error=True)
        self._k = k = ctypes.WinDLL("kernel32", use_last_error=True)
        self._d = d = ctypes.WinDLL("dwmapi")
        self._enum_t = ctypes.WINFUNCTYPE(ctypes.c_int, wt.HWND, wt.LPARAM)
        u.EnumWindows.argtypes = [self._enum_t, wt.LPARAM]
        u.EnumChildWindows.argtypes = [wt.HWND, self._enum_t, wt.LPARAM]
        u.IsWindowVisible.argtypes = [wt.HWND]
        u.IsIconic.argtypes = [wt.HWND]
        u.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
        u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.GetWindow.argtypes = [wt.HWND, wt.UINT]
        u.GetWindow.restype = wt.HWND
        u.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        u.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        u.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
        u.GetShellWindow.restype = wt.HWND
        u.GetForegroundWindow.restype = wt.HWND
        u.GetAncestor.argtypes = [wt.HWND, wt.UINT]
        u.GetAncestor.restype = wt.HWND
        u.SendMessageTimeoutW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT,
                                          ctypes.POINTER(ctypes.c_size_t)]
        u.SendMessageTimeoutW.restype = ctypes.c_ssize_t
        u.GetClassLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
        u.GetClassLongPtrW.restype = ctypes.c_size_t
        d.DwmGetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
        k.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
        k.OpenProcess.restype = wt.HANDLE
        k.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
        k.GetProcessTimes.argtypes = [wt.HANDLE, ctypes.POINTER(wt.FILETIME), ctypes.POINTER(wt.FILETIME),
                                      ctypes.POINTER(wt.FILETIME), ctypes.POINTER(wt.FILETIME)]
        k.CloseHandle.argtypes = [wt.HANDLE]
        k.GetApplicationUserModelId.argtypes = [wt.HANDLE, ctypes.POINTER(wt.UINT), wt.LPWSTR]

    def _text(self, fn, h):
        buf = ctypes.create_unicode_buffer(512)
        fn(h, buf, 512)
        return buf.value

    def _cloaked(self, h):
        v = wt.DWORD(0)
        return v.value if self._d.DwmGetWindowAttribute(h, 14, ctypes.byref(v), 4) == 0 else 0     # DWMWA_CLOAKED

    def snapshot(self):
        """Every top-level window, z-order top first. Only plain reads: no message is sent to any window."""
        u, out, shell = self._u, [], self._u.GetShellWindow()

        def cb(h, _lp):
            try:
                visible = bool(u.IsWindowVisible(h))
                if not visible:
                    out.append(WinInfo(int(h or 0), "", 0, "", False, 0, 0, 0, False, False))
                    return 1
                pid = wt.DWORD()
                u.GetWindowThreadProcessId(h, ctypes.byref(pid))
                owner = u.GetWindow(h, 4)                                    # GW_OWNER
                out.append(WinInfo(int(h or 0), self._text(u.GetWindowTextW, h), int(pid.value),
                                   self._text(u.GetClassNameW, h), True, int(owner or 0),
                                   int(u.GetWindowLongPtrW(h, -20)) & 0xFFFFFFFF, self._cloaked(h),
                                   bool(u.IsIconic(h)), h == shell))
            except Exception:                                                # noqa: BLE001  (never raise into Windows)
                pass
            return 1
        u.EnumWindows(self._enum_t(cb), 0)
        return out

    def foreground(self):
        """The window the user is working in, as the top-level window that owns it (a dialog counts for its owner)."""
        h = self._u.GetForegroundWindow()
        if not h:
            return 0
        return int(self._u.GetAncestor(h, 3) or h)                           # GA_ROOTOWNER

    def is_own(self, hwnd):
        """Does this window belong to this program (the bar, a panel, Settings, a menu)?"""
        pid = wt.DWORD()
        self._u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value) == os.getpid()

    def _process(self, pid):
        h = self._k.OpenProcess(0x1000, False, pid)                          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None, None
        try:
            buf, n = ctypes.create_unicode_buffer(1024), wt.DWORD(1024)
            path = buf.value if self._k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else None
            c, e, kt, ut = wt.FILETIME(), wt.FILETIME(), wt.FILETIME(), wt.FILETIME()
            start = None
            if self._k.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(kt), ctypes.byref(ut)):
                start = (c.dwHighDateTime << 32) | c.dwLowDateTime
            return (path or None), start
        finally:
            self._k.CloseHandle(h)

    def _core_pid(self, frame):
        found = []

        def cb(ch, _lp):
            if self._text(self._u.GetClassNameW, ch) == CORE_WINDOW_CLASS:
                pid = wt.DWORD()
                self._u.GetWindowThreadProcessId(ch, ctypes.byref(pid))
                found.append(int(pid.value))
            return 1
        self._u.EnumChildWindows(frame, self._enum_t(cb), 0)
        return found[0] if found else 0

    def resolve(self, w):
        """(exe path, process start time) of the app behind `w`; (None, None) when that cannot be found (yet).
        A UWP app's window is an ApplicationFrameWindow of ApplicationFrameHost; the app is its CoreWindow's process,
        which may not exist yet (opening) or any more (closing): then the caller asks again at the next scan."""
        pid = w.pid
        if w.cls == APP_FRAME_CLASS:
            pid = self._core_pid(w.hwnd)
            if not pid:
                return None, None
        return self._process(pid)

    def _packaged_window(self, hwnd):
        """Is the process that owns `hwnd` a packaged (MSIX/UWP) app? GetApplicationUserModelId with no buffer answers
        ERROR_INSUFFICIENT_BUFFER (122) for a packaged process and APPMODEL_ERROR_NO_APPLICATION (15700) for a plain one."""
        pid = wt.DWORD()
        self._u.GetWindowThreadProcessId(wt.HWND(hwnd), ctypes.byref(pid))
        h = self._k.OpenProcess(0x1000, False, pid.value) if pid.value else None
        if not h:
            return False
        try:
            n = wt.UINT(0)
            return self._k.GetApplicationUserModelId(h, ctypes.byref(n), None) in (0, 122)
        finally:
            self._k.CloseHandle(h)

    def _icon_exe(self, path, size):
        import winutil
        return winutil.file_icon(path, size) if path else None

    def _icon_window(self, hwnd, size):
        """WM_GETICON (small2, small, big). It may block on a hung window: 100 ms time-out and ABORTIFHUNG."""
        import winutil
        h = wt.HWND(hwnd)
        for which in (2, 0, 1):                                              # ICON_SMALL2, ICON_SMALL, ICON_BIG
            res = ctypes.c_size_t(0)
            ok = self._u.SendMessageTimeoutW(h, 0x7F, which, 0, 0x2, 100, ctypes.byref(res))   # WM_GETICON, ABORTIFHUNG
            if ok and res.value:
                img = winutil.hicon_to_image(res.value)
                if img is not None:
                    return img.resize((size, size))
        return None

    def _icon_class(self, hwnd, size):
        import winutil
        h = wt.HWND(hwnd)
        for idx in (-34, -14):                                               # GCL_HICONSM, GCL_HICON: a stored handle
            hi = self._u.GetClassLongPtrW(h, idx)
            if hi:
                img = winutil.hicon_to_image(hi)
                if img is not None:
                    return img.resize((size, size))
        return None

    def fetch_icon(self, hwnd, path, size):
        """PIL image or None. Runs on the icon worker thread. The HICONs are borrowed (never destroyed here).
        `path` is the exe of the app (for a UWP window: of its CoreWindow process, or None while that is not found: then
        no icon, and the caller asks again).
        Order: a UWP frame window -> only the app's exe icon (its own window/class icons are ApplicationFrameHost's);
        a packaged process -> exe icon, WM_GETICON, class icon (closest to the taskbar, measured); any other -> WM_GETICON,
        class icon, exe icon."""
        if self._text(self._u.GetClassNameW, wt.HWND(hwnd)) == APP_FRAME_CLASS:
            return self._icon_exe(path, size)
        steps = (lambda: self._icon_window(hwnd, size), lambda: self._icon_class(hwnd, size),
                 lambda: self._icon_exe(path, size))
        if self._packaged_window(hwnd):
            steps = steps[2:] + steps[:2]
        for step in steps:
            img = step()
            if img is not None:
                return img
        return None


class Win32Actions:
    """Click actions on a real window: restore, minimize, bring forward, and (only from the "Close window" menu row) ask it
    to close with WM_CLOSE, the same request as its X button. Nothing moves or resizes a window and no process is ever
    ended. Returns False when the window is gone or Windows refuses (an elevated window, say)."""

    def __init__(self):
        self._u = u = ctypes.WinDLL("user32", use_last_error=True)
        u.IsWindow.argtypes = [wt.HWND]
        u.SetForegroundWindow.argtypes = [wt.HWND]
        u.ShowWindowAsync.argtypes = [wt.HWND, ctypes.c_int]
        u.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]

    def run(self, action, hwnd):
        h = wt.HWND(hwnd)
        if not self._u.IsWindow(h):
            return False
        if action == "close":
            return bool(self._u.PostMessageW(h, 0x0010, 0, 0))               # WM_CLOSE: posted, never waits, never kills
        if action == "minimize":
            return bool(self._u.ShowWindowAsync(h, 6))                       # SW_MINIMIZE: posted, never waits for the window
        if action == "restore":
            self._u.ShowWindowAsync(h, 9)                                    # SW_RESTORE
        return bool(self._u.SetForegroundWindow(h))


class FakeActions:
    """TEST mode (and tests): only records what would have been done; no window is touched."""

    def __init__(self):
        self.calls = []

    def run(self, action, hwnd):
        self.calls.append((action, hwnd))
        return True


class FakeSource:
    """TEST mode: a made-up list, no Windows call. The first window is the active one; the third is minimized."""

    def __init__(self, titles=None, own_pid=0):
        self.titles = list(titles if titles is not None else ui.BAR_TEST_WINDOWS)
        self.active_index = 0
        self.minimized = {2}

    def snapshot(self):
        return [WinInfo(1000 + i, t, 5000 + i, "FakeWindow", True, 0, 0, 0, i in self.minimized, False)
                for i, t in enumerate(self.titles)]

    def foreground(self):
        return 1000 + self.active_index

    def is_own(self, hwnd):
        return False

    def resolve(self, w):
        return "fake/app%d.exe" % (w.pid - 5000), 132000000000000000 + (w.pid - 5000) * 10_000_000

    def fetch_icon(self, hwnd, path, size):
        from PIL import Image
        n = (hwnd * 53) % 200 + 40
        return Image.new("RGBA", (size, size), (n, 120, 255 - n // 2, 255))


# ------------------------------------------------------------------ icons
class IconLoader:
    """One daemon worker thread. `request(hwnd, path)` -> later `put(("bar", ("icon", hwnd, PIL image or None)))`."""

    def __init__(self, fetch, put, size=ICON_SIZE):
        self._fetch, self._put, self._size = fetch, put, size
        self._q = queue.Queue()
        self._thread = None

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def request(self, hwnd, path):
        self._q.put((hwnd, path))

    def stop(self):
        t, self._thread = self._thread, None
        if t is not None:
            self._q.put(None)
            t.join(2)

    def _run(self):
        while True:
            item = self._q.get()
            if item is None:
                return
            try:
                img = self._fetch(item[0], item[1], self._size)
            except Exception:                                                # noqa: BLE001
                img = None
            self._put(("bar", ("icon", item[0], img)))


def generic_icon(size=ICON_SIZE):
    """The icon of a window whose own icon cannot be found: a plain rounded square in the theme's colors."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    c = theme.hex_rgb(theme.bar_palette()["dim_text"])
    ImageDraw.Draw(img).rounded_rectangle((1, 1, size - 2, size - 2), radius=3, outline=c + (255,), width=2)
    return img


def dim_icon(img, alpha=None):
    """The same icon at `alpha` opacity (minimized windows)."""
    alpha = theme.BAR_DIM_ICON_ALPHA if alpha is None else alpha
    out = img.convert("RGBA")
    a = out.getchannel("A").point(lambda v: int(v * alpha))
    out.putalpha(a)
    return out


def tile_letter(title):
    """The letter of the "letter tile" shown (titles off) for a window with no icon of its own: the first character
    of the title, upper-case; "" when the title has none (the generic icon is shown then)."""
    t = (title or "").strip()
    return t[0].upper() if t else ""


View = collections.namedtuple("View", "entries active icon_of dim_of has_icon", defaults=(None, None))


def give_foreground_back(source, actions, prev, is_own):
    """A menu of ours just closed without a command: put the foreground back on `prev`, if the window still exists and
    the foreground is still ours (if the user clicked another window to close the menu, that one keeps it).
    Never raises. True when it was given back."""
    try:
        if not prev or actions is None:
            return False
        fg = source.foreground()
        if fg and not is_own(fg):
            safe_log("info", "tasks: menu closed; foreground stays with %d", fg)
            return False
        ok = bool(actions.run("front", prev))
        safe_log("info", "tasks: menu closed; foreground %d -> %d (%s)", fg or 0, prev, "given back" if ok else "window gone")
        return ok
    except Exception:                                               # noqa: BLE001
        safe_log("exception", "tasks: giving the foreground back failed")
        return False


class ForegroundKeeper:
    """The bar's menus while "Show open windows" is OFF: there is no window list and no hook, so the window to give back
    is read from the system at the moment of the right click. If that is one of OUR windows, nothing is given back."""

    def __init__(self, source, actions):
        self.source, self.actions = source, actions

    def _is_own(self, hwnd):
        f = getattr(self.source, "is_own", None)
        try:
            return bool(f(hwnd)) if f is not None else False
        except Exception:                                           # noqa: BLE001
            return False

    def previous_active(self):
        try:
            fg = self.source.foreground()
            return int(fg) if fg and not self._is_own(fg) else 0
        except Exception:                                           # noqa: BLE001
            safe_log("exception", "tasks: previous window lookup failed")
            return 0

    def give_back(self, prev):
        return give_foreground_back(self.source, self.actions, prev, self._is_own)


class Tasks:
    """The controller (Tk thread only). `on_change()` is called when what the bar shows changed (list, titles,
    minimized, active, an icon arrived)."""

    def __init__(self, source, loader, on_change, own_pid=None, now=time.monotonic, make_photo=None, actions=None,
                 schedule=None):
        self.source, self.loader, self._on_change, self._now = source, loader, on_change, now
        self.actions, self._schedule = actions, schedule              # schedule(ms, fn): root.after
        self.model = TaskModel(own_pid if own_pid is not None else os.getpid())
        self._make_photo = make_photo
        self._dirty = False
        self._last_scan = None
        self._photos = {}              # hwnd -> PhotoImage with the window's real icon
        self._dim = {}                 # hwnd -> the same icon, faded (minimized windows)
        self._inflight, self._last_try = set(), {}
        self._generic = self._generic_dim = None
        self.started = False
        self.scans = 0
        self.last_external = 0         # the last foreground window that was NOT ours (never the bar, a panel, Settings)

    def _photo(self, img):
        if self._make_photo is not None:
            return self._make_photo(img)
        from PIL import ImageTk
        return ImageTk.PhotoImage(img)

    # ---- lifecycle
    def start(self):
        self.started = True
        self.loader.start()
        self.scan()

    def stop(self):
        self.started = False
        self.loader.stop()
        self._photos.clear()
        self._dim.clear()
        self._inflight.clear()
        self._last_try.clear()
        self._generic = self._generic_dim = None

    # ---- detection
    def mark_dirty(self):
        self._dirty = True

    def pump(self):
        """Called every App._poll round: scan if something was reported, but never more often than every 100 ms."""
        if self.started and self._dirty and (self._last_scan is None or self._now() - self._last_scan >= SCAN_MIN_S):
            self.scan()

    def tick(self):
        """The 2 s safety comparison: the same full scan, whether or not an event was seen."""
        if self.started:
            self.scan()

    def scan(self):
        self._dirty = False
        self._last_scan = self._now()
        self.scans += 1
        fg = self.source.foreground()
        self._note_foreground(fg)
        changed, removed = self.model.update(self.source.snapshot(), self.source.resolve, fg)
        for h in removed:                                       # the window is gone: its icon and bookkeeping go
            self._photos.pop(h, None)
            self._dim.pop(h, None)
            self._inflight.discard(h)
            self._last_try.pop(h, None)
        now = self._now()
        for e in self.model.entries:                            # no real icon yet (or still none): ask again, slowly
            if e.hwnd in self._photos or e.hwnd in self._inflight:
                continue
            if now - self._last_try.get(e.hwnd, -1e9) >= ICON_RETRY_S:
                self._last_try[e.hwnd] = now
                self._inflight.add(e.hwnd)
                self.loader.request(e.hwnd, e.path)
        if changed:
            self._on_change()

    def on_icon(self, hwnd, img):
        """The worker's answer (arrives through the app queue, so this runs on the Tk thread)."""
        self._inflight.discard(hwnd)
        if not self.started or not any(e.hwnd == hwnd for e in self.model.entries):
            return
        if img is not None:
            self._photos[hwnd] = self._photo(img)
            self._dim[hwnd] = self._photo(dim_icon(img))
            self._on_change()

    # ---- the foreground we give back after a menu
    def _is_own(self, hwnd):
        f = getattr(self.source, "is_own", None)
        try:
            return bool(f(hwnd)) if f is not None else False
        except Exception:                                               # noqa: BLE001
            return False

    def _note_foreground(self, fg):
        if fg and not self._is_own(fg):
            self.last_external = int(fg)

    def previous_active(self):
        """The window that was active before the click: the foreground window now, unless that is one of OURS (a menu
        or the bar may hold it): then the last foreground window that was not. 0 if there is none. Never raises."""
        try:
            fg = self.source.foreground()
            self._note_foreground(fg)
            if fg and not self._is_own(fg):
                return int(fg)
            return self.last_external
        except Exception:                                               # noqa: BLE001
            safe_log("exception", "tasks: previous window lookup failed")
            return 0

    def give_back(self, prev):
        """A menu of ours just closed without a command: put the foreground back on `prev` (see give_foreground_back).
        Never raises. True when it was given back."""
        if not self.started:
            return False
        return give_foreground_back(self.source, self.actions, prev, self._is_own)

    # ---- clicks (step 3)
    def activate(self, hwnd, prev_active):
        """A click on a button (or a "+N" menu row). `prev_active` is the foreground window read when the mouse went DOWN
        (clicking the bar does not change it, but a menu might). Never raises. True when the request was made."""
        try:
            entry = next((e for e in self.model.entries if e.hwnd == hwnd), None)
            if entry is None or self.actions is None:
                return False                                            # the window is gone (or nothing to act with)
            action = decide(entry.minimized, prev_active, hwnd)
            ok = bool(self.actions.run(action, hwnd))
            if not ok:
                safe_log("info", "tasks: could not bring window %d forward (%s)", hwnd, action)
            elif action != "minimize" and self._schedule is not None:
                self._schedule(150, lambda: self._check_front(hwnd, action))
            self.mark_dirty()                                           # show the result at once
            return ok
        except Exception:                                               # noqa: BLE001  (a click must never break Tk)
            safe_log("exception", "tasks: click failed")
            return False

    def _check_front(self, hwnd, action):
        try:
            if self.started and self.source.foreground() != hwnd:
                safe_log("info", "tasks: could not bring window %d forward (%s)", hwnd, action)
        except Exception:                                               # noqa: BLE001
            pass

    def close_window(self, hwnd):
        """"Close window" from a button's menu: ask that window to close (WM_CLOSE through actions). The button is NOT
        removed here: it goes the normal way, when the next scan no longer finds the window. A window that is already
        gone, or one Windows will not let us post to (an elevated one), is logged quietly. Never raises."""
        try:
            if self.actions is None or not hwnd:
                return False
            ok = bool(self.actions.run("close", hwnd))
            if not ok:
                safe_log("info", "tasks: could not ask window %d to close", hwnd)
            return ok
        except Exception:                                               # noqa: BLE001
            safe_log("exception", "tasks: close request failed")
            return False

    # ---- what the bar draws
    def icon_of(self, hwnd):
        p = self._photos.get(hwnd)
        if p is None:
            if self._generic is None:
                self._generic = self._photo(generic_icon())
            p = self._generic
        return p

    def dim_of(self, hwnd):
        """The icon for a minimized window: the real one, faded."""
        p = self._dim.get(hwnd)
        if p is None:
            if self._generic_dim is None:
                self._generic_dim = self._photo(dim_icon(generic_icon()))
            p = self._generic_dim
        return p

    def has_icon(self, hwnd):
        return hwnd in self._photos

    def view(self):
        return View(self.model.entries, self.model.active, self.icon_of, self.dim_of, self.has_icon)
