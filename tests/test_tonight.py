"""Tests for tonight.

The reference night is 2026-12-15 at a Cerro Tololo-like site
(lat -31.27, lon -70.70). On that date the Sun's RA is ~17.5h, so an
object near RA 5.5h (82.5 deg) and Dec -31 transits close to the
zenith around local midnight — a reliable "high in the sky" target.
"""

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from astropy import units as u
from astropy.coordinates import SkyCoord, get_body
from astropy.time import Time

from tonight.cli import main
from tonight.core import (
    TonightError,
    _all_runs,
    format_summary,
    moon_separation_deg,
    parse_site,
    parse_targets,
    plan_night,
)

SITE = "-31.2733,-70.7033,2300"
DATE = "2026-12-15"


def write_csv(text):
    fh = tempfile.NamedTemporaryFile(
        "w", suffix=".csv", delete=False, encoding="utf-8"
    )
    fh.write(text)
    fh.close()
    return fh.name


def plan_for(csv_text, site=SITE, date=DATE):
    path = write_csv(csv_text)
    try:
        site_obj = parse_site(site)
        targets, has_priority = parse_targets(path)
        return plan_night(site_obj, targets, date, has_priority=has_priority)
    finally:
        os.unlink(path)


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class TestObservableRanking(unittest.TestCase):
    def test_high_target_is_observable_with_sane_window(self):
        plan = plan_for("name,ra,dec\nZenith Target,82.5,-31.0\n")
        self.assertFalse(plan.no_night)
        self.assertEqual(len(plan.results), 1)
        r = plan.results[0]
        self.assertTrue(r.observable, r.reason)
        # It transits near the zenith, so it must be good for hours and
        # get very close to airmass 1.
        self.assertGreater(r.window_hours, 3.0)
        self.assertLess(r.window_hours, 12.0)
        self.assertLess(r.min_airmass, 1.1)
        self.assertGreaterEqual(r.min_airmass, 1.0)
        self.assertLess(r.window_start.jd, r.best_time.jd)
        self.assertLess(r.best_time.jd, r.window_end.jd)
        self.assertIsNotNone(r.moon_sep_deg)
        self.assertGreaterEqual(r.moon_sep_deg, 0.0)
        self.assertLessEqual(r.moon_sep_deg, 180.0)

    def test_longer_window_ranks_first_without_priority(self):
        # The zenith target is up for most of the night; Acrux (RA 12.4h)
        # only rises above airmass 2 shortly before dawn on this date.
        plan = plan_for(
            "name,ra,dec\nAcrux,186.649,-63.099\nZenith Target,82.5,-31.0\n"
        )
        names = [r.name for r in plan.results if r.observable]
        self.assertEqual(names[0], "Zenith Target")

    def test_priority_column_wins_over_window(self):
        plan = plan_for(
            "name,ra,dec,priority\n"
            "Zenith Target,82.5,-31.0,\n"
            "Acrux,186.649,-63.099,10\n"
        )
        names = [r.name for r in plan.results if r.observable]
        self.assertEqual(names[0], "Acrux")


class TestUnobservable(unittest.TestCase):
    def test_far_north_target_from_southern_site(self):
        plan = plan_for("name,ra,dec\nPolar Target,82.5,80.0\n")
        r = plan.results[0]
        self.assertFalse(r.observable)
        self.assertIn("never rises above airmass 2", r.reason)

    def test_target_near_the_sun_is_unobservable(self):
        # On 2026-12-15 the Sun is near RA 262 deg, Dec -23 deg: a target
        # there is up in daylight only.
        plan = plan_for("name,ra,dec\nSun Neighbour,262.0,-23.0\n")
        r = plan.results[0]
        self.assertFalse(r.observable)
        self.assertTrue(r.reason)


class TestMoonSeparation(unittest.TestCase):
    def test_target_at_moon_position_has_zero_separation(self):
        site = parse_site(SITE)
        t = Time("2026-12-15 04:00:00", scale="utc")
        moon = get_body("moon", t, site.location)
        sep = moon_separation_deg(moon, t, site.location)
        self.assertLess(sep, 0.01)

    def test_moon_illumination_is_a_fraction(self):
        plan = plan_for("name,ra,dec\nZenith Target,82.5,-31.0\n")
        self.assertIsNotNone(plan.moon_illumination)
        self.assertGreaterEqual(plan.moon_illumination, 0.0)
        self.assertLessEqual(plan.moon_illumination, 1.0)


class TestCoordinateFormats(unittest.TestCase):
    def test_sexagesimal_and_degrees_give_identical_plans(self):
        deg = plan_for(
            "name,ra,dec\nA,82.5,-31.0\nB,90.0,45.25\n"
        )
        sex = plan_for(
            "name,ra,dec\nA,05:30:00,-31:00:00\nB,06:00:00,45:15:00\n"
        )
        self.assertEqual(len(deg.results), len(sex.results))
        for rd, rs in zip(deg.results, sex.results):
            self.assertEqual(rd.name, rs.name)
            self.assertEqual(rd.observable, rs.observable)
            if rd.observable:
                self.assertAlmostEqual(rd.window_start.jd, rs.window_start.jd, places=6)
                self.assertAlmostEqual(rd.window_end.jd, rs.window_end.jd, places=6)
                self.assertAlmostEqual(rd.min_airmass, rs.min_airmass, places=6)


