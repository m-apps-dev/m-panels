"""Sürüm 4 birim testleri: arayüz metinleri tek yerde (strings.py), İngilizce yorumlar, log, tek örnek,
bat dosyaları, ikon yedeği, kur.py, görev çubuğu stilleri. Gerçek masaüstüne DOKUNMAZ.

Çalıştırma:  python -m unittest discover -s tests -v
"""
import ast
import io
import logging
import os
import re
import string
import sys
import tempfile
import threading
import time
import tokenize
import tkinter as tk
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import applog  # noqa: E402
import kur  # noqa: E402
import mpanels  # noqa: E402
import strings  # noqa: E402
import theme  # noqa: E402
import uiwidgets  # noqa: E402
import version  # noqa: E402
import winutil  # noqa: E402

# theme.py is allowed to hold literals (colors, font names; tests/test_v3.py guards the opposite direction)
AUDITED = ["mpanels", "fileops", "uiwidgets", "winutil", "deskicons", "richtext", "notefmt", "kur", "applog",
           "calendar_panel/__init__", "calendar_panel/core", "calendar_panel/source", "calendar_panel/model",
           "calendar_panel/settings", "calendar_panel/view", "changelog"]
TURKISH = "ğüşöçıİĞÜŞÖÇ"

# String constants that are NOT user-visible text. Everything else in code must come from strings.py.
TECHNICAL_EXACT = {
    # names of OS objects / on-disk names / registry / window classes
    "MPanels_SingleInstance", "TkDefaultFont", "quit step failed", "Toolbutton", "CHANGELOG.md", "MPanels_Test_", "MPanels", "*root", "shell:RecycleBinFolder", "!disabled",
    "Paneller", "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced",
    "Microsoft\\Windows\\Start Menu\\Programs\\Startup", "APPDATA", "Progman", "SHELLDLL_DefView", "/select,",
    "ShellState", "HideIcons",
    # Turkish case folding (single letters)
    "ı", "İ", "I",
    # rich-text tag prefixes, number formats, developer-facing error text
    "fmt:", "col:", "#x", "SHGetImageList error ",
    # kur.py: the generated .bat files
    "M-Panels.bat", "M-Panels-Test.bat", "%~dp0mpanels.py", 'start "" "', "@echo off", '--desktop "',
    "rem M Panels launcher - starts the program with pythonw (no console window).",
    "rem Written by kur.py (python kur.py --write-bat); re-run it if the Python install moves.",
    # log lines (developer-facing, English by design)
    "M Panels exited normally", "%(asctime)s %(levelname)-7s %(message)s",
    "=== M Panels v%s starting (%s) ===", "python %s | %s | %s", "desktop=%s | data=%s | pid=%s",
    "Uncaught exception", "Uncaught exception in thread %s", "Exception in Tk callback",
    # calendar_panel: HTTP, iCal property names, log lines, developer-facing errors
    "MPanels-Calendar/1.0", "webcal://", "https://", "User-Agent", "not an object", "%Y%m%d%H%M",
    "#[0-9a-fA-F]{6}", "could not open Google Calendar: %s","could not open Google Calendar: no browser accepted the request", "calendar: %s","calendar refresh failed: %s", "calendar %r could not be expanded: %s",
    # drag/snap diagnostics in mpanels.log (technical, English by design)
    "display layout changed: %d monitor(s) %s", "display check failed", "monitor layout could not be read; keeping the last known one",
    "drag press panel=%s xy=%s,%s moving=on", "release panel=%s xy=%s,%s moving_was=%s", "drop decision: lost_release=%s cancelled=%s locked=%s snap_enabled=%s snap_preview=%s candidate=%s preview_shown=%s event_xy=%s,%s panel_rect=%s", "1x1+0+0", "preview show box=%s", "drop_snap panel=%s choose_drop=%s", "press while an earlier drag was still open (release lost): finishing it first, panel=%s", "button already up while dragging (release lost): ending the drag, panel=%s", "motion with the button up (release lost): ending the drag, panel=%s", "drag start panel=%s held-check follows", "preview hide", "drag cancelled with Esc: restoring the layout of the press, panel=%s",
}
TECHNICAL_PATTERNS = [
    re.compile(r"^<.+>$"),                    # Tk event sequences
    re.compile(r"^[A-Z][A-Z0-9]{0,3}$"),      # PIL modes, GUID fields, mode tags
    re.compile(r"^[A-Za-z]$"),                # single letters
    re.compile(r"^\[.*\]$"),                  # regex character classes
    re.compile(r"^\^.*\$$"),                  # whole-string regexes
    re.compile(r"^[A-Z][A-Z0-9_]*$"),         # iCal property names (DTSTART, SUMMARY...)
    re.compile(r"^\*\.\w+$"),                  # file masks (*.json)
    re.compile(r"^%[A-Za-z][%A-Za-z:/ \-]*$"),  # strftime formats
]


