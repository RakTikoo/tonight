"""Command-line interface for tonight."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from .core import (
    TonightError,
    format_summary,
    parse_site,
    parse_targets,
    plan_night,
    write_plan_csv,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tonight",
        description="Plan one night of observing: give it a CSV of targets, "
        "a site and a date, and get back a ranked plan for that night.",
    )
    sub = p.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="build the plan for one night")
    plan.add_argument("targets", help="CSV of targets: name, ra, dec [, priority]")
    plan.add_argument(
        "--site",
        required=True,
        help='observing site as "lat,lon,height_m" (degrees, metres), '
        'e.g. --site "-31.2733,-70.7033,2300"',
    )
    plan.add_argument(
        "--date",
        default=None,
        help="night date, YYYY-MM-DD (default: today, UTC)",
    )
    plan.add_argument(
        "--out",
        default=None,
        help="write the full plan CSV here (default: summary only)",
    )
    return p


def _normalise_argv(argv):
    """Join '--site VALUE' into '--site=VALUE'.

    Site strings for southern/western sites start with '-', which
    argparse would otherwise mistake for another option flag.
    """
    out = []
    i = 0
    while i < len(argv):
        if argv[i] == "--site" and i + 1 < len(argv):
            out.append(f"--site={argv[i + 1]}")
            i += 2
        else:
            out.append(argv[i])
            i += 1
    return out


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    args = build_parser().parse_args(_normalise_argv(list(argv)))
    try:
        site = parse_site(args.site)
        date_str = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        targets, has_priority = parse_targets(args.targets)
        plan = plan_night(site, targets, date_str, has_priority=has_priority)
        if args.out:
            write_plan_csv(plan, args.out)
        print(format_summary(plan))
        if args.out:
            print(f"\nFull plan written to {args.out}")
    except TonightError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