class TestUserErrors(unittest.TestCase):
    def test_empty_csv_is_a_clean_error(self):
        path = write_csv("name,ra,dec\n")
        try:
            code, out, err = run_cli(
                ["plan", path, "--site", SITE, "--date", DATE]
            )
        finally:
            os.unlink(path)
        self.assertEqual(code, 2)
        self.assertIn("no targets", err)
        self.assertNotIn("Traceback", err)

    def test_missing_columns_is_a_clean_error(self):
        path = write_csv("name,ra\nA,82.5\n")
        try:
            code, out, err = run_cli(
                ["plan", path, "--site", SITE, "--date", DATE]
            )
        finally:
            os.unlink(path)
        self.assertEqual(code, 2)
        self.assertIn("missing required column", err)
        self.assertIn("dec", err)
        self.assertNotIn("Traceback", err)

    def test_bad_site_string_is_a_clean_error(self):
        path = write_csv("name,ra,dec\nA,82.5,-31.0\n")
        try:
            code, out, err = run_cli(
                ["plan", path, "--site", "nowhere", "--date", DATE]
            )
        finally:
            os.unlink(path)
        self.assertEqual(code, 2)
        self.assertIn("bad site", err)
        self.assertNotIn("Traceback", err)

    def test_unparseable_coordinates_are_a_clean_error(self):
        with self.assertRaises(TonightError):
            plan_for("name,ra,dec\nA,banana,-31.0\n")

    def test_bad_date_is_a_clean_error(self):
        with self.assertRaises(TonightError):
            plan_for("name,ra,dec\nA,82.5,-31.0\n", date="15/12/2026")

    def test_missing_file_is_a_clean_error(self):
        code, out, err = run_cli(
            ["plan", "/nonexistent/targets.csv", "--site", SITE, "--date", DATE]
        )
        self.assertEqual(code, 2)
        self.assertIn("cannot read targets file", err)
        self.assertNotIn("Traceback", err)


class TestNoAstronomicalNight(unittest.TestCase):
    def test_high_latitude_summer_is_a_clean_message_not_a_crash(self):
        # Longyearbyen in late June: the Sun never gets anywhere near
        # 18 degrees below the horizon.
        path = write_csv("name,ra,dec\nA,82.5,-31.0\nB,201.7,-47.5\n")
        out_path = path + ".plan.csv"
        try:
            code, out, err = run_cli(
                ["plan", path, "--site", "78.2232,15.6267,0",
                 "--date", "2026-06-21", "--out", out_path]
            )
            self.assertEqual(code, 0, err)
            self.assertIn("No astronomical night", out)
            self.assertNotIn("Traceback", err)
            with open(out_path, encoding="utf-8") as fh:
                body = fh.read()
            self.assertIn("unobservable", body)
            self.assertIn("no astronomical night", body)
        finally:
            os.unlink(path)
            if os.path.exists(out_path):
                os.unlink(out_path)


class TestAdversarialReviewFixes(unittest.TestCase):
    """Regressions from the independent adversarial review (REVIEW.md)."""

    def test_non_finite_site_height_is_a_clean_error(self):
        for site in ("0,0,nan", "0,0,inf", "0,0,-inf"):
            with self.assertRaises(TonightError):
                parse_site(site)

    def test_non_finite_ra_is_a_clean_error(self):
        for ra in ("nan", "inf", "-inf"):
            with self.assertRaises(TonightError):
                plan_for(f"name,ra,dec\nA,{ra},0\n")

    def test_non_finite_priority_is_a_clean_error(self):
        for prio in ("nan", "inf"):
            with self.assertRaises(TonightError):
                plan_for(f"name,ra,dec,priority\nA,82.5,-31,{prio}\n")

    def test_strict_date_format(self):
        for bad in ("2026-2-5", "2026-12-15 ", "1800-01-01", "2200-01-01"):
            with self.assertRaises(TonightError):
                plan_for("name,ra,dec\nA,82.5,-31.0\n", date=bad)

    def test_out_of_range_sexagesimal_is_a_clean_error(self):
        for ra in ("24:00:00", "12:60:00"):
            with self.assertRaises(TonightError):
                plan_for(f"name,ra,dec\nA,{ra},0\n")

    def test_polar_continuous_night_is_not_called_no_darkness(self):
        # North Pole in mid-December: the Sun stays below -18 degrees
        # all day. That is continuous night, not "no night".
        plan = plan_for(
            "name,ra,dec\nA,82.5,80.0\n", site="90,0,0", date="2026-12-15"
        )
        self.assertTrue(plan.no_night)
        self.assertTrue(plan.continuous_night)
        self.assertIn("continuous astronomical night", plan.results[0].reason)
        self.assertNotIn("never gets 18 degrees", plan.results[0].reason)


