from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from ..domain.shifts import ShiftCatalog
from ..domain.workers import WorkerGroups


class ShiftSpec(BaseModel):
    code: str
    start: str
    end: str
    paid_end: str
    clock_end_override: str | None = None
    tags: list[str] = []


class ShiftsConfig(BaseModel):
    shifts: list[ShiftSpec]


class ServiceCycleConfig(BaseModel):
    anchor_monday: date
    cycle_weeks: int
    service_week_in_cycle: int


class SolverConfig(BaseModel):
    time_limit_seconds: int = 30
    num_search_workers: int = 8
    debug: bool = False


class InstanceConfig(BaseModel):
    report_start: date
    report_end: date
    buffer_days: int
    workers: list[str]
    worker_groups: dict[str, list[str]]
    service_cycle: ServiceCycleConfig
    locale: str
    solver: SolverConfig = Field(default_factory=SolverConfig)

    def groups(self) -> WorkerGroups:
        return WorkerGroups(
            core=self.worker_groups["core"],
            night_capable=self.worker_groups["night_capable"],
            service_extra=self.worker_groups["service_extra"],
        )


class ObjectiveWeights(BaseModel):
    saturday_minutes: int
    sunday_minutes: int
    holiday_minutes: int
    weekday_excess_minutes: int
    weekly_rest_penalty: int
    fairness_weekend_minutes: int
    fairness_holiday_minutes: int
    fairness_weekday_excess: int
    fairness_shift_counts: int


class FairnessToggles(BaseModel):
    enable_weekend_minutes: bool = True
    enable_holiday_minutes: bool = True
    enable_weekday_excess: bool = True
    enable_shift_counts: bool = True


class RulesConfig(BaseModel):
    min_daily_rest_hours: int
    objective_weights: ObjectiveWeights
    fairness: FairnessToggles


@dataclass(frozen=True)
class LoadedConfig:
    instance: InstanceConfig
    rules: RulesConfig
    shifts: ShiftCatalog


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_from_instance_path(instance_path: str) -> LoadedConfig:
    instance_file = Path(instance_path)
    base_dir = instance_file.parent
    instance = InstanceConfig.model_validate(_load_yaml(instance_file))
    shifts_cfg = ShiftsConfig.model_validate(_load_yaml(base_dir / "shifts.yaml"))
    shifts = ShiftCatalog.from_specs([s.model_dump() for s in shifts_cfg.shifts])
    rules = RulesConfig.model_validate(_load_yaml(base_dir / "rules.yaml"))
    return LoadedConfig(instance=instance, rules=rules, shifts=shifts)
