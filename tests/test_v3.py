"""Sürüm 3 birim testleri: tema, stil çevirisi, not biçimi (JSON), eski .txt içe alma, zengin metin, font arama,
sürüm numarası. Gerçek masaüstüne DOKUNMAZ (geçici klasör; Tk pencereleri gizli).

Çalıştırma:  python -m unittest discover -s tests -v
"""
import os
import re
import shutil
import sys
import tempfile
import tkinter as tk
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import fileops  # noqa: E402
import notefmt  # noqa: E402
import richtext  # noqa: E402
import theme  # noqa: E402
import uiwidgets  # noqa: E402
import version  # noqa: E402


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestTheme(unittest.TestCase):
    def test_eski_config_ikisine_ayni_deger(self):
        d = {"font_size": 12, "text_color": "#112233", "color": "#ff0000"}
        theme.migrate_style(d)
        self.assertEqual((d["title_size"], d["content_size"]), (12, 12))
        self.assertEqual((d["title_color"], d["content_color"]), ("#112233", "#112233"))
        self.assertNotIn("font_size", d)
        self.assertNotIn("text_color", d)
        self.assertEqual(d["color"], "#ff0000")

    def test_yeni_anahtarlar_ezilmez(self):
        d = {"font_size": 12, "title_size": 20}
        theme.migrate_style(d)
        self.assertEqual((d["title_size"], d["content_size"]), (20, 12))

    def test_eski_config_yoksa_dokunmaz(self):
        d = {"color": "#fff000"}
        theme.migrate_style(d)
        self.assertEqual(d, {"color": "#fff000"})

    def test_baslik_eskisi_gibi_kalin_icerik_degil(self):
        d = theme.sanitize_style(theme.migrate_style({"font_size": 9, "text_color": "#e8e8ec"}))
        self.assertTrue(d["title_bold"])
        self.assertFalse(d["content_bold"])
        self.assertEqual((d["title_font"], d["content_font"]), ("Segoe UI", "Segoe UI"))

    def test_dogrulama(self):
        d = theme.sanitize_style({"title_size": "abc", "content_size": 500, "title_color": "kırmızı",
                                  "content_font": "  ", "title_bold": "x", "content_italic": 1})
        self.assertEqual(d["title_size"], 9)
        self.assertEqual(d["content_size"], 72)
        self.assertEqual(d["title_color"], theme.TEXT_COLOR)
        self.assertEqual(d["content_font"], theme.FONT_FAMILY)
        self.assertTrue(d["title_bold"])                  # bozuk değer → varsayılan (başlık kalın)
        self.assertTrue(d["content_italic"])

    def test_boyut_siniri(self):
        self.assertEqual((theme.SIZE_MIN, theme.SIZE_MAX), (6, 72))
        self.assertEqual(theme.normalize_font_size(1), 6)
        self.assertEqual(theme.normalize_font_size("11,6"), 12)
        self.assertEqual(theme.normalize_font_size(None), 9)
        self.assertEqual(theme.normalize_font_size(True), 9)

    def test_stil_anahtarlari_ayri(self):
        k = theme.STYLE_KEYS
        self.assertEqual(len(k), 10)
        self.assertEqual(sum(x.startswith("title_") for x in k), 5)
        self.assertEqual(sum(x.startswith("content_") for x in k), 5)

    def test_tk_font_spec(self):
        st = {"font": "Arial", "size": 11, "color": "#ffffff", "bold": True, "italic": True}
        self.assertEqual(theme.tk_font_spec(st), ("Arial", 11, "bold", "italic"))
        st.update(bold=False, italic=False)
        self.assertEqual(theme.tk_font_spec(st), ("Arial", 11, "normal"))

    def test_renk_yardimcilari_ve_olculer(self):
        self.assertEqual(theme.hex_rgb("#010203"), (1, 2, 3))
        self.assertEqual(theme.blend("#000000", "#ffffff", 0.5), "#7f7f7f")
        self.assertTrue(theme.is_hex_color("#a1B2c3") and not theme.is_hex_color("a1b2c3"))
        self.assertGreater(theme.HEAD_H, 0)
        self.assertEqual(theme.make_bg(100, 60, "#3aa0ff").size, (100, 60))

    def test_tema_degerleri_tek_modulde(self):
        """Renk (tırnaklı #rrggbb) ve font adı yalnız theme.py'de yazılır; diğer modüller theme'den okur."""
        for n in os.listdir(ROOT):
            if not n.endswith(".py") or n in ("theme.py", "kur.py"):
                continue
            src = read(os.path.join(ROOT, n))
            self.assertNotRegex(src, r"[\"']#[0-9a-fA-F]{6}[\"']", n + ": sabit renk")
            self.assertNotIn("Segoe UI", src, n + ": sabit font adı")
        self.assertRegex(read(os.path.join(ROOT, "theme.py")), r"HEAD_H\s*=")

    def test_theme_tkinter_import_etmez(self):
        src = read(os.path.join(ROOT, "theme.py"))
        self.assertNotRegex(src, r"(?m)^\s*(import|from)\s+tkinter")


