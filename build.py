#!/usr/bin/env python3
"""Build the Applied Mathematics Seminar website from talks.toml.

Python 3.11+ standard library only. Writes, next to this script:

  index.html              the current academic year
  <year>.html             one page per academic year, e.g. 2026-2027.html
  seminar.ics             calendar feed with every talk
  ics/<date>.ics          one calendar file per talk ("Add to calendar")
  flyers/<date>.html      one printable flyer per talk with a title
  schedule.txt            plain-text list of the current year's talks, for emails

Usage:
  python3 build.py                      # today = current date in Central time
  python3 build.py --today 2026-10-05   # build as if it were that day
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import os
import re
import sys
import tomllib
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parent

ROOT_KEYS = {"series", "years", "talks"}
SERIES_KEYS = {
    "title", "department", "university", "city", "organizer", "contact",
    "site_url", "timezone", "weekday", "default_start", "default_end", "blurb",
}
YEAR_KEYS = {"id", "terms", "blocked"}
TERM_KEYS = {"name", "start", "end"}
TALK_KEYS = {
    "date", "speaker", "affiliation", "position", "webpage", "title",
    "start", "end", "room", "note", "abstract", "bio", "reserved",
}
SEP = '<span class="sep"> · </span>'
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class DataError(Exception):
    pass


# ---------------------------------------------------------------- data

def is_date(x) -> bool:
    """A plain TOML date such as 2026-10-02 (a datetime is a date subclass, so exclude it)."""
    return isinstance(x, dt.date) and not isinstance(x, dt.datetime)


def load(path: Path) -> dict:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    series = data.get("series", {})
    years = data.get("years", [])
    talks = data.get("talks", [])

    def unknown(obj, allowed, where):
        extra = set(obj) - allowed
        if extra:
            raise DataError(f"{where}: unknown field(s) {sorted(extra)}; allowed: {sorted(allowed)}")

    unknown(data, ROOT_KEYS, "talks.toml")
    if not isinstance(series, dict):
        raise DataError("[series] must be a table")
    for name, items in (("years", years), ("talks", talks)):
        if not isinstance(items, list) or not all(isinstance(x, dict) for x in items):
            raise DataError(f"{name} must be written as [[{name}]] blocks")

    unknown(series, SERIES_KEYS, "[series]")
    missing = SERIES_KEYS - {"blurb"} - set(series)
    if missing:
        raise DataError(f"[series]: missing {sorted(missing)}")
    for key in series:
        if not isinstance(series[key], str):
            raise DataError(f"[series] {key} must be a quoted string")
    if not re.match(r"https?://[^/\s]+", series["site_url"]):
        raise DataError(f"[series] site_url must start with http:// or https://, got {series['site_url']!r}")
    if not series["site_url"].endswith("/"):
        series["site_url"] += "/"
    try:
        series["tz"] = ZoneInfo(series["timezone"])
    except (ZoneInfoNotFoundError, ValueError):
        raise DataError(f"[series] timezone {series['timezone']!r} is not a known time zone") from None
    series["start_t"] = parse_time(series["default_start"], "[series] default_start")
    series["end_t"] = parse_time(series["default_end"], "[series] default_end")
    check_order(series["start_t"], series["end_t"], "[series] default_start/default_end")
    if series["weekday"] not in WEEKDAYS:
        raise DataError(f"[series] weekday must be one of {WEEKDAYS}, got {series['weekday']!r}")
    weekday = WEEKDAYS.index(series["weekday"])

    if not years:
        raise DataError("no [[years]] entries")
    ids = set()
    for y in years:
        unknown(y, YEAR_KEYS, f"[[years]] {y.get('id')}")
        m = re.fullmatch(r"(\d{4})-(\d{4})", str(y.get("id", "")))
        if not m or int(m[2]) != int(m[1]) + 1:
            raise DataError(f"[[years]] id must look like 2026-2027, got {y.get('id')!r}")
        if y["id"] in ids:
            raise DataError(f"[[years]] {y['id']} appears twice")
        ids.add(y["id"])
        y["span"] = (dt.date(int(m[1]), 8, 1), dt.date(int(m[2]), 7, 31))
        y["label"] = f"{m[1]}–{m[2]}"
        y.setdefault("terms", [])
        y.setdefault("blocked", [])
        if not isinstance(y["terms"], list) or not all(isinstance(t, dict) for t in y["terms"]):
            raise DataError(f"[[years]] {y['id']}: terms must be a list of {{ name, start, end }}")
        for t in y["terms"]:
            unknown(t, TERM_KEYS, f"term in {y['id']}")
            if TERM_KEYS - set(t):
                raise DataError(f"term in {y['id']}: missing {sorted(TERM_KEYS - set(t))}")
            if not isinstance(t["name"], str):
                raise DataError(f"term in {y['id']}: name must be a quoted string")
            if not (is_date(t["start"]) and is_date(t["end"])):
                raise DataError(f"term {t['name']}: start/end must be plain dates (no quotes)")
            if t["start"] > t["end"]:
                raise DataError(f"term {t['name']}: start is after end")
            if not (y["span"][0] <= t["start"] and t["end"] <= y["span"][1]):
                raise DataError(f"term {t['name']}: must lie inside {y['id']} (August 1 to July 31)")
        terms = sorted(y["terms"], key=lambda t: t["start"])
        for a, b in zip(terms, terms[1:]):
            if b["start"] <= a["end"]:
                raise DataError(f"terms {a['name']} and {b['name']} overlap")
        if not isinstance(y["blocked"], list) or not all(is_date(d) for d in y["blocked"]):
            raise DataError(f"[[years]] {y['id']}: blocked must be a list of plain dates (no quotes)")
        y["talks"] = []
    years.sort(key=lambda y: y["span"][0])

    seen = set()
    for t in talks:
        where = f"[[talks]] {t.get('date')}"
        unknown(t, TALK_KEYS, where)
        d = t.get("date")
        if not is_date(d):
            raise DataError(f"{where}: date must be a plain date like 2026-10-02 (no quotes)")
        if d in seen:
            raise DataError(f"{where}: two talks on the same date")
        seen.add(d)
        if d.weekday() != weekday:
            print(f"warning: {d} is a {WEEKDAYS[d.weekday()]}, not a {series['weekday']}", file=sys.stderr)
        if "reserved" in t and not isinstance(t["reserved"], bool):
            raise DataError(f"{where}: reserved must be true or false (no quotes)")
        for key in TALK_KEYS - {"date", "reserved"}:
            if key in t and not isinstance(t[key], str):
                raise DataError(f"{where}: {key} must be a quoted string")
        for key in ("speaker", "affiliation", "position", "title", "room", "note"):
            if key in t:
                t[key] = " ".join(t[key].split())
        if not t.get("reserved") and not t.get("speaker"):
            raise DataError(f"{where}: needs a speaker, or reserved = true")
        if t.get("webpage") and not re.match(r"https?://", t["webpage"]):
            raise DataError(f"{where}: webpage must start with http:// or https://")
        t["start_t"] = parse_time(t["start"], where) if "start" in t else series["start_t"]
        t["end_t"] = parse_time(t["end"], where) if "end" in t else series["end_t"]
        check_order(t["start_t"], t["end_t"], f"{where}: start/end")
        owner = [y for y in years if y["span"][0] <= d <= y["span"][1]]
        if not owner:
            raise DataError(f"{where}: no [[years]] entry covers this date")
        t["year"] = owner[0]
        owner[0]["talks"].append(t)
    for y in years:
        y["talks"].sort(key=lambda t: t["date"])
        taken = {t["date"] for t in y["talks"]}
        blocked = set(y["blocked"])
        y["fridays"] = []  # (term name, [dates]) for every in-term, unblocked, untaken date
        for term in y["terms"]:
            d = term["start"] + dt.timedelta(days=(weekday - term["start"].weekday()) % 7)
            dates = []
            while d <= term["end"]:
                if d not in blocked and d not in taken:
                    dates.append(d)
                d += dt.timedelta(days=7)
            y["fridays"].append((term["name"], dates))
    return {"series": series, "years": years, "talks": sorted(talks, key=lambda t: t["date"])}


def parse_time(value, where) -> dt.time:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(value))
    if not m or int(m[1]) > 23 or int(m[2]) > 59:
        raise DataError(f"{where}: time must be HH:MM (24-hour), got {value!r}")
    return dt.time(int(m[1]), int(m[2]))


def check_order(start: dt.time, end: dt.time, where) -> None:
    if end <= start:
        raise DataError(f"{where}: end time {end:%H:%M} must be after start time {start:%H:%M}")


# ---------------------------------------------------------------- formatting

def esc(s) -> str:
    return html.escape(str(s), quote=True)


# Shown for a booked talk whose title is not known yet (talks.toml never says "TBA").
TITLE_TBA = "Title TBA"


def fmt_time(t: dt.time, meridiem=True) -> str:
    h = t.hour % 12 or 12
    s = f"{h}:{t.minute:02d}"
    return f"{s} {'AM' if t.hour < 12 else 'PM'}" if meridiem else s


def fmt_range(a: dt.time, b: dt.time) -> str:
    if (a.hour < 12) == (b.hour < 12):
        return f"{fmt_time(a, False)}–{fmt_time(b)}"
    return f"{fmt_time(a)}–{fmt_time(b)}"


def fmt_date(d: dt.date) -> str:
    return f"{d:%A}, {d:%B} {d.day}, {d.year}"


def fmt_short(d: dt.date) -> str:
    return f"{d:%a}, {d:%b} {d.day}"


def paragraphs(text: str) -> list[str]:
    return [" ".join(p.split()) for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def rich(text: str) -> str:
    """Paragraphs as HTML; $x$ becomes italic x."""
    out = []
    for p in paragraphs(text):
        p = re.sub(r"\$([^$]+)\$", r"<i>\1</i>", esc(p))
        out.append(f"<p>{p}</p>")
    return "\n".join(out)


def plain(text: str) -> str:
    return "\n\n".join(re.sub(r"\$([^$]+)\$", r"\1", p) for p in paragraphs(text))


def local_dt(t: dict, which: str, tz) -> dt.datetime:
    return dt.datetime.combine(t["date"], t[f"{which}_t"], tzinfo=tz)


def who(t: dict) -> str:
    return ", ".join(x for x in (t.get("position"), t.get("affiliation")) if x)


# ---------------------------------------------------------------- HTML

def page(title: str, description: str, body: str, css: str, extra_head: str = "", body_class: str = "") -> str:
    cls = f' class="{body_class}"' if body_class else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="stylesheet" href="{css}">
{extra_head}<!-- Generated by build.py from talks.toml. Edit talks.toml, not this file. -->
</head>
<body{cls}>
{body}
</body>
</html>
"""


