"""Daily rest constraints based on shift transitions."""

from __future__ import annotations

from ortools.sat.python import cp_model

from pharma_scheduler.solver.model import ProblemData
from pharma_scheduler.solver.variables import Variables


def _build_forbidden_pairs(data: ProblemData) -> set[tuple[str, str]]:
    min_rest_minutes = data.rules.min_daily_rest_hours * 60
    forbidden: set[tuple[str, str]] = set()
    for code1, shift1 in data.shifts.items():
        for code2, shift2 in data.shifts.items():
            rest = (24 * 60 - shift1.clock_end_minute) + shift2.start_minute
            if rest < min_rest_minutes:
                forbidden.add((code1, code2))
    return forbidden


def apply_rest_rules(model: cp_model.CpModel, data: ProblemData, vars_: Variables) -> None:
    forbidden = _build_forbidden_pairs(data)
    days = data.calendar.days
    for day in days[:-1]:
        next_day = days[day.index + 1]
        day_shifts = data.day_shifts[day.index]
        next_shifts = data.day_shifts[next_day.index]
        for code1 in day_shifts:
            for code2 in next_shifts:
                if (code1, code2) in forbidden:
                    for worker in data.workers:
                        model.Add(
                            vars_.x[(worker, day.index, code1)]
                            + vars_.x[(worker, next_day.index, code2)]
                            <= 1
                        )
