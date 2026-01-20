"""Calendar management for pharmacy scheduling.

This module handles:
- Date range generation (report period + buffer)
- Service week calculation (4-week cycle)
- Bank holiday detection
- Day type classification
- Helper functions for weeks, weekends, and Sunday compensation
"""

from datetime import date, timedelta
from enum import Enum
from typing import List, Tuple, Set
import holidays


class DayType(Enum):
    """Classification of days for shift assignment."""
    NORMAL_WEEKDAY = "normal_weekday"
    NORMAL_WEEKEND_OR_HOLIDAY = "normal_weekend_or_holiday"
    SERVICE_WEEKDAY = "service_weekday"
    SERVICE_WEEKEND_OR_HOLIDAY = "service_weekend_or_holiday"


class Calendar:
    """Calendar with service weeks, holidays, and day typing."""

    def __init__(
        self,
        report_start: date,
        report_end: date,
        buffer_days: int,
        anchor_monday: date,
        cycle_weeks: int = 4,
        service_week_in_cycle: int = 4,
        locale: str = "PT"
    ):
        """Initialize calendar.

        Args:
            report_start: First day of report period
            report_end: Last day of report period
            buffer_days: Extra days after report_end for Sunday compensation
            anchor_monday: Reference Monday for service week cycle (must be Monday)
            cycle_weeks: Length of service cycle in weeks
            service_week_in_cycle: Which week in cycle is service week (1-indexed)
            locale: Country code for holidays
        """
        self.report_start = report_start
        self.report_end = report_end
        self.buffer_days = buffer_days
        self.anchor_monday = anchor_monday
        self.cycle_weeks = cycle_weeks
        self.service_week_in_cycle = service_week_in_cycle

        # Validate anchor is Monday
        if anchor_monday.weekday() != 0:
            raise ValueError(f"Anchor date {anchor_monday} is not a Monday")

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

        # Precompute day types
        self._day_types = {d: self._compute_day_type(d) for d in self.dates}

    def _compute_day_type(self, d: date) -> DayType:
        """Compute day type for a given date."""
        is_weekend = d.weekday() >= 5  # Saturday=5, Sunday=6
        is_holiday = d in self.holidays
        is_service = self._is_service_week(d)

        if is_service:
            if is_weekend or is_holiday:
                return DayType.SERVICE_WEEKEND_OR_HOLIDAY
            else:
                return DayType.SERVICE_WEEKDAY
        else:
            if is_weekend or is_holiday:
                return DayType.NORMAL_WEEKEND_OR_HOLIDAY
            else:
                return DayType.NORMAL_WEEKDAY

    def _is_service_week(self, d: date) -> bool:
        """Check if date falls in a service week."""
        # Get Monday of the week containing d
        monday = d - timedelta(days=d.weekday())

        # Calculate weeks since anchor
        weeks_since_anchor = (monday - self.anchor_monday).days // 7

        # Determine position in cycle (1-indexed)
        cycle_position = (weeks_since_anchor % self.cycle_weeks) + 1

        return cycle_position == self.service_week_in_cycle

    def get_day_type(self, d: date) -> DayType:
        """Get day type for a date."""
        return self._day_types[d]

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

    def get_sunday_comp_weekdays(self, sunday: date) -> List[date]:
        """Get candidate weekdays for Sunday compensation.

        Returns Mon-Fri of week before Sunday + Mon-Fri of week of Sunday.

        Args:
            sunday: The Sunday date

        Returns:
            List of weekday dates (Mon-Fri) from two weeks
        """
        # Week containing Sunday
        monday_of = self.get_week_id(sunday)
        week_of_weekdays = [monday_of + timedelta(days=i) for i in range(5)]

        # Week before Sunday
        monday_before = monday_of - timedelta(days=7)
        week_before_weekdays = [monday_before +
                                timedelta(days=i) for i in range(5)]

        # Combine and filter to dates in solve range
        all_weekdays = week_before_weekdays + week_of_weekdays
        return [d for d in sorted(set(all_weekdays)) if d in self.dates]

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

    def __len__(self) -> int:
        """Number of days in solve range."""
        return len(self.dates)

    def __repr__(self) -> str:
        return (f"Calendar(report={self.report_start} to {self.report_end}, "
                f"solve={self.solve_start} to {self.solve_end}, "
                f"days={len(self.dates)})")
