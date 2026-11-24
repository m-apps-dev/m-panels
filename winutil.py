"""Windows-specific helpers: desktop paths, shortcuts, hidden attribute, icons, single instance.

This module never touches the "real desktop" on its own; paths come from the caller's parameters.
The only exception is get_real_desktop() / get_public_desktop() (they only READ).
"""
import ctypes
import os
import sys
import threading

from PIL import Image

try:
    import pythoncom
    import win32api
    import win32con
    import win32gui
    import win32com.client
    from win32com.shell import shell, shellcon
    HAS_WIN32 = True
except Exception:  # pywin32 missing
    HAS_WIN32 = False


# ------------------------------------------------------------------ paths (read-only)
def get_real_desktop():
    """The user's real desktop folder (may be redirected to a cloud-synced folder)."""
    return str(shell.SHGetKnownFolderPath(shell.FOLDERID_Desktop, 0, 0))


def get_public_desktop():
    return str(shell.SHGetKnownFolderPath(shell.FOLDERID_PublicDesktop, 0, 0))


def get_startup_dir():
    return os.path.join(os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs\Startup")


# ------------------------------------------------------------------ file attributes
def set_hidden(path):
    attrs = win32api.GetFileAttributes(path)
    win32api.SetFileAttributes(path, attrs | win32con.FILE_ATTRIBUTE_HIDDEN)


def is_hidden(path):
    try:
        return bool(os.stat(path).st_file_attributes & 0x2)
    except Exception:
        return False


# ------------------------------------------------------------------ shortcuts
def _shelllink():
    return pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER,
                                      shell.IID_IShellLink)


def create_shortcut(lnk_path, target, args="", workdir="", icon="", desc=""):
    """Create a .lnk. Uses IShellLink (Unicode): WScript.Shell is ANSI, so it cannot save
    paths with Turkish characters (e.g. an accented folder name)."""
    sl = _shelllink()
    sl.SetPath(target)
    if args:
        sl.SetArguments(args)
    wd = workdir or (os.path.dirname(target) if os.path.isabs(target) else "")
    if wd:
        sl.SetWorkingDirectory(wd)
    if icon:
        sl.SetIconLocation(icon, 0)
    if desc:
        sl.SetDescription(desc)
    sl.QueryInterface(pythoncom.IID_IPersistFile).Save(lnk_path, 0)


_lnk_cache = {}


def resolve_shortcut(lnk_path):
    """.lnk target path (may be empty: UWP/shell targets). Served from the cache if unchanged."""
    try:
        key = (lnk_path, os.stat(lnk_path).st_mtime_ns)
    except OSError:
        return ""
    if key in _lnk_cache:
        return _lnk_cache[key]
    try:
        sl = _shelllink()
        sl.QueryInterface(pythoncom.IID_IPersistFile).Load(lnk_path, 0)
        target = sl.GetPath(0)[0] or ""
    except Exception:
        target = ""
    _lnk_cache[key] = target
    return target


# ------------------------------------------------------------------ icons
SHGFI_SYSICONINDEX = 0x4000
SHGFI_PIDL = 0x8
SHIL_LARGE, SHIL_EXTRALARGE = 0, 2


class _ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", ctypes.c_int), ("xHotspot", ctypes.c_uint32), ("yHotspot", ctypes.c_uint32),
                ("hbmMask", ctypes.c_void_p), ("hbmColor", ctypes.c_void_p)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16),
                ("biCompression", ctypes.c_uint32), ("biSizeImage", ctypes.c_uint32),
                ("biXPelsPerMeter", ctypes.c_int32), ("biYPelsPerMeter", ctypes.c_int32),
                ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]


_user32 = ctypes.windll.user32 if sys.platform == "win32" else None
_gdi32 = ctypes.windll.gdi32 if sys.platform == "win32" else None
if _user32:
    _user32.GetDC.restype = ctypes.c_void_p
    _user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    _user32.GetIconInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ICONINFO)]
    _user32.DestroyIcon.argtypes = [ctypes.c_void_p]
    _gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    _gdi32.GetObjectW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    _gdi32.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
                                 ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]


def _dib(hdc, hbm, w, h):
    bmi = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    _gdi32.GetDIBits(hdc, hbm, 0, h, buf, ctypes.byref(bmi), 0)
    return buf.raw


