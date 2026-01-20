from __future__ import annotations

from ortools.sat.python import cp_model

from ..domain.calendar import Calendar, DayType
from ..domain.demand import DemandProfile
from ..domain.workers import WorkerGroups
from ..solver.variables import Variables


def _sum_for_shift(
    variables: Variables, workers: list[str], day_index: int, shift_code: str
) -> cp_model.LinearExpr:
    return sum(
        variables.x[(w, day_index, shift_code)]
        for w in workers
        if (w, day_index, shift_code) in variables.x
    )


def add_coverage(
    model: cp_model.CpModel,
    calendar: Calendar,
    variables: Variables,
    demand: DemandProfile,
    groups: WorkerGroups,
) -> None:
    """Apply exact coverage constraints by day type."""
    core = groups.core
    for d in calendar.days:
        day_type = d.day_type
        demand_map = demand.demand_for_day_type(day_type)
        if day_type == DayType.SERVICE_WEEKEND_OR_HOLIDAY:
            for shift_code, required in demand_map.items():
                model.Add(_sum_for_shift(variables, core, d.index, shift_code) == required)
            if d.is_weekend and groups.service_extra:
                extra_worker = groups.service_extra[0]
                msw = variables.x.get((extra_worker, d.index, "MSW"))
                fsw = variables.x.get((extra_worker, d.index, "FSW"))
                if msw is not None and fsw is not None:
                    model.Add(msw + fsw == 1)
        else:
            for shift_code, required in demand_map.items():
                model.Add(_sum_for_shift(variables, core, d.index, shift_code) == required)