def _docstring_ids(tree):
    ids = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            b = n.body
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) \
                    and isinstance(b[0].value.value, str):
                ids.add(id(b[0].value))
    return ids


def hardcoded_ui_strings(source):
    """[(line, text)] — string constants (not docstrings) that look like text and are not whitelisted."""
    tree = ast.parse(source)
    doc = _docstring_ids(tree)
    out = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Constant) and isinstance(n.value, str)) or id(n) in doc:
            continue
        v = n.value
        if not re.search(r"[^\W\d_]", v):
            continue                                   # no letters at all: symbols, digits, separators
        if re.fullmatch(r"[A-Za-z0-9_.\-]+", v) and not v[0].isupper():
            continue                                   # identifiers, dict keys, flags, file names
        if v in TECHNICAL_EXACT or any(p.match(v) for p in TECHNICAL_PATTERNS):
            continue
        out.append((n.lineno, v))
    return out


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestStringsAudit(unittest.TestCase):
    def test_kodda_sabit_arayuz_metni_yok(self):
        bad = []
        for m in AUDITED:
            for ln, v in hardcoded_ui_strings(read(os.path.join(ROOT, m + ".py"))):
                bad.append(f"{m}.py:{ln}: {v!r}")
        self.assertEqual(bad, [], "sabit arayüz metni var; strings.py'ye taşıyın:\n" + "\n".join(bad))

    def test_denetleyici_sabit_metni_yakalar(self):
        self.assertEqual([v for _, v in hardcoded_ui_strings('m.add_command(label="Open file")')], ["Open file"])
        self.assertEqual([v for _, v in hardcoded_ui_strings('messagebox.showwarning("Warning", "x y")')],
                         ["Warning", "x y"])
        self.assertEqual(hardcoded_ui_strings('m.add_command(label=ui.ITEM_OPEN)\nx = "title_size"\n'
                                              'def f():\n    """Doc text."""\n'), [])

    def test_kullanilan_metin_sabitleri_strings_icinde_var(self):
        missing = []
        for m in AUDITED:
            tree = ast.parse(read(os.path.join(ROOT, m + ".py")))
            for n in ast.walk(tree):
                if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "ui":
                    if not hasattr(strings, n.attr):
                        missing.append(f"{m}: ui.{n.attr}")
        self.assertEqual(missing, [])

    def test_format_alanlari_cagrilarla_uyumlu(self):
        """ui.X.format(a=..., b=...) çağrısındaki anahtarlar, X içindeki {alan}larla birebir aynı olmalı."""
        problems = []
        for m in AUDITED:
            tree = ast.parse(read(os.path.join(ROOT, m + ".py")))
            for n in ast.walk(tree):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "format"
                        and isinstance(n.func.value, ast.Attribute) and isinstance(n.func.value.value, ast.Name)
                        and n.func.value.value.id == "ui" and hasattr(strings, n.func.value.attr)):
                    name = n.func.value.attr
                    want = {f for _, f, _, _ in string.Formatter().parse(getattr(strings, name)) if f}
                    got = {k.arg for k in n.keywords if k.arg}
                    if any(k.arg is None for k in n.keywords) or n.args:
                        continue                                    # **kwargs / positional: cannot check
                    if want != got:
                        problems.append(f"{m}:{n.lineno} {name}: gerekli {sorted(want)}, verilen {sorted(got)}")
        self.assertEqual(problems, [])

    def test_strings_py_gecerli(self):
        names = [n for n in dir(strings) if n.isupper()]
        self.assertGreater(len(names), 100)
        for n in names:
            v = getattr(strings, n)
            if isinstance(v, str):
                list(string.Formatter().parse(v))                   # raises on a broken format string
        self.assertEqual(strings.APP_NAME, "M Panels")
        self.assertEqual(strings.TEST_TAG, "(TEST)")
        self.assertEqual(set(strings.COLOR_NAMES), {k for k, _ in theme.PRESETS})

    def test_strings_py_turkce_harf_yok(self):
        """Arayüz İngilizce: Türkçe harf yalnız örnek metinde (yazı tipi önizlemesi) bulunabilir."""
        bad = [n for n in dir(strings) if n.isupper() and isinstance(getattr(strings, n), str)
               and any(c in getattr(strings, n) for c in TURKISH) and n != "SAMPLE_TEXT"]
        self.assertEqual(bad, [])

    def test_on_ayarli_renk_adlari_stringsten(self):
        self.assertEqual([n for n, _ in mpanels.PRESETS], [strings.COLOR_NAMES[k] for k, _ in theme.PRESETS])


