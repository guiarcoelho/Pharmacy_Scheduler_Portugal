"""Service week rule placeholder (calendar handles tagging)."""

from __future__ import annotations

from ortools.sat.python import cp_model

from pharma_scheduler.solver.model import ProblemData
from pharma_scheduler.solver.variables import Variables


def apply_service_week_rules(model: cp_model.CpModel, data: ProblemData, vars_: Variables) -> None:
    _ = (model, data, vars_)
