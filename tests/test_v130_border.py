"""v1.3: the panel border width (Settings > Panel > Border width, config key "border", 0-4 px, default 2).
Pure checks (normalize, make_bg), the Settings window on a made-up App (Apply / Discard / Cancel, Make default, Revert,
Factory), and the real App in test mode (old config, one drawing path for shortcut / note / calendar panels, the grip).
Nothing touches the real desktop, foreground or config; every dialog and color chooser is replaced."""
import copy
import hashlib
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import calendar_panel  # noqa: E402
import fileops  # noqa: E402
import mpanels  # noqa: E402
import strings as ui  # noqa: E402
import theme  # noqa: E402
from test_v120_step1 import Base as AppBase, pump  # noqa: E402
from test_v56 import Base as SettingsBase, FakeApp as _FakeApp  # noqa: E402


class FakeApp(_FakeApp):
    def __init__(self, root):
        super().__init__(root)
        self.saved_defaults = {}

    def save_defaults(self, **parts):
        self.saved_defaults.update(parts)


# --------------------------------------------------------------------------- pure
class TestNormalize(unittest.TestCase):
    def test_garbage_is_the_default(self):
        for v in (None, True, False, "", "abc", " ", [], {}, 2.5, "2.5", "1,5", float("nan"), float("inf")):
            self.assertEqual(theme.normalize_border(v), 2, repr(v))

    def test_out_of_range_is_clamped(self):
        for v, want in ((9, 4), (5, 4), (-1, 0), (-100, 0), ("7", 4), ("-2", 0), (1e9, 4)):
            self.assertEqual(theme.normalize_border(v), want, repr(v))

    def test_valid_values_are_kept_and_zero_is_allowed(self):
        for v in range(0, 5):
            self.assertEqual(theme.normalize_border(v), v)
            self.assertEqual(theme.normalize_border(str(v)), v)
            self.assertEqual(theme.normalize_border(float(v)), v)
        self.assertEqual(theme.normalize_border(" 3 "), 3)

    def test_constants(self):
        self.assertEqual((theme.BORDER, theme.BORDER_MIN, theme.BORDER_MAX, theme.GRIP_INSET), (2, 0, 4, 3))
        self.assertEqual(mpanels.PANEL_FACTORY["border"], 2)
        self.assertIn("border", mpanels.APPEARANCE_KEYS)


class TestMakeBg(unittest.TestCase):
    def test_default_border_is_what_it_was(self):
        for (w, h, c) in ((60, 30, "#3aa0ff"), (380, 280, "#ff9a3c")):
            a = theme.make_bg(w, h, c).tobytes()
            self.assertEqual(hashlib.sha256(a).hexdigest(),
                             hashlib.sha256(theme.make_bg(w, h, c, border=2).tobytes()).hexdigest())

    def test_every_width_draws_differently(self):
        imgs = {n: theme.make_bg(120, 60, "#3aa0ff", border=n).tobytes() for n in range(0, 5)}
        self.assertEqual(len(set(imgs.values())), 5)

    def test_border_pixels(self):
        col = theme.hex_rgb("#3aa0ff")
        for n in range(1, 5):
            im = theme.make_bg(120, 60, "#3aa0ff", border=n)
            self.assertEqual(im.getpixel((60, 0)), col)                  # top edge is the color...
            self.assertEqual(im.getpixel((60, n - 1)), col)              # ...n rows deep...
            self.assertNotEqual(im.getpixel((60, n)), col)               # ...and not one more
        self.assertNotEqual(theme.make_bg(120, 60, "#3aa0ff", border=0).getpixel((60, 0)), col)


# --------------------------------------------------------------------------- Settings window on a made-up App
class SettingsCase(SettingsBase):
    def setUp(self):
        for p in (mock.patch.object(mpanels.colorchooser, "askcolor", return_value=(None, None)),
                  mock.patch.object(mpanels.messagebox, "askyesno", return_value=False),
                  mock.patch.object(mpanels.messagebox, "showinfo"),
                  mock.patch.object(mpanels.messagebox, "showwarning")):
            p.start()
            self.addCleanup(p.stop)

    def open(self, app=None, name="One"):
        return super().open(app or FakeApp(self.root), name)


