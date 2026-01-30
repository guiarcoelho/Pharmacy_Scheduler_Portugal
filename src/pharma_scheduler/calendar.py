"""Calendar management for scheduling.

This module handles:
- Date range generation (report period + buffer)
- Bank holiday detection
- Special-day tags (from config)
- Helper functions for weeks, weekends, and Sunday compensation
"""

from datetime import date, timedelta
from typing import Dict, List, Tuple, Set
import holidays


class Calendar:
    """Calendar with holidays and special tags."""

    def __init__(
        self,
        report_start: date,
        report_end: date,
        buffer_days: int,
        locale: str = "PT",
        special_tags_by_date: Dict[date, Set[str]] | None = None,
    ):
        """Initialize calendar.

        Args:
            report_start: First day of report period
            report_end: Last day of report period
            buffer_days: Extra days after report_end for Sunday compensation
            locale: Country code for holidays
            special_tags_by_date: mapping date -> set of special tags
        """
        self.report_start = report_start
        self.report_end = report_end
        self.buffer_days = buffer_days
        self.special_tags_by_date = special_tags_by_date or {}

        # Generate full date range (report + buffer)
        self.solve_start = report_start
        self.solve_end = report_end + timedelta(days=buffer_days)

        # Generate all dates
        self.dates: List[date] = []
        current = self.solve_start
        while current <= self.solve_end:
            self.dates.append(current)
            current += timedelta(days=1)

        # Get holidays for relevant years
        years = set(d.year for d in self.dates)
        self.holidays = holidays.country_holidays(locale, years=years)

    def is_saturday(self, d: date) -> bool:
        """Check if date is Saturday."""
        return d.weekday() == 5

    def is_sunday(self, d: date) -> bool:
        """Check if date is Sunday."""
        return d.weekday() == 6

    def is_weekend(self, d: date) -> bool:
        """Check if date is weekend (Sat or Sun)."""
        return d.weekday() >= 5

    def is_holiday(self, d: date) -> bool:
        """Check if date is a bank holiday."""
        return d in self.holidays

    def get_special_tags(self, d: date) -> Set[str]:
        """Get special tags for a date (may be empty)."""
        return set(self.special_tags_by_date.get(d, set()))

    def is_in_report_range(self, d: date) -> bool:
        """Check if date is in report range (not buffer)."""
        return self.report_start <= d <= self.report_end

    def get_week_id(self, d: date) -> date:
        """Get Monday date for the week containing d (for aggregation)."""
        return d - timedelta(days=d.weekday())

    def get_all_weeks(self) -> List[date]:
        """Get list of all week IDs (Monday dates) in solve range."""
        weeks = set()
        for d in self.dates:
            weeks.add(self.get_week_id(d))
        return sorted(weeks)

    def get_days_in_week(self, week_id: date) -> List[date]:
        """Get all dates in a week (up to 7 days)."""
        days = []
        for i in range(7):
            d = week_id + timedelta(days=i)
            if d in self.dates:
                days.append(d)
        return days

    def get_weekend_pairs(self) -> List[Tuple[date, date]]:
        """Get all (Saturday, Sunday) pairs in solve range."""
        pairs = []
        for d in self.dates:
            if self.is_saturday(d):
                sunday = d + timedelta(days=1)
                if sunday in self.dates:
                    pairs.append((d, sunday))
        return pairs

    def get_sundays(self) -> List[date]:
        """Get all Sunday dates in solve range."""
        return [d for d in self.dates if self.is_sunday(d)]

    def get_sunday_comp_windows(self, sunday: date) -> Tuple[List[date], List[date]]:
        """Get candidate weekdays for Sunday compensation.

        The extra day off can happen in the same week (Mon-Fri before Sunday)
        or in the following week (Mon-Fri after Sunday).

        Args:
            sunday: The Sunday date

        Returns:
            Tuple of (week1_days, week2_days)
        """
        # 1. Week 1: Monday-Friday BEFORE/OF the Sunday
        monday_of = self.get_week_id(sunday)
        week1 = [monday_of + timedelta(days=i) for i in range(5)]
        week1 = [d for d in week1 if d in self.dates]

        # 2. Week 2: Monday-Friday AFTER the Sunday
        monday_next = monday_of + timedelta(days=7)
        week2 = [monday_next + timedelta(days=i) for i in range(5)]
        week2 = [d for d in week2 if d in self.dates]

        return week1, week2

    def get_next_weekend(self, sunday: date) -> Tuple[date, date]:
        """Get next weekend (Saturday, Sunday) after a Sunday.

        Args:
            sunday: The Sunday date

        Returns:
            (next_saturday, next_sunday) tuple
        """
        # Next Saturday is 6 days after this Sunday
        next_saturday = sunday + timedelta(days=6)
        next_sunday = sunday + timedelta(days=7)
        return (next_saturday, next_sunday)

    def get_report_dates(self) -> List[date]:
        """Get only dates in report range (excluding buffer)."""
        return [d for d in self.dates if self.is_in_report_range(d)]

    def get_day_context(self, d: date) -> dict:
        """Get dictionary of day attributes for JSONLogic evaluation."""
        has_next_day = d + timedelta(days=1) in self.dates
        return {
            "date": d.isoformat(),
            "weekday": d.weekday(),
            "is_holiday": self.is_holiday(d),
            "is_weekend": self.is_weekend(d),
            "is_saturday": self.is_saturday(d),
            "is_sunday": self.is_sunday(d),
            "special_tags": sorted(self.get_special_tags(d)),
            "in_report_range": self.is_in_report_range(d),
            "has_next_day": has_next_day,
            "next_date": (d + timedelta(days=1)).isoformat() if has_next_day else None,
        }

    def __len__(self) -> int:
        """Number of days in solve range."""
        return len(self.dates)

    def __repr__(self) -> str:
        return (
            f"Calendar(report={self.report_start} to {self.report_end}, "
            f"solve={self.solve_start} to {self.solve_end}, "
            f"days={len(self.dates)})"
        )
