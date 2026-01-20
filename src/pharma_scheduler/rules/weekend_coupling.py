from __future__ import annotations

from ortools.sat.python import cp_model

from ..domain.calendar import Calendar
from ..domain.workers import WorkerGroups
from ..solver.variables import Variables


def add_weekend_coupling(
    model: cp_model.CpModel, calendar: Calendar, variables: Variables, groups: WorkerGroups
) -> None:
    """Core workers must work Saturday and Sunday together or not at all."""
    for sat_idx, sun_idx in calendar.saturday_sunday_pairs():
        for w in groups.core:
            model.Add(variables.works[(w, sat_idx)] == variables.works[(w, sun_idx)])
