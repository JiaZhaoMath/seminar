"""Checks for build.py. Standard library only.

Run from the repo root:  python3 -m unittest discover tests
"""

import datetime as dt
import html.parser
import re
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import build  # noqa: E402

TODAY = dt.date(2026, 9, 28)

# Words that must never reach the public repo or site. Host-only names are
# listed; people who are also speakers (e.g. Zheng Sun) cannot be.
FORBIDDEN = [
    r"mail\.google", r"jia\.zhao\.math@gmail", r"\bTBA\b", r"\bTBD\b", r"to be announced",
    r"\bnominat", r"\bcoordinator\b", r"\binviter\b", r"\bhost(ed|s)?\b", r"as stated",
    r"correspondence", r"Sidje", r"Putkaradze", r"Shan Zhao", r"Organizer-provided",
    r"\bUnfilled\b", r"\bBlocked\b",
]

SEED_DATES = ["2026-09-11", "2026-09-25", "2026-10-02", "2026-10-09",
              "2026-10-16", "2026-11-06", "2026-11-13", "2026-11-20",
              "2026-12-04"]
EXPECTED_OPEN = ["2026-10-23",
                 "2027-01-15", "2027-01-22", "2027-01-29", "2027-02-05", "2027-02-12",
                 "2027-02-19", "2027-02-26", "2027-03-05", "2027-03-12", "2027-03-19",
                 "2027-04-02", "2027-04-16", "2027-04-23", "2027-04-30"]


