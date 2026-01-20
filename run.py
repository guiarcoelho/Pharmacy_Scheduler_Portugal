#!/usr/bin/env python3
"""
Unified Run Script for Pharmacy Scheduler
-----------------------------------------
This script performs the standard workflow:
1. Validates the project configuration.
2. Generates the optimal schedule.
3. Exports results to CSV and Excel.
"""

import sys
import os
from pathlib import Path

# Add src to python path to allow running without installation
sys.path.append(str(Path(__file__).parent / "src"))

try:
    from pharma_scheduler.cli import cmd_solve, cmd_check
    from argparse import Namespace
except ImportError as e:
    print(f"Error: Could not import project modules. {e}")
    print("Ensure you are running this from the project root and dependencies are installed.")
    sys.exit(1)

def main():
    print("🚀 Starting Pharmacy Scheduler Workflow...")
    
    # Define standard paths
    config_path = "config/instance.yaml"
    output_dir = "out"
    
    # 1. Check Configuration
    print("\n[1/2] Validating configuration...")
    check_args = Namespace(config=config_path)
    if cmd_check(check_args) != 0:
        print("❌ Configuration validation failed. Please fix the issues above.")
        sys.exit(1)
    
    # 2. Solve and Export
    print("\n[2/2] Generating optimal schedule...")
    solve_args = Namespace(
        config=config_path,
        out=output_dir,
        excel=True,
        verbose=False
    )
    
    if cmd_solve(solve_args) == 0:
        print("\n" + "="*60)
        print("✅ WORKFLOW COMPLETE")
        print("="*60)
        print(f"Schedule: {output_dir}/schedule.csv")
        print(f"Excel Report: {output_dir}/schedule.xlsx")
        print(f"Worker Stats: {output_dir}/worker_stats.csv")
        print("="*60)
    else:
        print("❌ Scheduling failed. See errors above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
