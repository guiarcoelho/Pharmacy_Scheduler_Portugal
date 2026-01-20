from __future__ import annotations

from dataclasses import dataclass

from ..solver.solve import SolveResult


@dataclass
class ScheduleOutput:
    schedule_rows: list[dict]
    worker_rows: list[dict]


def build_schedule_rows(result: SolveResult) -> list[dict]:
    rows: list[dict] = []
    calendar = result.context.calendar
    variables = result.context.variables
    solver = result.solver
    for (w, d, s), var in variables.x.items():
        if not calendar.days[d].is_report:
            continue
        if solver.Value(var) == 1:
            day = calendar.days[d]
            rows.append(
                {
                    "date": day.day.isoformat(),
                    "day_type": day.day_type.value,
                    "shift_code": s,
                    "worker": w,
                }
            )
    rows.sort(key=lambda r: (r["date"], r["shift_code"], r["worker"]))
    return rows


def build_worker_rows(result: SolveResult) -> list[dict]:
    calendar = result.context.calendar
    variables = result.context.variables
    solver = result.solver
    weeks = calendar.report_weeks()

    rows: list[dict] = []
    for w in result.context.instance.workers:
        row: dict[str, int | str] = {
            "worker": w,
            "total_paid_minutes": solver.Value(variables.total_paid_minutes[w]),
            "weekend_paid_minutes": solver.Value(variables.weekend_paid_minutes[w]),
            "sat_paid_minutes": solver.Value(variables.sat_paid_minutes[w]),
            "sun_paid_minutes": solver.Value(variables.sun_paid_minutes[w]),
            "holiday_paid_minutes": solver.Value(variables.holiday_paid_minutes[w]),
        }
        for week_id in weeks.keys():
            key = week_id.isoformat()
            row[f"weekday_paid_minutes_{key}"] = solver.Value(
                variables.weekday_paid_minutes[(w, week_id)]
            )
            row[f"excess40_{key}"] = solver.Value(variables.excess40[(w, week_id)])
        for shift_code in result.context.shifts.codes():
            row[f"count_{shift_code}"] = solver.Value(
                variables.shift_counts[(w, shift_code)]
            )
        sundays_worked = 0
        for d in calendar.days:
            if d.is_report and d.is_sunday and solver.Value(variables.works[(w, d.index)]) == 1:
                sundays_worked += 1
        row["sundays_worked"] = sundays_worked
        row["sunday_comp_triggers"] = sundays_worked if w in result.context.groups.core else 0

        weekends_off = 0
        for sat_idx, sun_idx in calendar.saturday_sunday_pairs():
            if not (calendar.days[sat_idx].is_report and calendar.days[sun_idx].is_report):
                continue
            if (
                solver.Value(variables.works[(w, sat_idx)]) == 0
                and solver.Value(variables.works[(w, sun_idx)]) == 0
            ):
                weekends_off += 1
        row["full_weekends_off"] = weekends_off
        rows.append(row)
    return rows


def build_outputs(result: SolveResult) -> ScheduleOutput:
    return ScheduleOutput(
        schedule_rows=build_schedule_rows(result),
        worker_rows=build_worker_rows(result),
    )