def hicon_to_image(hicon):
    """HICON -> PIL RGBA (with the alpha channel)."""
    ii = _ICONINFO()
    if not _user32.GetIconInfo(hicon, ctypes.byref(ii)):
        return None
    hdc = _user32.GetDC(None)
    try:
        bm = (ctypes.c_byte * 32)()
        _gdi32.GetObjectW(ii.hbmColor or ii.hbmMask, 32, bm)
        w = int.from_bytes(bytes(bm[4:8]), "little", signed=True)
        h = abs(int.from_bytes(bytes(bm[8:12]), "little", signed=True))
        if not ii.hbmColor:           # monochrome icon (rare)
            return None
        raw = _dib(hdc, ii.hbmColor, w, h)
        img = Image.frombuffer("RGBA", (w, h), raw, "raw", "BGRA", 0, 1)
        if img.getchannel("A").getextrema() == (0, 0):     # no alpha -> derive it from the mask
            mraw = _dib(hdc, ii.hbmMask, w, h)
            mask = Image.frombuffer("RGBA", (w, h), mraw, "raw", "BGRA", 0, 1).convert("L")
            img.putalpha(mask.point(lambda v: 0 if v > 127 else 255))
        return img
    finally:
        _user32.ReleaseDC(None, hdc)
        if ii.hbmColor:
            _gdi32.DeleteObject(ii.hbmColor)
        if ii.hbmMask:
            _gdi32.DeleteObject(ii.hbmMask)


class _GUID(ctypes.Structure):
    _fields_ = [("D1", ctypes.c_uint32), ("D2", ctypes.c_uint16), ("D3", ctypes.c_uint16),
                ("D4", ctypes.c_ubyte * 8)]


def _iid_imagelist():
    # IID_IImageList = {46EB5926-582E-4017-9FDF-E8998DAA0950}
    return _GUID(0x46EB5926, 0x582E, 0x4017, (ctypes.c_ubyte * 8)(0x9F, 0xDF, 0xE8, 0x99, 0x8D, 0xAA, 0x09, 0x50))


_imagelists = {}


def _imagelist(which):
    """System icon list (IImageList* == HIMAGELIST; used with comctl32 ImageList_GetIcon)."""
    if which not in _imagelists:
        ptr = ctypes.c_void_p()
        iid = _iid_imagelist()
        hr = ctypes.windll.shell32.SHGetImageList(which, ctypes.byref(iid), ctypes.byref(ptr))
        if hr != 0 or not ptr.value:
            raise OSError(f"SHGetImageList error {hr:#x}")
        _imagelists[which] = ptr.value
    return _imagelists[which]


def _icon_from_index(idx, size):
    which = SHIL_EXTRALARGE if size > 32 else SHIL_LARGE
    cc = ctypes.windll.comctl32
    cc.ImageList_GetIcon.restype = ctypes.c_void_p
    cc.ImageList_GetIcon.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint]
    hicon = cc.ImageList_GetIcon(_imagelist(which), idx, 0x1)    # ILD_TRANSPARENT
    if not hicon:
        return None
    try:
        return hicon_to_image(hicon)
    finally:
        _user32.DestroyIcon(hicon)


def shell_icon_key(path):
    """Cache key: the system icon index (the full/empty Recycle Bin icon changes it too)."""
    try:
        return shell.SHGetFileInfo(path, 0, SHGFI_SYSICONINDEX)[1][1]
    except Exception:
        return -1


def file_icon(path, size=32):
    """The Windows icon of a file/folder/shortcut (PIL RGBA, size x size)."""
    try:
        idx = shell.SHGetFileInfo(path, 0, SHGFI_SYSICONINDEX)[1][1]
        img = _icon_from_index(idx, size)
        if img is not None:
            return img.resize((size, size), Image.LANCZOS)
    except Exception:
        pass
    return None


def recycle_bin_key():
    try:
        pidl = shell.SHGetSpecialFolderLocation(0, shellcon.CSIDL_BITBUCKET)
        return shell.SHGetFileInfo(pidl, 0, SHGFI_SYSICONINDEX | SHGFI_PIDL)[1][1]
    except Exception:
        return -1


def recycle_bin_icon(size=32):
    try:
        pidl = shell.SHGetSpecialFolderLocation(0, shellcon.CSIDL_BITBUCKET)
        idx = shell.SHGetFileInfo(pidl, 0, SHGFI_SYSICONINDEX | SHGFI_PIDL)[1][1]
        img = _icon_from_index(idx, size)
        if img is not None:
            return img.resize((size, size), Image.LANCZOS)
    except Exception:
        pass
    return None


# ------------------------------------------------------------------ windows
_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x80
_WS_EX_APPWINDOW = 0x40000


def _hwnd(tk_window):
    return _user32.GetParent(tk_window.winfo_id()) or tk_window.winfo_id()


