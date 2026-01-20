from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..domain.metrics import ScheduleOutput


def export_excel(output: ScheduleOutput, out_dir: str) -> None:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    schedule_df = pd.DataFrame(output.schedule_rows)
    worker_df = pd.DataFrame(output.worker_rows)

    if schedule_df.empty:
        schedule_grid = schedule_df
    else:
        grouped = (
            schedule_df.groupby(["date", "day_type", "shift_code"])["worker"]
            .apply(lambda x: ", ".join(sorted(x)))
            .reset_index()
        )
        schedule_grid = grouped.pivot_table(
            index=["date", "day_type"],
            columns="shift_code",
            values="worker",
            aggfunc="first",
        ).reset_index()

    excel_path = out_path / "schedule.xlsx"
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        schedule_grid.to_excel(writer, sheet_name="schedule", index=False)
        worker_df.to_excel(writer, sheet_name="worker_stats", index=False)
