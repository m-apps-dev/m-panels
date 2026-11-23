# Changelog

Newest first. The About tab in Settings reads this file; the current version (version.py) must have an entry.

## 1.1.1 — 2026-11-23

### Calendar
- Your calendar addresses now live in M Panels itself. Settings > Calendar has a list of calendars with Add, Edit and Remove: each calendar has a name, its secret iCal address, an optional color and an on/off switch. The address field is masked (dots) with a Show button, and the list never shows addresses. Only the calendars that are switched on are shown. Nothing changes until you press Apply, like every other setting.
- "Import from M Calendar config…" reads the calendar list from an M Calendar config file you choose and adds the calendars it does not have yet. The file is only read, once; its location is not remembered and there is no default location any more.
- The old "Source file" setting is gone. A panel that still has it asks once, when the program starts: "Import calendars from <file name>?". Yes imports them (calendars that were not ticked before stay switched off); No imports nothing. Either way the old setting is removed and the question does not come back. If the file cannot be read you are told, and you can import later from Settings > Calendar.
- The addresses are stored in config.json (and so also in the automatic backups). They are never written to mpanels.log, error messages, window titles or tooltips, and "Make current Calendar look the default" and config.example.json never contain them.

### General
- Preparation for publishing the source: MIT license (LICENSE), a new README, a stricter .gitignore (virtual environments, logs, backups, launchers), no personal folder names in code, comments or tests, and a requirements.txt note for Python 3.12 in a venv.
- The program icon now comes from the bundled assets\m_panels.ico; a separate icon file outside the program folder is no longer used.

## 1.1.0 — 2026-11-23

### General
- Automatic config backup: each time the program starts, before anything is read or changed, config.json is copied to backups\config-YYYYMMDD-HHMMSS.json next to it (not when it is identical to the newest backup, and not on the first start). The last 15 backups are kept. If a backup fails, the program still starts and the reason is written to mpanels.log. To go back: quit M Panels (tray > Quit), copy a backup over config.json, start M Panels again.

