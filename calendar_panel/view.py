"""Drawing of the calendar panel: List / Day / Week views on Canvas widgets.

Ported from M Calendar's Widget.render_list / render_grid. The navigation rows are drawn on the panel's body
canvas; the scrollable content lives on its own child canvas (so tkinter clips it), whose background is the
matching slice of the panel's background image. The `panel` object supplies cfg, fonts and colors.
"""
import tkinter as tk
from datetime import date, datetime, time, timedelta

import strings as ui
import theme
from calendar_panel import core, settings

VIEWS = (("list", ui.CAL_VIEW_LIST), ("day", ui.CAL_VIEW_DAY), ("week", ui.CAL_VIEW_WEEK))


def blend(a, b, t):
    return theme.blend(a, b, t)


def make_palette(color, text, overrides=None):
    """Calendar colors derived from the panel color and the content text color (all values from theme.py).
    `overrides` ({key: '#rrggbb'}) replaces only the keys the user set; "bg" cannot be overridden."""
    bg = blend(theme.EDGE_HEX, color, theme.CAL_BG_MIX)
    pal = {
        "bg": bg, "text": text, "dim": blend(text, theme.EDGE_HEX, theme.BROKEN_MIX),
        "accent": blend(color, theme.WHITE, theme.BRIGHT_MIX),
        "event": blend(theme.EDGE_HEX, color, theme.CAL_EVENT_MIX), "event_text": theme.WHITE,
        "now": blend(theme.EDGE_HEX, color, theme.CAL_NOW_MIX), "now_line": theme.CAL_NOW_LINE,
        "grid": blend(bg, theme.WHITE, theme.CAL_GRID_MIX), "warn": theme.CAL_WARN,
    }
    if isinstance(overrides, dict):
        for k, v in overrides.items():
            if k in settings.COLOR_KEYS and k in pal and isinstance(v, str):
                pal[k] = v
    return pal


