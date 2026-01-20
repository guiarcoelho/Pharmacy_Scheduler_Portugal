from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from pharma_scheduler.io.load_config import ConfigBundle, load_config_bundle
from pharma_scheduler.solver.model import build_problem_data
from pharma_scheduler.solver.solve import solve_instance


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def solved_small_instance():
    bundle = load_config_bundle(_project_root() / "config" / "instance.yaml")
    solver_cfg = bundle.instance.solver.model_copy(
        update={"time_limit_seconds": 10, "num_search_workers": 4, "debug": False}
    )
    instance = bundle.instance.model_copy(
        update={
            "report_start": date(2026, 2, 1),
            "report_end": date(2026, 2, 14),
            "solver": solver_cfg,
        }
    )
    updated = ConfigBundle(
        instance=instance,
        rules=bundle.rules,
        shifts=bundle.shifts,
        demand=bundle.demand,
        worker_groups=bundle.worker_groups,
        service_cycle=bundle.service_cycle,
    )
    data = build_problem_data(
        instance=updated.instance,
        rules=updated.rules,
        shifts=updated.shifts,
        demand=updated.demand,
        worker_groups=updated.worker_groups,
        service_cycle=updated.service_cycle,
    )
    result = solve_instance(updated)
    return updated, data, result
