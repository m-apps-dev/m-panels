"""Setup helper for M Panels.

  python kur.py                    install packages, (re)write M-Panels.bat / M-Panels-Test.bat
  python kur.py --shortcuts        also create the Startup and Desktop shortcuts in the REAL locations
                                   (only after approval, at the real-desktop stage)
  python kur.py --target <folder> --skip-pip
                                   trial run: the shortcuts go to <folder>, the real desktop and the
                                   real Startup folder are not touched
  python kur.py --write-bat        only (re)write the two .bat files, then exit

Everything starts through pythonw.exe (no console window), including "Start with Windows".
"""
import argparse
import os
import subprocess
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import strings as ui  # noqa: E402

SCRIPT = os.path.join(APP_DIR, "mpanels.py")
PACKAGES = ["pystray", "pillow", "tkinterdnd2", "pywin32"]
BAT_NAME = "M-Panels.bat"
BAT_TEST_NAME = "M-Panels-Test.bat"
# The test-mode desktop folder lives next to the program folder (<program folder>\..\mpanels_deneme).
TEST_DESKTOP = os.path.join(os.path.dirname(APP_DIR), "mpanels_deneme")


def build_bat(pythonw, script="%~dp0mpanels.py", extra_args=""):
    """Text of a launcher .bat: start the program with pythonw (no console window).
    The script path is relative to the .bat itself (%~dp0) so the folder can be moved.
    A .bat double-click may still flash a console for an instant; the shortcuts target pythonw directly."""
    start = f'start "" "{pythonw}" "{script}"'
    if extra_args:
        start += " " + extra_args
    return "\r\n".join([
        "@echo off",
        "rem M Panels launcher - starts the program with pythonw (no console window).",
        "rem Written by kur.py (python kur.py --write-bat); re-run it if the Python install moves.",
        start + " %*",
        "",
    ])


def write_bats(pythonw, app_dir=APP_DIR, test_desktop=TEST_DESKTOP):
    """(Re)write M-Panels.bat and M-Panels-Test.bat in app_dir. Returns the two paths."""
    out = []
    for name, extra in ((BAT_NAME, ""), (BAT_TEST_NAME, f'--desktop "{test_desktop}"')):
        path = os.path.join(app_dir, name)
        with open(path, "w", encoding="oem", newline="") as f:
            f.write(build_bat(pythonw, extra_args=extra))
        out.append(path)
    return out


def make_shortcut(folder, pythonw, name=ui.APP_NAME, extra_args="", suffix="", icon=""):
    """Create <folder>\\<name><suffix>.lnk that runs mpanels.py through pythonw. Existing links with
    the same name are replaced; no other file is touched."""
    import winutil
    lnk = os.path.join(folder, name + suffix + ".lnk")
    winutil.create_shortcut(
        lnk, pythonw, args=f'"{SCRIPT}"' + (" " + extra_args if extra_args else ""),
        workdir=APP_DIR, icon=icon or "", desc=ui.KUR_SHORTCUT_DESC.format(name=name))
    return lnk


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=ui.APP_NAME)
    ap.add_argument("--target", help=ui.KUR_ARG_TARGET)
    ap.add_argument("--skip-pip", action="store_true", help=ui.KUR_ARG_SKIP_PIP)
    ap.add_argument("--shortcuts", action="store_true", help=ui.KUR_ARG_SHORTCUTS)
    ap.add_argument("--write-bat", action="store_true", help=ui.KUR_ARG_WRITE_BAT)
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if not args.write_bat:
        if args.skip_pip:
            print(ui.KUR_PIP_SKIPPED)
        else:
            print(ui.KUR_PIP)
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", *PACKAGES])

    import winutil  # after pywin32 is installed
    pythonw = winutil.find_pythonw()
    if not pythonw:
        raise SystemExit(ui.KUR_NO_PYTHONW.format(python=sys.executable))

    for path in write_bats(pythonw):
        print(ui.KUR_BAT_WRITTEN.format(path=path))
    if args.write_bat:
        return

    icon = winutil.app_icon_path() or ""
    if args.target:
        startup = desktop = os.path.abspath(args.target)
        os.makedirs(startup, exist_ok=True)
        suffix = ui.KUR_STARTUP_SUFFIX
    elif args.shortcuts:
        startup, desktop, suffix = winutil.get_startup_dir(), winutil.get_real_desktop(), ""
    else:
        print(ui.KUR_NO_SHORTCUTS)
        return

    print(ui.KUR_SHORTCUTS)
    # The Startup shortcut passes --autostart: if "Start with Windows" is off in Settings the program
    # quietly exits at login. Both shortcuts target pythonw.exe directly, so no console window appears.
    print("   ", make_shortcut(startup, pythonw, extra_args="--autostart", suffix=suffix, icon=icon))
    print("   ", make_shortcut(desktop, pythonw, icon=icon))
    print(ui.KUR_DONE.format(name=ui.APP_NAME))
    print(ui.KUR_FIRST_RUN.format(panel=ui.DEFAULT_PANEL_NAME))


if __name__ == "__main__":
    main()
