"""v0.5.1: changelog parser, CHANGELOG.md consistency, Help text and About-tab strings (no tkinter)."""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import changelog  # noqa: E402
import strings  # noqa: E402
import version  # noqa: E402

SECTIONS = {"Panels", "Notes", "Calendar", "General", "Settings", "Bar", "Search", "Open windows", "Start button", "Help and About", "Backups"}   # 1.2.0 groups
SAMPLE = """# Changelog

## 1.2.3 — 2030-01-02

### Panels
- first
- second

### General
- third

## 1.0.0
### Notes
- old
"""


def key(v):
    return tuple(int(x) for x in v.split("."))


class TestParser(unittest.TestCase):
    def test_parse_sample(self):
        r = changelog.parse(SAMPLE)
        self.assertEqual([x["version"] for x in r], ["1.2.3", "1.0.0"])
        self.assertEqual(r[0]["date"], "2030-01-02")
        self.assertEqual(r[1]["date"], "")
        self.assertEqual(r[0]["sections"], [("Panels", ["first", "second"]), ("General", ["third"])])
        self.assertEqual(r[1]["sections"], [("Notes", ["old"])])

    def test_ignores_stray_lines(self):
        r = changelog.parse("- orphan\n### Panels\n- orphan2\n## 0.1.0\n- no section\n### Notes\n- ok\n")
        self.assertEqual(r, [{"version": "0.1.0", "date": "", "sections": [("Notes", ["ok"])]}])

    def test_render(self):
        blocks = changelog.render(changelog.parse(SAMPLE))
        self.assertEqual(blocks[0], ("ver", "v1.2.3 — 2030-01-02"))
        self.assertIn(("sec", "Panels"), blocks)
        self.assertIn(("item", strings.ABOUT_BULLET + "first"), blocks)
        self.assertEqual([b for b in blocks if b[0] == "ver"][-1], ("ver", "v1.0.0"))

    def test_load_missing_or_bad_never_raises(self):
        self.assertEqual(changelog.load(os.path.join(ROOT, "yok", "CHANGELOG.md")), [])
        bad = os.path.join(ROOT, "_test_tmp_bad.md")
        try:
            with open(bad, "wb") as f:
                f.write(b"\xff\xfe\x00bad")
            self.assertEqual(changelog.load(bad), [])
        finally:
            os.remove(bad)


class TestChangelogFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rel = changelog.load()

    def test_exists_and_not_empty(self):
        self.assertTrue(os.path.isfile(changelog.PATH))
        self.assertTrue(self.rel)

    def test_current_version_has_an_entry(self):
        """If version.py is bumped without a CHANGELOG entry this test fails."""
        self.assertIn(version.__version__, [r["version"] for r in self.rel])
        cur = next(r for r in self.rel if r["version"] == version.__version__)
        self.assertTrue(any(items for _, items in cur["sections"]), "the current version has no entries")

    def test_newest_first_and_no_duplicates(self):
        vs = [r["version"] for r in self.rel]
        self.assertEqual(len(vs), len(set(vs)))
        self.assertEqual(vs, sorted(vs, key=key, reverse=True))
        self.assertEqual(vs[0], version.__version__)

    def test_history_is_complete(self):
        have = {r["version"] for r in self.rel}
        self.assertTrue({"0.1.0", "0.2.0", "0.3.0", "0.4.0", "0.5.0", "0.5.1"} <= have)

    def test_only_known_sections_and_no_empty_ones(self):
        for r in self.rel:
            self.assertTrue(r["sections"], r["version"])
            for name, items in r["sections"]:
                self.assertIn(name, SECTIONS, r["version"])
                self.assertTrue(items, f"{r['version']}/{name} is empty")

    def test_matches_notlar_history(self):
        if not os.path.isfile(os.path.join(ROOT, "NOTLAR.md")):
            self.skipTest("NOTLAR.md is not part of the public repository")
        with open(os.path.join(ROOT, "NOTLAR.md"), encoding="utf-8") as f:
            notes = f.read()
        for r in self.rel:
            self.assertRegex(notes, r"(?m)^\s*-\s*\**v%s" % re.escape(r["version"]))

    def test_english_only(self):
        with open(changelog.PATH, encoding="utf-8") as f:
            text = f.read()
        self.assertFalse([c for c in text if c in "ğüşöçıİĞÜŞÖÇ"])

    def test_plain_text_only(self):
        """The About tab shows the text as is, so no markdown emphasis may be used."""
        with open(changelog.PATH, encoding="utf-8") as f:
            self.assertNotIn("**", f.read())

    def test_no_secrets_or_addresses(self):
        with open(changelog.PATH, encoding="utf-8") as f:
            text = f.read().lower()
        self.assertNotIn("http", text)


class TestHelpStrings(unittest.TestCase):
    def test_headings_per_panel_type(self):
        heads = [h for h, _ in strings.HELP_SECTIONS]
        for h in ("Shortcut panels", "Note panels", "Calendar panels", "General"):
            self.assertIn(h, heads)

    def test_bullets_short_and_english(self):
        for h, items in strings.HELP_SECTIONS:
            self.assertTrue(items, h)
            for i in items:
                self.assertLess(len(i), 140, i)
                self.assertFalse([c for c in i if c in "ğüşöçıİĞÜŞÖÇ"])

    def test_general_mentions_required_topics(self):
        gen = " ".join(dict(strings.HELP_SECTIONS)["General"]).lower()
        for word in ("lock", "desktop icons", "tray", "windows"):
            self.assertIn(word, gen)

    def test_tab_label_and_status_strings(self):
        self.assertEqual(strings.TAB_ABOUT, "About")
        self.assertEqual(strings.CAL_UPDATED.format(time="14:32"), "Updated 14:32")   # v0.5.2: header tooltip only
        self.assertEqual(strings.CAL_LOADING, "Loading…")

    def test_no_version_in_help(self):
        blob = " ".join(i for _, items in strings.HELP_SECTIONS for i in items)
        self.assertNotRegex(blob, r"\d+\.\d+\.\d+")


class TestNoFooter(unittest.TestCase):
    def test_calendar_footer_space_removed(self):
        src = open(os.path.join(ROOT, "calendar_panel", "view.py"), encoding="utf-8").read()
        self.assertIn("return 0", src.split("def foot_height")[1].split("def ")[0])

    def test_panels_never_draw_the_version(self):
        src = open(os.path.join(ROOT, "mpanels.py"), encoding="utf-8").read()
        uses = [m.start() for m in re.finditer(r"__version__", src)]
        # allowed: import, tray tip, settings title, About tab, startup log
        self.assertEqual(len(uses), 5, "unexpected new use of __version__ (must not be drawn in a panel)")


if __name__ == "__main__":
    unittest.main()
