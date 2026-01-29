"""CP-SAT model for config-driven scheduling."""

from datetime import date, timedelta
from typing import Dict, List, Tuple
from ortools.sat.python import cp_model

from .calendar import Calendar
from .shifts import ShiftManager
from .jsonlogic import evaluate
from .rulebook import RulebookCompiler


class SchedulingModel:
    """CP-SAT model for pharmacy staff scheduling."""

    def __init__(
        self,
        calendar: Calendar,
        shift_manager: ShiftManager,
        workers: List[dict],
        rulebook: List[dict],
    ):
        """Initialize scheduling model.

        Args:
            calendar: Calendar with dates and day types
            shift_manager: Shift manager with shifts and demand
            workers: All worker dicts
            rulebook: List of constraint rules
        """
        self.calendar = calendar
        self.shift_manager = shift_manager
        self.workers = workers
        self.worker_ids = [w["id"] for w in workers]
        self.workers_by_id = {w["id"]: w for w in workers}
        self.rulebook = rulebook

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

        # Objective terms collected by rulebook
        self.objective_terms = []

        # Internal indices to speed up model building
        self._shift_codes_by_worker_day = {}  # (w, d) -> list[str]

    def build(self):
        """Build complete CP-SAT model."""
        print("Creating variables...")
        self._create_variables()
        self._create_aggregated_metrics()

        print("Applying rulebook...")
        compiler = RulebookCompiler(
            model=self.model,
            calendar=self.calendar,
            shift_manager=self.shift_manager,
            workers=self.workers,
            works=self.works,
            assignments=self.x,
            paid_minutes=self.paid_minutes,
            weekday_minutes=self.weekday_minutes,
            excess40=self.excess40,
            shift_counts=self.shift_counts,
        )
        compiler.apply(self.rulebook)
        self.objective_terms = compiler.objective_terms

        print("Building objective...")
        objective = sum(self.objective_terms) if self.objective_terms else 0
        self.model.Minimize(objective)

        print(f"Model built: {self.model.ModelStats()}")

    # ========================================
    # VARIABLE CREATION
    # ========================================

    def _create_variables(self):
        """Create all CP-SAT variables."""
        shift_paid_minutes = {
            s.code: s.paid_minutes for s in self.shift_manager.shifts
        }

        # Primary assignment variables
        for w in self.workers:
            w_id = w["id"]
            for d in self.calendar.dates:
                day_ctx = self.calendar.get_day_context(d)
                shift_codes = []

                for shift in self.shift_manager.shifts:
                    if not self.shift_manager.is_shift_allowed(shift, day_ctx):
                        continue
                    if not self._worker_can_do_shift(w, shift, day_ctx):
                        continue
                    self.x[w_id, d, shift.code] = self.model.NewBoolVar(
                        f'x_{w_id}_{d}_{shift.code}'
                    )
                    shift_codes.append(shift.code)
                self._shift_codes_by_worker_day[w_id, d] = shift_codes

        # Works indicator: at most one shift per day
        for w in self.worker_ids:
            for d in self.calendar.dates:
                shifts_on_day = self._shift_codes_by_worker_day.get((w, d), [])
                if shifts_on_day:
                    self.works[w, d] = self.model.NewBoolVar(f'works_{w}_{d}')
                    self.model.Add(
                        sum(self.x[w, d, s] for s in shifts_on_day) == self.works[w, d])
                else:
                    # No eligible shifts this day
                    self.works[w, d] = 0

        # Paid minutes by worker-day
        for w in self.worker_ids:
            for d in self.calendar.dates:
                shift_codes = self._shift_codes_by_worker_day.get((w, d), [])
                if shift_codes:
                    self.paid_minutes[w, d] = sum(
                        self.x[w, d, s] * shift_paid_minutes[s] for s in shift_codes
                    )
                else:
                    self.paid_minutes[w, d] = 0

    def _create_aggregated_metrics(self):
        """Create aggregated metric variables."""
        # Weekend/holiday minutes
        sat_days = [d for d in self.calendar.dates if self.calendar.is_saturday(d)]
        sun_days = [d for d in self.calendar.dates if self.calendar.is_sunday(d)]
        holiday_days = [d for d in self.calendar.dates if self.calendar.is_holiday(d)]

        for w in self.worker_ids:
            self.sat_minutes[w] = sum(
                self.paid_minutes.get((w, d), 0) for d in sat_days)
            self.sun_minutes[w] = sum(
                self.paid_minutes.get((w, d), 0) for d in sun_days)
            self.holiday_minutes[w] = sum(
                self.paid_minutes.get((w, d), 0) for d in holiday_days)
            self.weekend_minutes[w] = self.sat_minutes[w] + self.sun_minutes[w]

        # Weekday minutes and excess over 40h per week
        weeks = self.calendar.get_all_weeks()
        max_paid_minutes = max((s.paid_minutes for s in self.shift_manager.shifts), default=0)
        max_weekday_minutes = max_paid_minutes * 5
        max_excess = max(0, max_weekday_minutes - 2400)

        for w in self.worker_ids:
            for week in weeks:
                weekdays = [d for d in self.calendar.get_days_in_week(week)
                            if d.weekday() < 5]  # Mon-Fri

                self.weekday_minutes[w, week] = sum(
                    self.paid_minutes.get((w, d), 0) for d in weekdays
                )

                # Excess over 40h (2400 minutes)
                excess_var = self.model.NewIntVar(
                    0, max_excess, f'excess40_{w}_{week}')
                self.model.AddMaxEquality(
                    excess_var,
                    [0, self.weekday_minutes[w, week] - 2400],
                )
                self.excess40[w, week] = excess_var

        # Shift counts
        for w in self.worker_ids:
            for shift in self.shift_manager.shifts:
                count = sum(self.x.get((w, d, shift.code), 0)
                            for d in self.calendar.dates)
                self.shift_counts[w, shift.code] = count

    def _worker_can_do_shift(self, worker: dict, shift, day_ctx: dict) -> bool:
        if not shift.requires_worker_caps.issubset(set(worker.get("caps", []))):
            return False
        allowed_when = worker.get("allowed_when")
        if allowed_when is None:
            return True
        worker_ctx = dict(worker)
        worker_ctx.setdefault("groups", [])
        worker_ctx.setdefault("caps", [])
        shift_ctx = self.shift_manager._shift_ctx(shift)
        return bool(
            evaluate(
                allowed_when, {"day": day_ctx, "shift": shift_ctx, "worker": worker_ctx}
            )
        )

    def get_model(self) -> cp_model.CpModel:
        """Get the built CP-SAT model."""
        return self.model
