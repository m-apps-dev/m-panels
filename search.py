"""The search launcher's logic (v1.2 step 4): the program list (index), the matching, the launching and the few Windows
calls it needs. No tkinter here. Everything the outside world does is handed in (the sources of the list, the thread
starter, the clock, the Windows actions), so tests use made-up ones.

Source of the list: the shell:AppsFolder enumeration (the list the Start menu's "All apps" shows, Store apps included).
Each entry is (display name, parsing name); a program is started with os.startfile("shell:AppsFolder\\<parsing name>").
If AppsFolder raises or is empty, the .lnk files of the two Start Menu "Programs" folders are used instead (the Startup
sub-folder of both is left out) and a line in mpanels.log says so. Duplicates are removed by PARSING NAME, never by the
display name: two different programs with the same name both stay (a gray hint tells them apart).

Matching: the four Turkish forms of the letter i, case and accents are folded (c with cedilla -> c ...). Order of
results: whole name > name prefix > word prefix > initials ("vsc" -> Visual Studio Code) > substring; then the shorter
name, then alphabetical. An empty text matches nothing.

Windows calls (the only ones in this module): SendInput (the Win+S keystrokes and the typed text), GetForegroundWindow,
GetDoubleClickTime. The Win key is ALWAYS released again (finally)."""
import collections
import ctypes
import ctypes.wintypes as wt
import os
import re
import threading
import time
import unicodedata

import applog

LOG = applog.get_logger()

SCAN_MAX_AGE_S = 30            # a list older than this is refreshed in the background when the window opens
MAX_ROWS = 8                   # rows shown under the text box
MAX_TYPED = 256                # most characters typed into Windows Search
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x1, 0x2, 0x4, 0x8
VK_SPACE = 0x20
# The shortcut keys the Settings list offers (key = the value in config.json). Alt+Space (it would break every window's
# system menu) and Ctrl+Space (code completion in editors) are NOT offered. Experiment (24.11): these two were free.
HOTKEYS = {"off": None, "win+alt+space": (MOD_WIN | MOD_ALT, VK_SPACE), "ctrl+shift+space": (MOD_CONTROL | MOD_SHIFT, VK_SPACE)}
DEFAULT_HOTKEY = "off"
DEFAULTS = {"enabled": True, "hotkey": DEFAULT_HOTKEY, "store_apps": True, "windows_row": False}

APPS_FOLDER = "shell:AppsFolder\\"
Entry = collections.namedtuple("Entry", "name parsing kind hint store folded")      # kind: "app" (AppsFolder) | "lnk"


# ------------------------------------------------------------------ config
def defaults():
    return dict(DEFAULTS)


def sanitize(src):
    """A complete, valid 'search' dict. Wrong types fall back to the defaults; unknown keys are kept."""
    s = src if isinstance(src, dict) else {}
    out = {k: v for k, v in s.items() if k not in DEFAULTS}
    for k in ("enabled", "store_apps", "windows_row"):
        out[k] = s[k] if isinstance(s.get(k), bool) else DEFAULTS[k]
    out["hotkey"] = s["hotkey"] if s.get("hotkey") in HOTKEYS else DEFAULT_HOTKEY
    return out


def differences(search_cfg):
    """Only what differs from the defaults (this is what config.json holds)."""
    s = sanitize(search_cfg)
    return {k: v for k, v in s.items() if k not in DEFAULTS or v != DEFAULTS[k]}


# ------------------------------------------------------------------ matching
_FOLD_MAP = {0x130: "i", 0x131: "i", 0x49: "i"}        # I with dot, dotless i, I  ->  i


def fold(text):
    """Case-, accent- and Turkish-i-insensitive form of `text` (what is compared)."""
    t = unicodedata.normalize("NFKD", str(text).translate(_FOLD_MAP).casefold())
    return "".join(c for c in t if not unicodedata.combining(c))


def _words(f):
    return [w for w in re.split(r"[\W_]+", f) if w]


