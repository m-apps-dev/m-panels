"""M Panels file logic (no UI, testable).

Design rules:
  * No path is hard-coded; the Ctx (desktop, public desktop) is supplied by the caller.
  * There is NO permanent deletion: nothing in this module deletes a file/folder. It only moves
    (os.rename, same drive) and creates shortcuts.
  * Nothing is overwritten; on a name clash " (2)", " (3)"... is appended.
    (The one exception: a note panel's OWN note file is updated — temp file + os.replace.)
  * A locked/open file is not forced; the failure comes back as a message.
"""
import os
import re
from dataclasses import dataclass, field

import notefmt
import strings as ui
import winutil

PANELS_DIRNAME = "Paneller"
TRASH_DIRNAME = "_silinecek"
IGNORED_NAMES = {"desktop.ini", "thumbs.db"}
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}


# ------------------------------------------------------------------ context / result
@dataclass
class Ctx:
    desktop: str
    public_desktop: str = ""
    panels_root: str = field(init=False)

    def __post_init__(self):
        self.desktop = os.path.abspath(self.desktop)
        if self.public_desktop:
            self.public_desktop = os.path.abspath(self.public_desktop)
        self.panels_root = os.path.join(self.desktop, PANELS_DIRNAME)

    @property
    def trash(self):
        return os.path.join(self.panels_root, TRASH_DIRNAME)

    def panel_path(self, name):
        return os.path.join(self.panels_root, name)


@dataclass
class Result:
    ok: bool
    kind: str          # moved | shortcut | copied_shortcut | skip | refused | error
    message: str = ""
    dest: str = ""

    def __bool__(self):
        return self.ok


@dataclass
class Item:
    name: str          # display name (without the .lnk extension)
    path: str
    is_dir: bool
    is_lnk: bool
    broken: bool = False
    special: str = ""       # "recycle" = Recycle Bin (not a file, only in the config)


# ------------------------------------------------------------------ helpers
def norm(p):
    return os.path.normcase(os.path.abspath(p))


def parent_of(p):
    return norm(os.path.dirname(os.path.abspath(p)))


def is_inside(child, folder):
    """Is child inside folder (at any depth) or the folder itself?"""
    c, f = norm(child), norm(folder)
    return c == f or c.startswith(f.rstrip("\\") + "\\")


def same_drive(a, b):
    da, db = os.path.splitdrive(os.path.abspath(a))[0].lower(), os.path.splitdrive(os.path.abspath(b))[0].lower()
    return bool(da) and da == db


def valid_name(name):
    """Is the panel/item name valid? Returns the reason if not, else None."""
    n = (name or "").strip()
    if not n:
        return ui.NAME_EMPTY
    if _BAD_CHARS.search(n):
        return ui.NAME_BAD_CHARS
    if n.endswith(".") or n != name.strip():
        return ui.NAME_ENDS_DOT
    if n.split(".")[0].lower() in _RESERVED:
        return ui.NAME_RESERVED
    if n.lower() == TRASH_DIRNAME:
        return ui.NAME_RESERVED_APP.format(name=TRASH_DIRNAME)
    if len(n) > 100:
        return ui.NAME_TOO_LONG
    return None


def unique_name(folder, name, is_dir=False):
    """A non-clashing name in folder: 'name', 'name (2)', 'name (3)'... (extension kept)."""
    base, ext = (name, "") if is_dir else os.path.splitext(name)
    cand, n = name, 2
    while os.path.lexists(os.path.join(folder, cand)):
        cand = f"{base} ({n}){ext}"
        n += 1
    return cand


def display_name(filename, is_dir=False):
    if not is_dir and filename.lower().endswith(".lnk"):
        return filename[:-4]
    return filename


def _fail(e, what=""):
    """OSError -> a short message for the user (nothing is forced)."""
    if isinstance(e, PermissionError) or getattr(e, "winerror", 0) in (5, 32, 33):
        return ui.MOVE_LOCKED.format(what=what)
    return ui.MOVE_FAILED.format(what=what, error=e.strerror or e)