class TestCommentsEnglish(unittest.TestCase):
    ALLOWED = ("Sürüm geçmişi",)          # the Turkish name of a NOTLAR.md section, quoted verbatim

    def _texts(self, path):
        src = read(path)
        out = []
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                out.append((tok.start[0], tok.string))
        tree = ast.parse(src)
        for n in ast.walk(tree):
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef)):
                b = n.body
                if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) \
                        and isinstance(b[0].value.value, str):
                    out.append((b[0].lineno, b[0].value.value))
        return out

    def test_yorumlar_ve_docstringler_ingilizce(self):
        bad = []
        files = [m + ".py" for m in AUDITED + ["theme", "strings", "version"]] + [os.path.join("tools", "ikon_uret.py")]
        for f in files:
            for ln, text in self._texts(os.path.join(ROOT, f)):
                for a in self.ALLOWED:
                    text = text.replace(a, "")
                if any(c in text for c in TURKISH):
                    bad.append(f"{f}:{ln}: {text[:60]!r}")
        self.assertEqual(bad, [])

    def test_readme_ingilizce(self):
        text = read(os.path.join(ROOT, "README.md"))
        self.assertEqual([c for c in text if c in TURKISH], [])


class TestAppLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mp_log_")
        self.saved = (sys.excepthook, threading.excepthook, sys.stdout, sys.stderr)

    def tearDown(self):
        sys.excepthook, threading.excepthook, sys.stdout, sys.stderr = self.saved
        applog._close_handlers(applog.get_logger())
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dosyaya_yazar_ve_baslangic_bilgisi(self):
        p = os.path.join(self.tmp, "t.log")
        log = applog.setup(p, redirect_std=False)
        applog.log_startup(log, "9.9.9", "TEST", r"C:\deneme", r"C:\veri")
        applog.close = None
        for h in log.handlers:
            h.flush()
        text = read(p)
        self.assertIn("M Panels v9.9.9 starting (TEST)", text)
        self.assertIn(r"desktop=C:\deneme", text)
        self.assertIn("python ", text)

    def test_yakalanmamis_hata_loga_yazilir(self):
        p = os.path.join(self.tmp, "t.log")
        applog.setup(p, redirect_std=False)
        try:
            raise ValueError("deneme hatasi")
        except ValueError:
            sys.excepthook(*sys.exc_info())
        t = threading.Thread(target=lambda: 1 / 0, name="deneme-is-parcacigi")
        t.start()
        t.join()
        text = read(p)
        self.assertIn("Uncaught exception", text)
        self.assertIn("ValueError: deneme hatasi", text)
        self.assertIn("deneme-is-parcacigi", text)
        self.assertIn("ZeroDivisionError", text)

    def test_tk_callback_hatasi_loga_yazilir(self):
        p = os.path.join(self.tmp, "t.log")
        log = applog.setup(p, redirect_std=False)
        try:
            raise KeyError("tk")
        except KeyError:
            applog.tk_callback_handler(log)(*sys.exc_info())
        self.assertIn("Exception in Tk callback", read(p))

    def test_donen_log_boyut_sinirli(self):
        p = os.path.join(self.tmp, "r.log")
        log = applog.setup(p, max_bytes=2000, backups=2, redirect_std=False)
        for i in range(400):
            log.info("satir %d %s", i, "x" * 40)
        files = sorted(f for f in os.listdir(self.tmp) if f.startswith("r.log"))
        self.assertEqual(files, ["r.log", "r.log.1", "r.log.2"])
        for f in files:
            self.assertLessEqual(os.path.getsize(os.path.join(self.tmp, f)), 2200)

    def test_konsol_yokken_print_loga_gider(self):
        """pythonw'de sys.stdout/stderr None olur; print ve traceback kaybolmamalı."""
        p = os.path.join(self.tmp, "s.log")
        sys.stdout = sys.stderr = None
        applog.setup(p, redirect_std=True)
        print("merhaba log")
        sys.stderr.write("hata satiri\n")
        text = read(p)
        self.assertIn("merhaba log", text)
        self.assertIn("hata satiri", text)

    def test_log_dosyasi_acilamazsa_hata_vermez(self):
        log = applog.setup(os.path.join(self.tmp, "yok_klasor", "x.log"), redirect_std=False)
        log.info("bu satir sessizce yutulur")

    def test_gitignore_logu_icerir(self):
        self.assertTrue(any(l.strip().startswith("mpanels.log") for l in read(os.path.join(ROOT, ".gitignore")).splitlines()))


