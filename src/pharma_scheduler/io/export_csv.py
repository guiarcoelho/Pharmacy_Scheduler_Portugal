from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..domain.metrics import ScheduleOutput


def export_csv(output: ScheduleOutput, out_dir: str) -> None:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    schedule_df = pd.DataFrame(output.schedule_rows)
    worker_df = pd.DataFrame(output.worker_rows)
    schedule_df.to_csv(out_path / "schedule.csv", index=False)
    worker_df.to_csv(out_path / "worker_stats.csv", index=False)
