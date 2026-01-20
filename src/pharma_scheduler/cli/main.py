"""CLI entrypoint."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from pharma_scheduler.cli.check import run_check
from pharma_scheduler.cli.explain import run_explain
from pharma_scheduler.io.export_csv import export_schedule_csv, export_worker_stats_csv
from pharma_scheduler.io.export_excel import export_excel
from pharma_scheduler.io.load_config import load_config_bundle
from pharma_scheduler.io.pretty_print import print_summary
from pharma_scheduler.solver.solve import solve_instance


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def app() -> None:
    parser = argparse.ArgumentParser(prog="pharma-schedule")
    subparsers = parser.add_subparsers(dest="command", required=True)

    solve_parser = subparsers.add_parser("solve", help="Solve scheduling instance")
    solve_parser.add_argument("--config", required=True, type=Path)
    solve_parser.add_argument("--out", required=True, type=Path)
    solve_parser.add_argument("--excel", action="store_true")

    check_parser = subparsers.add_parser("check", help="Check configuration")
    check_parser.add_argument("--config", required=True, type=Path)

    explain_parser = subparsers.add_parser("explain", help="Explain calendar tagging")
    explain_parser.add_argument("--config", required=True, type=Path)
    explain_parser.add_argument("--date", required=True, type=_parse_date)

    args = parser.parse_args()

    if args.command == "check":
        raise SystemExit(run_check(args.config))
    if args.command == "explain":
        raise SystemExit(run_explain(args.config, args.date))
    if args.command == "solve":
        bundle = load_config_bundle(args.config)
        result = solve_instance(bundle)
        print_summary(result.status, result.objective_value, result.schedule)
        if result.status not in {"OPTIMAL", "FEASIBLE"}:
            raise SystemExit(1)

        args.out.mkdir(parents=True, exist_ok=True)
        export_schedule_csv(args.out / "schedule.csv", result.schedule)
        export_worker_stats_csv(args.out / "worker_stats.csv", result.worker_stats)
        if args.excel:
            export_excel(args.out / "schedule.xlsx", result.schedule, result.worker_stats)
        raise SystemExit(0)

    raise SystemExit(2)
