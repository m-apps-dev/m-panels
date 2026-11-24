"""The search window (v1.2 step 4): a small pop-up under the search button of the bar, a text box and up to 8 rows.
It takes the keyboard (it is NOT a no-activate window, unlike the bar).

SearchWindow  the tkinter view: text box + a canvas of rows (icon, name, a gray hint). It only reports what the user does
              to the controller.
Search        the controller: opens/closes the window, runs the matching on every key, starts the chosen program, sends
              Win+S for the optional "Search Windows" row. Everything the outside world does (the list, the Windows
              actions, the clock, the timers, the window class, the icons) is handed in, so tests use made-up ones.

Closing rules: Esc and a click on the search button (or the shortcut key) close it AND give the foreground back to the window
that was active before; Enter / a click on a row start the program and give nothing back (the program has the foreground);
losing the focus to another window closes it and gives nothing back. After the BUTTON closed the window, clicks on the
button within the system's double-click time are ignored (otherwise the second click of a double click opens it again)."""
import tkinter as tk
from tkinter import font as tkfont

import applog
import barwin
import search as search_mod
import strings as ui
import tasks as tasks_mod
import theme
import winutil

LOG = applog.get_logger()
FOCUS_CHECK_MS = 80          # the focus moves between our own widgets too: look a moment later before closing
WIN_SETTLE_MS = 60           # after our window is gone, before Win+S (so the "foreground before" is the settled one)
WIN_POLL_MS = 50             # how often the foreground is looked at after Win+S
WIN_WAIT_MS = 1000           # longest wait for Windows Search to take the foreground
WIN_TYPE_DELAY_MS = 120      # after it did, before the text is typed (the box needs a moment to take the keyboard)