class TestOutputFiles(unittest.TestCase):
    def test_plan_csv_has_ranked_rows_and_unobservable_section(self):
        path = write_csv(
            "name,ra,dec\nZenith Target,82.5,-31.0\nPolar Target,82.5,80.0\n"
        )
        out_path = path + ".plan.csv"
        try:
            code, out, err = run_cli(
                ["plan", path, "--site", SITE, "--date", DATE, "--out", out_path]
            )
            self.assertEqual(code, 0, err)
            with open(out_path, encoding="utf-8") as fh:
                rows = list(fh)
            self.assertIn("window_start_utc", rows[0])
            self.assertIn("Zenith Target", rows[1])
            self.assertIn("observable", rows[1])
            self.assertIn("Polar Target", rows[2])
            self.assertIn("unobservable", rows[2])
            self.assertIn("never rises above airmass 2", rows[2])
            self.assertIn("Observe in this order", out)
            self.assertIn("Unobservable tonight", out)
        finally:
            os.unlink(path)
            if os.path.exists(out_path):
                os.unlink(out_path)


class TestAllRuns(unittest.TestCase):
    def test_no_runs(self):
        self.assertEqual(_all_runs([False, False]), [])

    def test_single_run(self):
        self.assertEqual(_all_runs([False, True, True, False]), [(1, 2)])

    def test_runs_at_edges_and_multiple(self):
        mask = [True, True, False, True, False, True, True, True]
        self.assertEqual(_all_runs(mask), [(0, 1), (3, 3), (5, 7)])


class TestTwoWindows(unittest.TestCase):
    """A near-pole target from a mid-latitude site dips below the
    airmass limit around lower culmination and rises again, giving two
    windows in one night. Reference case found by scanning the real
    ephemeris: lat +40, lon 0, 2026-01-15, RA 285 deg, Dec +75 deg —
    upper culmination altitude 55 deg, lower culmination 25 deg,
    either side of the 30 deg (airmass 2) limit."""

    NORTH_SITE = "40.0,0.0,0"
    NORTH_DATE = "2026-01-15"
    CSV = "name,ra,dec\nDipping Target,285.0,75.0\n"

    def test_two_windows_are_all_reported(self):
        plan = plan_for(self.CSV, site=self.NORTH_SITE, date=self.NORTH_DATE)
        r = plan.results[0]
        self.assertTrue(r.observable)
        self.assertEqual(len(r.windows), 2)
        # Windows are in time order and do not overlap.
        self.assertLess(r.windows[0][1], r.windows[1][0])
        # The headline window is the longest stretch; the total is more.
        longest = max(
            (we - ws).to_value(u.hour) for ws, we in r.windows
        )
        self.assertAlmostEqual(r.window_hours, longest, places=6)
        self.assertAlmostEqual(
            r.total_window_hours,
            sum((we - ws).to_value(u.hour) for ws, we in r.windows),
            places=6,
        )
        self.assertGreater(r.total_window_hours, r.window_hours)
        # The headline start/end are one of the reported windows.
        self.assertIn((r.window_start, r.window_end), r.windows)
        # Best time (lowest airmass) falls inside a reported window.
        self.assertTrue(
            any(ws <= r.best_time <= we for ws, we in r.windows)
        )

    def test_summary_and_csv_show_both_windows(self):
        plan = plan_for(self.CSV, site=self.NORTH_SITE, date=self.NORTH_DATE)
        summary = format_summary(plan)
        self.assertIn("in 2 windows", summary)
        path = write_csv(self.CSV)
        out_path = path + ".plan.csv"
        try:
            code, out, err = run_cli(
                ["plan", path, "--site", self.NORTH_SITE,
                 "--date", self.NORTH_DATE, "--out", out_path]
            )
            self.assertEqual(code, 0, err)
            with open(out_path, encoding="utf-8") as fh:
                rows = list(fh)
            self.assertIn("window_count", rows[0])
            self.assertIn("total_window_hours", rows[0])
            fields = rows[1].strip().split(",")
            self.assertEqual(fields[14], "2")  # window_count column
            self.assertGreater(float(fields[15]), float(fields[9]))
        finally:
            os.unlink(path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_single_window_target_reports_one_window(self):
        plan = plan_for("name,ra,dec\nZenith Target,82.5,-31.0\n")
        r = plan.results[0]
        self.assertTrue(r.observable)
        self.assertEqual(len(r.windows), 1)
        self.assertAlmostEqual(r.total_window_hours, r.window_hours, places=6)
        self.assertEqual(
            (r.window_start, r.window_end), r.windows[0]
        )


if __name__ == "__main__":
    unittest.main()
