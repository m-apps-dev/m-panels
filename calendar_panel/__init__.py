"""Calendar panel support (ported from M Calendar's reading logic).

AVAILABLE tells the UI whether the optional calendar libraries are installed; when they are not,
the "Calendar" panel type is simply not offered.
"""
try:
    import icalendar  # noqa: F401
    import recurring_ical_events  # noqa: F401
    AVAILABLE = True
    UNAVAILABLE_REASON = ""
except Exception as _e:          # pragma: no cover - depends on the environment
    AVAILABLE = False
    UNAVAILABLE_REASON = str(_e)