class TestNoteFormat(unittest.TestCase):
    def test_gecersiz_aralik_atilir(self):
        sp = [{"start": 5, "end": 5, "bold": True}, {"start": "a", "end": 3, "bold": True},
              {"start": 0, "end": 4}, {"start": 0, "end": 4, "bold": "evet"}, "x",
              {"start": 0, "end": 4, "bold": True}]
        self.assertEqual(notefmt.clean_spans(sp), [{"start": 0, "end": 4, "bold": True}])

    def test_bitisik_ayni_birlesir_farkli_birlesmez(self):
        sp = [{"start": 0, "end": 3, "bold": True}, {"start": 3, "end": 6, "bold": True},
              {"start": 6, "end": 8, "italic": True}]
        self.assertEqual(notefmt.clean_spans(sp), [{"start": 0, "end": 6, "bold": True},
                                                   {"start": 6, "end": 8, "italic": True}])

    def test_cakisma_duzeltilir_ve_kirpilir(self):
        sp = [{"start": 0, "end": 10, "bold": True}, {"start": 5, "end": 15, "italic": True}]
        r = notefmt.clean_spans(sp, limit=12)
        self.assertEqual([(x["start"], x["end"]) for x in r], [(0, 10), (10, 12)])

    def test_ozellik_dogrulama(self):
        r = notefmt.clean_spans([{"start": 0, "end": 2, "color": "RED", "size": 999, "font": " Arial "}])
        self.assertEqual(r, [{"start": 0, "end": 2, "size": 72, "font": "Arial"}])
        r = notefmt.clean_spans([{"start": 0, "end": 2, "color": "#FF00AA"}])
        self.assertEqual(r[0]["color"], "#ff00aa")

    def test_json_gidis_donus(self):
        spans = [{"start": 1, "end": 4, "bold": True, "color": "#ff0000", "font": "Arial", "size": 14,
                  "italic": True, "underline": True}]
        raw = notefmt.dumps("çğıöşü\n  satır", spans)
        text, sp = notefmt.loads(raw)
        self.assertEqual(text, "çğıöşü\n  satır")
        self.assertEqual(sp, spans)
        self.assertIn("çğıöşü", raw)                      # \u kaçışı yok, okunabilir

    def test_bozuk_json(self):
        for raw in ("", "{", "[]", '{"text": 5}', '{"spans": []}'):
            with self.assertRaises(ValueError):
                notefmt.loads(raw)

    def test_spans_yoksa_bos(self):
        self.assertEqual(notefmt.loads('{"text": "a"}'), ("a", []))


class TestNoteFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mpanels_v3_")
        self.data = os.path.join(self.tmp, "veri")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_json_biçim_yazilip_okunur(self):
        sp = [{"start": 0, "end": 3, "bold": True}]
        self.assertTrue(fileops.write_note(self.data, "N", "abcdef", sp))
        nd = fileops.read_note(self.data, "N")
        self.assertEqual((nd.text, nd.spans, nd.imported, nd.warning), ("abcdef", sp, False, ""))
        self.assertTrue(fileops.note_path(self.data, "N").endswith("N.json"))

    def test_eski_txt_ice_alinir_ve_cope_tasinir(self):
        os.makedirs(fileops.notes_dir(self.data))
        old = fileops.legacy_note_path(self.data, "Eski")
        with open(old, "w", encoding="utf-8", newline="") as f:
            f.write("düz metin çğı\nikinci")
        nd = fileops.read_note(self.data, "Eski")
        self.assertTrue(nd.imported)
        self.assertEqual((nd.text, nd.spans, nd.warning), ("düz metin çğı\nikinci", [], ""))
        self.assertTrue(os.path.exists(fileops.note_path(self.data, "Eski")))
        self.assertFalse(os.path.exists(old))                                  # yerinde yok
        trashed = os.path.join(fileops.notes_trash(self.data), "Eski.txt")
        self.assertEqual(read(trashed), "düz metin çğı\nikinci")                # silinmedi, taşındı
        # ikinci okuma: artık JSON, tekrar içe alma yok
        nd2 = fileops.read_note(self.data, "Eski")
        self.assertFalse(nd2.imported)
        self.assertEqual(nd2.text, "düz metin çğı\nikinci")

    def test_icer_alma_cop_adi_cakisirsa_ezmez(self):
        os.makedirs(fileops.notes_trash(self.data))
        with open(os.path.join(fileops.notes_trash(self.data), "Eski.txt"), "w", encoding="utf-8") as f:
            f.write("önceki çöp")
        with open(fileops.legacy_note_path(self.data, "Eski"), "w", encoding="utf-8") as f:
            f.write("yeni")
        fileops.read_note(self.data, "Eski")
        kept = sorted(read(os.path.join(fileops.notes_trash(self.data), n))
                      for n in os.listdir(fileops.notes_trash(self.data)))
        self.assertEqual(kept, ["yeni", "önceki çöp"])

    def test_bozuk_json_yok_edilmez_cope_tasinir(self):
        os.makedirs(fileops.notes_dir(self.data))
        jp = fileops.note_path(self.data, "B")
        with open(jp, "w", encoding="utf-8") as f:
            f.write("{bozuk")
        nd = fileops.read_note(self.data, "B")
        self.assertEqual(nd.text, "")
        self.assertIn("could not be read", nd.warning)
        self.assertFalse(os.path.exists(jp))
        self.assertEqual(read(os.path.join(fileops.notes_trash(self.data), "B.json")), "{bozuk")

    def test_json_ve_txt_ikisi_varsa_json_kazanir_txt_yerinde(self):
        fileops.write_note(self.data, "N", "json metni", [])
        with open(fileops.legacy_note_path(self.data, "N"), "w", encoding="utf-8") as f:
            f.write("txt metni")
        self.assertEqual(fileops.read_note(self.data, "N").text, "json metni")
        self.assertTrue(os.path.exists(fileops.legacy_note_path(self.data, "N")))

    def test_olusturma_eski_txt_adiyla_cakisirsa_reddeder(self):
        os.makedirs(fileops.notes_dir(self.data))
        with open(fileops.legacy_note_path(self.data, "N"), "w", encoding="utf-8") as f:
            f.write("x")
        self.assertFalse(fileops.create_note(self.data, "N").ok)

    def test_yeniden_adlandir_ve_kaldir_json_ile_calisir(self):
        fileops.write_note(self.data, "A", "metin", [{"start": 0, "end": 2, "italic": True}])
        self.assertTrue(fileops.rename_note(self.data, "A", "B"))
        nd = fileops.read_note(self.data, "B")
        self.assertEqual((nd.text, len(nd.spans)), ("metin", 1))
        r = fileops.remove_note(self.data, "B")
        self.assertTrue(r.ok)
        self.assertTrue(r.dest.endswith(".json") and os.path.exists(r.dest))

    def test_ust_uste_yazma_gecici_dosya_birakmaz(self):
        for i in range(3):
            fileops.write_note(self.data, "N", f"v{i}", [])
        self.assertEqual(os.listdir(fileops.notes_dir(self.data)), ["N.json"])


