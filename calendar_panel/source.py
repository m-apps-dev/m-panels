r"""One-time import of a calendar list from a JSON file (READ-ONLY).

The file is expected to look like {"calendars": [{"name", "url", "color", "enabled"}]} (an older single
"ics_url" entry is understood too). The url is a secret iCal/ICS address, so it is treated like a password:
it is never logged and never put into an error message or a window title. The file is only read once, when
the user asks for an import; its path is not stored anywhere.
"""
import json
import os
import re

import strings as ui

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class SourceError(Exception):
    """The file is missing or unreadable. str(e) is a short, secret-free message."""


def _clean(entry):
    if not isinstance(entry, dict):
        return None
    url = str(entry.get("url", "") or "").strip()
    if not url:
        return None
    color = entry.get("color")
    return {"name": str(entry.get("name", "") or "").strip(), "url": url,
            "color": color if isinstance(color, str) and _HEX.match(color) else None,
            "enabled": bool(entry.get("enabled", True))}


def read_sources(path):
    """All calendars with an address from the file, as clean dicts. Raises SourceError."""
    if not path or not os.path.isfile(path):
        raise SourceError(ui.CAL_ERR_NO_SOURCE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except (OSError, ValueError) as e:
        raise SourceError(ui.CAL_ERR_SOURCE_BAD.format(error=e.__class__.__name__)) from None
    cals = [c for c in (_clean(x) for x in data.get("calendars") or []) if c]
    legacy = str(data.get("ics_url", "") or "").strip()
    if legacy and not cals:                       # the old single-address setting
        cals = [{"name": ui.CAL_LEGACY_NAME, "url": legacy, "color": None, "enabled": True}]
    for i, c in enumerate(cals, 1):
        if not c["name"]:
            c["name"] = f"{ui.CAL_ERR_UNNAMED} {i}"
    return cals


def merge(existing, imported):
    """`existing` plus those `imported` calendars whose address is not in the list yet. Returns (list, added)."""
    out = [dict(c) for c in existing]
    have = {c["url"] for c in out}
    added = 0
    for c in imported:
        if c["url"] not in have:
            out.append(dict(c))
            have.add(c["url"])
            added += 1
    return out, added