class TestSettingsWindow(SettingsCase):
    def test_spinbox_range_and_label(self):
        _, w = self.open()
        self.assertEqual((int(float(w.sp_border.cget("from"))), int(float(w.sp_border.cget("to")))), (0, 4))
        self.assertEqual(ui.LBL_BORDER.format(lo=0, hi=4), "Border width (px, 0–4)")

    def test_form_shows_the_panels_value(self):
        app = FakeApp(self.root)
        app.panels["Two"].cfg["border"] = 3
        _, w = self.open(app, "One")
        self.assertEqual(w.v["border"].get(), "2")
        self.assertFalse(w.dirty())
        w.request_select("Two")
        self.assertEqual(w.v["border"].get(), "3")
        self.assertFalse(w.dirty())

    def test_apply_writes_the_value(self):
        app, w = self.open()
        w.v["border"].set("4")
        self.assertTrue(w.dirty())
        w.apply()
        self.assertEqual(app.panels["One"].cfg["border"], 4)
        self.assertEqual(app.panels["One"].applied, 1)
        self.assertGreater(app.saves, 0)
        self.assertFalse(w.dirty())
        self.assertNotIn("Border width must", w.msg.cget("text"))

    def test_nothing_changes_before_apply(self):
        app, w = self.open()
        w.v["border"].set("0")
        self.assertEqual(app.panels["One"].cfg["border"], 2)
        self.assertEqual(app.saves, 0)

    def test_zero_is_applied_as_zero(self):
        app, w = self.open()
        w.v["border"].set("0")
        w.apply()
        self.assertEqual(app.panels["One"].cfg["border"], 0)
        self.assertEqual(w.v["border"].get(), "0")

    def test_bad_values_are_fixed_and_explained(self):
        for raw, want in (("abc", 2), ("", 2), ("9", 4), ("-1", 0), ("2.5", 2), ("  3  ", 3)):
            app, w = self.open()
            w.v["border"].set(raw)
            w.apply()
            self.assertEqual(app.panels["One"].cfg["border"], want, raw)
            self.assertEqual(w.v["border"].get(), str(want), raw)
            warned = "Border width must be a whole number from 0 to 4" in w.msg.cget("text")
            self.assertEqual(warned, raw.strip() != "3", raw)                    # empty warns too (same as Icon size)

    def test_x_dirty_discard_keeps_the_old_value(self):
        app, w = self.open()
        w.v["border"].set("4")
        self.answer(w, "discard")
        w.close()
        self.assertFalse(w.win.winfo_exists())
        self.assertEqual(app.panels["One"].cfg["border"], 2)
        self.assertEqual(app.saves, 0)

    def test_x_dirty_cancel_stays_open_with_the_edit(self):
        app, w = self.open()
        w.v["border"].set("4")
        m = self.answer(w, "cancel")
        w.close()
        m.assert_called_once()
        self.assertTrue(w.win.winfo_exists())
        self.assertEqual(w.v["border"].get(), "4")
        self.assertEqual(app.panels["One"].cfg["border"], 2)

    def test_x_dirty_apply_applies_then_closes(self):
        app, w = self.open()
        w.v["border"].set("1")
        self.answer(w, "apply")
        w.close()
        self.assertFalse(w.win.winfo_exists())
        self.assertEqual(app.panels["One"].cfg["border"], 1)

    def test_panel_switch_asks_and_discard_drops_the_edit(self):
        app, w = self.open()
        w.v["border"].set("4")
        m = self.answer(w, "discard")
        w.request_select("Two")
        m.assert_called_once()
        self.assertEqual(w.cur, "Two")
        self.assertEqual(w.v["border"].get(), "2")
        self.assertEqual(app.panels["One"].cfg["border"], 2)

    def test_make_default_includes_border(self):
        app, w = self.open()
        w.v["border"].set("3")
        w.make_default()
        self.assertEqual(app.panels["One"].cfg["border"], 3)
        self.assertEqual(app.saved_defaults.get("border"), 3)

    def test_revert_and_factory_reset_border(self):
        for factory in (False, True):
            app, w = self.open()
            app.panels["One"].cfg["border"] = 4
            w.select("One")
            self.assertEqual(w.v["border"].get(), "4")
            w.confirm_overwrite = mock.Mock(return_value=True)
            w.reset(factory)
            self.assertEqual(app.panels["One"].cfg["border"], 2, factory)
            self.assertEqual(w.v["border"].get(), "2", factory)


