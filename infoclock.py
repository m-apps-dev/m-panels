"""The bar's Info section (v1.2 step 1): the "bar" part of config.json and the date/time text. Pure functions, no tkinter,
so the clock is tested with a made-up `now`.

Text: English names from strings.py (the same tables the Calendar uses), one clock formatter for the whole program
(calendar_panel.core.fmt_time), no seconds:  "Tuesday 24 November · 14:32"."""
import copy

import search
import startmenu
import strings as ui
import theme
from calendar_panel import core

TIME_FORMATS = core.TIME_FORMATS
MINUTE_MS = 60000
PAD_MS = 30             # fire just AFTER the minute turns, never just before it


def defaults():
    """The factory 'bar' config: the bar is OFF."""
    return {"enabled": False, "info": {"enabled": True, "time_format": "24h", "show_date": True},
            "tasks": {"enabled": True, "show_titles": True}, "search": search.defaults(), "start": startmenu.defaults(),
            "colors": {}}


def _bool(v, default):
    return v if isinstance(v, bool) else default


def sanitize_colors(colors):
    """Only the colors the user changed: known keys with a valid #rrggbb value (lower-case); everything else is dropped
    (a missing key means "the derived default")."""
    src = colors if isinstance(colors, dict) else {}
    return {k: src[k].lower() for k in theme.BAR_COLOR_KEYS if k in src and theme.is_hex_color(src[k])}


def sanitize(bar):
    """A complete, valid 'bar' dict. Wrong types fall back to the defaults; keys we do not know are kept."""
    base = defaults()
    src = bar if isinstance(bar, dict) else {}
    out = {k: copy.deepcopy(v) for k, v in src.items() if k not in base}
    out["enabled"] = _bool(src.get("enabled"), base["enabled"])
    info_src = src.get("info") if isinstance(src.get("info"), dict) else {}
    info = {k: copy.deepcopy(v) for k, v in info_src.items() if k not in base["info"]}
    info["enabled"] = _bool(info_src.get("enabled"), base["info"]["enabled"])
    info["time_format"] = info_src.get("time_format") if info_src.get("time_format") in TIME_FORMATS \
        else base["info"]["time_format"]
    info["show_date"] = _bool(info_src.get("show_date"), base["info"]["show_date"])
    out["info"] = info
    tasks_src = src.get("tasks") if isinstance(src.get("tasks"), dict) else {}
    tasks = {k: copy.deepcopy(v) for k, v in tasks_src.items() if k not in base["tasks"]}
    tasks["enabled"] = _bool(tasks_src.get("enabled"), base["tasks"]["enabled"])
    tasks["show_titles"] = _bool(tasks_src.get("show_titles"), base["tasks"]["show_titles"])
    out["tasks"] = tasks
    out["search"] = search.sanitize(src.get("search"))
    out["start"] = startmenu.sanitize(src.get("start"))
    out["colors"] = sanitize_colors(src.get("colors"))
    return out


def format_info(now, time_format="24h", show_date=True):
    t = core.fmt_time(now, time_format)
    if not show_date:
        return t
    return ui.BAR_INFO.format(weekday=ui.CAL_DAYS[now.weekday()], day=now.day, month=ui.CAL_MONTHS[now.month - 1],
                              time=t)


def next_delay_ms(now):
    """Milliseconds from `now` to just after the next minute boundary (always 31..60030): recomputed at EVERY firing,
    so an early or late firing, a sleep or a clock change cannot make it drift."""
    into = now.second * 1000 + now.microsecond // 1000
    return MINUTE_MS - into + PAD_MS
