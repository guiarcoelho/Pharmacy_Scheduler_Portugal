#!/usr/bin/env python3
"""
Unified Run Script for Pharmacy Scheduler
-----------------------------------------
This script performs the standard workflow:
1. Validates the project configuration.
2. Generates the optimal schedule.
3. Exports results to CSV.
"""

import argparse
import sys
from pathlib import Path

# Add src to python path to allow running without installation
sys.path.append(str(Path(__file__).parent / "src"))


def _import_workflow():
    """Internal helper for `_import_workflow`."""
    try:
        from pharma_scheduler.workflow import check_configuration, explain, solve
    except ImportError as e:
        print(f"Error: Could not import project modules. {e}")
        print(
            "Ensure you are running this from the project root and dependencies are installed."
        )
        return None
    return check_configuration, explain, solve


def parse_args() -> argparse.Namespace:
    """Execute `parse_args`."""
    parser = argparse.ArgumentParser(
        description="Generate pharmacy schedules (recommended entrypoint: python run.py)"
    )

    parser.add_argument(
        "--config",
        default="config/scenario.yaml",
        help="Path to scenario.yaml (default: config/scenario.yaml)",
    )
    parser.add_argument(
        "--out",
        default="out",
        help="Output directory for CSV exports (default: out/)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print schedule by date to the console",
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="Validate configuration and exit",
    )
    mode.add_argument(
        "--explain",
        metavar="YYYY-MM-DD",
        help="Explain schedule for a specific date (reads schedule_<start>_<end>.csv from --out)",
    )

    return parser.parse_args()


def main() -> int:
    """Run the command-line entrypoint."""
    args = parse_args()
    workflow = _import_workflow()
    if workflow is None:
        return 1

    check_configuration, explain, solve = workflow

    if args.check:
        return check_configuration(args.config)

    if args.explain:
        return explain(config_path=args.config, out_dir=args.out, target_date=args.explain)

    print("🚀 Starting Pharmacy Scheduler Workflow...")

    print("\n[1/2] Validating configuration...")
    if check_configuration(args.config) != 0:
        print("❌ Configuration validation failed. Please fix the issues above.")
        return 1

    print("\n[2/2] Generating optimal schedule...")
    rc = solve(
        config_path=args.config,
        out_dir=args.out,
        verbose=args.verbose,
    )
    if rc != 0:
        print("❌ Scheduling failed. See errors above.")
        return rc

    print("\n" + "=" * 78)
    print("✅ WORKFLOW COMPLETE")
    print("=" * 78)
    print(f"Schedule files: {args.out}/schedule_*.csv")
    print(f"Worker stats files: {args.out}/worker_stats_*.csv")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
