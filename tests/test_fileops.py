"""fileops testleri. HİÇBİR gerçek masaüstü yoluna yazmaz: her test geçici bir 'sahte masaüstü' kullanır.

Çalıştırma:  python -m unittest discover -s tests -v
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fileops  # noqa: E402
import winutil  # noqa: E402

# İkinci sürücü testi için: MPANELS_TEST_OTHER_DRIVE ortam değişkeni, TEMP'ten FARKLI bir sürücüde var olan bir klasörü
# göstermelidir (ör. D:\Projects). Ayarlı değilse test atlanır. Geçici klasör bunun altında açılır, testten sonra silinir.
_OTHER = os.environ.get("MPANELS_TEST_OTHER_DRIVE", "").strip()
OTHER_DRIVE_ROOT = os.path.join(_OTHER, "_mpanels_test_tmp") if _OTHER else None


def touch(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mpanels_test_")
        self.desktop = os.path.join(self.tmp, "Desktop")
        self.public = os.path.join(self.tmp, "PublicDesktop")
        self.outside = os.path.join(self.tmp, "Dev")          # masaüstü dışı klasör
        for d in (self.desktop, self.public, self.outside):
            os.makedirs(d)
        self.ctx = fileops.Ctx(self.desktop, self.public)
        fileops.ensure_panels_root(self.ctx)
        self.assertTrue(fileops.create_panel(self.ctx, "Oyunlar"))
        self.assertTrue(fileops.create_panel(self.ctx, "Araçlar"))
        self.p1 = self.ctx.panel_path("Oyunlar")
        self.p2 = self.ctx.panel_path("Araçlar")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestDrop(Base):
    def test_paneller_klasoru_gizli(self):
        self.assertTrue(winutil.is_hidden(self.ctx.panels_root))

    def test_masaustu_ogesi_tasinir(self):
        src = touch(os.path.join(self.desktop, "a.txt"), "içerik")
        r = fileops.handle_drop(self.ctx, "Oyunlar", src)
        self.assertEqual(r.kind, "moved")
        self.assertFalse(os.path.exists(src))
        self.assertEqual(open(os.path.join(self.p1, "a.txt"), encoding="utf-8").read(), "içerik")

    def test_masaustu_klasoru_tasinir(self):
        d = os.path.join(self.desktop, "Klasör")
        touch(os.path.join(d, "i.txt"))
        r = fileops.handle_drop(self.ctx, "Oyunlar", d)
        self.assertEqual(r.kind, "moved")
        self.assertTrue(os.path.exists(os.path.join(self.p1, "Klasör", "i.txt")))

    def test_masaustu_disi_kisayol(self):
        src = touch(os.path.join(self.outside, "rapor.pdf"))
        r = fileops.handle_drop(self.ctx, "Oyunlar", src)
        self.assertEqual(r.kind, "shortcut")
        self.assertTrue(os.path.exists(src), "kaynak yerinde kalmalı")
        self.assertTrue(os.path.exists(os.path.join(self.p1, "rapor.lnk")))
        self.assertTrue(os.path.samefile(winutil.resolve_shortcut(r.dest), src))

    def test_turkce_karakterli_panel_adinda_kisayol(self):
        """Regresyon: WScript.Shell ANSI olduğundan 'Dış Bağlantılar' içinde .lnk kaydedilemiyordu."""
        self.assertTrue(fileops.create_panel(self.ctx, "Dış Bağlantılar"))
        src = touch(os.path.join(self.outside, "şğüİıöç dosyası.txt"))
        r = fileops.handle_drop(self.ctx, "Dış Bağlantılar", src)
        self.assertEqual(r.kind, "shortcut", r.message)
        self.assertTrue(os.path.exists(r.dest))
        self.assertTrue(os.path.samefile(winutil.resolve_shortcut(r.dest), src))

    def test_masaustu_disi_klasor_kisayol(self):
        d = os.path.join(self.outside, "Proje")
        os.makedirs(d)
        r = fileops.handle_drop(self.ctx, "Oyunlar", d)
        self.assertEqual(r.kind, "shortcut")
        self.assertTrue(os.path.isdir(d))
        self.assertTrue(os.path.exists(os.path.join(self.p1, "Proje.lnk")))

    def test_gercek_masaustu_ogesi_test_modunda_tasinmaz(self):
        """Test masaüstü kullanılırken GERÇEK masaüstünden bırakılan öğe taşınmaz, yalnız kısayol olur."""
        real = winutil.get_real_desktop()
        self.assertNotEqual(fileops.norm(real), fileops.norm(self.desktop))
        cands = [e.path for e in os.scandir(real)
                 if not winutil.is_hidden(e.path) and e.name.lower() != "desktop.ini"]
        if not cands:
            self.skipTest("gerçek masaüstünde öğe yok")
        src = cands[0]
        before = sorted(os.listdir(real))
        r = fileops.handle_drop(self.ctx, "Oyunlar", src)
        self.assertEqual(r.kind, "shortcut", r.message)
        self.assertEqual(sorted(os.listdir(real)), before, "gerçek masaüstü değişmemeli")
        self.assertTrue(os.path.lexists(src))

    def test_ad_cakismasi_ust_uste_yazmaz(self):
        touch(os.path.join(self.p1, "a.txt"), "ESKİ")
        src = touch(os.path.join(self.desktop, "a.txt"), "YENİ")
        r = fileops.handle_drop(self.ctx, "Oyunlar", src)
        self.assertEqual(os.path.basename(r.dest), "a (2).txt")
        self.assertEqual(open(os.path.join(self.p1, "a.txt"), encoding="utf-8").read(), "ESKİ")
        self.assertEqual(open(r.dest, encoding="utf-8").read(), "YENİ")
        src3 = touch(os.path.join(self.desktop, "a.txt"), "ÜÇ")
        r3 = fileops.handle_drop(self.ctx, "Oyunlar", src3)
        self.assertEqual(os.path.basename(r3.dest), "a (3).txt")

    def test_ayni_panele_birakma_islem_yok(self):
        src = touch(os.path.join(self.p1, "a.txt"))
        r = fileops.handle_drop(self.ctx, "Oyunlar", src)
        self.assertEqual(r.kind, "skip")
        self.assertTrue(os.path.exists(src))

    def test_paneller_arasi_tasima(self):
        src = touch(os.path.join(self.p1, "a.txt"), "z")
        r = fileops.handle_drop(self.ctx, "Araçlar", src)
        self.assertEqual(r.kind, "moved")
        self.assertFalse(os.path.exists(src))
        self.assertTrue(os.path.exists(os.path.join(self.p2, "a.txt")))

    def test_ortak_masaustu_lnk_kopyalanir_asil_kalir(self):
        lnk = os.path.join(self.public, "Uygulama.lnk")
        winutil.create_shortcut(lnk, os.path.join(self.outside, "x.exe"))
        r = fileops.handle_drop(self.ctx, "Oyunlar", lnk)
        self.assertEqual(r.kind, "copied_shortcut")
        self.assertTrue(os.path.exists(lnk), "ortak masaüstündeki asıl kalmalı")
        self.assertTrue(os.path.exists(os.path.join(self.p1, "Uygulama.lnk")))
        self.assertIn("copy", r.message)

    def test_ortak_masaustu_dosya_kisayol_olur(self):
        f = touch(os.path.join(self.public, "bilgi.txt"))
        r = fileops.handle_drop(self.ctx, "Oyunlar", f)
        self.assertEqual(r.kind, "copied_shortcut")
        self.assertTrue(os.path.exists(f))

    def test_farkli_surucu_tasinmaz_kisayol(self):
        """Hedef farklı sürücüdeyse taşıma yok. (same_drive yanlış döndürülerek dal zorlanır.)"""
        src = touch(os.path.join(self.desktop, "b.txt"))
        orig = fileops.same_drive
        fileops.same_drive = lambda a, b: False
        try:
            r = fileops.handle_drop(self.ctx, "Oyunlar", src)
        finally:
            fileops.same_drive = orig
        self.assertEqual(r.kind, "shortcut")
        self.assertTrue(os.path.exists(src), "kaynak taşınmamalı")

    def test_gercek_ikinci_surucu_kaynak(self):
        if not OTHER_DRIVE_ROOT or not os.path.isdir(os.path.dirname(OTHER_DRIVE_ROOT)):
            self.skipTest("MPANELS_TEST_OTHER_DRIVE ayarlı değil / klasör yok")
        if fileops.same_drive(self.tmp, OTHER_DRIVE_ROOT):
            self.skipTest("test klasörü ile MPANELS_TEST_OTHER_DRIVE aynı sürücü")
        os.makedirs(OTHER_DRIVE_ROOT, exist_ok=True)
        d = tempfile.mkdtemp(dir=OTHER_DRIVE_ROOT)
        try:
            src = touch(os.path.join(d, "uzak.txt"))
            r = fileops.handle_drop(self.ctx, "Oyunlar", src)
            self.assertEqual(r.kind, "shortcut")
            self.assertTrue(os.path.exists(src))
            self.assertTrue(os.path.exists(r.dest))
        finally:
            shutil.rmtree(OTHER_DRIVE_ROOT, ignore_errors=True)

    def test_panel_klasorleri_reddedilir(self):
        for bad in (self.ctx.panels_root, self.p2, self.desktop):
            r = fileops.handle_drop(self.ctx, "Oyunlar", bad)
            self.assertEqual(r.kind, "refused", bad)
            self.assertTrue(os.path.isdir(bad))
        # panelin içine, o panelin üst klasörünü de koyamaz
        self.assertEqual(fileops.handle_drop(self.ctx, "Oyunlar", self.tmp).kind, "refused")

    def test_kilitli_dosya_zorlanmaz(self):
        import win32file
        src = touch(os.path.join(self.desktop, "kilit.txt"))
        h = win32file.CreateFile(src, 0x80000000, 0, None, 3, 0, None)   # GENERIC_READ, paylaşım yok
        try:
            r = fileops.handle_drop(self.ctx, "Oyunlar", src)
            self.assertFalse(r.ok)
            self.assertEqual(r.kind, "error")
            self.assertIn("locked", r.message)
            self.assertTrue(os.path.exists(src), "kilitli dosya yerinde kalmalı")
            self.assertFalse(os.path.exists(os.path.join(self.p1, "kilit.txt")))
        finally:
            h.Close()


class TestPanelLifecycle(Base):
    def test_masaustune_geri_cikar(self):
        it = touch(os.path.join(self.p1, "a.txt"), "q")
        r = fileops.return_to_desktop(self.ctx, it)
        self.assertEqual(r.kind, "moved")
        self.assertTrue(os.path.exists(os.path.join(self.desktop, "a.txt")))
        self.assertFalse(os.path.exists(it))

    def test_geri_cikarken_cakisma(self):
        touch(os.path.join(self.desktop, "a.txt"), "MASAÜSTÜ")
        it = touch(os.path.join(self.p1, "a.txt"), "PANEL")
        r = fileops.return_to_desktop(self.ctx, it)
        self.assertEqual(os.path.basename(r.dest), "a (2).txt")
        self.assertEqual(open(os.path.join(self.desktop, "a.txt"), encoding="utf-8").read(), "MASAÜSTÜ")

    def test_panel_kaldir_icerik_geri_klasor_silinecege(self):
        touch(os.path.join(self.p1, "a.txt"), "1")
        touch(os.path.join(self.p1, "k", "b.txt"), "2")
        touch(os.path.join(self.desktop, "a.txt"), "VAR")      # çakışma
        r = fileops.remove_panel(self.ctx, "Oyunlar")
        self.assertTrue(r.ok, r.message)
        self.assertEqual(open(os.path.join(self.desktop, "a.txt"), encoding="utf-8").read(), "VAR")
        self.assertEqual(open(os.path.join(self.desktop, "a (2).txt"), encoding="utf-8").read(), "1")
        self.assertTrue(os.path.exists(os.path.join(self.desktop, "k", "b.txt")))
        self.assertFalse(os.path.exists(self.p1))
        # boş klasör silinmedi, _silinecek'e taşındı
        moved = os.path.join(self.ctx.trash, "Oyunlar")
        self.assertTrue(os.path.isdir(moved))
        self.assertEqual(os.listdir(moved), [])
        self.assertNotIn("Oyunlar", fileops.list_panel_folders(self.ctx))
        self.assertNotIn("_silinecek", fileops.list_panel_folders(self.ctx))

    def test_panel_kaldir_ayni_ad_iki_kez(self):
        fileops.remove_panel(self.ctx, "Oyunlar")
        fileops.create_panel(self.ctx, "Oyunlar")
        r = fileops.remove_panel(self.ctx, "Oyunlar")
        self.assertTrue(r.ok)
        self.assertEqual(sorted(os.listdir(self.ctx.trash)), ["Oyunlar", "Oyunlar (2)"])

    def test_panel_kaldir_kilitli_oge_paneli_yerinde_birakir(self):
        import win32file
        a = touch(os.path.join(self.p1, "a.txt"))
        b = touch(os.path.join(self.p1, "b.txt"))
        h = win32file.CreateFile(b, 0x80000000, 0, None, 3, 0, None)
        try:
            r = fileops.remove_panel(self.ctx, "Oyunlar")
        finally:
            h.Close()
        self.assertFalse(r.ok)
        self.assertTrue(os.path.isdir(self.p1), "panel kaldırılmamalı")
        self.assertTrue(os.path.exists(b), "kilitli öğe panelde kalmalı")

    def test_panel_yeniden_adlandir_klasor_adi_degisir(self):
        touch(os.path.join(self.p1, "a.txt"))
        r = fileops.rename_panel(self.ctx, "Oyunlar", "Oyunlarım")
        self.assertTrue(r.ok)
        self.assertFalse(os.path.exists(self.p1))
        self.assertTrue(os.path.exists(os.path.join(self.ctx.panel_path("Oyunlarım"), "a.txt")))

    def test_panel_adlandirma_cakisma_ve_gecersiz(self):
        self.assertFalse(fileops.rename_panel(self.ctx, "Oyunlar", "Araçlar").ok)
        self.assertTrue(os.path.isdir(self.p1) and os.path.isdir(self.p2))
        for bad in ("", "a/b", "x.", "CON", "_silinecek", "a?b"):
            self.assertFalse(fileops.create_panel(self.ctx, bad).ok, bad)

    def test_oge_yeniden_adlandir(self):
        a = touch(os.path.join(self.p1, "a.txt"))
        touch(os.path.join(self.p1, "b.txt"))
        self.assertFalse(fileops.rename_item(a, "b.txt").ok)       # üzerine yazma yok
        self.assertTrue(os.path.exists(a))
        r = fileops.rename_item(a, "c.txt")
        self.assertTrue(r.ok and os.path.exists(os.path.join(self.p1, "c.txt")))
        lnk = os.path.join(self.p1, "k.lnk")
        winutil.create_shortcut(lnk, self.outside)
        r = fileops.rename_item(lnk, "Yeni ad")
        self.assertTrue(os.path.exists(os.path.join(self.p1, "Yeni ad.lnk")))


class TestListing(Base):
    def test_bozuk_kisayol_isaretlenir_silinmez(self):
        ok_t = touch(os.path.join(self.outside, "var.txt"))
        good = os.path.join(self.p1, "iyi.lnk")
        bad = os.path.join(self.p1, "bozuk.lnk")
        winutil.create_shortcut(good, ok_t)
        winutil.create_shortcut(bad, os.path.join(self.outside, "yok.txt"))
        items = {i.name: i for i in fileops.list_items(self.p1)}
        self.assertFalse(items["iyi"].broken)
        self.assertTrue(items["bozuk"].broken)
        self.assertTrue(os.path.exists(bad), "bozuk kısayol silinmemeli")

    def test_gizli_ve_desktop_ini_gosterilmez_ve_sira(self):
        for n in ("c.txt", "a.txt", "b.txt"):
            touch(os.path.join(self.p1, n))
        touch(os.path.join(self.p1, "desktop.ini"))
        names = [i.name for i in fileops.list_items(self.p1)]
        self.assertEqual(names, ["a.txt", "b.txt", "c.txt"])
        names = [i.name for i in fileops.list_items(self.p1, order=["c.txt", "b.txt"])]
        self.assertEqual(names, ["c.txt", "b.txt", "a.txt"])

    def test_ikon_uretilir(self):
        f = touch(os.path.join(self.p1, "a.txt"))
        for size in (24, 32, 48):
            img = winutil.file_icon(f, size)
            self.assertIsNotNone(img)
            self.assertEqual(img.size, (size, size))
            self.assertGreater(img.getchannel("A").getextrema()[1], 0)
        self.assertIsNotNone(winutil.recycle_bin_icon(32))


class TestTestModeGuard(unittest.TestCase):
    def test_test_modu_gercek_masaustunu_reddeder(self):
        import mpanels
        real = winutil.get_real_desktop()
        for bad in (real, os.path.join(real, "alt"), os.path.dirname(real)):
            with self.assertRaises(SystemExit):
                mpanels.build_context(mpanels.parse_args(["--desktop", bad]))

    def test_test_modu_gecici_klasorde_calisir(self):
        import mpanels
        d = tempfile.mkdtemp(prefix="mpanels_guard_")
        try:
            ctx, data, test = mpanels.build_context(mpanels.parse_args(["--desktop", os.path.join(d, "D")]))
            self.assertTrue(test)
            self.assertTrue(fileops.is_inside(ctx.desktop, d))
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestNoDeleteInApp(unittest.TestCase):
    def test_uygulama_kodunda_silme_cagrisi_yok(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        bad = ("os.remove", "os.unlink", "shutil.rmtree", "os.rmdir", "os.removedirs", "send2trash")
        for fn in ("fileops.py", "winutil.py", "mpanels.py", "kur.py"):
            p = os.path.join(root, fn)
            if not os.path.exists(p):
                continue
            src = open(p, encoding="utf-8").read()
            for b in bad:
                self.assertNotIn(b, src, f"{fn} içinde {b}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
