"""Solver execution and solution extraction.

This module handles:
- CP-SAT solver configuration and execution
- Solution extraction from solver
- Statistics calculation
- Infeasibility diagnostics
"""

from datetime import date
from typing import Dict, List, Optional, Tuple
from ortools.sat.python import cp_model
import pandas as pd

from .model import SchedulingModel


class StatisticsCalculator:
    """Calculates scheduling statistics from solution."""

    def __init__(self, model: SchedulingModel):
        self.model = model
        self.calendar = model.calendar
        # `SchedulingModel.workers` is a list of worker dicts in the new config-first
        # flow. Statistics are keyed by worker ID.
        self.workers = getattr(model, "worker_ids", None) or [w["id"] for w in model.workers]

    def calculate(self, solution: pd.DataFrame) -> pd.DataFrame:
        """Calculate per-worker statistics."""
        if solution is None or len(solution) == 0:
            return pd.DataFrame()

        stats_list = []

        for w in self.workers:
            worker_schedule = solution[solution['worker'] == w]
            report_schedule = worker_schedule[worker_schedule['in_report_range']]

            # Basic metrics
            total_minutes = report_schedule['paid_minutes'].sum()
            
            # Helper to sum minutes by filter
            def sum_mins(mask): return report_schedule[mask]['paid_minutes'].sum()
            
            weekend_minutes = sum_mins(report_schedule['is_weekend'])
            sat_minutes = sum_mins(report_schedule['is_saturday'])
            sun_minutes = sum_mins(report_schedule['is_sunday'])
            holiday_minutes = sum_mins(report_schedule['is_holiday'])

            sundays_worked = len(report_schedule[report_schedule['is_sunday']])
            days_worked = len(report_schedule['date'].unique())
            days_off = len(self.calendar.get_report_dates()) - days_worked

            # Shift counts
            shift_counts = {s_code: 0 for s_code in self.model.shift_manager.shifts_by_code.keys()}
            shift_counts.update(report_schedule['shift'].value_counts().to_dict())

            # Weekday minutes and excess
            weeks = self.calendar.get_all_weeks()
            total_excess = 0
            for week in weeks:
                week_days = self.calendar.get_days_in_week(week)
                weekdays = [d for d in week_days if d.weekday() < 5]
                week_min = report_schedule[report_schedule['date'].isin(weekdays)]['paid_minutes'].sum()
                total_excess += max(0, week_min - 2400)

            # Full weekends off
            full_weekends_off = 0
            for (sat, sun) in self.calendar.get_weekend_pairs():
                # Only count weekends fully within report range
                if self.calendar.is_in_report_range(sat) and self.calendar.is_in_report_range(sun):
                    sat_worked = not report_schedule[report_schedule['date'] == sat].empty
                    sun_worked = not report_schedule[report_schedule['date'] == sun].empty
                    if not sat_worked and not sun_worked:
                        full_weekends_off += 1

            stats_list.append({
                'worker': w,
                'total_paid_minutes': total_minutes,
                'total_hours': total_minutes / 60,
                'total_shifts': days_worked,
                'days_off': days_off,
                'weekend_minutes': weekend_minutes,
                'saturday_minutes': sat_minutes,
                'sunday_minutes': sun_minutes,
                'holiday_minutes': holiday_minutes,
                'sundays_worked': sundays_worked,
                'full_weekends_off': full_weekends_off,
                'total_excess_40h': total_excess,
                **{f'shift_{k}': v for k, v in shift_counts.items()}
            })

        return pd.DataFrame(stats_list)


class SchedulingSolver:
    """Solver for scheduling problem."""

    def __init__(self, scheduling_model: SchedulingModel, solver_config: Dict):
        """Initialize solver.

        Args:
            scheduling_model: Built scheduling model
            solver_config: Solver configuration dict
        """
        self.scheduling_model = scheduling_model
        self.solver = cp_model.CpSolver()

        # Configure solver
        self.solver.parameters.max_time_in_seconds = solver_config.get(
            'time_limit_seconds', 300)
        self.solver.parameters.num_search_workers = solver_config.get(
            'num_search_workers', 8)
        self.solver.parameters.log_search_progress = solver_config.get(
            'log_search_progress', False)
        self.print_response_stats = solver_config.get('print_response_stats', False)
        random_seed = solver_config.get('random_seed')
        if random_seed is not None:
            self.solver.parameters.random_seed = int(random_seed)

        self.status = None
        self.solution = None
        self.stats = None

    def solve(self) -> bool:
        """Solve the scheduling problem.

        Returns:
            True if feasible solution found, False otherwise
        """
        print(
            f"\nSolving with time limit {self.solver.parameters.max_time_in_seconds}s...")

        model = self.scheduling_model.get_model()
        self.status = self.solver.Solve(model)
        if self.print_response_stats:
            print("\nSolver stats:")
            print(self.solver.ResponseStats())

        if self.status == cp_model.OPTIMAL:
            print(f"✓ Optimal solution found!")
            print(f"  Objective value: {self.solver.ObjectiveValue()}")
            print(f"  Solve time: {self.solver.WallTime():.2f}s")
            self._extract_solution()
            return True
        elif self.status == cp_model.FEASIBLE:
            print(f"✓ Feasible solution found (not proven optimal)")
            print(f"  Objective value: {self.solver.ObjectiveValue()}")
            print(f"  Best bound: {self.solver.BestObjectiveBound()}")
            print(f"  Solve time: {self.solver.WallTime():.2f}s")
            self._extract_solution()
            return True
        elif self.status == cp_model.INFEASIBLE:
            print(f"✗ Problem is INFEASIBLE")
            self._print_infeasibility_hints()
            return False
        else:
            print(f"✗ Solver status: {self.solver.StatusName(self.status)}")
            return False

    def _extract_solution(self):
        """Extract solution from solver."""
        model = self.scheduling_model
        calendar = model.calendar
        shift_manager = model.shift_manager

        # Extract assignments
        assignments = []
        for (w, d, s), var in model.x.items():
            if self.solver.Value(var) == 1:
                shift = shift_manager.shifts_by_code[s]
                assignments.append({
                    'date': d,
                    'worker': w,
                    'shift': s,
                    'shift_name': shift.name,
                    'day_tags': ",".join(sorted(calendar.get_special_tags(d))),
                    'paid_minutes': shift.paid_minutes,
                    'is_saturday': calendar.is_saturday(d),
                    'is_sunday': calendar.is_sunday(d),
                    'is_holiday': calendar.is_holiday(d),
                    'is_weekend': calendar.is_weekend(d),
                    'in_report_range': calendar.is_in_report_range(d)
                })

        self.solution = pd.DataFrame(assignments)

        # Calculate statistics using helper
        calculator = StatisticsCalculator(self.scheduling_model)
        self.stats = calculator.calculate(self.solution)

    def _print_infeasibility_hints(self):
        """Print hints for debugging infeasibility."""
        print("\nInfeasibility debugging hints:")
        print("1. Verify special-days tags cover required shifts")
        print("2. Verify enough eligible workers for each shift")
        print("3. Review Sunday compensation constraints (may need more buffer days)")
        print("4. Check daily rest constraints (late-to-early transitions)")
        print("5. Run `python run.py --check` to validate configuration")

    def get_solution(self) -> Optional[pd.DataFrame]:
        """Get solution DataFrame."""
        return self.solution

    def get_statistics(self) -> Optional[pd.DataFrame]:
        """Get statistics DataFrame."""
        return self.stats

    def get_objective_value(self) -> Optional[float]:
        """Get objective value if solution exists."""
        if self.status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            return self.solver.ObjectiveValue()
        return None