def talk_card(t: dict, s: dict, *, upcoming: bool) -> str:
    d = t["date"]
    anchor = d.isoformat()
    permalink = f"{t['year']['id']}.html#{anchor}"
    start = local_dt(t, "start", s["tz"])
    when = [f'<time datetime="{start.isoformat(timespec="minutes")}">{esc(fmt_date(d))}</time>',
            esc(fmt_range(t["start_t"], t["end_t"]))]
    if t.get("room"):
        when.append(esc(t["room"]))
    parts = [f'<article class="talk" id="{anchor}">',
             f'<p class="talk-when">{SEP.join(when)}</p>']
    if t.get("reserved"):
        parts.append('<p class="talk-reserved">Reserved</p>')
        parts.append("</article>")
        return "\n".join(parts)
    if t.get("note"):
        parts.append(f'<p class="talk-note">{esc(t["note"])}</p>')
    name = esc(t["speaker"])
    if t.get("webpage"):
        name = f'<a href="{esc(t["webpage"])}">{name}</a>'
    parts.append(f'<h3 class="talk-title">{esc(t.get("title") or TITLE_TBA)}</h3>')
    parts.append(f'<p class="talk-speaker"><span class="name">{name}</span>'
                 + (f'<span class="aff">{esc(who(t))}</span>' if who(t) else "") + "</p>")
    if t.get("abstract"):
        parts.append(f"<details><summary>Abstract</summary>\n{rich(t['abstract'])}\n</details>")
    if t.get("bio"):
        parts.append(f"<details><summary>About the speaker</summary>\n{rich(t['bio'])}\n</details>")
    links = []
    if upcoming:
        links.append(f'<a href="ics/{anchor}.ics">Add to calendar</a>')
    if t.get("title"):
        links.append(f'<a href="flyers/{anchor}.html">Flyer</a>')
    links.append(f'<a href="{permalink}">Link to this talk</a>')
    parts.append(f'<p class="talk-links">{SEP.join(links)}</p>')
    parts.append("</article>")
    return "\n".join(parts)


