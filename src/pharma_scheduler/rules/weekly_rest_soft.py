from __future__ import annotations

from ortools.sat.python import cp_model

from ..domain.calendar import Calendar
from ..domain.workers import WorkerGroups
from ..solver.variables import Variables


def add_weekly_rest_soft(
    model: cp_model.CpModel, calendar: Calendar, variables: Variables, groups: WorkerGroups
) -> dict[tuple[str, object], cp_model.BoolVar]:
    """Soft constraint: at least one day off per week."""
    no_day_off: dict[tuple[str, object], cp_model.BoolVar] = {}
    for week_id, indices in calendar.report_weeks().items():
        for w in groups.core:
            total_work_days = sum(variables.works[(w, i)] for i in indices)
            flag = model.NewBoolVar(f"no_day_off_{w}_{week_id}")
            model.Add(total_work_days == 7).OnlyEnforceIf(flag)
            model.Add(total_work_days <= 6).OnlyEnforceIf(flag.Not())
            no_day_off[(w, week_id)] = flag
    return no_day_off