class TestSingleInstance(unittest.TestCase):
    def setUp(self):
        self.name = f"MPanels_UnitTest_{os.getpid()}_{int(time.time() * 1000)}"

    def test_ikinci_edinme_reddedilir(self):
        self.assertTrue(winutil.acquire_single_instance(self.name))
        self.assertFalse(winutil.acquire_single_instance(self.name))

    def test_calisan_yokken_uyari_gonderilmez(self):
        self.assertFalse(winutil.signal_running_instance(self.name, retries=1))

    def test_uyari_dinleyiciye_ulasir(self):
        got = threading.Event()
        lis = winutil.start_instance_listener(self.name, got.set)
        try:
            self.assertTrue(winutil.signal_running_instance(self.name, retries=3))
            self.assertTrue(got.wait(2.0), "dinleyici uyarıyı almadı")
            got.clear()
            self.assertTrue(winutil.signal_running_instance(self.name, retries=3))       # tekrar tekrar çalışır
            self.assertTrue(got.wait(2.0))
        finally:
            lis.stop()
            lis.join(2)

    def test_ornek_adi_test_modunda_ayri(self):
        self.assertEqual(mpanels.instance_name(), "MPanels_SingleInstance")
        a = mpanels.instance_name(r"C:\x\deneme")
        self.assertTrue(a.startswith("MPanels_Test_") and a != mpanels.instance_name())
        self.assertEqual(a, mpanels.instance_name(r"c:\X\Deneme"))       # büyük/küçük harf duyarsız
        self.assertNotEqual(a, mpanels.instance_name(r"C:\x\baska"))