def _at_word_start(f, q):
    i = f.find(q)
    while i != -1:
        if i == 0 or not f[i - 1].isalnum():
            return True
        i = f.find(q, i + 1)
    return False


def tier(q, f):
    """0 whole name, 1 name prefix, 2 word prefix, 3 initials, 4 substring; None = no match. `q`, `f` are folded."""
    if f == q:
        return 0
    if f.startswith(q):
        return 1
    if _at_word_start(f, q):
        return 2
    qn = q.replace(" ", "")
    if len(qn) >= 2 and "".join(w[0] for w in _words(f)).startswith(qn):
        return 3
    if q in f:
        return 4
    return None


def is_store(parsing):
    """A packaged (Store) app: its parsing name is an AppUserModelID, 'PackageFamily!App' (a path never is)."""
    return "!" in parsing and "\\" not in parsing and "/" not in parsing


def make_entry(name, parsing, kind):
    return Entry(name, parsing, kind, "", is_store(parsing) if kind == "app" else False, fold(name))


def search(entries, text, store_apps=True, limit=MAX_ROWS):
    """The best `limit` entries for `text`, best first. Store apps are left out when `store_apps` is False."""
    q = fold(text).strip()
    if not q:
        return []
    found = []
    for e in entries:
        if not store_apps and e.store:
            continue
        t = tier(q, e.folded)
        if t is not None:
            found.append(((t, len(e.name), e.folded, e.name, e.parsing), e))
    found.sort(key=lambda p: p[0])
    return [e for _, e in found[:limit]]


def build_rows(entries, text, store_apps=True, windows_row=False, limit=MAX_ROWS):
    """What the list shows: [("app", Entry), ...] and, when `windows_row` is on and there is text, a last row
    ("windows", text) (it takes one of the `limit` places)."""
    t = (text or "").strip()
    row = windows_row and bool(t)
    rows = [("app", e) for e in search(entries, text, store_apps, limit - 1 if row else limit)]
    if row:
        rows.append(("windows", t))
    return rows


# ------------------------------------------------------------------ the list
def _path_hint(parsing, kind, depth):
    parts = [p for p in re.split(r"[\\/]+", parsing) if p and not p.startswith("{")]
    if kind == "lnk" or "\\" in parsing:
        parts = parts[:-1] or parts                       # the folder(s) above the file
    return "\\".join(parts[-depth:]) if parts else parsing


def _hint(e, depth):
    if e.kind == "app" and is_store(e.parsing):
        family = e.parsing.split("!")[0]
        if depth <= 1:
            return family.split("_")[0]
        return family if depth == 2 else e.parsing
    if e.kind == "lnk" or "\\" in e.parsing:
        return _path_hint(e.parsing, e.kind, depth)
    return e.parsing


def with_hints(entries):
    """Entries whose name is shared get a short gray hint that tells them apart (a folder, or the package name); the
    hint grows (one more folder, the whole family name) until the entries of one name differ. Others get no hint."""
    groups = collections.defaultdict(list)
    for i, e in enumerate(entries):
        groups[e.folded].append(i)
    out = list(entries)
    for idx in groups.values():
        if len(idx) < 2:
            continue
        for depth in (1, 2, 3, 4):
            hints = [_hint(entries[i], depth) for i in idx]
            if len(set(h.casefold() for h in hints)) == len(hints):
                break
        for i, h in zip(idx, hints):
            out[i] = entries[i]._replace(hint=h)
    return out


def entries_from_apps(rows):
    """AppsFolder rows (name, parsing name) -> entries; one per parsing name (case-insensitive)."""
    seen, out = set(), []
    for name, parsing in rows:
        if not name or not parsing or str(name).startswith("<error"):
            continue
        key = parsing.casefold()
        if key not in seen:
            seen.add(key)
            out.append(make_entry(name, parsing, "app"))
    return out


