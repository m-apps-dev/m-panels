"""All user-visible interface text, in one place (English).

Code never hard-codes UI text: it reads it from here (a test enforces this, see tests/test_v4.py).
User content (panel names, note text, file names) is never translated.
Placeholders use str.format fields, e.g. ``MOVE_FAILED.format(what="", error=...)``.
"""

APP_NAME = "M Panels"
TEST_TAG = "(TEST)"
DEFAULT_PANEL_NAME = "Sample"       # the panel made at the very first start (not again later)
RECYCLE_BIN_ITEM = "Recycle Bin"

# --------------------------------------------------------------- preset color names (keys live in theme.PRESETS)
COLOR_NAMES = {"blue": "Blue", "green": "Green", "orange": "Orange", "purple": "Purple",
               "cyan": "Cyan", "red": "Red", "pink": "Pink", "yellow": "Yellow"}
COLOR_CUSTOM = "Custom"

# --------------------------------------------------------------- common buttons / labels
BTN_OK = "OK"
BTN_CANCEL = "Cancel"
BTN_CREATE = "Create"
BTN_COLOR = "Color…"
BTN_PICK_COLOR = "Pick color…"
BTN_APPLY = "Apply"
BTN_MAKE_DEFAULT = "Make current look the default"
BTN_RESET_DEFAULTS = "Revert to defaults"
BTN_FACTORY = "Factory settings"
BTN_DISCARD = "Discard"
UNSAVED_TITLE = "Unsaved changes"
UNSAVED_MSG = "Unsaved changes — Apply / Discard / Cancel"
CONFIRM_OVERWRITE = "This will overwrite current settings. Continue?"
CHK_BOLD = "Bold"
CHK_ITALIC = "Italic"
LBL_SIZE = "Size"
SAMPLE_TEXT = "Sample text — AaBbCcÇçĞğİıÖöŞşÜü 0123"
FONT_DIALOG_TITLE = "Choose font"

# --------------------------------------------------------------- item (icon) context menu
ITEM_OPEN = "Open"
ITEM_OPEN_LOCATION = "Open file location"
ITEM_RENAME = "Rename…"
ITEM_RETURN = "Return to desktop"
ITEM_REMOVE_SPECIAL = "Remove from panel"
ITEM_MOVE_LEFT = "Move left"
ITEM_MOVE_RIGHT = "Move right"

# --------------------------------------------------------------- panel context menu
MENU_NEW_PANEL = "New panel…"
MENU_RENAME = "Rename…"
MENU_COLOR = "Color"
MENU_CUSTOM_COLOR = "Custom color…"
MENU_OPACITY = "Opacity"
MENU_TITLE_TEXT = "Title text…"
MENU_CONTENT_TEXT = "Content text…"
MENU_SORT_AZ = "Sort A–Z"
MENU_RECYCLE_ADD = "Add Recycle Bin"
MENU_RECYCLE_REMOVE = "Remove Recycle Bin"
MENU_SETTINGS = "Settings…"
MENU_REMOVE_PANEL = "Remove panel…"
MENU_COLLAPSE = "Collapse"
MENU_EXPAND = "Expand"

# --------------------------------------------------------------- note formatting menu (selected text)
FMT_BOLD = "Bold"
FMT_ITALIC = "Italic"
FMT_UNDERLINE = "Underline"
FMT_COLOR = "Color…"
FMT_FONT = "Font…"
FMT_SIZE = "Size"
FMT_SIZE_OTHER = "Other…"
FMT_CLEAR = "Clear formatting"

# --------------------------------------------------------------- dialogs
DLG_PANEL_COLOR = "Panel color"
DLG_TEXT_COLOR = "Text color"
DLG_SIZE_TITLE = "Size"
DLG_SIZE_PROMPT = "Font size ({lo}–{hi}):"
DLG_TITLE_TEXT = "Title text"
DLG_CONTENT_TEXT = "Content text"
DLG_STYLE_TITLE = "{what} — {panel}"
DLG_RENAME_ITEM_TITLE = "Rename"
DLG_NEW_NAME = "New name:"
DLG_PANEL_NAME_TITLE = "Panel name"
DLG_REMOVE_TITLE = "Remove panel"
REMOVE_PANEL_MSG = ("Remove the panel '{name}'?\n\n"
                    "Items inside are moved back to the desktop; nothing is deleted.")
