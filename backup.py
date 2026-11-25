"""Automatic config backup (v1.1.0, step 7d). Every start copies config.json to backups\\config-YYYYMMDD-HHMMSS.json
(next to config.json) BEFORE anything is placed, clamped or saved. A failure never stops the program (it is logged).

Only files in the backups folder whose name matches config-YYYYMMDD-HHMMSS.json are ever looked at or deleted; nothing
else is touched. The names sort by time, so 'the newest' and 'the oldest' are found by name."""
import datetime
import json
import os
import re
import shutil

import applog
import strings as ui

DIRNAME = "backups"
KEEP = 15
_PATTERN = re.compile(r"^config-\d{8}-\d{6}\.json$")


def backup_dir(config_path):
    return os.path.join(os.path.dirname(os.path.abspath(config_path)), DIRNAME)


def backup_names(folder):
    """Sorted (oldest first) names of OUR backups in the folder: regular files with the config-<date>-<time>.json name."""
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    return sorted(n for n in names if _PATTERN.match(n) and os.path.isfile(os.path.join(folder, n))
                  and not os.path.islink(os.path.join(folder, n)))


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _same_bytes(path, data):
    try:
        return _read(path) == data
    except OSError:
        return False


def _when(name):
    try:
        return datetime.datetime.strptime(name[len("config-"):-len(".json")], "%Y%m%d-%H%M%S")
    except ValueError:
        return None


def parse_config_bytes(data):
    """The config dict inside `data` (bytes), or None when it is not a usable config: it must be UTF-8 JSON, an object
    with a 'panels' object. Never raises."""
    try:
        obj = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, AttributeError):
        return None
    if isinstance(obj, dict) and isinstance(obj.get("panels"), dict):
        return obj
    return None


def list_backups(folder):
    """Our backups, NEWEST first, as dicts: name, path, when (datetime or None), readable, panel_names (list; empty when
    unreadable), panel_count, kinds (count per KIND_ORDER kind), newest (True for the first). A file that cannot be read or parsed is 'unreadable'; this
    function never raises."""
    out = []
    for name in reversed(backup_names(folder)):
        path = os.path.join(folder, name)
        cfg = None
        try:
            cfg = parse_config_bytes(_read(path))
        except OSError:
            pass
        names = list(cfg["panels"]) if cfg is not None else []
        kinds = dict.fromkeys(KIND_ORDER, 0)
        for n in names:
            kinds[panel_kind(cfg["panels"][n])] += 1
        out.append({"name": name, "path": path, "when": _when(name), "readable": cfg is not None,
                    "panel_names": [str(n) for n in names], "panel_count": len(names), "kinds": kinds,
                    "newest": not out})
    return out


KIND_ORDER = ("shortcut", "note", "calendar", "other")


def panel_kind(panel_cfg):
    """'shortcut', 'note' or 'calendar' for a panel's config; a panel with no 'type' is a shortcut panel (the program's
    default); anything else (an unknown type, a panel that is not an object) is 'other'."""
    if not isinstance(panel_cfg, dict):
        return "other"
    t = panel_cfg.get("type", "shortcut")
    return t if t in ("shortcut", "note", "calendar") else "other"


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
ROW_MAX = 78                                                     # characters before the "(newest)" tag


def row_text(entry):
    """One line of the restore list: '25 Nov 2026 11:19 — 18 panels: 9 Shortcuts, 6 Notes, 3 Calendars' (only kinds with
    a count above 0, fixed order; cut with … when long; the '(newest)' tag is never cut). Panel names are not shown."""
    t = entry["when"]
    stamp = ("%d %s %d %02d:%02d" % (t.day, _MONTHS[t.month - 1], t.year, t.hour, t.minute)) if t else entry["name"]
    if not entry["readable"]:
        text = ui.RESTORE_ROW_UNREADABLE.format(when=stamp)
    else:
        n = entry["panel_count"]
        noun = ui.RESTORE_PANEL if n == 1 else ui.RESTORE_PANELS
        parts = []
        for key in KIND_ORDER:
            c = entry["kinds"].get(key, 0)
            if c > 0:
                one, many = ui.RESTORE_KINDS[key]
                parts.append("%d %s" % (c, one if c == 1 else many))
        text = (ui.RESTORE_ROW.format(when=stamp, count=n, noun=noun, kinds=", ".join(parts)) if n
                else ui.RESTORE_ROW_EMPTY.format(when=stamp))
    if len(text) > ROW_MAX:
        text = text[:ROW_MAX - 1].rstrip() + "…"
    return text + (" " + ui.RESTORE_NEWEST if entry["newest"] else "")


