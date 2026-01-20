"""Fairness constraints (mean-scaled absolute deviation)."""

from __future__ import annotations

from ortools.sat.python import cp_model

from pharma_scheduler.solver.model import ProblemData
from pharma_scheduler.solver.variables import Variables


def _mean_scaled_diffs(
    model: cp_model.CpModel,
    metrics: dict[str, cp_model.IntVar],
    workers: list[str],
    prefix: str,
) -> list[cp_model.IntVar]:
    n = len(workers)
    total = model.NewIntVar(0, 1_000_000 * n, f"total_{prefix}")
    model.Add(total == sum(metrics[w] for w in workers))
    diffs: list[cp_model.IntVar] = []
    for worker in workers:
        diff = model.NewIntVar(0, 1_000_000 * n, f"diff_{prefix}_{worker}")
        model.AddAbsEquality(diff, n * metrics[worker] - total)
        diffs.append(diff)
    return diffs


def apply_fairness(
    model: cp_model.CpModel, data: ProblemData, vars_: Variables
) -> dict[str, list[cp_model.IntVar]]:
    core = list(data.worker_groups.core)
    diff_map: dict[str, list[cp_model.IntVar]] = {}

    toggles = data.rules.fairness

    if toggles.weekend_minutes:
        diff_map["weekend_minutes"] = _mean_scaled_diffs(
            model, vars_.weekend_paid, core, "weekend_minutes"
        )
    if toggles.holiday_minutes:
        diff_map["holiday_minutes"] = _mean_scaled_diffs(
            model, vars_.holiday_paid, core, "holiday_minutes"
        )
    if toggles.weekday_excess:
        diff_map["weekday_excess"] = _mean_scaled_diffs(
            model, vars_.total_excess_by_worker, core, "weekday_excess"
        )

    if toggles.shift_count:
        excluded = {"NS", "NSW", "FSW"}
        for code in data.shifts.keys():
            if code in excluded:
                continue
            metrics = {worker: vars_.shift_counts[(worker, code)] for worker in core}
            diff_map[f"shift_{code}"] = _mean_scaled_diffs(
                model, metrics, core, f"shift_{code}"
            )

    return diff_map