def _move(src, dest_dir):
    """Move src into dest_dir under a non-clashing name (same drive). Returns a Result."""
    is_dir = os.path.isdir(src)
    name = unique_name(dest_dir, os.path.basename(src), is_dir)
    dest = os.path.join(dest_dir, name)
    try:
        os.rename(src, dest)
    except OSError as e:
        return Result(False, "error", _fail(e, f"'{display_name(os.path.basename(src), is_dir)}': "))
    return Result(True, "moved", dest=dest)


def make_shortcut_to(src, dest_dir):
    is_dir = os.path.isdir(src)
    base = os.path.basename(src.rstrip("\\/")) or src
    stem = base if is_dir else os.path.splitext(base)[0] or base
    name = unique_name(dest_dir, stem + ".lnk")
    dest = os.path.join(dest_dir, name)
    try:
        winutil.create_shortcut(dest, os.path.abspath(src))
    except Exception as e:
        return Result(False, "error", ui.SHORTCUT_FAILED.format(error=e))
    return Result(True, "shortcut", dest=dest)


# ------------------------------------------------------------------ panel folders
def ensure_panels_root(ctx):
    """Create the (hidden) Paneller folder. Only works under ctx.desktop."""
    os.makedirs(ctx.panels_root, exist_ok=True)
    winutil.set_hidden(ctx.panels_root)


def list_panel_folders(ctx):
    if not os.path.isdir(ctx.panels_root):
        return []
    out = []
    for e in os.scandir(ctx.panels_root):
        if e.is_dir() and e.name.lower() != TRASH_DIRNAME:
            out.append(e.name)
    return sorted(out, key=str.casefold)


def create_panel(ctx, name):
    err = valid_name(name)
    if err:
        return Result(False, "refused", err)
    ensure_panels_root(ctx)
    path = ctx.panel_path(name)
    if os.path.lexists(path):
        return Result(False, "refused", ui.PANEL_EXISTS)
    os.mkdir(path)
    return Result(True, "moved", dest=path)


def rename_panel(ctx, old, new):
    err = valid_name(new)
    if err:
        return Result(False, "refused", err)
    src, dst = ctx.panel_path(old), ctx.panel_path(new)
    if norm(src) != norm(dst) and os.path.lexists(dst):
        return Result(False, "refused", ui.PANEL_EXISTS)
    try:
        os.rename(src, dst)          # also works when only the letter case changes
    except OSError as e:
        return Result(False, "error", _fail(e, ui.PANEL_RENAME_FAILED))
    return Result(True, "moved", dest=dst)


def remove_panel(ctx, name):
    """Remove a panel: its contents move back to the desktop (' (2)' on a clash), then the empty folder
    is MOVED to _silinecek. Nothing is deleted. If an item cannot be moved the panel stays in place."""
    folder = ctx.panel_path(name)
    if not os.path.isdir(folder):
        return Result(False, "error", ui.PANEL_FOLDER_MISSING)
    moved, problems = 0, []
    for e in os.scandir(folder):
        r = _move(e.path, ctx.desktop)
        if r.ok:
            moved += 1
        else:
            problems.append(r.message)
    if problems:
        return Result(False, "error",
                      ui.PANEL_REMOVE_PARTIAL.format(moved=moved, failed=len(problems), problems=" ".join(problems)))
    os.makedirs(ctx.trash, exist_ok=True)
    r = _move(folder, ctx.trash)
    if not r.ok:
        return Result(False, "error", r.message)
    return Result(True, "moved", ui.PANEL_REMOVED.format(moved=moved), dest=r.dest)


# ------------------------------------------------------------------ note panels (rich text, JSON)
NOTES_DIRNAME = "notlar"
NOTE_EXT = ".json"
LEGACY_NOTE_EXT = ".txt"        # version 2's plain-text notes: imported on first open


@dataclass
class NoteData:
    text: str = ""
    spans: list = field(default_factory=list)
    imported: bool = False      # the old .txt was imported
    warning: str = ""


def notes_dir(data_dir):
    return os.path.join(data_dir, NOTES_DIRNAME)


def notes_trash(data_dir):
    return os.path.join(notes_dir(data_dir), TRASH_DIRNAME)


def note_path(data_dir, name):
    return os.path.join(notes_dir(data_dir), name + NOTE_EXT)


