"""Command-line interface for pharmacy scheduler.

Commands:
- solve: Generate schedule
- check: Validate configuration
- explain: Explain schedule for specific date
"""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
import yaml

from .calendar import Calendar
from .shifts import ShiftManager
from .model import SchedulingModel
from .solver import SchedulingSolver
from .export import Exporter


def load_config(config_path: str) -> dict:
    """Load and merge configuration files.

    Args:
        config_path: Path to instance.yaml

    Returns:
        Merged configuration dict
    """
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_file) as f:
        instance_config = yaml.safe_load(f)

    # Load shifts.yaml from same directory
    shifts_file = config_file.parent / 'shifts.yaml'
    if not shifts_file.exists():
        raise FileNotFoundError(f"Shifts file not found: {shifts_file}")

    with open(shifts_file) as f:
        shifts_config = yaml.safe_load(f)

    # Merge configs
    config = {
        **instance_config,
        'shifts': shifts_config['shifts']
    }

    return config


def cmd_solve(args):
    """Execute solve command."""
    print("="*60)
    print("PHARMACY SCHEDULER - SOLVE")
    print("="*60)

    # Load configuration
    print(f"\nLoading configuration from {args.config}...")
    config = load_config(args.config)

    # Parse dates
    report_start = datetime.fromisoformat(config['report_start']).date()
    report_end = datetime.fromisoformat(config['report_end']).date()
    buffer_days = config.get('buffer_days', 14)
    anchor_monday = datetime.fromisoformat(
        config['service_cycle']['anchor_monday']).date()

    # Build calendar
    print("Building calendar...")
    calendar = Calendar(
        report_start=report_start,
        report_end=report_end,
        buffer_days=buffer_days,
        anchor_monday=anchor_monday,
        cycle_weeks=config['service_cycle']['cycle_weeks'],
        service_week_in_cycle=config['service_cycle']['service_week_in_cycle'],
        locale=config.get('locale', 'PT')
    )
    print(f"  {calendar}")

    # Build shift manager
    print("Loading shifts...")
    shift_manager = ShiftManager(
        shifts_config=config['shifts'],
        demand_config=config['demand']
    )
    print(f"  {shift_manager}")

    # Extract workers
    workers = [w['id'] for w in config['workers']]
    core_workers = [w['id']
                    for w in config['workers'] if 'core' in w.get('groups', [])]

    print(f"Workers: {', '.join(workers)}")
    print(f"Core workers: {', '.join(core_workers)}")

    # Build model
    print("\nBuilding CP-SAT model...")
    model = SchedulingModel(
        calendar=calendar,
        shift_manager=shift_manager,
        workers=workers,
        core_workers=core_workers,
        config=config
    )
    model.build()

    # Solve
    solver = SchedulingSolver(model, config)
    success = solver.solve()

    if not success:
        print("\n✗ Failed to find feasible solution")
        return 1

    # Export results
    solution = solver.get_solution()
    stats = solver.get_statistics()
    objective = solver.get_objective_value()

    exporter = Exporter(args.out)
    exporter.export_csv(solution, stats)

    if args.excel:
        exporter.export_excel(solution, stats)

    if args.verbose:
        exporter.print_schedule_by_date(solution)

    exporter.print_summary(solution, stats, objective)

    print(f"\n✓ Schedule generation complete!")
    return 0


def cmd_check(args):
    """Execute check command."""
    print("="*60)
    print("PHARMACY SCHEDULER - CHECK CONFIGURATION")
    print("="*60)

    try:
        print(f"\nLoading configuration from {args.config}...")
        config = load_config(args.config)
        print("✓ Configuration files loaded successfully")

        # Validate dates
        report_start = datetime.fromisoformat(config['report_start']).date()
        report_end = datetime.fromisoformat(config['report_end']).date()
        anchor_monday = datetime.fromisoformat(
            config['service_cycle']['anchor_monday']).date()

        print(f"\n✓ Report period: {report_start} to {report_end}")
        print(f"  Duration: {(report_end - report_start).days + 1} days")

        # Check anchor is Monday
        if anchor_monday.weekday() != 0:
            print(f"✗ ERROR: Anchor date {anchor_monday} is not a Monday!")
            return 1
        print(f"✓ Service cycle anchor: {anchor_monday} (Monday)")

        # Build calendar to check service weeks
        calendar = Calendar(
            report_start=report_start,
            report_end=report_end,
            buffer_days=config.get('buffer_days', 14),
            anchor_monday=anchor_monday,
            cycle_weeks=config['service_cycle']['cycle_weeks'],
            service_week_in_cycle=config['service_cycle']['service_week_in_cycle'],
            locale=config.get('locale', 'PT')
        )

        # Count service days
        service_days = sum(1 for d in calendar.dates
                           if 'SERVICE' in calendar.get_day_type(d).value.upper())
        print(f"✓ Service days in solve range: {service_days}")

        # Check workers
        workers = [w['id'] for w in config['workers']]
        core_workers = [w['id']
                        for w in config['workers'] if 'core' in w.get('groups', [])]
        night_capable = [w['id'] for w in config['workers']
                         if 'night_capable' in w.get('groups', [])]

        print(f"\n✓ Workers configured: {len(workers)}")
        print(f"  Core: {', '.join(core_workers)}")
        print(f"  Night-capable: {', '.join(night_capable)}")

        if len(night_capable) == 0:
            print("  ⚠ WARNING: No night-capable workers (NS/NSW will be uncovered)")

        # Check shifts
        shift_manager = ShiftManager(config['shifts'], config['demand'])
        print(f"\n✓ Shifts configured: {len(shift_manager.shifts)}")

        # Check forbidden transitions
        forbidden = shift_manager.get_forbidden_transitions(
            config['constraints']['min_daily_rest_hours']
        )
        print(f"✓ Forbidden transitions (11h rest): {len(forbidden)}")

        print("\n" + "="*60)
        print("✓ Configuration is valid!")
        print("="*60)

        return 0

    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


