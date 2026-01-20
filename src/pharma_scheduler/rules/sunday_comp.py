from __future__ import annotations

from ortools.sat.python import cp_model

from ..domain.calendar import Calendar
from ..domain.workers import WorkerGroups
from ..solver.variables import Variables


def add_sunday_compensation(
    model: cp_model.CpModel,
    calendar: Calendar,
    variables: Variables,
    groups: WorkerGroups,
) -> None:
    """Apply Sunday compensation rules for core workers."""
    for d in calendar.days:
        if not (d.is_sunday and d.is_report):
            continue
        candidates = calendar.weekday_candidates_for_sunday(d.index)
        next_sat, next_sun = calendar.next_weekend_after_sunday(d.index)
        for w in groups.core:
            sun_work = variables.works[(w, d.index)]
            if candidates:
                model.Add(
                    sum(variables.works[(w, idx)] for idx in candidates) <= len(candidates) - 1
                ).OnlyEnforceIf(sun_work)
            if next_sat is not None:
                model.Add(variables.works[(w, next_sat)] == 0).OnlyEnforceIf(sun_work)
            if next_sun is not None:
                model.Add(variables.works[(w, next_sun)] == 0).OnlyEnforceIf(sun_work)
