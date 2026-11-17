# Independent adversarial review — tonight

Reviewer: independent subagent (did not build the tool). Date: 2026-11-17.
Environment: `~/workspace/astro-tools/.venv` (astropy 8.0.2, astroplan 0.10.1),
plus a fresh venv for the install test. The gauntlet was run locally; at review time nothing had been published.

## What was checked

- **Full test battery** (`run_tests.py`): originally **16 tests, all passing**.
- **README demo** reproduced in the project venv and in a fresh venv:
  output matches the README **exactly** (diff-clean, including Moon
  separations 90/101/111/118°, illumination 40%, dusk 01:21 / dawn 07:54 UTC).
- **Independent oracle** (own astropy/manual code, not the tool's):
  - Dusk/dawn: manual Sun-altitude crossings (topocentric RA/Dec +
    apparent sidereal time, spherical formula) at 01:20:13 / 07:52:58 UTC
    vs tool 01:21:58 / 07:54:29 — differences ≈ **1.5–1.7 min**, inside
    the README's "good to a few minutes".
  - Target altitude/airmass at best times: manual hour-angle formula
    agrees with tool min-airmass to **≤0.0003** for targets culminating
    inside the night, ≤0.01 for targets still rising at dawn.
  - Observable windows: manual 1-minute alt ≥ 30° scan agrees with tool
    window starts to **≤0.8 min**.
  - **Moon separation (parallax-sensitive)**: tool transforms the target
    into the Moon's topocentric GCRS frame. Verified correct: pure
    spherical formula from the topocentric Moon RA/Dec agrees to
    **≤0.006°**, AltAz-frame separation agrees to **0.000°**, for all
    four demo targets. Caution recorded: the naive
    `target.separation(get_body("moon", …))` in ICRS is *wrong* by up to
    ~73° (M42: 28.7° naive vs 101.4° correct), because transforming a
    nearby body to barycentric ICRS corrupts its direction — the tool
    does **not** make that mistake; the reported earlier parallax bug
    fix is present and correct.
  - Moon illumination: independent Sun–Moon–Earth phase-angle
    computation gives 0.3974 vs tool 0.3974 (**diff 0.0000**).
- **Offline behaviour**: verified two ways — (1) real network namespace
  (`unshare -n`), (2) sockets blocked in-process with an empty HOME.
  Full demo plan produced both times. The offline claim is true.
- **Fresh install**: new venv + `pip install ~/workspace/astro-tools/tonight`
  succeeded (astropy 8.0.2 / astroplan 0.10.1 resolved); demo reproduced.
  Note: /tmp is a 512 MB tmpfs shared with other tools' venvs and ran
  out of space mid-review; the fresh venv was therefore created on disk
  (path under /tmp pointed at it). The install itself is unaffected.
- **Adversarial inputs**: polar sites (±90°, ±85°, ±78°), equator,
  circumpolar targets, targets never rising / up in daylight only,
  two-window long winter nights, malformed CSVs (empty, missing/short
  rows, duplicate/uppercase/spaced headers, quoted commas, unbalanced
  quotes), sexagesimal edge cases (`24:00:00`, `12:60:00`, `-00:30:00`
  — negative-zero Dec is handled correctly), extreme dates
  (0001/9999/1800/2200), non-finite values (nan/inf) in site, RA, Dec,
  priority, unwritable `--out` path (clean error, exit 2), missing CLI
  args (argparse exit 2).

## Findings and fixes

| # | Severity | Finding | Status |
|---|----------|---------|--------|
| 1 | Medium | **Polar continuous night misreported.** At lat ±90 (and +85) in winter the Sun stays below −18° all day (sampled range −28°…−18°), yet the tool reported "no astronomical night (the Sun never gets 18 degrees below the horizon)" — the opposite of the truth — with all targets unobservable. | **Fixed (reason, not planning):** `plan_night` now samples the Sun over 24 h when no dusk/dawn pair exists and distinguishes continuous night (`NightPlan.continuous_night`, honest summary + per-target reason). Planning a 24-hour night would change the documented one-dusk-to-dawn design, so it is **reported, not implemented** (see below). |
| 2 | Medium | **Non-finite inputs silently accepted.** `--site "0,0,nan"` / `inf` height produced a bogus "no astronomical night" plan; RA `nan`/`inf` produced the nonsense reason "highest during the night: nan degrees — it is up in daylight"; priority `nan` silently corrupted ranking order. | **Fixed:** finite checks in `parse_site`, `_parse_ra`, `_parse_dec`, and priority parsing — all now clean `TonightError`s (exit 2 via CLI). |
| 3 | Medium | **Two-window nights silently truncated.** On long winter nights a target can be above airmass 2 in two separate stretches (verified: lat 55, Dec +40/+50/+60, several RAs, 12.2 h night — 2 runs). The tool reports only the longest run; the second window, and its contribution to ranking, are invisible and undocumented. | **Not fixed — documented + reported.** A correct fix needs a multi-window output schema (a design change). README Limits now states the one-window behaviour explicitly. |
| 4 | Low | **Date format not actually enforced.** `2026-2-5` was accepted despite the documented `YYYY-MM-DD`; years 0001/1800/2200/9999 produced plans amid ERFA "dubious year" warnings leaked to stderr. | **Fixed:** strict `YYYY-MM-DD` regex + validity check, and years restricted to 1900–2100 (the built-in ephemeris/ERFA range) with a clean error. |
| 5 | Low | **Out-of-range sexagesimal silently normalised.** RA `24:00:00` and `12:60:00` were accepted (astropy `IllegalHourWarning`/`IllegalMinuteWarning` leaked to stderr, values silently wrapped/carried). | **Fixed:** Angle parsing now treats astropy range warnings as parse errors → clean `TonightError`. |
| 6 | Low | README Limits was incomplete: no mention of the one-window limit (finding 3), polar continuous night, or the supported year range. | **Fixed:** three bullets added to Limits. The rest of Limits was verified honest: "plane-parallel airmass … good to a few minutes" (measured ≤0.8 min on windows, ~1.7 min on twilight), "IERS-B … well under a second", "built-in ephemeris (arcminute-level)", "ideal horizon", fully-offline claim — all stand. |
| 7 | Info | `best_time`/`min_airmass` are 5-minute-grid samples; for targets still rising at dawn (Acrux, Omega Centauri in the demo) `best_time` equals dawn exactly. This is correct behaviour for a truncated window and is covered by the "planning-grade" limit. | No change. |
| 8 | Info | Plain-degree RA outside 0–360 (e.g. 361, −10) is silently wrapped by SkyCoord. Common astronomical leniency; left as-is and noted here. | No change. |
| 9 | Info | The `.venv`'s installed copy of `core.py` differed from the local tree by one unused import (`dataclass, field`) at review start — functionally identical; the fresh-install test used the local tree. | No change. |

## Fixes applied (all inside this directory)

- `tonight/core.py`: finite-value validation (site/RA/Dec/priority);
  sexagesimal range warnings → errors; strict date format + 1900–2100
  year guard; continuous-night detection and honest reporting
  (`NightPlan.continuous_night`, summary text, per-target reason).
- `tests/test_tonight.py`: 6 regression tests added
  (`TestAdversarialReviewFixes`).
- `README.md`: Limits section completed (one-window, continuous
  night, year range).

## Final state

- Tests: **22 run, all passing** (16 original + 6 new).
- README demo after fixes: **unchanged, still matches exactly**.
- Fresh-venv install of the fixed tree: **succeeds**; demo and
  offline (`unshare -n`) run verified again after the fixes.

## Reported, not fixed (needs a design decision)

1. **Plan polar continuous night as a 24-hour night** instead of only
   reporting it — changes the documented dusk-to-dawn design.
2. **Multiple observable windows per target** (finding 3) — needs an
   output-schema change (extra rows or a windows list) and a ranking
   decision (longest stretch vs total time up).
