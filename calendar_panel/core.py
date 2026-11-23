"""Calendar logic ported from M Calendar (takvim_widget.py v1.5.0): download, parse, expand, layout.

Behaviour is kept as in the original; only the user-visible words come from strings.py. No tkinter here,
so everything can be tested without a display or a network. The heavy libraries are imported lazily
so the pure helpers (day_label, layout_lanes) work even when they are missing.
"""
import urllib.request
from datetime import date, datetime, time, timedelta

import strings as ui
import theme

USER_AGENT = "MPanels-Calendar/1.0"
TIMEOUT = 30


def parse_calendar(data):
    """iCal bytes/text -> icalendar.Calendar."""
    import icalendar
    return icalendar.Calendar.from_ical(data)


def download_calendar(url):
    """Download an (secret) iCal/ICS address and parse it. `webcal://` is treated as `https://`."""
    url = url.strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = r.read()
    return parse_calendar(data)


def _to_local(value):
    """date -> (midnight datetime, True); datetime -> (local time, False)."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone().replace(tzinfo=None)
        return value, False
    return datetime.combine(value, time.min), True


def expand(cal, d0, d1, meta=None):
    """Split the events between d0 (inclusive) and d1 (exclusive) into per-day pieces."""
    import recurring_ical_events
    start = datetime.combine(d0, time.min).astimezone()
    end = datetime.combine(d1, time.min).astimezone()
    out = []
    for ev in recurring_ical_events.of(cal).between(start, end):
        if str(ev.get("STATUS", "")).upper() == "CANCELLED":
            continue
        dtstart = ev.get("DTSTART")
        if dtstart is None:
            continue
        s, all_day = _to_local(dtstart.dt)
        dtend = ev.get("DTEND")
        if dtend is not None:
            e, _ = _to_local(dtend.dt)
        elif ev.get("DURATION") is not None:
            e = s + ev.get("DURATION").dt
        else:
            e = s + (timedelta(days=1) if all_day else timedelta(0))
        title = str(ev.get("SUMMARY", "") or "").strip() or ui.CAL_UNTITLED
        location = str(ev.get("LOCATION", "") or "").strip()
        base = {"title": title, "location": location, "all_day": all_day,
                "start": s, "end": e,
                "color": (meta or {}).get("color"), "cal": (meta or {}).get("name", "")}

        if all_day:
            if e.date() <= s.date():
                e = s + timedelta(days=1)
            d = max(s.date(), d0)
            while d < e.date() and d < d1:
                out.append({**base, "day": d, "first": d == s.date(),
                            "seg_start": None, "seg_end": None})
                d += timedelta(days=1)
        else:
            last = s.date() if e <= s else (e - timedelta(microseconds=1)).date()
            d = max(s.date(), d0)
            while d <= last and d < d1:
                day0 = datetime.combine(d, time.min)
                out.append({**base, "day": d, "first": d == s.date(),
                            "seg_start": max(s, day0),
                            "seg_end": max(min(e, day0 + timedelta(days=1)), max(s, day0))})
                d += timedelta(days=1)

    out.sort(key=lambda x: (x["day"], not x["all_day"],
                            x["seg_start"] or datetime.min, x["title"]))
    return out


def layout_lanes(segs, min_minutes=20):
    """Place overlapping events side by side in lanes.
    min_minutes: the shortest time a box covers on screen (one text line)."""
    for s in segs:
        if "_disp_end" in s:   # the end to draw on screen (fitted to the content)
            s["_e"] = s["_disp_end"]
        else:
            s["_e"] = max(s["seg_end"], s["seg_start"] + timedelta(minutes=min_minutes))
    segs = sorted(segs, key=lambda s: (s["seg_start"], -(s["_e"] - s["seg_start"])))
    clusters, cur, cur_end = [], [], None
    for s in segs:
        if cur and s["seg_start"] >= cur_end:
            clusters.append(cur)
            cur, cur_end = [], None
        cur.append(s)
        cur_end = s["_e"] if cur_end is None else max(cur_end, s["_e"])
    if cur:
        clusters.append(cur)
    for cl in clusters:
        lanes = []
        for s in cl:
            for i, lane_end in enumerate(lanes):
                if s["seg_start"] >= lane_end:
                    lanes[i] = s["_e"]
                    s["lane"] = i
                    break
            else:
                s["lane"] = len(lanes)
                lanes.append(s["_e"])
        for s in cl:
            s["lanes"] = len(lanes)
    return segs


def week_column_widths(total, busy, empty_w, shrink=True, busy_min=theme.CAL_BUSY_MIN_W, empty_min=theme.CAL_EMPTY_MIN_W):
    """Widths (px) of the Week columns; they add up to `total`.
    busy[i]: the day has at least one event (an all-day event counts); empty_w: the ONE fixed width of every empty
    column (the widest possible day header, measured once; it does not depend on the day or the week).
    Without `shrink`, with no busy day or with every day busy: all columns are equal.
    Otherwise an empty day gets just its header width and the busy days share the rest EQUALLY. When that would
    leave a busy column narrower than `busy_min`: (b) busy columns stay at busy_min and the empty ones shrink
    proportionally, still equal to each other (not below `empty_min`); (c) if that is still not enough, the empty ones stay at `empty_min`
    and the busy ones share the rest equally (below busy_min); (d) if even that is impossible, all equal."""
    n = len(busy)
    if n == 0:
        return []
    equal = [total / n] * n
    k = sum(1 for b in busy if b)
    m = n - k
    if not shrink or k == 0 or m == 0 or total <= 0:
        return equal
    ew = float(max(empty_w, empty_min))
    heads = [ew] * n
    sum_empty = ew * m
    share = (total - sum_empty) / k
    if share >= busy_min:
        return [share if busy[i] else heads[i] for i in range(n)]
    leftover = total - k * busy_min
    if leftover > 0:
        f = leftover / sum_empty
        if all(heads[i] * f >= empty_min for i in range(n) if not busy[i]):
            return [float(busy_min) if busy[i] else heads[i] * f for i in range(n)]
    share = (total - m * empty_min) / k
    if share >= empty_min:
        return [share if busy[i] else float(empty_min) for i in range(n)]
    return equal


TIME_FORMATS = ("24h", "12h")
WEEK_STARTS = ("monday", "sunday")


def fmt_time(dt, fmt="24h", compact=False):
    """The ONE place that formats a clock time. 24h: 14:30. 12h: '2 PM' / '2:30 PM' (minutes only when not 0);
    compact (narrow Week boxes and the hour labels): '2p' / '2:30p'."""
    if fmt != "12h":
        return f"{dt:%H:%M}"
    h = dt.hour % 12 or 12
    pm = dt.hour >= 12
    if compact:
        suf = ui.CAL_PM_SHORT if pm else ui.CAL_AM_SHORT
        return f"{h}{suf}" if dt.minute == 0 else f"{h}:{dt.minute:02d}{suf}"
    suf = ui.CAL_PM if pm else ui.CAL_AM
    return f"{h} {suf}" if dt.minute == 0 else f"{h}:{dt.minute:02d} {suf}"


def fmt_hour_label(k, fmt="24h"):
    """Hour-grid label of hour k (0-23): '07' or, in 12h, the short '7a' / '12p'."""
    if fmt != "12h":
        return f"{k:02d}"
    return fmt_time(datetime(2000, 1, 1, k % 24), "12h", compact=True)


def time_sample(fmt="24h"):
    """The widest typical time text of a format (used to measure the List time column)."""
    return fmt_time(datetime(2000, 1, 1, 12, 30), fmt)


def week_start_of(d, week_start="monday"):
    """The first day of d's week: Monday (default) or Sunday."""
    first = 6 if week_start == "sunday" else 0
    return d - timedelta(days=(d.weekday() - first) % 7)


def day_label(d, today=None):
    today = today or date.today()
    base = f"{d.day} {ui.CAL_MONTHS[d.month - 1]} {ui.CAL_DAYS[d.weekday()]}"
    if d == today:
        return f"{ui.CAL_TODAY} · " + base
    if d == today + timedelta(days=1):
        return f"{ui.CAL_TOMORROW} · " + base
    return base
