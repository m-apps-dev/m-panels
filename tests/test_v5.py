"""Sürüm 5 birim testleri: takvim paneli (calendar_panel/). AĞSIZ: sahte iCal verisi ve sahte indirici kullanır.
Gerçek bir takvim dosyasına/adresine ve gerçek masaüstüne DOKUNMAZ.

Çalıştırma:  python -m unittest discover -s tests -v
"""
import hashlib
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.request
from datetime import date, datetime, timedelta
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import calendar_panel  # noqa: E402
import strings  # noqa: E402
import theme  # noqa: E402
from calendar_panel import core, settings, source  # noqa: E402
from calendar_panel.model import CalendarModel  # noqa: E402

D0 = date(2030, 3, 4)           # a Monday
SECRET = "https://calendar.example.invalid/private/SECRET-TOKEN-123/basic.ics"

ICS = "\r\n".join([
    "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//test//EN",
    # timed event, Monday 10:00-11:00
    "BEGIN:VEVENT", "UID:a1", "DTSTART:20300304T100000", "DTEND:20300304T110000", "SUMMARY:Standup",
    "LOCATION:Room 1", "END:VEVENT",
    # overlapping event
    "BEGIN:VEVENT", "UID:a2", "DTSTART:20300304T103000", "DTEND:20300304T120000", "SUMMARY:Design review", "END:VEVENT",
    # all-day, single day (no DTEND)
    "BEGIN:VEVENT", "UID:a3", "DTSTART;VALUE=DATE:20300305", "SUMMARY:Holiday", "END:VEVENT",
    # multi-day timed: Tue 22:00 -> Thu 02:00
    "BEGIN:VEVENT", "UID:a4", "DTSTART:20300305T220000", "DTEND:20300307T020000", "SUMMARY:Night shift", "END:VEVENT",
    # recurring: daily x3 from Wednesday
    "BEGIN:VEVENT", "UID:a5", "DTSTART:20300306T080000", "DTEND:20300306T083000", "RRULE:FREQ=DAILY;COUNT=3",
    "SUMMARY:Gym", "END:VEVENT",
    # cancelled
    "BEGIN:VEVENT", "UID:a6", "DTSTART:20300306T130000", "DTEND:20300306T140000", "STATUS:CANCELLED",
    "SUMMARY:Cancelled thing", "END:VEVENT",
    # no title
    "BEGIN:VEVENT", "UID:a7", "DTSTART:20300307T150000", "DTEND:20300307T160000", "END:VEVENT",
    # all-day, 2 days
    "BEGIN:VEVENT", "UID:a8", "DTSTART;VALUE=DATE:20300309", "DTEND;VALUE=DATE:20300311", "SUMMARY:Trip", "END:VEVENT",
    "END:VCALENDAR", ""])


def fake_cal():
    return core.parse_calendar(ICS.encode("utf-8"))


def titles(evs, day=None):
    return [e["title"] for e in evs if day is None or e["day"] == day]


@unittest.skipUnless(calendar_panel.AVAILABLE, "icalendar kitaplıkları yok")
class TestExpand(unittest.TestCase):
    def setUp(self):
        self.evs = core.expand(fake_cal(), D0, D0 + timedelta(days=7), {"color": "#112233", "name": "Work"})

    def test_gunluk_olaylar(self):
        self.assertEqual(titles(self.evs, D0), ["Standup", "Design review"])
        self.assertEqual(titles(self.evs, D0 + timedelta(days=1))[0], "Holiday")      # all-day sorts first

    def test_iptal_edilen_yok(self):
        self.assertNotIn("Cancelled thing", titles(self.evs))

    def test_basliksiz(self):
        self.assertIn(strings.CAL_UNTITLED, titles(self.evs))

    def test_tekrar_eden(self):
        self.assertEqual(sum(1 for e in self.evs if e["title"] == "Gym"), 3)

    def test_cok_gunlu_zamanli_gun_parcalari(self):
        parts = [e for e in self.evs if e["title"] == "Night shift"]
        self.assertEqual([p["day"] for p in parts], [D0 + timedelta(days=i) for i in (1, 2, 3)])
        self.assertEqual([p["first"] for p in parts], [True, False, False])
        self.assertEqual(parts[0]["seg_start"], datetime(2030, 3, 5, 22, 0))
        self.assertEqual(parts[0]["seg_end"], datetime(2030, 3, 6, 0, 0))
        self.assertEqual(parts[2]["seg_end"], datetime(2030, 3, 7, 2, 0))

    def test_tum_gun_iki_gun(self):
        parts = [e for e in self.evs if e["title"] == "Trip"]
        self.assertEqual([p["day"] for p in parts], [date(2030, 3, 9), date(2030, 3, 10)])
        self.assertTrue(all(p["all_day"] and p["seg_start"] is None for p in parts))

    def test_meta_rengi_ve_takvim_adi(self):
        e = self.evs[0]
        self.assertEqual((e["color"], e["cal"]), ("#112233", "Work"))
        self.assertEqual(e["location"], "Room 1")

    def test_aralik_siniri(self):
        evs = core.expand(fake_cal(), D0, D0 + timedelta(days=1))
        self.assertEqual({e["day"] for e in evs}, {D0})


