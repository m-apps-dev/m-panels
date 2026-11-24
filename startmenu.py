"""The bar's Start button (v1.2 step 5): the "bar.start" part of config.json and the one thing the button does: open (or close)
the real Windows Start menu by pressing the Win key once.

The press is ONE SendInput call holding both events (Win down, Win up), so the key can never be left down between two calls.
If Windows takes fewer than two events, or the call raises, a Win-up is sent again in a `finally` (the Win key is ALWAYS
released). The click is a toggle by Windows' own rule: the Win key opens the menu when it is closed and closes it when it is
open; the bar does not read the menu's state at click time (the experiment of 24.11 showed that is not needed).

No tkinter here. The Windows call (SendInput) is handed in, so tests use a made-up one; TEST mode uses FakeStartActions, which
only records."""
import applog
import search

LOG = applog.get_logger()

DEFAULTS = {"enabled": True}
EXT, UP = search.KEYEVENTF_EXTENDEDKEY, search.KEYEVENTF_KEYUP
WIN_DOWN = (search.VK_LWIN, 0, EXT)
WIN_UP = (search.VK_LWIN, 0, EXT | UP)


# ------------------------------------------------------------------ config
def defaults():
    return dict(DEFAULTS)


def sanitize(src):
    """A complete, valid 'start' dict. A wrong type falls back to the default; unknown keys are kept."""
    s = src if isinstance(src, dict) else {}
    out = {k: v for k, v in s.items() if k not in DEFAULTS}
    out["enabled"] = s["enabled"] if isinstance(s.get("enabled"), bool) else DEFAULTS["enabled"]
    return out


def differences(start_cfg):
    """Only what differs from the defaults (this is what config.json holds)."""
    s = sanitize(start_cfg)
    return {k: v for k, v in s.items() if k not in DEFAULTS or v != DEFAULTS[k]}


# ------------------------------------------------------------------ the Windows call
class StartActions:
    """Presses the Win key (down + up in one SendInput call). `send` is handed in by tests."""

    def __init__(self, send=None):
        self._send = send or search._real_send

    def open_start(self):
        """Press and release the Win key. The Win key goes up again whatever happens (finally). Returns True when Windows
        took both events."""
        taken = 0
        try:
            taken = int(self._send([WIN_DOWN, WIN_UP]) or 0)
        finally:
            if taken != 2:                               # fewer than 2 taken, or the call raised: make sure the key is up
                try:
                    self._send([WIN_UP])
                except Exception:                        # noqa: BLE001
                    LOG.exception("start: the Win key could not be released")
        return taken == 2


class FakeStartActions:
    """TEST mode (and tests): only records; no key is sent."""

    def __init__(self):
        self.calls = []
        self.fail = None                                 # an exception to raise from open_start()

    def open_start(self):
        self.calls.append(("win",))
        if self.fail is not None:
            raise self.fail
        return True


# ------------------------------------------------------------------ the controller
class Start:
    """What a click on the Start button does. `close_search()` closes the search window without giving the foreground back
    (the Start menu is about to take it). A click that comes within the system's double-click time of the previous Start click
    is ignored (the second click of a double click would close the menu the first one opened)."""

    def __init__(self, actions, clock, close_search, double_click=search.double_click_ms):
        self.actions, self.clock, self._close_search, self._double = actions, clock, close_search, double_click
        self.clicked_at = None

    def click(self):
        try:
            now = self.clock()
            if self.clicked_at is not None and (now - self.clicked_at) * 1000.0 < self._double():
                LOG.info("start: click ignored (inside the double-click time of the previous click)")
                return False
            self.clicked_at = now
            try:
                self._close_search()
            except Exception:                            # noqa: BLE001
                LOG.exception("start: closing the search window failed")
            self.actions.open_start()
            LOG.info("start: Win key sent")
            return True
        except Exception:                                # noqa: BLE001  (never break a Tk callback)
            LOG.exception("start: click failed")
            return False
