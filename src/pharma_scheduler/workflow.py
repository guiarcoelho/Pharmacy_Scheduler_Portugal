"""High-level workflow helpers for generating schedules.

This module is intentionally CLI-agnostic so it can be used by `run.py`,
notebooks, or other Python entrypoints.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import yaml

from .calendar import Calendar
from .config_schema import InstanceConfig
from .export import Exporter
from .model import SchedulingModel
from .shifts import ShiftManager
from .solver import SchedulingSolver


def load_config(config_path: str) -> dict:
    """Load and validate configuration, merging `instance.yaml` + `shifts.yaml`."""
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with config_file.open() as f:
        instance_config = yaml.safe_load(f)

    shifts_file = config_file.parent / "shifts.yaml"
    if not shifts_file.exists():
        raise FileNotFoundError(f"Shifts file not found: {shifts_file}")

    with shifts_file.open() as f:
        shifts_config = yaml.safe_load(f)

    config = {**instance_config, "shifts": shifts_config["shifts"]}
    validated_config = InstanceConfig.from_dict(config)
    return validated_config.to_dict()


def check_configuration(config_path: str) -> int:
    """Validate configuration files and print a short report."""
    print("=" * 60)
    print("PHARMACY SCHEDULER - CHECK CONFIGURATION")
    print("=" * 60)

    try:
        print(f"\nLoading configuration from {config_path}...")
        config = load_config(config_path)
        print("✓ Configuration files loaded successfully")

        report_start = datetime.fromisoformat(config["report_start"]).date()
        report_end = datetime.fromisoformat(config["report_end"]).date()
        anchor_monday = datetime.fromisoformat(
            config["service_cycle"]["anchor_monday"]
        ).date()

        print(f"\n✓ Report period: {report_start} to {report_end}")
        print(f"  Duration: {(report_end - report_start).days + 1} days")

        if anchor_monday.weekday() != 0:
            print(f"✗ ERROR: Anchor date {anchor_monday} is not a Monday!")
            return 1
        print(f"✓ Service cycle anchor: {anchor_monday} (Monday)")

        calendar = Calendar(
            report_start=report_start,
            report_end=report_end,
            buffer_days=config.get("buffer_days", 14),
            anchor_monday=anchor_monday,
            cycle_weeks=config["service_cycle"]["cycle_weeks"],
            service_week_in_cycle=config["service_cycle"]["service_week_in_cycle"],
            locale=config.get("locale", "PT"),
        )

        service_days = sum(
            1
            for d in calendar.dates
            if "SERVICE" in calendar.get_day_type(d).value.upper()
        )
        print(f"✓ Service days in solve range: {service_days}")

        workers = [w["id"] for w in config["workers"]]
        core_workers = [
            w["id"] for w in config["workers"] if "core" in w.get("groups", [])
        ]
        night_capable = [
            w["id"]
            for w in config["workers"]
            if "night_capable" in w.get("groups", [])
        ]

        print(f"\n✓ Workers configured: {len(workers)}")
        print(f"  Core: {', '.join(core_workers)}")
        print(f"  Night-capable: {', '.join(night_capable)}")

        if len(night_capable) == 0:
            print("  ⚠ WARNING: No night-capable workers (NS/NSW will be uncovered)")

        shift_manager = ShiftManager(config["shifts"], config["demand"])
        print(f"\n✓ Shifts configured: {len(shift_manager.shifts)}")

        forbidden = shift_manager.get_forbidden_transitions(
            config["constraints"]["min_daily_rest_hours"]
        )
        print(f"✓ Forbidden transitions (11h rest): {len(forbidden)}")

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

    report_start = datetime.fromisoformat(config["report_start"]).date()
    report_end = datetime.fromisoformat(config["report_end"]).date()
    buffer_days = config.get("buffer_days", 14)
    anchor_monday = datetime.fromisoformat(config["service_cycle"]["anchor_monday"]).date()

    print("Building calendar...")
    calendar = Calendar(
        report_start=report_start,
        report_end=report_end,
        buffer_days=buffer_days,
        anchor_monday=anchor_monday,
        cycle_weeks=config["service_cycle"]["cycle_weeks"],
        service_week_in_cycle=config["service_cycle"]["service_week_in_cycle"],
        locale=config.get("locale", "PT"),
    )
    print(f"  {calendar}")

    print("Loading shifts...")
    shift_manager = ShiftManager(shifts_config=config["shifts"], demand_config=config["demand"])
    print(f"  {shift_manager}")

    workers = [w["id"] for w in config["workers"]]
    core_workers = [w["id"] for w in config["workers"] if "core" in w.get("groups", [])]

    print(f"Workers: {', '.join(workers)}")
    print(f"Core workers: {', '.join(core_workers)}")

    print("\nBuilding CP-SAT model...")
    model = SchedulingModel(
        calendar=calendar,
        shift_manager=shift_manager,
        workers=workers,
        core_workers=core_workers,
        config=config,
    )
    model.build()

    solver = SchedulingSolver(model, config)
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
        report_start = datetime.fromisoformat(config["report_start"]).date()
        report_end = datetime.fromisoformat(config["report_end"]).date()
        anchor_monday = datetime.fromisoformat(config["service_cycle"]["anchor_monday"]).date()

        calendar = Calendar(
            report_start=report_start,
            report_end=report_end,
            buffer_days=config.get("buffer_days", 14),
            anchor_monday=anchor_monday,
            cycle_weeks=config["service_cycle"]["cycle_weeks"],
            service_week_in_cycle=config["service_cycle"]["service_week_in_cycle"],
            locale=config.get("locale", "PT"),
        )

        day_type = calendar.get_day_type(day)
        print(f"\nDate: {day} ({day.strftime('%A')})")
        print(f"Day Type: {day_type.value}")
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

