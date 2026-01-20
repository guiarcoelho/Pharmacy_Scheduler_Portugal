from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkerGroups:
    core: list[str]
    night_capable: list[str]
    service_extra: list[str]

    @property
    def all_workers(self) -> list[str]:
        return sorted(set(self.core + self.night_capable + self.service_extra))
