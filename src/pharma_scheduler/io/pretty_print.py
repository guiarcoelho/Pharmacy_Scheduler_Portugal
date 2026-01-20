"""Console summary output."""

from __future__ import annotations

from typing import Any


def print_summary(result_status: str, objective_value: int | None, schedule: list[dict[str, Any]]) -> None:
    print(f"Status: {result_status}")
    if objective_value is not None:
        print(f"Objective: {objective_value}")
    print(f"Assignments: {len(schedule)}")
