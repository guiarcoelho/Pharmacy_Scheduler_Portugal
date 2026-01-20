from __future__ import annotations

from ortools.sat.python import cp_model

from ..domain.calendar import Calendar
from ..domain.shifts import ShiftCatalog
from ..domain.workers import WorkerGroups
from ..solver.variables import Variables


def add_eligibility(
    model: cp_model.CpModel,
    calendar: Calendar,
    shifts: ShiftCatalog,
    variables: Variables,
    groups: WorkerGroups,
) -> None:
    """Restrict shift eligibility for night-only and extra-service workers."""
    night_shifts = {"NS", "NSW"}
    for w in groups.core:
        if w not in groups.night_capable:
            for d in calendar.days:
                for s in night_shifts:
                    var = variables.x.get((w, d.index, s))
                    if var is not None:
                        model.Add(var == 0)
        for d in calendar.days:
            var = variables.x.get((w, d.index, "FSW"))
            if var is not None:
                model.Add(var == 0)

    extra_workers = set(groups.service_extra)
    for w in extra_workers:
        for d in calendar.days:
            is_service_weekend = d.is_service_day and d.is_weekend
            if not is_service_weekend:
                for s in variables.day_shifts[d.index]:
                    var = variables.x.get((w, d.index, s))
                    if var is not None:
                        model.Add(var == 0)
                model.Add(variables.works[(w, d.index)] == 0)
                continue

            allowed = {"MSW", "FSW"}
            for s in variables.day_shifts[d.index]:
                var = variables.x.get((w, d.index, s))
                if var is None:
                    continue
                if s not in allowed:
                    model.Add(var == 0)
            msw = variables.x.get((w, d.index, "MSW"))
            fsw = variables.x.get((w, d.index, "FSW"))
            if msw is not None and fsw is not None:
                model.Add(msw + fsw == 1)
                model.Add(variables.works[(w, d.index)] == 1)
