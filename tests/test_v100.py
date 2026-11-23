"""1.0.0 fix: the Calendar panel can be resized like the other panels (its content canvas covers the corner, so it
must carry the resize grip itself); the new size is saved to config.json and survives a restart."""
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import calendar_panel  # noqa: E402
import fileops  # noqa: E402
import mpanels  # noqa: E402


def pump(app, n=15):
    for _ in range(n):
        app.root.update()


@unittest.skipUnless(calendar_panel.AVAILABLE, "calendar libraries not installed")
class TestCalendarResize(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mpanels_t100_")
        self.desk, self.pub, self.data = (os.path.join(self.tmp, n) for n in ("Desktop", "Public", "veri"))
        os.makedirs(self.desk)
        os.makedirs(self.pub)
        self.apps = []
        # never read the real calendar source or touch the network: the panel's refresh is a no-op here
        patcher = mock.patch("calendar_panel.model.CalendarModel.refresh", lambda *a, **k: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        for a in self.apps:
            try:
                a.quit()
            except Exception:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_app(self):
        app = mpanels.App(fileops.Ctx(self.desk, self.pub), self.data, test_mode=True, use_tray=False,
                          instance_name="t100_%d" % len(self.apps))
        self.apps.append(app)
        return app

    def test_kose_tutamaci_ile_buyutme_kaydedilir_ve_korunur(self):
        app = self.make_app()
        p = app.new_panel("Cal", "calendar")
        pump(app)
        w0, h0 = p.cfg["w"], p.cfg["h"]
        cv = p.cal_cv
        self.assertIsNotNone(cv)
        # the corner of the CONTENT canvas is the panel's resize corner
        self.assertTrue(p._in_cal_grip(cv.winfo_width() - 5, cv.winfo_height() - 5))
        self.assertFalse(p._in_cal_grip(5, 5))
        p._cal_press(types.SimpleNamespace(x=cv.winfo_width() - 5, y=cv.winfo_height() - 5, x_root=500, y_root=400))
        self.assertTrue(p.resizing)
        p._body_drag(types.SimpleNamespace(x_root=560, y_root=470))
        p._body_release(types.SimpleNamespace(x_root=560, y_root=470))
        pump(app)
        self.assertFalse(p.resizing)
        self.assertEqual((p.cfg["w"], p.cfg["h"]), (w0 + 60, h0 + 70))
        self.assertEqual((p.cur_w, p.cur_h), (w0 + 60, h0 + 70))
        with open(app.config_path, encoding="utf-8") as f:
            saved = json.load(f)["panels"]["Cal"]
        self.assertEqual((saved["w"], saved["h"]), (w0 + 60, h0 + 70))
        # restart: a new App reads the saved size back
        app.quit()
        self.apps.remove(app)
        app2 = self.make_app()
        pump(app2)
        p2 = app2.panels["Cal"]
        self.assertEqual((p2.cfg["w"], p2.cfg["h"]), (w0 + 60, h0 + 70))
        self.assertEqual((p2.cur_w, p2.cur_h), (w0 + 60, h0 + 70))

    def test_tutamac_kilitliyken_ve_kapaliyken_pasif(self):
        app = self.make_app()
        p = app.new_panel("Cal", "calendar")
        pump(app)
        cv = p.cal_cv
        pt = (cv.winfo_width() - 5, cv.winfo_height() - 5)
        app.cfg["general"]["lock_panels"] = True
        self.assertFalse(p._in_cal_grip(*pt))
        p._cal_press(types.SimpleNamespace(x=pt[0], y=pt[1], x_root=1, y_root=1))
        self.assertFalse(p.resizing)

    def test_tuval_olaylari_bagli(self):
        app = self.make_app()
        p = app.new_panel("Cal", "calendar")
        pump(app)
        for seq in ("<ButtonPress-1>", "<B1-Motion>", "<ButtonRelease-1>"):
            self.assertTrue(p.cal_cv.bind(seq), seq + " takvim tuvalinde bağlı değil")

    def test_tutamac_cizgileri_takvim_tuvalinde(self):
        app = self.make_app()
        p = app.new_panel("Cal", "calendar")
        pump(app)
        cv = p.cal_cv
        w, h = cv.winfo_width(), cv.winfo_height()
        lines = [i for i in cv.find_all() if cv.type(i) == "line"]
        near = [i for i in lines if all(c >= 0 for c in cv.coords(i)) and max(cv.coords(i)[0], cv.coords(i)[2]) >= w - 8
                and max(cv.coords(i)[1], cv.coords(i)[3]) >= h - 8]
        self.assertGreaterEqual(len(near), 3, "tutamaç çizgileri takvim tuvalinde çizilmedi")


if __name__ == "__main__":
    unittest.main()