class TestApplyToAllPanels(SettingsCase):
    """The 'Apply to all panels' box next to Border width: a one-shot that copies only the width to every panel."""
    def test_box_exists_and_starts_clear(self):
        _, w = self.open()
        self.assertFalse(w.v_border_all.get())
        self.assertEqual(w.cb_border_all.cget("text"), "Apply to all panels")

    def test_ticking_alone_is_an_unsaved_change(self):
        app, w = self.open()
        self.assertFalse(w.dirty())
        w.v_border_all.set(True)
        self.assertTrue(w.dirty())
        w.v_border_all.set(False)
        self.assertFalse(w.dirty())

    def test_ticked_apply_writes_every_panel_and_redraws_them(self):
        app, w = self.open()
        w.v["border"].set("4")
        w.v_border_all.set(True)
        w.apply()
        for n in ("One", "Two"):
            self.assertEqual(app.panels[n].cfg["border"], 4, n)
            self.assertGreaterEqual(app.panels[n].applied, 1, n)        # the drawing cache is renewed
        self.assertGreater(app.saves, 0)
        self.assertFalse(w.dirty())

    def test_unticked_apply_changes_only_the_selected_panel(self):
        app, w = self.open()
        w.v["border"].set("4")
        w.apply()
        self.assertEqual(app.panels["One"].cfg["border"], 4)
        self.assertEqual(app.panels["Two"].cfg["border"], 2)
        self.assertEqual(app.panels["Two"].applied, 0)

    def test_box_clears_itself_after_apply(self):
        app, w = self.open()
        w.v_border_all.set(True)
        w.apply()
        self.assertFalse(w.v_border_all.get())
        w.v["border"].set("3")
        w.apply()                                          # a second Apply must NOT spread again
        self.assertEqual(app.panels["One"].cfg["border"], 3)
        self.assertEqual(app.panels["Two"].cfg["border"], 2)

    def test_other_settings_of_the_other_panels_stay(self):
        app, w = self.open()
        two = app.panels["Two"]
        before = {k: v for k, v in copy.deepcopy(two.cfg).items() if k != "border"}
        w.v["border"].set("1")
        w.v["color"].set(ui.COLOR_CUSTOM)
        w.color = "#123456"
        w.v_op.set(40)
        w.v_border_all.set(True)
        w.apply()
        self.assertEqual({k: v for k, v in two.cfg.items() if k != "border"}, before)
        self.assertEqual(two.cfg["border"], 1)
        self.assertEqual(app.panels["One"].cfg["color"], "#123456")

    def test_bad_value_is_fixed_for_all_panels_too(self):
        app, w = self.open()
        w.v["border"].set("9")
        w.v_border_all.set(True)
        w.apply()
        self.assertEqual([app.panels[n].cfg["border"] for n in ("One", "Two")], [4, 4])

    def test_discard_changes_no_panel_and_clears_the_box(self):
        app, w = self.open()
        w.v["border"].set("4")
        w.v_border_all.set(True)
        self.answer(w, "discard")
        w.request_select("Two")
        self.assertFalse(w.v_border_all.get())
        self.assertEqual([app.panels[n].cfg["border"] for n in ("One", "Two")], [2, 2])
        self.assertEqual(app.saves, 0)
        self.assertEqual(sum(p.applied for p in app.panels.values()), 0)

    def test_x_discard_changes_no_panel(self):
        app, w = self.open()
        w.v["border"].set("4")
        w.v_border_all.set(True)
        self.answer(w, "discard")
        w.close()
        self.assertFalse(w.win.winfo_exists())
        self.assertEqual([app.panels[n].cfg["border"] for n in ("One", "Two")], [2, 2])
        self.assertEqual(app.saves, 0)

    def test_cancel_changes_no_panel(self):
        app, w = self.open()
        w.v["border"].set("4")
        w.v_border_all.set(True)
        self.answer(w, "cancel")
        w.close()
        self.assertTrue(w.win.winfo_exists())               # Cancel = stay and keep editing (the existing rule)
        self.assertEqual([app.panels[n].cfg["border"] for n in ("One", "Two")], [2, 2])
        self.assertEqual(app.saves, 0)

    def test_discard_clears_the_box_before_anything_else_happens(self):
        app, w = self.open()
        w.v_border_all.set(True)
        self.answer(w, "discard")
        self.assertTrue(w._resolve_unsaved())
        self.assertFalse(w.v_border_all.get())
        self.assertFalse(w.dirty())

    def test_revert_to_defaults_reloads_the_form_and_clears_the_box(self):
        app, w = self.open()
        w.v_border_all.set(True)
        w.confirm_overwrite = mock.Mock(return_value=True)
        w.reset(False)
        self.assertFalse(w.v_border_all.get())
        self.assertEqual([app.panels[n].cfg["border"] for n in ("One", "Two")], [2, 2])

    def test_switching_panel_clears_the_box(self):
        app, w = self.open()
        w.v_border_all.set(True)
        self.answer(w, "discard")
        w.request_select("Two")
        self.assertFalse(w.v_border_all.get())

    def test_x_apply_with_the_box_ticked_applies_to_all_then_closes(self):
        app, w = self.open()
        w.v["border"].set("3")
        w.v_border_all.set(True)
        self.answer(w, "apply")
        w.close()
        self.assertEqual([app.panels[n].cfg["border"] for n in ("One", "Two")], [3, 3])

    def test_texts(self):
        self.assertEqual(ui.CHK_BORDER_ALL, "Apply to all panels")
        for text in (ui.HELP_SECTIONS[1][1][-1],):
            self.assertIn("all panels at once", text)
        readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
        self.assertIn("Apply to all panels", readme)
        log = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
        self.assertIn("Apply to all panels", log.split("## 1.2.0")[0])