REMOVE_NOTE_MSG = ("Remove the note '{name}'?\n\n"
                   "The note file is not deleted; it is moved to {trash} in the data folder.")
NEW_TITLE = "New panel"
NEW_TYPE = "Type"
NEW_KIND_SHORTCUT = "Shortcut panel (file/shortcut icons)"
NEW_KIND_NOTE = "Note panel (formatted text, auto-save)"
NEW_NAME = "Name"

# --------------------------------------------------------------- notifications / warnings
ITEM_BROKEN = "This shortcut's target could not be found."
ITEM_OPEN_FAILED = "Could not open: {error}"
NAME_TAKEN = "A panel or note with this name already exists."
NOTE_IMPORTED = "The old plain-text note was imported; the .txt file was moved to {trash}."

# --------------------------------------------------------------- tray
TRAY_SHOW_HIDE = "Show / Hide"
TRAY_NEW = "New panel"
TRAY_SETTINGS = "Settings…"
TRAY_QUIT = "Quit"

# --------------------------------------------------------------- settings window
SET_TITLE = "{app} v{version} — Settings"
TAB_PANEL = "Panel"
TAB_TITLE = "Title"
TAB_CONTENT = "Content"
TAB_GENERAL = "General"
TAB_ABOUT = "About"
TAB_BAR = "Bar"
LBL_PANEL = "Panel"
LBL_NAME = "Name"
LBL_COLOR = "Color"
LBL_OPACITY = "Opacity"
LBL_ICON_SIZE = "Icon size (px, {lo}–{hi})"
CHK_START_COLLAPSED = "Start collapsed"
CHK_HOVER_OPEN = "Open on hover"
CHK_AUTOSTART = "Start with Windows"
CHK_LOCK = "Lock panels (moving and resizing disabled)"
CHK_HIDE_ICONS = "Hide desktop icons"
LBL_SNAPPING = "Snapping"
CHK_SNAP = "Snap panels"
CHK_SNAP_PREVIEW = "Preview"
LBL_SNAP_DISTANCE = "Snap distance (px)"
NAME_SNAP_DISTANCE = "Snap distance"
NAME_STACK_GAP = "Stack gap"
LBL_STACK_GAP = "Stack gap (px)"
MSG_SNAP_RANGE = " ({what} must be a whole number from {lo} to {hi}; kept {n}.)"
TEST_MODE_NOTE = "(TEST mode: startup and desktop-icon settings are disabled)"
VERSION_LINE = "{app} v{version}"
MSG_ICONS_FAILED = "Could not change the desktop icons."
MSG_ICONS_HIDDEN = "Desktop icons hidden (they return to normal when M Panels quits)."
MSG_ICONS_RESTORED = "Desktop icons restored."
MSG_APPLIED = "Applied."
MSG_ICON_RANGE = " (Icon size must be a whole number from {lo} to {hi}; set to {n}.)"
MSG_TEXT_RANGE = " ({what} text size must be from {lo} to {hi}; set to {n}.)"
MSG_DEFAULT_SAVED = "This look is now the default for new panels."
MSG_FACTORY_LOADED = "Factory settings loaded."
MSG_DEFAULTS_LOADED = "Defaults loaded."
MSG_SNAP_PENDING = " Snapping settings loaded into the boxes: press Apply to use them."

# --------------------------------------------------------------- bar (v1.2)
CHK_BAR_SHOW = "Show bar (reserves a strip at the top of the main monitor)"
CHK_BAR_INFO = "Show date and time"
CHK_BAR_DATE = "Show date"
LBL_BAR_TIME_FORMAT = "Time format"
BAR_TIME_24 = "24-hour"
BAR_TIME_12 = "12-hour"
BAR_INFO = "{weekday} {day} {month} · {time}"
BAR_MENU_SETTINGS = "Settings…"
BAR_MENU_CLOSE = "Close window"
BAR_TEST_NOTE = "(TEST mode: the bar is drawn, but no screen space is reserved)"
MSG_BAR_FAILED = " Could not reserve the bar's space: the bar was not shown."
CHK_BAR_TASKS = "Show open windows"
CHK_BAR_TITLES = "Show window titles"
LBL_BAR_COLORS = "Colors"
BAR_COLOR_NAMES = {"background": "Bar background", "button": "Button", "border": "Button border", "text": "Text",
                   "active": "Active window"}
