"""Checks for build.py. Standard library only.

Run from the repo root:  python3 -m unittest discover tests

Two kinds of checks:
  SeedFixtureTest  exact known answers against tests/fixtures/seed_talks.toml, a frozen
                   copy of talks.toml from September 28, 2026. Never edit the fixture.
  LiveDataTest     rules that must hold for the real talks.toml whatever is booked
                   (privacy, links, calendar format). Adding a talk needs no test edits.
"""

import datetime as dt
import html.parser
import re
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import build  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "seed_talks.toml"
TODAY = dt.date(2026, 9, 28)

# Words that must never reach the public repo or site. Host-only names are
# listed; people who are also speakers (e.g. Zheng Sun) cannot be.
FORBIDDEN = [
    r"mail\.google", r"jia\.zhao\.math@gmail", r"\bTBA\b", r"\bTBD\b", r"to be announced",
    r"\bnominat", r"\bcoordinator\b", r"\binviter\b", r"\bhost(ed|s)?\b", r"as stated",
    r"correspondence", r"Sidje", r"Putkaradze", r"Shan Zhao", r"Organizer-provided",
    r"\bUnfilled\b", r"\bBlocked\b",
]
# Checked against the raw file, comments included. The generic words above (TBA,
# hosts, Blocked) appear legitimately in the instructions at the top of talks.toml.
FORBIDDEN_RAW = [
    r"mail\.google", r"jia\.zhao\.math@gmail", r"\bnominat", r"\bcoordinator\b", r"\binviter\b",
    r"correspondence", r"Sidje", r"Putkaradze", r"Shan Zhao", r"Organizer-provided",
]

SEED_DATES = ["2026-09-11", "2026-09-25", "2026-10-02", "2026-10-09",
              "2026-10-16", "2026-11-06", "2026-11-13", "2026-11-20"]
