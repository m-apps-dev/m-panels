"""Reads CHANGELOG.md (the single source of the release notes). No tkinter, so it is testable on its own.

Format:  `## <version> — <date>` starts a release, `### <Section>` a group, `- text` an entry.
`## Unreleased` collects entries of steps in progress; the parser skips them until the heading becomes a version."""
import os
import re

import strings as ui

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "CHANGELOG.md")

_REL = re.compile(r"^##\s+v?(\d+\.\d+\.\d+)\s*(?:[—–-]\s*(.+?))?\s*$")
_UNRELEASED = re.compile(r"^##\s+Unreleased\s*$", re.IGNORECASE)
_SEC = re.compile(r"^###\s+(.+?)\s*$")
_ITEM = re.compile(r"^[-*]\s+(.*\S)\s*$")


def parse(text):
    """-> [{'version', 'date', 'sections': [(name, [entries])]}] in file order (newest first)."""
    releases, rel, sec = [], None, None
    for line in text.splitlines():
        if _UNRELEASED.match(line):          # work in progress: not a release, never shown, never leaks into another
            rel, sec = None, None
            continue
        m = _REL.match(line)
        if m:
            rel = {"version": m.group(1), "date": m.group(2) or "", "sections": []}
            releases.append(rel)
            sec = None
            continue
        m = _SEC.match(line)
        if m and rel is not None:
            sec = (m.group(1), [])
            rel["sections"].append(sec)
            continue
        m = _ITEM.match(line)
        if m and sec is not None:
            sec[1].append(m.group(1))
    return releases


def load(path=PATH):
    """Parsed releases from the file; [] when it is missing or unreadable (never raises)."""
    try:
        with open(path, encoding="utf-8") as f:
            return parse(f.read())
    except (OSError, UnicodeError):
        return []


def render(releases):
    """Plain-text blocks for a read-only Text widget: [(tag, text)] with tags 'ver', 'sec', 'item'."""
    out = []
    for r in releases:
        out.append(("ver", ui.ABOUT_VER_PREFIX + r["version"] + (ui.ABOUT_DATE_SEP + r["date"] if r["date"] else "")))
        for name, items in r["sections"]:
            out.append(("sec", name))
            out.extend(("item", ui.ABOUT_BULLET + i) for i in items)
    return out