def legacy_note_path(data_dir, name):
    return os.path.join(notes_dir(data_dir), name + LEGACY_NOTE_EXT)


def note_payload(text, spans=None):
    """The JSON text to write to disk (also used for comparisons)."""
    return notefmt.dumps(text, spans or [])


def _to_trash(data_dir, path):
    try:
        os.makedirs(notes_trash(data_dir), exist_ok=True)
    except OSError as e:
        return Result(False, "error", _fail(e))
    return _move(path, notes_trash(data_dir))


def read_note(data_dir, name):
    """Returns NoteData. An old plain .txt is imported (JSON written, the .txt MOVED to _silinecek).
    Broken JSON is not destroyed: it is moved to _silinecek, the note opens empty and a warning is given."""
    jp, tp = note_path(data_dir, name), legacy_note_path(data_dir, name)
    if os.path.exists(jp):
        try:
            with open(jp, "r", encoding="utf-8") as f:
                text, spans = notefmt.loads(f.read())
            return NoteData(text, spans)
        except (OSError, ValueError) as e:
            r = _to_trash(data_dir, jp)
            where = (ui.NOTE_WHERE_TRASH.format(trash=f"{NOTES_DIRNAME}/{TRASH_DIRNAME}") if r.ok
                     else ui.NOTE_WHERE_KEPT)
            return NoteData(warning=ui.NOTE_UNREADABLE.format(error=e, where=where))
    if os.path.exists(tp):
        try:
            with open(tp, "r", encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError) as e:
            return NoteData(warning=ui.NOTE_LEGACY_UNREADABLE.format(error=e))
        w = write_note(data_dir, name, text, [])
        if not w.ok:
            return NoteData(text, warning=w.message + ui.NOTE_LEGACY_KEPT)
        r = _to_trash(data_dir, tp)
        return NoteData(text, imported=True,
                        warning="" if r.ok else ui.NOTE_LEGACY_TRASH_FAIL.format(trash=TRASH_DIRNAME, error=r.message))
    return NoteData()


def write_note(data_dir, name, text, spans=None):
    """Write the note to a temp file and os.replace it into place (no half-written file). Returns a Result."""
    path = note_path(data_dir, name)
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(note_payload(text, spans))
        os.replace(tmp, path)
    except OSError as e:
        return Result(False, "error", ui.NOTE_SAVE_FAILED.format(error=e.strerror or e))
    return Result(True, "moved", dest=path)


def name_taken(ctx, data_dir, cfg_panels, name, ignore=None):
    """Shortcut-panel folders and note names share one namespace (case-insensitive)."""
    n = name.strip().casefold()
    names = list(list_panel_folders(ctx)) + [k for k, v in cfg_panels.items() if v.get("type") in ("note", "calendar")]
    return any(x.casefold() == n for x in names if x != ignore)


def create_note(data_dir, name):
    err = valid_name(name)
    if err:
        return Result(False, "refused", err)
    if os.path.lexists(note_path(data_dir, name)) or os.path.lexists(legacy_note_path(data_dir, name)):
        return Result(False, "refused", ui.NOTE_EXISTS)
    return write_note(data_dir, name, "", [])


def rename_note(data_dir, old, new):
    err = valid_name(new)
    if err:
        return Result(False, "refused", err)
    src, dst = note_path(data_dir, old), note_path(data_dir, new)
    if norm(src) != norm(dst) and os.path.lexists(dst):
        return Result(False, "refused", ui.NOTE_EXISTS)
    if not os.path.exists(src):
        return Result(True, "moved", dest=dst)       # a note not written yet: no file to move
    try:
        os.rename(src, dst)
    except OSError as e:
        return Result(False, "error", _fail(e, ui.NOTE_RENAME_FAILED))
    return Result(True, "moved", dest=dst)


def remove_note(data_dir, name):
    """Does NOT delete the note file: moves it into notlar/_silinecek under a non-clashing name."""
    src = note_path(data_dir, name)
    if not os.path.exists(src):
        return Result(True, "moved", ui.NOTE_FILE_MISSING)
    return _to_trash(data_dir, src)


