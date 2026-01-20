from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ortools.sat.python import cp_model

from ..domain.calendar import Calendar, DayType
from ..domain.demand import DemandProfile
from ..domain.shifts import ShiftCatalog


@dataclass
class Variables:
    x: dict[tuple[str, int, str], cp_model.BoolVar]
    works: dict[tuple[str, int], cp_model.BoolVar]
    paid_minutes_day: dict[tuple[str, int], cp_model.IntVar]
    shift_counts: dict[tuple[str, str], cp_model.IntVar]
    weekend_paid_minutes: dict[str, cp_model.IntVar]
    holiday_paid_minutes: dict[str, cp_model.IntVar]
    sat_paid_minutes: dict[str, cp_model.IntVar]
    sun_paid_minutes: dict[str, cp_model.IntVar]
    weekday_paid_minutes: dict[tuple[str, object], cp_model.IntVar]
    excess40: dict[tuple[str, object], cp_model.IntVar]
    sum_excess40: dict[str, cp_model.IntVar]
    total_paid_minutes: dict[str, cp_model.IntVar]
    day_shifts: dict[int, list[str]]


def _sum_vars(vars_list: Iterable[cp_model.IntVar | cp_model.BoolVar]) -> cp_model.LinearExpr:
    return sum(vars_list) if vars_list else 0


