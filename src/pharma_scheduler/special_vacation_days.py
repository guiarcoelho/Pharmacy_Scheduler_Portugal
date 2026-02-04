"""Special days and vacation days loader/expander.

Special days are explicit date ranges that attach tags to dates.
They are designed to behave like holidays: a date can carry zero or more tags,
and tags can overlap.

These tags are then available to JSONLogic rules (shift existence and rulebook
filters) via `day.special_tags`.

Worker vacations are optional date ranges attached to each worker configuration.
Vacations expand into concrete dates and are attached to workers as:
- `vacation_dates`: set[date] for fast model checks
- `vacation_days`: list[str] for JSONLogic (`day.date` membership)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Set

import yaml


@dataclass(frozen=True)
class SpecialPeriod:
    """Encapsulates `SpecialPeriod` behavior and data."""
    start: date
    days: int


@dataclass(frozen=True)
class VacationPeriod:
    """Encapsulates `VacationPeriod` behavior and data."""
    start: date
    days: int


def _parse_special_days(data: dict) -> Dict[str, List[SpecialPeriod]]:
    """Internal helper for `_parse_special_days`."""
    result: Dict[str, List[SpecialPeriod]] = {}
    for item in data.get("special_days", []) or []:
        name = item["name"]
        periods: List[SpecialPeriod] = []
        for p in item.get("periods", []) or []:
            raw_start = p["start"]
            if isinstance(raw_start, datetime):
                start = raw_start.date()
            elif isinstance(raw_start, date):
                start = raw_start
            else:
                start = date.fromisoformat(str(raw_start))
            days = int(p["days"])
            if days <= 0:
                raise ValueError(f"Invalid period days={days} for special '{name}'")
            periods.append(SpecialPeriod(start=start, days=days))
        result[name] = periods
    return result


def load_special_days(path: str | Path) -> Dict[str, List[SpecialPeriod]]:
    """Execute `load_special_days`."""
    path = Path(path)
    if not path.exists():
        return {}
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return _parse_special_days(data)


def load_special_days_data(data: dict) -> Dict[str, List[SpecialPeriod]]:
    """Execute `load_special_days_data`."""
    return _parse_special_days(data or {})


def expand_periods(periods: Iterable[SpecialPeriod | VacationPeriod]) -> Set[date]:
    """Execute `expand_periods`."""
    days: Set[date] = set()
    for period in periods:
        for offset in range(period.days):
            days.add(period.start + timedelta(days=offset))
    return days


def _parse_worker_vacations(workers: Iterable[dict]) -> Dict[str, List[VacationPeriod]]:
    """Internal helper for `_parse_worker_vacations`."""
    result: Dict[str, List[VacationPeriod]] = {}
    for worker in workers:
        periods: List[VacationPeriod] = []
        raw_vacations = worker.get("vacations", []) or []
        if isinstance(raw_vacations, dict):
            raw_vacations = [raw_vacations]
        for p in raw_vacations:
            raw_start = p["start"]
            if isinstance(raw_start, datetime):
                start = raw_start.date()
            elif isinstance(raw_start, date):
                start = raw_start
            else:
                start = date.fromisoformat(str(raw_start))
            days = int(p["days"])
            if days <= 0:
                raise ValueError(
                    f"Invalid vacation days={days} for worker '{worker.get('id')}'"
                )
            periods.append(VacationPeriod(start=start, days=days))
        if periods:
            result[worker["id"]] = periods
    return result


def apply_worker_vacations(
    *,
    workers: List[dict],
    solve_dates: Iterable[date],
) -> List[str]:
    """Expand worker vacations and attach them to worker dicts.

    Returns a list of warning strings for vacations outside the solve range.
    """
    solve_set = set(solve_dates)
    warnings: List[str] = []
    vacations_by_worker = _parse_worker_vacations(workers)

    for worker in workers:
        worker_id = worker.get("id")
        periods = vacations_by_worker.get(worker_id, [])
        all_days = expand_periods(periods)
        in_solve = sorted(d for d in all_days if d in solve_set)
        out_of_solve = sorted(d for d in all_days if d not in solve_set)

        if out_of_solve:
            sample = ", ".join(d.isoformat() for d in out_of_solve[:3])
            suffix = "" if len(out_of_solve) <= 3 else ", ..."
            warnings.append(
                f"Worker '{worker_id}' has vacation days outside solve range: "
                f"{sample}{suffix}"
            )

        if periods and not in_solve:
            warnings.append(
                f"Worker '{worker_id}' vacations are entirely outside the solve range."
            )

        worker["vacation_dates"] = set(in_solve)
        worker["vacation_days"] = [d.isoformat() for d in in_solve]

    return warnings


def build_special_tag_index(
    *,
    dates: Iterable[date],
    specials: Dict[str, List[SpecialPeriod]],
) -> Dict[date, Set[str]]:
    """Execute `build_special_tag_index`."""
    date_set = set(dates)
    index: Dict[date, Set[str]] = {d: set() for d in date_set}

    for name, periods in specials.items():
        for day in expand_periods(periods):
            if day in index:
                index[day].add(name)

    return index
