"""Logging for M Panels: a size-limited rotating log file (mpanels.log).

The program normally runs under pythonw (no console), so errors would vanish silently.
setup() sends uncaught exceptions (main thread, other threads, Tk callbacks) and anything written to
stdout/stderr into the log, together with a few startup lines. It never raises: if the log file
cannot be opened the program simply runs without a log.
"""
import logging
import logging.handlers
import os
import platform
import sys
import threading

LOG_NAME = "mpanels"
MAX_BYTES = 256 * 1024
BACKUPS = 3
_FORMAT = "%(asctime)s %(levelname)-7s %(message)s"


class _StreamToLog:
    """File-like object that forwards complete lines written to stdout/stderr to the logger."""

    def __init__(self, logger, level):
        self.logger, self.level, self._buf = logger, level, ""

    def write(self, text):
        if not text:
            return 0
        self._buf += str(text)
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self.logger.log(self.level, line.rstrip())
        return len(text)

    def flush(self):
        if self._buf.strip():
            self.logger.log(self.level, self._buf.rstrip())
        self._buf = ""

    def isatty(self):
        return False


def _close_handlers(logger):
    for h in list(logger.handlers):
        try:
            h.close()
        except Exception:
            pass
        logger.removeHandler(h)


def get_logger():
    return logging.getLogger(LOG_NAME)


def setup(path, max_bytes=MAX_BYTES, backups=BACKUPS, redirect_std=True, install_hooks=True):
    """Create/refresh the rotating log at `path` and return the logger (never raises)."""
    logger = get_logger()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    _close_handlers(logger)
    try:
        handler = logging.handlers.RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backups,
                                                       encoding="utf-8")
        handler.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(handler)
    except Exception:
        logger.addHandler(logging.NullHandler())
        return logger
    if install_hooks:
        install_exception_hooks(logger)
    if redirect_std and (sys.stdout is None or sys.stderr is None):
        # pythonw: there is no console, so print() and tracebacks would be lost (or even raise)
        if sys.stdout is None:
            sys.stdout = _StreamToLog(logger, logging.INFO)
        if sys.stderr is None:
            sys.stderr = _StreamToLog(logger, logging.ERROR)
    return logger


def install_exception_hooks(logger):
    def hook(exc_type, exc, tb):
        logger.error("Uncaught exception", exc_info=(exc_type, exc, tb))

    def thread_hook(args):
        logger.error("Uncaught exception in thread %s", getattr(args.thread, "name", "?"),
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = hook
    threading.excepthook = thread_hook


def tk_callback_handler(logger):
    """A function for root.report_callback_exception (Tk swallows callback errors otherwise)."""
    def handler(exc_type, exc, tb):
        logger.error("Exception in Tk callback", exc_info=(exc_type, exc, tb))
    return handler


def log_startup(logger, version, mode, desktop, data_dir):
    """A few lines that make a bug report useful."""
    logger.info("=== M Panels v%s starting (%s) ===", version, mode)
    logger.info("python %s | %s | %s", sys.version.split()[0], platform.platform(), sys.executable)
    logger.info("desktop=%s | data=%s | pid=%s", desktop, data_dir, os.getpid())
