"""Automatic config backup (v1.1.0, step 7d). Every start copies config.json to backups\\config-YYYYMMDD-HHMMSS.json
(next to config.json) BEFORE anything is placed, clamped or saved. A failure never stops the program (it is logged).

Only files in the backups folder whose name matches config-YYYYMMDD-HHMMSS.json are ever looked at or deleted; nothing
else is touched. The names sort by time, so 'the newest' and 'the oldest' are found by name."""
import datetime
import os
import re
import shutil

import applog

DIRNAME = "backups"
KEEP = 15
_PATTERN = re.compile(r"^config-\d{8}-\d{6}\.json$")


def backup_dir(config_path):
    return os.path.join(os.path.dirname(os.path.abspath(config_path)), DIRNAME)


def list_backups(folder):
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


def make_backup(config_path, keep=KEEP, now=None):
    """Copy config.json into backups\\ unless it is missing or identical (byte for byte) to the newest backup; then keep
    at most `keep` backups (oldest deleted). Returns the new backup's path, or None (nothing to do, or it failed)."""
    log = applog.get_logger()
    try:
        if not os.path.isfile(config_path):
            return None                                          # first installation: nothing to back up
        data = _read(config_path)
        folder = backup_dir(config_path)
        os.makedirs(folder, exist_ok=True)
        names = list_backups(folder)
        if names and _read(os.path.join(folder, names[-1])) == data:
            return None                                          # same as the newest backup
        t = now or datetime.datetime.now()
        while True:
            name = "config-%s.json" % t.strftime("%Y%m%d-%H%M%S")
            if name not in names and not os.path.exists(os.path.join(folder, name)):
                break
            t += datetime.timedelta(seconds=1)                   # same second as an older backup: the next free one
        dest = os.path.join(folder, name)
        shutil.copyfile(config_path, dest)
        names = list_backups(folder)
        for old in names[:max(0, len(names) - keep)]:
            os.remove(os.path.join(folder, old))
        log.info("config backed up: %s", name)
        return dest
    except Exception as e:                                       # noqa: BLE001  (a backup problem must not stop the start)
        try:
            log.warning("config backup failed: %s", type(e).__name__)
        except Exception:                                        # noqa: BLE001
            pass
        return None