class SearchWindow:
    def __init__(self, root, pal, ctl):
        self.ctl, self.pal = ctl, pal
        self.top = t = tk.Toplevel(root)
        t.withdraw()
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        t.configure(bg=pal["border"])
        winutil.make_toolwindow(t)                       # no taskbar button / Alt+Tab entry (it still takes the keyboard)
        inner = tk.Frame(t, bg=pal["background"])
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        base = theme.tk_font_spec(theme.CONTENT_STYLE)
        self._font = tkfont.Font(t, font=base)
        self.var = tk.StringVar()
        self.ef = tk.Frame(inner, bg=pal["background"])
        self.ef.pack(fill="x")
        self.entry = tk.Entry(self.ef, textvariable=self.var, font=(base[0], base[1] + 2), bg=pal["button"], fg=pal["text"],
                              insertbackground=pal["text"], relief="flat", bd=0, highlightthickness=1,
                              highlightbackground=pal["border"], highlightcolor=pal["active"])
        self.entry.pack(fill="x", padx=theme.SEARCH_PAD, pady=theme.SEARCH_PAD, ipady=4)
        self.cv = tk.Canvas(inner, width=theme.SEARCH_W - 2, height=1, bg=pal["background"], highlightthickness=0, bd=0)
        self._cv_shown = False
        self.painter = barwin.Painter(t)
        self._anchor = self._work = None
        self._rows_h = 0
        self.var.trace_add("write", lambda *a: ctl.on_text(self.var.get()))
        self.entry.bind("<Escape>", lambda e: ctl.on_escape())
        self.entry.bind("<Return>", lambda e: ctl.on_enter())
        self.entry.bind("<Down>", lambda e: ctl.on_move(1))
        self.entry.bind("<Up>", lambda e: ctl.on_move(-1))
        self.entry.bind("<Tab>", lambda e: "break")
        self.cv.bind("<Motion>", lambda e: ctl.on_hover(e.y // theme.SEARCH_ROW_H))
        self.cv.bind("<Button-1>", lambda e: ctl.on_click(e.y // theme.SEARCH_ROW_H))
        t.bind("<FocusOut>", lambda e: ctl.on_focus_out())

    # ---- placing and focus
    def show(self, x, y, work):
        """Put the window at (x, y) (moved inside `work` if needed), in front, with the keyboard in the text box."""
        self._anchor, self._work = (x, y), work
        self._place()
        self.top.update_idletasks()
        self.top.deiconify()
        winutil.take_foreground(self.top)
        self.entry.focus_force()

    def _place(self):
        if self._anchor is None:
            return
        self.top.update_idletasks()
        w = theme.SEARCH_W
        h = self.ef.winfo_reqheight() + self._rows_h + 2
        x, y = search_mod.place_window(self._anchor[0], self._anchor[1], w, h, self._work)
        self.top.geometry("%dx%d+%d+%d" % (w, h, x, y))

    def own_hwnd(self):
        return winutil.hwnd_of(self.top)

    def has_focus(self):
        try:
            return self.top.focus_get() is not None
        except (KeyError, tk.TclError):
            return False

    # ---- the rows
    def set_rows(self, rows, sel, notice=""):
        cv, pal = self.cv, self.pal
        cv.delete("all")
        rh = theme.SEARCH_ROW_H
        h = len(rows) * rh + (theme.SEARCH_NOTICE_H if notice else 0)
        self._rows_h = h
        if h and not self._cv_shown:
            self.cv.pack(fill="x")
            self._cv_shown = True
        elif not h and self._cv_shown:
            self.cv.pack_forget()
            self._cv_shown = False
        if h:
            cv.configure(height=h)
        width = theme.SEARCH_W - 2
        ix = 4 + theme.SEARCH_PAD
        for i, (kind, payload) in enumerate(rows):
            y = i * rh
            if i == sel:
                cv.create_image(4, y + 1, image=self.painter.background(width - 8, rh - 2, "hover", pal), anchor="nw")
            icon, letter = self.ctl.icon_for(kind, payload)
            cy = y + rh // 2
            if icon is not None:
                cv.create_image(ix, cy - theme.SEARCH_ICON // 2, image=icon, anchor="nw")
                if letter:
                    cv.create_text(ix + theme.SEARCH_ICON // 2, cy, text=letter, font=self._font, fill=pal["text"])
            tx = ix + theme.SEARCH_ICON + theme.SEARCH_PAD
            right = width - 12
            if kind == "windows":
                name, hint = ui.SEARCH_WINDOWS_ROW.format(text=payload), ""
            else:
                name, hint = payload.name, payload.hint
            shown = tasks_mod.fit_text(name, right - tx, self._font.measure)
            cv.create_text(tx, cy, text=shown, anchor="w", font=self._font, fill=pal["text"])
            if hint:
                hx = tx + self._font.measure(shown) + 8
                room = right - hx
                if room >= 30:
                    cv.create_text(hx, cy, text=tasks_mod.fit_text(hint, room, self._font.measure), anchor="w",
                                   font=self._font, fill=pal["dim_text"])
        if notice:
            cv.create_text(ix, h - theme.SEARCH_NOTICE_H // 2, text=notice, anchor="w", font=self._font, fill=pal["text"])
        self._place()

    def destroy(self):
        try:
            self.top.destroy()
        except tk.TclError:
            pass


class Search:
    """The controller (Tk thread only). `host` is the bar: anchor() -> (x, y) under the button, pal(), foreground(),
    give_back(hwnd), set_active(bool), monitors()."""

    def __init__(self, root, cfg, index, actions, host, clock, window_factory=SearchWindow, icons=None,
                 double_click=search_mod.double_click_ms, schedule=None, make_photo=None):
        self.root, self.cfg, self.index, self.actions, self.host = root, cfg, index, actions, host
        self.clock, self._factory, self.icons = clock, window_factory, icons
        self._double_click = double_click
        self._schedule = schedule or (lambda ms, fn: self.root.after(ms, fn))
        self._make_photo = make_photo
        self.win = None
        self.prev = 0
        self.text, self.sel, self.rows, self.notice = "", 0, [], ""
        self.closed_at = None            # when the BUTTON last closed the window (the double-click guard)
        self.opened_at = None
        self._photos, self._inflight = {}, set()
        self._generic = self._magnifier = None
        self.stopped = False

    # ---- lifecycle
    def start(self):
        self.index.start()

    def stop(self):
        self.stopped = True
        self.close(give_back=False, why="search stopped")
        self.index.stop()
        if self.icons is not None and hasattr(self.icons, "stop"):
            self.icons.stop()
        self._photos.clear()
        self._inflight.clear()
        self._generic = self._magnifier = None

    def is_open(self):
        return self.win is not None

    # ---- opening and closing
    def open(self, prev):
        if self.win is not None or self.stopped:
            return False
        try:
            self.prev, self.text, self.sel, self.rows, self.notice = int(prev or 0), "", 0, [], ""
            self.index.refresh_if_stale()                # the cache is used AT ONCE; a stale one is refreshed behind it
            self.win = self._factory(self.root, self.host.pal(), self)
            ax, ay = self.host.anchor()
            self.win.show(ax, ay, self._work_area(ax, ay))
            self.opened_at = self.clock()
            self.host.set_active(True)
            self._draw()
            LOG.info("search: opened; window to give back: %d", self.prev)
            return True
        except Exception:                                # noqa: BLE001  (never break a Tk callback)
            LOG.exception("search: opening failed")
            self._drop()
            return False

    def _drop(self):
        w, self.win = self.win, None
        if w is not None:
            try:
                w.destroy()
            except Exception:                            # noqa: BLE001
                pass
        try:
            self.host.set_active(False)
        except Exception:                                # noqa: BLE001
            pass

    def close(self, give_back, why=""):
        """Close the window. `give_back`: the foreground goes back to the window that was active before it opened (only
        when nobody else has it, the bar's usual rule). True if it was open."""
        if self.win is None:
            return False
        prev, self.prev = self.prev, 0
        self._drop()
        LOG.info("search: closed (%s); foreground given back: %s", why, bool(give_back and prev))
        try:
            if give_back and prev:
                self.host.give_back(prev)
        except Exception:                                # noqa: BLE001
            LOG.exception("search: giving the foreground back failed")
        return True

    def _work_area(self, x, y):
        mons = list(self.host.monitors() or [])
        for m in mons:
            r = m.rect
            if r[0] <= x < r[2] and r[1] <= y < r[3]:
                return m.work
        return (mons[0].work if mons else (0, 0, 1920, 1080))

    # ---- the button and the shortcut key
    def button_click(self, was_open, prev):
        """A click on the bar's search button. `was_open`: was the window open when the mouse went DOWN."""
        try:
            now = self.clock()
            if self.closed_at is not None and (now - self.closed_at) * 1000.0 < self._double_click():
                LOG.info("search: click ignored (inside the double-click time of the click that closed the window)")
                return
            if was_open:
                if self.close(give_back=True, why="search button"):
                    self.closed_at = now
            else:
                self.open(prev)
        except Exception:                                # noqa: BLE001
            LOG.exception("search: button click failed")

    def toggle_hotkey(self):
        try:
            if self.win is not None:
                self.close(give_back=True, why="shortcut key")
            else:
                self.open(self.host.foreground())
        except Exception:                                # noqa: BLE001
            LOG.exception("search: shortcut key failed")

    # ---- what the window reports
    def on_text(self, text):
        self.text, self.notice, self.sel = text, "", 0
        self._query()

    def on_escape(self):
        self.close(give_back=True, why="Esc")

    def on_enter(self):
        self.activate(self.sel)

    def on_click(self, i):
        self.activate(i)

    def on_move(self, d):
        if self.rows:
            self.sel = max(0, min(len(self.rows) - 1, self.sel + d))
            self._draw()

    def on_hover(self, i):
        if 0 <= i < len(self.rows) and i != self.sel:
            self.sel = i
            self._draw()

    def on_focus_out(self):
        self._schedule(FOCUS_CHECK_MS, self._focus_check)

    def _focus_check(self):
        w = self.win
        if w is None:
            return
        try:
            if w.has_focus():
                return                                   # the focus only moved inside the window
            fg = self.actions.foreground()
            if fg and fg == w.own_hwnd():
                return
        except Exception:                                # noqa: BLE001
            pass
        self.close(give_back=False, why="focus lost")

    # ---- results
    def _query(self, keep=None):
        self.rows = search_mod.build_rows(self.index.entries(), self.text, self.cfg.get("store_apps", True),
                                          self.cfg.get("windows_row", False))
        if keep is not None:
            for i, (kind, payload) in enumerate(self.rows):
                if kind == "app" and payload.parsing == keep:
                    self.sel = i
                    break
        self.sel = max(0, min(self.sel, len(self.rows) - 1)) if self.rows else 0
        self._draw()

    def _draw(self):
        if self.win is not None:
            try:
                self.win.set_rows(self.rows, self.sel, self.notice)
            except Exception:                            # noqa: BLE001
                LOG.exception("search: drawing failed")

    def on_scan(self, result):
        """A background scan ended (the message came through the app queue)."""
        if self.index.finish(result) and self.win is not None:
            keep = self.rows[self.sel][1].parsing if self.rows and self.rows[self.sel][0] == "app" else None
            self._query(keep)

    # ---- starting things
    def activate(self, i):
        try:
            if not 0 <= i < len(self.rows):
                return
            kind, payload = self.rows[i]
            if kind == "windows":
                self._windows_search(payload)
                return
            try:
                self.actions.launch(payload)
            except Exception as e:                       # noqa: BLE001  (a refused start must not close the window)
                LOG.warning("search: could not start an entry (%s, winerror %s)", type(e).__name__, getattr(e, "winerror", None))
                self.notice = ui.SEARCH_LAUNCH_FAILED.format(name=payload.name)
                self._draw()
                return
            LOG.info("search: started an entry (%s)", payload.kind)
            self.close(give_back=False, why="started")
        except Exception:                                # noqa: BLE001
            LOG.exception("search: activating a row failed")

    def _windows_search(self, text):
        """The window closes, Win+S opens Windows Search, and once that has the foreground the text is typed into it."""
        self.close(give_back=False, why="Search Windows")
        self._schedule(WIN_SETTLE_MS, lambda: self._send_win_s(text))

    def _send_win_s(self, text):
        try:
            before = self.actions.foreground()
            self.actions.open_windows_search()
            self._schedule(WIN_POLL_MS, lambda: self._wait_foreground(before, text, WIN_POLL_MS))
        except Exception:                                # noqa: BLE001
            LOG.exception("search: Win+S failed")

    def _wait_foreground(self, before, text, waited):
        try:
            if self.actions.foreground() != before:
                self._schedule(WIN_TYPE_DELAY_MS, lambda: self._type(text))
            elif waited >= WIN_WAIT_MS:
                LOG.info("search: Windows Search did not take the foreground within %d ms; the text was not typed", WIN_WAIT_MS)
            else:
                self._schedule(WIN_POLL_MS, lambda: self._wait_foreground(before, text, waited + WIN_POLL_MS))
        except Exception:                                # noqa: BLE001
            LOG.exception("search: waiting for Windows Search failed")

    def _type(self, text):
        try:
            self.actions.type_text(text)
        except Exception:                                # noqa: BLE001
            LOG.exception("search: typing into Windows Search failed")

    # ---- icons (only for the rows on show; fetched by a worker thread, never here)
    def _photo(self, img):
        if self._make_photo is not None:
            return self._make_photo(img)
        from PIL import ImageTk
        return ImageTk.PhotoImage(img, master=self.root)

    def icon_for(self, kind, payload):
        """(PhotoImage, letter) for a row: the entry's own icon; else a plain square with the first letter."""
        if kind == "windows":
            if self._magnifier is None:
                self._magnifier = self._photo(theme.search_icon(theme.SEARCH_ICON, self.host.pal()["text"]))
            return self._magnifier, ""
        got = self._photos.get(payload.parsing)
        if got:
            return got, ""
        if got is None and payload.parsing not in self._inflight and self.icons is not None:
            self._inflight.add(payload.parsing)
            self.icons.request(payload)
        if self._generic is None:
            self._generic = self._photo(tasks_mod.generic_icon(theme.SEARCH_ICON))
        return self._generic, tasks_mod.tile_letter(payload.name)

    def on_icon(self, key, img):
        """The worker's answer (through the app queue). None = this entry has no icon: remembered, not asked again."""
        self._inflight.discard(key)
        if self.stopped:
            return
        if len(self._photos) > 128:
            self._photos.clear()
        self._photos[key] = self._photo(img) if img is not None else False
        if img is not None and self.win is not None:
            self._draw()