### Panels
- Multiple monitors: every panel (or stack) has a home, the place where you put it, and config.json keeps only that. If a monitor is missing when the program starts (or is unplugged while it runs), the panels that lived on it are shown on the main monitor, in the same place relative to the missing monitor, and a stack moves as one. Nothing you saved is overwritten: when the monitor is back, the panels return to their homes. If you move a panel yourself while the monitor is missing, the place where you drop it becomes its new home.
- Fixed: starting the program while a monitor was missing (for example a laptop on its own) overwrote the saved place of the panels that were on that monitor, and they did not come back when the monitor did.
- Screen changes are noticed within a few seconds (the monitors and their work areas are checked every 2 seconds). Panels are placed again only after the new layout has stayed the same for about 3 seconds, so a monitor that sleeps and wakes does not move anything. Nothing is moved while you are dragging a panel; it waits for the drop. A panel you snapped under a stack that was shown on the main monitor goes back to the other monitor together with that stack.
- A panel's title bar is always kept on a real monitor, never in a gap between monitors of different sizes or heights and never under the taskbar: when you drop a panel (or when the screens change) at least 80 px of its title bar stays on the monitor it is on, inside that monitor's work area.
- Snapping beside a panel no longer lands off the screen: a spot where the title bar would not be reachable is not offered (no preview, no snap), the same way a taken spot is skipped.
- Snap under another panel: drop an unlocked panel so its top edge is within 24 px of the spot right under another panel (or under the bottom panel of a stack; 2 px below its bottom edge) and they overlap horizontally by at least half of the narrower one, and it snaps: same left edge and width, 2 px gap. Several snapped panels form a stack. You cannot snap into the middle of a stack.
- Snap to the side: drop an unlocked panel so its left or right edge is within the snap distance (24 px by default) of the spot beside another panel (the other panel's edge plus the stack gap) and the two overlap vertically by at least half of the lower one, and it snaps there with its top edge aligned to the other panel's top edge. The width does not change. This is only an alignment: nothing is remembered or pushed, and moving either panel later does not move the other. Dropping the top of a stack beside a panel aligns the whole stack. Next to a panel in the middle of a stack, the top edge of that very panel is used. If both snapping under and snapping beside are possible, the nearer one wins (under wins a tie). Nothing snaps while snapping is off or panels are locked.
- Snapping looks at what you can see: a closed panel counts as just its title bar, an open one as its full height. Snapping never lays a panel on top of another: a spot that is already taken (also by a panel of a stack you are dragging) is skipped, the next candidate is tried, and if none fits the panel stays where you dropped it.
- Snap preview: while you drag a panel (or the top of a stack, which shows the whole stack), a thin blue frame (2 px, empty inside) shows exactly where it would land if you dropped it now, and a blue line marks the edge of the panel it would snap to. It uses the same decision as the drop, so what you see is what happens. It disappears when nothing would snap, when you release, when you press Esc (Esc cancels the whole move, see below), and while snapping is off or panels are locked. The frame ignores the mouse and never takes focus. Settings > General > Snapping has a new "Preview" tick box (on by default); it follows the same rules as the other Snapping settings (Apply, Make default, Revert, Factory).
- Fixed: with an open panel, a closed panel snapped beside it and a third panel dropped beside the closed one, the third panel snapped under the closed panel's title bar (and could cover other panels). A slight overlap now no longer counts as wanting to snap under or beside; it must be at least half.
- Esc while dragging a panel cancels the whole move, like in Windows: the preview goes and everything is put back exactly as it was when you pressed the mouse button: the panel (or, for the top of a stack, the whole stack), the panels that were pushed, and a panel pulled out of the middle of a stack returns to its place in the stack. If you keep the mouse button down, moving the mouse no longer moves the panel and releasing it does nothing; the next press starts a normal drag (the blue frame comes back). Esc without a drag does nothing. This replaces the earlier behaviour where Esc only cancelled the snapping while the move went on.
- Fixed: a panel that had been in a stack, pulled out and dropped back near its old place did not move onto the previewed spot (the preview was right and it was counted as snapped, but the window stayed where you let go until you clicked its title bar). The window now always sits exactly on the previewed rectangle. The drop applies the very candidate the preview showed, and if the mouse release is ever missed the drag ends by itself.
- Stacks: opening, closing or resizing a panel moves the panels below it, frame by frame, so the gap stays the same. Dragging the top panel moves the whole stack. Dragging a middle or bottom panel takes it out of the stack only once you pull it more than 24 px away from its place (the panels below then move up to close the gap and stay in the stack); drop it before that and it goes back, the stack unchanged. All panels of a stack share one width: resizing any of them changes all. Only the top of a stack is kept on screen; the panels below may extend past the screen edge.
- Settings > General > Snapping: "Snap panels" on/off, "Snap distance" (4–64 px, default 24) and "Stack gap" (0–24 px, default 2). Nothing changes until Apply; a value that is out of range or not a whole number is not applied and a warning is shown. Changing the gap re-stacks every stack from its top (the top stays in place). "Make default" saves the three settings too. "Revert to defaults" / "Factory settings" load them into the boxes (the window then has unsaved changes); they take effect when you press Apply, like every other setting here.
- Snapping does not care which monitor the dropped panel came from: it snaps next to the target and takes its left edge and width, so the stack stays on the monitor of its top panel.
- A Calendar panel in a stack uses the stack width; its per-view widths are kept and used again when it leaves the stack (Settings > Calendar says "In a stack: stack width is used").
- Stacks are saved and restored (the gaps are recalculated on start). While panels are locked nothing snaps or leaves a stack, but opening and closing still moves the panels below. `general.snap_distance` (24), `general.stack_gap` (2) and `general.snap_enabled` (true) in config.json; with `snap_enabled` off, no new snapping happens but existing stacks keep working.

### Calendar
- Settings > Calendar is now compact (fits on a 1080p screen): calendar tick boxes share a line, settings sit in two columns, colors in three. To change a color, click its swatch (or focus it and press Enter/Space); the "Pick color…" buttons are gone.
- Calendar settings: "Make current Calendar look the default" saves the applied look (hours, hour heights, fitting, fading, time format, week start, shrinking of empty days, widths per view and your colors) as the default for new Calendar panels and for "Revert to defaults". Source, calendar choice, view, weeks and refresh are not part of it. "Factory settings" uses the built-in look and keeps your saved default.
- Calendar settings: nine calendar colors (text, dim text, accent, event, event text, now highlight, now line, grid lines, notice text) can be set one by one in Settings > Calendar > Colors. A "●" marks a color you set; "Reset" returns one color, "Revert to derived colors" returns all of them to colors derived from the panel color (colors you did not set keep following the panel color). Nothing changes until you press Apply.
- Calendar panel menu: "Open Google Calendar" opens Google Calendar in your default browser (Calendar panels only). If the browser cannot be opened, nothing is shown; the reason is written to mpanels.log.
- Calendar settings: choose 12-hour or 24-hour time (List, Day/Week hour labels and boxes, tooltips) and whether the Week view starts on Monday or Sunday. The List view still starts today.
- Week view: days without events shrink to one fixed narrow width (enough for the widest day header, so it never moves from day to day or week to week), and days with events share the remaining width equally (an all-day event counts as busy). Switch it off with Settings > Calendar > "Week: shrink empty days".
- Each view (List / Day / Week) of a calendar panel now remembers its own width: resize the panel in one view, switch to another, and switch back. The height stays shared. A view you never resized keeps the current width.
- Fixed: with Settings open, switching a calendar panel to Day/Week (or changing the weeks) and pressing Apply no longer puts the old View back; the form follows the panel and does not count it as an unsaved change.
- Calendar settings: Day/Week first and last hour, hour height, empty hour height, "fit boxes to their text" and past-event fading are now in Settings > Calendar.

## 1.0.0 — 2026-11-22

### General
- First stable release. No new features since 0.5.6.
- Verified on real desktop: autostart after Windows restart, panel positions and contents preserved.

### Calendar
- Fixed: Calendar panel can now be resized like other panels.

## 0.5.6 — 2026-11-21

### Settings
- Nothing in the Settings window changes until you press Apply. This now includes "Start with Windows" and "Lock panels" (before, they took effect the moment you ticked them).
- Closing the window with X, or choosing another panel, while something is not applied asks: "Unsaved changes — Apply / Discard / Cancel". Cancel keeps you where you are.
- "Revert to defaults" and "Factory settings" now ask "This will overwrite current settings. Continue?" first.

## 0.5.5 — 2026-11-21

### Settings
- Fixed: "Hide desktop icons" in Settings > General took effect the moment you ticked the box. It now waits for Apply. Closing the window with X without Apply changes nothing.

## 0.5.4 — 2026-11-21

### General
- Installed for real: the Startup and Desktop shortcuts "M Panels" now start the program with the new Python environment (a venv). Fixed a SyntaxWarning in the calendar source file.

## 0.5.3 — 2026-11-21

### General
- M Panels now runs from its own Python environment, a venv (Python 3.12.8), instead of a shared Python installation. requirements.txt lists the exact package versions.

## 0.5.2 — 2026-11-21

### Panels
- Fixed: Quit in the tray menu did not close the program. It now closes all windows, the tray icon, background work and the single-instance lock, and ends the process (a 5-second safety exit covers anything that hangs).

### Calendar
- The refresh status (Updated 14:32 / Loading… / error) is shown in a tooltip when you hover the panel title; it is no longer drawn inside the panel.

### General
- New command line option --quit asks the running copy to quit.

## 0.5.1 — 2026-11-21

### Panels
- The version number no longer appears inside any panel.

### Calendar
- Removed the small status line below the calendar; the content area is a little taller.

### General
- New About tab in Settings (rightmost): app name, icon and version, a short Help, and this What's new list.
- The version line moved from the General tab to About; the window title still shows the version.

## 0.5.0 — 2026-11-21

### Panels
- Third panel type: Calendar (New panel: Shortcuts / Notes / Calendar).

### Calendar
- Day, Week and List views (1–4 weeks) read from the calendars of an existing calendar list (the iCal addresses of your Google or Outlook.com calendars).
- Settings has a Calendar tab: source file, calendars to show, view, weeks, refresh interval.
- Reading runs in the background; errors show a short message inside the panel and never affect other panels.
- Calendar addresses are never copied, logged or shown; only the path of the source file is stored.

### General
- Refresh calendar entry in the panel menu.

## 0.4.0 — 2026-11-21

### Panels
- Panels, dialogs and notices are hidden from the taskbar and Alt+Tab; only Settings shows a taskbar button.

### General
- All interface text is English (kept in strings.py).
- Starts without a console window (M-Panels.bat uses pythonw).
- Single instance: starting it again shows the panels and Settings of the running copy.
- Errors are written to mpanels.log.
- App icon file support; kur.py no longer touches the real desktop unless asked.

## 0.3.0 — 2026-11-21

### Panels
- Right-click menu is grouped; title text and content text styles are set separately (font, size, color, bold, italic).

### Notes
- Formatted notes (bold, italic, underline, color, font, size), saved as JSON.

### General
- Settings window has tabs; colors and metrics moved to theme.py; the version is shown in the window.

## 0.2.0 — 2026-11-21

### Panels
- Icon size is a number box (16–128 px).

### Notes
- Note panels.

### General
- Lock panels (no moving or resizing).
- Hide desktop icons (restored on quit).

## 0.1.0 — 2026-11-21

### Panels
- Shortcut panels on the desktop with drag and drop, reordering and returning items to the desktop.

### General
- Tray icon (Show / Hide, New panel, Settings, Quit).
- TEST mode that never touches the real desktop.
