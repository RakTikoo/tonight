"""Core planning logic for tonight.

Give it a list of targets, an observing site (coordinates, never a name
lookup) and a date, and it works out — for the astronomical night that
begins on that date — when each target is above airmass 2, how good it
gets, where the Moon is, and in what order to observe.

Everything runs offline: IERS auto-download is switched off (astropy's
bundled IERS-B table is used instead, which is plenty accurate for
planning), and the site is always given as coordinates so no name
resolution is ever needed.
"""

from __future__ import annotations

import csv
import math
import re
import warnings
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from astropy import units as u
from astropy.coordinates import Angle, EarthLocation, SkyCoord, get_body
from astropy.time import Time
from astropy.utils import iers

# Offline by design: never download IERS-A; the bundled IERS-B fallback
# is accurate to well under a second of time, far finer than a plan needs.
iers.conf.auto_download = False

from astroplan import AstroplanWarning, Observer, moon_illumination

# Airmass 2 == altitude 30 degrees (plane-parallel approximation).
AIRMASS_LIMIT = 2.0
ALT_LIMIT_DEG = 30.0
GRID_STEP_DAYS = 5.0 / 1440.0  # 5-minute sampling across the night


class TonightError(Exception):
    """A user-facing error (bad input), reported without a traceback."""


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------


@dataclass
class Site:
    lat: float  # degrees
    lon: float  # degrees, east positive
    height_m: float

    @property
    def location(self) -> EarthLocation:
        return EarthLocation(
            lat=self.lat * u.deg, lon=self.lon * u.deg, height=self.height_m * u.m
        )

    @property
    def utc_offset_hours(self) -> float:
        """Mean solar time offset from UTC implied by the longitude."""
        return self.lon / 15.0


def parse_site(text: str) -> Site:
    """Parse a --site string of the form "lat,lon,height_m"."""
    parts = [p.strip() for p in (text or "").split(",")]
    if len(parts) != 3:
        raise TonightError(
            f'bad site "{text}" — expected "lat,lon,height_m", '
            'e.g. --site "-31.2733,-70.7033,2300"'
        )
    try:
        lat, lon, height = (float(p) for p in parts)
    except ValueError:
        raise TonightError(
            f'bad site "{text}" — lat, lon and height must all be numbers'
        ) from None
    if not (math.isfinite(lat) and math.isfinite(lon) and math.isfinite(height)):
        raise TonightError(
            f'bad site "{text}" — lat, lon and height must all be finite numbers'
        )
    if not -90.0 <= lat <= 90.0:
        raise TonightError(f"bad site — latitude {lat} is outside -90..90")
    if not -180.0 <= lon <= 180.0:
        raise TonightError(f"bad site — longitude {lon} is outside -180..180")
    return Site(lat=lat, lon=lon, height_m=height)


@dataclass
class Target:
    name: str
    coord: SkyCoord
    priority: float = 0.0