BTN_BAR_COLOR_RESET = "Reset"
BTN_BAR_COLORS_RESET = "Reset colors"
BAR_SAMPLE_NORMAL = "Window"
BAR_SAMPLE_ACTIVE = "Active"
BAR_SAMPLE_MINIMIZED = "Minimized"
BAR_OVERFLOW = "+{n}"
BAR_ELLIPSIS = "…"
BAR_TEST_WINDOWS = ("Notes — TEST window", "Browser — a page with a rather long title that does not fit on one button",
                    "Mail — Inbox", "Editor — project", "Terminal", "Calculator", "Files — Documents", "Music")
MSG_BAR_PENDING = " Bar settings loaded into the boxes: press Apply to use them."

# --------------------------------------------------------------- Start button (v1.2 step 5)
CHK_START_SHOW = "Show Start button"

# --------------------------------------------------------------- search (v1.2 step 4)
LBL_SEARCH = "Search"
CHK_SEARCH_SHOW = "Show search button"
LBL_SEARCH_HOTKEY = "Shortcut key"
SEARCH_HOTKEY_LABELS = {"off": "Off", "win+alt+space": "Win+Alt+Space", "ctrl+shift+space": "Ctrl+Shift+Space"}
CHK_SEARCH_STORE = "Include Store apps"
CHK_SEARCH_WINROW = "Show 'Search Windows' row"
SEARCH_WINDOWS_ROW = "Search Windows for '{text}'"
SEARCH_LAUNCH_FAILED = "Could not start {name}."
MSG_SEARCH_FAILED = " Could not register the shortcut key (another program may be using it): the bar settings were not applied."

# --------------------------------------------------------------- command line
ARG_DESKTOP = "TEST mode: use this folder as the desktop (the real desktop is not touched)"
ARG_PUBLIC = "TEST mode: folder to use as the public desktop"
ARG_DATA = ("location of config.json (default: program folder; in TEST mode: next to the test folder)")
ARG_RESTORE_ICONS = ("restore the desktop icons to their state before M Panels and turn the setting off "
                     "(run this before uninstalling)")
ARG_QUIT = "ask the running copy (same mode) to quit"
ARG_AUTOSTART = "started from Windows startup (kur.py adds the shortcut)"
ERR_TEST_REAL_DESKTOP = "TEST mode cannot run on the real desktop (or inside/above it): {path}"
ERR_TEST_NO_ICONS = "Desktop icons are not touched in TEST mode."
MSG_RESTORE_OK = "Desktop icons restored to their previous state."
MSG_RESTORE_FAIL = "Could not restore the desktop icons."

# --------------------------------------------------------------- file operations (messages returned to the UI)
NAME_EMPTY = "The name cannot be empty."
NAME_BAD_CHARS = 'The name cannot contain these characters: < > : " / \\ | ? *'
NAME_ENDS_DOT = "The name cannot end with a dot."
NAME_RESERVED = "This name is reserved by Windows."
NAME_RESERVED_APP = "'{name}' is a reserved name."
NAME_TOO_LONG = "The name is too long."
MOVE_LOCKED = "{what}Could not move: the file is open or locked, or access is denied. Not forced."
MOVE_FAILED = "{what}Could not move: {error}"
SHORTCUT_FAILED = "Could not create the shortcut: {error}"
PANEL_EXISTS = "A panel with this name already exists."
PANEL_RENAME_FAILED = "Could not rename the panel: "
PANEL_FOLDER_MISSING = "Panel folder not found."
PANEL_REMOVE_PARTIAL = ("{moved} item(s) returned to the desktop; {failed} item(s) could not be moved, so the "
                        "panel was not removed. {problems}")
