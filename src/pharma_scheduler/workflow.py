"""High-level workflow helpers for generating schedules.

This module is intentionally CLI-agnostic so it can be used by `run.py`,
notebooks, or other Python entrypoints.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from .calendar import Calendar
from .export import Exporter
from .model import SchedulingModel
from .scenario_loader import load_scenario
from .shifts import ShiftManager
from .solver import SchedulingSolver
from .special_vacation_days import (
    apply_worker_vacations,
    build_special_tag_index,
    load_special_days_data,
)


def load_config(config_path: str) -> dict:
    """Load scenario configuration (scenario.yaml)."""
    return load_scenario(config_path)


def check_configuration(config_path: str) -> int:
    """Validate configuration files and print a short report."""
    print("=" * 60)
    print("PHARMACY SCHEDULER - CHECK CONFIGURATION")
    print("=" * 60)

    try:
        print(f"\nLoading configuration from {config_path}...")
        config = load_config(config_path)
        print("✓ Scenario files loaded successfully")

        calendar_cfg = config["calendar"].get("calendar", config["calendar"])
        report_start = datetime.fromisoformat(calendar_cfg["report_start"]).date()
        report_end = datetime.fromisoformat(calendar_cfg["report_end"]).date()
        buffer_days = calendar_cfg.get("buffer_days", 14)
        locale = calendar_cfg.get("holiday_locale", "PT")

        print(f"\n✓ Report period: {report_start} to {report_end}")
        print(f"  Duration: {(report_end - report_start).days + 1} days")

        special_days = load_special_days_data(config.get("special_days", {}))
        all_dates = [
            report_start + timedelta(days=i)
            for i in range((report_end - report_start).days + 1 + buffer_days)
        ]
        calendar = Calendar(
            report_start=report_start,
            report_end=report_end,
            buffer_days=buffer_days,
            locale=locale,
            special_tags_by_date=build_special_tag_index(
                dates=all_dates, specials=special_days
            ),
        )

        worker_defs = config["workers"].get("workers", [])
        warnings = apply_worker_vacations(
            workers=worker_defs,
            solve_dates=calendar.dates,
        )

        workers = [w["id"] for w in worker_defs]
        core_workers = [
            w["id"]
            for w in worker_defs
            if "core" in w.get("groups", [])
        ]
        night_capable = [
            w["id"]
            for w in worker_defs
            if "night_capable" in w.get("caps", [])
        ]

        print(f"\n✓ Workers configured: {len(workers)}")
        print(f"  Core: {', '.join(core_workers)}")
        print(f"  Night-capable: {', '.join(night_capable)}")

        if len(night_capable) == 0:
            print("  ⚠ WARNING: No night-capable workers (NS/NSW will be uncovered)")
        if warnings:
            print("\n⚠ Vacation warnings:")
            for warning in warnings:
                print(f"  - {warning}")

        shift_manager = ShiftManager(config["shifts"]["shifts"])
        print(f"\n✓ Shifts configured: {len(shift_manager.shifts)}")

        print("\n" + "=" * 60)
        print("✓ Configuration is valid!")
        print("=" * 60)
        return 0

    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback

        traceback.print_exc()
        return 1


def solve(
    *,
    config_path: str,
    out_dir: str,
    excel: bool = True,
    verbose: bool = False,
) -> int:
    """Generate a schedule and export results."""
    print("=" * 60)
    print("PHARMACY SCHEDULER - SOLVE")
    print("=" * 60)

    print(f"\nLoading configuration from {config_path}...")
    config = load_config(config_path)
    calendar_cfg = config["calendar"].get("calendar", config["calendar"])

    report_start = datetime.fromisoformat(calendar_cfg["report_start"]).date()
    report_end = datetime.fromisoformat(calendar_cfg["report_end"]).date()
    buffer_days = calendar_cfg.get("buffer_days", 14)
    locale = calendar_cfg.get("holiday_locale", "PT")

    print("Building calendar...")
    special_days = load_special_days_data(config.get("special_days", {}))
    special_tags = build_special_tag_index(
        dates=[report_start + timedelta(days=i) for i in range((report_end - report_start).days + 1 + buffer_days)],
        specials=special_days,
    )
    calendar = Calendar(
        report_start=report_start,
        report_end=report_end,
        buffer_days=buffer_days,
        locale=locale,
        special_tags_by_date=special_tags,
    )
    print(f"  {calendar}")

    print("Loading shifts...")
    shift_manager = ShiftManager(shifts_config=config["shifts"]["shifts"])
    print(f"  {shift_manager}")

    workers = config["workers"].get("workers", [])
    warnings = apply_worker_vacations(
        workers=workers,
        solve_dates=calendar.dates,
    )
    worker_ids = [w["id"] for w in workers]
    core_workers = [w["id"] for w in workers if "core" in w.get("groups", [])]

    print(f"Workers: {', '.join(worker_ids)}")
    print(f"Core workers: {', '.join(core_workers)}")
    if warnings:
        print("\n⚠ Vacation warnings:")
        for warning in warnings:
            print(f"  - {warning}")

    print("\nBuilding CP-SAT model...")
    model = SchedulingModel(
        calendar=calendar,
        shift_manager=shift_manager,
        workers=workers,
        rulebook=config["constraints"],
    )
    model.build()

    solver = SchedulingSolver(model, config.get("solver", {}).get("solver", {}))
    success = solver.solve()
    if not success:
        print("\n✗ Failed to find feasible solution")
        return 1

    solution = solver.get_solution()
    stats = solver.get_statistics()
    objective = solver.get_objective_value()

    exporter = Exporter(out_dir)
    exporter.export_csv(solution, stats)

    if excel:
        exporter.export_excel(solution, stats)

    if verbose:
        exporter.print_schedule_by_date(solution)

    exporter.print_summary(solution, stats, objective)

    print("\n✓ Schedule generation complete!")
    return 0


def explain(*, config_path: str, out_dir: str, target_date: str) -> int:
    """Explain schedule for a specific date based on exported CSV."""
    print("=" * 60)
    print(f"PHARMACY SCHEDULER - EXPLAIN {target_date}")
    print("=" * 60)

    try:
        day = date.fromisoformat(target_date)

        schedule_file = Path(out_dir) / "schedule.csv"
        if not schedule_file.exists():
            print(f"\n✗ Error: Schedule file not found at {schedule_file}")
            print("  Run `python run.py` first (or generate a schedule into the same --out).")
            return 1

        import pandas as pd

        df = pd.read_csv(schedule_file)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        day_schedule = df[df["date"] == day]

        if day_schedule.empty:
            print(f"\nNo assignments found for {target_date} in {schedule_file}")
            return 0

        config = load_config(config_path)
        calendar_cfg = config["calendar"].get("calendar", config["calendar"])
        report_start = datetime.fromisoformat(calendar_cfg["report_start"]).date()
        report_end = datetime.fromisoformat(calendar_cfg["report_end"]).date()
        buffer_days = calendar_cfg.get("buffer_days", 14)
        locale = calendar_cfg.get("holiday_locale", "PT")
        special_days = load_special_days_data(config.get("special_days", {}))
        special_tags = build_special_tag_index(
            dates=[report_start + timedelta(days=i) for i in range((report_end - report_start).days + 1 + buffer_days)],
            specials=special_days,
        )

        calendar = Calendar(
            report_start=report_start,
            report_end=report_end,
            buffer_days=buffer_days,
            locale=locale,
            special_tags_by_date=special_tags,
        )
        print(f"\nDate: {day} ({day.strftime('%A')})")
        print(f"Special Tags: {', '.join(sorted(calendar.get_special_tags(day)))}")
        print("-" * 30)
        print(f"{'Worker':<10} {'Shift':<10}")
        print("-" * 30)

        for _, row in day_schedule.iterrows():
            print(f"{row['worker']:<10} {row['shift']:<10}")

        print("-" * 30)
        return 0

    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        return 1