def _with_hide_restore(data, current_bytes):
    """`data` (a config, bytes) with general.hide_icons_restore taken from the CURRENT config (bytes): that value belongs
    to this computer's desktop right now, not to whenever the backup was made. Unchanged when it already matches."""
    cur = parse_config_bytes(current_bytes) if current_bytes else None
    new = parse_config_bytes(data)
    if cur is None or new is None:
        return data
    cg = cur.get("general")
    value = cg.get("hide_icons_restore") if isinstance(cg, dict) else None
    ng = new.get("general")
    if not isinstance(ng, dict):
        if value is None:
            return data
        ng = new["general"] = {}
    if ng.get("hide_icons_restore") == value and ("hide_icons_restore" in ng or value is None):
        return data
    ng["hide_icons_restore"] = value
    return json.dumps(new, ensure_ascii=False, indent=2).encode("utf-8")


def prepare_restore(config_path, backup_path):
    """Step 1 of a restore. Reads the chosen backup into memory and checks it (ValueError when it is not a usable config;
    nothing else is touched then), THEN backs up the current config (BackupFailed when that does not work) (the rotation may delete the chosen file; its bytes
    are already in memory), and returns the bytes to write later (see write_restore)."""
    try:
        data = _read(backup_path)
    except OSError as e:
        raise ValueError("backup cannot be read") from e
    if parse_config_bytes(data) is None:
        raise ValueError("backup is not a usable config")
    make_backup(config_path, strict=True)                        # BackupFailed: the restore must not go on
    return _with_hide_restore(data, _read_or_none(config_path))


def _read_or_none(path):
    try:
        return _read(path)
    except OSError:
        return None


def write_restore(config_path, data):
    """The LAST step of quit: atomically replace config.json with `data` (temp file + replace). hide_icons_restore is taken
    again from the config as it is NOW (after every save). A failure is logged and leaves the current config untouched.
    Returns True when written."""
    tmp = config_path + ".restore.tmp"
    try:
        data = _with_hide_restore(data, _read_or_none(config_path))
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, config_path)
        applog.get_logger().info("config restored from a backup")
        return True
    except Exception as e:                                       # noqa: BLE001
        try:
            applog.get_logger().warning("config restore failed: %s", type(e).__name__)
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:                                        # noqa: BLE001
            pass
        return False


class BackupFailed(Exception):
    """The current config could not be backed up (restore only; the start-up backup just logs)."""


def make_backup(config_path, keep=KEEP, now=None, strict=False):
    """Copy config.json into backups\\ unless it is missing or identical (byte for byte) to the newest backup; then keep
    at most `keep` backups (oldest deleted). Returns the new backup's path, or None (nothing to do, or it failed).
    strict=True (restore): a failure raises BackupFailed instead of being swallowed, and the new file is checked to
    exist with the same bytes; 'nothing to do' (no config, or an identical backup exists) is still a success."""
    log = applog.get_logger()
    try:
        if not os.path.isfile(config_path):
            return None                                          # first installation: nothing to back up
        data = _read(config_path)
        folder = backup_dir(config_path)
        os.makedirs(folder, exist_ok=True)
        names = backup_names(folder)
        if any(_same_bytes(os.path.join(folder, n), data) for n in names):
            return None                                          # same as ANY existing backup: nothing new to keep
        t = now or datetime.datetime.now()
        while True:
            name = "config-%s.json" % t.strftime("%Y%m%d-%H%M%S")
            if name not in names and not os.path.exists(os.path.join(folder, name)):
                break
            t += datetime.timedelta(seconds=1)                   # same second as an older backup: the next free one
        dest = os.path.join(folder, name)
        shutil.copyfile(config_path, dest)
        if strict and not _same_bytes(dest, data):
            raise OSError("the new backup is missing or differs")
        names = backup_names(folder)
        try:
            for old in names[:max(0, len(names) - keep)]:
                os.remove(os.path.join(folder, old))
        except OSError:
            if not strict:                                       # (restore: the copy is safe; only old ones stay)
                raise
        log.info("config backed up: %s", name)
        return dest
    except Exception as e:                                       # noqa: BLE001  (a backup problem must not stop the start)
        try:
            log.warning("config backup failed: %s", type(e).__name__)
        except Exception:                                        # noqa: BLE001
            pass
        if strict:
            raise BackupFailed(type(e).__name__) from e
        return None
