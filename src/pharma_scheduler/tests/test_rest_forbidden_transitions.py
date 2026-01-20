from __future__ import annotations

from datetime import date
from pathlib import Path

from pharma_scheduler.io.load_config import ConfigBundle, load_config_bundle
from pharma_scheduler.rules.rest_rules import _build_forbidden_pairs
from pharma_scheduler.solver.model import build_problem_data


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_forbidden_transitions() -> None:
    bundle = load_config_bundle(_project_root() / "config" / "instance.yaml")
    instance = bundle.instance.model_copy(
        update={"report_start": date(2026, 2, 1), "report_end": date(2026, 2, 2)}
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
    forbidden = _build_forbidden_pairs(data)

    assert ("TS", "M") in forbidden
    assert ("TSW", "MSW") in forbidden
