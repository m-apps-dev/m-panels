"""Rich-text layer of the note panel: bold/italic/underline/color/font/size on a tk.Text.

Model: every character has overridden attributes (font, size, bold, italic, underline, color);
a missing attribute comes from the panel's content font (the base).
  * font+size+bold+italic are combined into a single "fmt:[...]" tag (Tk font tags do not merge);
  * underline is the "ul" tag and color is "col:#rrggbb" (independent options, they do merge).
The file format lives in notefmt.py; this module only converts Text <-> (text, spans).
"""
import json

import notefmt

UL = "ul"


def fmt_tag(font=None, size=None, bold=None, italic=None):
    return "fmt:" + json.dumps([font, size, bold, italic], ensure_ascii=False)


class RichText:
    """text: tk.Text; base: () -> {'font','size','bold','italic'} (the panel's content font)."""

    def __init__(self, text, base):
        self.t, self.base = text, base

    # ------------------------------------------------------------ position helpers
    def _off(self, index):
        r = self.t.count("1.0", index, "chars")
        if not r:
            return 0
        return int(r[0] if isinstance(r, (tuple, list)) else r)

    def _idx(self, off):
        return f"1.0+{int(off)}c"

    def total(self):
        return self._off("end-1c")

    def selection(self):
        """(start, end) character offsets, or None."""
        r = self.t.tag_ranges("sel")
        if not r:
            return None
        a, b = self._off(r[0]), self._off(r[1])
        return (a, b) if b > a else None

    # ------------------------------------------------------------ tags
    def _ours(self, name):
        return name == UL or name.startswith("fmt:") or name.startswith("col:")

    def _ensure(self, name):
        """(Re)configure a tag: the font is computed from the base."""
        if name == UL:
            self.t.tag_configure(UL, underline=True)
        elif name.startswith("col:"):
            self.t.tag_configure(name, foreground=name[4:])
        elif name.startswith("fmt:"):
            fam, size, bold, ital = json.loads(name[4:])
            b = self.base()
            fam = fam or b["font"]
            size = size or b["size"]
            bold = b["bold"] if bold is None else bold
            ital = b["italic"] if ital is None else ital
            styles = (["bold"] if bold else []) + (["italic"] if ital else [])
            self.t.tag_configure(name, font=(fam, int(size), *(styles or ["normal"])))

    def restyle(self):
        """When the base font changes, recompute the font of the formatted parts."""
        for n in self.t.tag_names():
            if n.startswith("fmt:"):
                self._ensure(n)

    def _attrs_at(self, index):
        a = {"font": None, "size": None, "bold": None, "italic": None, "underline": False, "color": None}
        for n in self.t.tag_names(index):
            if n.startswith("fmt:"):
                a["font"], a["size"], a["bold"], a["italic"] = json.loads(n[4:])
            elif n == UL:
                a["underline"] = True
            elif n.startswith("col:"):
                a["color"] = n[4:]
        return a

    def _boundaries(self, lo, hi):
        pts = {lo, hi}
        for n in self.t.tag_names():
            if not self._ours(n):
                continue
            r = self.t.tag_ranges(n)
            for i in range(0, len(r), 2):
                for o in (self._off(r[i]), self._off(r[i + 1])):
                    if lo < o < hi:
                        pts.add(o)
        return sorted(pts)

    def _segments(self, lo, hi):
        """[(a, b, attributes)] — the range [lo, hi) split into pieces of constant formatting."""
        pts = self._boundaries(lo, hi)
        return [(a, b, self._attrs_at(self._idx(a))) for a, b in zip(pts, pts[1:]) if b > a]

    def _set(self, a, b, at):
        """Remove all formatting tags over [a,b) and apply the attributes `at`."""
        s, e = self._idx(a), self._idx(b)
        for n in self.t.tag_names():
            if self._ours(n):
                self.t.tag_remove(n, s, e)
        if any(at[k] is not None for k in ("font", "size", "bold", "italic")):
            n = fmt_tag(at["font"], at["size"], at["bold"], at["italic"])
            self._ensure(n)
            self.t.tag_add(n, s, e)
        if at["underline"]:
            self._ensure(UL)
            self.t.tag_add(UL, s, e)
        if at["color"]:
            n = "col:" + at["color"]
            self._ensure(n)
            self.t.tag_add(n, s, e)

    # ------------------------------------------------------------ load / save
    def load(self, text, spans):
        t = self.t
        t.delete("1.0", "end")
        for n in t.tag_names():
            if self._ours(n):
                t.tag_remove(n, "1.0", "end")
        t.insert("1.0", text)
        total = self.total()
        for sp in notefmt.clean_spans(spans, total):
            self._set(sp["start"], sp["end"], {
                "font": sp.get("font"), "size": sp.get("size"), "bold": sp.get("bold"),
                "italic": sp.get("italic"), "underline": bool(sp.get("underline")), "color": sp.get("color")})
        t.edit_reset()
        t.edit_modified(False)

    def dump(self):
        """(text, spans) — spans in notefmt form, identical neighbours merged."""
        text = self.t.get("1.0", "end-1c")
        spans = []
        for a, b, at in self._segments(0, self.total()):
            sp = {"start": a, "end": b}
            for k in ("font", "size", "bold", "italic", "color"):
                if at[k] is not None:
                    sp[k] = at[k]
            if at["underline"]:
                sp["underline"] = True
            if len(sp) > 2:
                spans.append(sp)
        return text, notefmt.clean_spans(spans)

    # ------------------------------------------------------------ formatting operations (on the selection)
    def _modify(self, fn):
        sel = self.selection()
        if not sel:
            return False
        segs = self._segments(*sel)
        for a, b, at in segs:
            self._set(a, b, fn(at))
        return True

    def _eff(self, at, key):
        return self.base()[key] if at[key] is None else at[key]

    def toggle(self, key):
        """key: 'bold' | 'italic' | 'underline'. Turns it off if the whole selection has it, otherwise on for all."""
        sel = self.selection()
        if not sel:
            return False
        segs = self._segments(*sel)
        if key == "underline":
            new = not all(at["underline"] for _, _, at in segs)
            return self._modify(lambda at: {**at, "underline": new})
        new = not all(self._eff(at, key) for _, _, at in segs)
        val = None if new == self.base()[key] else new
        return self._modify(lambda at: {**at, key: val})

    def set_color(self, color):
        return self._modify(lambda at: {**at, "color": color})

    def set_font(self, family):
        return self._modify(lambda at: {**at, "font": family})

    def set_size(self, size):
        return self._modify(lambda at: {**at, "size": int(size)})

    def clear_format(self):
        return self._modify(lambda at: {"font": None, "size": None, "bold": None, "italic": None,
                                        "underline": False, "color": None})

    def effective(self, index):
        """For tests/preview: the effective font and color of that character."""
        at = self._attrs_at(index)
        b = self.base()
        return {"font": at["font"] or b["font"], "size": at["size"] or b["size"],
                "bold": self._eff(at, "bold"), "italic": self._eff(at, "italic"),
                "underline": at["underline"], "color": at["color"]}