PANEL_REMOVED = "{moved} item(s) returned to the desktop."
NOTE_EXISTS = "A note with this name already exists."
NOTE_RENAME_FAILED = "Could not rename the note: "
NOTE_FILE_MISSING = "The note file did not exist."
NOTE_SAVE_FAILED = "The note could not be saved: {error}"
NOTE_UNREADABLE = "The note file could not be read ({error}); the file was {where}."
NOTE_WHERE_TRASH = "moved to {trash}"
NOTE_WHERE_KEPT = "left in place"
NOTE_LEGACY_UNREADABLE = "The old note could not be read: {error}"
NOTE_LEGACY_KEPT = " The old .txt file was left in place."
NOTE_LEGACY_TRASH_FAIL = "The old .txt file could not be moved to {trash}: {error}"
NOTE_JSON_UNREADABLE = "note file could not be read: {error}"
NOTE_JSON_INVALID = "note file format is invalid"
ITEM_NOT_FOUND = "Item not found."
DROP_PANEL_FOLDER = "Panel folders cannot be added to a panel."
DROP_ALREADY = "The item is already in this panel."
COPY_FAILED = "Could not copy: {error}"
PUBLIC_COPIED = ("Public desktop items cannot be moved; a shortcut copy was created and the original "
                 "stayed in place.")
DIFFERENT_DRIVE = "Different drive: not moved, a shortcut was created."
ITEM_EXISTS = "An item with this name already exists."
RENAME_FAILED = "Could not rename: "

# --------------------------------------------------------------- kur.py (installer)
KUR_ARG_TARGET = "write the shortcuts to this folder instead of the real locations (trial run)"
KUR_ARG_SKIP_PIP = "skip package installation"
KUR_ARG_SHORTCUTS = ("create the Startup and Desktop shortcuts in the REAL locations "
                     "(run only after approval, at the real-desktop stage)")
KUR_ARG_WRITE_BAT = "(re)write M-Panels.bat and M-Panels-Test.bat using the detected pythonw, then exit"
KUR_PIP = "1) Installing packages..."
KUR_PIP_SKIPPED = "1) Package installation skipped."
KUR_SHORTCUTS = "2) Creating shortcuts:"
KUR_NO_SHORTCUTS = ("2) Shortcuts not created. Pass --shortcuts to create them in the real Startup folder "
                    "and on the Desktop (after approval).")
KUR_SHORTCUT_DESC = "{name} — desktop shortcut panels"
KUR_STARTUP_SUFFIX = " (startup)"
KUR_BAT_WRITTEN = "Wrote {path}"
KUR_DONE = "\nDone. Start the program with the '{name}' shortcut or M-Panels.bat."
KUR_FIRST_RUN = "On first run the hidden Desktop\\Paneller folder and a '{panel}' panel are created."
KUR_NO_PYTHONW = "pythonw.exe was not found next to {python}"

# --------------------------------------------------------------- misc
ERR_ALREADY_RUNNING = "{app} is already running; the running copy was brought forward."

# --------------------------------------------------------------- calendar panel
TAB_CALENDAR = "Calendar"
NEW_KIND_CALENDAR = "Calendar panel (Google / MSN events)"
MENU_CAL_REFRESH = "Refresh calendar"
MENU_CAL_OPEN_GOOGLE = "Open Google Calendar"
GOOGLE_CALENDAR_URL = "https://calendar.google.com/"      # fixed address, the only place it is written
REMOVE_CALENDAR_MSG = ("Remove the calendar panel '{name}'?\n\n"
                       "Nothing is deleted; your calendars and their source file are not touched.")
