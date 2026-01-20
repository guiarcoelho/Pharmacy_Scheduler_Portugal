"""Config validation command."""

from __future__ import annotations

from pathlib import Path

from pharma_scheduler.io.load_config import load_config_bundle
from pharma_scheduler.solver.model import build_problem_data


def run_check(instance_path: Path) -> int:
    bundle = load_config_bundle(instance_path)
    data = build_problem_data(
        instance=bundle.instance,
        rules=bundle.rules,
        shifts=bundle.shifts,
        demand=bundle.demand,
        worker_groups=bundle.worker_groups,
        service_cycle=bundle.service_cycle,
    )

    missing = set()
    for day in data.calendar.days:
        for code in data.demand.demand_for(day.day_type).keys():
            if code not in data.shifts:
                missing.add(code)
    if missing:
        print(f"Missing shift definitions: {sorted(missing)}")
        return 1

    print("Config OK")
    print(f"Days in solve range: {len(data.calendar.days)}")
    print(f"Workers: {', '.join(data.workers)}")
    return 0
