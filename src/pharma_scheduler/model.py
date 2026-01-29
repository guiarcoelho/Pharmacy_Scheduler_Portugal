"""CP-SAT model for config-driven scheduling."""

from typing import Dict, List
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

        # Objective terms collected by rulebook
        self.objective_terms = []

        # Internal indices to speed up model building
        self._shift_codes_by_worker_day = {}  # (w, d) -> list[str]

    def build(self):
        """Build complete CP-SAT model."""
        print("Creating variables...")
        self._create_variables()

        print("Applying rulebook...")
        compiler = RulebookCompiler(
            model=self.model,
            calendar=self.calendar,
            shift_manager=self.shift_manager,
            workers=self.workers,
            assignments=self.x,
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