# --------------------------------------------------------------------------- the real App (test mode)
class Rec:
    """A canvas that only records create_line calls."""
    def __init__(self):
        self.lines = []

    def create_line(self, *a, **k):
        self.lines.append(a)


class TestRealApp(AppBase):
    def setUp(self):
        super().setUp()
        for p in (mock.patch.object(mpanels.colorchooser, "askcolor", return_value=(None, None)),
                  mock.patch.object(mpanels.messagebox, "askyesno", return_value=False),
                  mock.patch.object(mpanels.messagebox, "showinfo"),
                  mock.patch.object(mpanels.messagebox, "showwarning")):
            p.start()
            self.addCleanup(p.stop)

    def panel_cfg(self, **over):
        c = {"type": "note", "x": 100, "y": 100, "w": 300, "h": 200}
        c.update(over)
        return {"panels": {"N": c}}

    def app_with(self, cfg):
        self.write_cfg(cfg)
        app = self.open(test_mode=True)
        return app, app.panels["N"]

    def test_old_config_without_the_key_opens_with_two(self):
        app, p = self.app_with(self.panel_cfg())
        self.assertEqual(p.cfg["border"], 2)
        self.assertEqual(p.border(), 2)
        self.assertEqual(p._bg_key[-1], 2)

    def test_config_values_are_sanitized_on_load(self):
        for raw, want in ((3, 3), (0, 0), ("x", 2), (9, 4), (-4, 0), (None, 2), (True, 2), (2.5, 2)):
            app, p = self.app_with(self.panel_cfg(border=raw))
            self.assertEqual(p.cfg["border"], want, repr(raw))
            self.close_all()
            self.apps.clear()

    def test_value_is_saved_to_the_file(self):
        app, p = self.app_with(self.panel_cfg(border=3))
        app.save()
        self.assertEqual(self.cfg_file()["panels"]["N"]["border"], 3)

    def test_bg_key_differs_for_every_width_and_make_bg_gets_it(self):
        app, p = self.app_with(self.panel_cfg())
        keys = set()
        with mock.patch.object(mpanels, "make_bg", wraps=theme.make_bg) as mb:
            for n in range(0, 5):
                p.cfg["border"] = n
                p.apply_cfg()
                keys.add(p._bg_key)
                self.assertEqual(mb.call_args.kwargs.get("border"), n)
        self.assertEqual(len(keys), 5)

    def test_all_three_panel_types_draw_through_make_bg_with_the_border(self):
        ctx = fileops.Ctx(self.desk, self.pub)
        fileops.ensure_panels_root(ctx)
        fileops.create_panel(ctx, "S")
        cfg = {"panels": {"S": {"border": 3}, "N": {"type": "note", "border": 1},
                          "C": {"type": "calendar", "border": 4}}}
        self.write_cfg(cfg)
        with mock.patch.object(mpanels, "make_bg", wraps=theme.make_bg) as mb:
            app = self.open(test_mode=True)
            seen = {}
            for name in ("S", "N", "C"):
                seen[name] = app.panels[name].border()
        self.assertEqual(seen, {"S": 3, "N": 1, "C": 4})
        used = {c.kwargs.get("border") for c in mb.call_args_list}
        self.assertTrue({3, 1, 4} <= used, used)

    def test_grip_position_is_border_plus_three(self):
        app, p = self.app_with(self.panel_cfg())
        w, h = 300, 170
        for border, inset in ((2, 5), (0, 3), (1, 4), (3, 6), (4, 7)):
            p.cfg["border"] = border
            cv = Rec()
            p._draw_grip(cv, w, h)
            want = [(w - inset - k, h - inset, w - inset, h - inset - k) for k in (4, 8, 12)]
            self.assertEqual(cv.lines, want, border)

    def test_grip_at_two_is_exactly_what_it_was(self):
        app, p = self.app_with(self.panel_cfg())
        cv = Rec()
        p._draw_grip(cv, 300, 170)                      # the old code: gx, gy = w - 5, h - 5
        self.assertEqual(cv.lines, [(300 - 5 - k, 170 - 5, 300 - 5, 170 - 5 - k) for k in (4, 8, 12)])

    def test_locked_panels_draw_no_grip(self):
        app, p = self.app_with(self.panel_cfg())
        app.cfg["general"]["lock_panels"] = True
        cv = Rec()
        p._draw_grip(cv, 300, 170)
        self.assertEqual(cv.lines, [])

    @unittest.skipUnless(calendar_panel.AVAILABLE, "calendar libraries are not installed")
    def test_calendar_grip_uses_the_same_function(self):
        app, p = self.app_with({"panels": {"N": {"type": "calendar", "border": 4, "x": 100, "y": 100, "w": 380, "h": 460}}})
        pump(app)
        with mock.patch.object(p, "_draw_grip", wraps=p._draw_grip) as g:
            p.draw_body()
            pump(app)
        self.assertTrue(g.called)
        cv = Rec()
        p._draw_grip(cv, 380, 400)
        self.assertEqual(cv.lines[0], (380 - 7 - 4, 400 - 7, 380 - 7, 400 - 7 - 4))

    def settings(self):
        w = mpanels.SettingsWindow(self.app, "N")
        self.addCleanup(lambda: w.win.winfo_exists() and w.win.destroy())
        return w

    def test_settings_apply_redraws_and_saves(self):
        app, p = self.app_with(self.panel_cfg())
        w = self.settings()
        key0 = p._bg_key
        w.v["border"].set("4")
        w.apply()
        self.assertEqual(p.cfg["border"], 4)
        self.assertNotEqual(p._bg_key, key0)
        self.assertEqual(self.cfg_file()["panels"]["N"]["border"], 4)

    def test_apply_to_all_on_the_real_app_redraws_every_panel_and_saves(self):
        app, p = self.app_with({"panels": {"N": {"type": "note", "x": 100, "y": 100, "w": 300, "h": 200},
                                           "M": {"type": "note", "x": 500, "y": 100, "w": 300, "h": 200, "opacity": 0.6}}})
        m = app.panels["M"]
        keys0 = (p._bg_key, m._bg_key)
        w = self.settings()
        w.v["border"].set("4")
        w.v_border_all.set(True)
        w.apply()
        self.assertEqual((p.cfg["border"], m.cfg["border"]), (4, 4))
        self.assertEqual((p._bg_key[-1], m._bg_key[-1]), (4, 4))
        self.assertNotEqual((p._bg_key, m._bg_key), keys0)
        self.assertEqual(m.cfg["opacity"], 0.6)
        self.assertFalse(w.v_border_all.get())
        saved = self.cfg_file()["panels"]
        self.assertEqual((saved["N"]["border"], saved["M"]["border"]), (4, 4))


    def test_make_default_revert_and_factory_on_the_real_app(self):
        app, p = self.app_with(self.panel_cfg())
        w = self.settings()
        w.confirm_overwrite = mock.Mock(return_value=True)
        w.v["border"].set("3")
        w.make_default()
        with open(app.defaults_path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["border"], 3)
        self.assertEqual(app.defaults()["border"], 3)
        self.assertEqual(app.defaults(factory=True)["border"], 2)
        p.cfg["border"] = 0
        w.reset(False)                                  # Revert to defaults: the saved default
        self.assertEqual(p.cfg["border"], 3)
        w.reset(True)                                   # Factory settings
        self.assertEqual(p.cfg["border"], 2)
        self.assertEqual(w.v["border"].get(), "2")

    def test_garbage_in_defaults_json_is_fixed(self):
        for raw, want in (("x", 2), (9, 4), (-1, 0), (None, 2)):
            app, p = self.app_with(self.panel_cfg())
            with open(app.defaults_path, "w", encoding="utf-8") as f:
                json.dump({"border": raw}, f)
            self.assertEqual(app.defaults()["border"], want, repr(raw))
            self.close_all()
            self.apps.clear()

    def test_new_panel_takes_the_default(self):
        app, p = self.app_with(self.panel_cfg())
        app.save_defaults(border=3)
        self.assertEqual(app.panel_cfg("Brand new")["border"], 3)


if __name__ == "__main__":
    print("python:", sys.executable)
    unittest.main()
