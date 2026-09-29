# Applied Mathematics Seminar — website

Website for the **Applied Mathematics Seminar**, Department of Mathematics, The University of Alabama.
Fridays, 11:00–11:50 AM Central time. Organizer: Jia Zhao (jia.zhao@ua.edu).

Live site: https://jiazhaomath.github.io/seminar/

Sibling site: [UASAM 2026](https://jiazhaomath.github.io/UASAM2026/), whose stylesheet this one adapts.

## What is here

| File | Purpose |
|---|---|
| `talks.toml` | **The only file you edit.** Series settings, academic years, and one entry per talk. Everything in it is public |
| `build.py` | Generates the site from `talks.toml`. Python 3.11+ standard library only, no packages |
| `style.css` | Hand-written stylesheet (UA crimson, serif, dark mode, print styles for the flyers) |
| `index.html` | Generated: the current academic year |
| `2026-2027.html` | Generated: one page per academic year. Permanent anchors such as `2026-2027.html#2026-10-02` |
| `seminar.ics` | Generated: calendar feed with every talk (subscribe with `webcal://jiazhaomath.github.io/seminar/seminar.ics`) |
| `ics/<date>.ics` | Generated: "Add to calendar" file for one talk |
| `flyers/<date>.html` | Generated: one-page printable flyer for each talk that has a title |
| `schedule.txt` | Generated: plain-text list of the current year's talks (date, time, room, speaker, affiliation, title) to paste into emails |
| `tests/test_build.py` | Checks, including a privacy scan of the data and every generated file |
| `.nojekyll` | Tells GitHub Pages to serve the files as they are |

Never edit the generated files by hand; the next build overwrites them.

## Add or update a talk

1. Open `talks.toml` and add a block at the end (the order does not matter):

   ```toml
   [[talks]]
   date = 2027-01-22
   speaker = "Jane Doe"
   position = "Associate Professor"
   affiliation = "Some University"
   webpage = "https://example.edu/~jdoe"
   title = "A talk title"
   room = "GP 346"
   abstract = '''
   First paragraph.

   Second paragraph, with $p$ in italics.
   '''
   bio = '''
   Short bio.
   '''
   ```

   Only `date` and `speaker` are required. Leave out anything not yet known and never write "TBA":
   the page simply shows the fields that exist (a missing title is shown as "Title TBA" automatically).
   `start`/`end` default to the regular slot (11:00–11:50 AM);
   a missing `room` is left off the page. For an unusual time or room also add `note = "…"`, which is highlighted.

2. To hold a date before the speaker can be named, add `reserved = true` instead of a speaker. The page shows
   "Reserved", the date disappears from the open list, and it is left out of the calendar.

3. Build and check:

   ```sh
   python3 build.py
   python3 -m unittest discover tests
   open index.html
   ```

   `build.py` prints how many talks, flyers and open dates it wrote. It stops with a clear error on a typo in a
   field name, a duplicate date, or a date outside every academic year.

4. Publish:

   ```sh
   git add -A
   git commit -m "Add Jane Doe, January 22"
   git push
   ```

   GitHub Pages redeploys from the `main` branch root within about a minute.

"Upcoming", "Past" and "Open dates" are worked out when you run the build. Rebuild and push after a talk
has happened so that it moves to "Past talks".

## Open dates

Open dates are not typed in. They are every Friday inside a term (the `terms` of each `[[years]]` entry), from
today on, that is neither listed in `blocked` nor taken by a talk. Blocked dates (holidays, breaks) never appear
on the site.

## Start a new academic year

Add a `[[years]]` entry with its terms and blocked dates from the
[UA academic calendar](https://academic-calendar.oitapps.ua.edu/academicCalendar):

```toml
[[years]]
id = "2027-2028"
terms = [
  { name = "Fall 2027", start = 2027-08-18, end = 2027-12-03 },
  { name = "Spring 2028", start = 2028-01-12, end = 2028-04-28 },
]
blocked = []
```

A year runs from August 1 to July 31. From August 1 on, `index.html` shows the new year, and the old year's page
stays as an archive and keeps its links.

## Privacy

The repository is public. `talks.toml` must hold only what may appear on the website: no hosts, email threads,
booking status or private notes. `tests/test_build.py` fails if such words appear in the data or in the site.