def entries_from_lnk(items):
    """Shortcut files (name, path, rank: 0 = the user's folder, 1 = the common one) -> entries. A shortcut of the common
    folder is dropped when the user's folder has one of the same name."""
    user = {fold(n) for n, _p, r in items if r == 0}
    seen, out = set(), []
    for name, path, rank in sorted(items, key=lambda t: t[2]):
        key = path.casefold()
        if key in seen or (rank != 0 and fold(name) in user):
            continue
        seen.add(key)
        out.append(make_entry(name, path, "lnk"))
    return out


def scan_lnk(roots):
    """The .lnk files under [(folder, rank)]: [(name, path, rank)]. The "Startup" sub-folder of each root is skipped."""
    out = []
    for root, rank in roots:
        if not root or not os.path.isdir(root):
            continue
        for cur, dirs, files in os.walk(root):
            if os.path.normcase(cur) == os.path.normcase(root):
                dirs[:] = [d for d in dirs if d.casefold() != "startup"]
            for f in files:
                if f.lower().endswith(".lnk"):
                    out.append((os.path.splitext(f)[0], os.path.join(cur, f), rank))
    return out


def scan(sources, log=LOG):
    """(entries, "appsfolder" | "lnk"). AppsFolder first; an exception or an empty list falls back to the shortcuts
    (and says so in the log). Runs on a worker thread."""
    entries = []
    try:
        entries = entries_from_apps(sources.appsfolder())
    except Exception as e:                                           # noqa: BLE001
        log.warning("search: shell:AppsFolder failed (%s); using the Start Menu shortcuts", type(e).__name__)
    else:
        if not entries:
            log.warning("search: shell:AppsFolder gave no entries; using the Start Menu shortcuts")
    if entries:
        return with_hints(entries), "appsfolder"
    return with_hints(entries_from_lnk(sources.lnk())), "lnk"


class Index:
    """The cached list. Nothing here waits for a scan: `entries()` is always the last finished list (maybe empty);
    a scan runs on a worker thread (`spawn(fn)`), its result comes back through `deliver(result)` (the app queue) and is
    taken over on the Tk thread by `finish(result)`. One scan at a time. `clock()` is injected."""

    def __init__(self, sources, clock, spawn, deliver):
        self.sources, self.clock, self._spawn, self._deliver = sources, clock, spawn, deliver
        self._entries = []
        self.cached_at = None
        self.scanning = False
        self.kind = ""
        self.stopped = False
        self.scans = 0

    def entries(self):
        return self._entries

    def start(self):
        """The first scan, at start-up (in the background)."""
        return self.request_refresh()

    def refresh_if_stale(self):
        if self.cached_at is None or self.clock() - self.cached_at >= SCAN_MAX_AGE_S:
            return self.request_refresh()
        return False

    def request_refresh(self):
        if self.scanning or self.stopped:
            return False
        self.scanning = True
        self.scans += 1
        self._spawn(self._work)
        return True

    def _work(self):                                    # worker thread
        try:
            result = scan(self.sources)
        except Exception:                               # noqa: BLE001
            LOG.exception("search: the scan failed")
            result = None
        self._deliver(result)

    def finish(self, result):
        """Tk thread: a scan ended. True when the list changed. A failed (None) or empty result keeps the old list and
        the old time, so the next opening tries again."""
        self.scanning = False
        if result is None or self.stopped or not result[0]:
            return False
        self._entries, self.kind = list(result[0]), result[1]
        self.cached_at = self.clock()
        return True

    def stop(self):
        self.stopped = True


def thread_spawn(fn):
    threading.Thread(target=fn, daemon=True, name="search-scan").start()