def make_toolwindow(tk_window, bottom=False):
    """Hide from the taskbar/Alt+Tab; optionally send to the bottom of the z-order.
    A window that is already visible is withdrawn and shown again so Windows drops its taskbar button."""
    try:
        tk_window.update_idletasks()
        hwnd = _hwnd(tk_window)
        style = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        want = (style | _WS_EX_TOOLWINDOW) & ~_WS_EX_APPWINDOW
        if want != style:
            visible = bool(tk_window.winfo_viewable())
            if visible:
                tk_window.withdraw()
            _user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, want)
            if visible:
                tk_window.deiconify()
        if bottom:
            _user32.SetWindowPos(_hwnd(tk_window), 1, 0, 0, 0, 0, 0x13)   # HWND_BOTTOM, NOMOVE|NOSIZE|NOACTIVATE
    except Exception:
        pass


_WS_EX_TRANSPARENT = 0x20           # mouse clicks fall through the window
_WS_EX_NOACTIVATE = 0x08000000      # never takes focus


def make_overlay(tk_window):
    """A display-only window (the snap preview): out of the taskbar/Alt+Tab, never activated, and the mouse goes
    straight through it. Call it once, while the window is withdrawn."""
    try:
        tk_window.update_idletasks()
        hwnd = _hwnd(tk_window)
        style = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        want = (style | _WS_EX_TOOLWINDOW | _WS_EX_TRANSPARENT | _WS_EX_NOACTIVATE) & ~_WS_EX_APPWINDOW
        _user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, want)
    except Exception:
        pass


def make_bar_window(tk_window):
    """The bar window: out of the taskbar/Alt+Tab and never activated by a click, but (unlike make_overlay) it takes
    the mouse (right-click menu). Call it once, while the window is withdrawn."""
    try:
        tk_window.update_idletasks()
        hwnd = _hwnd(tk_window)
        style = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        want = (style | _WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE) & ~_WS_EX_APPWINDOW
        _user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, want)
    except Exception:
        pass


def hwnd_of(tk_window):
    """The native window handle of a Tk window (the top-level frame), as an int."""
    return int(_hwnd(tk_window))


def take_foreground(tk_window):
    """Make this window the foreground window just before a menu opens from it. Windows closes a pop-up menu on Escape
    or an outside click only when the menu's owner is the foreground window; a NOACTIVATE bar is not, so without this
    Escape does nothing and the click that dismisses the menu is swallowed. True if the window now is the foreground."""
    try:
        hwnd = _hwnd(tk_window)
        _user32.SetForegroundWindow(hwnd)
        return int(_user32.GetForegroundWindow() or 0) == int(hwnd)
    except Exception:
        return False


def post_null(tk_window):
    """The WM_NULL after a pop-up menu (the documented companion of the SetForegroundWindow before it)."""
    try:
        _user32.PostMessageW(_hwnd(tk_window), 0, 0, 0)
    except Exception:
        pass


def bar_style_ok(tk_window):
    """True if the window is a tool window that is never activated, still takes the mouse and is not click-through."""
    tk_window.update_idletasks()
    style = _user32.GetWindowLongW(_hwnd(tk_window), _GWL_EXSTYLE)
    need = _WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE
    return (style & need) == need and not (style & (_WS_EX_APPWINDOW | _WS_EX_TRANSPARENT))


def overlay_style_ok(tk_window):
    """True if the window is click-through, never activated and hidden from the taskbar (see make_overlay)."""
    tk_window.update_idletasks()
    style = _user32.GetWindowLongW(_hwnd(tk_window), _GWL_EXSTYLE)
    need = _WS_EX_TOOLWINDOW | _WS_EX_TRANSPARENT | _WS_EX_NOACTIVATE
    return (style & need) == need and not (style & _WS_EX_APPWINDOW)


_VK_LBUTTON, _VK_ESCAPE = 0x01, 0x1B


def _key_state(vk):
    """The raw GetAsyncKeyState result for a virtual key (0 if the call is not possible). Tests replace THIS to
    check the bit mask: bit 0x8000 = down right now; bit 0x0001 = "was pressed since the last call" (stale!)."""
    try:
        return int(ctypes.windll.user32.GetAsyncKeyState(vk)) & 0xFFFF
    except Exception:
        return 0


def _is_down(vk):
    return bool(_key_state(vk) & 0x8000)      # ONLY the "down now" bit; 0x0001 would give false positives


def esc_down():
    """Is the Escape key held down right now (works whichever window has the focus)?"""
    return _is_down(_VK_ESCAPE)