class TestFontList(unittest.TestCase):
    FONTS = ["Arial", "Arial Narrow", "Segoe UI", "Çalışkan", "İstanbul Sans", "Times New Roman"]

    def test_arama(self):
        f = uiwidgets.filter_fonts
        self.assertEqual(f(self.FONTS, ""), self.FONTS)
        self.assertEqual(f(self.FONTS, "arial"), ["Arial", "Arial Narrow"])
        self.assertEqual(f(self.FONTS, "NEW"), ["Times New Roman"])
        self.assertEqual(f(self.FONTS, "istanbul"), ["İstanbul Sans"])
        self.assertEqual(f(self.FONTS, "çal"), ["Çalışkan"])
        self.assertEqual(f(self.FONTS, "yok"), [])

    def test_temizleme(self):
        r = uiwidgets.clean_families(["Arial", "arial", "@MS Gothic", "", "Calibri", "Arial"])
        self.assertEqual(r, ["Arial", "Calibri"])

    def test_gercek_liste_bos_degil(self):
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("Tk yok")
        root.withdraw()
        try:
            fam = uiwidgets.list_fonts(root)
        finally:
            root.destroy()
        self.assertTrue(len(fam) > 5)
        self.assertFalse(any(x.startswith("@") for x in fam))
        self.assertEqual(len(fam), len({x.casefold() for x in fam}))


class TestVersion(unittest.TestCase):
    def test_numara_bicimi(self):
        self.assertRegex(version.__version__, r"^\d+\.\d+\.\d+$")

    def test_surum_0_5_1(self):
        self.assertEqual(version.__version__, "1.1.1")

    def test_notlar_md_surum_gecmisinde_guncel_surum_var(self):
        if not os.path.isfile(os.path.join(ROOT, "NOTLAR.md")):
            self.skipTest("NOTLAR.md is not part of the public repository")
        notes = read(os.path.join(ROOT, "NOTLAR.md"))
        self.assertIn("Sürüm geçmişi", notes)
        hist = notes.split("Sürüm geçmişi", 1)[1]
        self.assertRegex(hist, r"(?m)^\s*-\s*\**v?%s" % re.escape(version.__version__))

    def test_sürüm_tek_yerde_tanimli(self):
        hits = []
        for n in os.listdir(ROOT):
            if n.endswith(".py"):
                if re.search(r"__version__\s*=", read(os.path.join(ROOT, n))):
                    hits.append(n)
        self.assertEqual(hits, ["version.py"])