EXPECTED_OPEN = ["2026-10-23", "2026-12-04",
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


def privacy_hits(src: str) -> list[str]:
    """Forbidden patterns found in a talks.toml source (parsed values and raw text)."""
    text = "\n".join(values(tomllib.loads(src)))
    hits = [p for p in FORBIDDEN if re.search(p, text, re.I)]
    return hits + [p for p in FORBIDDEN_RAW if re.search(p, src, re.I)]


def snapshot(out: Path) -> dict:
    return {p.relative_to(out): p.read_bytes() for p in out.rglob("*") if p.is_file()}


class SiteChecks:
    """Rules every build must satisfy, whatever the data."""

    def generated(self):
        return [p for p in self.out.rglob("*") if p.is_file() and p.suffix in {".html", ".ics", ".txt"}]

    def test_privacy_generated(self):
        for path in self.generated():
            # The build's own placeholder for an unknown title is the one allowed "TBA".
            text = path.read_text(encoding="utf-8").replace(build.TITLE_TBA, "")
            for pat in FORBIDDEN:
                m = re.search(pat, text, re.I)
                self.assertIsNone(m, f"{path.relative_to(self.out)} contains {m and m.group(0)!r}")

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
        booked = [t for t in tomllib.loads(self.src)["talks"] if not t.get("reserved")]
        self.assertEqual(feed.count("BEGIN:VEVENT"), len(booked))
        self.assertEqual(self.result["talks"], len(booked))

    def test_every_talk_on_its_year_page(self):
        data = build.load(self.data)
        for y in data["years"]:
            page = (self.out / f"{y['id']}.html").read_text(encoding="utf-8")
            for t in y["talks"]:
                self.assertIn(f'id="{t["date"]}"', page)

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

    def test_no_temp_files_left(self):
        self.assertEqual([p for p in self.out.rglob("*.tmp")], [])


class LiveDataTest(SiteChecks, unittest.TestCase):
    """The real talks.toml, built as of today."""

    @classmethod
    def setUpClass(cls):
        cls.data = ROOT / "talks.toml"
        cls.src = cls.data.read_text(encoding="utf-8")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        cls.result = build.build(cls.data, cls.out, dt.date.today())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_privacy_data_file(self):
        self.assertEqual(privacy_hits(self.src), [], "talks.toml (values or comments)")


class SeedFixtureTest(SiteChecks, unittest.TestCase):
    """Known answers for the frozen September 28 data."""

    @classmethod
    def setUpClass(cls):
        cls.data = FIXTURE
        cls.src = FIXTURE.read_text(encoding="utf-8")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        cls.result = build.build(FIXTURE, cls.out, TODAY)
        cls.index = (cls.out / "index.html").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # ---- content

    def test_all_seed_talks_present(self):
        for d in SEED_DATES:
            self.assertIn(f'id="{d}"', self.index)
        self.assertEqual(self.result["talks"], 8)

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
        src = self.src + '\n[[talks]]\ndate = 2026-10-23\nreserved = true\n'
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
        self.assertEqual(len(blocks), 1 + 8)                 # header + one block per talk
        self.assertTrue(blocks[0].startswith("Applied Mathematics Seminar, 2026–2027"))
        self.assertIn("Friday, October 16, 2026, 10:00–10:50 AM, GP 208\nAina G. Irbe, Accessible Minds\n", text)
        laiu = next(b for b in blocks if "Laiu" in b)
        self.assertEqual(laiu, "Friday, November 6, 2026, 11:00–11:50 AM\nPaul Laiu, Oak Ridge National Laboratory\nTitle TBA")
        z = next(b for b in blocks if "Zharnitsky" in b)
        self.assertIn("11:00–11:50 AM\n", z)                  # default slot, no room guessed
        self.assertNotIn("$", text)
        self.assertNotIn("\r", text)

    # ---- calendar

    def test_ics_dst(self):
        feed = (self.out / "seminar.ics").read_text(encoding="utf-8")
        self.assertIn("DTSTART:20261002T160000Z", feed)   # 11:00 CDT
        self.assertIn("DTSTART:20261016T150000Z", feed)   # 10:00 CDT
        self.assertIn("DTSTART:20261113T170000Z", feed)   # 11:00 CST, after Nov 1
        self.assertIn("DTEND:20261113T175000Z", feed)     # default end 11:50 CST
        laiu = (self.out / "ics" / "2026-11-06.ics").read_text(encoding="utf-8").replace("\r\n ", "")
        self.assertIn("Paul Laiu — Title TBA", laiu)

    def test_year_rollover(self):
        src = self.src + ('\n[[years]]\nid = "2027-2028"\nterms = [{ name = "Fall 2027", '
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


class BadInputTest(unittest.TestCase):
    """Invalid data is rejected before anything is written; a failed build keeps the old site."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.base = FIXTURE.read_text(encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def edited(self, old, new):
        self.assertEqual(self.base.count(old), 1, old)
        return self.base.replace(old, new)

    def assertRejected(self, src, msg=None):
        data = self.dir / "talks.toml"
        data.write_text(src, encoding="utf-8")
        out = self.dir / "site"
        with self.assertRaises(build.DataError, msg=msg):
            build.build(data, out, TODAY)
        self.assertFalse(out.exists(), f"{msg}: output written before the error")

    def test_bad_talks(self):
        for extra in ('date = 2026-10-23\nspeker = "Typo"',
                      'date = 2026-10-02\nspeaker = "Duplicate"',
                      'date = 2030-01-04\nspeaker = "No year"',
                      'date = 2026-10-23\nspeaker = "X"\nreserved = "false"',
                      'date = 2026-10-23\nspeaker = "   "',
                      'date = 2026-10-23\nspeaker = "X"\ntitle = 3',
                      'date = 2026-10-23\nspeaker = "X"\nstart = "11:00"\nend = "10:30"',
                      'date = 2026-10-23\nspeaker = "X"\nstart = "12:00"',       # default end 11:50
                      'date = 2026-10-23\nspeaker = "X"\nstart = "25:00"',
                      'date = 2026-10-23\nspeaker = "X"\nwebpage = "example.edu"'):
            self.assertRejected(self.base + "\n[[talks]]\n" + extra + "\n", extra)

    def test_bad_years_and_terms(self):
        cases = [
            self.base + '\n[[years]]\nid = "2026-2027"\n',
            self.edited("end = 2027-04-30", "end = 2028-01-14"),                   # outside the year
            self.edited("start = 2027-01-13, end = 2027-04-30",
                        "start = 2027-04-30, end = 2027-01-13"),                   # reversed
            self.edited("start = 2027-01-13", "start = 2026-12-01"),               # overlaps fall
            self.edited("blocked = [2026-10-30", 'blocked = ["2026-10-30"'),       # quoted date
        ]
        for src in cases:
            self.assertRejected(src)

    def test_bad_series(self):
        cases = [
            self.edited('default_end = "11:50"', 'default_end = "10:50"'),
            self.edited('timezone = "America/Chicago"', 'timezone = "Mars/Base"'),
            self.edited('weekday = "Friday"', 'weekday = "Fryday"'),
            self.edited('site_url = "https://jiazhaomath.github.io/seminar/"', 'site_url = "invalid-url/"'),
            "extra = 1\n" + self.base,
        ]
        for src in cases:
            self.assertRejected(src)

    def test_failed_render_keeps_previous_site(self):
        out = self.dir / "site"
        build.build(FIXTURE, out, TODAY)
        before = snapshot(out)
        with mock.patch.object(build, "flyer_page", side_effect=RuntimeError("render failed")):
            with self.assertRaises(RuntimeError):
                build.build(FIXTURE, out, TODAY + dt.timedelta(days=7))
        self.assertEqual(snapshot(out), before)

    def test_symlinked_output_folder_refused(self):
        outside = self.dir / "elsewhere"
        outside.mkdir()
        (outside / "user-calendar.ics").write_text("mine", encoding="utf-8")
        out = self.dir / "site"
        out.mkdir()
        (out / "ics").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(build.DataError):
            build.build(FIXTURE, out, TODAY)
        self.assertEqual(sorted(p.name for p in outside.iterdir()), ["user-calendar.ics"])

    def test_only_stale_owned_files_pruned(self):
        out = self.dir / "site"
        build.build(FIXTURE, out, TODAY)
        (out / "ics" / "notes.ics").write_text("mine", encoding="utf-8")
        (out / "ics" / "2030-01-04.ics").write_text("old talk", encoding="utf-8")
        build.build(FIXTURE, out, TODAY)
        self.assertTrue((out / "ics" / "notes.ics").exists())
        self.assertFalse((out / "ics" / "2030-01-04.ics").exists())

    def test_privacy_scan_reads_comments(self):
        self.assertEqual(privacy_hits(self.base), [])
        self.assertNotEqual(privacy_hits(self.base + "\n# https://mail.google.com/mail/u/0\n"), [])


if __name__ == "__main__":
    unittest.main()