# ------------------------------------------------------------------ drag and drop
def handle_drop(ctx, panel_name, src):
    """Apply the rules when an item is dropped on a panel: where it goes, and what happens to the source."""
    panel = ctx.panel_path(panel_name)
    src = os.path.abspath(src.strip().strip('"'))
    if not os.path.lexists(src):
        return Result(False, "error", ui.ITEM_NOT_FOUND)

    # Guards: the desktop itself, the Paneller folder, a panel folder or a path containing
    # them is refused (putting a panel inside itself or above itself).
    if is_inside(panel, src) or norm(src) == norm(ctx.panels_root) or parent_of(src) == norm(ctx.panels_root):
        return Result(False, "refused", ui.DROP_PANEL_FOLDER)
    if parent_of(src) == norm(panel):
        return Result(True, "skip", ui.DROP_ALREADY)

    parent = parent_of(src)
    same = same_drive(src, panel)
    from_other_panel = parent_of(parent) == norm(ctx.panels_root) if parent else False
    from_desktop = parent == norm(ctx.desktop)
    from_public = bool(ctx.public_desktop) and parent == norm(ctx.public_desktop)

    if from_public:
        # Public desktop: cannot be moved without admin rights -> a copied shortcut, the original stays.
        if src.lower().endswith(".lnk"):
            name = unique_name(panel, os.path.basename(src))
            dest = os.path.join(panel, name)
            try:
                with open(src, "rb") as fi, open(dest, "xb") as fo:    # 'x': never overwrites
                    fo.write(fi.read())
            except OSError as e:
                return Result(False, "error", ui.COPY_FAILED.format(error=e.strerror or e))
            r = Result(True, "copied_shortcut", dest=dest)
        else:
            r = make_shortcut_to(src, panel)
            r.kind = "copied_shortcut" if r.ok else r.kind
        if r.ok:
            r.message = ui.PUBLIC_COPIED
        return r

    if (from_desktop or from_other_panel) and same:
        return _move(src, panel)

    # Not from the desktop (or a different drive): no move, a shortcut.
    r = make_shortcut_to(src, panel)
    if r.ok and (from_desktop or from_other_panel):
        r.message = ui.DIFFERENT_DRIVE
    return r


def return_to_desktop(ctx, item_path):
    """MOVE the item back to the desktop (' (2)' on a clash)."""
    if parent_of(item_path) == norm(ctx.desktop):
        return Result(True, "skip")
    return _move(item_path, ctx.desktop)


def rename_item(item_path, new_display):
    """Rename an item in the same folder; refuses on a clash (never overwrites)."""
    err = valid_name(new_display)
    if err:
        return Result(False, "refused", err)
    folder = os.path.dirname(item_path)
    new = new_display.strip()
    if item_path.lower().endswith(".lnk") and not new.lower().endswith(".lnk"):
        new += ".lnk"
    dst = os.path.join(folder, new)
    if norm(dst) != norm(item_path) and os.path.lexists(dst):
        return Result(False, "refused", ui.ITEM_EXISTS)
    try:
        os.rename(item_path, dst)
    except OSError as e:
        return Result(False, "error", _fail(e, ui.RENAME_FAILED))
    return Result(True, "moved", dest=dst)


# ------------------------------------------------------------------ listing
def list_items(folder, order=None):
    """The contents of a panel folder. Order: those in the order list first, the rest A-Z."""
    items = []
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return items
    for e in entries:
        if e.name.lower() in IGNORED_NAMES or winutil.is_hidden(e.path):
            continue
        is_dir = e.is_dir()
        is_lnk = (not is_dir) and e.name.lower().endswith(".lnk")
        broken = False
        if is_lnk:
            t = winutil.resolve_shortcut(e.path)
            broken = bool(t) and os.path.isabs(t) and not os.path.exists(t)
        items.append(Item(display_name(e.name, is_dir), e.path, is_dir, is_lnk, broken))
    pos = {n.casefold(): i for i, n in enumerate(order or [])}
    items.sort(key=lambda it: (pos.get(os.path.basename(it.path).casefold(), 10 ** 6),
                               it.name.casefold()))
    return items
