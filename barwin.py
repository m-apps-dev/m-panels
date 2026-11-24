"""The bar (v1.2 step 1): a flat strip along the top of the main monitor, always on top, never taking focus.
Sections: Info (date and time, on the right; step 1) and Tasks (one button per open window, from the left; step 2).
The left end (theme.BAR_LEFT_RESERVE, derived: 72 px): 0-31 the Start icon (step 5; empty when it is off), then 4 px, the
search button (step 4, 36-67), 4 px, and the window buttons.

BarWindow  the tkinter window (drawing, tooltips, the "+N" menu, right-click menu "Settings…").
Bar        the controller: owns the AppBar session, the owner/message window, the once-a-minute clock, the Tasks
           controller (tasks.py). Everything the
           outside world does (Windows calls, the message window, the clock, the window) is handed in, so tests use
           made-up ones. It never touches Tk from another thread: messages arrive through App._poll -> Bar.handle."""
import tkinter as tk
from tkinter import font as tkfont

import appbar
import applog
import infoclock
import search as search_mod
import strings as ui
import tasks as tasks_mod
import theme
import winutil

LOG = applog.get_logger()


class Painter:
    """Draws bar buttons on a canvas. One drawing code for the bar and for the sample strip in Settings. Keeps the
    PhotoImages of the button backgrounds (a canvas does not), made by theme.make_btn (rounded, RGBA)."""

    def __init__(self, master):
        self._master = master
        self._photos = {}

    def background(self, w, h, state, pal):
        fill, frame = theme.btn_colors(pal, state)
        key = (w, h, fill, frame)
        p = self._photos.get(key)
        if p is None:
            if len(self._photos) > 200:
                self._photos.clear()
            from PIL import ImageTk
            p = self._photos[key] = ImageTk.PhotoImage(theme.make_btn(w, h, fill, frame), master=self._master)
        return p

    def button(self, cv, x, w, state, pal, icon, label, font, letter=""):
        """One button at `x` (top = theme.BAR_BTN_TOP). `icon`: a PhotoImage; `label`: the title shown ("" = icon only);
        `letter`: drawn over the icon (letter tile). Returns what was drawn (for the hit areas and tests)."""
        y0, h = theme.BAR_BTN_TOP, theme.BAR_BTN_H
        cv.create_image(x, y0, image=self.background(w, h, state, pal), anchor="nw")
        cy = y0 + h // 2
        if label:
            ix = x + theme.BAR_BTN_PAD
        else:
            ix = x + (w - theme.BAR_ICON) // 2
        if icon is not None:
            cv.create_image(ix, cy - theme.BAR_ICON // 2, image=icon, anchor="nw")
            if letter:
                cv.create_text(ix + theme.BAR_ICON // 2, cy, text=letter, font=font, fill=pal["text"])
        if label:
            cv.create_text(ix + theme.BAR_ICON + theme.BAR_ICON_GAP, cy, text=label, anchor="w", font=font,
                           fill=pal["dim_text"] if state == "minimized" else pal["text"])
        fill, frame = theme.btn_colors(pal, state)
        return {"fill": fill, "frame": frame, "h": h, "state": state}


class BarWindow:
    def __init__(self, root, on_settings, popup, test_tag=""):
        self.test_tag = test_tag
        self.top = t = tk.Toplevel(root)
        t.withdraw()
        t.overrideredirect(True)
        self.pal = theme.bar_palette()                   # colors in use (set_look changes them)
        self.show_titles = True
        t.configure(bg=self.pal["background"])
        t.attributes("-topmost", True)
        t.geometry("1x1+0+0")
        self.cv = tk.Canvas(t, bg=self.pal["background"], highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)
        winutil.make_bar_window(t)                       # while withdrawn: no taskbar button, no focus
        self._menu = tk.Menu(t, tearoff=0)
        self._menu.add_command(label=ui.BAR_MENU_SETTINGS, command=self._cmd(on_settings))
        self._task_menu = tk.Menu(t, tearoff=0)          # right-click on a window button: Close window, nothing else
        self._task_menu.add_command(label=ui.BAR_MENU_CLOSE)
        self._popup = popup
        self._chosen = False                             # did the open menu run a command?
        self.cv.bind("<Button-3>", self._on_right_click)
        self.rect, self.text = None, ""
        self._mapped = False
        self.view = None                                 # tasks.View: what to draw as buttons (None = no Tasks section)
        self.buttons = []                                # what the last draw put on the canvas (also the hit areas)
        self._font = None
        self._tip = self._tip_job = self._tip_for = None
        self._hover = None                               # hwnd of the button under the pointer (-1: the "+N" button)
        self.painter = Painter(t)
        self.cv.bind("<Motion>", self._on_motion)
        self.cv.bind("<Leave>", self._on_leave)
        self.cv.bind("<ButtonPress-1>", self._on_press)
        self.cv.bind("<ButtonRelease-1>", self._on_release)
        self.on_task = None                              # on_task(hwnd, prev_foreground): set by the Bar
        self.on_close = None                             # on_close(hwnd): "Close window" in a button's menu: set by the Bar
        self.foreground = lambda: 0                      # () -> the window active before a click (never ours): set by the Bar
        self.give_back = None                            # give_back(hwnd): foreground back after a menu: set by the Bar
        self.menu_foreground = True                      # False only for a bar built with no foreground source at all (some tests)
        self._press = None
        self.search_on = False                           # the search button is drawn (the Bar switches it)
        self.search_active = False                       # the search window is open: the button is drawn "active"
        self.search_button = None                        # what the last draw put on the canvas for it (also its hit area)
        self.search_open = lambda: False                 # () -> is the search window open: set by the Bar
        self.on_search = None                            # on_search(was_open, prev_foreground): set by the Bar
        self._press_open = False
        self._search_photos = {}
        self.start_on = False                            # the Start button is drawn (the Bar switches it)
        self.start_button = None                         # what the last draw put on the canvas for it (also its hit area)
        self.on_start = None                             # on_start(): set by the Bar
        self._start_photos = {}
        self.icon_source = theme.tile_icon               # icon_source(size) -> PIL RGBA (tests may replace it)
        self.cv.bind("<Double-Button-1>", self._on_double)

    def show(self, rect):
        """Put the window exactly on `rect` (left, top, right, bottom), topmost, without activating it."""
        self.rect = tuple(rect)
        x, y, w, h = rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]
        self.top.geometry("%dx%d+%d+%d" % (w, h, x, y))
        if not self._mapped:
            self._mapped = True
            self.top.deiconify()                         # the only deiconify it gets
        self.top.update_idletasks()
        winutil.overlay_show(self.top, x, y, w, h)
        self.draw()

    def set_text(self, text):
        self.text = text
        self.draw()

    def set_tasks(self, view):
        self.view = view
        self.draw()

    def set_search(self, on):
        self.search_on = bool(on)
        if not on:
            self.search_active = False
        self.draw()

    def set_start(self, on):
        self.start_on = bool(on)
        self.draw()

    def set_search_active(self, on):
        self.search_active = bool(on)
        self.draw()

    def set_look(self, colors, show_titles):
        """Settings > Apply: the five user colors (only the changed ones) and "Show window titles". Redraws at once."""
        self.pal = theme.bar_palette(colors)
        self.show_titles = bool(show_titles)
        self.top.configure(bg=self.pal["background"])
        self.cv.configure(bg=self.pal["background"])
        self._hover = None
        self.draw()

    def draw(self):
        if self.rect is None:
            return
        w, h = self.rect[2] - self.rect[0], self.rect[3] - self.rect[1]
        pal = self.pal
        font = theme.tk_font_spec(theme.CONTENT_STYLE)
        if self._font is None:
            self._font = tkfont.Font(self.top, font=font)
        cv = self.cv
        cv.delete("all")
        cv.create_line(0, h - 1, w, h - 1, fill=pal["line"])
        cy = (h - 1) // 2
        if self.test_tag:
            cv.create_text(theme.BAR_PAD_X, cy, text=self.test_tag, anchor="w", fill=pal["text"], font=font)
        right = w - theme.BAR_PAD_X
        if self.text:
            cv.create_text(right, cy, text=self.text, anchor="e", fill=pal["text"], font=font)
            right -= self._font.measure(self.text) + 2 * theme.BAR_PAD_X
        self._draw_start(font)
        self._draw_search(font)
        self._draw_tasks(h, right, font)

    def _search_photo(self, color):
        p = self._search_photos.get(color)
        if p is None:
            from PIL import ImageTk
            p = self._search_photos[color] = ImageTk.PhotoImage(theme.search_icon(theme.BAR_ICON, color), master=self.top)
        return p

    def _start_icon_photo(self, size, hover):
        """The app icon for the Start button, made once per (size, hover) and kept (a draw never reads the file). None when
        the icon cannot be had at all (no source, or it raised or gave nothing): the caller draws the dots instead."""
        key = ("icon", size, bool(hover))
        if key in self._start_photos:
            return self._start_photos[key]
        photo = None
        try:
            img = self.icon_source(size) if self.icon_source is not None else None
            if img is not None:
                if hover:
                    img = theme.start_glow(img)
                from PIL import ImageTk
                photo = ImageTk.PhotoImage(img, master=self.top)
        except Exception:                                # noqa: BLE001
            LOG.warning("bar: the Start icon could not be made; drawing the dots", exc_info=True)
            photo = None
        self._start_photos[key] = photo
        return photo

    def _start_dots_photo(self, color):
        key = ("dots", color)
        p = self._start_photos.get(key)
        if p is None:
            from PIL import ImageTk
            p = self._start_photos[key] = ImageTk.PhotoImage(theme.start_icon(theme.BAR_ICON, color), master=self.top)
        return p

    def _draw_start(self, font):
        """The Start button: four colored tiles (theme.tile_icon, the same drawing as the tray icon), no frame and no fill,
        1 px in from the zone's edges; hover brightens it, there is no "active" look. The hit area is the whole Start zone
        (x 0-31, any y). If the icon cannot be made the old 3x3 dots button is drawn instead (a log line says so).
        Off: nothing is drawn, the place stays empty and nothing else moves."""
        self.start_button = None
        if not self.start_on:
            return
        x, w, pal = theme.BAR_START_BTN_X, theme.BAR_START_BTN_W, self.pal
        hover = self._hover == "start"
        state = "hover" if hover else "normal"
        size = theme.BAR_START_ICON
        photo = self._start_icon_photo(size, hover)
        if photo is None:                                # fallback: the dots on a 3c button
            bx, bw = 0, w
            look = self.painter.button(self.cv, bx, bw, state, pal, self._start_dots_photo(pal["text"]), "", font)
            self.start_button = {"x": x, "w": w, "hwnd": 0, "kind": "start", "title": "", "state": state, "icon": 0,
                                 "fill": look["fill"], "frame": look["frame"], "h": look["h"]}
            return
        ix, iy = theme.start_icon_pos(size, self.rect[3] - self.rect[1])
        self.cv.create_image(ix, iy, image=photo, anchor="nw")
        self.start_button = {"x": x, "w": w, "hwnd": 0, "kind": "start", "title": "", "state": state, "icon": size,
                             "icon_xy": (ix, iy), "fill": None, "frame": None, "h": size}

    def _draw_search(self, font):
        """The magnifier button at the left end (no label). Off: nothing is drawn and the place stays empty."""
        self.search_button = None
        if not self.search_on:
            return
        x, w, pal = theme.BAR_SEARCH_BTN_X, theme.BAR_SEARCH_BTN_W, self.pal
        state = "active" if self.search_active else ("hover" if self._hover == "search" else "normal")
        look = self.painter.button(self.cv, x, w, state, pal, self._search_photo(pal["text"]), "", font)
        self.search_button = {"x": x, "w": w, "hwnd": 0, "kind": "search", "title": "", "state": state,
                              "fill": look["fill"], "frame": look["frame"], "h": look["h"]}

    def _state(self, key, minimized, active):
        if active:
            return "active"
        if key == self._hover:
            return "hover"
        return "minimized" if minimized else "normal"

    def _draw_tasks(self, h, right, font):
        """The buttons: from BAR_LEFT_RESERVE to `right`. Each one is recorded in self.buttons (hit areas, tests)."""
        self.buttons = []
        view, cv, pal = self.view, self.cv, self.pal
        if view is None or not view.entries:
            return
        left = theme.BAR_LEFT_RESERVE
        n = len(view.entries)
        if self.show_titles:
            k, bw, more = tasks_mod.layout(n, right - left)
            more_w = bw
        else:
            k, bw, more, more_w = tasks_mod.layout_icons(n, right - left, self._font.measure,
                                                         lambda m: ui.BAR_OVERFLOW.format(n=m))
        if bw <= 0:
            return
        x = left
        for i in range(k + (1 if more else 0)):
            overflow = i == k
            e = None if overflow else view.entries[i]
            width = more_w if overflow else bw
            letter = ""
            if overflow:
                shown = ui.BAR_OVERFLOW.format(n=more)
                look = self.painter.button(cv, x, width, self._state(-1, False, False), pal, None, "", font)
                cv.create_text(x + width // 2, theme.BAR_BTN_TOP + theme.BAR_BTN_H // 2, text=shown, fill=pal["text"],
                               font=font)
            else:
                active = e.hwnd == view.active
                state = self._state(e.hwnd, e.minimized, active)
                dim = e.minimized and view.dim_of is not None
                icon = view.dim_of(e.hwnd) if dim else view.icon_of(e.hwnd)
                text_on = self.show_titles and tasks_mod.text_room(width) >= theme.BAR_TEXT_MIN_ROOM
                shown = tasks_mod.fit_text(e.title, tasks_mod.text_room(width), self._font.measure) if text_on else ""
                if not self.show_titles and view.has_icon is not None and not view.has_icon(e.hwnd):
                    letter = tasks_mod.tile_letter(e.title)
                look = self.painter.button(cv, x, width, state, pal, icon, shown, font, letter=letter)
            self.buttons.append({"x": x, "w": width, "hwnd": 0 if overflow else e.hwnd,
                                 "kind": "more" if overflow else "task", "title": "" if overflow else e.title,
                                 "shown": shown, "active": (not overflow) and active, "minimized": bool(e and e.minimized),
                                 "rest": view.entries[k:] if overflow else (), "state": look["state"],
                                 "fill": look["fill"], "frame": look["frame"], "h": look["h"], "letter": letter})
            x += width + theme.BAR_BTN_GAP

    # ------------------------------------------------------------ pointer: tooltip, "+N" menu
    def hit(self, x):
        st = self.start_button
        if st is not None and st["x"] <= x < st["x"] + st["w"]:
            return st
        sb = self.search_button
        if sb is not None and sb["x"] <= x < sb["x"] + sb["w"]:
            return sb
        for b in self.buttons:
            if b["x"] <= x < b["x"] + b["w"]:
                return b
        return None

    def _hide_tip(self):
        if self._tip_job is not None:
            try:
                self.top.after_cancel(self._tip_job)
            except Exception:                            # noqa: BLE001
                pass
            self._tip_job = None
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None
        self._tip_for = None

    def _on_leave(self, e=None):
        self._hide_tip()
        self._set_hover(None)

    def _set_hover(self, key):
        """The button under the pointer changed: redraw (a few cached images, nothing else)."""
        if key != self._hover:
            self._hover = key
            self.draw()

    def _on_motion(self, e):
        b = self.hit(e.x)
        self._set_hover(None if b is None else (b["kind"] if b["kind"] in ("search", "start")
                                                else (-1 if b["kind"] == "more" else b["hwnd"])))
        key = b["hwnd"] if b and b["kind"] == "task" else None
        if key == self._tip_for:
            return
        self._hide_tip()
        if key is not None:
            self._tip_for = key
            self._tip_job = self.top.after(theme.BAR_TIP_DELAY_MS, lambda: self._show_tip(b, e.x_root))

    def _show_tip(self, b, x_root):
        """The full title under the button (always: a title that fits gains nothing, one that is cut shows it all)."""
        self._tip_job = None
        if self.rect is None:
            return
        t = tk.Toplevel(self.top)
        t.withdraw()
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        tk.Label(t, text=b["title"], bg=self.pal["tip_bg"], fg=self.pal["text"],
                 font=theme.tk_font_spec(theme.CONTENT_STYLE), padx=8, pady=3).pack()
        winutil.make_bar_window(t)
        t.geometry("+%d+%d" % (max(self.rect[0], x_root - 20), self.rect[3] + 4))
        t.deiconify()
        self._tip = t

    def _on_press(self, e):
        """The button under the mouse and the foreground window, both noted NOW: a menu opened later may change the
        foreground, and the "already active -> minimize" rule needs the window that was active BEFORE the click."""
        try:
            self._hide_tip()
            self._press = (self.hit(e.x), int(self.foreground() or 0))
            self._press_open = bool(self.search_open())          # was the search window open when the mouse went down
        except Exception:                                # noqa: BLE001  (never break a Tk callback)
            self._press = None
            tasks_mod.safe_log("exception", "bar: press failed")

    def _on_release(self, e):
        try:
            press, self._press = self._press, None
            b = self.hit(e.x)
            if press is None or press[0] is None or b is not press[0]:
                return                                   # released elsewhere: not a click
            self._clicked(b, press[1])
        except Exception:                                # noqa: BLE001
            tasks_mod.safe_log("exception", "bar: click failed")

    def _on_double(self, e):
        """The second press of a double click. On the search or Start button it does NOTHING (the first click already
        acted); on anything else it is an ordinary press, as before."""
        b = self.hit(e.x)
        if b is not None and b["kind"] in ("search", "start"):
            return "break"
        self._on_press(e)

    def _clicked(self, b, prev):
        if b["kind"] == "start":
            if self.on_start is not None:
                self.on_start()
        elif b["kind"] == "search":
            if self.on_search is not None:
                self.on_search(self._press_open, prev)
        elif b["kind"] == "task":
            self._activate(b["hwnd"], prev)
        elif b["kind"] == "more":
            m = tk.Menu(self.top, tearoff=0)
            for t in b["rest"]:
                m.add_command(label=tasks_mod.fit_text(t.title, 480, self._font.measure),
                              command=self._cmd(lambda h=t.hwnd: self._activate(h, prev)))
            self._open_menu(m, self.top.winfo_rootx() + b["x"], self.top.winfo_rooty() + self.rect[3] - self.rect[1])

    # ------------------------------------------------------------ menus (Win32 rule: the owner must be the foreground)
    def _cmd(self, fn):
        """A menu command that also notes "something was chosen": then the command decides the foreground (Settings
        comes to the front, a "+N" row brings its window), and nothing is given back."""
        def run():
            self._chosen = True
            return fn()
        return run

    def _open_menu(self, menu, x, y):
        """Open a menu from the bar. Before: the window that was active (never one of ours) is noted and the bar takes
        the foreground, so Escape and an outside click close the menu. After it closes WITHOUT a command: the foreground
        goes back to the noted window. Never raises into Tk."""
        self._chosen = False
        prev = 0
        if self.menu_foreground:
            try:
                prev = int(self.foreground() or 0)
                ok = winutil.take_foreground(self.top)
                tasks_mod.safe_log("info", "bar: menu opens; window to give back: %d; bar took the foreground: %s", prev, ok)
            except Exception:                            # noqa: BLE001
                tasks_mod.safe_log("exception", "bar: preparing the menu failed")
        try:
            self._popup(menu, x, y)
        finally:
            if self.menu_foreground:
                winutil.post_null(self.top)
                self._menu_closed(prev)

    def _menu_closed(self, prev):
        """The menu is gone. A chosen command may still be about to run (Tk runs it from the idle loop), so the decision
        waits a moment; a command that ran sets _chosen first."""
        try:
            self.top.after(60, lambda: self._finish_menu(prev))
        except Exception:                                # noqa: BLE001
            self._finish_menu(prev)

    def _finish_menu(self, prev):
        try:
            if self._chosen:
                tasks_mod.safe_log("info", "bar: menu closed with a command; the foreground is left to it")
            elif self.give_back is not None and prev:
                self.give_back(prev)
        except Exception:                                # noqa: BLE001
            tasks_mod.safe_log("exception", "bar: giving the foreground back failed")

    def _on_right_click(self, e):
        """A window button: Close window only; the empty bar, the date and the "+N" button: Settings… only."""
        try:
            b = self.hit(e.x)
            menu = self._menu
            if b is not None and b["kind"] == "task":
                self._task_menu.entryconfigure(0, command=self._cmd(lambda h=b["hwnd"]: self._close(h)))
                menu = self._task_menu
            self._open_menu(menu, e.x_root, e.y_root)
        except Exception:                                # noqa: BLE001  (never break a Tk callback)
            tasks_mod.safe_log("exception", "bar: right click failed")

    def _close(self, hwnd):
        try:
            if self.on_close is not None:
                self.on_close(hwnd)
        except Exception:                                # noqa: BLE001
            tasks_mod.safe_log("exception", "bar: close failed")

    def _activate(self, hwnd, prev):
        try:
            if self.on_task is not None:
                self.on_task(hwnd, prev)
        except Exception:                                # noqa: BLE001
            tasks_mod.safe_log("exception", "bar: click failed")

    def destroy(self):
        self._hide_tip()
        try:
            self.top.destroy()
        except tk.TclError:
            pass


class Bar:
    def __init__(self, root, info, backend, shell, monitors, now, on_settings, popup, on_layout, test_mode=False,
                 window_factory=BarWindow, tasks_cfg=None, tasks_factory=None, keeper_factory=None, colors=None,
                 search_cfg=None, search_factory=None, start_cfg=None, start_factory=None):
        """info: the bar.info dict (read live, so Settings > Apply is seen at once); shell: an object with hwnd /
        callback / close(); monitors(): a fresh probe; now(): datetime; on_layout(): the work area may have changed."""
        self.root, self.info, self.backend, self.shell = root, info, backend, shell
        self._monitors, self.now, self._on_layout = monitors, now, on_layout
        self._on_settings, self._popup, self.test_mode = on_settings, popup, test_mode
        self._window_factory = window_factory
        self.tasks_cfg = tasks_cfg if tasks_cfg is not None else {"enabled": False}
        self._tasks_factory = tasks_factory
        self.colors = colors if colors is not None else {}      # bar.colors: only the colors the user changed (read live)
        self._keeper_factory = keeper_factory            # Tasks off: reads the foreground at the right click
        self.keeper = None
        self.search_cfg = search_cfg if search_cfg is not None else {"enabled": False}      # bar.search (read live)
        self._search_factory = search_factory            # search_factory(bar) -> searchwin.Search
        self.search = None                               # the search controller while the button is on
        self.hotkey_name = "off"                         # the shortcut key that is registered now
        self.start_cfg = start_cfg if start_cfg is not None else {"enabled": False}         # bar.start (read live)
        self._start_factory = start_factory              # start_factory(bar) -> startmenu.Start
        self.startmenu = None                            # the Start controller while the button is on
        self._rect = None                                # where the bar is (the search window opens under it)
        self.tasks = None                                # tasks.Tasks while the section is on
        self.session = self.win = None
        self._job = None
        self._shown = None

    # ------------------------------------------------------------ lifecycle
    def start(self):
        """Register, then show. False (and nothing left behind) when it cannot be done."""
        if not self.shell.hwnd:
            LOG.warning("bar: no owner window; the bar is not shown")
            self.shell.close()
            return False
        self.session = appbar.AppBarSession(self.backend, self.shell.hwnd, self.shell.callback, theme.BAR_HEIGHT,
                                            self._monitors, LOG.info)
        rect = self.session.register()
        if rect is None:
            LOG.warning("bar: could not reserve space; the bar is not shown")
            self.shell.close()
            self.session = None
            return False
        self.win = self._window_factory(self.root, self._on_settings, self._popup, ui.TEST_TAG if self.test_mode else "")
        self.win.on_task, self.win.foreground = self._task_click, self._foreground
        self.win.on_close = self._close_window
        self.win.give_back = self._give_back
        self.win.on_search = self._search_click
        self.win.on_start = self._start_click
        self.win.search_open = self._search_is_open
        self.win.menu_foreground = self._menu_foreground()
        self.win.set_look(self.colors, self.tasks_cfg.get("show_titles", True))
        self._show(rect)
        self._draw()
        self._schedule()
        self.start_tasks()
        self.start_start()
        self.start_search()
        LOG.info("bar: on (%s) rect=%s", "TEST: nothing reserved" if self.test_mode else "space reserved", rect)
        return True

    def stop(self):
        """Idempotent; the shortcut key goes first (it must not outlive the bar), then ABM_REMOVE, then the owner window
        and the bar window go."""
        self._cancel()
        self.stop_search()
        self.stop_start()
        if self.session is not None:
            self.session.unregister()
        if self.tasks is not None:                       # (the hooks are removed by shell.close(), which waits for it)
            t, self.tasks = self.tasks, None
            t.stop()
        self.shell.close()
        if self.win is not None:
            self.win.destroy()
        self.session = self.win = None
        LOG.info("bar: off")

    # ------------------------------------------------------------ messages (App._poll hands them over)
    def handle(self, payload):
        kind = payload[0] if payload else None
        if self.session is None:
            return
        if kind == "abn":
            wparam, lparam = payload[1], payload[2]
            if wparam == appbar.ABN_POSCHANGED:
                rect = self.session.reposition()
                if rect is not None:
                    self._show(rect)
                    self._on_layout()
            elif wparam == appbar.ABN_FULLSCREENAPP:
                LOG.info("bar: full-screen app %s", "opened" if lparam else "closed")      # step 1: logged only
        elif kind == "tbc":
            LOG.info("bar: Explorer restarted; registering again")
            rect = self.session.reregister()
            if rect is not None:
                self._show(rect)
            self._on_layout()
        elif kind == "time":
            self.realign()
        elif kind == "tasks":
            ack = getattr(self.shell, "ack_tasks", None)
            if ack is not None:
                ack()
            if self.tasks is not None:
                self.tasks.mark_dirty()
        elif kind == "icon":
            if self.tasks is not None:
                self.tasks.on_icon(payload[1], payload[2])
        elif kind == "scan":
            if self.search is not None:
                self.search.on_scan(payload[1])
        elif kind == "sicon":
            if self.search is not None:
                self.search.on_icon(payload[1], payload[2])
        elif kind == "hotkey":
            if self.search is not None and self.hotkey_name != "off":
                self.search.toggle_hotkey()

    def _show(self, rect):
        self._rect = tuple(rect)
        self.win.show(rect)

    # ------------------------------------------------------------ the clock
    def _text(self):
        if not self.info.get("enabled"):
            return ""
        return infoclock.format_info(self.now(), self.info.get("time_format", "24h"), bool(self.info.get("show_date")))

    def _draw(self):
        self._shown = self._text()
        if self.win is not None:
            self.win.set_text(self._shown)

    def _cancel(self):
        if self._job is not None:
            try:
                self.root.after_cancel(self._job)
            except Exception:                                           # noqa: BLE001
                pass
            self._job = None

    def _schedule(self):
        self._cancel()
        self._job = self.root.after(infoclock.next_delay_ms(self.now()), self._on_minute)

    def _on_minute(self):
        self._job = None
        if self.session is None:
            return
        self._draw()
        self._schedule()

    def realign(self):
        """The clock may have jumped (time zone, manual change, wake from sleep): redraw and re-aim the one timer."""
        if self.session is None:
            return
        self._draw()
        self._schedule()

    def refresh(self):
        """Safety net (App._tick, every 2 s): if the text on the bar is not what the clock says now, fix it and re-aim;
        and the same full comparison for the window list (a missed event costs at most this long)."""
        if self.session is not None and self._shown != self._text():
            self.realign()
        if self.tasks is not None:
            self.tasks.tick()

    def pump(self):
        """App._poll, every round: scan the window list if the hooks said something changed (max one scan per 100 ms)."""
        if self.tasks is not None:
            self.tasks.pump()

    # ------------------------------------------------------------ Tasks section
    def start_tasks(self):
        if (self.tasks is not None or self.session is None or not self.tasks_cfg.get("enabled")
                or self._tasks_factory is None):
            return
        self.tasks = self._tasks_factory(self._tasks_changed)
        self.tasks.start()
        if not self.test_mode and hasattr(self.shell, "set_tasks_hooks"):      # TEST mode: never a real hook
            if not self.shell.set_tasks_hooks(True):
                LOG.warning("tasks: no window events; the list follows the 2 s comparison only")

    def stop_tasks(self):
        if self.tasks is None:
            return
        if not self.test_mode and hasattr(self.shell, "set_tasks_hooks"):
            self.shell.set_tasks_hooks(False)
        t, self.tasks = self.tasks, None
        t.stop()
        if self.win is not None:
            self.win.set_tasks(None)

    def set_tasks(self, cfg):
        """Settings > Apply: the Tasks section on or off, titles on or off, live."""
        self.tasks_cfg = cfg
        if self.win is not None:
            self.win.set_look(self.colors, cfg.get("show_titles", True))
        if self.win is not None:
            self.win.menu_foreground = self._menu_foreground()
        if cfg.get("enabled"):
            self.start_tasks()
        else:
            self.stop_tasks()

    def set_colors(self, colors):
        """Settings > Apply: the user's bar colors (only the changed ones), live."""
        self.colors = colors
        if self.win is not None:
            self.win.set_look(colors, self.tasks_cfg.get("show_titles", True))
            LOG.info("bar: look changed (%d own colors, titles %s)", len(colors),
                     "on" if self.tasks_cfg.get("show_titles", True) else "off")

    # ------------------------------------------------------------ Start button (step 5)
    def start_start(self):
        if (self.startmenu is not None or self.session is None or not self.start_cfg.get("enabled")
                or self._start_factory is None):
            return
        self.startmenu = self._start_factory(self)
        self.win.set_start(True)

    def stop_start(self):
        self.startmenu = None
        if self.win is not None:
            self.win.set_start(False)

    def set_start(self, cfg):
        """Settings > Apply: the Start button on or off, live (nothing to register, so this cannot fail)."""
        self.start_cfg = cfg
        if cfg.get("enabled"):
            self.start_start()
        else:
            self.stop_start()

    def _start_click(self):
        if self.startmenu is not None:
            self.startmenu.click()

    def close_search(self):
        """A click on Start closes the search window first, WITHOUT giving the foreground back (the Start menu takes it)."""
        if self.search is not None and self.search.is_open():
            self.search.close(give_back=False, why="start button")

    # ------------------------------------------------------------ Search section (step 4)
    def start_search(self):
        """The search button, the list (first scan in the background) and the shortcut key. False when the shortcut key
        could not be registered (the button works anyway; Settings > Apply then undoes the change)."""
        if (self.search is not None or self.session is None or not self.search_cfg.get("enabled")
                or self._search_factory is None):
            return True
        self.search = self._search_factory(self)
        self.win.set_search(True)
        self.search.start()
        return self._set_hotkey(self.search_cfg.get("hotkey", "off"))

    def stop_search(self):
        s, self.search = self.search, None
        if s is not None:
            s.stop()
        self._set_hotkey("off")
        if self.win is not None:
            self.win.set_search(False)

    def set_search(self, cfg):
        """Settings > Apply: the search section and its shortcut key, live. False when the new key could not be registered
        (the old key then stays)."""
        self.search_cfg = cfg
        if cfg.get("enabled"):
            if self.search is None:
                return self.start_search()
            return self._set_hotkey(cfg.get("hotkey", "off"))
        self.stop_search()
        return True

    def _set_hotkey(self, name):
        """Register the shortcut key `name` (replacing the one in use); "off" removes it. TEST mode registers nothing real.
        The key is removed again with the bar, with the search section and with Settings > Off."""
        if name == self.hotkey_name:
            return True
        spec = search_mod.HOTKEYS.get(name) or (0, 0)
        if self.test_mode or not hasattr(self.shell, "set_hotkey"):
            ok = True
        else:
            ok = bool(self.shell.set_hotkey(spec[0], spec[1]))
        if ok:
            self.hotkey_name = name
            LOG.info("search: shortcut key %s%s", name, " (TEST mode: not registered)" if self.test_mode else "")
        else:
            LOG.warning("search: could not register the shortcut key %s", name)
        return ok

    def _search_is_open(self):
        return self.search is not None and self.search.is_open()

    def _search_click(self, was_open, prev):
        if self.search is not None:
            self.search.button_click(was_open, prev)

    # -- what the search window asks of the bar (the "host" interface)
    def anchor(self):
        """Where the search window's top-left corner goes: the left edge of the search button, right under the bar."""
        r = self._rect or (0, 0, 0, theme.BAR_HEIGHT)
        return r[0] + theme.BAR_SEARCH_BTN_X, r[3]

    def pal(self):
        return theme.bar_palette(self.colors)

    def foreground(self):
        return self._foreground()

    def give_back(self, hwnd):
        self._give_back(hwnd)

    def set_active(self, on):
        if self.win is not None:
            self.win.set_search_active(on)

    def monitors(self):
        return self._monitors()

    def _menu_foreground(self):
        """The menus take/give back the foreground with Tasks on (the list tracks it) AND off (the keeper reads it)."""
        return self._tasks_factory is not None or self._keeper_factory is not None

    def _the_keeper(self):
        if self.win is None:                             # the bar is gone: nothing to give back for
            return None
        if self.tasks is not None:
            return self.tasks
        if self.keeper is None and self._keeper_factory is not None:
            self.keeper = self._keeper_factory()
        return self.keeper

    def _task_click(self, hwnd, prev):
        if self.tasks is not None:
            self.tasks.activate(hwnd, prev)

    def _close_window(self, hwnd):
        if self.tasks is not None:
            self.tasks.close_window(hwnd)

    def _foreground(self):
        k = self._the_keeper()
        return k.previous_active() if k is not None else 0

    def _give_back(self, hwnd):
        k = self._the_keeper()
        if k is not None:
            k.give_back(hwnd)

    def _tasks_changed(self):
        if self.win is not None and self.tasks is not None:
            self.win.set_tasks(self.tasks.view())

    def set_info(self, info):
        self.info = info
        self.realign()
