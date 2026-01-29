"""Shift definitions and management.

This module handles:
- Shift parsing from configuration
- Clock vs paid minutes calculation
- Shift existence by day (JSONLogic)
- Forbidden transition calculation for rest constraints
"""

from dataclasses import dataclass
from datetime import time
from typing import Dict, List, Set, Tuple

from .jsonlogic import evaluate


@dataclass
class Shift:
    """Shift definition with time and metadata."""
    code: str
    name: str
    start: time
    end: time  # For payment calculation
    clock_end: time  # For rest calculation (may differ from end)
    tags: Set[str]
    coverage_min: int
    coverage_max: int
    allowed_when: dict | None
    requires_worker_caps: Set[str]

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
    """Manages shifts and shift existence by day."""

    def __init__(self, shifts_config: List[Dict]):
        """Initialize shift manager.

        Args:
            shifts_config: List of shift definitions from YAML
        """
        self.shifts = self._parse_shifts(shifts_config)
        self.shifts_by_code = {s.code: s for s in self.shifts}

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
                tags=set(s.get('labels', [])),
                coverage_min=int(s['coverage']['min']),
                coverage_max=int(s['coverage']['max']),
                allowed_when=s.get('allowed_when'),
                requires_worker_caps=set(s.get('requires_worker_caps', [])),
            )
            shifts.append(shift)

        return shifts

    def is_shift_allowed(self, shift: Shift, day_context: dict) -> bool:
        """Check if a shift exists on a given day."""
        if shift.allowed_when is None:
            return True
        return bool(evaluate(shift.allowed_when, {"day": day_context, "shift": self._shift_ctx(shift)}))

    def _shift_ctx(self, shift: Shift) -> dict:
        return {
            "code": shift.code,
            "labels": sorted(shift.tags),
            "coverage": {"min": shift.coverage_min, "max": shift.coverage_max},
        }

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