class TestRichText(unittest.TestCase):
    BASE = {"font": "Segoe UI", "size": 9, "bold": False, "italic": False}

    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError:
            raise unittest.SkipTest("Tk yok")
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.t = tk.Text(self.root)
        self.base = dict(self.BASE)
        self.r = richtext.RichText(self.t, lambda: self.base)

    def select(self, a, b):
        self.t.tag_remove("sel", "1.0", "end")
        self.t.tag_add("sel", f"1.0+{a}c", f"1.0+{b}c")

    def test_yukle_kaydet_gidis_donus(self):
        spans = [{"start": 0, "end": 3, "bold": True, "color": "#ff0000"},
                 {"start": 5, "end": 9, "italic": True, "underline": True, "font": "Arial", "size": 14}]
        self.r.load("çğı öşü\nsatır2", spans)
        text, sp = self.r.dump()
        self.assertEqual(text, "çğı öşü\nsatır2")
        self.assertEqual(sp, spans)

    def test_aralik_metin_disina_tasarsa_kirpilir(self):
        self.r.load("abc", [{"start": 1, "end": 99, "bold": True}, {"start": 50, "end": 60, "italic": True}])
        self.assertEqual(self.r.dump()[1], [{"start": 1, "end": 3, "bold": True}])

    def test_kalin_ac_kapat(self):
        self.r.load("merhaba dünya", [])
        self.select(0, 7)
        self.assertTrue(self.r.toggle("bold"))
        self.assertEqual(self.r.dump()[1], [{"start": 0, "end": 7, "bold": True}])
        self.assertTrue(self.r.effective("1.0")["bold"])
        self.assertFalse(self.r.effective("1.0+8c")["bold"])
        self.r.toggle("bold")
        self.assertEqual(self.r.dump()[1], [])

    def test_kismen_kalinsa_hepsi_kalin_olur(self):
        self.r.load("abcdef", [{"start": 0, "end": 2, "bold": True}])
        self.select(0, 6)
        self.r.toggle("bold")
        self.assertEqual(self.r.dump()[1], [{"start": 0, "end": 6, "bold": True}])

    def test_italik_altcizili_renk_font_boyut_birlesir(self):
        self.r.load("abcdefgh", [])
        self.select(2, 6)
        self.r.toggle("italic")
        self.r.toggle("underline")
        self.r.set_color("#00ff00")
        self.r.set_font("Arial")
        self.r.set_size(20)
        self.assertEqual(self.r.dump()[1], [{"start": 2, "end": 6, "italic": True, "underline": True,
                                             "color": "#00ff00", "font": "Arial", "size": 20}])
        eff = self.r.effective("1.0+3c")
        self.assertEqual((eff["font"], eff["size"], eff["italic"]), ("Arial", 20, True))
        self.assertEqual(self.r.effective("1.0+1c")["size"], 9)

    def test_ust_uste_biçim_yalniz_secimi_degistirir(self):
        self.r.load("abcdefgh", [{"start": 0, "end": 8, "bold": True}])
        self.select(2, 4)
        self.r.set_color("#112233")
        self.assertEqual(self.r.dump()[1], [
            {"start": 0, "end": 2, "bold": True},
            {"start": 2, "end": 4, "bold": True, "color": "#112233"},
            {"start": 4, "end": 8, "bold": True}])

    def test_bicimi_temizle(self):
        self.r.load("abcdef", [{"start": 0, "end": 6, "bold": True, "color": "#ff0000", "size": 20}])
        self.select(1, 3)
        self.r.clear_format()
        self.assertEqual(self.r.dump()[1], [{"start": 0, "end": 1, "bold": True, "color": "#ff0000", "size": 20},
                                            {"start": 3, "end": 6, "bold": True, "color": "#ff0000", "size": 20}])

    def test_secim_yoksa_islem_yok(self):
        self.r.load("abc", [])
        self.assertIsNone(self.r.selection())
        self.assertFalse(self.r.toggle("bold"))
        self.assertEqual(self.r.dump()[1], [])

    def test_taban_kalinsa_toggle_italik_gibi_calisir(self):
        self.base["bold"] = True
        self.r.load("abcd", [])
        self.select(0, 4)
        self.r.toggle("bold")                      # taban kalın → kapatır (açık geçersiz kılma False)
        self.assertEqual(self.r.dump()[1], [{"start": 0, "end": 4, "bold": False}])
        self.assertFalse(self.r.effective("1.0")["bold"])
        self.r.toggle("bold")                      # tekrar: tabana döner → span yok
        self.assertEqual(self.r.dump()[1], [])

    def test_taban_font_degisince_bicimli_kisim_takip_eder(self):
        self.r.load("abcd", [{"start": 0, "end": 2, "bold": True}])
        self.base["size"] = 16
        self.r.restyle()
        self.assertEqual(self.r.effective("1.0")["size"], 16)
        tag = [n for n in self.t.tag_names() if n.startswith("fmt:")][0]
        self.assertIn("16", str(self.t.tag_cget(tag, "font")))

    def test_yeniden_yukle_eski_etiketleri_temizler(self):
        self.r.load("abc", [{"start": 0, "end": 3, "bold": True}])
        self.r.load("xyz", [])
        self.assertEqual(self.r.dump(), ("xyz", []))

    def test_dosya_gidis_donus_pencereyle(self):
        tmp = tempfile.mkdtemp(prefix="mpanels_rt_")
        try:
            self.r.load("Merhaba çğı\nDünya", [{"start": 0, "end": 7, "bold": True, "color": "#ff9a3c"}])
            text, sp = self.r.dump()
            fileops.write_note(tmp, "R", text, sp)
            nd = fileops.read_note(tmp, "R")
            t2 = tk.Text(self.root)
            r2 = richtext.RichText(t2, lambda: self.base)
            r2.load(nd.text, nd.spans)
            self.assertEqual(r2.dump(), (text, sp))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
