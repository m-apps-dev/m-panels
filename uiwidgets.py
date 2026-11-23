"""Shared UI components: searchable font list + preview, style editor (font/size/color/bold/italic).

Separate from the application code so M Calendar can use it too (tkinter + theme + strings + winutil).
"""
import tkinter as tk
import tkinter.font as tkfont
from tkinter import colorchooser, ttk

import strings as ui
import theme
import winutil

_FAMILIES = None


def filter_fonts(families, query):
    """Fonts containing the query (ignoring case and the Turkish dotted/dotless i difference); order is kept."""
    q = _fold(query)
    if not q:
        return list(families)
    return [f for f in families if q in _fold(f)]


def _fold(s):
    return (s or "").strip().replace("İ", "i").replace("I", "ı").casefold().replace("ı", "i")


def clean_families(raw):
    """Installed font names: vertical-writing variants starting with '@' and duplicates are dropped; A-Z order."""
    seen, out = set(), []
    for f in raw:
        if not f or f.startswith("@") or f.casefold() in seen:
            continue
        seen.add(f.casefold())
        out.append(f)
    return sorted(out, key=str.casefold)


def list_fonts(root=None):
    global _FAMILIES
    if _FAMILIES is None:
        _FAMILIES = clean_families(tkfont.families(root))
    return _FAMILIES


class FontPicker(ttk.Frame):
    """Search box + font list. get() / set(name). on_change is called when the selection changes."""

    def __init__(self, parent, family=theme.FONT_FAMILY, on_change=None, rows=6):
        super().__init__(parent)
        self.on_change = on_change
        self.fonts = list_fonts(self)
        self.family = tk.StringVar(value=family)
        self.q = tk.StringVar()
        self.entry = ttk.Entry(self, textvariable=self.q)
        self.entry.pack(fill="x")
        fr = ttk.Frame(self)
        fr.pack(fill="both", expand=True, pady=(3, 0))
        self.lb = tk.Listbox(fr, height=rows, exportselection=False, activestyle="none")
        sb = ttk.Scrollbar(fr, orient="vertical", command=self.lb.yview)
        self.lb.configure(yscrollcommand=sb.set)
        self.lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.shown = []
        self.q.trace_add("write", lambda *a: self._refill())
        self.lb.bind("<<ListboxSelect>>", self._picked)
        self.entry.bind("<Return>", self._first)
        self._refill()

    def _refill(self):
        self.shown = filter_fonts(self.fonts, self.q.get())
        self.lb.delete(0, "end")
        for f in self.shown:
            self.lb.insert("end", f)
        self._mark()

    def _mark(self):
        cur = self.family.get().casefold()
        self.lb.selection_clear(0, "end")
        for i, f in enumerate(self.shown):
            if f.casefold() == cur:
                self.lb.selection_set(i)
                self.lb.see(i)
                break

    def _picked(self, e=None):
        sel = self.lb.curselection()
        if sel:
            self.family.set(self.shown[sel[0]])
            if self.on_change:
                self.on_change()

    def _first(self, e=None):
        if self.shown:
            self.family.set(self.shown[0])
            self._mark()
            if self.on_change:
                self.on_change()

    def get(self):
        return self.family.get()

    def set(self, family):
        self.family.set(family or theme.FONT_FAMILY)
        if self.q.get():
            self.q.set("")              # the filter must not hide the selected font
        else:
            self._mark()


