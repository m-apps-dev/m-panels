"""Per-panel calendar settings (the `calendar` dict in a panel's config). Pure, no tkinter."""
import copy
import re

VIEW_KEYS = ("list", "day", "week")
# Colors the user may override (all keys of view.make_palette except "bg", which always follows the panel color)
COLOR_KEYS = ("text", "dim", "accent", "event", "event_text", "now", "now_line", "grid", "warn")
_HEX6 = re.compile(r"#[0-9a-fA-F]{6}")
REFRESH_MIN, REFRESH_MAX = 1, 120
WIDTH_MIN, WIDTH_MAX = 150, 4000                # panel width per view (WIDTH_MIN equals mpanels.MIN_W; a test checks it)
# Everything below the first four keys keeps M Calendar's defaults and has no UI.
DEFAULTS = {
    # [{"name", "url", "color", "enabled"}]. The url is a secret iCal address: it lives only here (and in the
    # config file on disk); it is never logged, never shown in a title/tooltip/error and never part of the "look".
    "calendars": [],
    "view": "list",
    "list_weeks": 1,
    "refresh_minutes": 5,
    "start_hour": 7,
    "end_hour": 24,
    "hour_height": 30,
    "fit_boxes": True,
    "time_format": "24h",                       # "24h" | "12h"
    "week_start": "monday",                     # "monday" | "sunday" (Week view only; List always starts today)
    "shrink_empty": True,                       # Week: days without events shrink to their header width
    "empty_hour_height": 20,
    "past_fade": 55,
    "widths": {},                               # width remembered per view: {"list": px, "day": px, "week": px}
    "colors": {},                               # ONLY the colors the user overrode: {key: "#rrggbb"}; absent = derived
}


# The "look" of a calendar panel: the ONE list of keys that "Make current look the default" saves and that
# new panels / "Revert to defaults" / "Factory settings" restore. Source, calendar choice, view, weeks and
# refresh are NOT part of it.
LOOK_KEYS = ("start_hour", "end_hour", "hour_height", "empty_hour_height", "fit_boxes", "past_fade",
             "time_format", "week_start", "shrink_empty", "widths", "colors")


def _int(v, lo, hi, default):
    if isinstance(v, bool) or v is None:
        return default
    try:
        n = int(round(float(str(v).strip().replace(",", "."))))
    except (ValueError, TypeError, OverflowError):
        return default
    return max(lo, min(hi, n))


def clean_calendar(e):
    """One valid calendar entry, or None (not a dict / no address)."""
    if not isinstance(e, dict):
        return None
    url = e.get("url")
    if not isinstance(url, str) or not url.strip():
        return None
    name, color = e.get("name"), e.get("color")
    return {"name": name.strip() if isinstance(name, str) else "", "url": url.strip(),
            "color": color.strip().lower() if isinstance(color, str) and _HEX6.fullmatch(color.strip()) else None,
            "enabled": bool(e.get("enabled", True))}


def pending_migration(s):
    """(source_path, ticked_names) when a pre-1.1.1 `source_path` is still waiting for the one-time question."""
    path = s.get("source_path") if isinstance(s, dict) else None
    if isinstance(path, str) and path.strip():
        return path.strip(), list(s.get("legacy_names") or [])
    return None


def finish_migration(s, imported=None, ticked=None):
    """`s` without the old source_path / legacy names. `imported` (clean calendars) is appended; when the old
    setting ticked some names, only those stay enabled."""
    out = {k: v for k, v in s.items() if k not in ("source_path", "legacy_names")}
    cals = [dict(c) for c in out.get("calendars") or []]
    have = {c["url"] for c in cals}
    for c in imported or []:
        if c["url"] not in have:
            c = dict(c)
            if ticked:
                c["enabled"] = c["name"] in set(ticked)
            cals.append(c)
            have.add(c["url"])
    out["calendars"] = cals
    return sanitize(out)


def sanitize(d):
    """A complete, valid settings dict from whatever the config held (missing/broken values -> defaults)."""
    d = d if isinstance(d, dict) else {}
    out = copy.deepcopy(DEFAULTS)
    cals = d.get("calendars")
    legacy_names = []
    if isinstance(cals, list):
        out["calendars"] = [c for c in (clean_calendar(x) for x in cals) if c]
        legacy_names = [c.strip() for c in cals if isinstance(c, str) and c.strip()]     # pre-1.1.1: ticked names
    kept = d.get("legacy_names")                # ...and the same names after a first sanitize
    if isinstance(kept, list):
        legacy_names += [c.strip() for c in kept if isinstance(c, str) and c.strip()]
    path = d.get("source_path")                 # pre-1.1.1 setting: kept ONLY until the migration question is answered
    if isinstance(path, str) and path.strip():
        out["source_path"] = path.strip()
        if legacy_names:
            out["legacy_names"] = legacy_names
    if d.get("view") in VIEW_KEYS:
        out["view"] = d["view"]
    out["list_weeks"] = _int(d.get("list_weeks"), 1, 4, DEFAULTS["list_weeks"])
    out["refresh_minutes"] = _int(d.get("refresh_minutes"), REFRESH_MIN, REFRESH_MAX, DEFAULTS["refresh_minutes"])
    out["start_hour"] = _int(d.get("start_hour"), 0, 23, DEFAULTS["start_hour"])
    out["end_hour"] = _int(d.get("end_hour"), 1, 24, DEFAULTS["end_hour"])
    if out["end_hour"] <= out["start_hour"]:
        out["end_hour"] = min(24, out["start_hour"] + 1)
    out["hour_height"] = _int(d.get("hour_height"), 12, 200, DEFAULTS["hour_height"])
    out["empty_hour_height"] = _int(d.get("empty_hour_height"), 6, 200, DEFAULTS["empty_hour_height"])
    out["past_fade"] = _int(d.get("past_fade"), 0, 90, DEFAULTS["past_fade"])
    out["fit_boxes"] = bool(d.get("fit_boxes", True))
    out["shrink_empty"] = bool(d.get("shrink_empty", True))
    out["time_format"] = d.get("time_format") if d.get("time_format") in ("24h", "12h") else "24h"
    out["week_start"] = d.get("week_start") if d.get("week_start") in ("monday", "sunday") else "monday"
    out["widths"] = {}
    w = d.get("widths")
    if isinstance(w, dict):
        for k in VIEW_KEYS:                     # unknown keys are dropped; missing/broken values mean "not recorded"
            n = _int(w.get(k), WIDTH_MIN, WIDTH_MAX, 0)
            if n:
                out["widths"][k] = n
    out["colors"] = {}
    c = d.get("colors")
    if isinstance(c, dict):
        for k in COLOR_KEYS:                    # unknown keys / broken values are ignored (the derived color is used)
            v = c.get(k)
            if isinstance(v, str) and _HEX6.fullmatch(v.strip()):
                out["colors"][k] = v.strip().lower()
    return out


def look_of(s):
    """The look subset of a settings dict (validated; anything missing or broken -> built-in value)."""
    full = sanitize(s)
    return {k: copy.deepcopy(full[k]) for k in LOOK_KEYS}


def with_look(s, look):
    """`s` with its look keys replaced by `look` (sanitized, keys outside LOOK_KEYS in `look` are ignored).
    Source, calendar choice, view, weeks and refresh stay as they are."""
    base = sanitize(s)
    base.update(look_of(look if isinstance(look, dict) else None))
    return sanitize(base)
