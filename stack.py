"""Snapping and stacks (v1.1 step 7a). Pure logic: no tkinter, no Windows calls, so it is tested without a screen.

Panels are identified by their name (the key in config["panels"]). A stack is a list of names, top to bottom;
config["stacks"] is a list of stacks. The layout is always DERIVED from the stack top and the panel heights."""

DEFAULT_SNAP_DISTANCE = 24          # px: how close a dropped panel's top edge must be to the stack's bottom edge
DEFAULT_STACK_GAP = 2               # px: the space between stacked panels
GENERAL_KEYS = ("snap_enabled", "snap_preview", "snap_distance", "stack_gap")
SNAP_DISTANCE_RANGE = (4, 64)
STACK_GAP_RANGE = (0, 24)


def _int_in(v, lo, hi, default):
    """A whole number inside [lo, hi]; anything else (text, bool, None, float with a fraction, out of range) -> default."""
    if isinstance(v, bool):
        return default
    if isinstance(v, float) and v == int(v):
        v = int(v)
    if not isinstance(v, int):
        return default
    return v if lo <= v <= hi else default


def sanitize_general(g):
    """Fix general.snap_distance / stack_gap / snap_enabled in place (missing or broken -> defaults)."""
    g["snap_distance"] = _int_in(g.get("snap_distance"), *SNAP_DISTANCE_RANGE, DEFAULT_SNAP_DISTANCE)
    g["stack_gap"] = _int_in(g.get("stack_gap"), *STACK_GAP_RANGE, DEFAULT_STACK_GAP)
    for key in ("snap_enabled", "snap_preview"):
        if not isinstance(g.get(key), bool):
            g[key] = True
    return g


def sanitize_stacks(stacks, known):
    """A clean list of stacks: unknown names and repeats dropped, one stack per panel, stacks shorter than 2 removed."""
    out, seen = [], set()
    if not isinstance(stacks, list):
        return out
    for s in stacks:
        if not isinstance(s, list):
            continue
        clean = []
        for n in s:
            if isinstance(n, str) and n in known and n not in seen:
                seen.add(n)
                clean.append(n)
        if len(clean) >= 2:
            out.append(clean)
    return out


def find(stacks, name):
    """(stack index, position) of a panel, or None."""
    for i, s in enumerate(stacks):
        if name in s:
            return i, s.index(name)
    return None


def remove(stacks, name):
    """The stacks without this panel (a stack left with fewer than 2 panels disappears)."""
    out = []
    for s in stacks:
        s = [n for n in s if n != name]
        if len(s) >= 2:
            out.append(s)
    return out


def rename(stacks, old, new):
    return [[new if n == old else n for n in s] for s in stacks]


def add_below(stacks, bottom, name):
    """Put `name` under `bottom`, which must be the bottom of a stack or a free panel (then they form a new stack)."""
    stacks = remove(stacks, name)
    for s in stacks:
        if s[-1] == bottom:
            s.append(name)
            return stacks
    if find(stacks, bottom) is None:
        stacks.append([bottom, name])
    return stacks


def positions(y, heights, gap):
    """Top y of each panel when the first one is at `y` and every panel is followed by `gap`."""
    out = []
    for h in heights:
        out.append(y)
        y += h + gap
    return out


MIN_OVERLAP = 0.5       # share of the narrower (or lower) panel that must overlap for an edge snap to count


def overlap_len(a0, alen, b0, blen):
    """How many px two 1-D intervals [a0, a0+alen) and [b0, b0+blen) share (0 when they only touch)."""
    return max(0, min(a0 + alen, b0 + blen) - max(a0, b0))


def overlaps_horizontally(ax, aw, bx, bw):
    """Do two spans share at least MIN_OVERLAP of the narrower one? (A 1 px overlap is not an intention.)"""
    return overlap_len(ax, aw, bx, bw) > 0 and overlap_len(ax, aw, bx, bw) >= MIN_OVERLAP * min(aw, bw)


def overlaps_vertically(ay, ah, by, bh):
    """Do two spans share at least MIN_OVERLAP of the lower one? Heights are the CURRENT visible heights (a closed
    panel is only its bar)."""
    return overlap_len(ay, ah, by, bh) > 0 and overlap_len(ay, ah, by, bh) >= MIN_OVERLAP * min(ah, bh)


def rects_collide(a, b):
    """(x, y, w, h) rectangles: do they share area? Touching edges do not count."""
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def _free(moved, obstacles):
    # obstacles may be (name, x, y, w, h) or (x, y, w, h)
    return not obstacles or not any(rects_collide(m, o[-4:]) for m in moved for o in obstacles)


def _below_options(dragged, candidates, threshold, gap, obstacles):
    """[(distance, name)] of every candidate the dropped panel could snap under (sorted by order of candidates)."""
    dn, dx, dy, dw, dh = dragged
    out = []
    for cn, cx, cy, cw, ch in candidates:
        if cn == dn:
            continue
        d = abs(dy - (cy + ch + gap))
        if d > threshold or not overlaps_horizontally(dx, dw, cx, cw):
            continue
        if _free([(cx, cy + ch + gap, cw, dh)], obstacles):        # where it would end up: nothing may be there
            out.append((d, cn))
    return out