class TestLayout(unittest.TestCase):
    def test_cakisanlar_yan_yana(self):
        a = {"seg_start": datetime(2030, 3, 4, 10), "seg_end": datetime(2030, 3, 4, 11), "title": "a"}
        b = {"seg_start": datetime(2030, 3, 4, 10, 30), "seg_end": datetime(2030, 3, 4, 12), "title": "b"}
        c = {"seg_start": datetime(2030, 3, 4, 13), "seg_end": datetime(2030, 3, 4, 14), "title": "c"}
        core.layout_lanes([a, b, c])
        self.assertEqual((a["lanes"], b["lanes"], c["lanes"]), (2, 2, 1))
        self.assertNotEqual(a["lane"], b["lane"])
        self.assertEqual(c["lane"], 0)

    def test_en_kisa_kutu(self):
        a = {"seg_start": datetime(2030, 3, 4, 10), "seg_end": datetime(2030, 3, 4, 10), "title": "a"}
        b = {"seg_start": datetime(2030, 3, 4, 10, 10), "seg_end": datetime(2030, 3, 4, 10, 40), "title": "b"}
        core.layout_lanes([a, b], min_minutes=20)
        self.assertEqual(a["lanes"], 2)           # a occupies 20 minutes on screen, so b overlaps it

    def test_day_label(self):
        today = date(2030, 3, 4)
        self.assertEqual(core.day_label(today, today), "Today · 4 March Monday")
        self.assertEqual(core.day_label(today + timedelta(days=1), today), "Tomorrow · 5 March Tuesday")
        self.assertEqual(core.day_label(today + timedelta(days=2), today), "6 March Wednesday")


class TestDownload(unittest.TestCase):
    def test_webcal_https_olur_ve_ua_gonderilir(self):
        seen = {}

        class R:
            def read(self):
                return ICS.encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            seen["url"], seen["ua"], seen["timeout"] = req.full_url, req.get_header("User-agent"), timeout
            return R()

        with mock.patch.object(urllib.request, "urlopen", fake_urlopen):
            cal = core.download_calendar("  webcal://x.example.invalid/a.ics ")
        self.assertEqual(seen["url"], "https://x.example.invalid/a.ics")
        self.assertEqual(seen["ua"], core.USER_AGENT)
        self.assertEqual(seen["timeout"], 30)
        self.assertEqual(len(list(cal.walk("VEVENT"))), 8)


