from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import Iterable

import holidays


class DayType(str, Enum):
    NORMAL_WEEKDAY = "NORMAL_WEEKDAY"
    NORMAL_WEEKEND_OR_HOLIDAY = "NORMAL_WEEKEND_OR_HOLIDAY"
    SERVICE_WEEKDAY = "SERVICE_WEEKDAY"
    SERVICE_WEEKEND_OR_HOLIDAY = "SERVICE_WEEKEND_OR_HOLIDAY"


@dataclass(frozen=True)
class DayInfo:
    day: date
    index: int
    is_weekend: bool
    is_saturday: bool
    is_sunday: bool
    is_holiday: bool
    is_service_week: bool
    is_service_day: bool
    day_type: DayType
    week_id: date
    is_report: bool


@dataclass
class Calendar:
    days: list[DayInfo]
    date_to_index: dict[date, int]
    report_start: date
    report_end: date
    solve_end: date

    @staticmethod
    def build(
        report_start: date,
        report_end: date,
        buffer_days: int,
        locale: str,
        anchor_monday: date,
        cycle_weeks: int,
        service_week_in_cycle: int,
    ) -> "Calendar":
        solve_end = report_end + timedelta(days=buffer_days)
        years = list({report_start.year, report_end.year, solve_end.year})
        holiday_set = holidays.country_holidays(locale, years=years)

        days: list[DayInfo] = []
        date_to_index: dict[date, int] = {}
        current = report_start
        idx = 0
        while current <= solve_end:
            weekday = current.weekday()
            is_saturday = weekday == 5
            is_sunday = weekday == 6
            is_weekend = is_saturday or is_sunday
            is_holiday = current in holiday_set
            monday = current - timedelta(days=weekday)
            weeks_since_anchor = (monday - anchor_monday).days // 7
            cycle_pos = (weeks_since_anchor % cycle_weeks) + 1
            is_service_week = cycle_pos == service_week_in_cycle
            is_service_day = is_service_week
            if is_service_day:
                if is_weekend or is_holiday:
                    day_type = DayType.SERVICE_WEEKEND_OR_HOLIDAY
                else:
                    day_type = DayType.SERVICE_WEEKDAY
            else:
                if is_weekend or is_holiday:
                    day_type = DayType.NORMAL_WEEKEND_OR_HOLIDAY
                else:
                    day_type = DayType.NORMAL_WEEKDAY
            is_report = report_start <= current <= report_end
            info = DayInfo(
                day=current,
                index=idx,
                is_weekend=is_weekend,
                is_saturday=is_saturday,
                is_sunday=is_sunday,
                is_holiday=is_holiday,
                is_service_week=is_service_week,
                is_service_day=is_service_day,
                day_type=day_type,
                week_id=monday,
                is_report=is_report,
            )
            days.append(info)
            date_to_index[current] = idx
            idx += 1
            current += timedelta(days=1)
        return Calendar(
            days=days,
            date_to_index=date_to_index,
            report_start=report_start,
            report_end=report_end,
            solve_end=solve_end,
        )

    def report_indices(self) -> list[int]:
        return [d.index for d in self.days if d.is_report]

    def sundays(self) -> list[int]:
        return [d.index for d in self.days if d.is_sunday]

    def saturday_sunday_pairs(self) -> list[tuple[int, int]]:
        pairs = []
        for d in self.days:
            if d.is_saturday:
                next_day = d.day + timedelta(days=1)
                if next_day in self.date_to_index:
                    idx = self.date_to_index[next_day]
                    if self.days[idx].is_sunday:
                        pairs.append((d.index, idx))
        return pairs

    def weekday_candidates_for_sunday(self, sunday_index: int) -> list[int]:
        sunday = self.days[sunday_index].day
        monday_of_week = sunday - timedelta(days=sunday.weekday())
        monday_prev = monday_of_week - timedelta(days=7)
        candidates = []
        for offset in range(5):
            for base in (monday_prev, monday_of_week):
                d = base + timedelta(days=offset)
                idx = self.date_to_index.get(d)
                if idx is not None:
                    candidates.append(idx)
        return sorted(set(candidates))

    def next_weekend_after_sunday(self, sunday_index: int) -> tuple[int | None, int | None]:
        sunday = self.days[sunday_index].day
        next_saturday = sunday + timedelta(days=6)
        next_sunday = sunday + timedelta(days=7)
        return (
            self.date_to_index.get(next_saturday),
            self.date_to_index.get(next_sunday),
        )

    def weeks(self) -> dict[date, list[int]]:
        weeks: dict[date, list[int]] = {}
        for d in self.days:
            weeks.setdefault(d.week_id, []).append(d.index)
        return weeks

    def report_weeks(self) -> dict[date, list[int]]:
        weeks = self.weeks()
        report_weeks: dict[date, list[int]] = {}
        for week_id, indices in weeks.items():
            if any(self.days[i].is_report for i in indices) and len(indices) == 7:
                report_weeks[week_id] = indices
        return report_weeks


def summarize_day_types(days: Iterable[DayInfo]) -> dict[DayType, int]:
    counts: dict[DayType, int] = {}
    for d in days:
        counts[d.day_type] = counts.get(d.day_type, 0) + 1
    return counts
