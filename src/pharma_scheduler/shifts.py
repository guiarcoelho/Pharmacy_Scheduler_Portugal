"""Shift definitions and management.

This module handles:
- Shift parsing from configuration
- Clock vs paid minutes calculation
- Shift eligibility by worker
- Coverage demand by day type
- Forbidden transition calculation for rest constraints
"""

from dataclasses import dataclass
from datetime import time
from typing import Dict, List, Set, Tuple
from .calendar import DayType


@dataclass
class Shift:
    """Shift definition with time and metadata."""
    code: str
    name: str
    start: time
    end: time  # For payment calculation
    clock_end: time  # For rest calculation (may differ from end)
    tags: Set[str]

    @property
    def paid_minutes(self) -> int:
        """Calculate paid duration in minutes."""
        return self._calculate_minutes(self.start, self.end)

    @property
    def clock_minutes(self) -> int:
        """Calculate clock duration in minutes (for rest calculations)."""
        return self._calculate_minutes(self.start, self.clock_end)

    @staticmethod
    def _calculate_minutes(start: time, end: time) -> int:
        """Calculate minutes between start and end.

        Handles midnight boundary: if end is 00:00, treat as 24:00.
        """
        start_min = start.hour * 60 + start.minute
        end_min = end.hour * 60 + end.minute

        # If end is 00:00, treat as 1440 (24:00)
        if end_min == 0:
            end_min = 1440

        return end_min - start_min

    def __repr__(self) -> str:
        return f"Shift({self.code}: {self.start}-{self.end}, {self.paid_minutes}min)"


class ShiftManager:
    """Manages shifts, eligibility, and coverage demand."""

    def __init__(self, shifts_config: List[Dict], demand_config: Dict):
        """Initialize shift manager.

        Args:
            shifts_config: List of shift definitions from YAML
            demand_config: Coverage demand by day type from YAML
        """
        self.shifts = self._parse_shifts(shifts_config)
        self.shifts_by_code = {s.code: s for s in self.shifts}
        self.demand = self._parse_demand(demand_config)

        # Precompute shift sets by day type
        self._shifts_by_day_type = self._compute_shifts_by_day_type()

    def _parse_shifts(self, config: List[Dict]) -> List[Shift]:
        """Parse shift definitions from config."""
        shifts = []
        for s in config:
            start = time.fromisoformat(s['start'])
            end = time.fromisoformat(s['end'])

            # Clock end defaults to end, unless overridden
            clock_end_str = s.get('clock_end', s['end'])
            clock_end = time.fromisoformat(clock_end_str)

            shift = Shift(
                code=s['code'],
                name=s['name'],
                start=start,
                end=end,
                clock_end=clock_end,
                tags=set(s.get('tags', []))
            )
            shifts.append(shift)

        return shifts

    def _parse_demand(self, config: Dict) -> Dict[DayType, Dict[str, int]]:
        """Parse coverage demand from config."""
        demand = {}

        # Map config keys to DayType enum
        mapping = {
            'normal_weekday': DayType.NORMAL_WEEKDAY,
            'normal_weekend_or_holiday': DayType.NORMAL_WEEKEND_OR_HOLIDAY,
            'service_weekday': DayType.SERVICE_WEEKDAY,
            'service_weekend_or_holiday': DayType.SERVICE_WEEKEND_OR_HOLIDAY,
        }

        for key, day_type in mapping.items():
            if key in config:
                demand[day_type] = config[key]

        return demand

    def _compute_shifts_by_day_type(self) -> Dict[DayType, List[Shift]]:
        """Compute which shifts are allowed for each day type."""
        result = {}

        # Normal weekday: M, I, T
        result[DayType.NORMAL_WEEKDAY] = [
            s for s in self.shifts if s.code in ['M', 'I', 'T']
        ]

        # Normal weekend/holiday: MW, IW, TW
        result[DayType.NORMAL_WEEKEND_OR_HOLIDAY] = [
            s for s in self.shifts if s.code in ['MW', 'IW', 'TW']
        ]

        # Service weekday: MS, IS, TS, NS
        result[DayType.SERVICE_WEEKDAY] = [
            s for s in self.shifts if s.code in ['MS', 'IS', 'TS', 'FS', 'NS']
        ]

        # Service weekend/holiday: MSW, ISW, TSW, NSW, FSW
        result[DayType.SERVICE_WEEKEND_OR_HOLIDAY] = [
            s for s in self.shifts if s.code in ['MSW', 'ISW', 'TSW', 'NSW', 'FSW']
        ]

        return result

    def get_allowed_shifts(self, day_type: DayType) -> List[Shift]:
        """Get shifts allowed for a day type."""
        return self._shifts_by_day_type[day_type]

    def get_demand(self, day_type: DayType) -> Dict[str, int]:
        """Get coverage demand for a day type."""
        return self.demand.get(day_type, {})

    def is_eligible(self, worker: str, shift_code: str, day_type: DayType,
                    is_saturday: bool, is_sunday: bool) -> bool:
        """Check if worker is eligible for shift on this day type.

        Args:
            worker: Worker ID (A-F)
            shift_code: Shift code
            day_type: Day type
            is_saturday: Whether day is Saturday
            is_sunday: Whether day is Sunday

        Returns:
            True if worker can work this shift
        """
        # Night shifts: only E
        if shift_code in ['NS', 'NSW']:
            return worker == 'E'

        # Worker F: only MSW/FSW on service weekends (Sat or Sun)
        if worker == 'F':
            is_service_weekend = day_type == DayType.SERVICE_WEEKEND_OR_HOLIDAY
            is_weekend_day = is_saturday or is_sunday
            return (shift_code in ['MSW', 'FSW'] and
                    is_service_weekend and is_weekend_day)

        # Core workers (A-E): all non-night shifts on appropriate day types
        shift = self.shifts_by_code.get(shift_code)
        if shift is None:
            return False

        allowed_shifts = self.get_allowed_shifts(day_type)
        return shift in allowed_shifts

    def get_forbidden_transitions(self, min_rest_hours: int = 11) -> List[Tuple[str, str]]:
        """Calculate forbidden shift transitions based on rest requirement.

        Args:
            min_rest_hours: Minimum rest hours required between shifts

        Returns:
            List of (shift1_code, shift2_code) forbidden pairs
        """
        forbidden = []

        for s1 in self.shifts:
            # Use clock_end for s1 (23:59 for TS/TSW)
            end1_min = s1.clock_end.hour * 60 + s1.clock_end.minute

            for s2 in self.shifts:
                start2_min = s2.start.hour * 60 + s2.start.minute

                # Calculate rest minutes (handle midnight wraparound)
                if start2_min >= end1_min:
                    rest_min = start2_min - end1_min
                else:
                    # Wraparound: e.g., end 23:59 (1439), start 08:30 (510)
                    rest_min = (1440 - end1_min) + start2_min

                rest_hours = rest_min / 60

                if rest_hours < min_rest_hours:
                    forbidden.append((s1.code, s2.code))

        return forbidden

    def __repr__(self) -> str:
        return f"ShiftManager({len(self.shifts)} shifts)"
