"""Memory helpers (hints + hard locks) for report-window scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Iterable, Tuple

import pandas as pd

from .report_files import (
    ReportWindowFile,
    find_schedule_window_files,
    overlap_days,
    parse_schedule_window,
)


AssignmentKey = Tuple[date, str]


@dataclass(frozen=True)
class SourceAssignment:
    """Encapsulates `SourceAssignment` behavior and data."""
    shift: str
    source_path: Path


@dataclass
class MemoryApplyResult:
    """Encapsulates `MemoryApplyResult` behavior and data."""
    hints_enabled: bool = False
    locks_enabled: bool = False
    hint_source_files: int = 0
    hint_candidates: int = 0
    hints_applied: int = 0
    hints_skipped_locked: int = 0
    hints_skipped_invalid: int = 0
    hint_source_order: list[str] | None = None
    hint_selected_counts: dict[str, int] | None = None
    lock_source_files: int = 0
    lock_candidates: int = 0
    locks_applied: int = 0
    lock_conflicts: int = 0
    lock_invalid: int = 0


def _normalize_memory_config(memory_config: dict | None) -> dict:
    """Internal helper for `_normalize_memory_config`."""
    if not memory_config:
        return {}
    if "memory" in memory_config and isinstance(memory_config["memory"], dict):
        return memory_config["memory"]
    return memory_config


def _load_schedule_rows(path: Path) -> pd.DataFrame:
    """Internal helper for `_load_schedule_rows`."""
    df = pd.read_csv(path)
    required = {"date", "worker", "shift"}
    missing = required - set(df.columns)
    if missing:
        missing_txt = ", ".join(sorted(missing))
        raise ValueError(f"{path} is missing required columns: {missing_txt}")
    out = df[["date", "worker", "shift"]].copy()
    out["date"] = pd.to_datetime(out["date"]).dt.date
    out["worker"] = out["worker"].astype(str)
    out["shift"] = out["shift"].astype(str)
    return out


def _resolve_path(
    raw_path: str,
    *,
    scenario_base_dir: Path,
    memory_config_path: Path | None,
) -> Path:
    """Internal helper for `_resolve_path`."""
    p = Path(raw_path)
    if p.is_absolute():
        return p
    if memory_config_path is not None:
        from_memory = (memory_config_path.parent / p).resolve()
        if from_memory.exists():
            return from_memory
    return (scenario_base_dir / p).resolve()


def _window_for_source(path: Path, rows: pd.DataFrame) -> tuple[date, date]:
    """Internal helper for `_window_for_source`."""
    parsed = parse_schedule_window(path)
    if parsed is not None:
        return parsed.report_start, parsed.report_end
    start = rows["date"].min()
    end = rows["date"].max()
    if end < start:
        raise ValueError(f"{path} has invalid date range")
    return start, end


def _collect_lock_assignments(
    *,
    lock_paths: Iterable[Path],
    report_start: date,
    report_end: date,
) -> tuple[Dict[AssignmentKey, SourceAssignment], int]:
    """Internal helper for `_collect_lock_assignments`."""
    assignments: Dict[AssignmentKey, SourceAssignment] = {}
    candidates = 0
    for path in lock_paths:
        rows = _load_schedule_rows(path)
        src_start, src_end = _window_for_source(path, rows)
        overlap = overlap_days(src_start, src_end, report_start, report_end)
        if overlap <= 0:
            continue
        lo = max(src_start, report_start)
        hi = min(src_end, report_end)
        rows = rows[(rows["date"] >= lo) & (rows["date"] <= hi)]
        for _, row in rows.iterrows():
            candidates += 1
            key = (row["date"], row["worker"])
            next_value = SourceAssignment(shift=row["shift"], source_path=path)
            current = assignments.get(key)
            if current is None:
                assignments[key] = next_value
                continue
            if current.shift != next_value.shift:
                raise ValueError(
                    "Conflicting hard locks for "
                    f"{row['worker']} on {row['date']}: "
                    f"{current.shift} ({current.source_path}) vs "
                    f"{next_value.shift} ({next_value.source_path})"
                )
    return assignments, candidates


def _rank_hint_sources(
    *,
    out_dir: Path,
    report_start: date,
    report_end: date,
) -> list[ReportWindowFile]:
    """Internal helper for `_rank_hint_sources`."""
    candidates = []
    for item in find_schedule_window_files(out_dir):
        overlap = overlap_days(
            item.report_start, item.report_end, report_start, report_end
        )
        if overlap <= 0:
            continue
        mtime = item.path.stat().st_mtime
        candidates.append((item, overlap, item.window_days, mtime))

    candidates.sort(
        key=lambda x: (-x[1], -x[2], -x[3], x[0].path.name)
    )
    return [x[0] for x in candidates]


def _collect_hint_assignments(
    *,
    ranked_sources: Iterable[ReportWindowFile],
    report_start: date,
    report_end: date,
    worker_ids: list[str],
) -> tuple[Dict[AssignmentKey, SourceAssignment], int, dict[str, int]]:
    """Internal helper for `_collect_hint_assignments`."""
    assignments: Dict[AssignmentKey, SourceAssignment] = {}
    candidates = 0
    selected_counts: dict[str, int] = {}

    for source in ranked_sources:
        lo = max(source.report_start, report_start)
        hi = min(source.report_end, report_end)
        if hi < lo:
            continue
        rows = _load_schedule_rows(source.path)
        rows = rows[(rows["date"] >= lo) & (rows["date"] <= hi)]
        shift_map: Dict[AssignmentKey, str] = {}
        for _, row in rows.iterrows():
            key = (row["date"], row["worker"])
            shift_map[key] = row["shift"]
        num_days = (hi - lo).days + 1
        for day_offset in range(num_days):
            d = lo + timedelta(days=day_offset)
            for worker in worker_ids:
                key = (d, worker)
                shift = shift_map.get(key, "OFF")
                candidates += 1
                if key in assignments:
                    continue
                assignments[key] = SourceAssignment(shift=shift, source_path=source.path)
                selected_counts[source.path.name] = (
                    selected_counts.get(source.path.name, 0) + 1
                )
    return assignments, candidates, selected_counts


def _apply_lock_assignments(model, assignments: Dict[AssignmentKey, SourceAssignment]) -> tuple[int, int]:
    """Internal helper for `_apply_lock_assignments`."""
    applied = 0
    invalid = 0

    for (day, worker), assignment in assignments.items():
        if assignment.shift == "OFF":
            codes = model._shift_codes_by_worker_day.get((worker, day), [])
            vars_for_day = [model.x[worker, day, code] for code in codes]
            if vars_for_day:
                model.model.Add(sum(vars_for_day) == 0)
            applied += 1
            continue

        var = model.x.get((worker, day, assignment.shift))
        if var is None:
            invalid += 1
            continue
        model.model.Add(var == 1)
        applied += 1

    return applied, invalid


def _apply_hint_assignments(
    model,
    assignments: Dict[AssignmentKey, SourceAssignment],
    lock_assignments: Dict[AssignmentKey, SourceAssignment],
) -> tuple[int, int, int]:
    """Internal helper for `_apply_hint_assignments`."""
    applied = 0
    skipped_locked = 0
    skipped_invalid = 0

    for (day, worker), assignment in assignments.items():
        if (day, worker) in lock_assignments:
            skipped_locked += 1
            continue
        codes = model._shift_codes_by_worker_day.get((worker, day), [])
        if assignment.shift == "OFF":
            if not codes:
                skipped_invalid += 1
                continue
            for code in codes:
                model.model.AddHint(model.x[worker, day, code], 0)
            applied += 1
            continue

        var = model.x.get((worker, day, assignment.shift))
        if var is None:
            skipped_invalid += 1
            continue
        model.model.AddHint(var, 1)
        for code in codes:
            if code == assignment.shift:
                continue
            model.model.AddHint(model.x[worker, day, code], 0)
        applied += 1

    return applied, skipped_locked, skipped_invalid


def apply_memory(
    *,
    model,
    memory_config: dict | None,
    report_start: date,
    report_end: date,
    out_dir: str,
    scenario_base_dir: str,
    memory_config_path: str | None = None,
) -> MemoryApplyResult:
    """Execute `apply_memory`."""
    cfg = _normalize_memory_config(memory_config)
    result = MemoryApplyResult()

    if not cfg:
        return result

    global_enabled = bool(cfg.get("enabled", True))
    hints_cfg = cfg.get("hints", {}) or {}
    locks_cfg = cfg.get("locks", {}) or {}
    result.hints_enabled = global_enabled and bool(hints_cfg.get("enabled", False))
    result.locks_enabled = global_enabled and bool(locks_cfg.get("enabled", False))

    scenario_base = Path(scenario_base_dir).resolve()
    memory_path = Path(memory_config_path).resolve() if memory_config_path else None

    lock_assignments: Dict[AssignmentKey, SourceAssignment] = {}
    if result.locks_enabled:
        raw_files = locks_cfg.get("files", []) or []
        lock_paths = []
        for item in raw_files:
            raw_path = item["path"] if isinstance(item, dict) else str(item)
            path = _resolve_path(
                raw_path,
                scenario_base_dir=scenario_base,
                memory_config_path=memory_path,
            )
            if not path.exists():
                raise FileNotFoundError(f"Hard lock file not found: {path}")
            lock_paths.append(path)
        result.lock_source_files = len(lock_paths)
        lock_assignments, result.lock_candidates = _collect_lock_assignments(
            lock_paths=lock_paths,
            report_start=report_start,
            report_end=report_end,
        )
        result.locks_applied, result.lock_invalid = _apply_lock_assignments(
            model, lock_assignments
        )

    if result.hints_enabled:
        out_path = Path(out_dir).resolve()
        ranked = _rank_hint_sources(
            out_dir=out_path,
            report_start=report_start,
            report_end=report_end,
        )
        result.hint_source_files = len(ranked)
        result.hint_source_order = [item.path.name for item in ranked]
        (
            hint_assignments,
            result.hint_candidates,
            selected_counts,
        ) = _collect_hint_assignments(
            ranked_sources=ranked,
            report_start=report_start,
            report_end=report_end,
            worker_ids=list(getattr(model, "worker_ids", [])),
        )
        result.hint_selected_counts = selected_counts
        (
            result.hints_applied,
            result.hints_skipped_locked,
            result.hints_skipped_invalid,
        ) = _apply_hint_assignments(model, hint_assignments, lock_assignments)

    return result
