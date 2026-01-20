from __future__ import annotations

from ortools.sat.python import cp_model

from ..domain.calendar import summarize_day_types
from ..solver.solve import SolveResult


def print_summary(result: SolveResult) -> None:
    context = result.context
    solver = result.solver
    print(f"Status: {result.status_name}")
    if result.status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print(f"Objective: {result.objective_value:.2f}")
        print("Objective breakdown:")
        for name, expr in context.objective_terms.items():
            try:
                value = solver.Value(expr)
            except TypeError:
                value = 0
            print(f"  - {name}: {value}")
    counts = summarize_day_types(context.calendar.days)
    print("Day type counts:")
    for key, value in counts.items():
        print(f"  - {key.value}: {value}")