# ------------------------------------------------------------------ the real sources
class Win32Sources:
    """The real lists (read only). `appsfolder()` runs on a worker thread, so it starts COM there."""

    def appsfolder(self):
        import pythoncom
        from win32com.shell import shell, shellcon
        started = False
        try:
            pythoncom.CoInitialize()
            started = True
        except Exception:                                # noqa: BLE001  (already started in another mode: go on)
            pass
        try:
            pidl = shell.SHParseDisplayName("shell:AppsFolder", 0)[0]
            folder = shell.SHGetDesktopFolder().BindToObject(pidl, None, shell.IID_IShellFolder)
            out = []
            for child in folder.EnumObjects(0, shellcon.SHCONTF_NONFOLDERS | shellcon.SHCONTF_FOLDERS):
                try:
                    out.append((folder.GetDisplayNameOf(child, shellcon.SHGDN_NORMAL),
                                folder.GetDisplayNameOf(child, shellcon.SHGDN_FORPARSING)))
                except Exception:                        # noqa: BLE001  (one bad entry does not spoil the list)
                    continue
            return out
        finally:
            if started:
                pythoncom.CoUninitialize()

    def lnk(self):
        from win32com.shell import shell
        roots = []
        for rank, fid in ((0, shell.FOLDERID_Programs), (1, shell.FOLDERID_CommonPrograms)):
            try:
                roots.append((shell.SHGetKnownFolderPath(fid, 0, 0), rank))
            except Exception:                            # noqa: BLE001
                LOG.warning("search: a Start Menu folder could not be found")
        return scan_lnk(roots)


# ------------------------------------------------------------------ icons
def icon_path(entry, known_folder=None):
    """A real file whose icon stands for the entry: the shortcut itself, or the path in the parsing name (a plain path,
    or '{KNOWN-FOLDER-GUID}\\rest' with the folder resolved by `known_folder(guid)`). None for a packaged app (its
    logo is not reachable that way: a letter tile is shown)."""
    if entry.kind == "lnk":
        return entry.parsing
    p = entry.parsing
    if re.match(r"^[A-Za-z]:\\", p):
        return p
    m = re.match(r"^(\{[0-9A-Fa-f\-]{36}\})\\(.+)$", p)
    if m and known_folder is not None:
        try:
            base = known_folder(m.group(1))
        except Exception:                                # noqa: BLE001
            return None
        return os.path.join(base, m.group(2)) if base else None
    return None


def real_icon(entry, size):
    """PIL image of the entry's icon or None. Worker thread."""
    def known(guid):
        import pywintypes
        from win32com.shell import shell
        return shell.SHGetKnownFolderPath(pywintypes.IID(guid), 0, 0)
    path = icon_path(entry, known)
    if not path or not os.path.exists(path):
        return None
    import winutil
    return winutil.file_icon(path, size)


class IconWorker:
    """One daemon thread that fetches the icons of the rows on show. `request(entry)` -> later
    `put(("bar", ("sicon", entry.parsing, PIL image or None)))`."""

    def __init__(self, fetch, put, size):
        self._fetch, self._put, self._size = fetch, put, size
        self._q = None
        self._thread = None

    def request(self, entry):
        if self._thread is None:
            import queue
            self._q = queue.Queue()
            self._thread = threading.Thread(target=self._run, daemon=True, name="search-icons")
            self._thread.start()
        self._q.put(entry)

    def _run(self):
        while True:
            e = self._q.get()
            if e is None:
                return
            try:
                img = self._fetch(e, self._size)
            except Exception:                            # noqa: BLE001
                img = None
            self._put(("bar", ("sicon", e.parsing, img)))

    def stop(self):
        t, self._thread = self._thread, None
        if t is not None:
            self._q.put(None)
            t.join(2)


# ------------------------------------------------------------------ Windows actions
def place_window(x, y, w, h, work):
    """(x, y) of a w x h window wanted at (x, y), moved to lie inside `work` (left, top, right, bottom)."""
    nx = max(work[0], min(x, work[2] - w))
    ny = max(work[1], min(y, work[3] - h))
    return nx, ny


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