def year_page(y: dict, data: dict, today: dt.date, current: dict) -> str:
    s = data["series"]
    is_current = y is current
    finished = y["span"][1] < today
    upcoming = [t for t in y["talks"] if t["date"] >= today]
    past = [t for t in y["talks"] if t["date"] < today]
    open_terms = [(name, [d for d in dates if d >= today]) for name, dates in y["fridays"]]
    open_terms = [(n, ds) for n, ds in open_terms if ds]
    mail = f'<a href="mailto:{esc(s["contact"])}">{esc(s["contact"])}</a>'
    webcal = "webcal://" + s["site_url"].split("://", 1)[1] + "seminar.ics"

    sections = []  # (id, nav label, html)
    if not finished:
        cards = "\n".join(talk_card(t, s, upcoming=True) for t in upcoming) or \
            "<p>No upcoming talks are scheduled yet. Check back soon.</p>"
        sections.append(("upcoming", "Upcoming", f"<h2>Upcoming talks</h2>\n{cards}"))
        if open_terms:
            lists = "\n".join(
                f'<h3>{esc(name)}</h3>\n<ul class="open-dates">'
                + "".join(f'<li><time datetime="{d.isoformat()}">{esc(fmt_short(d))}</time></li>' for d in ds)
                + "</ul>" for name, ds in open_terms)
            sections.append(("open", "Open dates", f"""<h2>Open dates</h2>
<p>These {esc(s['weekday'])}s are still available. To give a talk or to suggest a speaker, email {esc(s['organizer'])} at {mail}.</p>
{lists}"""))
        if past:
            cards = "\n".join(talk_card(t, s, upcoming=False) for t in reversed(past))
            sections.append(("past", "Past talks", f"<h2>Past talks</h2>\n{cards}"))
    else:
        cards = "\n".join(talk_card(t, s, upcoming=False) for t in y["talks"]) or "<p>No talks are listed for this year.</p>"
        sections.append(("talks", "Talks", f"<h2>Talks</h2>\n{cards}"))

    bands = []
    for i, (sid, _, inner) in enumerate(sections):
        tint = " band--tint" if i % 2 == 0 else ""
        bands.append(f'<section id="{sid}" class="band{tint}">\n<div class="wrap">\n{inner}\n</div>\n</section>')
    nav = "".join(f'<li><a href="#{sid}">{label}</a></li>' for sid, label, _ in sections)
    nav += '<li><a href="#about">About</a></li>'

    slot = f"{s['weekday']}s, {fmt_range(s['start_t'], s['end_t'])} Central time"
    actions = [f'<li><a class="primary" href="{esc(webcal)}">Subscribe to the calendar</a></li>',
               '<li><a href="seminar.ics">Download .ics</a></li>']
    if open_terms:
        actions.append('<li><a href="#open">Give a talk</a></li>')
    years_links = []
    for other in data["years"]:
        if other is y:
            years_links.append(f'<li><span aria-current="page">{esc(other["label"])}</span></li>')
        else:
            years_links.append(f'<li><a href="{other["id"]}.html">{esc(other["label"])}</a></li>')
    blurb = f"<p>{esc(s['blurb'])}</p>\n" if s.get("blurb") else ""
    bands.append(f"""<section id="about" class="band{' band--tint' if len(sections) % 2 == 0 else ''}">
<div class="wrap">
<h2>About the seminar</h2>
{blurb}<dl>
<dt>When</dt><dd>{esc(slot)}, unless a talk lists a different time.</dd>
<dt>Organizer</dt><dd>{esc(s['organizer'])}, {mail}</dd>
<dt>Calendar</dt><dd><a href="{esc(webcal)}">Subscribe</a> to have new talks appear in your calendar automatically, or <a href="seminar.ics">download the .ics file</a>.</dd>
<dt>Academic years</dt><dd><ul class="years">{''.join(years_links)}</ul></dd>
</dl>
</div>
</section>""")

    head = f"{s['university']} · {s['department']}"
    body = f"""<header class="masthead" id="top">
<div class="wrap">
<p class="kicker">{esc(s['department'])} · {esc(s['university'])}</p>
<h1>{esc(s['title'])}</h1>
<p class="when-where"><span class="date">{esc(y['label'])}</span><span>{esc(slot)}</span></p>
<ul class="actions">{''.join(actions)}</ul>
</div>
</header>

<nav class="toc" aria-label="On this page">
<div class="wrap">
<a class="toc-home" href="#top">{esc(s['title'])} {esc(y['label'])}</a>
<ul>{nav}</ul>
</div>
</nav>

{chr(10).join(bands)}

<footer class="band--tint">
<div class="wrap">
<p>{esc(s['title'])}, {esc(s['department'])}, {esc(s['university'])}, {esc(s['city'])}. Page last updated {esc(fmt_date(today).split(', ', 1)[1])}.</p>
</div>
</footer>"""
    title = f"{s['title']} {y['label']} · {s['university']}"
    desc = f"{s['title']}, {head}: schedule, abstracts and open dates for {y['label']}."
    alt = '<link rel="alternate" type="text/calendar" title="Seminar calendar" href="seminar.ics">\n'
    return page(title, desc, body, "style.css", alt)


