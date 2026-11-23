"""M Panels — desktop shortcut panels (Fences-like). Design: docs/PLAN.md

Each panel = a Desktop\\Paneller\\<name> folder (the single source of truth). config.json only holds looks.
No permanent deletion: nothing in this program deletes files.

Run:        pythonw mpanels.py          (M-Panels.bat does this)
TEST mode:  python mpanels.py --desktop <test folder>     (never touches the real desktop)
"""
import argparse
import atexit
import copy
import ctypes
import ctypes.wintypes
import hashlib
import json
import logging
import math
from datetime import datetime
import os
import queue
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from tkinter import colorchooser, filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageTk

import applog
import backup
import calendar_panel
import changelog
import deskicons
import displays
import fileops
import richtext
import stack
import strings as ui
import theme
import uiwidgets
import winutil
from calendar_panel import settings as cal_settings
from theme import HEAD_H, KEY, KEY_RGB, RADIUS, blend, hex_rgb, make_bg, rgb_hex  # noqa: F401
from version import __version__

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except Exception:
    HAS_DND = False

try:
    import pystray
    HAS_TRAY = True
except Exception:
    HAS_TRAY = False

APP_NAME = ui.APP_NAME
HARD_EXIT_SECONDS = 5          # Quit watchdog: the process is force-ended if it is still alive after this
# Preset colors with their display names (the names live in strings.py, the hex values in theme.py)
PRESETS = [(ui.COLOR_NAMES[k], hexv) for k, hexv in theme.PRESETS]
APP_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(APP_DIR, "assets")

MIN_W, MIN_H = 150, HEAD_H + 80

# Factory values (color/font/metric values come from theme.py). defaults.json (gitignored) overrides them.
PANEL_FACTORY = {
    "color": theme.DEFAULT_COLOR, "opacity": theme.OPACITY, "icon_size": 32,
    **theme.style_defaults(),                    # title_* and content_* (title and content text are SEPARATE)
    "start_collapsed": False, "hover_open": False,
}
APPEARANCE_KEYS = list(PANEL_FACTORY)
LOG = applog.get_logger()
DISPLAY_POLL_MS = 2000      # how often the monitor layout is looked at (no window-message hook: nothing to crash silently)
DISPLAY_SETTLE_S = 3.0      # a changed layout must stay the same this long before panels are re-placed
GHOST_CANVAS = (8192, 4608)         # the preview canvas is larger than any screen; its window clips it
SNAPPING_KEY = "snapping"                        # defaults.json: snap_enabled / snap_distance / stack_gap (Make default)
CAL_LOOK_KEY = "calendar_look"                   # defaults.json: the user's default calendar look (see calendar_panel.settings.LOOK_KEYS)
PANEL_STATE = {"x": 80, "y": 80, "w": 380, "h": 280, "collapsed": False, "order": [], "specials": [],
               "type": "shortcut"}
ICON_MIN, ICON_MAX, ICON_DEFAULT = 16, 128, 32
CAL_PANEL_SIZE = (380, 460)        # size of a new calendar panel (w, h)
SAVE_DELAY = 600                   # autosave delay (ms) after typing stops in a note panel


def normalize_icon_size(v):
    """Convert an old/broken config value to an integer of 16–128 px (the old 24/32/48 are already pixels).
    An unreadable value (text, empty, None, bool) becomes 32."""
    if isinstance(v, bool) or v is None:
        return ICON_DEFAULT
    try:
        n = int(round(float(str(v).strip().replace(",", "."))))
    except (ValueError, TypeError, OverflowError):
        return ICON_DEFAULT
    return max(ICON_MIN, min(ICON_MAX, n))


# ------------------------------------------------------------------ helpers
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)        # config write: never leave a half-written file
    except Exception:
        pass


def wrap2(text, font, maxw):
    """At most two lines; if it does not fit, the second line ends with '…'."""
    if font.measure(text) <= maxw:
        return text
    words, line1, i = text.split(" "), "", 0
    while i < len(words) and font.measure((line1 + " " + words[i]).strip()) <= maxw:
        line1 = (line1 + " " + words[i]).strip()
        i += 1
    if not line1:
        k = len(text)
        while k > 1 and font.measure(text[:k]) > maxw:
            k -= 1
        line1, rest = text[:k], text[k:]
    else:
        rest = " ".join(words[i:])
    l2 = rest
    if font.measure(l2) > maxw:
        while l2 and font.measure(l2 + "…") > maxw:
            l2 = l2[:-1]
        l2 += "…"
    return line1 + "\n" + l2


def virtual_screen():
    """(x, y, w, h) of all monitors together; comes from the displays layer (the one place that knows the screens)."""
    try:
        return displays.virtual_bounds(displays.snapshot())
    except Exception:                                       # noqa: BLE001
        u = ctypes.windll.user32
        return u.GetSystemMetrics(76), u.GetSystemMetrics(77), u.GetSystemMetrics(78), u.GetSystemMetrics(79)


def _ico_frame(path, size):
    """The frame of an .ico closest to `size` (preferring a larger one), resized to size x size."""
    with Image.open(path) as im:
        sizes = sorted(im.info.get("sizes") or {im.size})
        best = next((s for s in sizes if s[0] >= size), sizes[-1])
        im.size = best
        im.load()
        return im.convert("RGBA").resize((size, size), Image.LANCZOS)