CAL_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"]
CAL_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
CAL_DAYS_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
CAL_TODAY = "Today"
CAL_TOMORROW = "Tomorrow"
CAL_ALL_DAY = "All day"
CAL_AM = "AM"
CAL_PM = "PM"
CAL_AM_SHORT = "a"
CAL_PM_SHORT = "p"
CAL_TIME_24 = "24-hour"
CAL_TIME_12 = "12-hour"
CAL_UNTITLED = "(untitled)"
CAL_NO_EVENTS = "No events in this range."
CAL_SHOW = "Show:"
CAL_WEEKS = "{n} wk"
CAL_VIEW_LIST = "List"
CAL_VIEW_DAY = "Day"
CAL_VIEW_WEEK = "Week"
CAL_RANGE = "{d0} {m0} – {d1} {m1} {year}"
CAL_ERR_LIBS = "Calendar support is not installed (pip install icalendar recurring-ical-events)."
CAL_ERR_NO_SOURCE = "The calendar file was not found."
CAL_ERR_SOURCE_BAD = "The calendar file could not be read ({error})."
CAL_UPDATED = "Updated {time}"
CAL_LOADING = "Loading…"
CAL_ERR_NONE = "No calendars to show. Add one in Settings › Calendar."
CAL_ERR_FETCH = "Could not fetch: {names}"
CAL_ERR_UNNAMED = "calendar"
BTN_BROWSE = "Browse…"
LBL_CAL_CALENDARS = "Calendars"
LBL_CAL_VIEW = "View"
LBL_CAL_WEEKS = "Weeks in list (1–4)"
LBL_CAL_REFRESH = "Refresh (min, 1–120)"
LBL_CAL_START_HOUR = "First hour (0–23)"
LBL_CAL_END_HOUR = "Last hour (1–24)"
LBL_CAL_HOUR_H = "Hour height (px, 12–200)"
LBL_CAL_EMPTY_H = "Empty hour height (px, 6–200)"
CHK_CAL_FIT = "Fit boxes to text"
CHK_CAL_SHRINK = "Week: shrink empty days"
LBL_CAL_TIME_FORMAT = "Time format"
LBL_CAL_WEEK_START = "Week starts on"
LBL_CAL_COLORS = "Colors"
LBL_CAL_DAYWEEK = "Day / Week"
TIP_CAL_COLOR_CHANGE = "Click to change"
CAL_LOOK_HINT = "Revert = your default · Factory = built-in (yours is kept)"
CAL_COLOR_NAMES = {"text": "Text", "dim": "Dim text (times)", "accent": "Accent (today)", "event": "Event",
                   "event_text": "Event text", "now": "Now highlight", "now_line": "Now line",
                   "grid": "Grid lines", "warn": "Notice text"}
CAL_COLOR_MARK = "●"
BTN_CAL_COLOR_RESET = "Reset"
BTN_CAL_COLORS_REVERT = "Revert to derived colors"
CAL_STACK_WIDTH_NOTE = "In a stack: stack width is used"
CAL_COLORS_NOTE = "● = set by you; others follow the panel color"
CONFIRM_CAL_COLORS_REVERT = ("Remove all your custom calendar colors and use colors derived from the panel color?"
                             " This takes effect when you press Apply.")
BTN_CAL_MAKE_DEFAULT = "Make current Calendar look the default"
CAL_LOOK_HELP = ("Saves hours, colors, time format and widths for new Calendar panels and for \"Revert to defaults\" "
                 "(not source, calendars, view, weeks or refresh). \"Factory settings\" uses the built-in look "
                 "and keeps your saved default.")
CONFIRM_CAL_LOOK_DEFAULT = "Save this calendar look as your default for new Calendar panels and \"Revert to defaults\"?"
MSG_CAL_LOOK_APPLY_FIRST = "There are unapplied changes. Press Apply first; the default is saved from the applied look."
MSG_CAL_LOOK_SAVED = "This calendar look is now your default."
LBL_CAL_FADE = "Fade past (%, 0–90; 0 = off)"
MSG_CAL_RANGE = " (Calendar: {what} must be a whole number from {lo} to {hi}; set to {n}.)"
BTN_CAL_ADD = "Add…"
BTN_CAL_EDIT = "Edit…"
BTN_CAL_REMOVE = "Remove"
BTN_CAL_IMPORT = "Import from M Calendar config…"
BTN_CAL_SHOW = "Show"
BTN_CAL_HIDE = "Hide"
CAL_COL_ON = "On"
CAL_COL_NAME = "Name"
CAL_COL_COLOR = "Color"
CAL_COLOR_DEFAULT = "default"
CAL_LIST_NOTE = "Addresses are hidden here; they are stored only in M Panels' config."
CAL_ADDRESS_MASK = "•"
CAL_ADDRESS_SCHEMES = ("https://", "http://", "webcal://")
LOG_CAL_MIGRATED = "calendar panel %r: old source setting removed, %d calendar(s) imported"
DLG_CAL_ADD = "Add calendar"
DLG_CAL_EDIT = "Edit calendar"
DLG_CAL_IMPORT = "Choose the M Calendar config file to import from"
LBL_CAL_NAME = "Name"
LBL_CAL_ADDRESS = "iCal address"
LBL_CAL_COLOR1 = "Color"
CHK_CAL_ENABLED = "Show this calendar"
CAL_NEW_NAME = "Calendar"
ERR_CAL_ADDRESS = "Enter an address that starts with https://, http:// or webcal://."
MSG_CAL_IMPORTED = "Imported {n} calendar(s). Press Apply to keep them."
MSG_CAL_IMPORT_NONE = "Nothing new to import."
MSG_CAL_IMPORT_FAILED = "Nothing was imported: {error}"
ASK_CAL_MIGRATE = ("Import calendars from {file} into the panel \"{panel}\"?\n\n"
                   "The addresses are read once and kept in M Panels' own settings; the file is not changed "
                   "and its location is not remembered.")