def flyer_page(t: dict, s: dict) -> str:
    d = t["date"]
    when = [fmt_date(d), fmt_range(t["start_t"], t["end_t"]) + " Central time"]
    if t.get("room"):
        when.append(t["room"])
    # Long abstract + bio: step the type down so the flyer still prints on one page.
    size = len(t.get("abstract", "")) + len(t.get("bio", ""))
    density = " flyer--compact" if size > 2000 else " flyer--dense" if size > 1200 else ""
    sections = []
    if t.get("abstract"):
        sections.append(f'<section><h2>Abstract</h2>\n{rich(t["abstract"])}\n</section>')
    if t.get("bio"):
        sections.append(f'<section><h2>About the speaker</h2>\n{rich(t["bio"])}\n</section>')
    note = f'<p class="flyer-note">{esc(t["note"])}</p>' if t.get("note") else ""
    aff = f'<p class="flyer-aff">{esc(who(t))}</p>' if who(t) else ""
    url = s["site_url"].split("://", 1)[1].rstrip("/")
    body = f"""<p class="flyer-back"><a href="../{t['year']['id']}.html#{d.isoformat()}">Back to the seminar page</a> · Use your browser's Print command to print this flyer.</p>
<main class="flyer-page{density}">
<header class="flyer-head">
<p class="flyer-series">{esc(s['title'])}</p>
<p class="flyer-dept">{esc(s['department'])} · {esc(s['university'])}</p>
</header>
<p class="flyer-when">{''.join(f'<span>{esc(w)}</span>' for w in when)}</p>
{note}
<h1 class="flyer-title">{esc(t['title'])}</h1>
<p class="flyer-speaker">{esc(t['speaker'])}</p>
{aff}
{chr(10).join(sections)}
<footer class="flyer-foot"><span>Everyone is welcome.</span><span>{esc(url)}</span></footer>
</main>"""
    return page(f"{t['speaker']}: {t['title']} · {s['title']}", f"Flyer for the {s['title']} talk on {fmt_date(d)}.",
                body, "../style.css", body_class="flyer")