class StyleEditor(ttk.Frame):
    """Font (searchable) + size + color + bold + italic + preview. get()/set(style dict)."""

    def __init__(self, parent, style=None, on_change=None):
        super().__init__(parent)
        st = {**theme.TITLE_STYLE, **(style or {})}
        self.on_change = on_change
        self.color = st["color"]
        self.size = tk.StringVar(value=str(st["size"]))
        self.bold, self.italic = tk.BooleanVar(value=st["bold"]), tk.BooleanVar(value=st["italic"])
        self.picker = FontPicker(self, st["font"], on_change=self._changed)
        self.picker.grid(row=0, column=0, columnspan=4, sticky="nsew")
        ttk.Label(self, text=ui.LBL_SIZE).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.sp = ttk.Spinbox(self, from_=theme.SIZE_MIN, to=theme.SIZE_MAX, textvariable=self.size, width=5,
                              command=self._changed)
        self.sp.grid(row=1, column=1, sticky="w", pady=(6, 0))
        self.sp.bind("<KeyRelease>", lambda e: self._changed())
        cf = ttk.Frame(self)
        self.sw = tk.Label(cf, width=4, relief="solid", bd=1, bg=self.color)
        self.sw.pack(side="left")
        ttk.Button(cf, text=ui.BTN_COLOR, command=self.pick_color).pack(side="left", padx=4)
        cf.grid(row=1, column=2, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Checkbutton(self, text=ui.CHK_BOLD, variable=self.bold, command=self._changed).grid(
            row=2, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(self, text=ui.CHK_ITALIC, variable=self.italic, command=self._changed).grid(
            row=2, column=2, columnspan=2, sticky="w")
        self.prev = tk.Label(self, text=ui.SAMPLE_TEXT, anchor="w", bg=theme.SURFACE, padx=8, pady=8,
                             relief="sunken", bd=1, width=44)
        self.prev.grid(row=3, column=0, columnspan=4, sticky="we", pady=(6, 0))
        self.columnconfigure(3, weight=1)
        self._changed(notify=False)

    def pick_color(self):
        c = colorchooser.askcolor(color=self.color, parent=self.winfo_toplevel())[1]
        if c:
            self.color = c
            self.sw.configure(bg=c)
            self._changed()

    def _changed(self, notify=True):
        st = self.get()
        try:
            self.prev.configure(font=theme.tk_font_spec(st), fg=st["color"])
        except tk.TclError:
            pass
        if notify and self.on_change:
            self.on_change()

    def get(self):
        """Validated style: the size is clamped to 6-72 (invalid input -> default)."""
        return {"font": self.picker.get() or theme.FONT_FAMILY,
                "size": theme.normalize_font_size(self.size.get()),
                "color": self.color if theme.is_hex_color(self.color) else theme.TEXT_COLOR,
                "bold": bool(self.bold.get()), "italic": bool(self.italic.get())}

    def size_valid(self):
        s = self.size.get().strip()
        return s.isdigit() and theme.SIZE_MIN <= int(s) <= theme.SIZE_MAX

    def set(self, st):
        st = {**theme.TITLE_STYLE, **st}
        self.color = st["color"]
        self.sw.configure(bg=self.color)
        self.size.set(str(st["size"]))
        self.bold.set(st["bold"])
        self.italic.set(st["italic"])
        self.picker.set(st["font"])
        self._changed(notify=False)


class _Modal:
    """Small modal window skeleton: body + OK/Cancel. Hidden from the taskbar and Alt+Tab."""

    def __init__(self, parent, title):
        self.result = None
        w = self.win = tk.Toplevel(parent)
        w.title(title)
        w.attributes("-topmost", True)
        w.resizable(False, False)
        self.body = ttk.Frame(w, padding=12)
        self.body.pack(fill="both", expand=True)
        bf = ttk.Frame(w, padding=(12, 0, 12, 12))
        bf.pack(fill="x")
        ttk.Button(bf, text=ui.BTN_OK, command=self.ok).pack(side="right")
        ttk.Button(bf, text=ui.BTN_CANCEL, command=w.destroy).pack(side="right", padx=6)
        w.bind("<Escape>", lambda e: w.destroy())
        winutil.make_toolwindow(w)          # no taskbar button / Alt+Tab entry

    def ok(self):
        raise NotImplementedError

    def run(self):
        self.win.grab_set()
        self.win.wait_window()
        return self.result


class StyleDialog(_Modal):
    """Title/content text window (from the right-click menu)."""

    def __init__(self, parent, title, style):
        super().__init__(parent, title)
        self.ed = StyleEditor(self.body, style)
        self.ed.pack(fill="both", expand=True)

    def ok(self):
        self.result = self.ed.get()
        self.win.destroy()


class FontDialog(_Modal):
    """Font family choice only (for selected text in a note panel)."""

    def __init__(self, parent, family=theme.FONT_FAMILY, size=theme.FONT_SIZE):
        super().__init__(parent, ui.FONT_DIALOG_TITLE)
        self.size = size
        self.prev = tk.Label(self.body, text=ui.SAMPLE_TEXT, anchor="w", bg=theme.SURFACE, fg=theme.TEXT_COLOR,
                             padx=8, pady=8, relief="sunken", bd=1, width=44)
        self.picker = FontPicker(self.body, family, on_change=self._prev)
        self.picker.pack(fill="both", expand=True)
        self.prev.pack(fill="x", pady=(6, 0))
        self._prev()

    def _prev(self):
        try:
            self.prev.configure(font=(self.picker.get(), int(self.size)))
        except tk.TclError:
            pass

    def ok(self):
        self.result = self.picker.get()
        self.win.destroy()


class PromptDialog(_Modal):
    """Ask for one value: free text (kind="text") or a whole number in [lo, hi] (kind="int").
    Replaces tkinter's simpledialog so every window shares the same taskbar behaviour."""

    def __init__(self, parent, title, prompt, initial="", kind="text", lo=None, hi=None):
        super().__init__(parent, title)
        self.kind, self.lo, self.hi = kind, lo, hi
        ttk.Label(self.body, text=prompt).pack(anchor="w")
        self.var = tk.StringVar(value=str(initial))
        self.entry = ttk.Entry(self.body, textvariable=self.var, width=34)
        self.entry.pack(fill="x", pady=(4, 0))
        self.entry.focus_set()
        self.entry.select_range(0, "end")
        self.win.bind("<Return>", lambda e: self.ok())

    def ok(self):
        v = self.var.get()
        if self.kind == "int":
            if not v.strip().lstrip("-").isdigit():
                return
            n = int(v)
            if (self.lo is not None and n < self.lo) or (self.hi is not None and n > self.hi):
                return
            v = n
        self.result = v
        self.win.destroy()


class Tip:
    """A small hover tooltip for a widget (shown after a short delay; never takes focus)."""

    def __init__(self, widget, text, delay=500):
        self.widget, self.text, self.delay = widget, text, delay
        self.win = None
        self._job = None
        widget.bind("<Enter>", self._enter, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")

    def _enter(self, e=None):
        self.hide()
        self._job = self.widget.after(self.delay, self.show)

    def show(self):
        self._job = None
        if self.win is not None or not self.widget.winfo_exists():
            return
        w = self.win = tk.Toplevel(self.widget)
        w.wm_overrideredirect(True)
        tk.Label(w, text=self.text, justify="left", relief="solid", bd=1, bg=theme.TIP_BG, fg=theme.TIP_FG,
                 padx=6, pady=3, wraplength=420).pack()
        w.wm_geometry(f"+{self.widget.winfo_rootx()}+{self.widget.winfo_rooty() + self.widget.winfo_height() + 4}")

    def hide(self, e=None):
        if self._job is not None:
            try:
                self.widget.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        if self.win is not None:
            try:
                self.win.destroy()
            except Exception:
                pass
            self.win = None


class CalendarDialog(_Modal):
    """Add / edit one calendar: name, secret iCal address (masked until "Show" is pressed), color, on/off.
    `result` is a clean calendar dict, or None when cancelled. The address is never echoed in messages."""
    def __init__(self, parent, initial=None):
        super().__init__(parent, ui.DLG_CAL_EDIT if initial else ui.DLG_CAL_ADD)
        init = initial or {}
        self.color = init.get("color")
        self.v_name = tk.StringVar(value=init.get("name", ""))
        self.v_url = tk.StringVar(value=init.get("url", ""))
        self.v_on = tk.BooleanVar(value=bool(init.get("enabled", True)))
        b = self.body
        ttk.Label(b, text=ui.LBL_CAL_NAME).grid(row=0, column=0, sticky="w", pady=3, padx=(0, 8))
        self.en_name = ttk.Entry(b, textvariable=self.v_name, width=40)
        self.en_name.grid(row=0, column=1, columnspan=2, sticky="we", pady=3)
        ttk.Label(b, text=ui.LBL_CAL_ADDRESS).grid(row=1, column=0, sticky="w", pady=3, padx=(0, 8))
        self.en_url = ttk.Entry(b, textvariable=self.v_url, width=40, show=ui.CAL_ADDRESS_MASK)
        self.en_url.grid(row=1, column=1, sticky="we", pady=3)
        self.btn_show = ttk.Button(b, text=ui.BTN_CAL_SHOW, width=7, command=self.toggle_show)
        self.btn_show.grid(row=1, column=2, padx=(6, 0), pady=3)
        ttk.Label(b, text=ui.LBL_CAL_COLOR1).grid(row=2, column=0, sticky="w", pady=3, padx=(0, 8))
        cf = ttk.Frame(b)
        cf.grid(row=2, column=1, columnspan=2, sticky="w", pady=3)
        self.sw = tk.Label(cf, width=4, relief="solid", bd=1)
        self.sw.pack(side="left")
        ttk.Button(cf, text=ui.BTN_PICK_COLOR, command=self.pick_color).pack(side="left", padx=6)
        ttk.Button(cf, text=ui.BTN_CAL_COLOR_RESET, command=self.reset_color).pack(side="left")
        ttk.Checkbutton(b, text=ui.CHK_CAL_ENABLED, variable=self.v_on).grid(row=3, column=1, columnspan=2,
                                                                          sticky="w", pady=3)
        self.lbl_err = ttk.Label(b, text="", foreground=theme.DIALOG_ERROR_TEXT)
        self.lbl_err.grid(row=4, column=0, columnspan=3, sticky="w")
        self._show_color()
        self.en_name.focus_set()
        self.win.bind("<Return>", lambda e: self.ok())

    @property
    def masked(self):
        return str(self.en_url.cget("show")) == ui.CAL_ADDRESS_MASK

    def toggle_show(self):
        now_masked = self.masked
        self.en_url.configure(show="" if now_masked else ui.CAL_ADDRESS_MASK)
        self.btn_show.configure(text=ui.BTN_CAL_SHOW if not now_masked else ui.BTN_CAL_HIDE)

    def _show_color(self):
        self.sw.configure(bg=self.color or self.win.cget("bg"), text="" if self.color else "—")

    def pick_color(self):
        c = colorchooser.askcolor(color=self.color, parent=self.win, title=ui.LBL_CAL_COLOR1)[1]
        if c:
            self.color = c.lower()
            self._show_color()

    def reset_color(self):
        self.color = None
        self._show_color()

    def ok(self):
        url = self.v_url.get().strip()
        if not url.lower().startswith(ui.CAL_ADDRESS_SCHEMES) or " " in url:
            self.lbl_err.configure(text=ui.ERR_CAL_ADDRESS)
            return
        self.result = {"name": self.v_name.get().strip() or ui.CAL_NEW_NAME, "url": url,
                       "color": self.color, "enabled": bool(self.v_on.get())}
        self.win.destroy()