class CalendarView:
    def __init__(self, panel, model):
        self.panel, self.model = panel, model
        self.anchor = date.today()      # the date shown in Day/Week
        self.scroll = 0
        self.nav_hits = []              # (x0, y0, x1, y1, callable) in body-canvas coordinates
        self.tips = []                  # (x0, y0, x1, y1, text) in content-canvas (virtual) coordinates
        self.content_h = 0
        self._tip = None

    # ------------------------------------------------------------ settings / fonts
    @property
    def s(self):
        return self.panel.cfg["calendar"]

    def _fonts(self):
        return self.panel.cal_fonts()

    def nav_height(self):
        return 2 * (self._fonts()["small"].metrics("linespace") + 8) + 2

    def foot_height(self):
        """No footer line any more (v0.5.1): the content area runs to the bottom of the panel."""
        return 0

    # ------------------------------------------------------------ actions
    def set_view(self, key):
        old = self.s["view"]
        self.s["view"] = key
        self.anchor, self.scroll = date.today(), 0
        self.panel.cal_view_changed(old)                    # width of the new view (draws the body)
        self.panel.app.save()
        self.panel.app.sync_settings_cal(self.panel)        # an open Settings form must not keep the old value

    def set_weeks(self, n):
        self.s["list_weeks"] = n
        self.scroll = 0
        self.panel.app.save()
        self.panel.draw_body()
        self.panel.app.sync_settings_cal(self.panel)

    def nav(self, step):
        self.anchor += timedelta(days=step * (7 if self.s["view"] == "week" else 1))
        self.scroll = 0
        self.panel.draw_body()

    def go_today(self):
        self.anchor, self.scroll = date.today(), 0
        self.panel.draw_body()

    def scroll_by(self, delta):
        self.scroll = max(0, self.scroll + delta)
        self.panel.draw_body()

    # ------------------------------------------------------------ navigation rows (body canvas)
    def draw_nav(self, b, w, y0):
        """Two rows at the top of the body: views + refresh, then weeks / date navigation."""
        f, pal = self._fonts(), self.panel.cal_palette()
        self.nav_hits = []
        row_h = f["small"].metrics("linespace") + 8
        view = self.s["view"]

        def label(x, y, text, color, font, fn=None, anchor="nw"):
            it = b.create_text(x, y, text=text, fill=color, font=font, anchor=anchor)
            x0, y1, x1, y2 = b.bbox(it)
            if fn:
                self.nav_hits.append((x0 - 3, y1 - 2, x1 + 3, y2 + 2, fn))
            return x1

        x, y = 10, y0 + 5
        for key, name in VIEWS:
            on = view == key
            x = label(x, y, name, pal["accent"] if on else pal["dim"],
                      f["small_bold"] if on else f["small"], lambda k=key: self.set_view(k)) + 10
        if self.model.snapshot()["loading"]:
            b.create_text(self.panel.cur_w - 12, y, text="…", fill=pal["accent"], font=f["small"], anchor="ne")
        else:
            label(self.panel.cur_w - 12, y, "⟳", pal["dim"], f["small_bold"], self.panel.cal_refresh, anchor="ne")
            # ne-anchored: the hit box is computed from the bbox, so it stays correct

        y2 = y0 + row_h + 3
        if view == "list":
            x = label(10, y2, ui.CAL_SHOW, pal["dim"], f["small"]) + 6
            weeks = max(1, min(4, int(self.s["list_weeks"])))
            for n in range(1, 5):
                on = n == weeks
                x = label(x, y2, ui.CAL_WEEKS.format(n=n), pal["accent"] if on else pal["dim"],
                          f["small_bold"] if on else f["small"], lambda k=n: self.set_weeks(k)) + 8
        else:
            d0, d1, days = self._range()
            x = label(10, y2, "◀", pal["dim"], f["day"], lambda: self.nav(-1)) + 6
            x = label(x, y2, self._range_label(days), pal["text"], f["day"]) + 6
            x = label(x, y2, "▶", pal["dim"], f["day"], lambda: self.nav(1)) + 8
            today = date.today()
            if not (d0 <= today < d1):
                label(x, y2, ui.CAL_TODAY, pal["accent"], f["small_bold"], self.go_today)

    def nav_click(self, x, y):
        for x0, y0, x1, y1, fn in self.nav_hits:
            if x0 <= x <= x1 and y0 <= y <= y1:
                fn()
                return True
        return False

    def _empty_col_w(self, f):
        """Width of a shrunken (empty) Week column: the widest possible header (widest weekday abbreviation or
        day number 1-31 in the current fonts) + padding. Measured once per font setup, so it never changes
        with the day or the week."""
        tiny, day = f["tiny"], f["day"]
        key = (str(tiny.actual()), str(day.actual()))
        if getattr(self, "_ecw_key", None) != key:
            wd = max(tiny.measure(n) for n in ui.CAL_DAYS_SHORT)
            wn = max(day.measure(str(n)) for n in range(1, 32))
            self._ecw_key, self._ecw = key, max(wd, wn) + theme.CAL_HEAD_PAD
        return self._ecw

    def _range(self):
        ncols = 7 if self.s["view"] == "week" else 1
        d0 = core.week_start_of(self.anchor, self.s.get("week_start", "monday")) if ncols == 7 else self.anchor
        return d0, d0 + timedelta(days=ncols), [d0 + timedelta(days=i) for i in range(ncols)]

    def _range_label(self, days):
        d0, last = days[0], days[-1]
        if len(days) == 7:
            return ui.CAL_RANGE.format(d0=d0.day, m0=ui.CAL_MONTHS[d0.month - 1], d1=last.day,
                                       m1=ui.CAL_MONTHS[last.month - 1], year=last.year)
        return core.day_label(d0) + f" {d0.year}"

    # ------------------------------------------------------------ content (child canvas)
    def draw_content(self, cv, w, h, bg_image, bg_y):
        """Draw the current view on `cv` (w x h). bg_image: panel background; bg_y: offset of cv in the body."""
        cv.delete("all")
        if bg_image is not None:
            cv.create_image(0, -bg_y, image=bg_image, anchor="nw", tags="bg")
        self.tips = []
        for _ in range(2):                          # a second pass if the scroll had to be clamped
            cv.delete("cal")
            self.tips = []
            if self.s["view"] == "list":
                self.content_h = self._draw_list(cv, w)
            else:
                self.content_h = self._draw_grid(cv, w, 7 if self.s["view"] == "week" else 1)
            limit = max(0, self.content_h - h)
            if self.scroll <= limit:
                break
            self.scroll = limit
        cv.move("cal", 0, -self.scroll)
        self.panel._draw_grip(cv, w, h)             # this canvas covers the panel's corner: it draws the grip

    def _snap(self):
        return self.model.snapshot()

    def _error(self, cv, w, y):
        err = self._snap()["error"]
        if not err:
            return y
        f, pal = self._fonts(), self.panel.cal_palette()
        it = cv.create_text(10, y + 6, text=err, fill=pal["warn"], font=f["small"], anchor="nw",
                            width=max(40, w - 20), tags="cal")
        return cv.bbox(it)[3] + 6

    def _draw_list(self, cv, w):
        f, pal = self._fonts(), self.panel.cal_palette()
        weeks = max(1, min(4, int(self.s["list_weeks"])))
        y = self._error(cv, w, 0) + 4
        today = date.today()
        evs = self.model.events_between(today, today + timedelta(days=weeks * 7))
        evs = [e for e in evs if e["first"] or e["day"] == today]
        if not evs and not self._snap()["error"]:
            cv.create_text(10, y + 6, text=ui.CAL_NO_EVENTS, fill=pal["dim"], font=f["ev"], anchor="nw", tags="cal")
            y += 30
        now = datetime.now()
        pf = max(0, min(90, int(self.s["past_fade"]))) / 100
        current = None
        for ev in evs:
            if ev["day"] != current:
                current = ev["day"]
                it = cv.create_text(10, y + 8, text=core.day_label(current), fill=pal["accent"] if current == today else pal["text"],
                                    font=f["day"], anchor="nw", tags="cal")
                y = cv.bbox(it)[3] + 2
            is_now = not ev["all_day"] and ev["start"] <= now < ev["end"]
            is_past = not ev["all_day"] and ev["end"] <= now
            t = ui.CAL_ALL_DAY if ev["all_day"] else core.fmt_time(ev["start"], self.s.get("time_format", "24h"))
            ccol = ev["color"] or pal["event"]
            text = ev["title"] + (f"\n📍 {ev['location']}" if ev["location"] else "")
            tx = 16 + f["small"].measure(core.time_sample(self.s.get("time_format", "24h"))) + 22
            tcol = blend(pal["text"], pal["bg"], pf) if is_past else pal["text"]
            item = cv.create_text(tx, y + 2, text=text, fill=tcol, font=f["ev"], anchor="nw",
                                  width=max(40, w - tx - 8), tags="cal")
            x0, y0, x1, y1 = cv.bbox(item)
            row_h = max(y1 - y0, f["small"].metrics("linespace")) + 4
            if is_now:
                r = cv.create_rectangle(6, y, w - 6, y + row_h, fill=pal["now"], outline="", tags="cal")
                cv.tag_lower(r, item)
            bar = blend(ccol, pal["bg"], pf) if is_past else ccol
            cv.create_rectangle(10, y + 3, 14, y + row_h - 1, fill=bar, outline="", tags="cal")
            cv.create_text(18, y + 3, text=t, fill=blend(pal["dim"], pal["bg"], pf) if is_past else pal["dim"],
                           font=f["small"], anchor="nw", tags="cal")
            self.tips.append((6, y, w - 6, y + row_h, self._tip_text(ev, self.s.get("time_format", "24h"))))
            y += row_h
        return y + 10

    # --- Day / Week grid (port of render_grid)
    def _draw_grid(self, cv, w, ncols):
        f, pal = self._fonts(), self.panel.cal_palette()
        s = self.s
        today = date.today()
        d0, d1, days = self._range()
        err_h = self._error(cv, w, 0)
        evs = self.model.events_between(d0, d1)
        sh, eh = int(s["start_hour"]), int(s["end_hour"])
        sh, eh = max(0, min(sh, 23)), max(1, min(eh, 24))
        if eh <= sh:
            eh = min(24, sh + 1)
        hh = max(12, int(s["hour_height"]))
        tiny = f["tiny"]
        line_h = tiny.metrics("linespace")
        gutter = 40
        base_y = err_h
        head_h = (line_h * 2 + 8) if ncols == 7 else 4
        allday_by_col = [[e for e in evs if e["all_day"] and e["day"] == d] for d in days]
        allday_rows = max((len(a) for a in allday_by_col), default=0)
        ad_row_h = line_h + 4
        allday_h = allday_rows * ad_row_h + (6 if allday_rows else 0)
        top = base_y + head_h + allday_h
        x0 = gutter

        # column widths: equal, except in Week where a day without events shrinks to its header (shrink_empty)
        total_w = w - gutter - 8
        if ncols == 7:
            day_busy = [any(e["day"] == d for e in evs) for d in days]       # an all-day event counts
            cws = core.week_column_widths(total_w, day_busy, self._empty_col_w(f), bool(s.get("shrink_empty", True)))
        else:
            cws = [total_w / ncols] * ncols
        edges = [0.0]
        for cw_ in cws:
            edges.append(edges[-1] + cw_)

        def colx(i):
            return x0 + edges[i]

        fit = bool(s.get("fit_boxes", True))
        tf = s.get("time_format", "24h")
        min_h = line_h + 3

        def label(seg, with_time=True):
            txt = seg["title"]
            if with_time and seg["first"]:
                txt = f"{core.fmt_time(seg['start'], tf, compact=ncols == 7)} {txt}"
            return txt

        def measure(text, width):
            it = cv.create_text(0, 0, text=text, font=tiny, anchor="nw", width=max(1, width))
            bb = cv.bbox(it)
            cv.delete(it)
            return (bb[3] - bb[1]) if bb else line_h

        def hours_of(dt, d):
            return (dt - datetime.combine(d, time.min)).total_seconds() / 3600

        # 1) the on-screen height of every event
        segs_by_day, busy = [], set()
        for ci, d in enumerate(days):
            day_segs = [e for e in evs if not e["all_day"] and e["day"] == d]
            for sg in day_segs:
                h0 = max(sh, min(eh, hours_of(sg["seg_start"], d)))
                h1 = max(sh, min(eh, hours_of(sg["seg_end"], d)))
                dur_px = (h1 - h0) * hh
                if fit:
                    txt = label(sg) + (f"\n📍 {sg['location']}" if sg["location"] else "")
                    disp = max(min_h, min(dur_px, measure(txt, cws[ci] - 8) + 6))
                else:
                    disp = max(min_h, dur_px)
                sg["_disp_h"] = disp
                sg["_disp_end"] = sg["seg_start"] + timedelta(hours=disp / hh)
                he = min(eh, h0 + disp / hh)
                for k in range(int(h0), int(he - 1e-9) + 1):
                    busy.add(k)
            segs_by_day.append(day_segs)

        # 2) hour rows: empty hours are short
        eh_px = max(6, min(hh, int(s.get("empty_hour_height", 20))))
        H = {k: (hh if k in busy else eh_px) for k in range(sh, eh)}
        Y, acc = {}, top
        for k in range(sh, eh):
            Y[k] = acc
            acc += H[k]
        grid_bottom = acc

        def y_of(dt, d):
            hrs = max(sh, min(eh, hours_of(dt, d)))
            if hrs >= eh:
                return grid_bottom
            k = int(hrs)
            return Y[k] + (hrs - k) * H[k]

        def put(*a, **k):
            return cv.create_text(*a, tags=k.pop("tags", ("cal",)), **k)

        if ncols == 7:
            for i, d in enumerate(days):
                cx = colx(i) + cws[i] / 2
                put(cx, base_y + 4, text=ui.CAL_DAYS_SHORT[d.weekday()], fill=pal["accent"] if d == today else pal["dim"],
                    font=tiny, anchor="n")
                put(cx, base_y + 4 + line_h, text=str(d.day), fill=pal["accent"] if d == today else pal["text"],
                    font=f["day"], anchor="n")

        for i, items in enumerate(allday_by_col):
            for j, ev in enumerate(items):
                y = base_y + head_h + j * ad_row_h + 2
                cv.create_rectangle(colx(i) + 2, y, colx(i + 1) - 2, y + ad_row_h - 2,
                                    fill=ev["color"] or pal["event"], outline="", tags="cal")
                self._fit_text(cv, colx(i) + 5, y + 1, cws[i] - 8, ad_row_h - 2, ev["title"], pal["event_text"], tiny)
                self.tips.append((colx(i) + 2, y, colx(i + 1) - 2, y + ad_row_h - 2, self._tip_text(ev, self.s.get("time_format", "24h"))))

        for k in range(sh, eh + 1):
            y = Y.get(k, grid_bottom)
            cv.create_line(x0, y, w - 8, y, fill=pal["grid"], tags="cal")
            if k < eh:
                if H[k] >= line_h - 2:
                    put(x0 - 6, y + 2, text=core.fmt_hour_label(k, tf), fill=pal["dim"], font=tiny, anchor="ne")
                else:
                    put(x0 - 6, y + H[k] / 2, text=core.fmt_hour_label(k, tf), fill=pal["dim"],
                        font=(tiny.actual("family"), max(6, int(tiny.actual("size")) - 3)), anchor="e")
        for i in range(ncols + 1):
            cv.create_line(colx(i), top, colx(i), grid_bottom, fill=pal["grid"], tags="cal")

        # 3) events
        now = datetime.now()
        pf = max(0, min(90, int(s["past_fade"]))) / 100
        for i, d in enumerate(days):
            for sg in core.layout_lanes(segs_by_day[i]):
                y1 = y_of(sg["seg_start"], d)
                y2 = y1 + sg["_disp_h"]
                if y2 > grid_bottom:
                    y1, y2 = max(top, grid_bottom - (y2 - y1)), grid_bottom
                lw = cws[i] / sg["lanes"]
                xa = colx(i) + sg["lane"] * lw + 2
                xb = xa + lw - 3
                past = sg["end"] <= now
                base_col = sg["color"] or pal["event"]
                fill = blend(base_col, pal["bg"], pf * 0.9) if past else base_col
                tcol = blend(pal["event_text"], pal["bg"], pf * 0.75) if past else pal["event_text"]
                cv.create_rectangle(xa, y1 + 1, xb, y2 - 1, fill=fill, outline=pal["bg"], tags="cal")
                txt = label(sg, with_time=sg["lanes"] == 1)
                if sg["location"] and (y2 - y1) > line_h * 3:
                    txt += f"\n📍 {sg['location']}"
                self._fit_text(cv, xa + 3, y1 + 2, xb - xa - 5, y2 - y1 - 3, txt, tcol, tiny)
                self.tips.append((xa, y1, xb, y2, self._tip_text(sg, tf)))
            if d == today and sh <= now.hour + now.minute / 60 < eh:
                y = y_of(now, d)
                cv.create_line(colx(i), y, colx(i + 1), y, fill=pal["now_line"], width=2, tags="cal")
                cv.create_oval(colx(i) - 4, y - 4, colx(i) + 4, y + 4, fill=pal["now_line"], outline="", tags="cal")
        return grid_bottom + 10

    @staticmethod
    def _fit_text(cv, x, y, w, h, text, color, font):
        """Fit text into a box. A box lower than two lines shows one line and is cut on the right; at least
        one line is always visible (it may overflow the box a little)."""
        if w < 8:
            return
        lh = font.metrics("linespace")
        single = h < lh * 2
        base = text.replace("\n", " ") if single else text
        item = cv.create_text(x, y, text=base, fill=color, font=font, anchor="nw",
                              width=None if single else max(1, w), tags="cal")

        def too_big():
            bb = cv.bbox(item)
            if not bb:
                return False
            return (bb[2] - bb[0] > w + 1) if single else (bb[3] - bb[1] > max(h, lh))

        n = len(base)
        while too_big() and n > 1:
            n -= 1
            cv.itemconfig(item, text=base[:n].rstrip() + "…")

    # ------------------------------------------------------------ tooltips
    @staticmethod
    def _tip_text(ev, tf="24h"):
        t = ui.CAL_ALL_DAY if ev["all_day"] else f"{core.fmt_time(ev['start'], tf)}–{core.fmt_time(ev['end'], tf)}"
        lines = [ev["title"], t]
        if ev.get("location"):
            lines.append("📍 " + ev["location"])
        if ev.get("cal"):
            lines.append(ev["cal"])
        return "\n".join(lines)

    def tip_at(self, x, y):
        """The tooltip text for a point in content-canvas coordinates (scroll applied), or None."""
        vy = y + self.scroll
        for x0, y0, x1, y1, text in reversed(self.tips):
            if x0 <= x <= x1 and y0 <= vy <= y1:
                return text
        return None

    def status_text(self):
        """Refresh status for the header tooltip (it is not drawn in the panel): Loading… / error / Updated HH:MM."""
        snap = self.panel.model.snapshot() if self.panel.model is not None else None
        if snap is None:
            return ""
        lines = []
        if snap["loading"]:
            lines.append(ui.CAL_LOADING)
        if snap["error"]:
            lines.append(snap["error"])
        if snap["last_update"]:
            lines.append(ui.CAL_UPDATED.format(time=core.fmt_time(snap['last_update'], self.s.get("time_format", "24h"))))
        return "\n".join(lines)

    def show_tip(self, text, rx, ry):
        if self._tip is not None and getattr(self._tip, "_text", None) == text:
            self._tip.geometry(f"+{rx + 14}+{ry + 12}")
            return
        self.hide_tip()
        import winutil
        pal = self.panel.cal_palette()
        tw = tk.Toplevel(self.panel.top)
        tw.overrideredirect(True)
        tw.attributes("-topmost", True)
        tk.Label(tw, text=text, bg=theme.SURFACE, fg=theme.TEXT_COLOR, font=self._fonts()["small"], justify="left",
                 padx=8, pady=5, wraplength=360, relief="solid", bd=1, highlightbackground=pal["accent"]).pack()
        tw._text = text
        winutil.make_toolwindow(tw)
        tw.geometry(f"+{rx + 14}+{ry + 12}")
        self._tip = tw

    def hide_tip(self):
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None
