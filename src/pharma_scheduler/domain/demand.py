from __future__ import annotations

from dataclasses import dataclass

from .calendar import DayType


@dataclass(frozen=True)
class DemandProfile:
    demand: dict[DayType, dict[str, int]]

    @staticmethod
    def default() -> "DemandProfile":
        return DemandProfile(
            demand={
                DayType.NORMAL_WEEKDAY: {"M": 1, "I": 1, "T": 2},
                DayType.NORMAL_WEEKEND_OR_HOLIDAY: {"MW": 1, "IW": 1, "TW": 1},
                DayType.SERVICE_WEEKDAY: {"MS": 1, "IS": 1, "TS": 1, "NS": 1},
                DayType.SERVICE_WEEKEND_OR_HOLIDAY: {
                    "MSW": 1,
                    "ISW": 1,
                    "TSW": 1,
                    "NSW": 1,
                },
            }
        )

    def shifts_for_day_type(self, day_type: DayType) -> list[str]:
        return list(self.demand[day_type].keys())

    def demand_for_day_type(self, day_type: DayType) -> dict[str, int]:
        return self.demand[day_type]


COMMON_SHIFT_TYPES = [
    "M",
    "I",
    "T",
    "MW",
    "IW",
    "TW",
    "MS",
    "IS",
    "TS",
    "MSW",
    "ISW",
    "TSW",
    "FSW",
]