def lbutton_down():
    """Is the PRIMARY mouse button (Tk's button 1) held down right now, whichever window has the capture?
    GetAsyncKeyState reports the physical buttons, so with swapped buttons (left-handed setting) the primary one is VK_RBUTTON."""
    try:
        swapped = bool(ctypes.windll.user32.GetSystemMetrics(23))      # SM_SWAPBUTTON
    except Exception:
        swapped = False
    return _is_down(0x02 if swapped else _VK_LBUTTON)


# --- the snap preview window is shown/moved/hidden with Win32 only (no Tk deiconify/lift/focus: those can disturb the
# mouse capture of the panel being dragged). It is created and mapped once, then hidden.
_u32 = ctypes.WinDLL("user32", use_last_error=True)
_u32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                              ctypes.c_uint]
_u32.SetWindowPos.restype = ctypes.c_int
_u32.IsWindowVisible.argtypes = [ctypes.c_void_p]
_SWP_NOSIZE, _SWP_NOMOVE, _SWP_NOZORDER, _SWP_NOACTIVATE = 0x1, 0x2, 0x4, 0x10
_SWP_SHOWWINDOW, _SWP_HIDEWINDOW = 0x40, 0x80
_HWND_TOPMOST = ctypes.c_void_p(-1)


def overlay_show(tk_window, x, y, w, h):
    """Show (or move/resize) the window topmost without activating it: SetWindowPos(HWND_TOPMOST, NOACTIVATE|SHOWWINDOW)."""
    try:
        return bool(_u32.SetWindowPos(_hwnd(tk_window), _HWND_TOPMOST, int(x), int(y), int(w), int(h),
                                      _SWP_NOACTIVATE | _SWP_SHOWWINDOW))
    except Exception:
        return False


def overlay_hide(tk_window):
    try:
        _u32.SetWindowPos(_hwnd(tk_window), None, 0, 0, 0, 0,
                          _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_NOACTIVATE | _SWP_HIDEWINDOW)
    except Exception:
        pass


def window_visible(tk_window):
    """Is the native window shown right now (what the user sees)?"""
    try:
        return bool(_u32.IsWindowVisible(_hwnd(tk_window)))
    except Exception:
        return False


def is_toolwindow(tk_window):
    """True if the window is hidden from the taskbar/Alt+Tab (tool-window style, no app-window style)."""
    tk_window.update_idletasks()
    style = _user32.GetWindowLongW(_hwnd(tk_window), _GWL_EXSTYLE)
    return bool(style & _WS_EX_TOOLWINDOW) and not (style & _WS_EX_APPWINDOW)


def show_in_taskbar(tk_window):
    """The opposite of make_toolwindow: a normal window with a taskbar button (the Settings window)."""
    try:
        tk_window.update_idletasks()
        hwnd = _hwnd(tk_window)
        style = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        want = (style & ~_WS_EX_TOOLWINDOW) | _WS_EX_APPWINDOW
        if want != style:
            visible = bool(tk_window.winfo_viewable())
            if visible:
                tk_window.withdraw()
            _user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, want)
            if visible:
                tk_window.deiconify()
    except Exception:
        pass


def send_to_bottom(tk_window):
    try:
        hwnd = _user32.GetParent(tk_window.winfo_id()) or tk_window.winfo_id()
        _user32.SetWindowPos(hwnd, 1, 0, 0, 0, 0, 0x13)
    except Exception:
        pass


# ------------------------------------------------------------------ single instance
_mutex = None


def acquire_single_instance(name="MPanels_SingleInstance"):
    """True: first instance. False: already running."""
    global _mutex
    k32 = ctypes.windll.kernel32
    _mutex = k32.CreateMutexW(None, False, name)
    return ctypes.windll.kernel32.GetLastError() != 183   # ERROR_ALREADY_EXISTS


def release_single_instance():
    """Release the single-instance lock (idempotent)."""
    global _mutex
    if _mutex:
        try:
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(_mutex))
        except Exception:
            pass
        _mutex = None


RAISE, QUIT = "_Raise", "_Quit"        # event kinds: bring the running copy forward / ask it to quit


def _event_name(name, kind=RAISE):
    return name + kind


def signal_running_instance(name="MPanels_SingleInstance", retries=10, kind=RAISE):
    """Tell the already-running instance to come forward (it shows its panels and the Settings window).
    Retries briefly because the first instance may still be creating its event. True if signalled."""
    import time
    k32 = ctypes.windll.kernel32
    k32.OpenEventW.restype = ctypes.c_void_p
    for _ in range(max(1, retries)):
        h = k32.OpenEventW(0x0002, False, _event_name(name, kind))      # EVENT_MODIFY_STATE
        if h:
            k32.SetEvent(ctypes.c_void_p(h))
            k32.CloseHandle(ctypes.c_void_p(h))
            return True
        time.sleep(0.1)
    return False


