"""Calendar data of one panel: background refresh with a result lock. No tkinter.

All network and file access happens on a worker thread; the UI thread only reads the finished state.
`notify` is called from the worker when new state is ready (the app puts a message on its queue).
`fetch` / `reader` can be replaced in tests (no network).
"""
import logging
import threading
from datetime import datetime

import strings as ui
from calendar_panel import AVAILABLE, core

log = logging.getLogger("mpanels")


class CalendarModel:
    def __init__(self, notify=None, fetch=None):
        self.notify = notify
        self._fetch = fetch
        self._lock = threading.Lock()
        self.data = {}              # url -> icalendar.Calendar (the last good download)
        self.metas = []             # calendars shown: [{"name","url","color"}]
        self.error = None
        self.last_update = None
        self.loading = False

    # ---- state seen by the UI thread
    def snapshot(self):
        with self._lock:
            return {"error": self.error, "last_update": self.last_update, "loading": self.loading,
                    "metas": list(self.metas), "data": dict(self.data)}

    def events_between(self, d0, d1):
        snap = self.snapshot()
        out = []
        for meta in snap["metas"]:
            cal = snap["data"].get(meta["url"])
            if cal is not None:
                try:
                    out += core.expand(cal, d0, d1, meta)
                except Exception as e:            # a broken calendar must not break the panel
                    log.warning("calendar %r could not be expanded: %s", meta["name"], e.__class__.__name__)
        out.sort(key=lambda x: (x["day"], not x["all_day"], x["seg_start"] or datetime.min, x["title"]))
        return out

    # ---- refresh
    def refresh(self, calendars, sync=False):
        """Start a refresh (no-op while one is running) of the enabled ones among `calendars`
        ([{"name","url","color","enabled"}]). sync=True runs it inline (tests)."""
        if not AVAILABLE:
            with self._lock:
                self.error = ui.CAL_ERR_LIBS
            self._notify()
            return False
        with self._lock:
            if self.loading:
                return False
            self.loading = True
        if sync:
            self._work([dict(c) for c in calendars or []])
        else:
            threading.Thread(target=self._work, args=([dict(c) for c in calendars or []],), daemon=True,
                             name="calendar-refresh").start()
        return True

    def _work(self, calendars):
        results, errors, error, metas = {}, [], None, []
        try:
            fetch = self._fetch or core.download_calendar
            metas = [c for c in calendars if c.get("enabled", True)]
            if not metas:
                error = ui.CAL_ERR_NONE
            for m in metas:
                try:
                    results[m["url"]] = fetch(m["url"])
                except Exception as e:
                    # name + exception class only: the address is a secret
                    errors.append(f"{m.get('name') or ui.CAL_ERR_UNNAMED} ({e.__class__.__name__})")
            if errors:
                error = ui.CAL_ERR_FETCH.format(names=", ".join(errors))
        except Exception as e:
            log.error("calendar refresh failed: %s", e.__class__.__name__)
            error = ui.CAL_ERR_FETCH.format(names=e.__class__.__name__)
        if error:
            log.warning("calendar: %s", error)
        with self._lock:
            self.data.update(results)                                    # keep old data for failures
            self.metas = [{"name": m.get("name") or ui.CAL_ERR_UNNAMED, "url": m["url"], "color": m.get("color")} for m in metas]
            wanted_urls = {m["url"] for m in metas}
            self.data = {u: v for u, v in self.data.items() if u in wanted_urls}
            if results:
                self.last_update = datetime.now()
            self.error = error
            self.loading = False
        self._notify()

    def stop(self):
        """Quit: no more notifications to the UI (a running worker is a daemon thread and just ends)."""
        self.notify = None

    def _notify(self):
        if self.notify:
            try:
                self.notify()
            except Exception:
                pass
