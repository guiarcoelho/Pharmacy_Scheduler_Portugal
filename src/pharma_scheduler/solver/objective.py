from __future__ import annotations

from ortools.sat.python import cp_model

from ..io.load_config import ObjectiveWeights
from ..solver.variables import Variables
from ..rules.fairness import FairnessTerm


def build_objective(
    model: cp_model.CpModel,
    calendar,
    variables: Variables,
    weights: ObjectiveWeights,
    no_day_off: dict[tuple[str, object], cp_model.BoolVar],
    fairness_terms: list[FairnessTerm],
) -> dict[str, cp_model.LinearExpr]:
    work_cost = (
        weights.saturday_minutes * sum(variables.sat_paid_minutes.values())
        + weights.sunday_minutes * sum(variables.sun_paid_minutes.values())
        + weights.holiday_minutes * sum(variables.holiday_paid_minutes.values())
    )

    weekday_excess_cost = weights.weekday_excess_minutes * sum(
        variables.excess40.values()
    )
    weekly_rest_cost = weights.weekly_rest_penalty * sum(no_day_off.values())

    fairness_cost = 0
    for term in fairness_terms:
        if term.metric == "weekend_minutes":
            weight = weights.fairness_weekend_minutes
        elif term.metric == "holiday_minutes":
            weight = weights.fairness_holiday_minutes
        elif term.metric == "weekday_excess":
            weight = weights.fairness_weekday_excess
        elif term.metric == "shift_counts":
            weight = weights.fairness_shift_counts
        else:
            weight = 0
        fairness_cost += weight * sum(term.diffs)

    model.Minimize(work_cost + weekday_excess_cost + weekly_rest_cost + fairness_cost)

    return {
        "work_cost": work_cost,
        "weekday_excess_cost": weekday_excess_cost,
        "weekly_rest_cost": weekly_rest_cost,
        "fairness_cost": fairness_cost,
    }