_u = ctypes.WinDLL("user32", use_last_error=True)
_u.SendInput.argtypes = [wt.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
_u.SendInput.restype = wt.UINT
_u.GetForegroundWindow.restype = wt.HWND
_u.GetDoubleClickTime.restype = wt.UINT
VK_LWIN, VK_S = 0x5B, 0x53
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x1, 0x2, 0x4


def _real_send(events):
    """Send [(vk, scan, flags)] as keyboard input, one call. Returns how many events Windows took (a count only:
    input dropped for a window of a higher integrity level is not reported)."""
    arr = (_INPUT * len(events))()
    for i, (vk, scan_code, flags) in enumerate(events):
        arr[i].type = 1
        arr[i].ki = _KEYBDINPUT(vk, scan_code, flags, 0, 0)
    return int(_u.SendInput(len(events), arr, ctypes.sizeof(_INPUT)))


def double_click_ms():
    """The system's double-click time (ms)."""
    try:
        return int(_u.GetDoubleClickTime()) or 500
    except Exception:                                    # noqa: BLE001
        return 500


class SearchActions:
    """What the search window does to Windows: start a program, open Windows Search, type text. Tests give a made-up
    `send`, `startfile` and `foreground`, so nothing real is touched."""

    def __init__(self, send=None, foreground=None, startfile=None, sleep=time.sleep):
        self._send = send or _real_send
        self._foreground = foreground
        self._startfile = startfile
        self._sleep = sleep

    def launch(self, entry):
        """Start the program. Raises OSError when Windows cannot."""
        target = APPS_FOLDER + entry.parsing if entry.kind == "app" else entry.parsing
        (self._startfile or os.startfile)(target)

    def foreground(self):
        if self._foreground is not None:
            return int(self._foreground() or 0)
        return int(_u.GetForegroundWindow() or 0)

    def open_windows_search(self):
        """Win+S. The Win key goes up again whatever happens in between."""
        down = False
        try:
            self._send([(VK_LWIN, 0, KEYEVENTF_EXTENDEDKEY)])
            down = True
            self._sleep(0.02)
            self._send([(VK_S, 0, 0)])
            self._sleep(0.02)
            self._send([(VK_S, 0, KEYEVENTF_KEYUP)])
            self._sleep(0.02)
            self._send([(VK_LWIN, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP)])
            down = False
        finally:
            if down:
                try:
                    self._send([(VK_LWIN, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP)])
                except Exception:                        # noqa: BLE001
                    LOG.exception("search: the Win key could not be released")

    def type_text(self, text):
        """Type `text` into the window that has the keyboard (Unicode key events, no key codes)."""
        raw = str(text)[:MAX_TYPED].encode("utf-16-le")
        events = []
        for i in range(0, len(raw), 2):
            unit = raw[i] | (raw[i + 1] << 8)
            events.append((0, unit, KEYEVENTF_UNICODE))
            events.append((0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        if events:
            self._send(events)


class FakeSearchActions:
    """TEST mode (and tests): only records; nothing is started, sent or read from Windows."""

    def __init__(self):
        self.calls = []
        self.fail = None                 # an exception to raise from launch()
        self.fg = 0
        self.fg_after_win_s = None       # what foreground() says after open_windows_search() (None: unchanged)

    def launch(self, entry):
        self.calls.append(("launch", entry.parsing))
        if self.fail is not None:
            raise self.fail

    def foreground(self):
        return self.fg

    def open_windows_search(self):
        self.calls.append(("win_s",))
        if self.fg_after_win_s is not None:
            self.fg = self.fg_after_win_s

    def type_text(self, text):
        self.calls.append(("type", text))


class FakeSources:
    """A made-up list for tests: `apps` = [(name, parsing)], `lnks` = [(name, path, rank)]; `apps` may be an exception."""

    def __init__(self, apps=(), lnks=()):
        self.apps, self.lnks = apps, lnks
        self.calls = []

    def appsfolder(self):
        self.calls.append("appsfolder")
        if isinstance(self.apps, BaseException):
            raise self.apps
        return list(self.apps)

    def lnk(self):
        self.calls.append("lnk")
        return list(self.lnks)