# ---------------------------------------------------------------- plain text

def schedule_text(y: dict, s: dict) -> str:
    """Short listing of one year's talks (date, time, room, speaker, affiliation, title) for emails."""
    def strip(x):
        return re.sub(r"\$([^$]+)\$", r"\1", x)

    blocks = [f"{s['title']}, {y['label']}\n{s['department']}, {s['university']}\n{s['site_url']}"]
    for t in y["talks"]:
        if t.get("reserved"):
            continue
        when = [fmt_date(t["date"]), fmt_range(t["start_t"], t["end_t"])]
        if t.get("room"):
            when.append(t["room"])
        lines = [", ".join(when), ", ".join(x for x in (t["speaker"], t.get("affiliation")) if x)]
        lines.append(strip(t.get("title") or TITLE_TBA))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


# ---------------------------------------------------------------- iCalendar

def ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics_fold(line: str) -> bytes:
    """Fold to at most 75 octets per line without splitting a UTF-8 character."""
    out, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > 75:
            out.append(cur)
            cur = b" "
        cur += b
    out.append(cur)
    return b"\r\n".join(out)


def ics_utc(x: dt.datetime) -> str:
    return x.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ics_calendar(talks: list[dict], s: dict, stamp: dt.date) -> bytes:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             "PRODID:-//The University of Alabama//Applied Mathematics Seminar build.py//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             f"X-WR-CALNAME:{ics_escape('UA ' + s['title'])}", f"X-WR-TIMEZONE:{s['timezone']}"]
    for t in talks:
        if t.get("reserved"):
            continue
        d = t["date"]
        url = f"{s['site_url']}{t['year']['id']}.html#{d.isoformat()}"
        summary = f"{s['title']}: {t['speaker']} — {t.get('title') or TITLE_TBA}"
        desc = [t["speaker"] + (f", {who(t)}" if who(t) else ""), t.get("title") or TITLE_TBA]
        if t.get("note"):
            desc.append(t["note"])
        if t.get("abstract"):
            desc.append(plain(t["abstract"]))
        desc.append(url)
        lines += ["BEGIN:VEVENT",
                  f"UID:{d:%Y%m%d}-applied-math-seminar@{s['site_url'].split('://', 1)[1].split('/', 1)[0]}",
                  f"DTSTAMP:{stamp:%Y%m%d}T000000Z",
                  f"DTSTART:{ics_utc(local_dt(t, 'start', s['tz']))}",
                  f"DTEND:{ics_utc(local_dt(t, 'end', s['tz']))}",
                  f"SUMMARY:{ics_escape(summary)}"]
        if t.get("room"):
            lines.append(f"LOCATION:{ics_escape(t['room'] + ', ' + s['university'] + ', ' + s['city'])}")
        lines += [f"DESCRIPTION:{ics_escape(chr(10).join(desc))}", f"URL:{url}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return b"\r\n".join(ics_fold(line) for line in lines) + b"\r\n"


# ---------------------------------------------------------------- main

def pick_current(years: list[dict], today: dt.date) -> dict:
    for y in years:
        if y["span"][0] <= today <= y["span"][1]:
            return y
    started = [y for y in years if y["span"][0] <= today]
    return started[-1] if started else years[0]


# Per-talk files the build owns: only these are ever deleted, and only when stale.
OWNED = {"ics": re.compile(r"\d{4}-\d{2}-\d{2}\.ics"), "flyers": re.compile(r"\d{4}-\d{2}-\d{2}\.html")}


def write_file(path: Path, payload: bytes) -> None:
    """Write via a temporary file and rename, so a reader never sees half a file."""
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_bytes(payload)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def build(data_path: Path, out: Path, today: dt.date) -> dict:
    data = load(data_path)
    s = data["series"]

    # Render everything first: if anything fails, the previous site is left untouched.
    current = pick_current(data["years"], today)
    files = {}  # path relative to out -> bytes
    written = []
    for y in data["years"]:
        text = year_page(y, data, today, current).encode("utf-8")
        files[f"{y['id']}.html"] = text
        written.append(f"{y['id']}.html")
        if y is current:
            files["index.html"] = text
            files["schedule.txt"] = schedule_text(y, s).encode("utf-8")
    booked = [t for t in data["talks"] if not t.get("reserved")]
    files["seminar.ics"] = ics_calendar(booked, s, today)
    for t in booked:
        files[f"ics/{t['date']}.ics"] = ics_calendar([t], s, today)
        if t.get("title"):
            files[f"flyers/{t['date']}.html"] = flyer_page(t, s).encode("utf-8")

    out.mkdir(parents=True, exist_ok=True)
    if out.resolve() != ROOT:
        files["style.css"] = (ROOT / "style.css").read_bytes()
    for sub in OWNED:
        d = out / sub
        if d.is_symlink() or (d.exists() and not d.is_dir()):
            raise DataError(f"{d} must be a plain folder (not a symlink or a file); move it away and rebuild")
        d.mkdir(exist_ok=True)
    for rel, payload in files.items():
        write_file(out / rel, payload)
    for sub, pattern in OWNED.items():
        for old in (out / sub).iterdir():
            if (pattern.fullmatch(old.name) and old.is_file() and not old.is_symlink()
                    and f"{sub}/{old.name}" not in files):
                old.unlink()  # a talk that was removed, renamed to reserved, or lost its title
    return {"current": current["id"], "years": written, "talks": len(booked),
            "flyers": sum(1 for t in booked if t.get("title")),
            "open": sum(len([d for d in ds if d >= today]) for _, ds in current["fridays"])}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=ROOT / "talks.toml")
    ap.add_argument("--out", type=Path, default=ROOT)
    ap.add_argument("--today", type=dt.date.fromisoformat,
                    help="build as if it were this date (YYYY-MM-DD); default: today in Central time")
    args = ap.parse_args(argv)
    today = args.today or dt.datetime.now(ZoneInfo("America/Chicago")).date()
    try:
        r = build(args.data, args.out, today)
    except (DataError, tomllib.TOMLDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"built {', '.join(r['years'])} (index = {r['current']}) as of {today}: "
          f"{r['talks']} talks, {r['flyers']} flyers, {r['open']} open dates, schedule.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
