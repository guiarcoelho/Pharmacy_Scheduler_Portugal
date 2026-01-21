"""CP-SAT model for pharmacy scheduling.

This module contains:
- Variable creation (assignments, work indicators, metrics)
- All hard constraints (coverage, eligibility, rest, coupling, compensation)
- Soft constraints (weekly rest, fairness)
- Objective function construction
"""

from datetime import date, timedelta
from typing import Dict, List, Tuple
from ortools.sat.python import cp_model

from .calendar import Calendar, DayType
from .shifts import ShiftManager


class SchedulingModel:
    """CP-SAT model for pharmacy staff scheduling."""

    def __init__(
        self,
        calendar: Calendar,
        shift_manager: ShiftManager,
        workers: List[str],
        core_workers: List[str],
        config: Dict
    ):
        """Initialize scheduling model.

        Args:
            calendar: Calendar with dates and day types
            shift_manager: Shift manager with shifts and demand
            workers: All worker IDs
            core_workers: Core worker IDs (A-E)
            config: Configuration dict with constraints and objective weights
        """
        self.calendar = calendar
        self.shift_manager = shift_manager
        self.workers = workers
        self.core_workers = core_workers
        self.config = config

        self.model = cp_model.CpModel()

        # Variables (created in build())
        self.x = {}  # x[w, d, s]: worker w assigned to shift s on day d
        self.works = {}  # works[w, d]: worker w works on day d
        # paid_minutes[w, d]: paid minutes for worker w on day d
        self.paid_minutes = {}

        # Aggregated metrics
        self.weekend_minutes = {}
        self.sat_minutes = {}
        self.sun_minutes = {}
        self.holiday_minutes = {}
        self.weekday_minutes = {}  # weekday_minutes[w, week]
        self.excess40 = {}  # excess40[w, week]
        self.shift_counts = {}  # shift_counts[w, shift_code]

        # Soft constraint variables
        self.no_day_off = {}  # no_day_off[w, week]
        self.sunday_violations = {}  # (w, sunday_date) -> list of BoolVars
        self.low_m_vars = []  # list of BoolVars for shift M
        self.low_i_vars = []  # list of BoolVars for shift I
        self.sunday_comp_delayed_vars = []  # list of BoolVars for delayed comp
        self.flexible_coverage_violations = []  # list of (penalty, BoolVar)
        self.fairness_diffs = {}  # fairness_diffs[metric, w]

    def build(self):
        """Build complete CP-SAT model."""
        print("Creating variables...")
        self._create_variables()

        print("Adding hard constraints...")
        self._add_coverage_constraints()
        self._add_rest_constraints()
        self._add_weekend_coupling()
        self._add_sunday_compensation()

        print("Adding soft constraints...")
        self._add_weekly_rest_soft()
        self._add_fairness_constraints()

        print("Building objective...")
        self._build_objective()

        print(f"Model built: {self.model.ModelStats()}")

    # ========================================
    # VARIABLE CREATION
    # ========================================

    def _create_variables(self):
        """Create all CP-SAT variables."""
        # Primary assignment variables
        for w in self.workers:
            for d in self.calendar.dates:
                day_type = self.calendar.get_day_type(d)
                allowed_shifts = self.shift_manager.get_allowed_shifts(
                    day_type)
                is_sat = self.calendar.is_saturday(d)
                is_sun = self.calendar.is_sunday(d)

                for shift in allowed_shifts:
                    if self.shift_manager.is_eligible(w, shift.code, day_type, is_sat, is_sun):
                        self.x[w, d, shift.code] = self.model.NewBoolVar(
                            f'x_{w}_{d}_{shift.code}'
                        )

        # Works indicator: at most one shift per day
        for w in self.workers:
            for d in self.calendar.dates:
                shifts_on_day = [s for (worker, day, s) in self.x.keys()
                                 if worker == w and day == d]
                if shifts_on_day:
                    self.works[w, d] = self.model.NewBoolVar(f'works_{w}_{d}')
                    self.model.Add(
                        sum(self.x[w, d, s] for s in shifts_on_day) == self.works[w, d])
                else:
                    # No eligible shifts this day
                    self.works[w, d] = 0

        # Paid minutes by worker-day
        for w in self.workers:
            for d in self.calendar.dates:
                shifts_on_day = [(s, self.shift_manager.shifts_by_code[s].paid_minutes)
                                 for (worker, day, s) in self.x.keys()
                                 if worker == w and day == d]
                if shifts_on_day:
                    self.paid_minutes[w, d] = sum(
                        self.x[w, d, s] * minutes for s, minutes in shifts_on_day
                    )
                else:
                    self.paid_minutes[w, d] = 0

        # Aggregated metrics
        self._create_aggregated_metrics()

    def _create_aggregated_metrics(self):
        """Create aggregated metric variables."""
        # Weekend/holiday minutes
        for w in self.workers:
            sat_days = [
                d for d in self.calendar.dates if self.calendar.is_saturday(d)]
            sun_days = [
                d for d in self.calendar.dates if self.calendar.is_sunday(d)]
            holiday_days = [
                d for d in self.calendar.dates if self.calendar.is_holiday(d)]

            self.sat_minutes[w] = sum(
                self.paid_minutes.get((w, d), 0) for d in sat_days)
            self.sun_minutes[w] = sum(
                self.paid_minutes.get((w, d), 0) for d in sun_days)
            self.holiday_minutes[w] = sum(
                self.paid_minutes.get((w, d), 0) for d in holiday_days)
            self.weekend_minutes[w] = self.sat_minutes[w] + self.sun_minutes[w]

        # Weekday minutes and excess over 40h per week
        weeks = self.calendar.get_all_weeks()
        for w in self.core_workers:
            for week in weeks:
                weekdays = [d for d in self.calendar.get_days_in_week(week)
                            if d.weekday() < 5]  # Mon-Fri

                self.weekday_minutes[w, week] = sum(
                    self.paid_minutes.get((w, d), 0) for d in weekdays
                )

                # Excess over 40h (2400 minutes)
                excess_var = self.model.NewIntVar(
                    0, 10000, f'excess40_{w}_{week}')
                self.model.Add(
                    excess_var >= self.weekday_minutes[w, week] - 2400)
                self.model.Add(excess_var >= 0)
                self.excess40[w, week] = excess_var

        # Shift counts
        for w in self.workers:
            for shift in self.shift_manager.shifts:
                count = sum(self.x.get((w, d, shift.code), 0)
                            for d in self.calendar.dates)
                self.shift_counts[w, shift.code] = count

    # ========================================
    # HARD CONSTRAINTS
    # ========================================

    def _add_coverage_constraints(self):
        """Add exact coverage demand constraints."""
        for d in self.calendar.dates:
            day_type = self.calendar.get_day_type(d)
            demand = self.shift_manager.get_demand(day_type)
            is_sat = self.calendar.is_saturday(d)
            is_sun = self.calendar.is_sunday(d)
            is_service_weekend = (day_type == DayType.SERVICE_WEEKEND_OR_HOLIDAY and
                                  (is_sat or is_sun))

            for shift_code, count in demand.items():
                total = sum(self.x.get((w, d, shift_code), 0)
                            for w in self.workers)
                
                # Check for custom rules in instance.yaml
                rules = self.config.get('demand_rules', {}).get(shift_code)
                
                if rules and day_type == DayType.NORMAL_WEEKDAY:
                    self._apply_demand_rules(d, shift_code, total, count, rules)
                else:
                    self._apply_standard_coverage(total, count)

            # Worker F must work service weekend days
            if is_service_weekend:
                self._apply_service_weekend_rules(d)

    def _apply_demand_rules(self, d, shift_code, total, count, rules):
        """Apply configurable demand rules (hard min, soft targets)."""
        hard_min = rules.get('hard_min', count)
        penalty = rules.get('penalty', 0)
        
        # Hard constraints
        self.model.Add(total >= hard_min)
        self.model.Add(total <= count)
        
        # Soft target (with penalty if total < count)
        if penalty > 0 and count > hard_min:
            # violation = 1 if total < count
            violation = self.model.NewBoolVar(f'low_coverage_{shift_code}_{d}')
            
            self.model.Add(total == count).OnlyEnforceIf(violation.Not())
            self.model.Add(total < count).OnlyEnforceIf(violation)
            
            self.flexible_coverage_violations.append((penalty, violation))

    def _apply_standard_coverage(self, total, count):
        """Apply standard exact coverage constraint."""
        self.model.Add(total == count)

    def _apply_service_weekend_rules(self, d):
        """Apply rules for Worker F on service weekends."""
        f_msw = self.x.get(('F', d, 'MSW'), 0)
        f_fsw = self.x.get(('F', d, 'FSW'), 0)
        self.model.Add(f_msw + f_fsw == 1)

    def _add_rest_constraints(self):
        """Add daily rest (11h minimum) constraints via forbidden transitions."""
        min_rest = self.config['constraints']['min_daily_rest_hours']
        forbidden = self.shift_manager.get_forbidden_transitions(min_rest)

        for i in range(len(self.calendar.dates) - 1):
            d1 = self.calendar.dates[i]
            d2 = self.calendar.dates[i + 1]

            for w in self.workers:
                for (s1, s2) in forbidden:
                    x1 = self.x.get((w, d1, s1), None)
                    x2 = self.x.get((w, d2, s2), None)

                    if x1 is not None and x2 is not None:
                        self.model.Add(x1 + x2 <= 1)

    def _add_weekend_coupling(self):
        """Add weekend coupling: core workers work both Sat+Sun or neither."""
        if not self.config['constraints'].get('weekend_coupling_enabled', True):
            return

        weekend_pairs = self.calendar.get_weekend_pairs()

        for w in self.core_workers:
            for (sat, sun) in weekend_pairs:
                sat_work = self.works.get((w, sat), 0)
                sun_work = self.works.get((w, sun), 0)
                self.model.Add(sat_work == sun_work)

    def _add_sunday_compensation(self):
        """Add Sunday compensation constraints for core workers.

        Enforces a 10-day window (Week Of + Week After) for compensatory rest.
        Includes a soft preference for the rest day to occur in the Week Of.
        """
        if not self.config['constraints'].get('sunday_compensation_enabled', True):
            return

        for w in self.core_workers:
            for sun in self.calendar.get_sundays():
                sun_work = self.works.get((w, sun), None)
                if sun_work is None or not isinstance(sun_work, cp_model.IntVar):
                    continue

                # 1. Hard Constraint: 10-Day Window (Mon-Fri of Week Of + Week After)
                candidates = self.calendar.get_sunday_comp_weekdays(sun)
                if candidates:
                    total_work = sum(self.works.get((w, d), 0) for d in candidates)
                    # Must have at least one day off: work <= |C| - 1
                    self.model.Add(total_work <= len(candidates) - 1).OnlyEnforceIf(sun_work)

                    # 2. Soft Preference: Rest day in the SAME week (Monday-Friday of Sunday week)
                    # We penalize if the worker works ALL 5 days of the Sunday week.
                    monday_of = self.calendar.get_week_id(sun)
                    same_week_days = [monday_of + timedelta(days=i) for i in range(5)]
                    same_week_dates = [d for d in same_week_days if d in self.calendar.dates]
                    
                    if len(same_week_dates) == 5:
                        work_same_week = sum(self.works.get((w, d), 0) for d in same_week_dates)
                        delayed_var = self.model.NewBoolVar(f'sun_comp_delayed_{w}_{sun}')
                        
                        # delayed_var is 1 if (sun_work == 1) AND (work_same_week == 5)
                        is_full_week = self.model.NewBoolVar(f'full_week_{w}_{sun}')
                        self.model.Add(work_same_week == 5).OnlyEnforceIf(is_full_week)
                        self.model.Add(work_same_week < 5).OnlyEnforceIf(is_full_week.Not())
                        
                        self.model.AddBoolAnd([is_full_week, sun_work]).OnlyEnforceIf(delayed_var)
                        self.model.AddBoolOr([is_full_week.Not(), sun_work.Not()]).OnlyEnforceIf(delayed_var.Not())
                        
                        self.sunday_comp_delayed_vars.append(delayed_var)

                # 3. Soft Constraint: Next weekend off
                # Since weekend coupling is enabled, we only need to check Saturday
                try:
                    next_sat, _ = self.calendar.get_next_weekend(sun)
                    if next_sat in self.calendar.dates:
                        next_sat_work = self.works.get((w, next_sat), 0)
                        if isinstance(next_sat_work, cp_model.IntVar):
                            violation = self.model.NewBoolVar(f'sun_next_wknd_violation_{w}_{sun}')
                            # violation = sun_work AND next_sat_work
                            self.model.AddBoolAnd([sun_work, next_sat_work]).OnlyEnforceIf(violation)
                            self.model.AddBoolOr([sun_work.Not(), next_sat_work.Not()]).OnlyEnforceIf(violation.Not())
                            self.sunday_violations[w, sun] = violation
                except Exception:
                    pass

    # ========================================
    # SOFT CONSTRAINTS
    # ========================================

    def _add_weekly_rest_soft(self):
        """Add soft weekly rest constraint (penalize working all 7 days)."""
        if not self.config['constraints'].get('weekly_rest_penalty_enabled', True):
            return

        weeks = self.calendar.get_all_weeks()

        for w in self.core_workers:
            for week in weeks:
                days = self.calendar.get_days_in_week(week)
                total_work = sum(self.works.get((w, d), 0) for d in days)

                # Create boolean: no day off this week
                no_off = self.model.NewBoolVar(f'no_day_off_{w}_{week}')

                # Channeling constraints
                self.model.Add(total_work == len(days)).OnlyEnforceIf(no_off)
                self.model.Add(total_work <= len(days) -
                               1).OnlyEnforceIf(no_off.Not())

                self.no_day_off[w, week] = no_off

    def _add_fairness_constraints(self):
        """Add mean-scaled fairness constraints for core workers."""
        fairness_config = self.config['objective']['fairness']
        n = len(self.core_workers)

        # Weekend minutes fairness
        if fairness_config.get('weekend_minutes', 0) > 0:
            self._add_fairness_for_metric(
                'weekend_minutes',
                {w: self.weekend_minutes[w] for w in self.core_workers},
                n,
                fairness_config['weekend_minutes']
            )

        # Holiday minutes fairness
        if fairness_config.get('holiday_minutes', 0) > 0:
            self._add_fairness_for_metric(
                'holiday_minutes',
                {w: self.holiday_minutes[w] for w in self.core_workers},
                n,
                fairness_config['holiday_minutes']
            )

        # Weekday excess fairness
        if fairness_config.get('weekday_excess', 0) > 0:
            weeks = self.calendar.get_all_weeks()
            total_excess = {w: sum(self.excess40.get((w, week), 0) for week in weeks)
                            for w in self.core_workers}
            self._add_fairness_for_metric(
                'weekday_excess',
                total_excess,
                n,
                fairness_config['weekday_excess']
            )

        # Shift count fairness (for common shifts, exclude night shifts)
        if fairness_config.get('shift_counts', 0) > 0:
            common_shifts = ['M', 'I', 'T', 'MW', 'IW', 'TW',
                             'MS', 'IS', 'TS', 'MSW', 'ISW', 'TSW', 'FSW']
            for shift_code in common_shifts:
                counts = {w: self.shift_counts.get((w, shift_code), 0)
                          for w in self.core_workers}
                self._add_fairness_for_metric(
                    f'shift_{shift_code}',
                    counts,
                    n,
                    fairness_config['shift_counts']
                )

    def _add_fairness_for_metric(self, name: str, metrics: Dict[str, any],
                                 n: int, weight: int):
        """Add mean-scaled fairness for a metric.

        Minimizes: sum_w |n * metric[w] - Total|
        """
        total = sum(metrics.values())

        for w in metrics.keys():
            diff_var = self.model.NewIntVar(
                0, 10000000, f'fairness_{name}_{w}')
            self.model.AddAbsEquality(diff_var, n * metrics[w] - total)
            self.fairness_diffs[name, w] = diff_var

    # ========================================
    # OBJECTIVE FUNCTION
    # ========================================

    def _build_objective(self):
        """Build objective function to minimize."""
        obj_config = self.config['objective']

        objective = 0

        # 1. Work cost (weekend/holiday premium)
        # Only count report range days
        report_dates = self.calendar.get_report_dates()

        for w in self.workers:
            for d in report_dates:
                minutes = self.paid_minutes.get((w, d), 0)

                if self.calendar.is_saturday(d):
                    objective += obj_config['saturday_weight'] * minutes
                elif self.calendar.is_sunday(d):
                    objective += obj_config['sunday_weight'] * minutes

                if self.calendar.is_holiday(d):
                    objective += obj_config['holiday_weight'] * minutes

        # 2. Weekday excess cost
        weeks = self.calendar.get_all_weeks()
        for w in self.core_workers:
            for week in weeks:
                objective += obj_config['weekday_excess_weight'] * \
                    self.excess40.get((w, week), 0)

        # 3. Weekly rest penalty
        for w in self.core_workers:
            for week in weeks:
                objective += obj_config['weekly_rest_penalty'] * \
                    self.no_day_off.get((w, week), 0)

        # 4. Sunday compensation penalties (Soft Constraint)
        # (a) Next weekend violation
        sunday_penalty = obj_config.get('sunday_next_weekend_penalty', 0)
        for violation in self.sunday_violations.values():
            objective += sunday_penalty * violation

        # (b) Delayed compensation violation (taken in Week After instead of Week Of)
        delayed_penalty = obj_config.get('penalty_sunday_comp_delayed', 0)
        for var in self.sunday_comp_delayed_vars:
            objective += delayed_penalty * var

        # 5. Flexible coverage penalties
        for penalty, violation in self.flexible_coverage_violations:
            objective += penalty * violation

        # 6. Fairness costs
        # These are mean-scaled absolute deviations to ensure work is distributed
        # evenly across all core workers. Weights are built into the diff variables.
        for (metric, w), diff in self.fairness_diffs.items():
            objective += diff

        self.model.Minimize(objective)

    def get_model(self) -> cp_model.CpModel:
        """Get the built CP-SAT model."""
        return self.model
