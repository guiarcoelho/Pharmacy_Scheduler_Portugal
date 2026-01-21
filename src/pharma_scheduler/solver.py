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

from .calendar import Calendar
from .shifts import ShiftManager
from .model import SchedulingModel


class SchedulingSolver:
    """Solver for pharmacy scheduling problem."""

    def __init__(self, scheduling_model: SchedulingModel, config: Dict):
        """Initialize solver.

        Args:
            scheduling_model: Built scheduling model
            config: Solver configuration
        """
        self.scheduling_model = scheduling_model
        self.config = config
        self.solver = cp_model.CpSolver()

        # Configure solver
        solver_config = config.get('solver', {})
        self.solver.parameters.max_time_in_seconds = solver_config.get(
            'time_limit_seconds', 300)
        self.solver.parameters.num_search_workers = solver_config.get(
            'num_search_workers', 8)
        self.solver.parameters.log_search_progress = solver_config.get(
            'log_search_progress', True)

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
                    'day_type': calendar.get_day_type(d).value,
                    'paid_minutes': shift.paid_minutes,
                    'is_saturday': calendar.is_saturday(d),
                    'is_sunday': calendar.is_sunday(d),
                    'is_holiday': calendar.is_holiday(d),
                    'is_weekend': calendar.is_weekend(d),
                    'in_report_range': calendar.is_in_report_range(d)
                })

        self.solution = pd.DataFrame(assignments)

        # Calculate statistics
        self._calculate_statistics()

    def _calculate_statistics(self):
        """Calculate per-worker statistics."""
        if self.solution is None or len(self.solution) == 0:
            self.stats = pd.DataFrame()
            return

        model = self.scheduling_model
        calendar = model.calendar
        workers = model.workers

        stats_list = []

        for w in workers:
            worker_schedule = self.solution[self.solution['worker'] == w]

            # Filter to report range only
            report_schedule = worker_schedule[worker_schedule['in_report_range']]

            # Basic metrics
            total_minutes = report_schedule['paid_minutes'].sum()
            weekend_minutes = report_schedule[report_schedule['is_weekend']]['paid_minutes'].sum(
            )
            sat_minutes = report_schedule[report_schedule['is_saturday']]['paid_minutes'].sum(
            )
            sun_minutes = report_schedule[report_schedule['is_sunday']]['paid_minutes'].sum(
            )
            holiday_minutes = report_schedule[report_schedule['is_holiday']]['paid_minutes'].sum(
            )

            # Sundays worked
            sundays_worked = len(report_schedule[report_schedule['is_sunday']])

            # Days worked in report range
            days_worked = len(report_schedule['date'].unique())
            total_days_in_report = len(calendar.get_report_dates())
            days_off = total_days_in_report - days_worked

            # Shift counts - include all shifts defined in shift_manager
            shift_counts = {s_code: 0 for s_code in model.shift_manager.shifts_by_code.keys()}
            counts = report_schedule['shift'].value_counts().to_dict()
            shift_counts.update(counts)

            # Weekday minutes by week
            weeks = calendar.get_all_weeks()
            weekday_by_week = {}
            excess_by_week = {}

            for week in weeks:
                week_days = calendar.get_days_in_week(week)
                weekdays = [d for d in week_days if d.weekday() < 5]
                week_schedule = report_schedule[report_schedule['date'].isin(
                    weekdays)]
                weekday_min = week_schedule['paid_minutes'].sum()
                weekday_by_week[str(week)] = weekday_min
                excess_by_week[str(week)] = max(0, weekday_min - 2400)

            # Full weekends off
            weekend_pairs = calendar.get_weekend_pairs()
            full_weekends_off = 0
            for (sat, sun) in weekend_pairs:
                if calendar.is_in_report_range(sat) and calendar.is_in_report_range(sun):
                    sat_worked = len(
                        report_schedule[report_schedule['date'] == sat]) > 0
                    sun_worked = len(
                        report_schedule[report_schedule['date'] == sun]) > 0
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
                'total_excess_40h': sum(excess_by_week.values()),
                **{f'shift_{k}': v for k, v in shift_counts.items()}
            })

        self.stats = pd.DataFrame(stats_list)

    def _print_infeasibility_hints(self):
        """Print hints for debugging infeasibility."""
        print("\nInfeasibility debugging hints:")
        print("1. Check service week alignment with date range")
        print("2. Verify enough eligible workers for each shift")
        print("3. Review Sunday compensation constraints (may need more buffer days)")
        print("4. Check daily rest constraints (especially TS/TSW transitions)")
        print("5. Use 'pharma-schedule check' to validate configuration")

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
