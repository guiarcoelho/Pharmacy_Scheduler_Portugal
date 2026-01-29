"""Rulebook compiler: translates config rules into CP-SAT constraints.

The rulebook (`constraints.yaml`) is the single source of truth for:
- hard constraints (must hold)
- soft constraints / preferences (add penalty terms to the objective)

Each rule has an `op` that maps to a compiler method:
  op: max_assignments_per_worker_per_day
  -> _op_max_assignments_per_worker_per_day(...)

`where` is a JSONLogic predicate evaluated against a context dict containing
some subset of: `{day, shift, worker}` (depending on op).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List

from ortools.sat.python import cp_model

from .jsonlogic import evaluate


@dataclass
class Rule:
    id: str
    kind: str
    op: str
    params: dict
    where: dict | None


class RulebookCompiler:
    def __init__(
        self,
        *,
        model: cp_model.CpModel,
        calendar,
        shift_manager,
        workers: List[dict],
        works: Dict,
        assignments: Dict,
        paid_minutes: Dict,
        weekday_minutes: Dict,
        excess40: Dict,
        shift_counts: Dict,
    ):
        self.model = model
        self.calendar = calendar
        self.shift_manager = shift_manager
        self.workers = workers
        self.works = works
        self.assignments = assignments
        self.paid_minutes = paid_minutes
        self.weekday_minutes = weekday_minutes
        self.excess40 = excess40
        self.shift_counts = shift_counts

        self.objective_terms = []

    def apply(self, rules: Iterable[dict]):
        for raw in rules:
            rule = Rule(
                id=raw.get("id", ""),
                kind=raw.get("kind", "hard"),
                op=raw.get("op", ""),
                params=raw.get("params", {}) or {},
                where=raw.get("where"),
            )
            handler = getattr(self, f"_op_{rule.op}", None)
            if handler is None:
                raise ValueError(f"Unknown rule op: {rule.op}")
            handler(rule)

    def _matches(self, rule: Rule, ctx: dict) -> bool:
        if rule.where is None:
            return True
        return bool(evaluate(rule.where, ctx))

    def _op_max_assignments_per_worker_per_day(self, rule: Rule):
        max_count = int(rule.params.get("max", 1))
        for w in self.workers:
            w_id = w["id"]
            for d in self.calendar.dates:
                day_ctx = self.calendar.get_day_context(d)
                ctx = {"worker": w, "day": day_ctx}
                if not self._matches(rule, ctx):
                    continue
                shifts = [
                    s for s in self.shift_manager.shifts
                    if (w_id, d, s.code) in self.assignments
                ]
                if not shifts:
                    continue
                total = sum(self.assignments[w_id, d, s.code] for s in shifts)
                self.model.Add(total <= max_count)

    def _op_coverage_bounds_from_shift(self, rule: Rule):
        for d in self.calendar.dates:
            day_ctx = self.calendar.get_day_context(d)
            for shift in self.shift_manager.shifts:
                if not self.shift_manager.is_shift_allowed(shift, day_ctx):
                    continue
                ctx = {"day": day_ctx, "shift": self.shift_manager._shift_ctx(shift)}
                if not self._matches(rule, ctx):
                    continue
                total = sum(
                    self.assignments.get((w["id"], d, shift.code), 0)
                    for w in self.workers
                )
                self.model.Add(total >= shift.coverage_min)
                self.model.Add(total <= shift.coverage_max)

    def _op_coverage_soft_shortfall_to_shift_max(self, rule: Rule):
        penalty = int(rule.params.get("penalty_per_unit", 0))
        if penalty <= 0:
            return
        for d in self.calendar.dates:
            day_ctx = self.calendar.get_day_context(d)
            for shift in self.shift_manager.shifts:
                if not self.shift_manager.is_shift_allowed(shift, day_ctx):
                    continue
                ctx = {"day": day_ctx, "shift": self.shift_manager._shift_ctx(shift)}
                if not self._matches(rule, ctx):
                    continue
                total = sum(
                    self.assignments.get((w["id"], d, shift.code), 0)
                    for w in self.workers
                )
                shortfall = self.model.NewIntVar(
                    0, shift.coverage_max, f"shortfall_{shift.code}_{d}"
                )
                self.model.AddMaxEquality(shortfall, [0, shift.coverage_max - total])
                self.objective_terms.append(penalty * shortfall)

    def _op_min_rest_between_consecutive_days(self, rule: Rule):
        min_hours = int(rule.params.get("min_hours", 11))
        forbidden = self.shift_manager.get_forbidden_transitions(min_hours)
        for i in range(len(self.calendar.dates) - 1):
            d1 = self.calendar.dates[i]
            d2 = self.calendar.dates[i + 1]
            for w in self.workers:
                if not self._matches(rule, {"worker": w}):
                    continue
                w_id = w["id"]
                for s1, s2 in forbidden:
                    x1 = self.assignments.get((w_id, d1, s1))
                    x2 = self.assignments.get((w_id, d2, s2))
                    if x1 is not None and x2 is not None:
                        self.model.Add(x1 + x2 <= 1)

    def _op_weekend_coupling(self, rule: Rule):
        for w in self.workers:
            w_ctx = {"worker": w}
            if not self._matches(rule, w_ctx):
                continue
            w_id = w["id"]
            for sat, sun in self.calendar.get_weekend_pairs():
                sat_work = self.works.get((w_id, sat), 0)
                sun_work = self.works.get((w_id, sun), 0)
                self.model.Add(sat_work == sun_work)

    def _op_sunday_comp_min_day_off(self, rule: Rule):
        min_days_off = int(rule.params.get("min_days_off", 1))
        for w in self.workers:
            w_ctx = {"worker": w}
            if not self._matches(rule, w_ctx):
                continue
            w_id = w["id"]
            for sun in self.calendar.get_sundays():
                sun_work = self.works.get((w_id, sun), None)
                if sun_work is None or not isinstance(sun_work, cp_model.IntVar):
                    continue
                week1, week2 = self.calendar.get_sunday_comp_windows(sun)
                candidates = week1 + week2
                if candidates:
                    total_work = sum(self.works.get((w_id, d), 0) for d in candidates)
                    self.model.Add(
                        total_work <= len(candidates) - min_days_off
                    ).OnlyEnforceIf(sun_work)

    def _op_sunday_next_weekend_penalty(self, rule: Rule):
        penalty = int(rule.params.get("penalty_per_unit", 0))
        if penalty <= 0:
            return
        for w in self.workers:
            w_ctx = {"worker": w}
            if not self._matches(rule, w_ctx):
                continue
            w_id = w["id"]
            for sun in self.calendar.get_sundays():
                sun_work = self.works.get((w_id, sun), None)
                if sun_work is None or not isinstance(sun_work, cp_model.IntVar):
                    continue
                next_sat, _ = self.calendar.get_next_weekend(sun)
                if next_sat not in self.calendar.dates:
                    continue
                next_sat_work = self.works.get((w_id, next_sat), None)
                if next_sat_work is None or not isinstance(next_sat_work, cp_model.IntVar):
                    continue
                violation = self.model.NewBoolVar(f"sun_next_wknd_{w_id}_{sun}")
                self.model.AddBoolAnd([sun_work, next_sat_work]).OnlyEnforceIf(violation)
                self.model.AddBoolOr([sun_work.Not(), next_sat_work.Not()]).OnlyEnforceIf(
                    violation.Not()
                )
                self.objective_terms.append(penalty * violation)

    def _op_sunday_comp_delayed_penalty(self, rule: Rule):
        penalty = int(rule.params.get("penalty_per_unit", 0))
        if penalty <= 0:
            return
        for w in self.workers:
            w_ctx = {"worker": w}
            if not self._matches(rule, w_ctx):
                continue
            w_id = w["id"]
            for sun in self.calendar.get_sundays():
                sun_work = self.works.get((w_id, sun), None)
                if sun_work is None or not isinstance(sun_work, cp_model.IntVar):
                    continue
                week1, _ = self.calendar.get_sunday_comp_windows(sun)
                if len(week1) != 5:
                    continue
                work_week1 = sum(self.works.get((w_id, d), 0) for d in week1)
                is_full_week = self.model.NewBoolVar(f"full_week1_{w_id}_{sun}")
                self.model.Add(work_week1 == 5).OnlyEnforceIf(is_full_week)
                self.model.Add(work_week1 < 5).OnlyEnforceIf(is_full_week.Not())

                violation = self.model.NewBoolVar(f"sun_comp_delayed_{w_id}_{sun}")
                self.model.AddBoolAnd([is_full_week, sun_work]).OnlyEnforceIf(violation)
                self.model.AddBoolOr([is_full_week.Not(), sun_work.Not()]).OnlyEnforceIf(
                    violation.Not()
                )
                self.objective_terms.append(penalty * violation)

    def _op_weekly_no_day_off_penalty(self, rule: Rule):
        penalty = int(rule.params.get("penalty_per_unit", 0))
        if penalty <= 0:
            return
        weeks = self.calendar.get_all_weeks()
        for w in self.workers:
            w_ctx = {"worker": w}
            if not self._matches(rule, w_ctx):
                continue
            w_id = w["id"]
            for week in weeks:
                days = self.calendar.get_days_in_week(week)
                total_work = sum(self.works.get((w_id, d), 0) for d in days)
                no_off = self.model.NewBoolVar(f"no_day_off_{w_id}_{week}")
                self.model.Add(total_work == len(days)).OnlyEnforceIf(no_off)
                self.model.Add(total_work <= len(days) - 1).OnlyEnforceIf(no_off.Not())
                self.objective_terms.append(penalty * no_off)

    def _op_cost_per_minute(self, rule: Rule):
        penalty = int(rule.params.get("penalty_per_unit", 0))
        if penalty <= 0:
            return
        for d in self.calendar.dates:
            day_ctx = self.calendar.get_day_context(d)
            for shift in self.shift_manager.shifts:
                if not self.shift_manager.is_shift_allowed(shift, day_ctx):
                    continue
                ctx = {"day": day_ctx, "shift": self.shift_manager._shift_ctx(shift)}
                if not self._matches(rule, ctx):
                    continue
                for w in self.workers:
                    var = self.assignments.get((w["id"], d, shift.code))
                    if var is None:
                        continue
                    self.objective_terms.append(penalty * shift.paid_minutes * var)

    def _op_weekday_excess_cost(self, rule: Rule):
        penalty = int(rule.params.get("penalty_per_unit", 0))
        if penalty <= 0:
            return
        weeks = self.calendar.get_all_weeks()
        for w in self.workers:
            w_ctx = {"worker": w}
            if not self._matches(rule, w_ctx):
                continue
            w_id = w["id"]
            for week in weeks:
                excess = self.excess40.get((w_id, week), 0)
                # `excess` is typically an IntVar; don't compare it to 0 (unsupported).
                # Adding `penalty * 0` is fine when it's a constant.
                self.objective_terms.append(penalty * excess)

    def _op_fairness_mean_scaled(self, rule: Rule):
        metric = rule.params.get("metric")
        weight = int(rule.params.get("penalty_per_unit", 0))
        if weight <= 0:
            return

        workers = [w for w in self.workers if self._matches(rule, {"worker": w})]
        if len(workers) < 2:
            return
        worker_ids = [w["id"] for w in workers]
        n = len(worker_ids)

        if metric == "weekend_minutes":
            metrics = {w: self._weekend_minutes(w) for w in worker_ids}
        elif metric == "holiday_minutes":
            metrics = {w: self._holiday_minutes(w) for w in worker_ids}
        elif metric == "weekday_excess":
            metrics = {
                w: sum(
                    self.excess40.get((w, week), 0)
                    for week in self.calendar.get_all_weeks()
                )
                for w in worker_ids
            }
        elif isinstance(metric, str) and metric.startswith("shift_count:"):
            code = metric.split(":", 1)[1]
            metrics = {
                w: self.shift_counts.get((w, code), 0) for w in worker_ids
            }
        else:
            return

        total = sum(metrics.values())
        for w in worker_ids:
            diff = self.model.NewIntVar(0, 10000000, f"fairness_{metric}_{w}")
            self.model.AddAbsEquality(diff, n * metrics[w] - total)
            self.objective_terms.append(weight * diff)

    def _weekend_minutes(self, worker_id: str):
        sat_days = [d for d in self.calendar.dates if self.calendar.is_saturday(d)]
        sun_days = [d for d in self.calendar.dates if self.calendar.is_sunday(d)]
        return sum(self.paid_minutes.get((worker_id, d), 0) for d in sat_days + sun_days)

    def _holiday_minutes(self, worker_id: str):
        holiday_days = [d for d in self.calendar.dates if self.calendar.is_holiday(d)]
        return sum(self.paid_minutes.get((worker_id, d), 0) for d in holiday_days)
