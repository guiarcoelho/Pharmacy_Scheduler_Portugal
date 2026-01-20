from __future__ import annotations

from dataclasses import dataclass

from ortools.sat.python import cp_model

from .model import ModelContext


@dataclass
class SolveResult:
    context: ModelContext
    solver: cp_model.CpSolver
    status: int

    @property
    def status_name(self) -> str:
        return self.solver.StatusName(self.status)

    @property
    def objective_value(self) -> float:
        if self.status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return self.solver.ObjectiveValue()
        return float("inf")


def solve_model(context: ModelContext) -> SolveResult:
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = context.instance.solver.time_limit_seconds
    solver.parameters.num_search_workers = context.instance.solver.num_search_workers
    if context.instance.solver.debug:
        solver.parameters.log_search_progress = True
        solver.parameters.cp_model_presolve = True
    status = solver.Solve(context.model)
    return SolveResult(context=context, solver=solver, status=status)
