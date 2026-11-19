# tonight

**Give it a CSV of targets, an observing site and a date — get back a ranked observing plan for that night: when each target is up, how good it gets, and in what order to observe.**

## Install

```console
$ pip install git+https://github.com/RakTikoo/tonight
```

Needs Python 3.10+; installs astropy and astroplan. Everything runs
**offline** — the site is given as coordinates (never a name lookup),
and Earth-rotation data comes from astropy's bundled IERS-B table
(auto-download is switched off; see *Limits*).

## Usage

```console
$ tonight plan targets.csv --site "-31.2733,-70.7033,2300" --date 2026-12-15 --out plan.csv
```

- `targets.csv` — columns `name,ra,dec` plus an optional `priority`.
  RA/Dec may be plain degrees (`83.822`, `-5.391`) or sexagesimal
  (`05:35:17.3`, `-05:23:28` — RA in hours, Dec in degrees).
- `--site` — `"lat,lon,height_m"`: latitude and longitude in degrees
  (south/west negative), height in metres. Coordinates only, by design.
- `--date` — the night date, `YYYY-MM-DD` (default: today). The date is
  anchored in UTC: the plan covers the first astronomical night
  (sunset→sunrise with the Sun 18° down) that begins after 12:00 UTC
  on that date.
- `--out` — where to write the full plan CSV (optional; a summary is
  always printed to the terminal).

For each target the plan works out, over that night:

- the **observable window** where airmass < 2 (start/end),
- the **minimum airmass** and when it happens,
- the **Moon separation** at that best moment, and the night's Moon
  illumination.

Targets that never get above airmass 2 that night are listed separately
with a plain reason ("never rises above airmass 2 at this site",
"up in daylight only", …). Dates with no astronomical night at all
(high-latitude summer) are reported cleanly, not crashed on.

**Ranking:** if the CSV has a `priority` column, higher priority is
scheduled first. Within that (or with no priority column), longer
observable windows come first, then lower minimum airmass.

## Demo

`examples/targets.csv` for a site near Cerro Tololo, Chile, on the
night of 2026-12-15:

```console
$ tonight plan examples/targets.csv --site "-31.2733,-70.7033,2300" --date 2026-12-15 --out plan.csv
Night plan — 2026-12-15
Site: lat -31.2733, lon -70.7033, height 2300 m
Astronomical night: 2026-12-16 01:21 UTC -> 2026-12-16 07:54 UTC  (local solar 20:39 -> 03:11, UTC-4.71h from longitude)
Moon illumination tonight: 40%

Observe in this order:
 1. Tarantula Nebula — up 01:21->07:54 UTC (6.5 h), best airmass 1.27 at 04:40 UTC, Moon 90 deg away
 2. M42 Orion Nebula — up 01:21->07:54 UTC (6.5 h), best airmass 1.11 at 04:40 UTC, Moon 101 deg away
 3. Acrux — up 05:53->07:54 UTC (2.0 h), best airmass 1.45 at 07:54 UTC, Moon 111 deg away
 4. Omega Centauri — up 07:18->07:54 UTC (0.6 h), best airmass 1.70 at 07:54 UTC, Moon 118 deg away

Unobservable tonight:
 - M31 Andromeda Galaxy — never rises above airmass 2 at this site (highest it ever gets: 17 degrees)

Full plan written to plan.csv
```

(The Tarantula Nebula leads because the example CSV gives it
priority 10.) The CSV has one row per target with the window in UTC
and local solar time, window length, minimum airmass, best time, Moon
separation and the unobservable reasons.

## About the times — please read

Every time is printed in **UTC**, plus a **local solar time** derived
from the site's longitude (15° of longitude = 1 hour). `tonight` does
*not* know your site's civil time zone — it has no time-zone database
and never looks one up — so the "local" column is mean solar time,
which can differ from clock time at the site by an hour or more
(daylight saving, time-zone borders). Use the UTC column for anything
that must be exact, and treat the local column as a rough guide.

## Limits

- **Planning-grade accuracy.** Airmass uses the plane-parallel
  approximation on a 5-minute grid; window edges are interpolated.
  Good to a few minutes — not a substitute for your mount's software
  at the telescope.
- **IERS-B, not IERS-A.** Earth-rotation finals (IERS-A) require a
  download, so `tonight` runs fully offline on astropy's bundled
  IERS-B predictions instead. The difference is well under a second
  of time — invisible at planning precision.
- **Built-in ephemeris.** Moon positions come from astropy's built-in
  ephemeris (arcminute-level), not the JPL tables.
- **Ideal horizon.** Windows assume a flat horizon at altitude 0° and
  no weather, no twilight observing, and no telescope limits. If your
  site has mountains to the west, your real window is shorter.
- **One night, one site, target list only.** No multi-night trips, no
  site-name lookup, no equipment or exposure planning.
- **Ranking uses the longest window.** If a target is above airmass
  2 in two separate stretches of the same night — it dips below
  altitude 30° and rises again — every stretch is reported: the
  summary lists each one, and the CSV adds `window_count` and
  `total_window_hours` columns. But the ranking still uses the
  longest single stretch, so a broken-up night does not outrank a
  solid window of the same length.
- **Polar continuous night is reported, not planned.** Where the Sun
  stays more than 18° below the horizon all day (polar winter) there
  is no single dusk-to-dawn night; the date is reported as a
  continuous night with all targets unobservable, not planned as a
  24-hour night. Dates are supported for years 1900–2100, the range
  of the built-in ephemeris.

## Tests

```console
$ python3 run_tests.py
```

## Use with an AI agent

This repo ships a [SKILL.md](SKILL.md) written to the Agent Skills open
standard. If your coding agent supports skills, point it at this repo and
it can install tonight, run it on your target lists, and read the results
for you. The skill works as documented when the repo is cloned under its
real name (`tonight`) — the standard matches a skill to its folder name.

## License

MIT — see `LICENSE`.
