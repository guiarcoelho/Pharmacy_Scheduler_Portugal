"""Special days loader and expander.

Special days are explicit date ranges that attach tags to dates.
They are designed to behave like holidays: a date can carry zero or more tags,
and tags can overlap.

These tags are then available to JSONLogic rules (shift existence and rulebook
filters) via `day.special_tags`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Set

import yaml


@dataclass(frozen=True)
class SpecialPeriod:
    start: date
    days: int


def _parse_special_days(data: dict) -> Dict[str, List[SpecialPeriod]]:
    result: Dict[str, List[SpecialPeriod]] = {}
    for item in data.get("special_days", []) or []:
        name = item["name"]
        periods: List[SpecialPeriod] = []
        for p in item.get("periods", []) or []:
            start = date.fromisoformat(p["start"])
            days = int(p["days"])
            if days <= 0:
                raise ValueError(f"Invalid period days={days} for special '{name}'")
            periods.append(SpecialPeriod(start=start, days=days))
        result[name] = periods
    return result


def load_special_days(path: str | Path) -> Dict[str, List[SpecialPeriod]]:
    path = Path(path)
    if not path.exists():
        return {}
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return _parse_special_days(data)


def load_special_days_data(data: dict) -> Dict[str, List[SpecialPeriod]]:
    return _parse_special_days(data or {})


def expand_periods(periods: Iterable[SpecialPeriod]) -> Set[date]:
    days: Set[date] = set()
    for period in periods:
        for offset in range(period.days):
            days.add(period.start + timedelta(days=offset))
    return days


def build_special_tag_index(
    *,
    dates: Iterable[date],
    specials: Dict[str, List[SpecialPeriod]],
) -> Dict[date, Set[str]]:
    date_set = set(dates)
    index: Dict[date, Set[str]] = {d: set() for d in date_set}

    for name, periods in specials.items():
        for day in expand_periods(periods):
            if day in index:
                index[day].add(name)

    return index
