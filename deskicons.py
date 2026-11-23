"""Hide/show the desktop icons (Explorer 'Show desktop icons') — the backend is injectable.

Backend: get_hidden() -> bool, set_hidden(bool) -> bool (success).
The real backend lives in winutil; tests pass a fake one (the real desktop is never touched).
State is kept in the "general" section of the config:
  hide_desktop_icons : the user setting (on/off)
  hide_icons_restore : the state before we changed it (True = icons were hidden); None = nothing recorded
"""


class IconHider:
    def __init__(self, general, backend, save=lambda: None):
        self.g, self.backend, self.save = general, backend, save

    @property
    def enabled(self):
        return self.backend is not None

    def startup(self):
        """At startup: hide the icons if the setting is on. A 'previous state' record left by a crash is kept."""
        if self.enabled and self.g.get("hide_desktop_icons"):
            return self._hide()
        return True

    def set_enabled(self, on):
        """The settings checkbox. True: success. In TEST mode (backend None) it does nothing and returns False."""
        if not self.enabled:
            return False
        if on:
            ok = self._hide()
            if ok:
                self.g["hide_desktop_icons"] = True
            self.save()
            return ok
        ok = self._restore()
        self.g["hide_desktop_icons"] = False
        self.save()
        return ok

    def on_quit(self):
        """On quit, return to the previous state; the setting stays on (icons are hidden again at next start)."""
        if self.enabled and self.g.get("hide_desktop_icons"):
            return self._restore()
        return True

    def restore_now(self):
        """--restore-desktop-icons: return to the previous state and turn the setting off."""
        if not self.enabled:
            return False
        ok = self._restore()
        self.g["hide_desktop_icons"] = False
        self.save()
        return ok

    # -- internals
    def _hide(self):
        if self.g.get("hide_icons_restore") is None:
            self.g["hide_icons_restore"] = bool(self.backend.get_hidden())
        self.save()
        if self.backend.get_hidden():
            return True
        return bool(self.backend.set_hidden(True))

    def _restore(self):
        orig = self.g.get("hide_icons_restore")
        if orig is None:
            return True                      # nothing was changed by us
        ok = True
        if bool(self.backend.get_hidden()) != bool(orig):
            ok = bool(self.backend.set_hidden(bool(orig)))
        if ok:
            self.g["hide_icons_restore"] = None
        self.save()
        return ok
