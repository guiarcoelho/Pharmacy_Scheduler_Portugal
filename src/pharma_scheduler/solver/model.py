from __future__ import annotations

from dataclasses import dataclass

from ortools.sat.python import cp_model

from ..domain.calendar import Calendar
from ..domain.demand import DemandProfile
from ..domain.shifts import ShiftCatalog
from ..domain.workers import WorkerGroups
from ..io.load_config import InstanceConfig, RulesConfig
from ..rules.coverage import add_coverage
from ..rules.eligibility import add_eligibility
from ..rules.fairness import add_fairness_terms
from ..rules.rest_rules import add_daily_rest_constraints
from ..rules.service_week import add_service_week_rules
from ..rules.sunday_comp import add_sunday_compensation
from ..rules.weekend_coupling import add_weekend_coupling
from ..rules.weekly_rest_soft import add_weekly_rest_soft
from .objective import build_objective
from .variables import Variables, create_variables


@dataclass
class ModelContext:
    model: cp_model.CpModel
    variables: Variables
    calendar: Calendar
    shifts: ShiftCatalog
    demand: DemandProfile
    groups: WorkerGroups
    instance: InstanceConfig
    rules: RulesConfig
    objective_terms: dict[str, cp_model.LinearExpr]


def build_model(
    instance: InstanceConfig, rules: RulesConfig, shifts: ShiftCatalog
) -> ModelContext:
    calendar = Calendar.build(
        report_start=instance.report_start,
        report_end=instance.report_end,
        buffer_days=instance.buffer_days,
        locale=instance.locale,
        anchor_monday=instance.service_cycle.anchor_monday,
        cycle_weeks=instance.service_cycle.cycle_weeks,
        service_week_in_cycle=instance.service_cycle.service_week_in_cycle,
    )
    demand = DemandProfile.default()
    groups = instance.groups()

    model = cp_model.CpModel()
    variables = create_variables(model, calendar, shifts, demand, instance.workers)

    add_eligibility(model, calendar, shifts, variables, groups)
    add_coverage(model, calendar, variables, demand, groups)
    add_weekend_coupling(model, calendar, variables, groups)
    add_daily_rest_constraints(
        model, calendar, shifts, variables, rules.min_daily_rest_hours
    )
    add_sunday_compensation(model, calendar, variables, groups)
    add_service_week_rules(model, calendar, variables, groups)
    no_day_off = add_weekly_rest_soft(model, calendar, variables, groups)
    fairness_terms = add_fairness_terms(
        model, calendar, shifts, variables, groups, rules.fairness
    )
    objective_terms = build_objective(
        model, calendar, variables, rules.objective_weights, no_day_off, fairness_terms
    )

    return ModelContext(
        model=model,
        variables=variables,
        calendar=calendar,
        shifts=shifts,
        demand=demand,
        groups=groups,
        instance=instance,
        rules=rules,
        objective_terms=objective_terms,
    )
