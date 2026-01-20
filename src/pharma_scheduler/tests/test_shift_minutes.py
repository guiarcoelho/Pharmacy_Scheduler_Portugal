from __future__ import annotations

from pathlib import Path

from pharma_scheduler.io.load_config import load_shifts_config


def _config_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "config"


def test_shift_minutes() -> None:
    shifts = load_shifts_config(_config_dir() / "shifts.yaml")
    ts = shifts["TS"]
    tsw = shifts["TSW"]

    assert ts.clock_minutes == 479
    assert ts.paid_minutes == 480
    assert tsw.clock_minutes == 479
    assert tsw.paid_minutes == 480