def _side_options(dragged, candidates, threshold, gap, obstacles, group, ok=None):
    """[(distance, name, x, y)] of every spot beside a candidate the dropped panel (or its whole group) could take.
    `ok(x, y, w)` (step 7c): may the panel HEAD be at this spot (reachable on a real monitor)? No -> the spot is skipped."""
    dn, dx, dy, dw, dh = dragged
    group = group or [(dx, dy, dw, dh)]
    out = []
    for cn, cx, cy, cw, ch in candidates:
        if cn == dn or not overlaps_vertically(dy, dh, cy, ch):
            continue
        for tx in (cx + cw + gap, cx - gap - dw):               # right of the target, then left of it
            d = abs(dx - tx)
            if d > threshold or (ok is not None and not ok(tx, cy, dw)):
                continue
            moved =[(gx + tx - dx, gy + cy - dy, gw, gh) for gx, gy, gw, gh in group]
            if _free(moved, obstacles):
                out.append((d, cn, tx, cy))
    return out


def find_snap(dragged, candidates, threshold, gap=DEFAULT_STACK_GAP, obstacles=None):
    """Which candidate should the dropped panel snap under?

    dragged, candidates: (name, x, y, w, h) with the CURRENT visible size (a closed panel is only its bar). A candidate
    is the BOTTOM panel of a stack or a free panel. The dropped panel's top edge must be within `threshold` px
    (inclusive, above or below) of the TARGET position (the candidate's bottom edge + `gap`), and the two must overlap
    horizontally by at least half of the narrower one. With `obstacles` (rectangles), a spot that would overlap one of
    them is skipped. The monitor the dropped panel came from does not matter: it takes the target's left edge and
    width, so the stack stays on the target's monitor. The nearest wins (ties: the first). Returns its name."""
    opts = _below_options(dragged, candidates, threshold, gap, obstacles)
    return min(opts, key=lambda o: o[0])[1] if opts else None


def find_side(dragged, candidates, threshold, gap=DEFAULT_STACK_GAP, obstacles=None, group=None, ok=None):
    """Where should the dropped panel snap sideways? (step 7b)

    dragged, candidates: (name, x, y, w, h); any panel can be a candidate (also one in the middle of a stack). The
    dragged panel's left edge must be within `threshold` px (inclusive) of the spot right of the candidate (its right
    edge + `gap`), or its right edge within `threshold` of the spot left of it (candidate's left edge - `gap`), and
    the two must overlap vertically by at least half of the lower one (visible heights). The width never changes; the
    top edge becomes the candidate's top edge. `group` = rectangles that move together with the dragged panel (a stack
    top drags its stack); a spot where any of them would overlap an obstacle is skipped.
    The nearest wins (ties: the first candidate, right side before left). Returns (name, x, y) or None."""
    opts = _side_options(dragged, candidates, threshold, gap, obstacles, group, ok)
    if not opts:
        return None
    best = min(opts, key=lambda o: o[0])
    return best[1], best[2], best[3]


def choose_drop(dragged, bottoms, others, threshold, gap=DEFAULT_STACK_GAP, group=None, ok=None):
    """Decide what dropping a panel does: snap under a stack bottom, snap sideways, or nothing.

    `bottoms` = candidates to snap under (empty when the dragged thing may not snap under anything, e.g. a stack top),
    `others` = candidates for the side snap AND the obstacles: every spot that would overlap any of them is dropped from
    the list and the next one is tried; when none is left the panel stays where it was dropped. The smaller distance
    wins; on a tie snapping under wins. `ok(x, y, w)` (step 7c): a side spot whose head would not be reachable on a
    real monitor (off the screen, in a dead area) is skipped like a colliding one, so the preview never shows it.
    Returns ("below", name), ("side", name, x, y) or None. Nothing here is remembered: a side snap is only an alignment."""
    options = [(d, 0, n, ("below", n)) for d, n in _below_options(dragged, bottoms, threshold, gap, others)]
    options += [(d, 1, n, ("side", n, x, y)) for d, n, x, y in _side_options(dragged, others, threshold, gap, others, group, ok)]
    if not options:
        return None
    return min(options, key=lambda o: (o[0], o[1]))[3]


def plan_rects(res, dragged, group, rect_of, gap):
    """Where a drop decision (the result of choose_drop) puts the dragged unit, and which edge of the target it hugs.

    Returns (rects, edge): `rects` = the (x, y, w, h) rectangles the dragged panel (or all panels of the dragged stack)
    will occupy, `edge` = (x0, y0, x1, y1) the target's edge that is highlighted. `rect_of[name]` = (name, x, y, w, h).
    This is the ONE place that says where a snap ends up: the preview draws it and the drop applies the same decision."""
    dn, dx, dy, dw, dh = dragged
    if res[0] == "below":
        _, cx, cy, cw, ch = rect_of[res[1]]
        return [(cx, cy + ch + gap, cw, dh)], (cx, cy + ch, cx + cw, cy + ch)
    _, name, x, y = res
    _, cx, cy, cw, ch = rect_of[name]
    group = group or [(dx, dy, dw, dh)]
    rects = [(gx + x - dx, gy + y - dy, gw, gh) for gx, gy, gw, gh in group]
    edge = (cx + cw, cy, cx + cw, cy + ch) if x >= cx + cw else (cx, cy, cx, cy + ch)
    return rects, edge
