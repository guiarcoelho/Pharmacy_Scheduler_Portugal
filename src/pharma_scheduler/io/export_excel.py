"""Excel export utilities (optional)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def export_excel(path: Path, schedule: list[dict[str, Any]], stats: list[dict[str, Any]]) -> None:
    try:
        import openpyxl  # noqa: F401
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("openpyxl is required for Excel export") from exc

    schedule_df = pd.DataFrame(schedule).sort_values(["date", "shift_code", "worker"])
    stats_df = pd.DataFrame(stats).sort_values(["worker"])

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        schedule_df.to_excel(writer, sheet_name="schedule", index=False)
        stats_df.to_excel(writer, sheet_name="worker_stats", index=False)
