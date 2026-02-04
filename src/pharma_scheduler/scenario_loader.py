"""Scenario loader for config-first scheduler.

`scenario.yaml` is a lightweight manifest that points to the other YAML files
that define a scheduling scenario (calendar, workers, shifts, constraints, ...).

Paths are resolved relative to the scenario file location, so you can keep the
manifest in `config/` and the scenario contents in `config/scenarios/<name>/`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml


def _load_yaml(path: Path) -> dict:
    """Internal helper for `_load_yaml`."""
    with path.open() as f:
        return yaml.safe_load(f) or {}


def load_scenario(scenario_path: str) -> Dict[str, Any]:
    """Execute `load_scenario`."""
    scenario_file = Path(scenario_path)
    if not scenario_file.exists():
        raise FileNotFoundError(f"Scenario file not found: {scenario_path}")

    root = _load_yaml(scenario_file)
    scenario = root.get("scenario", root)

    base_dir = scenario_file.parent
    resolved_paths: Dict[str, str] = {}

    def _resolve(key: str) -> dict:
        """Internal helper for `_resolve`."""
        rel = scenario.get(key)
        if rel is None:
            return {}
        path = (base_dir / rel).resolve()
        resolved_paths[key] = str(path)
        return _load_yaml(path)

    data = {
        "calendar": _resolve("calendar"),
        "workers": _resolve("workers"),
        "shifts": _resolve("shifts"),
        "constraints": _resolve("constraints"),
        "special_days": _resolve("special_days"),
        "solver": _resolve("solver"),
        "memory": _resolve("memory"),
    }
    data["meta"] = scenario
    resolved_paths["scenario_root"] = str(base_dir.resolve())
    data["resolved_paths"] = resolved_paths
    return data
