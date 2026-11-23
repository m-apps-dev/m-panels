"""Sürüm 2 birim testleri: not dosyaları, ikon boyutu çevirisi, masaüstü ikonu gizleme mantığı.
Gerçek masaüstüne/Explorer'a DOKUNMAZ: geçici klasör + sahte arka uç.

Çalıştırma:  python -m unittest discover -s tests -v
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import deskicons  # noqa: E402
import fileops  # noqa: E402
import mpanels  # noqa: E402


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestIconSize(unittest.TestCase):
    def test_eski_degerler_ayni_kalir(self):
        for v in (24, 32, 48):
            self.assertEqual(mpanels.normalize_icon_size(v), v)

    def test_metin_ve_ondalik(self):
        self.assertEqual(mpanels.normalize_icon_size("48"), 48)
        self.assertEqual(mpanels.normalize_icon_size(" 40 "), 40)
        self.assertEqual(mpanels.normalize_icon_size(33.6), 34)

    def test_aralik_kirpilir(self):
        self.assertEqual(mpanels.normalize_icon_size(2), 16)
        self.assertEqual(mpanels.normalize_icon_size(500), 128)
        self.assertEqual(mpanels.normalize_icon_size(-5), 16)

    def test_bozuk_deger_varsayilan(self):
        for v in (None, "", "abc", True, [], {}):
            self.assertEqual(mpanels.normalize_icon_size(v), 32)

    def test_sinirlar(self):
        self.assertEqual((mpanels.ICON_MIN, mpanels.ICON_MAX, mpanels.ICON_DEFAULT), (16, 128, 32))


class TestNotes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mpanels_note_")
        self.data = os.path.join(self.tmp, "veri")
        self.desk = os.path.join(self.tmp, "Desktop")
        os.makedirs(self.desk)
        self.ctx = fileops.Ctx(self.desk)
        fileops.ensure_panels_root(self.ctx)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_yaz_oku_turkce_ve_satir_sonu(self):
        self.assertTrue(fileops.create_note(self.data, "Yapılacaklar"))
        txt = "çğıöşü ÇĞİÖŞÜ\nikinci satır\n\n  boşluk"
        self.assertTrue(fileops.write_note(self.data, "Yapılacaklar", txt))
        self.assertEqual(fileops.read_note(self.data, "Yapılacaklar").text, txt)
        self.assertTrue(fileops.note_path(self.data, "Yapılacaklar").startswith(self.data))

    def test_ustune_yazma_gecici_dosya_kalmaz(self):
        fileops.create_note(self.data, "N")
        fileops.write_note(self.data, "N", "bir")
        fileops.write_note(self.data, "N", "iki")
        self.assertEqual(fileops.read_note(self.data, "N").text, "iki")
        self.assertEqual(sorted(os.listdir(fileops.notes_dir(self.data))), ["N.json"])

    def test_olmayan_not_bos_okunur(self):
        self.assertEqual(fileops.read_note(self.data, "Yok").text, "")

    def test_ayni_ad_ikinci_kez_olusmaz_ve_icerik_korunur(self):
        fileops.create_note(self.data, "N")
        fileops.write_note(self.data, "N", "önemli")
        r = fileops.create_note(self.data, "N")
        self.assertFalse(r.ok)
        self.assertEqual(fileops.read_note(self.data, "N").text, "önemli")

    def test_gecersiz_ad(self):
        self.assertFalse(fileops.create_note(self.data, "a/b").ok)
        self.assertFalse(fileops.create_note(self.data, "  ").ok)

    def test_yeniden_adlandir(self):
        fileops.create_note(self.data, "Eski")
        fileops.write_note(self.data, "Eski", "metin")
        self.assertTrue(fileops.rename_note(self.data, "Eski", "Yeni"))
        self.assertEqual(fileops.read_note(self.data, "Yeni").text, "metin")
        self.assertFalse(os.path.exists(fileops.note_path(self.data, "Eski")))

    def test_yeniden_adlandir_cakisma_reddedilir(self):
        fileops.create_note(self.data, "A")
        fileops.create_note(self.data, "B")
        fileops.write_note(self.data, "B", "b")
        self.assertFalse(fileops.rename_note(self.data, "A", "B").ok)
        self.assertEqual(fileops.read_note(self.data, "B").text, "b")

    def test_kaldir_silmez_tasir(self):
        fileops.create_note(self.data, "N")
        fileops.write_note(self.data, "N", "kalsın")
        r = fileops.remove_note(self.data, "N")
        self.assertTrue(r.ok)
        self.assertFalse(os.path.exists(fileops.note_path(self.data, "N")))
        self.assertEqual(fileops.notefmt.loads(read(r.dest))[0], "kalsın")
        self.assertIn(fileops.TRASH_DIRNAME, r.dest)

    def test_kaldir_cakisan_cop_adi(self):
        for i in range(2):
            fileops.create_note(self.data, "N")
            fileops.write_note(self.data, "N", "v%d" % i)
            self.assertTrue(fileops.remove_note(self.data, "N"))
        trash = os.path.join(fileops.notes_dir(self.data), fileops.TRASH_DIRNAME)
        self.assertEqual(len(os.listdir(trash)), 2)

    def test_ad_alani_klasor_ve_not_ortak(self):
        fileops.create_panel(self.ctx, "Oyunlar")
        panels = {"Notum": {"type": "note"}, "Oyunlar": {"type": "shortcut"}}

        def nt(n, **k):
            return fileops.name_taken(self.ctx, self.data, panels, n, **k)

        self.assertTrue(nt("oyunlar"))
        self.assertTrue(nt("NOTUM"))
        self.assertFalse(nt("Başka"))
        self.assertFalse(nt("Notum", ignore="Notum"))      # kendi adı çakışma sayılmaz

    def test_not_dosyasi_masaustunde_degil(self):
        fileops.create_note(self.data, "N")
        self.assertFalse(fileops.is_inside(fileops.note_path(self.data, "N"), self.desk))


class FakeBackend:
    def __init__(self, hidden=False, works=True):
        self.hidden, self.works, self.calls = hidden, works, []

    def get_hidden(self):
        return self.hidden

    def set_hidden(self, v):
        self.calls.append(v)
        if self.works:
            self.hidden = v
        return self.works


class TestIconHider(unittest.TestCase):
    def mk(self, hidden=False, **kw):
        self.g = {"hide_desktop_icons": False, "hide_icons_restore": None}
        self.b = FakeBackend(hidden, **kw)
        self.h = deskicons.IconHider(self.g, self.b)

    def test_test_modu_pasif_hicbir_cagri_yok(self):
        g = {"hide_desktop_icons": True, "hide_icons_restore": None}
        h = deskicons.IconHider(g, None)
        self.assertFalse(h.enabled)
        self.assertFalse(h.set_enabled(True))
        self.assertTrue(h.startup())
        self.assertTrue(h.on_quit())
        self.assertFalse(h.restore_now())
        self.assertEqual(g, {"hide_desktop_icons": True, "hide_icons_restore": None})

    def test_gizle_eski_durum_kaydedilir_ve_kapaninca_doner(self):
        self.mk(hidden=False)
        self.assertTrue(self.h.set_enabled(True))
        self.assertTrue(self.b.hidden)
        self.assertEqual(self.g["hide_icons_restore"], False)
        self.assertTrue(self.g["hide_desktop_icons"])
        self.h.on_quit()
        self.assertFalse(self.b.hidden)
        self.assertTrue(self.g["hide_desktop_icons"])            # ayar açık kalır
        self.assertIsNone(self.g["hide_icons_restore"])

    def test_sonraki_acilista_tekrar_gizlenir(self):
        self.mk(hidden=False)
        self.h.set_enabled(True)
        self.h.on_quit()
        self.h.startup()
        self.assertTrue(self.b.hidden)
        self.assertEqual(self.g["hide_icons_restore"], False)

    def test_zaten_gizliyse_kapaninca_gizli_kalir(self):
        self.mk(hidden=True)
        self.h.set_enabled(True)
        self.assertEqual(self.b.calls, [])                       # değişiklik gerekmedi
        self.assertEqual(self.g["hide_icons_restore"], True)
        self.h.on_quit()
        self.assertTrue(self.b.hidden)                           # kullanıcı zaten gizli kullanıyordu
        self.assertEqual(self.b.calls, [])

    def test_ayar_kapatilinca_doner_ve_ayar_kapanir(self):
        self.mk(hidden=False)
        self.h.set_enabled(True)
        self.assertTrue(self.h.set_enabled(False))
        self.assertFalse(self.b.hidden)
        self.assertFalse(self.g["hide_desktop_icons"])

    def test_cokme_sonrasi_eski_durum_korunur(self):
        # önceki oturum çöktü: ikonlar gizli kaldı, kayıtta eski durum = gösteriliyordu
        self.mk(hidden=True)
        self.g.update(hide_desktop_icons=True, hide_icons_restore=False)
        self.h.startup()
        self.assertEqual(self.g["hide_icons_restore"], False)    # 'gizli' diye ezilmedi
        self.h.on_quit()
        self.assertFalse(self.b.hidden)

    def test_restore_now(self):
        self.mk(hidden=False)
        self.h.set_enabled(True)
        self.assertTrue(self.h.restore_now())
        self.assertFalse(self.b.hidden)
        self.assertFalse(self.g["hide_desktop_icons"])
        self.assertIsNone(self.g["hide_icons_restore"])

    def test_geri_donus_iki_kez_cagrilsa_zarar_yok(self):
        self.mk(hidden=False)
        self.h.set_enabled(True)
        self.h.on_quit()
        n = len(self.b.calls)
        self.h.on_quit()                                         # atexit ikinci kez
        self.assertEqual(len(self.b.calls), n)

    def test_arka_uc_basarisiz(self):
        self.mk(hidden=False, works=False)
        self.assertFalse(self.h.set_enabled(True))
        self.assertFalse(self.g["hide_desktop_icons"])           # ayar açık sayılmaz

    def test_ayar_kapaliyken_baslangicta_dokunmaz(self):
        self.mk(hidden=False)
        self.h.startup()
        self.assertEqual(self.b.calls, [])


if __name__ == "__main__":
    unittest.main()