class InstanceListener(threading.Thread):
    """Waits for signal_running_instance() from a second launch and calls callback() (from this thread)."""

    def __init__(self, name, callback, kind=RAISE):
        super().__init__(daemon=True)
        k32 = ctypes.windll.kernel32
        k32.CreateEventW.restype = ctypes.c_void_p
        self.k32, self.callback, self.stop_flag = k32, callback, False
        self.handle = k32.CreateEventW(None, False, False, _event_name(name, kind))   # auto-reset event

    def run(self):
        while not self.stop_flag:
            if self.k32.WaitForSingleObject(ctypes.c_void_p(self.handle), 300) == 0:   # WAIT_OBJECT_0
                try:
                    self.callback()
                except Exception:
                    pass

    def stop(self):
        self.stop_flag = True


def start_instance_listener(name, callback, kind=RAISE):
    t = InstanceListener(name, callback, kind)
    t.start()
    return t


def find_pythonw():
    """Path of the console-less interpreter (pythonw.exe) next to the running Python (conda base here),
    or None if it cannot be found."""
    exe = sys.executable
    if os.path.basename(exe).lower() == "pythonw.exe" and os.path.exists(exe):
        return exe
    cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(cand):
        return cand
    import shutil
    return shutil.which("pythonw")


def small_icon_size():
    """SM_CXSMICON: the size Windows draws a tray icon at (16 at 100 %, more on a scaled display). 16 if it cannot be read."""
    try:
        n = int(ctypes.windll.user32.GetSystemMetrics(49))
    except Exception:                                    # noqa: BLE001
        return 16
    return n if 12 <= n <= 64 else 16


def app_icon_path():
    """The icon file to use (tray source, shortcuts): the bundled assets/m_panels.ico, or None if it is missing."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "m_panels.ico")
    return p if os.path.isfile(p) else None


def open_path(path):
    os.startfile(path)


def reveal_in_explorer(path):
    import subprocess
    subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])


# ------------------------------------------------------------------ hide desktop icons (Explorer)
_ADV_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"


def desktop_icons_hidden():
    """Is Explorer's 'Show desktop icons' off? (HideIcons=1 -> hidden). Only READS."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _ADV_KEY) as k:
            return bool(winreg.QueryValueEx(k, "HideIcons")[0])
    except OSError:
        return False


def _defview_hwnd():
    """The desktop icon window (SHELLDLL_DefView): it can sit under Progman or under a WorkerW."""
    prog = _user32.FindWindowW("Progman", None)
    v = _user32.FindWindowExW(prog, 0, "SHELLDLL_DefView", None)
    if v:
        return v
    found = ctypes.c_void_p(0)
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(hwnd, _):
        child = _user32.FindWindowExW(hwnd, 0, "SHELLDLL_DefView", None)
        if child:
            found.value = child
            return False
        return True
    _user32.EnumWindows(EnumProc(cb), 0)
    return found.value or 0


def set_desktop_icons_hidden(hide):
    """First sends Explorer's own 'show/hide icons' command (WM_COMMAND 0x7402); if the registry does not
    reach the wanted state, writes HideIcons and refreshes the desktop. True: the wanted state was reached.
    WARNING: affects the real Explorer; only called OUTSIDE test mode."""
    import time
    import winreg
    if desktop_icons_hidden() == bool(hide):
        return True
    v = _defview_hwnd()
    if v:
        _user32.SendMessageW(v, 0x111, 0x7402, 0)       # WM_COMMAND, "Show desktop icons" toggle
        for _ in range(10):
            time.sleep(0.1)
            if desktop_icons_hidden() == bool(hide):
                return True
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _ADV_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "HideIcons", 0, winreg.REG_DWORD, 1 if hide else 0)
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)   # SHCNE_ASSOCCHANGED
        _user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "ShellState", 2, 2000, None)   # WM_SETTINGCHANGE
        if v:
            _user32.PostMessageW(v, 0x111, 0x7103, 0)    # refresh (F5)
    except OSError:
        return False
    return desktop_icons_hidden() == bool(hide)


class DesktopIconsBackend:
    get_hidden = staticmethod(desktop_icons_hidden)
    set_hidden = staticmethod(set_desktop_icons_hidden)