class _Links(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs, self.ids, self.stack = [], set(), []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        for key in ("href", "src"):
            if key in a:
                self.hrefs.append(a[key])


def values(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from values(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from values(v)
    else:
        yield str(obj)


class BuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        cls.result = build.build(ROOT / "talks.toml", cls.out, TODAY)
        cls.index = (cls.out / "index.html").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def generated(self):
        return [p for p in self.out.rglob("*") if p.is_file() and p.suffix in {".html", ".ics", ".txt"}]

    # ---- privacy

    def test_privacy_data_file(self):
        data = tomllib.loads((ROOT / "talks.toml").read_text(encoding="utf-8"))
        text = "\n".join(values(data))
        for pat in FORBIDDEN:
            self.assertIsNone(re.search(pat, text, re.I), f"talks.toml value matches {pat!r}")

    def test_privacy_generated(self):
        for path in self.generated():
            # The build's own placeholder for an unknown title is the one allowed "TBA".
            text = path.read_text(encoding="utf-8").replace(build.TITLE_TBA, "")
            for pat in FORBIDDEN:
                m = re.search(pat, text, re.I)
                self.assertIsNone(m, f"{path.relative_to(self.out)} contains {m and m.group(0)!r}")

    # ---- content

    def test_all_seed_talks_present(self):
        for d in SEED_DATES:
            self.assertIn(f'id="{d}"', self.index)
        self.assertEqual(self.result["talks"], len(SEED_DATES))

    def test_open_dates_exact(self):
        section = self.index.split('<section id="open"', 1)[1].split("</section>", 1)[0]
        found = re.findall(r'<time datetime="(\d{4}-\d{2}-\d{2})">', section)
        self.assertEqual(found, EXPECTED_OPEN)

    def test_past_and_upcoming_split(self):
        upcoming = self.index.split('<section id="upcoming"', 1)[1].split("</section>", 1)[0]
        past = self.index.split('<section id="past"', 1)[1].split("</section>", 1)[0]
        self.assertIn('id="2026-10-02"', upcoming)
        self.assertNotIn('id="2026-09-25"', upcoming)
        self.assertIn('id="2026-09-25"', past)
        self.assertNotIn("Add to calendar", past)

    def test_special_slot_highlighted(self):
        card = self.index.split('id="2026-10-16"', 1)[1].split("</article>", 1)[0]
        self.assertIn("10:00–10:50 AM", card)
        self.assertIn("GP 208", card)
        self.assertIn('class="talk-note"', card)

    def test_defaults_and_omissions(self):
        laiu = self.index.split('id="2026-11-06"', 1)[1].split("</article>", 1)[0]
        self.assertIn("11:00–11:50 AM", laiu)
        self.assertIn('<h3 class="talk-title">Title TBA</h3>', laiu)
        self.assertNotIn("GP ", laiu)                      # no room is guessed
        self.assertNotIn("Flyer", laiu)                    # no title, no flyer
        z = self.index.split('id="2026-11-13"', 1)[1].split("</article>", 1)[0]
        self.assertIn("11:00–11:50 AM", z)                 # series default slot
        self.assertIn("Fridays, 11:00–11:50 AM Central time", self.index)
        g = self.index.split('id="2026-11-20"', 1)[1].split("</article>", 1)[0]
        self.assertIn("Postdoc, Department of Mathematics &amp; Statistics, Texas Tech University", g)
        self.assertIn("<i>p</i>-Laplace", self.index)      # $p$ in italics

    def test_reserved_slot(self):
        src = (ROOT / "talks.toml").read_text(encoding="utf-8")
        src += '\n[[talks]]\ndate = 2026-10-23\nreserved = true\n'
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "talks.toml"
            data.write_text(src, encoding="utf-8")
            out = Path(tmp) / "site"
            build.build(data, out, TODAY)
            index = (out / "index.html").read_text(encoding="utf-8")
            card = index.split('id="2026-10-23"', 1)[1].split("</article>", 1)[0]
            self.assertIn("Reserved", card)
            self.assertNotIn('datetime="2026-10-23"', index.split('<section id="open"', 1)[1].split("</section>")[0])
            self.assertNotIn("20261023", (out / "seminar.ics").read_text(encoding="utf-8"))
            self.assertFalse((out / "ics" / "2026-10-23.ics").exists())
            self.assertNotIn("October 23", (out / "schedule.txt").read_text(encoding="utf-8"))

    def test_schedule_txt(self):
        text = (self.out / "schedule.txt").read_text(encoding="utf-8")
        blocks = text.rstrip("\n").split("\n\n")
        self.assertEqual(len(blocks), 1 + len(SEED_DATES))                 # header + one block per talk
        self.assertTrue(blocks[0].startswith("Applied Mathematics Seminar, 2026–2027"))
        self.assertIn("Friday, October 16, 2026, 10:00–10:50 AM, GP 208\nAina G. Irbe, Accessible Minds\n", text)
        laiu = next(b for b in blocks if "Laiu" in b)
        self.assertEqual(laiu, "Friday, November 6, 2026, 11:00–11:50 AM\nPaul Laiu, Oak Ridge National Laboratory\nTitle TBA")
        z = next(b for b in blocks if "Zharnitsky" in b)
        self.assertIn("11:00–11:50 AM\n", z)                  # default slot, no room guessed
        self.assertNotIn("$", text)
        self.assertNotIn("\r", text)

    # ---- calendar

    def test_ics_structure(self):
        for path in [self.out / "seminar.ics", *(self.out / "ics").glob("*.ics")]:
            raw = path.read_bytes()
            self.assertTrue(raw.endswith(b"\r\n"))
            self.assertNotIn(b"\n", raw.replace(b"\r\n", b""), f"{path.name}: bare LF")
            for line in raw.split(b"\r\n"):
                self.assertLessEqual(len(line), 75, f"{path.name}: long line {line[:30]!r}")
            text = raw.decode("utf-8")
            self.assertEqual(text.count("BEGIN:VEVENT"), text.count("END:VEVENT"))
            self.assertEqual(text.count("BEGIN:VCALENDAR"), 1)
        feed = (self.out / "seminar.ics").read_text(encoding="utf-8")
        self.assertEqual(feed.count("BEGIN:VEVENT"), len(SEED_DATES))

    def test_ics_dst(self):
        feed = (self.out / "seminar.ics").read_text(encoding="utf-8")
        self.assertIn("DTSTART:20261002T160000Z", feed)   # 11:00 CDT
        self.assertIn("DTSTART:20261016T150000Z", feed)   # 10:00 CDT
        self.assertIn("DTSTART:20261113T170000Z", feed)   # 11:00 CST, after Nov 1
        self.assertIn("DTEND:20261113T175000Z", feed)     # default end 11:50 CST
        laiu = (self.out / "ics" / "2026-11-06.ics").read_text(encoding="utf-8").replace("\r\n ", "")
        self.assertIn("Paul Laiu — Title TBA", laiu)

    # ---- HTML integrity

    def test_links_resolve(self):
        for path in self.out.rglob("*.html"):
            p = _Links()
            p.feed(path.read_text(encoding="utf-8"))
            for href in p.hrefs:
                if re.match(r"(https?|mailto|webcal):", href):
                    continue
                target, _, frag = href.partition("#")
                dest = (path.parent / target).resolve() if target else path
                self.assertTrue(dest.exists(), f"{path.name}: broken link {href}")
                if frag:
                    q = _Links()
                    q.feed(dest.read_text(encoding="utf-8"))
                    self.assertIn(frag, q.ids, f"{path.name}: missing anchor {href}")

    def test_year_rollover(self):
        src = (ROOT / "talks.toml").read_text(encoding="utf-8")
        src += ('\n[[years]]\nid = "2027-2028"\nterms = [{ name = "Fall 2027", '
                'start = 2027-08-18, end = 2027-12-03 }]\n')
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "talks.toml"
            data.write_text(src, encoding="utf-8")
            out = Path(tmp) / "site"
            r = build.build(data, out, dt.date(2027, 8, 15))
            self.assertEqual(r["current"], "2027-2028")
            self.assertIn("2027–2028", (out / "index.html").read_text(encoding="utf-8"))
            old = (out / "2026-2027.html").read_text(encoding="utf-8")
            self.assertIn('<section id="talks"', old)        # finished year = archive
            self.assertIn('id="2026-10-02"', old)

    def test_bad_data_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "talks.toml"
            base = (ROOT / "talks.toml").read_text(encoding="utf-8")
            for extra in ('\n[[talks]]\ndate = 2026-10-23\nspeker = "Typo"\n',
                          '\n[[talks]]\ndate = 2026-10-02\nspeaker = "Duplicate"\n',
                          '\n[[talks]]\ndate = 2030-01-04\nspeaker = "No year"\n'):
                data.write_text(base + extra, encoding="utf-8")
                with self.assertRaises(build.DataError):
                    build.load(data)


if __name__ == "__main__":
    unittest.main()