def _parse_angle(text: str, unit, where: str, kind: str, example: str) -> float:
    """Parse a sexagesimal angle, treating astropy's range warnings
    (hour 24, minute 60, …) as errors instead of silent normalisation."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            return float(Angle(text, unit=unit).degree)
    except Exception:
        raise TonightError(
            f"{where}: cannot parse {kind} {text!r} (use {example})"
        ) from None


def _parse_ra(text: str, where: str) -> float:
    """RA as degrees: a plain number is degrees; 'hh:mm:ss' is hours."""
    text = text.strip()
    try:
        value = float(text)
    except ValueError:
        value = _parse_angle(
            text, u.hourangle, where, "RA",
            "degrees, e.g. 83.822, or sexagesimal hours, e.g. 05:35:17",
        )
    if not math.isfinite(value):
        raise TonightError(f"{where}: RA {text!r} is not a finite number")
    return value


def _parse_dec(text: str, where: str) -> float:
    """Dec as degrees: a plain number is degrees; 'dd:mm:ss' is degrees."""
    text = text.strip()
    try:
        value = float(text)
    except ValueError:
        value = _parse_angle(
            text, u.deg, where, "Dec",
            "degrees, e.g. -5.391, or sexagesimal, e.g. -05:23:28",
        )
    if not math.isfinite(value):
        raise TonightError(f"{where}: Dec {text!r} is not a finite number")
    return value


def parse_targets(path: str) -> tuple[list[Target], bool]:
    """Read the targets CSV. Returns (targets, has_priority_column)."""
    try:
        fh = open(path, newline="", encoding="utf-8-sig")
    except OSError as exc:
        raise TonightError(f"cannot read targets file {path!r}: {exc.strerror or exc}") from None
    with fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise TonightError(f"targets file {path!r} is empty")
        fields = {f.strip().lower(): f for f in reader.fieldnames if f}
        missing = [c for c in ("name", "ra", "dec") if c not in fields]
        if missing:
            raise TonightError(
                f"targets file {path!r} is missing required column(s): "
                + ", ".join(missing)
                + " (required: name, ra, dec; optional: priority)"
            )
        has_priority = "priority" in fields
        targets: list[Target] = []
        for lineno, row in enumerate(reader, start=2):
            name = (row.get(fields["name"]) or "").strip()
            ra_raw = (row.get(fields["ra"]) or "").strip()
            dec_raw = (row.get(fields["dec"]) or "").strip()
            if not name and not ra_raw and not dec_raw:
                continue  # blank line
            where = f"{path} row {lineno}" + (f" ({name})" if name else "")
            if not name:
                raise TonightError(f"{path} row {lineno}: target has no name")
            ra = _parse_ra(ra_raw, where)
            dec = _parse_dec(dec_raw, where)
            if not -90.0 <= dec <= 90.0:
                raise TonightError(f"{where}: Dec {dec} is outside -90..90")
            priority = 0.0
            if has_priority:
                raw = (row.get(fields["priority"]) or "").strip()
                if raw:
                    try:
                        priority = float(raw)
                    except ValueError:
                        raise TonightError(
                            f"{where}: priority {raw!r} is not a number"
                        ) from None
                    if not math.isfinite(priority):
                        raise TonightError(
                            f"{where}: priority {raw!r} is not a finite number"
                        )
            targets.append(
                Target(name=name, coord=SkyCoord(ra=ra * u.deg, dec=dec * u.deg),
                       priority=priority)
            )
    if not targets:
        raise TonightError(f"no targets found in {path!r}")
    return targets, has_priority


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------


@dataclass
class TargetResult:
    name: str
    priority: float
    observable: bool
    reason: str = ""
    window_start: Time | None = None
    window_end: Time | None = None
    window_hours: float = 0.0
    min_airmass: float | None = None
    best_time: Time | None = None
    moon_sep_deg: float | None = None


@dataclass
class NightPlan:
    site: Site
    date_str: str
    dusk: Time | None
    dawn: Time | None
    moon_illumination: float | None  # 0..1, for the middle of the night
    results: list[TargetResult]  # observable (ranked) first, then unobservable
    has_priority: bool = False
    no_night: bool = False
    # True when there is no dusk/dawn pair because the Sun stays more
    # than 18 degrees below the horizon all day (polar continuous
    # night) — the opposite of the no-darkness case. Such dates are
    # reported, not planned (see README Limits).
    continuous_night: bool = False


def moon_separation_deg(coord: SkyCoord, time: Time, location: EarthLocation) -> float:
    """Angular separation in degrees between a target and the Moon."""
    moon = get_body("moon", time, location)
    # Compare in the Moon's own frame so the separation is a pure rotation.
    return float(coord.transform_to(moon.frame).separation(moon).degree)


def _is_missing(t) -> bool:
    """astroplan returns a masked Time when an event never happens."""
    if t is None:
        return True
    mask = getattr(t, "mask", None)
    if mask is None:
        return False
    try:
        return bool(np.any(mask))
    except Exception:
        return False


def _longest_run(mask: np.ndarray) -> tuple[int, int] | None:
    """(start, end) inclusive indices of the longest True run, or None."""
    padded = np.concatenate(([False], mask, [False]))
    edges = np.flatnonzero(np.diff(padded.astype(int)))
    starts, ends = edges[0::2], edges[1::2]  # ends exclusive
    if len(starts) == 0:
        return None
    k = int(np.argmax(ends - starts))
    return int(starts[k]), int(ends[k]) - 1


def _cross_time(t_a: Time, t_b: Time, alt_a: float, alt_b: float,
                level: float = ALT_LIMIT_DEG) -> Time:
    """Interpolated time at which altitude crosses `level` between samples."""
    if alt_b == alt_a:
        return t_b
    frac = (level - alt_a) / (alt_b - alt_a)
    frac = min(1.0, max(0.0, frac))
    return Time(t_a.jd + frac * (t_b.jd - t_a.jd), format="jd")


def _plan_target(observer: Observer, site: Site, target: Target,
                 times: Time) -> TargetResult:
    altaz = observer.altaz(times, target.coord)
    alt = np.asarray(altaz.alt.deg, dtype=float)
    am = np.asarray(altaz.secz.value, dtype=float)
    ok = np.isfinite(am) & (am > 0.0) & (am < AIRMASS_LIMIT)
    run = _longest_run(ok)
    if run is None:
        dec = float(target.coord.dec.degree)
        highest_ever = 90.0 - abs(site.lat - dec)
        if highest_ever <= ALT_LIMIT_DEG:
            reason = (
                "never rises above airmass 2 at this site "
                f"(highest it ever gets: {highest_ever:.0f} degrees)"
            )
        else:
            reason = (
                "never above airmass 2 during darkness tonight "
                f"(highest during the night: {alt.max():.0f} degrees — "
                "it is up in daylight)"
            )
        return TargetResult(name=target.name, priority=target.priority,
                            observable=False, reason=reason)
    s, e = run
    start = times[s] if s == 0 else _cross_time(times[s - 1], times[s], alt[s - 1], alt[s])
    end = times[e] if e == len(times) - 1 else _cross_time(times[e], times[e + 1], alt[e], alt[e + 1])
    seg = am[s:e + 1]
    k = s + int(np.argmin(seg))
    best_time = times[k]
    return TargetResult(
        name=target.name,
        priority=target.priority,
        observable=True,
        window_start=start,
        window_end=end,
        window_hours=float((end - start).to_value(u.hour)),
        min_airmass=float(am[k]),
        best_time=best_time,
        moon_sep_deg=moon_separation_deg(target.coord, best_time, site.location),
    )


def plan_night(site: Site, targets: list[Target], date_str: str,
               has_priority: bool = False) -> NightPlan:
    """Build the plan for the astronomical night beginning on `date_str`.

    The date is anchored in UTC: the plan covers the first astronomical
    night (sunset to sunrise, Sun 18 degrees down) that begins after
    12:00 UTC on that date.
    """
    if not isinstance(date_str, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", date_str
    ):
        raise TonightError(f"bad date {date_str!r} — expected YYYY-MM-DD")
    try:
        parsed = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise TonightError(f"bad date {date_str!r} — expected YYYY-MM-DD") from None
    if not 1900 <= parsed.year <= 2100:
        # Outside this range the built-in ephemeris and the bundled
        # IERS-B table are not valid (ERFA warns "dubious year"), so a
        # plan would be quietly unreliable rather than merely rough.
        raise TonightError(
            f"bad date {date_str!r} — year must be between 1900 and 2100 "
            "(the range the built-in ephemeris supports)"
        )
    observer = Observer(location=site.location)
    midday = Time(f"{date_str} 12:00:00", scale="utc")
    # astroplan warns "target always/never up" for polar days/nights;
    # we detect and report those cases ourselves, so keep stderr clean.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", AstroplanWarning)
        dusk = observer.sun_set_time(midday, which="next", horizon=-18 * u.deg)
        dawn = None
        if not _is_missing(dusk):
            dawn = observer.sun_rise_time(dusk, which="next", horizon=-18 * u.deg)
    if _is_missing(dusk) or _is_missing(dawn):
        # A missing dusk/dawn pair has two opposite causes: the Sun
        # never gets 18 degrees down (no darkness, polar summer) or it
        # never gets back up to 18 degrees down (continuous night,
        # polar winter). Sample the Sun over the date's 24 hours to
        # tell them apart so the reported reason is the true one.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", AstroplanWarning)
            samples = Time(
                np.linspace(midday.jd, midday.jd + 1.0, 25), format="jd"
            )
            sun_alts = np.asarray(
                observer.sun_altaz(samples).alt.deg, dtype=float
            )
        continuous = bool(np.all(sun_alts < -18.0))
        if continuous:
            reason = (
                "continuous astronomical night on this date at this site "
                "(the Sun stays more than 18 degrees below the horizon "
                "all day) — polar continuous night is reported, not planned"
            )
        else:
            reason = (
                "no astronomical night on this date at this site "
                "(the Sun never gets 18 degrees below the horizon)"
            )
        results = [
            TargetResult(
                name=t.name, priority=t.priority, observable=False,
                reason=reason,
            )
            for t in targets
        ]
        return NightPlan(site=site, date_str=date_str, dusk=None, dawn=None,
                         moon_illumination=None, results=results,
                         has_priority=has_priority, no_night=True,
                         continuous_night=continuous)

    n_steps = max(2, int(round((dawn.jd - dusk.jd) / GRID_STEP_DAYS)) + 1)
    times = Time(np.linspace(dusk.jd, dawn.jd, n_steps), format="jd")
    mid = dusk + (dawn - dusk) / 2.0
    illum = float(moon_illumination(mid))

    results = [_plan_target(observer, site, t, times) for t in targets]
    observable = [r for r in results if r.observable]
    unobservable = [r for r in results if not r.observable]
    if has_priority:
        observable.sort(key=lambda r: (-r.priority, -r.window_hours, r.min_airmass))
    else:
        observable.sort(key=lambda r: (-r.window_hours, r.min_airmass))
    return NightPlan(site=site, date_str=date_str, dusk=dusk, dawn=dawn,
                     moon_illumination=illum, results=observable + unobservable,
                     has_priority=has_priority, no_night=False)


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------


def _fmt_dt(t: Time | None) -> str:
    return "" if t is None else t.strftime("%Y-%m-%d %H:%M")


def _fmt_hm(t: Time | None) -> str:
    return "" if t is None else t.strftime("%H:%M")


def _fmt_local(t: Time | None, site: Site) -> str:
    if t is None:
        return ""
    return (t + site.utc_offset_hours * u.hour).strftime("%Y-%m-%d %H:%M")


def _fmt_local_hm(t: Time | None, site: Site) -> str:
    if t is None:
        return ""
    return (t + site.utc_offset_hours * u.hour).strftime("%H:%M")


def write_plan_csv(plan: NightPlan, path: str) -> None:
    site = plan.site
    try:
        fh = open(path, "w", newline="", encoding="utf-8")
    except OSError as exc:
        raise TonightError(f"cannot write plan file {path!r}: {exc.strerror or exc}") from None
    with fh:
        w = csv.writer(fh)
        w.writerow([
            "rank", "name", "priority", "status", "reason",
            "window_start_utc", "window_end_utc",
            "window_start_local_solar", "window_end_local_solar",
            "window_hours", "min_airmass", "best_time_utc",
            "moon_separation_deg", "moon_illumination_pct",
        ])
        illum_pct = "" if plan.moon_illumination is None else f"{plan.moon_illumination * 100:.0f}"
        rank = 0
        for r in plan.results:
            if r.observable:
                rank += 1
                w.writerow([
                    rank, r.name, f"{r.priority:g}", "observable", "",
                    _fmt_dt(r.window_start), _fmt_dt(r.window_end),
                    _fmt_local(r.window_start, site), _fmt_local(r.window_end, site),
                    f"{r.window_hours:.2f}", f"{r.min_airmass:.2f}",
                    _fmt_dt(r.best_time), f"{r.moon_sep_deg:.1f}", illum_pct,
                ])
            else:
                w.writerow([
                    "", r.name, f"{r.priority:g}", "unobservable", r.reason,
                    "", "", "", "", "", "", "", "", illum_pct,
                ])


def format_summary(plan: NightPlan) -> str:
    site = plan.site
    off = site.utc_offset_hours
    off_txt = f"UTC{off:+.2f}h"
    lines = [
        f"Night plan — {plan.date_str}",
        f"Site: lat {site.lat:.4f}, lon {site.lon:.4f}, height {site.height_m:.0f} m",
    ]
    if plan.no_night and plan.continuous_night:
        lines.append(
            "Continuous astronomical night on this date at this site: the "
            "Sun stays more than 18 degrees below the horizon all day, so "
            "there is no single dusk-to-dawn night to plan. Polar "
            "continuous night is reported, not planned (see Limits)."
        )
        lines.append(f"All {len(plan.results)} target(s) are unobservable tonight.")
        lines.append("")
        lines.append("Unobservable tonight:")
        for r in plan.results:
            lines.append(f" - {r.name} — {r.reason}")
        return "\n".join(lines)
    if plan.no_night:
        lines.append(
            "No astronomical night on this date at this site: the Sun never "
            "gets 18 degrees below the horizon, so it never gets fully dark."
        )
        lines.append(f"All {len(plan.results)} target(s) are unobservable tonight.")
        lines.append("")
        lines.append("Unobservable tonight:")
        for r in plan.results:
            lines.append(f" - {r.name} — {r.reason}")
        return "\n".join(lines)

    lines.append(
        f"Astronomical night: {_fmt_dt(plan.dusk)} UTC -> {_fmt_dt(plan.dawn)} UTC"
        f"  (local solar {_fmt_local_hm(plan.dusk, site)} -> "
        f"{_fmt_local_hm(plan.dawn, site)}, {off_txt} from longitude)"
    )
    lines.append(f"Moon illumination tonight: {plan.moon_illumination * 100:.0f}%")
    observable = [r for r in plan.results if r.observable]
    unobservable = [r for r in plan.results if not r.observable]
    lines.append("")
    if observable:
        lines.append("Observe in this order:")
        for i, r in enumerate(observable[:5], start=1):
            lines.append(
                f" {i}. {r.name} — up {_fmt_hm(r.window_start)}->{_fmt_hm(r.window_end)} UTC"
                f" ({r.window_hours:.1f} h), best airmass {r.min_airmass:.2f} at "
                f"{_fmt_hm(r.best_time)} UTC, Moon {r.moon_sep_deg:.0f} deg away"
            )
        if len(observable) > 5:
            lines.append(f"    ... and {len(observable) - 5} more in the plan file")
    else:
        lines.append("No targets are observable tonight.")
    if unobservable:
        lines.append("")
        lines.append("Unobservable tonight:")
        for r in unobservable:
            lines.append(f" - {r.name} — {r.reason}")
    return "\n".join(lines)