MSG_CAL_MIGRATE_FAILED = ("The calendars of the panel \"{panel}\" could not be imported from {file}: {error}\n"
                          "You can import them later in Settings › Calendar.")
FILETYPE_JSON = "JSON files"
FILETYPE_ALL = "All files"
CAL_LEGACY_NAME = "Google"          # name given to the old single-address setting

# --------------------------------------------------------------- About tab (v0.5.1)
ABOUT_HELP = "Help"
ABOUT_WHATS_NEW = "What's new"
ABOUT_VER_PREFIX = "v"
ABOUT_DATE_SEP = " — "
ABOUT_BULLET = "• "
ABOUT_NO_CHANGELOG = "The release notes (CHANGELOG.md) could not be read."
ABOUT_LICENSE_LINE = "MIT License · Copyright (c) 2026 M-Apps"
ABOUT_REPO_LINE = "github.com/m-apps-dev/m-panels"           # plain text, not a link

# Help: (heading, (bullet, ...)). Shown on the About tab; keep each bullet under 140 characters.
# Names of buttons, menu items, settings and tabs must match the strings above exactly (tests/test_v120_help.py).
HELP_SECTIONS = (
    ("What M Panels does", (
        "Puts small, movable panels on your desktop: shortcuts, notes and a calendar.",
        "An optional bar along the top of the screen adds your open windows, search, a Start button and the date and time.",
        "Use it your way: panels only, the bar only, or both.",
        "Panels only: leave the bar off (the default). Bar only: turn on Settings › Bar › Show bar and delete the Sample panel.",
        "Everything is saved automatically. Your files and notes are never deleted by the program; only the oldest settings backups are.",
        "Right-click a panel header (or use the ⋯ button) for its menu.",
    )),
    ("Shortcut panels", (
        "Drag files or folders from the desktop onto a panel; they move into the panel's folder.",
        "Double-click an item to open it. Right-click for Open, Open file location, Rename and Return to desktop.",
        "Drag items to reorder them, or drop them on another panel to move them.",
        "Settings: color, opacity, icon size, title and content text styles, start collapsed, open on hover.",
    )),
    ("Note panels", (
        "Type directly in the panel; it saves as you type.",
        "Select text and right-click for Bold, Italic, Underline, Color, Font, Size and Clear formatting.",
        "A removed note is moved to a recycle folder, never deleted.",
    )),
    ("Calendar panels", (
        "Shows your calendars as a List (1–4 weeks), a Day or a Week view; switch views in the panel's top row.",
        "Hover an event for its details; use the mouse wheel to scroll.",
        "Settings has a Calendar tab: add your calendars (secret iCal addresses), choose which to show, the view and the refresh interval.",
        "Settings › Calendar: choose 12-hour or 24-hour time, whether the week starts on Monday or Sunday, the hours shown, and colors.",
        "Panel menu: Open Google Calendar opens it in your browser.",
        "Settings › Calendar › Import from M Calendar config… reads an older calendar list once.",
        "Make current Calendar look the default saves your hours, colors and time format for new Calendar panels.",
        "If a calendar cannot be read, a short message appears inside the panel; other panels are not affected.",
    )),
    ("Snapping and stacks", (
        "Drop a panel close to another panel's edge and it snaps there: under it (forming a stack) or beside it.",
        "A blue frame shows where it will land. Press Esc while dragging to cancel the whole move.",
        "In a stack, opening, closing or resizing a panel moves the panels below it. Dragging the top panel moves the whole stack.",
        "Pull a lower panel a short way out of a stack to take it out; drop it sooner and it goes back.",
        "Settings › General › Snapping: turn snapping and the preview on or off, set the snap distance and the gap between stacked panels.",
        "Locked panels do not snap or leave a stack.",
    )),
    ("Several monitors", (
        "Each panel remembers the place where you put it. If its monitor is missing, the panel is shown on the main monitor.",
        "When the monitor comes back, the panel goes back to its own place. Nothing you saved is overwritten.",
        "If you move a panel yourself while its monitor is missing, the new place becomes its home.",
        "A panel's title bar always stays on a screen, never under the bar or the taskbar.",
    )),
    ("The bar", (
        "Turn it on in Settings › Bar › Show bar. It runs along the top of the main monitor; maximized windows stop below it.",
        "Panels that would sit under the bar are shown just below it. Their saved places are not changed.",
        "The date and time are on the right. Settings › Bar: show or hide them, 24-hour or 12-hour, with or without the date.",
        "Settings › Bar › Colors: click a color box to change it. Reset puts one back, Reset colors puts them all back.",
        "Right-click the bar (not a window button) to choose Settings…; quitting M Panels gives the screen space back.",
        "M Panels does not change your Windows taskbar settings. The tray's Show / Hide does not hide the bar.",
    )),
    ("Open windows", (
        "The bar lists your open windows, one button each, in the order the programs were started. New windows go to the end.",
        "Click a button to bring that window forward. Click the active window's button to minimize it; click a minimized one to restore it.",
        "Right-click a button and choose Close window to ask it to close, like its X button. A program can still ask about unsaved work.",
        "When there is no more room, the last button is +N. Its menu lists the other windows and works the same way.",
        "Settings › Bar: Show open windows turns the list off. Show window titles off gives icon-only buttons; point at one to see its title.",
    )),
    ("Search", (
        "Click the magnifier button on the bar, or press the shortcut key, and type a program name. Enter starts the first match.",
        "Arrow keys or a click choose another row. Esc closes the window and gives focus back; clicking elsewhere also closes it.",
        "It searches the Start menu's All apps list, Store apps included. Capitals and accents do not matter.",
        "Initials work too: typing vsc finds Visual Studio Code.",
        "Settings › Bar › Search: Shortcut key (Off, Win+Alt+Space or Ctrl+Shift+Space) and Include Store apps.",
        "If another program already uses the shortcut key, Apply tells you and changes nothing.",
        "Show 'Search Windows' row adds a last row, Search Windows for '…', that opens Windows Search and types your text there.",
    )),
    ("Start button", (
        "The button with four colored tiles at the left end of the bar opens the Windows Start menu. Click it again to close the menu.",
        "Right-click it to choose Settings…; Settings › Bar › Show Start button turns it off.",
    )),
    ("General", (
        "Lock panels: disables moving and resizing; opening items and collapsing still work.",
        "Hide desktop icons: hides Explorer's desktop icons; they come back when M Panels quits.",
        "Tray icon: Show / Hide, New panel, Settings… and Quit. Show / Hide does not hide the bar.",
        "Start with Windows: starts M Panels quietly at login.",
        "Starting M Panels twice just brings the running copy forward.",
        "Settings change only when you press Apply. Closing with unapplied changes asks Apply / Discard / Cancel.",
        "Every start saves a copy of your settings in the backups folder; the last 15 are kept.",
        "To go back: quit M Panels, copy a backup over config.json, then start M Panels again.",
    )),
    ("Known limitations", (
        "Programs running as administrator can be brought forward from the bar, but not minimized, restored or closed. Windows does not allow it.",
        "Windows opens the Start menu at the bottom left of the screen, next to its taskbar, not under the bar.",
        "Store apps show a general icon (with a letter) in search results; their own logo cannot be read.",
        "If Windows Search does not open within about a second, the text of the Search Windows row is not typed.",
        "Monitors with different display scaling (DPI) have not been tried.",
        "Panels below the top of a stack can extend past the bottom of the screen.",
        "Panels from two different missing monitors can end up on top of each other on the main monitor.",
    )),
)
