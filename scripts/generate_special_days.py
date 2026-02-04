#!/usr/bin/env python3
"""Generate special-days periods from service-cycle rules.

This tool is intentionally separate from the solver workflow.
It converts the current cycle-based service-week logic into an explicit
period list: {start, days}.

This is meant as a migration/bootstrap helper: once `special_days.yaml` exists,
the solver no longer needs to know how to compute "service weeks".
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, List

import yaml


@dataclass(frozen=True)
class SpecialPeriod:
    """Encapsulates `SpecialPeriod` behavior and data."""
    start: str
    days: int


def _compress_consecutive_dates(dates: Iterable[date]) -> List[SpecialPeriod]:
    """Internal helper for `_compress_consecutive_dates`."""
    ordered = sorted(set(dates))
    if not ordered:
        return []

    periods: List[SpecialPeriod] = []
    start = ordered[0]
    last = ordered[0]

    for current in ordered[1:]:
        if (current - last).days == 1:
            last = current
            continue

        periods.append(
            SpecialPeriod(
                start=start.isoformat(),
                days=(last - start).days + 1,
            )
        )
        start = current
        last = current

    periods.append(
        SpecialPeriod(
            start=start.isoformat(),
            days=(last - start).days + 1,
        )
    )
    return periods


def _is_service_day(
    d: date,
    *,
    anchor_monday: date,
    cycle_weeks: int,
    service_week_in_cycle: int,
    include_following_monday: bool,
) -> bool:
    # Service week is the configured week in the cycle (Mon-Sun)
    """Internal helper for `_is_service_day`."""
    monday = d - timedelta(days=d.weekday())
    weeks_since_anchor = (monday - anchor_monday).days // 7
    cycle_position = (weeks_since_anchor % cycle_weeks) + 1

    if cycle_position == service_week_in_cycle:
        return True

    if include_following_monday and d.weekday() == 0:
        prev_sunday = d - timedelta(days=1)
        monday_prev = prev_sunday - timedelta(days=prev_sunday.weekday())
        weeks_prev = (monday_prev - anchor_monday).days // 7
        cycle_prev = (weeks_prev % cycle_weeks) + 1
        return cycle_prev == service_week_in_cycle

    return False


def main() -> int:
    """Run the command-line entrypoint."""
    parser = argparse.ArgumentParser(
        description="Generate special-days list from service-cycle rules."
    )
    parser.add_argument(
        "--calendar",
        default="config/scenarios/pharmacy_pt/calendar.yaml",
        help="Path to calendar.yaml (default: config/scenarios/pharmacy_pt/calendar.yaml)",
    )
    parser.add_argument(
        "--out",
        default="config/scenarios/pharmacy_pt/special_days.yaml",
        help="Output YAML path (default: config/scenarios/pharmacy_pt/special_days.yaml)",
    )
    parser.add_argument(
        "--name",
        default="service",
        help="Special-days tag name (default: service)",
    )
    args = parser.parse_args()

    cal_path = Path(args.calendar)
    with cal_path.open() as f:
        cal = yaml.safe_load(f) or {}

    calendar = cal.get("calendar", cal)
    report_start = datetime.fromisoformat(calendar["report_start"]).date()
    report_end = datetime.fromisoformat(calendar["report_end"]).date()
    buffer_days = int(calendar.get("buffer_days", 7))
    service_cycle = calendar.get("service_cycle", {})

    anchor_monday = datetime.fromisoformat(service_cycle["anchor_monday"]).date()
    cycle_weeks = int(service_cycle["cycle_weeks"])
    service_week_in_cycle = int(service_cycle["service_week_in_cycle"])
    include_following_monday = bool(service_cycle.get("include_following_monday", True))

    # Important: generate through the *solve horizon*, not just the report end.
    # The solver includes buffer days before/after, and those days need the
    # same special tags for shift existence / weekend coupling to remain consistent.
    solve_start = report_start - timedelta(days=buffer_days)
    solve_end = report_end + timedelta(days=buffer_days)

    dates = []
    current = solve_start
    while current <= solve_end:
        if _is_service_day(
            current,
            anchor_monday=anchor_monday,
            cycle_weeks=cycle_weeks,
            service_week_in_cycle=service_week_in_cycle,
            include_following_monday=include_following_monday,
        ):
            dates.append(current)
        current += timedelta(days=1)

    periods = _compress_consecutive_dates(dates)

    output = {
        "special_days": [
            {
                "name": args.name,
                "periods": [asdict(p) for p in periods],
            }
        ]
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        yaml.safe_dump(output, f, sort_keys=False)

    print(f"Wrote {len(periods)} periods to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