class TestLaunchers(unittest.TestCase):
    def test_find_pythonw(self):
        p = winutil.find_pythonw()
        self.assertTrue(p and os.path.isfile(p) and os.path.basename(p).lower() == "pythonw.exe")

    def test_build_bat_icerigi(self):
        t = kur.build_bat(r"C:\Py\pythonw.exe")
        self.assertIn('start "" "C:\\Py\\pythonw.exe" "%~dp0mpanels.py" %*', t)
        self.assertNotIn("python.exe", t)
        self.assertTrue(t.startswith("@echo off"))
        t2 = kur.build_bat(r"C:\Py\pythonw.exe", extra_args='--desktop "D:\\deneme"')
        self.assertIn('"%~dp0mpanels.py" --desktop "D:\\deneme" %*', t2)

    def test_write_bats_gecici_klasore(self):
        with tempfile.TemporaryDirectory() as d:
            paths = kur.write_bats(r"C:\Py\pythonw.exe", app_dir=d, test_desktop=r"D:\mpanels_deneme")
            self.assertEqual([os.path.basename(p) for p in paths], ["M-Panels.bat", "M-Panels-Test.bat"])
            normal, test = (read(p) for p in paths)
            self.assertNotIn("--desktop", normal)
            self.assertIn('--desktop "D:\\mpanels_deneme"', test)

    def test_depodaki_bat_dosyalari(self):
        if not all(os.path.isfile(os.path.join(ROOT, n)) for n in ("M-Panels.bat", "M-Panels-Test.bat")):
            self.skipTest("the launchers are generated per machine (python kur.py --write-bat); not in this checkout")
        pythonw = winutil.find_pythonw()
        for name, test in (("M-Panels.bat", False), ("M-Panels-Test.bat", True)):
            path = os.path.join(ROOT, name)
            self.assertTrue(os.path.isfile(path), name + " yok (python kur.py --write-bat)")
            t = read(path)
            self.assertIn("pythonw.exe", t)
            self.assertIn('"%~dp0mpanels.py"', t)
            self.assertEqual("--desktop" in t, test)
            m = re.search(r'start "" "([^"]+pythonw\.exe)"', t)
            self.assertTrue(m and os.path.isfile(m.group(1)), "bat içindeki pythonw yolu geçerli değil")
            self.assertEqual(os.path.normcase(m.group(1)), os.path.normcase(pythonw))
        self.assertIn("mpanels_deneme", read(os.path.join(ROOT, "M-Panels-Test.bat")))

    def test_kur_target_gercek_yerlere_dokunmaz(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(kur, "write_bats", return_value=[]), \
                mock.patch.object(winutil, "get_startup_dir", side_effect=AssertionError("gerçek Başlangıç klasörü")), \
                mock.patch.object(winutil, "get_real_desktop", side_effect=AssertionError("gerçek masaüstü")):
            kur.main(["--target", d, "--skip-pip"])
            names = sorted(os.listdir(d))
            self.assertEqual(names, ["M Panels (startup).lnk", "M Panels.lnk"])
            pythonw = winutil.find_pythonw()
            for n in names:
                self.assertEqual(os.path.normcase(winutil.resolve_shortcut(os.path.join(d, n))), os.path.normcase(pythonw))

    def test_kur_bayraksiz_kisayol_olusturmaz(self):
        out = io.StringIO()
        with mock.patch.object(kur, "write_bats", return_value=[]), \
                mock.patch.object(winutil, "get_startup_dir", side_effect=AssertionError("gerçek Başlangıç klasörü")), \
                mock.patch.object(winutil, "get_real_desktop", side_effect=AssertionError("gerçek masaüstü")), \
                mock.patch.object(kur, "make_shortcut", side_effect=AssertionError("kısayol")), \
                mock.patch("sys.stdout", out):
            kur.main(["--skip-pip"])
        self.assertIn(strings.KUR_NO_SHORTCUTS, out.getvalue())

    def test_kur_arg_bayraklari(self):
        a = kur.parse_args(["--shortcuts", "--skip-pip", "--write-bat", "--target", "x"])
        self.assertTrue(a.shortcuts and a.skip_pip and a.write_bat and a.target == "x")


class TestIcon(unittest.TestCase):
    """The icon comes from the bundled assets/m_panels.ico (no personal path); a missing or broken file never raises."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mp_ico_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_paketli_ikon_kullanilir(self):
        self.assertEqual(os.path.normcase(winutil.app_icon_path()),
                         os.path.normcase(os.path.join(ROOT, "assets", "m_panels.ico")))
        self.assertFalse(hasattr(theme, "ICON_FILE"))

    def test_dosya_yoksa_hata_yok(self):
        with mock.patch.object(winutil, "app_icon_path", return_value=os.path.join(self.tmp, "yok.ico")):
            for size in (16, 48, 64):
                self.assertEqual(mpanels.app_icon_image(size).size, (size, size))
        with mock.patch.object(os.path, "isfile", return_value=False):
            self.assertIsNone(winutil.app_icon_path())

    def test_bozuk_dosya_hata_vermez(self):
        p = os.path.join(self.tmp, "bozuk.ico")
        with open(p, "wb") as f:
            f.write(b"bu bir ikon degil")
        with mock.patch.object(winutil, "app_icon_path", return_value=p):
            self.assertEqual(mpanels.app_icon_image(32).size, (32, 32))

    def test_ikon_dosyasi_kullanilir(self):
        from PIL import Image
        p = os.path.join(self.tmp, "m-panels.ico")
        Image.new("RGBA", (64, 64), (255, 0, 0, 255)).save(p, sizes=[(16, 16), (32, 32), (64, 64)])
        with mock.patch.object(winutil, "app_icon_path", return_value=p):
            im = mpanels.app_icon_image(48)
        self.assertEqual(im.size, (48, 48))
        self.assertEqual(im.getpixel((24, 24))[:3], (255, 0, 0))

    def test_paketlenmis_yedek_ikon_var(self):
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "assets", "m_panels.ico")))


class TestWindowStyles(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()

    def test_toolwindow_ve_gorev_cubugu(self):
        w = tk.Toplevel(self.root)
        w.update()
        winutil.make_toolwindow(w)
        self.assertTrue(winutil.is_toolwindow(w))
        winutil.show_in_taskbar(w)
        self.assertFalse(winutil.is_toolwindow(w))
        winutil.make_toolwindow(w)
        self.assertTrue(winutil.is_toolwindow(w))
        w.destroy()

    def test_gorunen_pencere_de_gizlenir(self):
        w = tk.Toplevel(self.root)
        w.geometry("100x60+10+10")
        w.deiconify()
        w.update()
        self.assertTrue(w.winfo_viewable())
        winutil.make_toolwindow(w)
        w.update()
        self.assertTrue(winutil.is_toolwindow(w))
        self.assertTrue(w.winfo_viewable(), "pencere gizlendikten sonra yeniden görünür olmalı")
        w.destroy()

    def test_modal_pencereler_gorev_cubugunda_yok(self):
        for dlg in (uiwidgets.PromptDialog(self.root, "t", "p", "x"),
                    uiwidgets.StyleDialog(self.root, "t", theme.style_defaults() and
                                          {"font": "Segoe UI", "size": 9, "color": "#ffffff", "bold": False,
                                           "italic": False}),
                    uiwidgets.FontDialog(self.root, "Segoe UI", 9)):
            dlg.win.update()
            self.assertTrue(winutil.is_toolwindow(dlg.win), type(dlg).__name__)
            dlg.win.destroy()


class TestPromptDialog(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()

    def test_metin(self):
        d = uiwidgets.PromptDialog(self.root, "t", "p", "ilk")
        self.assertEqual(d.var.get(), "ilk")
        d.var.set("yeni ad")
        d.ok()
        self.assertEqual(d.result, "yeni ad")

    def test_tam_sayi_aralik_disi_kabul_edilmez(self):
        d = uiwidgets.PromptDialog(self.root, "t", "p", 12, kind="int", lo=6, hi=72)
        for bad in ("5", "73", "abc", "", "1.5"):
            d.var.set(bad)
            d.ok()
            self.assertIsNone(d.result, bad)
            self.assertTrue(d.win.winfo_exists())
        d.var.set("40")
        d.ok()
        self.assertEqual(d.result, 40)


class TestVersion4(unittest.TestCase):
    def test_surum(self):
        self.assertEqual(version.__version__, "1.1.1")

    def test_pencere_basligi_ve_tepsi_metni_stringsten(self):
        self.assertEqual(strings.SET_TITLE.format(app=strings.APP_NAME, version="0.5.2"), "M Panels v0.5.2 — Settings")
        self.assertEqual(strings.VERSION_LINE.format(app=strings.APP_NAME, version="0.5.2"), "M Panels v0.5.2")


if __name__ == "__main__":
    unittest.main()
