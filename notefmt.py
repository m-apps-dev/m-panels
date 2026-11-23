"""Note file format (pure Python, no tkinter): text + formatting spans, as JSON.

Dosya:  {"format": 1, "text": "...", "spans": [{"start": 0, "end": 5, "bold": true, "italic": ...,
         "underline": ..., "color": "#rrggbb", "font": "Arial", "size": 14}, ...]}
Spans are character offsets (start inclusive, end exclusive). Only OVERRIDDEN attributes are written;
a missing attribute comes from the panel's content font.
"""
import json

import strings as ui
import theme

FORMAT = 1
ATTRS = ("font", "size", "bold", "italic", "underline", "color")


def clean_attr(key, v):
    """Validate one attribute; None if invalid (= no attribute)."""
    if key in ("bold", "italic", "underline"):
        return v if isinstance(v, bool) else None
    if key == "color":
        return v.lower() if theme.is_hex_color(v) else None
    if key == "font":
        return v.strip() if isinstance(v, str) and v.strip() and len(v) < 120 else None
    if key == "size":
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        return theme.normalize_font_size(v)
    return None


def clean_spans(spans, limit=None):
    """Drop invalid/empty spans, sort them, resolve overlaps and merge identical neighbours.
    If limit is given, spans are clipped to [0, limit]."""
    out = []
    if not isinstance(spans, list):
        return out
    for sp in spans:
        if not isinstance(sp, dict):
            continue
        s, e = sp.get("start"), sp.get("end")
        if isinstance(s, bool) or isinstance(e, bool) or not isinstance(s, int) or not isinstance(e, int):
            continue
        s = max(0, s)
        e = min(e, limit) if limit is not None else e
        if e <= s:
            continue
        attrs = {k: clean_attr(k, sp.get(k)) for k in ATTRS}
        attrs = {k: v for k, v in attrs.items() if v is not None}
        if attrs:
            out.append({"start": s, "end": e, **attrs})
    out.sort(key=lambda x: (x["start"], x["end"]))
    res = []
    for sp in out:
        if res and sp["start"] < res[-1]["end"]:            # overlap: the later span starts where the earlier one ends
            sp = {**sp, "start": res[-1]["end"]}
            if sp["end"] <= sp["start"]:
                continue
        prev = res[-1] if res else None
        if prev and prev["end"] == sp["start"] and all(prev.get(k) == sp.get(k) for k in ATTRS):
            prev["end"] = sp["end"]
        else:
            res.append(dict(sp))
    return res


def dumps(text, spans):
    return json.dumps({"format": FORMAT, "text": text, "spans": clean_spans(spans)},
                      ensure_ascii=False, indent=1, sort_keys=True)


def loads(raw):
    """JSON text -> (text, spans). Raises ValueError if invalid."""
    try:
        d = json.loads(raw)
    except (ValueError, TypeError) as e:
        raise ValueError(ui.NOTE_JSON_UNREADABLE.format(error=e))
    if not isinstance(d, dict) or not isinstance(d.get("text"), str):
        raise ValueError(ui.NOTE_JSON_INVALID)
    return d["text"], clean_spans(d.get("spans", []))