def cmd_explain(args):
    """Execute explain command."""
    print("="*60)
    print(f"PHARMACY SCHEDULER - EXPLAIN {args.date}")
    print("="*60)

    try:
        target_date = date.fromisoformat(args.date)
        
        # Load schedule from CSV
        schedule_file = Path(args.out) / 'schedule.csv'
        if not schedule_file.exists():
            print(f"\n✗ Error: Schedule file not found at {schedule_file}")
            print("  Run 'solve' first with the same --out directory.")
            return 1
            
        import pandas as pd
        df = pd.read_csv(schedule_file)
        df['date'] = pd.to_datetime(df['date']).dt.date
        
        # Filter for target date
        day_schedule = df[df['date'] == target_date]
        
        if day_schedule.empty:
            print(f"\nNo assignments found for {args.date} in {schedule_file}")
            return 0
            
        # Load config to get day type
        config = load_config(args.config)
        report_start = datetime.fromisoformat(config['report_start']).date()
        report_end = datetime.fromisoformat(config['report_end']).date()
        anchor_monday = datetime.fromisoformat(config['service_cycle']['anchor_monday']).date()
        
        calendar = Calendar(
            report_start=report_start,
            report_end=report_end,
            buffer_days=config.get('buffer_days', 14),
            anchor_monday=anchor_monday,
            cycle_weeks=config['service_cycle']['cycle_weeks'],
            service_week_in_cycle=config['service_cycle']['service_week_in_cycle']
        )
        
        day_type = calendar.get_day_type(target_date)
        print(f"\nDate: {target_date} ({target_date.strftime('%A')})")
        print(f"Day Type: {day_type.value}")
        print("-" * 30)
        
        print(f"{'Worker':<10} {'Shift':<10} {'Hours':<10}")
        print("-" * 30)
        
        total_hours = 0
        for _, row in day_schedule.iterrows():
            worker = row['worker']
            shift = row['shift']
            # We don't have hours in schedule.csv by default, but we could add them
            # or just show the code.
            print(f"{worker:<10} {shift:<10}")
            
        print("-" * 30)
        
        return 0

    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        return 1


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Pharmacy staff scheduling system using Google OR-Tools CP-SAT'
    )

    subparsers = parser.add_subparsers(
        dest='command', help='Command to execute')

    # Solve command
    solve_parser = subparsers.add_parser('solve', help='Generate schedule')
    solve_parser.add_argument(
        '--config', required=True, help='Path to instance.yaml')
    solve_parser.add_argument('--out', required=True, help='Output directory')
    solve_parser.add_argument(
        '--excel', action='store_true', help='Also export to Excel')
    solve_parser.add_argument(
        '--verbose', action='store_true', help='Print detailed schedule')

    # Check command
    check_parser = subparsers.add_parser(
        'check', help='Validate configuration')
    check_parser.add_argument(
        '--config', required=True, help='Path to instance.yaml')

    # Explain command
    explain_parser = subparsers.add_parser(
        'explain', help='Explain schedule for date')
    explain_parser.add_argument(
        '--config', required=True, help='Path to instance.yaml')
    explain_parser.add_argument(
        '--date', required=True, help='Date to explain (YYYY-MM-DD)')
    explain_parser.add_argument(
        '--out', required=True, help='Output directory where schedule.csv is located')

    args = parser.parse_args()

    if args.command == 'solve':
        return cmd_solve(args)
    elif args.command == 'check':
        return cmd_check(args)
    elif args.command == 'explain':
        return cmd_explain(args)
    else:
        parser.print_help()
        return 1


if __name__ == '__main__':
    sys.exit(main())