def create_variables(
    model: cp_model.CpModel,
    calendar: Calendar,
    shifts: ShiftCatalog,
    demand: DemandProfile,
    workers: list[str],
) -> Variables:
    day_shifts: dict[int, list[str]] = {}
    for d in calendar.days:
        shifts_today = list(demand.shifts_for_day_type(d.day_type))
        if d.is_service_day and d.is_weekend and "FSW" not in shifts_today:
            shifts_today.append("FSW")
        day_shifts[d.index] = shifts_today

    x: dict[tuple[str, int, str], cp_model.BoolVar] = {}
    works: dict[tuple[str, int], cp_model.BoolVar] = {}
    paid_minutes_day: dict[tuple[str, int], cp_model.IntVar] = {}

    max_shift_minutes = max(s.paid_minutes for s in shifts.shifts.values())
    for w in workers:
        for d in calendar.days:
            shifts_today = day_shifts[d.index]
            vars_today = []
            for s in shifts_today:
                var = model.NewBoolVar(f"x_{w}_{d.index}_{s}")
                x[(w, d.index, s)] = var
                vars_today.append(var)
            works_var = model.NewBoolVar(f"works_{w}_{d.index}")
            works[(w, d.index)] = works_var
            model.Add(_sum_vars(vars_today) == works_var)
            paid_var = model.NewIntVar(0, max_shift_minutes, f"paid_{w}_{d.index}")
            model.Add(
                paid_var
                == _sum_vars(
                    x[(w, d.index, s)] * shifts[s].paid_minutes for s in shifts_today
                )
            )
            paid_minutes_day[(w, d.index)] = paid_var

    report_days = [d.index for d in calendar.days if d.is_report]
    report_weekend_nonholiday = [
        d.index
        for d in calendar.days
        if d.is_report and d.is_weekend and not d.is_holiday
    ]
    report_saturdays = [
        d.index
        for d in calendar.days
        if d.is_report and d.is_saturday and not d.is_holiday
    ]
    report_sundays = [
        d.index
        for d in calendar.days
        if d.is_report and d.is_sunday and not d.is_holiday
    ]
    report_holidays = [d.index for d in calendar.days if d.is_report and d.is_holiday]

    weekend_paid_minutes: dict[str, cp_model.IntVar] = {}
    holiday_paid_minutes: dict[str, cp_model.IntVar] = {}
    sat_paid_minutes: dict[str, cp_model.IntVar] = {}
    sun_paid_minutes: dict[str, cp_model.IntVar] = {}
    total_paid_minutes: dict[str, cp_model.IntVar] = {}

    max_total_minutes = max_shift_minutes * len(report_days)
    for w in workers:
        weekend_var = model.NewIntVar(0, max_total_minutes, f"weekend_paid_{w}")
        holiday_var = model.NewIntVar(0, max_total_minutes, f"holiday_paid_{w}")
        sat_var = model.NewIntVar(0, max_total_minutes, f"sat_paid_{w}")
        sun_var = model.NewIntVar(0, max_total_minutes, f"sun_paid_{w}")
        total_var = model.NewIntVar(0, max_total_minutes, f"total_paid_{w}")

        model.Add(
            weekend_var
            == _sum_vars(paid_minutes_day[(w, d)] for d in report_weekend_nonholiday)
        )
        model.Add(
            holiday_var
            == _sum_vars(paid_minutes_day[(w, d)] for d in report_holidays)
        )
        model.Add(sat_var == _sum_vars(paid_minutes_day[(w, d)] for d in report_saturdays))
        model.Add(sun_var == _sum_vars(paid_minutes_day[(w, d)] for d in report_sundays))
        model.Add(total_var == _sum_vars(paid_minutes_day[(w, d)] for d in report_days))

        weekend_paid_minutes[w] = weekend_var
        holiday_paid_minutes[w] = holiday_var
        sat_paid_minutes[w] = sat_var
        sun_paid_minutes[w] = sun_var
        total_paid_minutes[w] = total_var

    shift_counts: dict[tuple[str, str], cp_model.IntVar] = {}
    for w in workers:
        for shift_code in shifts.codes():
            count_var = model.NewIntVar(0, len(report_days), f"count_{w}_{shift_code}")
            model.Add(
                count_var
                == _sum_vars(
                    x[(w, d, shift_code)]
                    for d in report_days
                    if (w, d, shift_code) in x
                )
            )
            shift_counts[(w, shift_code)] = count_var

    report_weeks = calendar.report_weeks()
    weekday_paid_minutes: dict[tuple[str, object], cp_model.IntVar] = {}
    excess40: dict[tuple[str, object], cp_model.IntVar] = {}
    sum_excess40: dict[str, cp_model.IntVar] = {}

    weekday_day_types = {DayType.NORMAL_WEEKDAY, DayType.SERVICE_WEEKDAY}
    for w in workers:
        excess_list = []
        for week_id, indices in report_weeks.items():
            weekday_indices = [
                i for i in indices if calendar.days[i].day_type in weekday_day_types
            ]
            week_var = model.NewIntVar(0, max_shift_minutes * 5, f"weekday_{w}_{week_id}")
            model.Add(
                week_var
                == _sum_vars(paid_minutes_day[(w, i)] for i in weekday_indices)
            )
            weekday_paid_minutes[(w, week_id)] = week_var
            excess_var = model.NewIntVar(0, max_shift_minutes * 5, f"excess_{w}_{week_id}")
            model.Add(excess_var >= week_var - 2400)
            model.Add(excess_var >= 0)
            excess40[(w, week_id)] = excess_var
            excess_list.append(excess_var)
        sum_excess = model.NewIntVar(0, max_shift_minutes * 5 * len(report_weeks), f"sum_excess_{w}")
        model.Add(sum_excess == _sum_vars(excess_list))
        sum_excess40[w] = sum_excess

    return Variables(
        x=x,
        works=works,
        paid_minutes_day=paid_minutes_day,
        shift_counts=shift_counts,
        weekend_paid_minutes=weekend_paid_minutes,
        holiday_paid_minutes=holiday_paid_minutes,
        sat_paid_minutes=sat_paid_minutes,
        sun_paid_minutes=sun_paid_minutes,
        weekday_paid_minutes=weekday_paid_minutes,
        excess40=excess40,
        sum_excess40=sum_excess40,
        total_paid_minutes=total_paid_minutes,
        day_shifts=day_shifts,
    )
