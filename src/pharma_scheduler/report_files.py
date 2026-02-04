"""Helpers for report-window output file names."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re
from typing import Iterable, Optional


_SCHEDULE_RE = re.compile(
    r"^schedule_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.csv$"
)
_STATS_RE = re.compile(
    r"^worker_stats_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.csv$"
)


@dataclass(frozen=True)
class ReportWindowFile:
    path: Path
    report_start: date
    report_end: date

    @property
    def window_days(self) -> int:
        return (self.report_end - self.report_start).days + 1


def window_tag(report_start: date, report_end: date) -> str:
    return f"{report_start.isoformat()}_{report_end.isoformat()}"


def schedule_filename(report_start: date, report_end: date) -> str:
    return f"schedule_{window_tag(report_start, report_end)}.csv"


def worker_stats_filename(report_start: date, report_end: date) -> str:
    return f"worker_stats_{window_tag(report_start, report_end)}.csv"


def excel_filename(report_start: date, report_end: date) -> str:
    return f"schedule_{window_tag(report_start, report_end)}.xlsx"


def parse_schedule_window(path: Path) -> Optional[ReportWindowFile]:
    m = _SCHEDULE_RE.match(path.name)
    if not m:
        return None
    start = date.fromisoformat(m.group(1))
    end = date.fromisoformat(m.group(2))
    if end < start:
        return None
    return ReportWindowFile(path=path, report_start=start, report_end=end)


def parse_worker_stats_window(path: Path) -> Optional[ReportWindowFile]:
    m = _STATS_RE.match(path.name)
    if not m:
        return None
    start = date.fromisoformat(m.group(1))
    end = date.fromisoformat(m.group(2))
    if end < start:
        return None
    return ReportWindowFile(path=path, report_start=start, report_end=end)


def find_schedule_window_files(directory: Path) -> list[ReportWindowFile]:
    files = []
    for p in directory.glob("schedule_*.csv"):
        item = parse_schedule_window(p)
        if item is not None:
            files.append(item)
    return sorted(files, key=lambda x: (x.report_start, x.report_end, x.path.name))


def find_worker_stats_window_files(directory: Path) -> list[ReportWindowFile]:
    files = []
    for p in directory.glob("worker_stats_*.csv"):
        item = parse_worker_stats_window(p)
        if item is not None:
            files.append(item)
    return sorted(files, key=lambda x: (x.report_start, x.report_end, x.path.name))


def overlap_days(
    start_a: date,
    end_a: date,
    start_b: date,
    end_b: date,
) -> int:
    lo = max(start_a, start_b)
    hi = min(end_a, end_b)
    if hi < lo:
        return 0
    return (hi - lo).days + 1


def latest_by_mtime(paths: Iterable[Path]) -> Optional[Path]:
    existing = [p for p in paths if p.exists()]
    if not existing:
        return None
    return max(existing, key=lambda p: p.stat().st_mtime)
