"""Explain day-type tagging for a date."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pharma_scheduler.io.load_config import load_config_bundle
from pharma_scheduler.solver.model import build_problem_data


def run_explain(instance_path: Path, target_date: date) -> int:
    bundle = load_config_bundle(instance_path)
    data = build_problem_data(
        instance=bundle.instance,
        rules=bundle.rules,
        shifts=bundle.shifts,
        demand=bundle.demand,
        worker_groups=bundle.worker_groups,
        service_cycle=bundle.service_cycle,
    )
    index = data.calendar.date_to_index.get(target_date)
    if index is None:
        print("Date outside solve range")
        return 1
    day = data.calendar.days[index]
    print(f"Date: {day.date.isoformat()}")
    print(f"Day type: {day.day_type.value}")
    print(f"Weekend: {day.is_weekend}")
    print(f"Holiday: {day.is_holiday}")
    print(f"Service week: {day.is_service_week}")
    return 0