class TestSource(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mp_cal_")
        self.path = os.path.join(self.tmp, "config.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, text):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_okuma_ve_temizleme(self):
        self.write('{"calendars": [{"name": "Work", "url": "https://a", "color": "#4285f4", "enabled": true},'
                   '{"name": "Bad", "url": "https://b", "color": "red", "enabled": false},'
                   '{"name": "NoUrl", "url": ""}, {"url": "https://c"}, "junk"]}')
        got = source.read_sources(self.path)
        self.assertEqual([c["name"] for c in got], ["Work", "Bad", f"{strings.CAL_ERR_UNNAMED} 3"])
        self.assertEqual(got[0]["color"], "#4285f4")
        self.assertIsNone(got[1]["color"])
        self.assertFalse(got[1]["enabled"])

    def test_eski_tek_adres(self):
        self.write('{"ics_url": "https://old", "calendars": []}')
        got = source.read_sources(self.path)
        self.assertEqual([(c["name"], c["url"]) for c in got], [(strings.CAL_LEGACY_NAME, "https://old")])

    def test_birlestir_ayni_adresi_ikilemez(self):
        have = [{"name": "A", "url": "u1", "color": None, "enabled": True}]
        got, added = source.merge(have, [{"name": "A2", "url": "u1", "color": None, "enabled": True},
                                         {"name": "B", "url": "u2", "color": None, "enabled": False}])
        self.assertEqual((added, [c["name"] for c in got]), (1, ["A", "B"]))
        self.assertEqual([c["name"] for c in have], ["A"])                 # the input list is not changed

    def test_dosya_yok(self):
        with self.assertRaises(source.SourceError) as cm:
            source.read_sources(os.path.join(self.tmp, "yok.json"))
        self.assertEqual(str(cm.exception), strings.CAL_ERR_NO_SOURCE)

    def test_bozuk_dosya_icerigi_mesaja_sizmaz(self):
        self.write('{"calendars": [{"url": "' + SECRET + '" BROKEN')
        with self.assertRaises(source.SourceError) as cm:
            source.read_sources(self.path)
        self.assertNotIn("SECRET-TOKEN", str(cm.exception))
        self.assertIn("JSONDecodeError", str(cm.exception))

    def test_dosya_salt_okunur(self):
        self.write('{"calendars": [{"name": "W", "url": "https://a"}]}')
        before = (hashlib.sha256(open(self.path, "rb").read()).hexdigest(), os.stat(self.path).st_mtime_ns)
        source.read_sources(self.path)
        after = (hashlib.sha256(open(self.path, "rb").read()).hexdigest(), os.stat(self.path).st_mtime_ns)
        self.assertEqual(before, after)


class TestSettings(unittest.TestCase):
    def test_varsayilanlar(self):
        s = settings.sanitize(None)
        self.assertNotIn("source_path", s)
        self.assertEqual(s["calendars"], [])
        self.assertEqual((s["view"], s["list_weeks"], s["refresh_minutes"]), ("list", 1, 5))
        self.assertEqual((s["start_hour"], s["end_hour"], s["hour_height"], s["past_fade"]), (7, 24, 30, 55))

    def test_bozuk_degerler(self):
        s = settings.sanitize({"view": "year", "list_weeks": "9", "refresh_minutes": "abc", "calendars": "x",
                               "start_hour": 30, "end_hour": 2, "source_path": "  ", "past_fade": True})
        self.assertNotIn("source_path", s)
        self.assertEqual((s["view"], s["list_weeks"], s["refresh_minutes"]), ("list", 4, 5))
        self.assertEqual(s["calendars"], [])
        self.assertEqual((s["start_hour"], s["end_hour"]), (23, 24))
        self.assertEqual(s["past_fade"], 55)

    def test_gecerli_degerler_korunur(self):
        d = {"calendars": [{"name": "A", "url": "https://a.invalid/x", "color": "#112233", "enabled": False},
                           {"name": "B", "url": "webcal://b.invalid/y", "color": None, "enabled": True}],
             "view": "week", "list_weeks": 3, "refresh_minutes": 15}
        s = settings.sanitize(d)
        for k, v in d.items():
            self.assertEqual(s[k], v)
        self.assertEqual(settings.sanitize(s), s)

    def test_yenileme_araligi_siniri(self):
        self.assertEqual(settings.sanitize({"refresh_minutes": 0})["refresh_minutes"], 1)
        self.assertEqual(settings.sanitize({"refresh_minutes": 5000})["refresh_minutes"], 120)

    def test_takvim_girdileri_temizlenir(self):
        s = settings.sanitize({"calendars": [{"name": " W ", "url": " https://a ", "color": "RED", "enabled": 0},
                                             {"name": "x", "url": ""}, {"url": None}, "junk", 5,
                                             {"url": "https://c", "color": "#ABCDEF"}]})
        self.assertEqual(s["calendars"], [{"name": "W", "url": "https://a", "color": None, "enabled": False},
                                          {"name": "", "url": "https://c", "color": "#abcdef", "enabled": True}])

    def test_eski_ayar_yalniz_tasima_sorusuna_kadar_kalir(self):
        old = {"source_path": r"D:\old\config.json", "calendars": ["Home", "  ", "Work"]}
        s = settings.sanitize(old)
        self.assertEqual((s["source_path"], s["legacy_names"], s["calendars"]),
                         (r"D:\old\config.json", ["Home", "Work"], []))
        self.assertEqual(settings.sanitize(s), s)
        self.assertEqual(settings.pending_migration(s), (r"D:\old\config.json", ["Home", "Work"]))
        done = settings.finish_migration(s, [{"name": "Work", "url": "u1", "color": None, "enabled": True},
                                             {"name": "Home", "url": "u2", "color": None, "enabled": True},
                                             {"name": "Sport", "url": "u3", "color": None, "enabled": True}], ["Home", "Work"])
        self.assertNotIn("source_path", done)
        self.assertNotIn("legacy_names", done)
        self.assertIsNone(settings.pending_migration(done))
        self.assertEqual([(c["name"], c["enabled"]) for c in done["calendars"]],
                         [("Work", True), ("Home", True), ("Sport", False)])      # only the old ticked names stay on
        self.assertIsNone(settings.pending_migration(settings.sanitize(None)))


@unittest.skipUnless(calendar_panel.AVAILABLE, "icalendar kitaplıkları yok")
class TestModel(unittest.TestCase):
    def setUp(self):
        self.cals = [{"name": "Work", "url": SECRET, "color": "#112233", "enabled": True},
                     {"name": "Home", "url": "https://home.example.invalid/x.ics", "color": None, "enabled": True}]
        self.calls = []
        self.fail = set()

        def fetch(url):
            self.calls.append(url)
            if url in self.fail:
                raise OSError("connect failed for " + url)         # a real error text may contain the address
            return fake_cal()

        self.fetch = fetch
        self.model = CalendarModel(fetch=fetch)
        self.deny_net = mock.patch.object(urllib.request, "urlopen", side_effect=AssertionError("network!"))
        self.deny_net.start()

    def tearDown(self):
        self.deny_net.stop()

    def test_yenileme_ve_olaylar(self):
        self.assertTrue(self.model.refresh(self.cals, sync=True))
        snap = self.model.snapshot()
        self.assertIsNone(snap["error"])
        self.assertIsNotNone(snap["last_update"])
        self.assertFalse(snap["loading"])
        evs = self.model.events_between(D0, D0 + timedelta(days=1))
        self.assertEqual(titles(evs), ["Standup", "Standup", "Design review", "Design review"])      # 2 calendars
        self.assertEqual({e["cal"] for e in evs}, {"Work", "Home"})

    def test_secili_takvimler(self):
        self.cals[0]["enabled"] = False
        self.model.refresh(self.cals, sync=True)
        self.assertEqual(self.calls, ["https://home.example.invalid/x.ics"])
        self.assertEqual({e["cal"] for e in self.model.events_between(D0, D0 + timedelta(days=1))}, {"Home"})

    def test_ag_hatasi_kisa_mesaj_ve_adres_yok(self):
        self.fail.add(SECRET)
        self.model.refresh(self.cals, sync=True)
        err = self.model.snapshot()["error"]
        self.assertIn("Work (OSError)", err)
        self.assertNotIn("SECRET-TOKEN", err)
        self.assertNotIn("example.invalid", err)
        # the other calendar still loaded
        self.assertEqual({e["cal"] for e in self.model.events_between(D0, D0 + timedelta(days=1))}, {"Home"})

    def test_hatada_eski_veri_kalir(self):
        self.model.refresh(self.cals, sync=True)
        self.fail.update(c["url"] for c in self.cals)
        self.model.refresh(self.cals, sync=True)
        snap = self.model.snapshot()
        self.assertIn("OSError", snap["error"])
        self.assertTrue(self.model.events_between(D0, D0 + timedelta(days=1)), "son başarılı veri ekranda kalmalı")

    def test_takvim_secili_degil(self):
        self.cals = []
        self.model.refresh(self.cals, sync=True)
        self.assertEqual(self.model.snapshot()["error"], strings.CAL_ERR_NONE)

    def test_beklenmedik_hata_uygulamayi_dusurmez(self):
        m = CalendarModel(fetch=lambda u: 1 / 0)
        m.refresh(self.cals, sync=True)
        self.assertIn("ZeroDivisionError", m.snapshot()["error"])
        self.assertFalse(m.snapshot()["loading"])

    def test_bozuk_takvim_cizimi_bozmaz(self):
        self.model.refresh(self.cals, sync=True)
        with mock.patch.object(core, "expand", side_effect=ValueError("bad data")):
            self.assertEqual(self.model.events_between(D0, D0 + timedelta(days=1)), [])

    def test_arka_planda_calisir_ve_haber_verir(self):
        done, started = threading.Event(), threading.Event()
        gate = threading.Event()
        main = threading.current_thread()
        threads = []

        def slow_fetch(url):
            threads.append(threading.current_thread())
            started.set()
            gate.wait(5)
            return fake_cal()

        m = CalendarModel(fetch=slow_fetch, notify=done.set)
        self.assertTrue(m.refresh(self.cals[:1]))                      # returns at once (the fetch is blocked)
        self.assertTrue(started.wait(2))
        self.assertTrue(m.snapshot()["loading"])
        self.assertFalse(m.refresh(self.cals[:1]), "yenileme sürerken ikincisi başlamamalı")
        gate.set()
        self.assertTrue(done.wait(5))
        self.assertIsNot(threads[0], main)
        self.assertFalse(m.snapshot()["loading"])

    def test_kutuphane_yoksa_mesaj(self):
        with mock.patch("calendar_panel.model.AVAILABLE", False):
            self.model.refresh(self.cals, sync=True)
        self.assertEqual(self.model.snapshot()["error"], strings.CAL_ERR_LIBS)
        self.assertEqual(self.calls, [])

    def test_hata_loga_adressiz_yazilir(self):
        import logging
        self.fail.add(SECRET)
        with self.assertLogs("mpanels", level=logging.WARNING) as cm:
            self.model.refresh(self.cals, sync=True)
        self.assertNotIn("SECRET-TOKEN", "\n".join(cm.output))


class TestRepoHygiene(unittest.TestCase):
    def test_gitignore_gizli_dosyalari_kapsar(self):
        with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as f:
            lines = {l.strip() for l in f if l.strip() and not l.startswith("#")}
        for pat in ("*token*.json", "credentials*.json", "client_secret*.json", "calendar_source*.json", "config.json"):
            self.assertIn(pat, lines)

    def repo_files(self):
        """Files that belong to the repository: what git would track (tracked + new, not ignored). Personal files that
        .gitignore keeps out (config.json with the user's calendar addresses, backups, notes) are NOT scanned.
        Without git (the public copy is a plain folder) every file except generated/personal names is checked."""
        import subprocess
        try:
            out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                                 check=True, capture_output=True).stdout.decode("utf-8")
            return [os.path.join(ROOT, f) for f in out.split("\0") if f and os.path.isfile(os.path.join(ROOT, f))]
        except (OSError, subprocess.CalledProcessError):
            skip_dirs = (".git", "__pycache__", "backups", "notlar", "venv", ".venv")
            files = []
            for dp, dn, fn in os.walk(ROOT):
                dn[:] = [d for d in dn if d not in skip_dirs]
                files += [os.path.join(dp, n) for n in fn if n not in ("config.json", "defaults.json")]
            return files

    def test_depoda_adres_veya_gizli_dosya_yok(self):
        bad = []
        for p in self.repo_files():
            if p.endswith((".py", ".md", ".json")) and os.path.basename(p) != "test_v5.py":
                with open(p, encoding="utf-8", errors="ignore") as f:
                    t = f.read()
                if "calendar.google.com/calendar/ical" in t or "outlook.live.com/owa/calendar" in t:
                    bad.append(p)
        self.assertEqual(bad, [])

    def test_kisisel_yol_sabitleri_kalkti(self):
        self.assertFalse(hasattr(theme, "DEFAULT_SOURCE_PATH"))
        self.assertFalse(hasattr(theme, "ICON_FILE"))

if __name__ == "__main__":
    unittest.main()