def app_icon_image(size):
    """The app icon (tray, windows): assets/m_panels.ico, else assets/m_panels.png,
    else a drawn placeholder. A missing or broken file never raises."""
    path = winutil.app_icon_path()
    if path:
        try:
            return _ico_frame(path, size)
        except Exception:
            pass
    try:
        return Image.open(os.path.join(ASSETS, "m_panels.png")).convert("RGBA").resize((size, size), Image.LANCZOS)
    except Exception:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 4, fill=theme.APP_ICON_BG_RGBA,
                            outline=theme.APP_ICON_EDGE_RGBA, width=max(1, size // 16))
        return img


# ------------------------------------------------------------------ folder watching
class Watcher(threading.Thread):
    """Watches the panel folders with FindFirstChangeNotification and queues a change event."""

    def __init__(self, put):
        super().__init__(daemon=True)
        self.put = put
        self.paths = {}            # folder path -> label
        self.dirty = True
        self.stop_flag = False
        self.lock = threading.Lock()

    def set_paths(self, paths):
        with self.lock:
            if paths != self.paths:
                self.paths = dict(paths)
                self.dirty = True

    def run(self):
        import win32con
        import win32event
        import win32file
        handles, labels = [], []
        flags = (win32con.FILE_NOTIFY_CHANGE_FILE_NAME | win32con.FILE_NOTIFY_CHANGE_DIR_NAME |
                 win32con.FILE_NOTIFY_CHANGE_LAST_WRITE)
        while not self.stop_flag:
            if self.dirty:
                for h in handles:
                    try:
                        win32file.FindCloseChangeNotification(h)
                    except Exception:
                        pass
                handles, labels = [], []
                with self.lock:
                    paths, self.dirty = dict(self.paths), False
                for p, label in paths.items():
                    try:
                        handles.append(win32file.FindFirstChangeNotification(p, False, flags))
                        labels.append(label)
                    except Exception:
                        pass
            if not handles:
                win32event.WaitForSingleObject(win32event.CreateEvent(None, 0, 0, None), 500)
                continue
            r = win32event.WaitForMultipleObjects(handles, False, 700)
            if win32event.WAIT_OBJECT_0 <= r < win32event.WAIT_OBJECT_0 + len(handles):
                i = r - win32event.WAIT_OBJECT_0
                self.put(("fs", labels[i]))
                try:
                    win32file.FindNextChangeNotification(handles[i])
                except Exception:
                    self.dirty = True


# ------------------------------------------------------------------ panel window
class PanelWin:
    def __init__(self, app, name):
        self.app, self.name = app, name
        self.cfg = app.panel_cfg(name)
        self.is_note = self.cfg["type"] == "note"
        self.is_calendar = self.cfg["type"] == "calendar"
        self.folder = None if (self.is_note or self.is_calendar) else app.ctx.panel_path(name)
        self.cal = self.model = self.cal_cv = None      # calendar panel: view, data model, content canvas
        self._cal_job = None
        self._cal_minute = None
        self.text = None            # the note panel's text box
        self._save_job = None
        self._saved_sig = ""        # the last note written to disk (JSON text)
        self.rich = None
        self.items = []
        self.icon_keys = {}
        self.photos = {}            # cache
        self.keep = []              # PhotoImage references
        self.rects = []             # (x0,y0,x1,y1,idx)
        self.scroll = 0
        self.sel = None
        self.hover = None
        self.press = None
        self.dragging = False
        self.ghost = None
        self.resizing = False
        self.moving = None
        self.expanded = not self.cfg["collapsed"]
        self.hover_opened = False
        self._leave_job = None
        self._anim = None
        self._bg_key = None
        self._aborted = False           # Esc during this drag: everything was put back; moves and the release do nothing
        self._undo = None           # layout snapshot taken at the press (what Esc restores)
        self._esc_job = None
        self._held = False          # a stack member being dragged that has not yet left its stack
        self._slot = None           # ... and the place it came from
        self._shown_xy = None       # where a stack member's window was last put (skip needless moves)
        self.fonts = {}

        self.top = tk.Toplevel(app.root)
        self.top.overrideredirect(True)
        self.top.configure(bg=KEY)
        self.top.attributes("-transparentcolor", KEY)
        self.head_h = self.calc_head_h()
        self.head = tk.Canvas(self.top, height=self.head_h, bg=KEY, highlightthickness=0, bd=0)
        self.body = tk.Canvas(self.top, bg=KEY, highlightthickness=0, bd=0)
        if self.is_note:
            self._make_text()
        if self.is_calendar:
            self._make_calendar()
        self._bind()
        self.apply_cfg(first=True)
        self.top.after(120, lambda: winutil.make_toolwindow(self.top, bottom=True))

    # ------------------------------------------------------------ events
    def _bind(self):
        h, b, t = self.head, self.body, self.top
        h.bind("<ButtonPress-1>", self._head_press)
        h.bind("<B1-Motion>", self._head_motion)
        h.bind("<ButtonRelease-1>", self._head_release)
        h.bind("<Double-Button-1>", lambda e: self.toggle())
        h.bind("<Button-3>", lambda e: self.panel_menu(e.x_root, e.y_root))
        if self.is_calendar:                       # hovering the title shows the refresh status
            h.bind("<Motion>", self._head_hover)
            h.bind("<Leave>", lambda e: self.cal.hide_tip() if self.cal else None)
        b.bind("<ButtonPress-1>", self._body_press)
        b.bind("<B1-Motion>", self._body_drag)
        b.bind("<ButtonRelease-1>", self._body_release)
        b.bind("<Double-Button-1>", self._body_double)
        b.bind("<Motion>", self._body_hover)
        b.bind("<Leave>", lambda e: self._set_hover(None))
        b.bind("<Button-3>", self._body_right)
        b.bind("<MouseWheel>", self._wheel)
        t.bind("<Enter>", self._enter)
        t.bind("<Leave>", self._leave)
        if HAS_DND and self.folder is not None:     # no file dropping on note/calendar panels
            for c in (h, b):
                c.drop_target_register(DND_FILES)
                c.dnd_bind("<<DropEnter>>", self._drop_enter)
                c.dnd_bind("<<DropLeave>>", self._drop_leave)
                c.dnd_bind("<<Drop>>", self._drop)

    def _enter(self, e):
        if self._leave_job:
            self.top.after_cancel(self._leave_job)
            self._leave_job = None
        if self.cfg["hover_open"] and self.cfg["collapsed"] and not self.expanded:
            self.hover_opened = True
            self.set_expanded(True)

    def _leave(self, e):
        if self.hover_opened and not self.app.busy:
            self._leave_job = self.top.after(500, self._maybe_close_hover)
        self.top.after(350, lambda: self.app.sink_if_idle(self))

    def _maybe_close_hover(self):
        self._leave_job = None
        px, py = self.top.winfo_pointerxy()
        x0, y0 = self.top.winfo_rootx(), self.top.winfo_rooty()
        inside = x0 <= px < x0 + self.top.winfo_width() and y0 <= py < y0 + self.top.winfo_height()
        if self.hover_opened and not inside and not self.app.busy:
            self.hover_opened = False
            self.set_expanded(False)

    # --- drag and drop (from Explorer)
    def _drop_enter(self, e):
        self.body.configure(highlightthickness=2, highlightbackground=theme.DROP_HIGHLIGHT)
        return e.action

    def _drop_leave(self, e):
        self.body.configure(highlightthickness=0)
        return e.action

    def _drop(self, e):
        self.body.configure(highlightthickness=0)
        try:
            paths = list(self.top.tk.splitlist(e.data))
        except Exception:
            paths = [e.data]
        self.app.drop_paths(self, paths)
        return e.action

    # --- header
    def _head_hover(self, e):
        text = self.cal.status_text() if self.cal and not self.moving else ""
        if text:
            self.cal.show_tip(text, e.x_root, e.y_root)
        elif self.cal:
            self.cal.hide_tip()

    def _head_press(self, e):
        if self.cal:
            self.cal.hide_tip()
        if self.moving and self.moving[3]:                  # the state of an earlier drag must never reach this click
            LOG.warning("press while an earlier drag was still open (release lost): finishing it first, panel=%s", self.name)
            self._end_drag(e.x_root, e.y_root, e.x, lost=True)
        self.moving = (e.x_root - self.cfg["x"], e.y_root - self.cfg["y"], e.x, False)
        self._aborted = False
        self._undo = self.app.snapshot_layout()
        self.app.clear_drag_plan()
        LOG.info("drag press panel=%s xy=%s,%s moving=on", self.name, e.x_root, e.y_root)

    def cancel_drag(self):
        """Esc while dragging (like Windows): the move is cancelled completely. The preview goes and the layout taken
        at the press (this panel, everything that moves with it, the stacks) is put back exactly. The button may
        still be down: further moves and the release then do nothing."""
        if self._aborted or not self.moving:
            return
        self._aborted = True
        LOG.info("drag cancelled with Esc: restoring the layout of the press, panel=%s", self.name)
        self.app.clear_drag_plan()
        self.app.hide_preview()
        if self._undo is not None:
            self.app.restore_layout(self._undo)
        self._held, self._slot = False, None

    def _esc_check(self):
        """Every 40 ms while dragging: Esc cancels the snap; and a left button that is no longer down means the
        release never reached us (safety net): the drag ends the normal way, with the stored candidate."""
        self._esc_job = None
        if not self.moving:
            return
        if self.moving[3] and not winutil.lbutton_down():
            px, py = self.top.winfo_pointerxy()
            LOG.warning("button already up while dragging (release lost): ending the drag, panel=%s", self.name)
            return self._end_drag(px, py, self.moving[2], lost=True)
        if not self._aborted and winutil.esc_down():
            self.cancel_drag()
        self._esc_job = self.top.after(40, self._esc_check)

    def _move_to(self, x, y):
        """Put the window at x,y and remember it: _shown_xy is ALWAYS where the window really is (relayout skips a
        move only when the window already sits at the target)."""
        self.top.geometry(f"+{int(x)}+{int(y)}")
        self._shown_xy = (int(x), int(y))

    def _head_motion(self, e):
        if not self.moving:
            return
        ox, oy, _, was_moving = self.moving
        if self._aborted:                                 # cancelled with Esc: the panel stays where it was put back
            return
        if was_moving and not winutil.lbutton_down():     # safety net: the button is up, the release got lost
            LOG.warning("motion with the button up (release lost): ending the drag, panel=%s", self.name)
            return self._end_drag(e.x_root, e.y_root, e.x, lost=True)
        self.moving = (ox, oy, self.moving[2], True)
        if self.app.locked:                       # locked: the panel does not move
            return
        if not was_moving:
            LOG.info("drag start panel=%s held-check follows", self.name)
            self.app.begin_drag(self)             # a middle/bottom member is "held" until it is pulled out of its slot
            if self._esc_job is None:
                self._esc_job = self.top.after(40, self._esc_check)
        self.cfg["x"], self.cfg["y"] = e.x_root - ox, e.y_root - oy
        self._move_to(self.cfg["x"], self.cfg["y"])
        if self._held:
            self.app.check_pulled_out(self)
        else:
            self.app.stack_changed(self)          # a stack top takes its stack along
        self.app.update_preview(self)             # where it would snap if dropped now

    def _head_release(self, e):
        LOG.info("release panel=%s xy=%s,%s moving_was=%s", self.name, e.x_root, e.y_root, "on" if self.moving else "off")
        self._end_drag(e.x_root, e.y_root, e.x)

    def _end_drag(self, xr, yr, ex, lost=False):
        """THE end of a header press (a real release, or the safety net). The drag state is always cleared here.
        The drop applies exactly the candidate the last motion computed (and the preview showed); only then the
        preview goes. Esc / locked / snapping off = no candidate."""
        m, self.moving = self.moving, None
        if self._esc_job is not None:
            self.top.after_cancel(self._esc_job)
            self._esc_job = None
        g = self.app.cfg["general"]
        stored = self.app._drag_plan
        LOG.info("drop decision: lost_release=%s cancelled=%s locked=%s snap_enabled=%s snap_preview=%s candidate=%s "
                 "preview_shown=%s event_xy=%s,%s panel_rect=%s", lost, self._aborted, self.app.locked,
                 g["snap_enabled"], g["snap_preview"], stored[1]["res"] if stored and stored[1] else None,
                 self.app._preview_shown and self.app._preview_shown["rects"], xr, yr,
                 (int(self.cfg["x"]), int(self.cfg["y"]), self.cur_w, self.cur_h))
        try:
            if not m or self._aborted:
                return                                # Esc already restored everything: the release does nothing
            if m[3]:
                if not self.app.locked:
                    if self._held:                    # dropped within snap_distance of its slot: back into place
                        self.app.return_to_slot(self)
                    else:
                        # the candidate comes BEFORE the clamp (a clamp would move the panel and the drop would no
                        # longer match the preview); the clamp only runs when nothing snapped
                        if not self.app.apply_drag_plan(self):
                            self.clamp()
                    self.app.commit_home(self)    # the drop is the user's act: where it ended is the new HOME
                    self.app.save()
            else:
                w = self.top.winfo_width()
                if ex >= w - 32:
                    self.panel_menu(xr, yr)
                elif ex <= 28:
                    self.toggle()
        finally:
            self.app.clear_drag_plan()
            self.app.hide_preview()                   # only after the decision has been applied

    # --- body
    def _in_grip(self, x, y):
        return (self.expanded and not self.app.locked) and x >= self.body.winfo_width() - 18 and y >= self.body.winfo_height() - 18

    def _hit(self, x, y):
        for x0, y0, x1, y1, i in self.rects:
            if x0 <= x < x1 and y0 <= y < y1:
                return i
        return None

    def _body_press(self, e):
        if self._in_grip(e.x, e.y):
            self.resizing = True
            self.press = (e.x_root, e.y_root, None)
            return
        if self.is_calendar:
            if self.cal is not None:
                self.cal.nav_click(e.x, e.y)
            return
        i = self._hit(e.x, e.y)
        self.sel = i
        self.press = (e.x_root, e.y_root, i)
        self.dragging = False
        self.draw_body()

    def _body_drag(self, e):
        if self.resizing:
            w = max(MIN_W, self.cfg["w"] + e.x_root - self.press[0])
            h = max(MIN_H, self.cfg["h"] + e.y_root - self.press[1])
            self.press = (e.x_root, e.y_root, None)
            self.cfg["w"], self.cfg["h"] = w, h
            self.remember_width()
            self.app.set_stack_width(self, w)
            self.apply_size(w, h)
            return
        if self.press and self.press[2] is not None and self.press[2] < len(self.items):
            if not self.dragging and abs(e.x_root - self.press[0]) + abs(e.y_root - self.press[1]) > 8:
                self.dragging = True
                self._make_ghost(self.items[self.press[2]])
            if self.dragging and self.ghost:
                self.ghost.geometry(f"+{e.x_root + 6}+{e.y_root + 6}")

    def _body_release(self, e):
        if self.resizing:
            self.resizing = False
            self.press = None
            self.app.save()
            return
        if self.dragging:
            self.dragging = False
            if self.ghost:
                self.ghost.destroy()
                self.ghost = None
            if self.press and self.press[2] is not None and self.press[2] < len(self.items):
                self.app.finish_item_drag(self, self.items[self.press[2]], e.x_root, e.y_root)
        self.press = None

    def _make_ghost(self, item):
        g = tk.Toplevel(self.top)
        g.overrideredirect(True)
        g.attributes("-topmost", True)
        g.attributes("-alpha", 0.8)
        ph = self.icon_photo(item)
        lbl = tk.Label(g, image=ph, bd=0)
        lbl.image = ph
        lbl.pack()
        self.ghost = g

    def _body_hover(self, e):
        self.body.configure(cursor="size_nw_se" if self._in_grip(e.x, e.y) else "")
        self._set_hover(self._hit(e.x, e.y))

    def _set_hover(self, i):
        if i != self.hover:
            self.hover = i
            self.draw_body()

    def _body_double(self, e):
        i = self._hit(e.x, e.y)
        if i is not None:
            self.app.open_item(self.items[i])

    def _body_right(self, e):
        i = self._hit(e.x, e.y)
        if i is None:
            self.panel_menu(e.x_root, e.y_root)
        else:
            self.sel = i
            self.draw_body()
            self.item_menu(self.items[i], e.x_root, e.y_root)

    def _wheel(self, e):
        if self.is_calendar:
            if self.cal is not None:
                self.cal.scroll_by(-(e.delta // 120) * 40)
            return
        self.scroll = self.scroll - (e.delta // 120) * 40
        self.draw_body()

    # ------------------------------------------------------------ menus
    def item_menu(self, item, x, y):
        a = self.app
        m = tk.Menu(self.top, tearoff=0)
        m.add_command(label=ui.ITEM_OPEN, command=lambda: a.open_item(item))
        if not item.special:
            m.add_command(label=ui.ITEM_OPEN_LOCATION, command=lambda: a.reveal_item(item))
            m.add_command(label=ui.ITEM_RENAME, command=lambda: a.rename_item(self, item))
            m.add_command(label=ui.ITEM_RETURN, command=lambda: a.return_item(self, item))
        else:
            m.add_command(label=ui.ITEM_REMOVE_SPECIAL, command=lambda: a.toggle_special(self, item.special))
        m.add_separator()
        m.add_command(label=ui.ITEM_MOVE_LEFT, command=lambda: a.move_in_order(self, item, -1))
        m.add_command(label=ui.ITEM_MOVE_RIGHT, command=lambda: a.move_in_order(self, item, +1))
        a.popup(m, x, y)

    def build_menu(self):
        """Right-click menu, grouped by command (separators between groups):
        New panel / Rename | Color / Opacity | Title text / Content text |
        [Items: Sort A–Z, Recycle Bin — shortcut panels only] | Settings | Remove panel | Collapse/Expand"""
        a = self.app
        m = tk.Menu(self.top, tearoff=0)
        m.add_command(label=ui.MENU_NEW_PANEL, command=a.new_panel)
        m.add_command(label=ui.MENU_RENAME, command=lambda: a.rename_panel(self))
        m.add_separator()
        cm = tk.Menu(m, tearoff=0)
        for n, c in PRESETS:
            cm.add_command(label=n, command=lambda c=c: self.set_color(c))
        cm.add_separator()
        cm.add_command(label=ui.MENU_CUSTOM_COLOR, command=self.pick_color)
        m.add_cascade(label=ui.MENU_COLOR, menu=cm)
        om = tk.Menu(m, tearoff=0)
        for p in (100, 90, 80, 70, 60, 50):
            om.add_command(label=f"%{p}", command=lambda p=p: self.set_opacity(p / 100))
        m.add_cascade(label=ui.MENU_OPACITY, menu=om)
        m.add_separator()
        m.add_command(label=ui.MENU_TITLE_TEXT, command=lambda: a.edit_style(self, "title"))
        m.add_command(label=ui.MENU_CONTENT_TEXT, command=lambda: a.edit_style(self, "content"))
        m.add_separator()
        if self.folder is not None:
            m.add_command(label=ui.MENU_SORT_AZ, command=lambda: a.sort_az(self))
            has_bin = "recycle" in self.cfg["specials"]
            m.add_command(label=ui.MENU_RECYCLE_REMOVE if has_bin else ui.MENU_RECYCLE_ADD,
                          command=lambda: a.toggle_special(self, "recycle"))
            m.add_separator()
        if self.is_calendar:
            m.add_command(label=ui.MENU_CAL_REFRESH, command=self.cal_refresh)
            m.add_command(label=ui.MENU_CAL_OPEN_GOOGLE, command=self.cal_open_google)
            m.add_separator()
        m.add_command(label=ui.MENU_SETTINGS, command=lambda: a.open_settings(self.name))
        m.add_separator()
        m.add_command(label=ui.MENU_REMOVE_PANEL, command=lambda: a.remove_panel(self))
        m.add_separator()
        m.add_command(label=ui.MENU_COLLAPSE if self.expanded else ui.MENU_EXPAND, command=self.toggle)
        return m

    def panel_menu(self, x, y):
        self.app.popup(self.build_menu(), x, y)

    # ------------------------------------------------------------ look settings
    def set_color(self, c):
        self.cfg["color"] = c
        self.apply_cfg()
        self.app.save()

    def pick_color(self):
        self.app.busy += 1
        try:
            c = colorchooser.askcolor(color=self.cfg["color"], parent=self.top, title=ui.DLG_PANEL_COLOR)[1]
        finally:
            self.app.busy -= 1
        if c:
            self.set_color(c)

    def set_opacity(self, v):
        self.cfg["opacity"] = v
        self.top.attributes("-alpha", v)
        self.app.save()

    def font(self, role="content"):
        """role: 'title' | 'content' — title and content text are set SEPARATELY."""
        st = theme.style_of(self.cfg, role)
        key = (role, st["font"], st["size"], st["bold"], st["italic"])
        if key not in self.fonts:
            self.fonts[key] = tkfont.Font(family=st["font"], size=int(st["size"]),
                                          weight="bold" if st["bold"] else "normal",
                                          slant="italic" if st["italic"] else "roman")
        return self.fonts[key]

    def calc_head_h(self):
        """Header bar height: at least theme.HEAD_H; grows with the text for a large title font."""
        return max(HEAD_H, int(self.font("title").metrics("linespace")) + theme.HEAD_PAD)

    def apply_cfg(self, first=False):
        self.fonts = {}
        self.head_h = self.calc_head_h()
        self.head.configure(height=self.head_h)
        self.photos = {}
        self._bg_key = None
        self.top.attributes("-alpha", float(self.cfg["opacity"]))
        self.reload_items(draw=False)
        self.style_text()
        w, h = self.target_width(), int(self.cfg["h"])
        self.cfg["w"] = w
        self.apply_size(w, h if self.expanded else self.head_h, first=first)

    def target_width(self):
        """THE place that decides the panel's width. A free calendar panel uses the width remembered for its
        current view (when there is one); every other panel uses its own width. (v1.2+: a panel inside a stack
        will take the stack width here.)"""
        sw = self.app.stack_width(self.name)
        if sw is not None:                               # in a stack: the stack width wins (widths are kept, not used)
            return sw
        if self.is_calendar:
            n = self.cfg["calendar"]["widths"].get(self.cfg["calendar"]["view"])
            if n:
                return int(n)
        return int(self.cfg["w"])

    def remember_width(self):
        """The user resized the panel: a calendar panel remembers this width for its current view."""
        if self.is_calendar and not self.in_stack():
            s = self.cfg["calendar"]
            s["widths"][s["view"]] = int(self.cfg["w"])

    def in_stack(self):
        return self.app.stack_pos(self.name) is not None

    def refresh_width(self):
        """Take the width this panel should have now (after leaving a stack a calendar returns to its own width)."""
        w = self.target_width()
        if w != int(self.cfg["w"]) or w != self.cur_w:
            self.cfg["w"] = w
            self.apply_size(w, self.cur_h)

    def cal_view_changed(self, old_view):
        """The calendar view changed (panel buttons or Settings > Apply): remember the width of the view we are
        leaving, then take the width of the new one (no record for it = keep the current width)."""
        s = self.cfg["calendar"]
        if old_view != s["view"] and old_view in cal_settings.VIEW_KEYS and not self.in_stack():
            s["widths"][old_view] = int(self.cfg["w"])
        w = self.target_width()
        if w != int(self.cfg["w"]):
            self.cfg["w"] = w
            self.apply_size(w, self.cur_h)              # the left edge stays; only the width changes
        else:
            self.draw_body()

    def clamp(self):
        """After a drop that did not snap: the head is pulled onto the monitor it is on (work area). Only the SHOWN
        place moves here; the caller makes it the new home (a drop is the user's act)."""
        self.cfg["x"], self.cfg["y"] = self.app.clamp_xy(self)
        self._move_to(self.cfg["x"], self.cfg["y"])
        self.app.stack_changed(self)

    def apply_size(self, w, h, first=False):
        """Set the window size and background (h = the currently visible height)."""
        self.cur_w, self.cur_h = w, h
        pos = self.app.stack_pos(self.name)
        if first and (pos is None or pos[1] == 0):          # free panels and stack tops (members follow the top)
            self.app.adopt_home(self)                       # SHOWN place from the HOME; the home itself is not touched
        self.top.geometry(f"{w}x{h}+{self.cfg['x']}+{self.cfg['y']}")
        self._shown_xy = (int(self.cfg["x"]), int(self.cfg["y"]))
        self.head.place(x=0, y=0, width=w, height=self.head_h)
        if h > self.head_h:
            self.body.place(x=0, y=self.head_h, width=w, height=h - self.head_h)
        else:
            self.body.place_forget()
        if self.text is not None:
            if h > self.head_h + 40:
                self.text.place(x=8, y=self.head_h + 6, width=max(20, w - 16), height=max(20, h - self.head_h - 6 - 22))
            else:
                self.text.place_forget()
        if self.cal_cv is not None:
            nav, foot = self.cal.nav_height(), self.cal.foot_height()
            ch = h - self.head_h - nav - foot
            if ch > 20:
                self.cal_cv.place(x=0, y=self.head_h + nav, width=w, height=ch)
            else:
                self.cal_cv.place_forget()
        key = (w, h, self.cfg["color"], self.head_h)
        if key != self._bg_key:
            bg = make_bg(w, h, self.cfg["color"])
            self.bg_head = ImageTk.PhotoImage(bg.crop((0, 0, w, min(h, self.head_h))))
            self.bg_body = ImageTk.PhotoImage(bg.crop((0, self.head_h, w, h))) if h > self.head_h else None
            self._bg_key = key
        self.draw_head()
        self.draw_body()
        self.app.stack_changed(self)                        # panels below this one in a stack follow (every frame)

    # ------------------------------------------------------------ expand/collapse
    def toggle(self):
        self.hover_opened = False
        self.cfg["collapsed"] = self.expanded          # if it is open it is about to collapse
        self.set_expanded(not self.expanded)
        self.app.save()

    def set_expanded(self, on):
        if on == self.expanded and self._anim is None:
            return
        self.expanded = on
        full = int(self.cfg["h"])
        a, b = self.cur_h, (full if on else self.head_h)
        steps = 7
        if self._anim:
            self.top.after_cancel(self._anim)
        def step(i):
            h = round(a + (b - a) * i / steps)
            self.apply_size(self.cur_w, max(self.head_h, h))
            self._anim = self.top.after(14, lambda: step(i + 1)) if i < steps else None
        step(1)

    # ------------------------------------------------------------ contents
    def reload_items(self, draw=True):
        if self.is_note or self.is_calendar:
            self.items, self.icon_keys = [], {}
            if draw:
                self.draw_body()
            return
        items = fileops.list_items(self.folder, self.cfg["order"])
        if "recycle" in self.cfg["specials"]:
            items.append(fileops.Item(ui.RECYCLE_BIN_ITEM, "shell:RecycleBinFolder", False, False,
                                      special="recycle"))
        self.items = items
        self.icon_keys = {}
        for it in items:
            self.icon_keys[it.path] = (winutil.recycle_bin_key() if it.special
                                       else winutil.shell_icon_key(it.path))
        if self.sel is not None and self.sel >= len(items):
            self.sel = None
        if draw:
            self.draw_body()

    def icon_photo(self, item):
        size = normalize_icon_size(self.cfg["icon_size"])
        key = (self.icon_keys.get(item.path, -1), size, item.broken, item.special)
        ph = self.photos.get(key)
        if ph is None:
            img = winutil.recycle_bin_icon(size) if item.special else winutil.file_icon(item.path, size)
            if img is None:
                img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                ImageDraw.Draw(img).rounded_rectangle((3, 3, size - 4, size - 4), radius=5,
                                                      fill=theme.ICON_FALLBACK_RGBA)
            if item.broken:
                img = img.copy()
                img.putalpha(img.getchannel("A").point(lambda v: int(v * 0.35)))
            ph = ImageTk.PhotoImage(img)
            self.photos[key] = ph
        return ph

    def metrics(self):
        icon = normalize_icon_size(self.cfg["icon_size"])
        f = self.font()
        cw = max(icon + 26, f.measure("M" * 8) + 8)
        ch = icon + 10 + 2 * f.metrics("linespace") + 10
        return cw, ch

    def draw_head(self):
        c, w = self.head, self.cur_w
        c.delete("all")
        c.create_image(0, 0, image=self.bg_head, anchor="nw")
        col, txt = self.cfg["color"], self.cfg["title_color"]
        bright = blend(col, theme.WHITE, theme.BRIGHT_MIX)
        c.create_text(16, self.head_h // 2 + 1, text="▾" if self.expanded else "▸", fill=bright,
                      font=theme.HEAD_GLYPH_FONT, anchor="center")
        title = self.name + (f"  {ui.TEST_TAG}" if self.app.test_mode else "")
        f = self.font("title")
        maxw = w - 70
        while len(title) > 1 and f.measure(title) > maxw:
            title = title[:-2] + "…"
        c.create_text(30, self.head_h // 2 + 1, text=title, fill=txt, font=f, anchor="w")
        c.create_text(w - 17, self.head_h // 2 - 1, text="⋯", fill=bright, font=theme.HEAD_MENU_FONT,
                      anchor="center")

    def draw_body(self):
        b = self.body
        if not self.expanded and self.cur_h <= self.head_h:
            return
        b.delete("all")
        w, h = self.cur_w, self.cur_h - self.head_h
        if h <= 0 or self.bg_body is None:
            return
        b.create_image(0, 0, image=self.bg_body, anchor="nw")
        self.keep = []
        self.rects = []
        if self.is_note:
            self._draw_grip(b, w, h)
            return
        if self.is_calendar:
            self._draw_calendar(b, w, h)
            return
        pad = 8
        cw, ch = self.metrics()
        cols = max(1, (w - 2 * pad) // cw)
        rows = (len(self.items) + cols - 1) // cols
        total = rows * ch + 2 * pad
        self.scroll = max(0, min(self.scroll, max(0, total - h)))
        f = self.font("content")
        col, txt = self.cfg["color"], self.cfg["content_color"]
        hl = blend(theme.EDGE_HEX, col, theme.HILITE_MIX)
        sel = blend(theme.EDGE_HEX, col, theme.SELECT_MIX)
        margin = (w - 2 * pad - cols * cw) // 2 if cols * cw < w - 2 * pad else 0
        for i, it in enumerate(self.items):
            r, cidx = divmod(i, cols)
            x0 = pad + margin + cidx * cw
            y0 = pad + r * ch - self.scroll
            if y0 + ch < 0 or y0 > h:
                continue
            self.rects.append((x0, y0, x0 + cw, y0 + ch, i))
            if i == self.sel or i == self.hover:
                b.create_rectangle(x0 + 1, y0 + 1, x0 + cw - 2, y0 + ch - 2, fill=sel if i == self.sel else hl,
                                   outline="", tags="hl")
            ph = self.icon_photo(it)
            self.keep.append(ph)
            icon = normalize_icon_size(self.cfg["icon_size"])
            b.create_image(x0 + cw // 2, y0 + 6 + icon // 2, image=ph)
            tcol = blend(txt, theme.EDGE_HEX, theme.BROKEN_MIX) if it.broken else txt
            b.create_text(x0 + cw // 2, y0 + 6 + icon + 4, text=wrap2(it.name, f, cw - 6), fill=tcol,
                          font=f, anchor="n", justify="center")
        self._draw_grip(b, w, h)

    # ------------------------------------------------------------ calendar panel
    def cal_fonts(self):
        """tk fonts for the calendar views, derived from the panel's content text style."""
        st = theme.style_of(self.cfg, "content")
        key = ("cal", st["font"], st["size"], st["bold"], st["italic"])
        if key not in self.fonts:
            fam, size = st["font"], int(st["size"])

            def mk(sz, bold=False, italic=False):
                return tkfont.Font(family=fam, size=max(6, sz), weight="bold" if bold else "normal",
                                   slant="italic" if italic else "roman")
            self.fonts[key] = {"ev": mk(size, st["bold"], st["italic"]), "day": mk(size, True),
                               "small": mk(size - 1), "small_bold": mk(size - 1, True), "tiny": mk(size - 2)}
        return self.fonts[key]

    def cal_palette(self):
        from calendar_panel import view as cal_view
        return cal_view.make_palette(self.cfg["color"], self.cfg["content_color"], self.cfg["calendar"].get("colors"))

    def _make_calendar(self):
        if not calendar_panel.AVAILABLE:
            return                              # the panel stays; it shows a short message instead
        from calendar_panel import view as cal_view
        from calendar_panel.model import CalendarModel
        name = self.name
        self.model = CalendarModel(notify=lambda: self.app.q.put(("cal", name)))
        self.cal = cal_view.CalendarView(self, self.model)
        cv = self.cal_cv = tk.Canvas(self.top, bg=KEY, highlightthickness=0, bd=0)
        cv.bind("<MouseWheel>", self._wheel)
        cv.bind("<Button-3>", lambda e: self.panel_menu(e.x_root, e.y_root))
        cv.bind("<Motion>", self._cal_motion)
        cv.bind("<Leave>", lambda e: self.cal.hide_tip())
        # the content canvas covers the bottom-right corner, so it must carry the resize grip itself
        cv.bind("<ButtonPress-1>", self._cal_press)
        cv.bind("<B1-Motion>", self._body_drag)
        cv.bind("<ButtonRelease-1>", self._body_release)
        self.top.after(400, self.cal_refresh)
        self._schedule_cal_refresh()

    def _in_cal_grip(self, x, y):
        cv = self.cal_cv
        return (cv is not None and self.expanded and not self.app.locked
                and x >= cv.winfo_width() - 18 and y >= cv.winfo_height() - 18)

    def _cal_press(self, e):
        if self._in_cal_grip(e.x, e.y):
            self.resizing = True
            self.press = (e.x_root, e.y_root, None)

    def _cal_motion(self, e):
        self.cal_cv.configure(cursor="size_nw_se" if self._in_cal_grip(e.x, e.y) else "")
        text = self.cal.tip_at(e.x, e.y) if self.cal else None
        if text:
            self.cal.show_tip(text, e.x_root, e.y_root)
        else:
            self.cal.hide_tip()

    def cal_open_google(self):
        """Open Google Calendar in the default browser. A failure is only logged (the user sees nothing)."""
        try:
            if not webbrowser.open(ui.GOOGLE_CALENDAR_URL):
                applog.get_logger().warning("could not open Google Calendar: no browser accepted the request")
        except Exception as e:                      # noqa: BLE001 - must never crash the program
            applog.get_logger().warning("could not open Google Calendar: %s", e)

    def cal_refresh(self):
        """Refresh now (a background thread does the work)."""
        if self.model is None:
            return
        s = self.cfg["calendar"]
        self.model.refresh(s["calendars"])
        self.draw_body()

    def _schedule_cal_refresh(self):
        if self._cal_job:
            try:
                self.top.after_cancel(self._cal_job)
            except Exception:
                pass
        ms = int(self.cfg["calendar"]["refresh_minutes"]) * 60_000
        self._cal_job = self.top.after(ms, self._auto_cal_refresh)

    def _auto_cal_refresh(self):
        self.cal_refresh()
        self._schedule_cal_refresh()

    def cal_settings_changed(self):
        """After Settings › Apply: new source/selection/interval."""
        self.cfg["calendar"] = cal_settings.sanitize(self.cfg.get("calendar"))
        if self.cal is not None:
            self.cal.scroll = 0
        if self.model is not None:
            self._schedule_cal_refresh()
        self.cal_refresh()
        self.draw_body()

    def cal_tick(self):
        """Redraw once a minute (the 'now' line, past events fading)."""
        if self.cal is None or not self.expanded:
            return
        m = datetime.now().strftime("%Y%m%d%H%M")
        if m != self._cal_minute:
            self._cal_minute = m
            self.draw_body()

    def _draw_calendar(self, b, w, h):
        if self.cal is None:
            b.create_text(w // 2, h // 2, text=ui.CAL_ERR_LIBS, fill=theme.CAL_WARN, font=self.font("content"),
                          width=max(60, w - 30), justify="center")
            self._draw_grip(b, w, h)
            return
        nav, foot = self.cal.nav_height(), self.cal.foot_height()
        self.cal.draw_nav(b, w, 0)
        ch = h - nav - foot
        if ch > 20 and self.cal_cv is not None:
            self.cal.draw_content(self.cal_cv, w, ch, self.bg_body, nav)
        self._draw_grip(b, w, h)

    def _draw_grip(self, b, w, h):
        """Resize grip (not drawn while the panels are locked)."""
        if self.app.locked:
            return
        gx, gy = w - 5, h - 5
        for k in (4, 8, 12):
            b.create_line(gx - k, gy, gx, gy - k, fill=blend(self.cfg["color"], theme.WHITE, theme.GRIP_MIX))

    # ------------------------------------------------------------ note panel
    def base_style(self):
        """RichText's base font = the panel's content text."""
        return theme.style_of(self.cfg, "content")

    def _make_text(self):
        t = self.text = tk.Text(self.top, wrap="word", undo=True, bd=0, highlightthickness=0, relief="flat",
                                padx=6, pady=4)
        self.rich = richtext.RichText(t, self.base_style)
        self.style_text()
        nd = fileops.read_note(self.app.data_dir, self.name)
        self.rich.load(nd.text, nd.spans)
        self._saved_sig = fileops.note_payload(*self.rich.dump())
        msg = nd.warning or (ui.NOTE_IMPORTED.format(trash=f"{fileops.NOTES_DIRNAME}/{fileops.TRASH_DIRNAME}")
                             if nd.imported else "")
        if msg:
            self.top.after(700, lambda: self.top.winfo_exists() and self.app.flash(self, msg, error=bool(nd.warning)))
        t.bind("<<Modified>>", self._text_modified)
        t.bind("<Button-1>", lambda e: t.focus_force(), add="+")
        t.bind("<Button-3>", self._text_right)

    def style_text(self):
        if self.text is None:
            return
        st = theme.style_of(self.cfg, "content")
        col = self.cfg["color"]
        self.text.configure(bg=blend(theme.EDGE_HEX, col, theme.NOTE_BG_MIX), fg=st["color"], insertbackground=st["color"],
                            selectbackground=blend(theme.EDGE_HEX, col, theme.NOTE_SEL_MIX), selectforeground=theme.WHITE,
                            font=theme.tk_font_spec(st))
        self.rich.restyle()

    def _schedule_save(self):
        if self._save_job:
            self.top.after_cancel(self._save_job)
        self._save_job = self.top.after(SAVE_DELAY, self.save_note)

    def _text_modified(self, e=None):
        t = self.text
        if t is None or not t.edit_modified():
            return
        t.edit_modified(False)
        self._schedule_save()

    def save_note(self):
        """Save the note (text + formatting) now: autosave, closing, renaming. A Result or None."""
        if self._save_job:
            try:
                self.top.after_cancel(self._save_job)
            except Exception:
                pass
            self._save_job = None
        if self.text is None:
            return None
        text, spans = self.rich.dump()
        sig = fileops.note_payload(text, spans)
        if sig == self._saved_sig:           # compare the real content even if <<Modified>> has not been processed yet
            return None
        r = fileops.write_note(self.app.data_dir, self.name, text, spans)
        if r.ok:
            self._saved_sig = sig
        else:
            self.app.flash(self, r.message, error=True)
        return r

    # --- formatting of the selected text (right-click)
    def _text_right(self, e):
        if self.rich.selection():
            self.app.popup(self.build_format_menu(), e.x_root, e.y_root)
        else:
            self.panel_menu(e.x_root, e.y_root)
        return "break"

    def build_format_menu(self):
        m = tk.Menu(self.top, tearoff=0)
        m.add_command(label=ui.FMT_BOLD, command=lambda: self.format_op("bold"))
        m.add_command(label=ui.FMT_ITALIC, command=lambda: self.format_op("italic"))
        m.add_command(label=ui.FMT_UNDERLINE, command=lambda: self.format_op("underline"))
        m.add_separator()
        m.add_command(label=ui.FMT_COLOR, command=lambda: self.format_op("color"))
        m.add_command(label=ui.FMT_FONT, command=lambda: self.format_op("font"))
        sm = tk.Menu(m, tearoff=0)
        for n in (8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48, 72):
            sm.add_command(label=str(n), command=lambda n=n: self.format_op("size", n))
        sm.add_separator()
        sm.add_command(label=ui.FMT_SIZE_OTHER, command=lambda: self.format_op("size"))
        m.add_cascade(label=ui.FMT_SIZE, menu=sm)
        m.add_separator()
        m.add_command(label=ui.FMT_CLEAR, command=lambda: self.format_op("clear"))
        return m

    def format_op(self, op, value=None):
        """Apply formatting to the selected text and save the note. Returns whether it was applied."""
        r, t = self.rich, self.text
        sel = r.selection()
        if not sel:
            return False
        if op in ("bold", "italic", "underline"):
            ok = r.toggle(op)
        elif op == "clear":
            ok = r.clear_format()
        else:
            if op == "color":
                value = self.app.ask_color(self, self.cfg["content_color"])
            elif op == "font":
                value = value or self.app.ask_font(self.base_style()["font"], self.base_style()["size"])
            elif op == "size" and value is None:
                value = self.app.ask_size(self.base_style()["size"])
            if value is None:
                return False
            t.tag_remove("sel", "1.0", "end")          # restore the selection after the dialog
            t.tag_add("sel", f"1.0+{sel[0]}c", f"1.0+{sel[1]}c")
            ok = {"color": r.set_color, "font": r.set_font, "size": r.set_size}[op](value)
        if ok:
            self._schedule_save()
        return bool(ok)

    def destroy(self):
        if self.text is not None:
            self.save_note()
        if self.cal is not None:
            self.cal.hide_tip()
        for j in (self._anim, self._leave_job, self._cal_job):
            if j:
                try:
                    self.top.after_cancel(j)
                except Exception:
                    pass
        self.top.destroy()


# ------------------------------------------------------------------ application
class App:
    def __init__(self, ctx, data_dir, test_mode=False, use_tray=True, icon_backend=None, instance_name=None,
                 displays_provider=None, clock=None):
        self.ctx, self.test_mode = ctx, test_mode
        self.displays = displays_provider or displays.Displays()     # the screens (tests give a made-up layout)
        self.clock = clock or time.monotonic
        self._disp_applied = self._disp_seen = displays.signature(self.displays.monitors())
        self._disp_seen_at = self.clock()
        self._disp_warned = False
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.config_path = os.path.join(data_dir, "config.json")
        self.defaults_path = os.path.join(data_dir, "defaults.json")
        backup.make_backup(self.config_path)            # first thing after reading: before any placement, clamp or save
        self.cfg = load_json(self.config_path, {})
        g = self.cfg.setdefault("general", {})
        g.setdefault("autostart", True)
        g.setdefault("lock_panels", False)
        g.setdefault("hide_desktop_icons", False)
        g.setdefault("hide_icons_restore", None)
        stack.sanitize_general(g)                       # snap_distance, stack_gap, snap_enabled (v1.1 step 7a)
        self.cfg.setdefault("panels", {})
        self.cfg["stacks"] = self.cfg["stacks"] if isinstance(self.cfg.get("stacks"), list) else []
        self._relaying = False
        self._ghost = self._ghost_cv = None           # the snap preview window (created once, hidden when not needed)
        self._preview_key = self._preview_shown = None
        self._drag_plan = None                        # (panel name, drop_plan) the last motion computed: the ONE candidate
        # Desktop icons: NO backend in TEST mode (the real Explorer is never touched).
        backend = None if test_mode else (icon_backend or winutil.DesktopIconsBackend())
        self.icons = deskicons.IconHider(g, backend, self.save)
        self.panels = {}
        self.busy = 0                   # panels are not sent to the bottom while a menu/dialog is open
        self.q = queue.Queue()
        self.visible = True
        self.tray = None
        self._quitting = False
        self.hard_exit_s = None                # set by main(): last-resort os._exit watchdog
        self.settings_win = None
        self._fs_dirty = set()
        self._fs_job = None
        self._toast = None

        self.root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
        self.root.withdraw()
        self.root.title(APP_NAME)
        self.root.report_callback_exception = applog.tk_callback_handler(applog.get_logger())
        self.make_ghost()                              # the snap preview window: created once, now (hidden)
        self._icon = ImageTk.PhotoImage(app_icon_image(48))
        try:
            self.root.iconphoto(True, self._icon)
        except Exception:
            pass

        fileops.ensure_panels_root(ctx)
        if not fileops.list_panel_folders(ctx):
            fileops.create_panel(ctx, ui.DEFAULT_PANEL_NAME)
        self.watcher = Watcher(self.q.put)
        self.watcher.start()
        self.sync_panels()
        if use_tray:
            self._setup_tray()
        self._listener = winutil.start_instance_listener(instance_name, lambda: self.q.put(("cmd", "raise"))) \
            if instance_name else None
        self._quit_listener = winutil.start_instance_listener(instance_name, lambda: self.q.put(("cmd", "quit")),
                                                              winutil.QUIT) if instance_name else None
        self._poll()
        self.root.after(2000, self._tick)
        self.root.after(DISPLAY_POLL_MS, self._display_tick)
        self.root.after(700, self.migrate_calendar_sources)
        self.icons.startup()
        atexit.register(self.icons.on_quit)     # on a normal exit (tray Quit included) the icons return to normal

    @property
    def locked(self):
        return bool(self.cfg["general"].get("lock_panels"))

    def set_lock(self, on):
        self.cfg["general"]["lock_panels"] = bool(on)
        self.save()
        for p in self.panels.values():
            p.draw_body()

    # ------------------------------------------------------------ config
    def defaults(self, factory=False):
        d = copy.deepcopy(PANEL_FACTORY)
        if not factory:
            saved = load_json(self.defaults_path, {})
            if isinstance(saved, dict):
                theme.migrate_style(saved)               # old defaults.json: font_size/text_color
                d.update({k: v for k, v in saved.items() if k in PANEL_FACTORY})
        return theme.sanitize_style(d)

    def snapping_defaults(self, factory=False):
        """snap_enabled / snap_distance / stack_gap to start from: saved default (defaults.json > "snapping") or built-in."""
        saved = None
        if not factory:
            data = load_json(self.defaults_path, {})
            saved = data.get(SNAPPING_KEY) if isinstance(data, dict) else None
        d = stack.sanitize_general(dict(saved) if isinstance(saved, dict) else {})
        return {k: d[k] for k in stack.GENERAL_KEYS}

    def set_snapping(self, vals):
        """Apply snap_enabled / snap_distance / stack_gap (sanitized). A new gap re-stacks every stack from its top."""
        g = self.cfg["general"]
        old = dict(g)
        g.update({k: vals[k] for k in stack.GENERAL_KEYS if k in vals})
        stack.sanitize_general(g)
        if g["stack_gap"] != old.get("stack_gap"):
            self.relayout_all()
        if any(g[k] != old.get(k) for k in stack.GENERAL_KEYS):
            self.save()

    def calendar_look(self, factory=False):
        """The calendar look to start from: the user's saved default (defaults.json > "calendar_look"), or the
        built-in look (factory, or nothing/garbage saved). Always a complete, valid subset."""
        saved = None
        if not factory:
            data = load_json(self.defaults_path, {})
            saved = data.get(CAL_LOOK_KEY) if isinstance(data, dict) else None
        return cal_settings.look_of(saved)

    def save_defaults(self, **parts):
        """Write defaults.json keeping what is already there (appearance and calendar look are saved separately)."""
        data = load_json(self.defaults_path, {})
        data = data if isinstance(data, dict) else {}
        data.update(parts)
        save_json(self.defaults_path, data)

    def panel_cfg(self, name):
        c = self.cfg["panels"].get(name)
        if c is None:
            c = {**self.defaults(), **copy.deepcopy(PANEL_STATE)}
            n = len(self.cfg["panels"])
            c["x"], c["y"] = PANEL_STATE["x"] + 40 * n, PANEL_STATE["y"] + 40 * n
            c["collapsed"] = c["start_collapsed"]
            self.cfg["panels"][name] = c
        theme.migrate_style(c)           # old config: single font_size/text_color -> same value for title and content
        for k, v in {**PANEL_FACTORY, **PANEL_STATE}.items():
            c.setdefault(k, copy.deepcopy(v))
        theme.sanitize_style(c)
        c["icon_size"] = normalize_icon_size(c["icon_size"])     # old config value -> 16–128 px
        if c["type"] not in ("shortcut", "note", "calendar"):
            c["type"] = "shortcut"
        if c["type"] == "calendar":
            c["calendar"] = cal_settings.sanitize(c.get("calendar"))
        return c

    def save(self):
        save_json(self.config_path, self._file_cfg())

    def _file_cfg(self):
        """What goes to config.json. The file always holds the HOME place of every panel (where the user put it), never
        the place it is SHOWN at right now (that depends on the monitors that exist at the moment). Stack members are
        saved at their SETTLED place derived from the top's home (not mid-animation). The live cfg is not touched."""
        data = dict(self.cfg)
        settled = self._settled_stack_cfg()
        panels = {}
        for name, c in self.cfg["panels"].items():
            c2 = {k: v for k, v in c.items() if k != "_home"}
            if name in settled:
                c2["x"], c2["y"], c2["w"] = settled[name]
            elif c.get("_home"):
                c2["x"], c2["y"] = int(c["_home"][0]), int(c["_home"][1])
            panels[name] = c2
        data["panels"] = panels
        return data

    # ------------------------------------------------------------ monitors: home and shown place (v1.1 step 7c)
    # cfg["x"/"y"] of a panel is the place it is SHOWN at (what drag, relayout and snapping work with). Each free panel
    # and stack top ALSO has cfg["_home"] = (x, y): where the user put it, the only place saved to config.json (stack
    # members are derived from their top's home). cfg["mon"] = the rectangle of the monitor the home was on. The home
    # changes only by a user act (commit_home); opening, a display change and clamping only change the shown place.
    def monitors(self):
        return self.displays.monitors()

    def clamp_xy(self, p):
        return displays.clamp_head(self.monitors(), p.cfg["x"], p.cfg["y"], p.cfg["w"], p.head_h)

    def monitor_of(self, x, y):
        """An id (the rectangle) of the monitor that contains the point (the nearest one when outside). Overridable in tests."""
        return displays.monitor_at(self.monitors(), x, y)

    @staticmethod
    def _mon_cfg(c):
        m = c.get("mon")
        if isinstance(m, (list, tuple)) and len(m) == 4 and all(isinstance(v, int) and not isinstance(v, bool) for v in m) \
                and m[2] > m[0] and m[3] > m[1]:
            return tuple(m)
        return None

    def _home_xy(self, p):
        h = p.cfg.get("_home")
        return (int(h[0]), int(h[1])) if h else (int(p.cfg["x"]), int(p.cfg["y"]))

    def _show_home(self, p):
        """The shown place of a unit from its home and the monitors that exist now (displays.place). Home untouched."""
        hx, hy = self._home_xy(p)
        mons = self.monitors()
        r = displays.monitor_rect_of(mons, hx, hy, p.cfg["w"], p.head_h)
        if r:                                       # the home is on a monitor that exists: remember that monitor
            p.cfg["mon"] = list(r)
        p.cfg["x"], p.cfg["y"] = displays.place(mons, hx, hy, p.cfg["w"], p.head_h, self._mon_cfg(p.cfg))

    def adopt_home(self, p):
        """A panel window is created: its HOME is the saved x/y (an old config has nothing else: x/y = home) unless it
        already has one (rename); it is shown at the place the current monitors allow."""
        if "_home" not in p.cfg:
            p.cfg["_home"] = (int(p.cfg["x"]), int(p.cfg["y"]))
        if self._mon_cfg(p.cfg) is None:
            p.cfg.pop("mon", None)
        self._show_home(p)

    def set_home(self, p):
        """The user put this unit here: where it is shown now is its new home (and the monitor it is on)."""
        p.cfg["_home"] = (int(p.cfg["x"]), int(p.cfg["y"]))
        r = displays.monitor_rect_of(self.monitors(), p.cfg["x"], p.cfg["y"], p.cfg["w"], p.head_h)
        if r:
            p.cfg["mon"] = list(r)

    def commit_home(self, p):
        """A drop ended (user act). A free panel / stack top: its place is the new home. A stack member: derived."""
        pos = self.stack_pos(p.name)
        if pos is not None and pos[1] > 0:
            p.cfg.pop("_home", None)
        else:
            self.set_home(p)

    def _derived_homes(self):
        """name -> (x, y, mon) of every stack MEMBER: its place derived from its top's HOME (stacks whose top window
        exists). Taken before a panel is removed/renamed, so a member that becomes a top keeps its HOME, not the shifted
        place it is shown at."""
        out = {}
        stacks = self.cfg["stacks"]
        for si, names in enumerate(stacks):
            if not (isinstance(names, list) and names):
                continue
            ps = [self.panels.get(n) if isinstance(n, str) else None for n in names]
            if len(ps) < 2 or ps[0] is None or any(p is None for p in ps):
                continue
            hx, hy = self._home_xy(ps[0])
            ys = stack.positions(hy, [self._target_h(p) for p in ps], self.cfg["general"]["stack_gap"])
            for p, y in list(zip(ps, ys))[1:]:
                out[p.name] = (hx, y, ps[0].cfg.get("mon"))
        return out

    def ensure_homes(self, derived=None):
        """Members have no home of their own; every free panel / stack top has one. A panel that just became a top or
        free because its stack lost its top: its home is the place derived from the OLD top's home (`derived`), never
        the place it is shown at (that may be a shifted one while a monitor is missing)."""
        for p in self.panels.values():
            pos = self.stack_pos(p.name)
            if pos is not None and pos[1] > 0:
                p.cfg.pop("_home", None)
            elif "_home" not in p.cfg:
                d = (derived or {}).get(p.name)
                if d:
                    p.cfg["_home"] = (int(d[0]), int(d[1]))
                    if d[2]:
                        p.cfg["mon"] = list(d[2])
                    self._show_home(p)
                    p._move_to(p.cfg["x"], p.cfg["y"])
                else:
                    self.set_home(p)

    def relayout_displays(self):
        """The monitors changed (or the app starts): every free panel and stack top is shown where its home allows now;
        stacks follow their top. Homes are never touched, so a monitor that comes back gets its panels back."""
        for p in self.panels.values():
            pos = self.stack_pos(p.name)
            if (pos is not None and pos[1] > 0) or "_home" not in p.cfg:
                continue
            old = (int(p.cfg["x"]), int(p.cfg["y"]))
            self._show_home(p)
            if (int(p.cfg["x"]), int(p.cfg["y"])) != old or p._shown_xy != (int(p.cfg["x"]), int(p.cfg["y"])):
                p._move_to(p.cfg["x"], p.cfg["y"])
        self.relayout_all()

    def _display_tick(self):
        if self._quitting:
            return
        try:
            self._display_check()
        except Exception:                                   # noqa: BLE001
            LOG.exception("display check failed")
        self.root.after(DISPLAY_POLL_MS, self._display_tick)

    def _display_check(self):
        """Every DISPLAY_POLL_MS: has the monitor layout (monitors + work areas) changed? The new layout must stay the
        same for DISPLAY_SETTLE_S before the panels are re-placed (a monitor that sleeps drops out and comes back within
        seconds); never while a panel is being dragged (it waits for the drop). Returns True when it re-placed."""
        now = self.clock()
        probed = self.displays.probe()
        if probed is None:                                  # the system could not say: that is not 'monitors gone'
            if not self._disp_warned:
                self._disp_warned = True
                LOG.warning("monitor layout could not be read; keeping the last known one")
            return False
        self._disp_warned = False
        sig = displays.signature(probed)
        if sig != self._disp_seen:
            self._disp_seen, self._disp_seen_at = sig, now
        if sig == self._disp_applied or now - self._disp_seen_at < DISPLAY_SETTLE_S:
            return False
        if any(p.moving for p in self.panels.values()):
            return False
        self._disp_applied = sig
        self.displays.commit(probed)                        # only now do clamp / snapping / placement see the new layout
        LOG.info("display layout changed: %d monitor(s) %s", len(sig), [s[0] for s in sig])
        self.relayout_displays()
        return True

    # ------------------------------------------------------------ snapping and stacks (v1.1 step 7a; see docs/PLAN.md, step 7)
    def stack_pos(self, name):
        """(stack index, position) of a panel, or None."""
        return stack.find(self.cfg["stacks"], name)

    def stack_width(self, name):
        """The common width of the stack this panel is in (the stack top's width), or None when it is free."""
        pos = self.stack_pos(name)
        top = self.cfg["panels"].get(self.cfg["stacks"][pos[0]][0]) if pos else None
        return int(top["w"]) if top else None

    def _stack_panels(self, si):
        return [p for p in (self.panels.get(n) for n in self.cfg["stacks"][si]) if p is not None]

    @staticmethod
    def _target_h(p):
        return int(p.cfg["h"]) if p.expanded else p.head_h

    def _settled_stack_cfg(self):
        out = {}
        gap = self.cfg["general"]["stack_gap"]
        for si in range(len(self.cfg["stacks"])):
            ps = self._stack_panels(si)
            if len(ps) < 2:
                continue
            top = ps[0]
            hx, hy = self._home_xy(top)                 # the TOP's home decides; members are derived from it
            ys = stack.positions(hy, [self._target_h(p) for p in ps], gap)
            for p, y in list(zip(ps, ys))[1:]:
                out[p.name] = (hx, y, int(top.cfg["w"]))
        return out

    def stack_changed(self, panel):
        """A panel moved or changed height: the panels below it in its stack follow (called every animation frame)."""
        if self._relaying or self.panels.get(panel.name) is not panel:
            return
        pos = self.stack_pos(panel.name)
        if pos is not None:
            self.relayout(pos[0])

    def relayout_all(self):
        for si in range(len(self.cfg["stacks"])):
            self.relayout(si)

    def relayout(self, si):
        """Place every panel of a stack under the top: same left edge and width, `stack_gap` between them. The
        positions are always derived from the top and the current heights (never added up frame by frame)."""
        ps = self._stack_panels(si)
        if len(ps) < 2 or self._relaying:
            return
        gap = self.cfg["general"]["stack_gap"]
        top = ps[0]
        w, x = int(top.cfg["w"]), int(top.cfg["x"])
        y = int(top.cfg["y"]) + top.cur_h + gap
        self._relaying = True
        try:
            for p in ps[1:]:
                if p._held:                                  # being dragged: it keeps its slot in the chain only
                    y += p.cur_h + gap
                    continue
                p.cfg["x"], p.cfg["y"] = x, y
                if int(p.cfg["w"]) != w or p.cur_w != w:
                    p.cfg["w"] = w
                    p.apply_size(w, p.cur_h)             # also places the window
                    p._shown_xy = (x, y)
                elif p._shown_xy != (x, y):
                    p._move_to(x, y)
                y += p.cur_h + gap
        finally:
            self._relaying = False

    def set_stack_width(self, panel, w):
        """A panel in a stack was resized: the whole stack takes the new width."""
        pos = self.stack_pos(panel.name)
        if pos is None:
            return
        names = self.cfg["stacks"][pos[0]]
        self.cfg["panels"][names[0]]["w"] = w
        self._relaying = True
        try:
            for p in self._stack_panels(pos[0]):
                if p is not panel and (int(p.cfg["w"]) != w or p.cur_w != w):
                    p.cfg["w"] = w
                    p.apply_size(w, p.cur_h)
        finally:
            self._relaying = False

    def begin_drag(self, panel):
        """A header drag starts. A stack top is not held (the whole stack moves with it); a panel in the middle or at
        the bottom stays in its stack and is only HELD at its slot until it is pulled out (check_pulled_out)."""
        pos = self.stack_pos(panel.name)
        panel._held = pos is not None and pos[1] > 0
        panel._slot = (int(panel.cfg["x"]), int(panel.cfg["y"])) if panel._held else None

    def check_pulled_out(self, panel):
        """While dragging a held member: once it is more than snap_distance away from its slot it leaves the stack
        (the panels below close the gap and stay in the stack)."""
        sx, sy = panel._slot
        if math.hypot(panel.cfg["x"] - sx, panel.cfg["y"] - sy) <= self.cfg["general"]["snap_distance"]:
            return
        panel._held, panel._slot = False, None
        self.cfg["stacks"] = stack.remove(self.cfg["stacks"], panel.name)
        self.relayout_all()
        panel.refresh_width()

    def return_to_slot(self, panel):
        """A held member was dropped within snap_distance of its slot: it goes back, the stack is unchanged."""
        panel.cfg["x"], panel.cfg["y"] = panel._slot
        panel._held, panel._slot = False, None
        panel._move_to(panel.cfg["x"], panel.cfg["y"])
        self.relayout_all()

    def stack_monitor(self, name):
        """The monitor of a panel's stack = the monitor of the stack TOP (a free panel: its own). Step 7c builds on this."""
        pos = self.stack_pos(name)
        p = self.panels.get(self.cfg["stacks"][pos[0]][0] if pos else name)
        return self.monitor_of(int(p.cfg["x"]) + p.cur_w // 2, int(p.cfg["y"])) if p else 0

    def drop_plan(self, panel):
        """What dropping this panel here would do, or None: {"res": stack.choose_drop result, "rects": where the panel
        (or the whole stack) ends up, "edge": the target edge to highlight}. The preview and the drop both use it."""
        g = self.cfg["general"]
        if self.locked or not g["snap_enabled"]:
            return None
        stacks = self.cfg["stacks"]
        pos = self.stack_pos(panel.name)
        if pos is not None and pos[1] != 0:                    # only a stack TOP can be dropped (others are held/detached)
            return None
        own = set(stacks[pos[0]]) if pos else {panel.name}

        def rect(p):
            return (p.name, int(p.cfg["x"]), int(p.cfg["y"]), p.cur_w, p.cur_h)
        bottoms, others = [], []
        for p in self.panels.values():
            if p.name in own:
                continue
            others.append(rect(p))
            ps = self.stack_pos(p.name)
            if pos is None and (ps is None or ps[1] == len(stacks[ps[0]]) - 1):
                bottoms.append(rect(p))
        group = [rect(p)[1:] for p in self._stack_panels(pos[0])] if pos else None     # a stack top moves its whole stack
        mons, hh = self.monitors(), panel.head_h
        res = stack.choose_drop(rect(panel), bottoms, others, g["snap_distance"], g["stack_gap"], group,
                                lambda x, y, w: displays.reachable(mons, x, y, w, hh))   # a head off the screen is no candidate
        if res is None:
            return None
        rects, edge = stack.plan_rects(res, rect(panel), group, {r[0]: r for r in others}, g["stack_gap"])
        return {"res": res, "rects": rects, "edge": edge}

    # ---- snap preview: a frame where the panel would land + a line on the target's edge (display only)
    def snapshot_layout(self):
        """Everything a header drag can change: the stacks and every panel's position, width and window position."""
        return {"stacks": copy.deepcopy(self.cfg["stacks"]),
                "panels": {n: (p.cfg["x"], p.cfg["y"], p.cfg["w"], p.cur_w, p._shown_xy) for n, p in self.panels.items()}}

    def restore_layout(self, snap):
        """Put a snapshot back EXACTLY: stacks, cfg, and the real windows (via PanelWin._move_to)."""
        self.cfg["stacks"] = copy.deepcopy(snap["stacks"])
        self._relaying = True
        try:
            for n, (x, y, w, cur_w, shown) in snap["panels"].items():
                p = self.panels.get(n)
                if p is None:
                    continue
                p._held, p._slot = False, None
                p.cfg["x"], p.cfg["y"], p.cfg["w"] = x, y, w
                if p.cur_w != cur_w:
                    p.apply_size(cur_w, p.cur_h)         # also places the window
                p._move_to(x, y)
        finally:
            self._relaying = False

    def clear_drag_plan(self):
        self._drag_plan = None

    def update_preview(self, panel):
        """While dragging: compute the candidate for the panel's current position and keep it (it is what the drop
        applies); show (or move, or remove) the preview for it. With the preview setting off the candidate is the
        same, it is only not drawn."""
        plan = None if panel._aborted else self.drop_plan(panel)
        self._drag_plan = (panel.name, plan)
        if plan is None or not self.cfg["general"]["snap_preview"]:
            return self.hide_preview()
        key = (plan["res"], tuple(plan["rects"]), plan["edge"])
        if key != self._preview_key:                           # same candidate: nothing is redrawn
            self._show_preview(plan)
            self._preview_key = key

    def make_ghost(self):
        """The preview window: created and mapped ONCE (then hidden); from then on only Win32 SetWindowPos moves it."""
        g = self._ghost = tk.Toplevel(self.root)
        g.withdraw()
        g.overrideredirect(True)
        g.configure(bg=KEY)
        g.attributes("-transparentcolor", KEY)
        g.attributes("-topmost", True)
        g.geometry("1x1+0+0")
        self._ghost_cv = tk.Canvas(g, bg=KEY, highlightthickness=0, bd=0)
        self._ghost_cv.place(x=0, y=0, width=GHOST_CANVAS[0], height=GHOST_CANVAS[1])   # the window clips it
        winutil.make_overlay(g)                                # while withdrawn: click-through, no focus, no taskbar
        g.deiconify()                                          # the only deiconify it ever gets
        g.update_idletasks()
        winutil.overlay_hide(g)

    def _show_preview(self, plan):
        rects, (ex0, ey0, ex1, ey1) = plan["rects"], plan["edge"]
        xs = [r[0] for r in rects] + [r[0] + r[2] for r in rects] + [ex0, ex1]
        ys = [r[1] for r in rects] + [r[1] + r[3] for r in rects] + [ey0, ey1]
        bx, by = min(xs) - 2, min(ys) - 2
        bw, bh = max(xs) + 2 - bx, max(ys) + 2 - by
        if self._ghost is None:
            self.make_ghost()
        g, cv = self._ghost, self._ghost_cv
        cv.delete("all")
        for x, y, w, h in rects:                               # 2 px frame, empty inside
            cv.create_rectangle(x - bx + 1, y - by + 1, x - bx + w - 1, y - by + h - 1, outline=theme.ACCENT, width=2)
        cv.create_line(ex0 - bx, ey0 - by, ex1 - bx, ey1 - by, fill=theme.ACCENT, width=2)    # the target's edge
        winutil.overlay_show(g, bx, by, bw, bh)                # SetWindowPos(HWND_TOPMOST, NOACTIVATE | SHOWWINDOW)
        LOG.info("preview show box=%s", (bx, by, bw, bh))
        self._preview_shown = {"rects": list(rects), "edge": plan["edge"], "box": (bx, by, bw, bh)}

    def preview_visible(self):
        return self._ghost is not None and winutil.window_visible(self._ghost)

    def hide_preview(self):
        self._preview_key = None
        self._preview_shown = None
        if self.preview_visible():
            LOG.info("preview hide")
            winutil.overlay_hide(self._ghost)

    def apply_drag_plan(self, panel):
        """The drop: apply EXACTLY the candidate the last motion computed (None = it does not snap). True = snapped."""
        stored, self._drag_plan = self._drag_plan, None
        plan = stored[1] if stored and stored[0] == panel.name else None
        return self.drop_snap(panel, plan, decided=True)

    def drop_snap(self, panel, plan=None, decided=False):
        """A panel (or a stack top, which takes its stack along) was dropped. The pure rules are in stack.choose_drop:
        a FREE panel may snap under the bottom panel of a stack (or under a free panel); any dropped panel may snap
        to the side of another panel (alignment only, nothing is remembered). The nearer one wins; a tie goes to
        snapping under. The monitor the panel came from does not matter. Returns True when something snapped."""
        if not decided:                                        # direct call (no drag): decide now
            plan = self.drop_plan(panel)
        LOG.info("drop_snap panel=%s choose_drop=%s", panel.name, plan and plan["res"])
        if plan is None:
            return False
        res, stacks = plan["res"], self.cfg["stacks"]
        if res[0] == "below":
            self.cfg["stacks"] = stack.add_below(stacks, res[1], panel.name)
            self.relayout(self.stack_pos(panel.name)[0])
        else:                                                  # side: same width, top edge = the target's top edge
            panel.cfg["x"], panel.cfg["y"] = res[2], res[3]
            panel._move_to(res[2], res[3])
            self.stack_changed(panel)                          # a stack top: the whole stack follows
        return True

    # ------------------------------------------------------------ panels
    def sync_panels(self):
        derived = self._derived_homes()                      # before panels are destroyed/removed (see ensure_homes)
        folders = fileops.list_panel_folders(self.ctx)
        notes = [n for n, c in self.cfg["panels"].items() if c.get("type") in ("note", "calendar") and n not in folders]
        names = folders + sorted(notes, key=str.casefold)
        for n in list(self.panels):
            if n not in names:
                self.panels.pop(n).destroy()
        for n in names:
            if n not in self.panels:
                self.panels[n] = PanelWin(self, n)
                if not self.visible:
                    self.panels[n].top.withdraw()
        self.watcher.set_paths({self.ctx.panels_root: "*root",
                                **{self.ctx.panel_path(n): n for n in folders}})
        self.cfg["stacks"] = stack.sanitize_stacks(self.cfg["stacks"], set(names) | set(self.cfg["panels"]))
        self.ensure_homes(derived)
        self.relayout_all()
        self.save()

    def migrate_calendar_sources(self):
        """v1.1.1, once per calendar panel: a pre-1.1.1 config still has `source_path` (the old M Calendar file).
        Ask ONE time whether to import its calendars into M Panels' own settings. Yes: import; No: nothing is
        imported. Either way the old setting is removed, so the question never comes again. Addresses are never
        logged or put into a message."""
        from calendar_panel import source as cal_source
        for name, p in list(self.panels.items()):
            if not p.is_calendar:
                continue
            pend = cal_settings.pending_migration(p.cfg["calendar"])
            if not pend:
                continue
            path, ticked = pend
            fname = os.path.basename(path) or path
            imported = []
            if messagebox.askyesno(APP_NAME, ui.ASK_CAL_MIGRATE.format(file=fname, panel=name), parent=self.root):
                try:
                    imported = cal_source.read_sources(path)
                except cal_source.SourceError as e:
                    messagebox.showwarning(APP_NAME, ui.MSG_CAL_MIGRATE_FAILED.format(panel=name, file=fname, error=e),
                                           parent=self.root)
            p.cfg["calendar"] = cal_settings.finish_migration(p.cfg["calendar"], imported, ticked)
            applog.get_logger().info(ui.LOG_CAL_MIGRATED, name, len(imported))
            p.cal_settings_changed()
        self.save()

    def reload_all(self):
        for p in self.panels.values():
            p.reload_items()

    def popup(self, menu, x, y):
        self.busy += 1
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()
            self.root.after(300, self._unbusy)

    def _unbusy(self):
        self.busy = max(0, self.busy - 1)

    def sink_if_idle(self, panel):
        if self.busy or not panel.top.winfo_exists():
            return
        px, py = panel.top.winfo_pointerxy()
        x0, y0 = panel.top.winfo_rootx(), panel.top.winfo_rooty()
        if not (x0 <= px < x0 + panel.top.winfo_width() and y0 <= py < y0 + panel.top.winfo_height()):
            winutil.send_to_bottom(panel.top)

    def panel_at(self, rx, ry):
        for p in self.panels.values():
            t = p.top
            if t.winfo_viewable() and t.winfo_rootx() <= rx < t.winfo_rootx() + t.winfo_width() \
                    and t.winfo_rooty() <= ry < t.winfo_rooty() + t.winfo_height():
                return p
        return None

    # ------------------------------------------------------------ dialogs (overridable in tests)
    def ask_text(self, title, prompt, initial=""):
        self.busy += 1
        try:
            return uiwidgets.PromptDialog(self._dlg_parent(), title, prompt, initial).run()
        finally:
            self.busy -= 1

    def ask_style(self, title, style):
        """Title/content text window -> a new style dict or None. Overridable in tests."""
        self.busy += 1
        try:
            return uiwidgets.StyleDialog(self._dlg_parent(), title, style).run()
        finally:
            self.busy -= 1

    def ask_font(self, family, size):
        self.busy += 1
        try:
            return uiwidgets.FontDialog(self._dlg_parent(), family, size).run()
        finally:
            self.busy -= 1

    def ask_color(self, panel, initial):
        self.busy += 1
        try:
            return colorchooser.askcolor(color=initial, parent=panel.top, title=ui.DLG_TEXT_COLOR)[1]
        finally:
            self.busy -= 1

    def ask_size(self, initial):
        self.busy += 1
        try:
            return uiwidgets.PromptDialog(self._dlg_parent(), ui.DLG_SIZE_TITLE,
                                          ui.DLG_SIZE_PROMPT.format(lo=theme.SIZE_MIN, hi=theme.SIZE_MAX),
                                          initial, kind="int", lo=theme.SIZE_MIN, hi=theme.SIZE_MAX).run()
        finally:
            self.busy -= 1

    def edit_style(self, panel, role):
        """The menu's 'Title text…' / 'Content text…': font, size, color, bold, italic."""
        what = ui.DLG_TITLE_TEXT if role == "title" else ui.DLG_CONTENT_TEXT
        new = self.ask_style(ui.DLG_STYLE_TITLE.format(what=what, panel=panel.name), theme.style_of(panel.cfg, role))
        if not new:
            return
        for k, v in new.items():
            panel.cfg[f"{role}_{k}"] = v
        theme.sanitize_style(panel.cfg)
        panel.apply_cfg()
        self.save()

    def confirm(self, title, msg):
        self.busy += 1
        try:
            return messagebox.askyesno(title, msg, parent=self._dlg_parent())
        finally:
            self.busy -= 1

    def _dlg_parent(self):
        for p in self.panels.values():
            if p.top.winfo_viewable():
                p.top.lift()
                return p.top
        return self.root

    def flash(self, panel, text, error=False):
        """A short notice shown for 4 s under the panel."""
        if self._toast is not None:
            try:
                self._toast.destroy()
            except Exception:
                pass
        t = tk.Toplevel(self.root)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        winutil.make_toolwindow(t)
        col = panel.cfg["color"]
        tk.Label(t, text=text, bg=theme.SURFACE, fg=theme.ERROR_TEXT if error else theme.TEXT_COLOR,
                 font=(theme.FONT_FAMILY, theme.FONT_SIZE),
                 wraplength=max(220, panel.cur_w - 20), justify="left", padx=10, pady=6,
                 highlightthickness=1, highlightbackground=col).pack()
        t.update_idletasks()
        t.geometry(f"+{panel.top.winfo_rootx()}+{panel.top.winfo_rooty() + panel.cur_h + 6}")
        self._toast = t
        self.last_flash = text
        t.after(4000, lambda: t.winfo_exists() and t.destroy())

    # ------------------------------------------------------------ item operations
    def drop_paths(self, panel, paths):
        """Items dropped from Explorer (the drag-and-drop rules in docs/PLAN.md)."""
        msgs, errs = [], []
        for p in paths:
            r = fileops.handle_drop(self.ctx, panel.name, p)
            if r.kind == "skip":
                continue
            (msgs if r.ok else errs).append(r.message) if r.message else None
        self.reload_all()
        if errs:
            self.flash(panel, "\n".join(errs), error=True)
        elif msgs:
            self.flash(panel, "\n".join(dict.fromkeys(msgs)))
        return msgs, errs

    def finish_item_drag(self, src, item, rx, ry):
        tgt = self.panel_at(rx, ry)
        if tgt is None or item.special:
            return
        if tgt is src:
            b = src.body
            slot = self.slot_at(src, rx - b.winfo_rootx(), ry - b.winfo_rooty())
            names = [os.path.basename(i.path) for i in src.items if not i.special]
            me = os.path.basename(item.path)
            if me in names:
                names.remove(me)
                names.insert(min(slot, len(names)), me)
                src.cfg["order"] = names
                self.save()
                src.reload_items()
            return
        self.drop_paths(tgt, [item.path])

    def slot_at(self, panel, x, y):
        best, bd = len(panel.items), 10 ** 9
        for x0, y0, x1, y1, i in panel.rects:
            d = (x - (x0 + x1) / 2) ** 2 + (y - (y0 + y1) / 2) ** 2
            if d < bd:
                best, bd = i, d
        return best

    def open_item(self, item):
        try:
            os.startfile(item.path)          # folder -> Explorer, shortcut/file -> the associated app
        except OSError as e:
            if item.is_lnk and item.broken:
                messagebox.showwarning(APP_NAME, ui.ITEM_BROKEN)
            else:
                messagebox.showwarning(APP_NAME, ui.ITEM_OPEN_FAILED.format(error=e.strerror or e))

    def reveal_item(self, item):
        target = item.path
        if item.is_lnk:
            t = winutil.resolve_shortcut(item.path)
            if t and os.path.exists(t):
                target = t
        winutil.reveal_in_explorer(target)

    def rename_item(self, panel, item):
        new = self.ask_text(ui.DLG_RENAME_ITEM_TITLE, ui.DLG_NEW_NAME, item.name if item.is_lnk else os.path.basename(item.path))
        if new is None:
            return
        r = fileops.rename_item(item.path, new)
        panel.reload_items()
        if not r.ok:
            self.flash(panel, r.message, error=True)

    def return_item(self, panel, item):
        r = fileops.return_to_desktop(self.ctx, item.path)
        self.reload_all()
        if not r.ok:
            self.flash(panel, r.message, error=True)

    def move_in_order(self, panel, item, delta):
        names = [os.path.basename(i.path) for i in panel.items if not i.special]
        me = os.path.basename(item.path)
        if me not in names:
            return
        i = names.index(me)
        j = max(0, min(len(names) - 1, i + delta))
        names.insert(j, names.pop(i))
        panel.cfg["order"] = names
        self.save()
        panel.sel = j
        panel.reload_items()

    def sort_az(self, panel):
        panel.cfg["order"] = []
        self.save()
        panel.reload_items()

    def toggle_special(self, panel, kind):
        sp = panel.cfg["specials"]
        sp.remove(kind) if kind in sp else sp.append(kind)
        self.save()
        panel.reload_items()

    # ------------------------------------------------------------ panel operations
    def ask_new_panel(self):
        """(name, kind) or None. Overridable in tests."""
        self.busy += 1
        try:
            return NewPanelDialog(self).run()
        finally:
            self.busy -= 1

    def new_panel(self, name=None, kind=None):
        """kind: 'shortcut' (folder panel) or 'note'. Without name/kind the type+name window opens."""
        if name is None:
            res = self.ask_new_panel()
            if res is None:
                return None
            name, kind = res
        kind = kind or "shortcut"
        name = name.strip()
        if fileops.name_taken(self.ctx, self.data_dir, self.cfg["panels"], name):
            messagebox.showwarning(APP_NAME, ui.NAME_TAKEN)
            return None
        if kind == "calendar":
            err = fileops.valid_name(name)
            r = fileops.Result(False, "refused", err) if err else fileops.Result(True, "moved")
            if r.ok:
                c = self.panel_cfg(name)
                c["type"] = "calendar"
                c["w"], c["h"] = CAL_PANEL_SIZE
                c["collapsed"] = c["start_collapsed"]
                c["calendar"] = cal_settings.with_look(None, self.calendar_look())
        elif kind == "note":
            r = fileops.create_note(self.data_dir, name)
            if r.ok:
                c = self.panel_cfg(name)          # created with the defaults
                c["type"] = "note"
                c["collapsed"] = c["start_collapsed"]
        else:
            r = fileops.create_panel(self.ctx, name)
        if not r.ok:
            messagebox.showwarning(APP_NAME, r.message)
            return None
        self.sync_panels()
        return self.panels.get(name)

    def do_rename(self, panel, new):
        """Rename a panel/note (the folder or the note file changes too). Returns a Result."""
        new = new.strip()
        taken = fileops.name_taken(self.ctx, self.data_dir, self.cfg["panels"], new, ignore=panel.name)
        if new.casefold() != panel.name.casefold() and taken:
            return fileops.Result(False, "refused", ui.NAME_TAKEN)
        if panel.is_calendar:
            err = fileops.valid_name(new)
            r = fileops.Result(False, "refused", err) if err else fileops.Result(True, "moved")
        elif panel.is_note:
            panel.save_note()
            r = fileops.rename_note(self.data_dir, panel.name, new)
        else:
            r = fileops.rename_panel(self.ctx, panel.name, new)
        if r.ok:
            self.cfg["panels"][new] = self.cfg["panels"].pop(panel.name)
            self.cfg["stacks"] = stack.rename(self.cfg["stacks"], panel.name, new)
            self.panels.pop(panel.name).destroy()
            self.sync_panels()
        return r

    def rename_panel(self, panel, new=None):
        if new is None:
            new = self.ask_text(ui.DLG_PANEL_NAME_TITLE, ui.DLG_NEW_NAME, panel.name)
            if new is None or new.strip() == panel.name:
                return
        r = self.do_rename(panel, new)
        if not r.ok:
            self.flash(panel, r.message, error=True)

    def remove_panel(self, panel, confirm=True):
        if confirm:
            if panel.is_calendar:
                msg = ui.REMOVE_CALENDAR_MSG.format(name=panel.name)
            elif panel.is_note:
                msg = ui.REMOVE_NOTE_MSG.format(name=panel.name, trash=f"{fileops.NOTES_DIRNAME}/{fileops.TRASH_DIRNAME}")
            else:
                msg = ui.REMOVE_PANEL_MSG.format(name=panel.name)
            if not self.confirm(ui.DLG_REMOVE_TITLE, msg):
                return None
        if panel.is_calendar:
            r = fileops.Result(True, "moved")           # nothing on disk to move or delete
        elif panel.is_note:
            panel.save_note()
            r = fileops.remove_note(self.data_dir, panel.name)
        else:
            r = fileops.remove_panel(self.ctx, panel.name)
        if r.ok:
            self.cfg["panels"].pop(panel.name, None)
            self.sync_panels()
        else:
            self.reload_all()
            self.flash(panel, r.message, error=True)
        return r

    # ------------------------------------------------------------ settings
    def sync_settings_cal(self, panel):
        """Tell an open Settings window that this calendar panel's view/weeks changed on the panel itself."""
        w = self.settings_win
        if w is not None:
            try:
                if w.win.winfo_exists():
                    w.sync_cal_view(panel)
            except tk.TclError:
                pass

    def open_settings(self, name=None):
        if self.settings_win is not None and self.settings_win.win.winfo_exists():
            w = self.settings_win.win
            if w.state() == "iconic":
                w.deiconify()
            w.lift()
            try:
                w.focus_force()
            except tk.TclError:
                pass
            if name:
                self.settings_win.request_select(name)
            return
        self.settings_win = SettingsWindow(self, name)

    def bring_forward(self):
        """A second launch asked us to come forward: show the panels and bring Settings to the front."""
        self.show_all(True)
        self.open_settings()

    def set_autostart(self, on):
        """'Start with Windows' is a config flag: kur.py always installs the startup shortcut,
        and the program quietly exits at startup when the flag is off (no shortcut has to be deleted)."""
        self.cfg["general"]["autostart"] = bool(on)
        self.save()

    # ------------------------------------------------------------ tray / queue
    def _setup_tray(self):
        if not HAS_TRAY:
            return
        put = self.q.put
        menu = pystray.Menu(
            pystray.MenuItem(ui.TRAY_SHOW_HIDE, lambda i, it: put(("cmd", "toggle")), default=True),
            pystray.MenuItem(ui.TRAY_NEW, lambda i, it: put(("cmd", "new"))),
            pystray.MenuItem(ui.TRAY_SETTINGS, lambda i, it: put(("cmd", "settings"))),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(ui.TRAY_QUIT, lambda i, it: put(("cmd", "quit"))),
        )
        tip = ui.VERSION_LINE.format(app=APP_NAME, version=__version__) + (f" {ui.TEST_TAG}" if self.test_mode else "")
        self.tray = pystray.Icon("MPanels", app_icon_image(64), tip, menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "fs":
                    self._fs_dirty.add(val)
                    if self._fs_job is None:
                        self._fs_job = self.root.after(250, self._fs_flush)
                elif kind == "cmd":
                    if val == "toggle":
                        self.show_all(not self.visible)
                    elif val == "new":
                        self.show_all(True)
                        self.new_panel()
                    elif val == "settings":
                        self.open_settings()
                    elif val == "raise":
                        self.bring_forward()
                    elif val == "quit":
                        self.quit()
                        return
                elif kind == "cal":
                    p = self.panels.get(val)
                    if p is not None and p.expanded:
                        p.draw_body()
        except queue.Empty:
            pass
        self.root.after(150, self._poll)

    def _fs_flush(self):
        dirty, self._fs_dirty, self._fs_job = self._fs_dirty, set(), None
        if "*root" in dirty:
            if set(fileops.list_panel_folders(self.ctx)) != {n for n, p in self.panels.items() if p.folder is not None}:
                self.sync_panels()
        for n in dirty:
            if n in self.panels:
                self.panels[n].reload_items()

    def _tick(self):
        """Every 2 s: is the Recycle Bin icon (full/empty) up to date?"""
        for p in self.panels.values():
            if "recycle" in p.cfg["specials"]:
                k = winutil.recycle_bin_key()
                if p.icon_keys.get("shell:RecycleBinFolder") != k:
                    p.reload_items()
        for p in self.panels.values():
            p.cal_tick()
        self.root.after(2000, self._tick)

    def show_all(self, on):
        self.visible = on
        for p in self.panels.values():
            if on:
                p.top.deiconify()
                winutil.make_toolwindow(p.top, bottom=True)
            else:
                p.top.withdraw()

    def quit(self):
        """Close everything and end the process: panels/windows, tray icon, background threads, the
        single-instance lock. Each step is guarded so one failure cannot keep the program alive; when
        hard_exit_s is set (the real program), a watchdog ends the process if it is still alive after that."""
        if self._quitting:
            return
        self._quitting = True
        if self.hard_exit_s:
            t = threading.Timer(self.hard_exit_s, lambda: os._exit(0))
            t.daemon = True
            t.start()
        steps = (
            lambda: [p.save_note() for p in self.panels.values()],
            self.save,
            self.icons.on_quit,                 # desktop icons back to normal (does nothing in TEST mode)
            lambda: setattr(self.watcher, "stop_flag", True),
            lambda: self._listener.stop() if self._listener is not None else None,
            lambda: self._quit_listener.stop() if self._quit_listener is not None else None,
            lambda: self.tray.stop() if self.tray is not None else None,
            lambda: [p.model.stop() for p in self.panels.values() if p.model is not None],
            winutil.release_single_instance,
            self.root.destroy,
        )
        for step in steps:
            try:
                step()
            except Exception:
                logging.getLogger("mpanels").exception("quit step failed")


# ------------------------------------------------------------------ new-panel window
class NewPanelDialog:
    """New panel: name + type (shortcut / note)."""

    def __init__(self, app):
        self.result = None
        w = self.win = tk.Toplevel(app.root)
        w.title(ui.NEW_TITLE)
        w.attributes("-topmost", True)
        w.resizable(False, False)
        winutil.make_toolwindow(w)          # no taskbar button / Alt+Tab entry
        f = ttk.Frame(w, padding=12)
        f.pack(fill="both", expand=True)
        self.kind, self.name = tk.StringVar(value="shortcut"), tk.StringVar()
        ttk.Label(f, text=ui.NEW_TYPE).grid(row=0, column=0, sticky="nw", padx=(0, 10))
        kf = ttk.Frame(f)
        ttk.Radiobutton(kf, text=ui.NEW_KIND_SHORTCUT, variable=self.kind,
                        value="shortcut").pack(anchor="w")
        ttk.Radiobutton(kf, text=ui.NEW_KIND_NOTE, variable=self.kind,
                        value="note").pack(anchor="w")
        if calendar_panel.AVAILABLE:                 # the Calendar type is only offered when its libraries exist
            ttk.Radiobutton(kf, text=ui.NEW_KIND_CALENDAR, variable=self.kind,
                            value="calendar").pack(anchor="w")
        kf.grid(row=0, column=1, sticky="w")
        ttk.Label(f, text=ui.NEW_NAME).grid(row=1, column=0, sticky="w", pady=(8, 0), padx=(0, 10))
        e = ttk.Entry(f, textvariable=self.name, width=30)
        e.grid(row=1, column=1, sticky="we", pady=(8, 0))
        bf = ttk.Frame(f)
        ttk.Button(bf, text=ui.BTN_CREATE, command=self.ok).pack(side="left")
        ttk.Button(bf, text=ui.BTN_CANCEL, command=w.destroy).pack(side="left", padx=6)
        bf.grid(row=2, column=1, sticky="e", pady=(10, 0))
        w.bind("<Return>", lambda ev: self.ok())
        w.bind("<Escape>", lambda ev: w.destroy())
        e.focus_set()

    def ok(self):
        n = self.name.get().strip()
        err = fileops.valid_name(n)
        if err:
            messagebox.showwarning(APP_NAME, err, parent=self.win)
            return
        self.result = (n, self.kind.get())
        self.win.destroy()

    def run(self):
        self.win.grab_set()
        self.win.wait_window()
        return self.result


# ------------------------------------------------------------------ settings window
class SettingsWindow:
    """Tabbed settings: Panel · Title · Content · General, with shared buttons at the bottom (Apply, defaults...).
    Rule: NOTHING changes until 'Apply' (the General checkboxes included). Closing with X or switching panel
    while something is unapplied asks 'Unsaved changes - Apply / Discard / Cancel'. Only 'Revert to defaults' and
    'Factory settings' act at once, after a confirmation.
    This is the one window that shows in the taskbar while it is open."""

    # (key, label): code uses the keys, the user sees the labels
    TABS = (("panel", ui.TAB_PANEL), ("title", ui.TAB_TITLE), ("content", ui.TAB_CONTENT),
            ("calendar", ui.TAB_CALENDAR), ("general", ui.TAB_GENERAL), ("about", ui.TAB_ABOUT))

    # Calendar tab, Day/Week look + fading: (form variable, label, lo, hi, settings key)
    CAL_LOOK_FIELDS = (("cal_start", ui.LBL_CAL_START_HOUR, 0, 23), ("cal_end", ui.LBL_CAL_END_HOUR, 1, 24),
                       ("cal_hh", ui.LBL_CAL_HOUR_H, 12, 200), ("cal_ehh", ui.LBL_CAL_EMPTY_H, 6, 200),
                       ("cal_fade", ui.LBL_CAL_FADE, 0, 90))
    CAL_LOOK_KEYS = {"cal_start": "start_hour", "cal_end": "end_hour", "cal_hh": "hour_height",
                     "cal_ehh": "empty_hour_height", "cal_fade": "past_fade"}

    def __init__(self, app, name=None):
        self.app = app
        w = self.win = tk.Toplevel(app.root)
        w.title(ui.SET_TITLE.format(app=APP_NAME, version=__version__))
        w.attributes("-topmost", True)
        w.resizable(False, False)
        f = ttk.Frame(w, padding=12)
        f.pack(fill="both", expand=True)
        self.v = {k: tk.StringVar() for k in ("panel", "name", "color", "icon", "cal_view",
                                              "cal_weeks", "cal_refresh", "cal_start", "cal_end", "cal_hh",
                                              "cal_ehh", "cal_fade")}
        self.v_cal_fit = tk.BooleanVar(value=True)
        self.v_cal_shrink = tk.BooleanVar(value=True)
        self.v_cal_tf = tk.StringVar()
        self.v_cal_ws = tk.StringVar()
        self.cal_list = []                    # working copy of calendar["calendars"]; applied by Apply
        self.v_op = tk.IntVar(value=95)
        self.v_start, self.v_hover = tk.BooleanVar(), tk.BooleanVar()
        self.v_auto = tk.BooleanVar(value=bool(app.cfg["general"]["autostart"]))
        self.v_lock = tk.BooleanVar(value=app.locked)
        self.v_hide = tk.BooleanVar(value=bool(app.cfg["general"]["hide_desktop_icons"]) and app.icons.enabled)
        self.v_snap = tk.BooleanVar(value=bool(app.cfg["general"]["snap_enabled"]))
        self.v_snap_prev = tk.BooleanVar(value=bool(app.cfg["general"]["snap_preview"]))
        self.v_snap_dist = tk.StringVar(value=str(app.cfg["general"]["snap_distance"]))
        self.v_stack_gap = tk.StringVar(value=str(app.cfg["general"]["stack_gap"]))
        self.color = theme.DEFAULT_COLOR

        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Label(top, text=ui.LBL_PANEL).pack(side="left", padx=(0, 10))
        self.cb_panel = ttk.Combobox(top, textvariable=self.v["panel"], state="readonly", width=32)
        self.cb_panel.pack(side="left")
        self.cb_panel.bind("<<ComboboxSelected>>", lambda e: self.request_select(self.v["panel"].get()))

        self.nb = ttk.Notebook(f)
        self.nb.pack(fill="both", expand=True, pady=(8, 0))
        self.tab = {k: ttk.Frame(self.nb, padding=10) for k, _ in self.TABS}
        for k, label in self.TABS:
            if k != "calendar":          # the Calendar tab is added only while a calendar panel is selected
                self.nb.add(self.tab[k], text=label)

        # --- Panel tab
        p = self.tab["panel"]

        def row(parent, r, label, widget):
            ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", pady=3, padx=(0, 10))
            widget.grid(row=r, column=1, sticky="we", pady=3)

        row(p, 0, ui.LBL_NAME, ttk.Entry(p, textvariable=self.v["name"], width=34))
        cf = ttk.Frame(p)
        self.cb_color = ttk.Combobox(cf, textvariable=self.v["color"], width=14,
                                     values=[n for n, _ in PRESETS] + [ui.COLOR_CUSTOM], state="readonly")
        self.cb_color.pack(side="left")
        self.sw = tk.Label(cf, width=4, relief="solid", bd=1)
        self.sw.pack(side="left", padx=6)
        ttk.Button(cf, text=ui.BTN_PICK_COLOR, command=self.pick_color).pack(side="left")
        row(p, 1, ui.LBL_COLOR, cf)
        row(p, 2, ui.LBL_OPACITY, ttk.Scale(p, from_=30, to=100, variable=self.v_op, orient="horizontal"))
        ttk.Checkbutton(p, text=ui.CHK_START_COLLAPSED, variable=self.v_start).grid(row=3, column=1, sticky="w")
        ttk.Checkbutton(p, text=ui.CHK_HOVER_OPEN, variable=self.v_hover).grid(row=4, column=1, sticky="w")
        p.columnconfigure(1, weight=1)

        # --- Title tab
        self.title_ed = uiwidgets.StyleEditor(self.tab["title"], theme.TITLE_STYLE)
        self.title_ed.pack(fill="both", expand=True)

        # --- Content tab (+ icon size)
        self.content_ed = uiwidgets.StyleEditor(self.tab["content"], theme.CONTENT_STYLE)
        self.content_ed.pack(fill="both", expand=True)
        irow = ttk.Frame(self.tab["content"])
        irow.pack(fill="x", pady=(8, 0))
        ttk.Label(irow, text=ui.LBL_ICON_SIZE.format(lo=ICON_MIN, hi=ICON_MAX)).pack(side="left", padx=(0, 10))
        self.sp_icon = ttk.Spinbox(irow, from_=ICON_MIN, to=ICON_MAX, increment=1, textvariable=self.v["icon"],
                                   width=6)
        self.sp_icon.pack(side="left")

        # --- General tab
        g = self.tab["general"]
        self.cb_auto = ttk.Checkbutton(g, text=ui.CHK_AUTOSTART, variable=self.v_auto)
        self.cb_auto.pack(anchor="w", pady=2)
        self.cb_lock = ttk.Checkbutton(g, text=ui.CHK_LOCK, variable=self.v_lock)
        self.cb_lock.pack(anchor="w", pady=2)
        self.cb_hide = ttk.Checkbutton(g, text=ui.CHK_HIDE_ICONS, variable=self.v_hide)
        self.cb_hide.pack(anchor="w", pady=2)
        sn = ttk.LabelFrame(g, text=ui.LBL_SNAPPING, padding=(6, 2))          # one tight row (like Calendar, step 6b)
        sn.pack(fill="x", pady=(8, 0))
        self.cb_snap = ttk.Checkbutton(sn, text=ui.CHK_SNAP, variable=self.v_snap)
        self.cb_snap.pack(side="left")
        self.cb_snap_prev = ttk.Checkbutton(sn, text=ui.CHK_SNAP_PREVIEW, variable=self.v_snap_prev)
        self.cb_snap_prev.pack(side="left", padx=(10, 0))
        ttk.Label(sn, text=ui.LBL_SNAP_DISTANCE).pack(side="left", padx=(14, 4))
        self.sp_snap_dist = ttk.Spinbox(sn, from_=stack.SNAP_DISTANCE_RANGE[0], to=stack.SNAP_DISTANCE_RANGE[1],
                                        increment=1, textvariable=self.v_snap_dist, width=4)
        self.sp_snap_dist.pack(side="left")
        ttk.Label(sn, text=ui.LBL_STACK_GAP).pack(side="left", padx=(14, 4))
        self.sp_stack_gap = ttk.Spinbox(sn, from_=stack.STACK_GAP_RANGE[0], to=stack.STACK_GAP_RANGE[1],
                                        increment=1, textvariable=self.v_stack_gap, width=4)
        self.sp_stack_gap.pack(side="left")
        if app.test_mode:
            self.cb_auto.state(["disabled"])
            self.cb_hide.state(["disabled"])
            ttk.Label(g, text=ui.TEST_MODE_NOTE).pack(anchor="w", pady=(6, 0))

        self._build_about(self.tab["about"])

        # --- Calendar tab (only shown for calendar panels). Compact grid: 4 columns (label, box, label, box).
        ct = self.tab["calendar"]
        small = tkfont.nametofont("TkDefaultFont").copy()
        sz = small.cget("size")
        small.configure(size=(sz + 1 if sz < 0 else max(7, sz - 1)))
        self._small_font = small

        def lab(r, c, text):
            ttk.Label(ct, text=text).grid(row=r, column=c, sticky="w", pady=2, padx=(0, 6) if c == 0 else (14, 6))

        lab(0, 0, ui.LBL_CAL_CALENDARS)
        lf = ttk.Frame(ct)
        lf.grid(row=0, column=1, columnspan=3, sticky="we", pady=2)
        self.cal_tree = ttk.Treeview(lf, columns=("on", "name", "color"), show="headings", height=4,
                                     selectmode="browse")
        for col, text, wd, anchor in (("on", ui.CAL_COL_ON, 36, "center"), ("name", ui.CAL_COL_NAME, 190, "w"),
                                     ("color", ui.CAL_COL_COLOR, 70, "w")):
            self.cal_tree.heading(col, text=text)
            self.cal_tree.column(col, width=wd, anchor=anchor, stretch=(col == "name"))
        self.cal_tree.pack(side="left", fill="both", expand=True)
        self.cal_tree.bind("<Double-1>", lambda e: self.cal_edit())
        bb = ttk.Frame(lf)
        bb.pack(side="left", fill="y", padx=(8, 0))
        self.btn_cal_add = ttk.Button(bb, text=ui.BTN_CAL_ADD, command=self.cal_add)
        self.btn_cal_edit = ttk.Button(bb, text=ui.BTN_CAL_EDIT, command=self.cal_edit)
        self.btn_cal_remove = ttk.Button(bb, text=ui.BTN_CAL_REMOVE, command=self.cal_remove)
        self.btn_cal_import = ttk.Button(bb, text=ui.BTN_CAL_IMPORT, command=self.cal_import)
        for b_ in (self.btn_cal_add, self.btn_cal_edit, self.btn_cal_remove, self.btn_cal_import):
            b_.pack(fill="x", pady=1)
        ttk.Label(ct, text=ui.CAL_LIST_NOTE, font=self._small_font, foreground="gray40").grid(
            row=1, column=1, columnspan=3, sticky="w")
        self.cal_view_labels = dict(zip(cal_settings.VIEW_KEYS, (ui.CAL_VIEW_LIST, ui.CAL_VIEW_DAY, ui.CAL_VIEW_WEEK)))
        lab(2, 0, ui.LBL_CAL_VIEW)
        self.cb_cal_view = ttk.Combobox(ct, textvariable=self.v["cal_view"], state="readonly", width=9,
                                        values=list(self.cal_view_labels.values()))
        self.cb_cal_view.grid(row=2, column=1, sticky="w", pady=2)
        lab(2, 2, ui.LBL_CAL_WEEKS)
        self.sp_cal_weeks = ttk.Spinbox(ct, from_=1, to=4, increment=1, textvariable=self.v["cal_weeks"], width=4)
        self.sp_cal_weeks.grid(row=2, column=3, sticky="w", pady=2)
        lab(3, 0, ui.LBL_CAL_REFRESH)
        self.sp_cal_refresh = ttk.Spinbox(ct, from_=cal_settings.REFRESH_MIN, to=cal_settings.REFRESH_MAX,
                                          increment=1, textvariable=self.v["cal_refresh"], width=4)
        self.sp_cal_refresh.grid(row=3, column=1, sticky="w", pady=2)
        ttk.Label(ct, text=ui.LBL_CAL_DAYWEEK, font=self._small_font, foreground="gray40").grid(
            row=4, column=0, columnspan=4, sticky="w", pady=(8, 0))
        self.cal_look_widgets = []           # Day/Week look + past fading (v1.1 step 1)
        spots = {"cal_start": (5, 0), "cal_end": (5, 2), "cal_hh": (6, 0), "cal_ehh": (6, 2), "cal_fade": (7, 0)}
        for key, label, lo, hi in self.CAL_LOOK_FIELDS:
            r, c = spots[key]
            lab(r, c, label)
            sp = ttk.Spinbox(ct, from_=lo, to=hi, increment=1, textvariable=self.v[key], width=4)
            sp.grid(row=r, column=c + 1, sticky="w", pady=2)
            self.cal_look_widgets.append(sp)
        cb_fit = ttk.Checkbutton(ct, text=ui.CHK_CAL_FIT, variable=self.v_cal_fit)
        cb_fit.grid(row=8, column=0, columnspan=2, sticky="w", pady=2)
        self.cal_look_widgets.append(cb_fit)
        cb_shrink = ttk.Checkbutton(ct, text=ui.CHK_CAL_SHRINK, variable=self.v_cal_shrink)
        cb_shrink.grid(row=8, column=2, columnspan=2, sticky="w", padx=(14, 0), pady=2)
        self.cal_look_widgets.append(cb_shrink)
        self.cal_tf_labels = {"24h": ui.CAL_TIME_24, "12h": ui.CAL_TIME_12}
        self.cal_ws_labels = {"monday": ui.CAL_DAYS[0], "sunday": ui.CAL_DAYS[6]}
        lab(9, 0, ui.LBL_CAL_TIME_FORMAT)
        cb_tf = ttk.Combobox(ct, textvariable=self.v_cal_tf, state="readonly", width=9, values=list(self.cal_tf_labels.values()))
        cb_tf.grid(row=9, column=1, sticky="w", pady=2)
        lab(9, 2, ui.LBL_CAL_WEEK_START)
        cb_ws = ttk.Combobox(ct, textvariable=self.v_cal_ws, state="readonly", width=9, values=list(self.cal_ws_labels.values()))
        cb_ws.grid(row=9, column=3, sticky="w", pady=2)
        self.cal_look_widgets += [cb_tf, cb_ws]
        # --- colors (v1.1 step 5): only the keys the user overrides are stored; the rest follow the panel color.
        # A swatch is the picker: click it, or focus it and press Enter/Space.
        self.cal_colors = {}                 # working copy of calendar["colors"]; applied by Apply
        cf = ttk.LabelFrame(ct, text=ui.LBL_CAL_COLORS, padding=(6, 2))
        cf.grid(row=10, column=0, columnspan=4, sticky="we", pady=(8, 0))
        self.cal_col_ui = {}
        self.cal_color_widgets = []
        for i, key in enumerate(cal_settings.COLOR_KEYS):
            cell = ttk.Frame(cf)
            cell.grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 10), pady=1)
            ttk.Label(cell, text=ui.CAL_COLOR_NAMES[key], width=14).pack(side="left")
            sw = tk.Label(cell, width=3, relief="solid", bd=1, cursor="hand2", takefocus=True, highlightthickness=1)
            sw.pack(side="left", padx=3)
            for seq in ("<Button-1>", "<Return>", "<space>"):
                sw.bind(seq, lambda e, k=key: self.pick_cal_color(k))
            sw.bind("<Button-1>", lambda e, k=key: (e.widget.focus_set(), self.pick_cal_color(k)))
            uiwidgets.Tip(sw, ui.TIP_CAL_COLOR_CHANGE)
            mark = ttk.Label(cell, text="", width=1)
            mark.pack(side="left")
            rb = ttk.Button(cell, text=ui.BTN_CAL_COLOR_RESET, width=5, command=lambda k=key: self.reset_cal_color(k))
            rb.pack(side="left")
            self.cal_col_ui[key] = (sw, mark, rb)
            self.cal_color_widgets.append(cell)
        rv = ttk.Frame(cf)
        rv.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self.btn_cal_revert = ttk.Button(rv, text=ui.BTN_CAL_COLORS_REVERT, command=self.revert_cal_colors)
        self.btn_cal_revert.pack(side="left")
        ttk.Label(rv, text=ui.CAL_COLORS_NOTE, font=self._small_font, foreground="gray40").pack(side="left", padx=(10, 0))
        # --- default look (v1.1 step 6): one line; the full explanation is the button's tooltip
        df = ttk.Frame(ct)
        df.grid(row=11, column=0, columnspan=4, sticky="we", pady=(8, 0))
        self.btn_cal_look_default = ttk.Button(df, text=ui.BTN_CAL_MAKE_DEFAULT, command=self.make_cal_look_default)
        self.btn_cal_look_default.pack(side="left")
        uiwidgets.Tip(self.btn_cal_look_default, ui.CAL_LOOK_HELP)
        ttk.Label(df, text=ui.CAL_LOOK_HINT, font=self._small_font, foreground="gray40").pack(side="left", padx=(10, 0))
        self.lbl_cal_stack_note = ttk.Label(ct, text=ui.CAL_STACK_WIDTH_NOTE, font=self._small_font, foreground="gray40")
        self.lbl_cal_stack_note.grid(row=12, column=0, columnspan=4, sticky="w", pady=(4, 0))
        ct.columnconfigure(3, weight=1)

        # --- shared buttons (bottom, centered)
        bf = ttk.Frame(f)
        bf.pack(pady=(10, 2))
        ttk.Button(bf, text=ui.BTN_APPLY, command=self.apply).pack(side="left")
        ttk.Button(bf, text=ui.BTN_MAKE_DEFAULT, command=self.make_default).pack(side="left", padx=6)
        ttk.Button(bf, text=ui.BTN_RESET_DEFAULTS, command=lambda: self.reset(False)).pack(side="left")
        ttk.Button(bf, text=ui.BTN_FACTORY, command=lambda: self.reset(True)).pack(side="left", padx=6)
        self.msg = ttk.Label(f, text="")
        self.msg.pack(anchor="w", pady=(4, 0))
        self.cur = ""                       # selected panel name (stays "" when there is no panel)
        self.refresh_panels()
        self.select(name or next(iter(app.panels), ""))
        self._mark_clean()
        w.protocol("WM_DELETE_WINDOW", self.close)
        winutil.show_in_taskbar(w)          # Settings may appear in the taskbar while it is open

    # ------------------------------------------------------------ about tab
    def _build_about(self, a):
        """Name, icon and version on top; below, a read-only scrollable Help / What's new text."""
        head = ttk.Frame(a)
        head.pack(fill="x")
        self._about_icon = ImageTk.PhotoImage(app_icon_image(48), master=self.win)
        ttk.Label(head, image=self._about_icon).pack(side="left", padx=(0, 12))
        names = ttk.Frame(head)
        names.pack(side="left")
        big = tkfont.nametofont("TkDefaultFont").copy()
        big.configure(size=abs(int(big.cget("size"))) + 4, weight="bold")
        self._about_fonts = [big]
        self.about_name = ttk.Label(names, text=APP_NAME, font=big)
        self.about_name.pack(anchor="w")
        self.about_ver = ttk.Label(names, text=ui.ABOUT_VER_PREFIX + __version__)
        self.about_ver.pack(anchor="w")
        bar = ttk.Frame(a)
        bar.pack(fill="x", pady=(10, 4))
        self.v_about = tk.StringVar(value="help")
        for key, label in (("help", ui.ABOUT_HELP), ("news", ui.ABOUT_WHATS_NEW)):
            ttk.Radiobutton(bar, text=label, value=key, variable=self.v_about, style="Toolbutton",
                            command=self.show_about).pack(side="left", padx=(0, 6))
        box = ttk.Frame(a)
        box.pack(fill="both", expand=True)
        sb = ttk.Scrollbar(box, orient="vertical")
        sb.pack(side="right", fill="y")
        t = self.about_text = tk.Text(box, width=58, height=14, wrap="word", relief="flat", bd=0, padx=6, pady=4,
                                      yscrollcommand=sb.set, cursor="arrow", font="TkDefaultFont")
        t.pack(side="left", fill="both", expand=True)
        sb.configure(command=t.yview)
        base = tkfont.nametofont("TkDefaultFont")
        bold = base.copy()
        bold.configure(weight="bold")
        self._about_fonts.append(bold)
        t.tag_configure("ver", font=bold, spacing1=10, spacing3=2)
        t.tag_configure("sec", font=bold, spacing1=6)
        t.tag_configure("item", lmargin1=10, lmargin2=22)
        self.show_about()

    def show_about(self):
        """Fill the read-only text with Help (from strings.py) or What's new (from CHANGELOG.md)."""
        t = self.about_text
        t.configure(state="normal")
        t.delete("1.0", "end")
        if self.v_about.get() == "help":
            blocks = []
            for heading, items in ui.HELP_SECTIONS:
                blocks.append(("ver", heading))
                blocks.extend(("item", ui.ABOUT_BULLET + i) for i in items)
        else:
            blocks = changelog.render(changelog.load()) or [("item", ui.ABOUT_NO_CHANGELOG)]
        for tag, text in blocks:
            t.insert("end", text + "\n", tag)
        t.configure(state="disabled")
        t.yview_moveto(0)

    # ------------------------------------------------------------ calendar tab
    def _sync_cal_tab(self, is_calendar):
        present = str(self.tab["calendar"]) in self.nb.tabs()
        if is_calendar and not present:
            self.nb.insert(self.tab["general"], self.tab["calendar"], text=ui.TAB_CALENDAR)
        elif not is_calendar and present:
            self.nb.forget(self.tab["calendar"])

    # --- calendar list (a working copy; nothing reaches the panel before Apply)
    def _refresh_cal_list(self, select=None):
        self.cal_tree.delete(*self.cal_tree.get_children())
        for i, c in enumerate(self.cal_list):
            self.cal_tree.insert("", "end", iid=str(i), values=(
                "✓" if c["enabled"] else "", c["name"] or ui.CAL_ERR_UNNAMED, c["color"] or ui.CAL_COLOR_DEFAULT))
        if select is not None and 0 <= select < len(self.cal_list):
            self.cal_tree.selection_set(str(select))
        has = bool(self.cal_list)
        for b_ in (self.btn_cal_edit, self.btn_cal_remove):
            b_.state(["!disabled"] if has else ["disabled"])

    def _cal_selected(self):
        sel = self.cal_tree.selection()
        return int(sel[0]) if sel else None

    def ask_calendar(self, initial=None):
        """The add/edit window (modal). Returns a calendar dict or None. Tests replace this method."""
        return uiwidgets.CalendarDialog(self.win, initial).run()

    def cal_add(self):
        d = self.ask_calendar(None)
        if d:
            self.cal_list.append(cal_settings.clean_calendar(d))
            self._refresh_cal_list(len(self.cal_list) - 1)

    def cal_edit(self):
        i = self._cal_selected()
        if i is None:
            return
        d = self.ask_calendar(dict(self.cal_list[i]))
        if d:
            self.cal_list[i] = cal_settings.clean_calendar(d)
            self._refresh_cal_list(i)

    def cal_remove(self):
        i = self._cal_selected()
        if i is None:
            return
        del self.cal_list[i]
        self._refresh_cal_list(min(i, len(self.cal_list) - 1))

    def cal_import(self):
        """One-time import from an M Calendar config file. The path is not remembered; the file is only read."""
        from calendar_panel import source as cal_source
        p = filedialog.askopenfilename(parent=self.win, title=ui.DLG_CAL_IMPORT,
                                       filetypes=[(ui.FILETYPE_JSON, "*.json"), (ui.FILETYPE_ALL, "*.*")])
        if not p:
            return
        try:
            found = cal_source.read_sources(p)
        except cal_source.SourceError as e:
            messagebox.showerror(APP_NAME, ui.MSG_CAL_IMPORT_FAILED.format(error=e), parent=self.win)
            return
        self.cal_list, added = cal_source.merge(self.cal_list, found)
        self._refresh_cal_list(len(self.cal_list) - 1 if added else None)
        messagebox.showinfo(APP_NAME, ui.MSG_CAL_IMPORTED.format(n=added) if added else ui.MSG_CAL_IMPORT_NONE,
                            parent=self.win)

    def _load_calendar(self, pw):
        s = pw.cfg["calendar"]
        self.v["cal_view"].set(self.cal_view_labels[s["view"]])
        self.v["cal_weeks"].set(str(s["list_weeks"]))
        self.v["cal_refresh"].set(str(s["refresh_minutes"]))
        self._load_cal_look(s)
        self.cal_list = [dict(c) for c in s["calendars"]]
        self._refresh_cal_list(0 if s["calendars"] else None)

    def _derived_cal_palette(self):
        from calendar_panel import view as cal_view
        pw = self.app.panels.get(self.cur)
        return cal_view.make_palette(pw.cfg["color"], pw.cfg["content_color"]) if pw is not None else {}

    def _refresh_cal_colors(self):
        """Swatches show the overriding color or else the color derived from the applied panel color."""
        der = self._derived_cal_palette()
        for key, (sw, mark, rb) in self.cal_col_ui.items():
            own = key in self.cal_colors
            sw.configure(bg=self.cal_colors.get(key) or der.get(key, theme.EDGE_HEX))
            mark.configure(text=ui.CAL_COLOR_MARK if own else "")
            rb.state(["!disabled"] if own else ["disabled"])
        self.btn_cal_revert.state(["!disabled"] if self.cal_colors else ["disabled"])

    def pick_cal_color(self, key):
        cur = self.cal_colors.get(key) or self._derived_cal_palette().get(key)
        c = colorchooser.askcolor(color=cur, parent=self.win, title=ui.CAL_COLOR_NAMES[key])[1]
        if c:
            self.cal_colors = cal_settings.sanitize({"colors": {**self.cal_colors, key: c}})["colors"]
            self._refresh_cal_colors()

    def reset_cal_color(self, key):
        self.cal_colors.pop(key, None)
        self._refresh_cal_colors()

    def revert_cal_colors(self):
        if self.cal_colors and messagebox.askyesno(ui.APP_NAME, ui.CONFIRM_CAL_COLORS_REVERT, parent=self.win):
            self.cal_colors = {}
            self._refresh_cal_colors()

    def _load_cal_look(self, s):
        self.cal_colors = dict(s.get("colors") or {})
        self._refresh_cal_colors()
        for var, key in self.CAL_LOOK_KEYS.items():
            self.v[var].set(str(s[key]))
        self.v_cal_fit.set(bool(s["fit_boxes"]))
        self.v_cal_shrink.set(bool(s["shrink_empty"]))
        self.v_cal_tf.set(self.cal_tf_labels[s["time_format"]])
        self.v_cal_ws.set(self.cal_ws_labels[s["week_start"]])

    def _apply_calendar(self, pw):
        by_label = {v: k for k, v in self.cal_view_labels.items()}
        old_view = pw.cfg["calendar"]["view"]
        s = cal_settings.sanitize({
            **pw.cfg["calendar"],
            "view": by_label.get(self.v["cal_view"].get(), "list"),
            "list_weeks": self.v["cal_weeks"].get(), "refresh_minutes": self.v["cal_refresh"].get(),
            "calendars": [dict(c) for c in self.cal_list],
            **{key: self.v[var].get() for var, key in self.CAL_LOOK_KEYS.items()},
            "fit_boxes": bool(self.v_cal_fit.get()), "shrink_empty": bool(self.v_cal_shrink.get()),
            "time_format": {v: k for k, v in self.cal_tf_labels.items()}.get(self.v_cal_tf.get(), "24h"),
            "week_start": {v: k for k, v in self.cal_ws_labels.items()}.get(self.v_cal_ws.get(), "monday"),
            "colors": dict(self.cal_colors)})
        warn = ""
        for var, label, lo, hi in self.CAL_LOOK_FIELDS:
            entered = self.v[var].get().strip()
            n = s[self.CAL_LOOK_KEYS[var]]
            if not (entered.lstrip("-").isdigit() and int(entered) == n):
                warn += ui.MSG_CAL_RANGE.format(what=label.split(" (")[0], lo=lo, hi=hi, n=n)
        pw.cfg["calendar"] = s
        pw.cal_view_changed(old_view)                   # take the new view's width
        self.v["cal_weeks"].set(str(s["list_weeks"]))
        self.v["cal_refresh"].set(str(s["refresh_minutes"]))
        self._load_cal_look(s)
        if pw.cal is not None:
            pw.cal.scroll = 0
        pw.cal_settings_changed()
        return warn

    def show_tab(self, name):
        self.nb.select(self.tab[name])

    def _apply_hide(self):
        """Apply the 'Hide desktop icons' checkbox (called from Apply only). Returns a message to append
        ('' when nothing changed). Never runs in TEST mode (the box is disabled and the backend is None)."""
        app = self.app
        if app.test_mode or not app.icons.enabled:
            return ""
        want = bool(self.v_hide.get())
        if want == bool(app.cfg["general"]["hide_desktop_icons"]):
            return ""
        if not app.icons.set_enabled(want):
            self.v_hide.set(bool(app.cfg["general"]["hide_desktop_icons"]))
            return " " + ui.MSG_ICONS_FAILED
        return " " + (ui.MSG_ICONS_HIDDEN if want else ui.MSG_ICONS_RESTORED)

    def refresh_panels(self):
        self.cb_panel["values"] = list(self.app.panels)

    def select(self, name):
        if name not in self.app.panels:
            return
        self.cur = name
        pw = self.app.panels[name]
        c = pw.cfg
        self.v["panel"].set(name)
        self.v["name"].set(name)
        self.color = c["color"]
        pre = {v: n for n, v in PRESETS}
        self.v["color"].set(pre.get(c["color"], ui.COLOR_CUSTOM))
        self.v_op.set(round(c["opacity"] * 100))
        self.v["icon"].set(str(c["icon_size"]))
        self.sp_icon.state(["disabled"] if (pw.is_note or pw.is_calendar) else ["!disabled"])
        self._sync_cal_tab(pw.is_calendar)
        if pw.is_calendar:
            self._load_calendar(pw)
        self.v_start.set(c["start_collapsed"])
        self.v_hover.set(c["hover_open"])
        self.title_ed.set(theme.style_of(c, "title"))
        self.content_ed.set(theme.style_of(c, "content"))
        self._sw()
        self._mark_clean()

    # ------------------------------------------------------------ unsaved-changes handling
    def _panel_snapshot(self):
        """Everything the Panel/Title/Content/Calendar tabs hold, as comparable plain values."""
        return (self.v["name"].get(), self.v["color"].get(), self.color, self.v_op.get(), self.v["icon"].get(),
                self.v_start.get(), self.v_hover.get(), tuple(sorted(self.title_ed.get().items())),
                tuple(sorted(self.content_ed.get().items())), tuple(tuple(sorted(c.items())) for c in self.cal_list), self.v["cal_view"].get(),
                self.v["cal_weeks"].get(), self.v["cal_refresh"].get(),
                tuple(self.v[k].get() for k in self.CAL_LOOK_KEYS), bool(self.v_cal_fit.get()),
                bool(self.v_cal_shrink.get()), self.v_cal_tf.get(), self.v_cal_ws.get(),
                tuple(sorted(self.cal_colors.items())))

    def _mark_clean(self):
        self._clean = self._panel_snapshot()

    SNAP_CAL_VIEW, SNAP_CAL_WEEKS = 10, 11          # positions of the View / Weeks values in _panel_snapshot()

    def sync_cal_view(self, p):
        """The calendar panel's view (or weeks) was changed on the panel itself while this window is open:
        show the new value in the form and do NOT count it as an unsaved change. Other edits stay unsaved."""
        if p.name != self.cur or not p.is_calendar:
            return
        s = p.cfg["calendar"]
        self.v["cal_view"].set(self.cal_view_labels[s["view"]])
        self.v["cal_weeks"].set(str(s["list_weeks"]))
        now, clean = self._panel_snapshot(), list(self._clean)
        for i in (self.SNAP_CAL_VIEW, self.SNAP_CAL_WEEKS):
            clean[i] = now[i]
        self._clean = tuple(clean)

    def _general_dirty(self):
        app, g = self.app, self.app.cfg["general"]
        if bool(self.v_lock.get()) != bool(app.locked):
            return True
        if (bool(self.v_snap.get()) != bool(g["snap_enabled"]) or bool(self.v_snap_prev.get()) != bool(g["snap_preview"])
                or self.v_snap_dist.get().strip() != str(g["snap_distance"])
                or self.v_stack_gap.get().strip() != str(g["stack_gap"])):
            return True
        if app.test_mode:
            return False
        return (bool(self.v_auto.get()) != bool(g.get("autostart", True))
                or bool(self.v_hide.get()) != (bool(g.get("hide_desktop_icons")) and app.icons.enabled))

    def dirty(self):
        """Is there anything in this window that Apply has not applied yet?"""
        return self._panel_snapshot() != self._clean or self._general_dirty()

    def _load_general(self):
        app = self.app
        self.v_auto.set(bool(app.cfg["general"]["autostart"]))
        self.v_lock.set(app.locked)
        self.v_hide.set(bool(app.cfg["general"]["hide_desktop_icons"]) and app.icons.enabled)
        self._load_general_snapping()

    def _apply_snapping(self):
        """Apply the Snapping box. A value that is not a whole number in range is NOT applied (the box returns to the
        applied value, with a warning). A new stack gap re-stacks every stack from its top. Returns warning text."""
        app, g, warn = self.app, self.app.cfg["general"], ""
        vals = {"snap_enabled": bool(self.v_snap.get()), "snap_preview": bool(self.v_snap_prev.get())}
        for key, var, (lo, hi), what in (("snap_distance", self.v_snap_dist, stack.SNAP_DISTANCE_RANGE, ui.NAME_SNAP_DISTANCE),
                                         ("stack_gap", self.v_stack_gap, stack.STACK_GAP_RANGE, ui.NAME_STACK_GAP)):
            raw = var.get().strip()
            if raw.isdigit() and lo <= int(raw) <= hi:
                vals[key] = int(raw)
            else:
                vals[key] = g[key]
                warn += ui.MSG_SNAP_RANGE.format(what=what, lo=lo, hi=hi, n=g[key])
        app.set_snapping(vals)
        self._load_general_snapping()
        return warn

    def _load_general_snapping(self):
        g = self.app.cfg["general"]
        self.v_snap.set(bool(g["snap_enabled"]))
        self.v_snap_prev.set(bool(g["snap_preview"]))
        self.v_snap_dist.set(str(g["snap_distance"]))
        self.v_stack_gap.set(str(g["stack_gap"]))

    def ask_unsaved(self):
        """Modal 'Unsaved changes' question. Returns 'apply', 'discard' or 'cancel' (dialog X = cancel)."""
        d = tk.Toplevel(self.win)
        d.title(ui.UNSAVED_TITLE)
        d.transient(self.win)
        d.resizable(False, False)
        d.attributes("-topmost", True)
        res = {"v": "cancel"}

        def pick(v):
            res["v"] = v
            d.destroy()

        ttk.Label(d, text=ui.UNSAVED_MSG, padding=16).pack()
        bf = ttk.Frame(d, padding=(16, 0, 16, 12))
        bf.pack()
        for v, label in (("apply", ui.BTN_APPLY), ("discard", ui.BTN_DISCARD), ("cancel", ui.BTN_CANCEL)):
            ttk.Button(bf, text=label, command=lambda v=v: pick(v)).pack(side="left", padx=4)
        d.protocol("WM_DELETE_WINDOW", lambda: pick("cancel"))
        d.bind("<Escape>", lambda e: pick("cancel"))
        d.grab_set()
        self.win.wait_window(d)
        return res["v"]

    def confirm_overwrite(self):
        return messagebox.askyesno(ui.APP_NAME, ui.CONFIRM_OVERWRITE, parent=self.win)

    def _resolve_unsaved(self):
        """True: it is fine to leave/switch (nothing unsaved, or Apply worked, or Discard). False: stay."""
        if not self.dirty():
            return True
        choice = self.ask_unsaved()
        if choice == "apply":
            return bool(self.apply())
        if choice == "discard":
            self._load_general()
            return True
        return False

    def request_select(self, name):
        """Switch the form to another panel, asking first when there are unapplied changes."""
        if name == self.cur:
            return
        if self._resolve_unsaved():
            self.select(name)
        else:
            self.v["panel"].set(self.cur)

    def close(self):
        """Window X: ask when something is unapplied; Cancel keeps the window open."""
        if self._resolve_unsaved():
            self.win.destroy()

    def _sw(self):
        self.sw.configure(bg=self.color)

    def pick_color(self):
        c = colorchooser.askcolor(color=self.color, parent=self.win)[1]
        if c:
            self.color = c
            self.v["color"].set(ui.COLOR_CUSTOM)
            self._sw()

    def apply(self):
        """Apply everything in the window. Returns False when it could not finish (rename refused)."""
        app = self.app
        hide_msg = self._apply_hide() + self._apply_snapping()
        if not app.test_mode and bool(self.v_auto.get()) != bool(app.cfg["general"].get("autostart", True)):
            app.set_autostart(self.v_auto.get())
        if bool(self.v_lock.get()) != bool(app.locked):
            app.set_lock(self.v_lock.get())
        p = app.panels.get(self.cur)
        if p is None:
            self.msg.configure(text=ui.MSG_APPLIED + hide_msg)
            return True
        sel = dict(PRESETS).get(self.v["color"].get())
        c = p.cfg
        c["color"] = sel if (sel and self.v["color"].get() != ui.COLOR_CUSTOM) else self.color
        c["opacity"] = self.v_op.get() / 100
        raw = self.v["icon"].get().strip()
        n_icon = normalize_icon_size(raw if raw else ICON_DEFAULT)
        warn = ""
        if not raw.lstrip("-").isdigit() or not ICON_MIN <= int(raw) <= ICON_MAX:
            warn = ui.MSG_ICON_RANGE.format(lo=ICON_MIN, hi=ICON_MAX, n=n_icon)
        self.v["icon"].set(str(n_icon))
        c["icon_size"] = n_icon
        for role, label, ed in (("title", ui.TAB_TITLE, self.title_ed), ("content", ui.TAB_CONTENT, self.content_ed)):
            st = ed.get()
            if not ed.size_valid():
                warn += ui.MSG_TEXT_RANGE.format(what=label, lo=theme.SIZE_MIN, hi=theme.SIZE_MAX, n=st["size"])
            for k, v in st.items():
                c[f"{role}_{k}"] = v
            ed.set(st)
        c["start_collapsed"], c["hover_open"] = self.v_start.get(), self.v_hover.get()
        new = self.v["name"].get().strip()
        p.apply_cfg()
        if p.is_calendar:
            warn += self._apply_calendar(p)
        app.save()
        if new and new != self.cur:
            r = app.do_rename(p, new)
            if r.ok:
                self.cur = new
                self.refresh_panels()
                self.select(new)
            else:
                self.msg.configure(text=r.message + hide_msg)
                return False
        self._mark_clean()
        self.msg.configure(text=ui.MSG_APPLIED + warn + hide_msg)
        return True

    def make_default(self):
        self.apply()
        g = self.app.cfg["general"]
        snapping = {SNAPPING_KEY: {k: g[k] for k in stack.GENERAL_KEYS}}   # the three Snapping settings travel with it
        p = self.app.panels.get(self.cur)
        look = {k: p.cfg[k] for k in APPEARANCE_KEYS} if p is not None else {}
        self.app.save_defaults(**look, **snapping)                            # the saved calendar look stays
        self.msg.configure(text=ui.MSG_DEFAULT_SAVED)

    def make_cal_look_default(self):
        """Settings > Calendar: save the APPLIED look of this calendar panel (only calendar_panel.settings.LOOK_KEYS)
        as the user's default for new Calendar panels and 'Revert to defaults'."""
        pw = self.app.panels.get(self.cur)
        if pw is None or not pw.is_calendar:
            return
        if self.dirty():
            messagebox.showinfo(ui.APP_NAME, ui.MSG_CAL_LOOK_APPLY_FIRST, parent=self.win)
            return
        if not messagebox.askyesno(ui.APP_NAME, ui.CONFIRM_CAL_LOOK_DEFAULT, parent=self.win):
            return
        self.app.save_defaults(**{CAL_LOOK_KEY: cal_settings.look_of(pw.cfg["calendar"])})
        self.msg.configure(text=ui.MSG_CAL_LOOK_SAVED)

    def reset(self, factory):
        p = self.app.panels.get(self.cur)
        if p is None or not self.confirm_overwrite():
            return
        p.cfg.update(self.app.defaults(factory))
        if p.is_calendar:                       # look only: source, calendar choice, view, weeks, refresh stay
            p.cfg["calendar"] = cal_settings.with_look(p.cfg.get("calendar"), self.app.calendar_look(factory))
        p.apply_cfg()
        self.app.save()
        self.select(self.cur)
        self._load_general()
        # Snapping: only LOADED into the boxes (the window becomes dirty); Apply puts it in force, like every other
        # General setting. Same rule as the Calendar colors' "Revert to derived colors".
        d = self.app.snapping_defaults(factory)
        self.v_snap.set(bool(d["snap_enabled"]))
        self.v_snap_prev.set(bool(d["snap_preview"]))
        self.v_snap_dist.set(str(d["snap_distance"]))
        self.v_stack_gap.set(str(d["stack_gap"]))
        pending = self._general_dirty()
        self.msg.configure(text=(ui.MSG_FACTORY_LOADED if factory else ui.MSG_DEFAULTS_LOADED)
                           + (ui.MSG_SNAP_PENDING if pending else ""))


# ------------------------------------------------------------------ entry point
def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=APP_NAME)
    ap.add_argument("--desktop", help=ui.ARG_DESKTOP)
    ap.add_argument("--public-desktop", help=ui.ARG_PUBLIC)
    ap.add_argument("--data", help=ui.ARG_DATA)
    ap.add_argument("--restore-desktop-icons", action="store_true",
                    help=ui.ARG_RESTORE_ICONS)
    ap.add_argument("--autostart", action="store_true", help=ui.ARG_AUTOSTART)
    ap.add_argument("--quit", action="store_true", help=ui.ARG_QUIT)
    return ap.parse_args(argv)


LOG_FILE = "mpanels.log"


def instance_name(test_desktop=None):
    """Name of the single-instance mutex/event. TEST mode gets its own name per test folder so a test run
    never collides with (or signals) the real program."""
    if test_desktop:
        h = hashlib.md5(os.path.normcase(os.path.abspath(test_desktop)).encode("utf-8")).hexdigest()[:12]
        return "MPanels_Test_" + h
    return "MPanels_SingleInstance"


def build_context(args):
    """(ctx, data_dir, test_mode). The real desktop is used ONLY when test mode is off."""
    if args.desktop:
        desk = os.path.abspath(args.desktop)
        real = winutil.get_real_desktop()
        if fileops.is_inside(desk, real) or fileops.is_inside(real, desk):
            raise SystemExit(ui.ERR_TEST_REAL_DESKTOP.format(path=desk))
        os.makedirs(desk, exist_ok=True)
        pub = os.path.abspath(args.public_desktop) if args.public_desktop else os.path.join(desk + "_ortak")
        os.makedirs(pub, exist_ok=True)
        data = os.path.abspath(args.data) if args.data else desk + "_veri"
        return fileops.Ctx(desk, pub), data, True
    return (fileops.Ctx(winutil.get_real_desktop(), winutil.get_public_desktop()),
            os.path.abspath(args.data) if args.data else APP_DIR, False)


def main(argv=None):
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    args = parse_args(argv)
    if args.restore_desktop_icons:
        if args.desktop:
            raise SystemExit(ui.ERR_TEST_NO_ICONS)
        path = os.path.join(os.path.abspath(args.data) if args.data else APP_DIR, "config.json")
        cfg = load_json(path, {})
        g = cfg.setdefault("general", {})
        ok = deskicons.IconHider(g, winutil.DesktopIconsBackend(), lambda: save_json(path, cfg)).restore_now()
        print(ui.MSG_RESTORE_OK if ok else ui.MSG_RESTORE_FAIL)
        return
    log = applog.setup(os.path.join(APP_DIR, LOG_FILE))
    ctx, data, test = build_context(args)
    name = instance_name(ctx.desktop if test else None)
    if args.quit:                        # ask the running copy (same mode) to quit, then leave
        winutil.signal_running_instance(name, retries=3, kind=winutil.QUIT)
        return
    if not winutil.acquire_single_instance(name):
        # Already running: do not open a second set of panels; ask the running copy to come forward.
        # (A silent autostart launch just exits.)
        if not args.autostart:
            winutil.signal_running_instance(name)
        log.info(ui.ERR_ALREADY_RUNNING.format(app=APP_NAME))
        return
    if args.autostart and not test:      # started from Windows startup: quietly exit if the flag is off
        cfg = load_json(os.path.join(data, "config.json"), {})
        if not cfg.get("general", {}).get("autostart", True):
            return
    applog.log_startup(log, __version__, "TEST" if test else "normal", ctx.desktop, data)
    app = App(ctx, data, test_mode=test, instance_name=name)
    app.hard_exit_s = HARD_EXIT_SECONDS
    app.root.mainloop()
    log.info("M Panels exited normally")
    logging.shutdown()
    os._exit(0)                          # leave no thread (tray, timers) behind


if __name__ == "__main__":
    main()
