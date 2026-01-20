from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


def _parse_hhmm(value: str) -> int:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time format: {value}")
    hours = int(parts[0])
    minutes = int(parts[1])
    if hours < 0 or hours > 24 or minutes < 0 or minutes > 59:
        raise ValueError(f"Invalid time value: {value}")
    return hours * 60 + minutes


def _duration_minutes(start_min: int, end_min: int) -> int:
    end = end_min
    if end <= start_min:
        end += 24 * 60
    return end - start_min


@dataclass(frozen=True)
class Shift:
    code: str
    start: str
    end: str
    paid_end: str
    clock_end_override: str | None
    tags: frozenset[str]
    start_minutes: int
    clock_end_minutes: int
    paid_end_minutes: int
    clock_minutes: int
    paid_minutes: int

    @staticmethod
    def from_spec(spec: dict) -> "Shift":
        start_minutes = _parse_hhmm(spec["start"])
        end_minutes = _parse_hhmm(spec["end"])
        paid_end_minutes = _parse_hhmm(spec["paid_end"])
        clock_end_override = spec.get("clock_end_override")
        clock_end_minutes = (
            _parse_hhmm(clock_end_override) if clock_end_override else end_minutes
        )
        clock_minutes = _duration_minutes(start_minutes, clock_end_minutes)
        paid_minutes = _duration_minutes(start_minutes, paid_end_minutes)
        return Shift(
            code=spec["code"],
            start=spec["start"],
            end=spec["end"],
            paid_end=spec["paid_end"],
            clock_end_override=clock_end_override,
            tags=frozenset(spec.get("tags", [])),
            start_minutes=start_minutes,
            clock_end_minutes=clock_end_minutes,
            paid_end_minutes=paid_end_minutes,
            clock_minutes=clock_minutes,
            paid_minutes=paid_minutes,
        )


@dataclass
class ShiftCatalog:
    shifts: dict[str, Shift]

    @staticmethod
    def from_specs(specs: Iterable[dict]) -> "ShiftCatalog":
        shifts = {}
        for spec in specs:
            shift = Shift.from_spec(spec)
            shifts[shift.code] = shift
        return ShiftCatalog(shifts=shifts)

    def __getitem__(self, code: str) -> Shift:
        return self.shifts[code]

    def codes(self) -> list[str]:
        return list(self.shifts.keys())
