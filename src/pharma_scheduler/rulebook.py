"""Primitive rulebook compiler for CP-SAT scheduling constraints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List

from ortools.sat.python import cp_model

from .jsonlogic import evaluate


@dataclass
class AssignmentRecord:
    worker_id: str
    worker: dict
    day: dict
    day_date: date
    shift: dict
    shift_code: str
    var: cp_model.IntVar


class RulebookCompiler:
    def __init__(
        self,
        *,
        model: cp_model.CpModel,
        calendar,
        shift_manager,
        workers: List[dict],
        assignments: Dict,
    ):
        self.model = model
        self.calendar = calendar
        self.shift_manager = shift_manager
        self.workers = self._normalize_workers(workers)
        self.assignments = assignments
        self.objective_terms: List[Any] = []
        self.rulebook_data: dict = {}

        self._day_items = self._build_day_items()
        self._day_by_date = {item["date_obj"]: item for item in self._day_items}
        self._week_items = self._build_week_items()
        self._shift_items = self._build_shift_items()
        self._shift_by_code = {s["code"]: s for s in self._shift_items}
        self._assignment_records = self._build_assignment_records()
        self._index_by_day = self._index_records("day_date")
        self._transition_cache: Dict[int, List[dict]] = {}
        self._var_counter = 0

    def apply(self, rulebook: Iterable[dict] | dict):
        if isinstance(rulebook, dict):
            self.rulebook_data = rulebook
            rules = rulebook.get("rules", []) or []
        else:
            self.rulebook_data = {}
            rules = rulebook or []
        for raw in rules:
            self._apply_rule(raw)

    def _apply_rule(self, rule: dict):
        for_each = rule.get("for_each", []) or []
        for env in self._iter_envs(for_each):
            if self._skip_env(env):
                continue
            let_values: Dict[str, Any] = {}
            for name, expr in (rule.get("let") or {}).items():
                let_values[name] = self._compile_int(expr, env, let_values)

            for stmt in rule.get("hard", []) or []:
                only_if = self._compile_bool(stmt.get("only_if"), env, let_values)
                if isinstance(only_if, bool) and not only_if:
                    continue
                lhs = self._compile_int(stmt["lhs"], env, let_values)
                rhs = self._compile_int(stmt["rhs"], env, let_values)
                op = stmt["op"]
                self._add_comparison(lhs, op, rhs, only_if)

            for stmt in rule.get("soft", []) or []:
                only_if = self._compile_bool(stmt.get("only_if"), env, let_values)
                if isinstance(only_if, bool) and not only_if:
                    continue
                units = self._compile_int(stmt["units"], env, let_values)
                if not isinstance(only_if, bool):
                    units = self._guard_units(units, only_if)
                penalty = stmt.get("penalty_per_unit", 0)
                if isinstance(penalty, dict):
                    penalty = self._compile_int(penalty, env, let_values)
                if penalty == 0:
                    continue
                self.objective_terms.append(penalty * units)

    def _normalize_workers(self, workers: List[dict]) -> List[dict]:
        normalized = []
        for w in workers:
            w = dict(w)
            w.setdefault("groups", [])
            w.setdefault("caps", [])
            w.setdefault("vacation_days", [])
            normalized.append(w)
        return normalized

    def _build_day_items(self) -> List[dict]:
        items = []
        for d in self.calendar.dates:
            ctx = dict(self.calendar.get_day_context(d))
            ctx["date_obj"] = d
            ctx["has_next_day"] = d + timedelta(days=1) in self.calendar.dates
            ctx["week_id"] = self.calendar.get_week_id(d).isoformat()
            items.append(ctx)
        return items

    def _build_week_items(self) -> List[dict]:
        items = []
        for week_id in self.calendar.get_all_weeks():
            days = self.calendar.get_days_in_week(week_id)
            items.append(
                {
                    "id": week_id.isoformat(),
                    "week_id": week_id,
                    "days": days,
                    "size": len(days),
                }
            )
        return items

    def _build_shift_items(self) -> List[dict]:
        items = []
        for shift in self.shift_manager.shifts:
            ctx = self.shift_manager._shift_ctx(shift)
            ctx["paid_minutes"] = shift.paid_minutes
            ctx["clock_minutes"] = shift.clock_minutes
            ctx["soft_fill_penalty"] = getattr(shift, "soft_fill_penalty", 0)
            ctx["_obj"] = shift
            items.append(ctx)
        return items

    def _build_assignment_records(self) -> List[AssignmentRecord]:
        records: List[AssignmentRecord] = []
        for (w_id, d, s_code), var in self.assignments.items():
            worker = next(w for w in self.workers if w["id"] == w_id)
            day = self._day_by_date[d]
            shift = self._shift_by_code[s_code]
            records.append(
                AssignmentRecord(
                    worker_id=w_id,
                    worker=worker,
                    day=day,
                    day_date=d,
                    shift=shift,
                    shift_code=s_code,
                    var=var,
                )
            )
        return records

    def _index_records(self, key: str) -> Dict[Any, List[AssignmentRecord]]:
        index: Dict[Any, List[AssignmentRecord]] = {}
        for rec in self._assignment_records:
            value = getattr(rec, key)
            index.setdefault(value, []).append(rec)
        return index

    def _iter_envs(self, for_each: List[dict]):
        env = {"i": {}}

        def walk(idx: int):
            if idx >= len(for_each):
                yield env
                return
            iter_def = for_each[idx]
            var_name = iter_def["var"]
            items = self._iter_items(iter_def, env)
            for item in items:
                env["i"][var_name] = item
                yield from walk(idx + 1)
            env["i"].pop(var_name, None)

        if not for_each:
            yield env
        else:
            yield from walk(0)

    def _iter_items(self, iter_def: dict, env: dict) -> List[dict]:
        iter_type = iter_def.get("type")
        if iter_type == "day":
            items = self._day_items
        elif iter_type == "week":
            items = self._week_items
        elif iter_type == "worker":
            items = self.workers
        elif iter_type == "shift":
            items = self._shift_items
        elif iter_type == "shift_transition":
            min_hours = int(iter_def.get("params", {}).get("min_rest_hours", 11))
            items = self._get_shift_transitions(min_hours)
        elif iter_type == "list":
            items = self._get_list_items(iter_def)
        else:
            raise ValueError(f"Unknown iterator type: {iter_type}")

        where = iter_def.get("where")
        if not where:
            return items
        filtered = []
        for item in items:
            ctx = {"this": item, "i": env.get("i", {})}
            if evaluate(where, ctx):
                filtered.append(item)
        return filtered

    def _get_list_items(self, iter_def: dict) -> List[dict]:
        path = iter_def.get("from")
        if not path:
            raise ValueError("list iterator requires 'from'")
        items = self._get_rulebook_path(path)
        if not isinstance(items, list):
            raise ValueError(f"list iterator expects list at '{path}'")
        expanded: List[dict] = []
        for item in items:
            if isinstance(item, dict) and "per_shift" in item:
                expanded.extend(self._expand_per_shift_item(item))
            else:
                expanded.append(item)
        return expanded

    def _expand_per_shift_item(self, item: dict) -> List[dict]:
        per_shift = item.get("per_shift") or {}
        where = per_shift.get("where")
        expanded: List[dict] = []
        for shift in self._shift_items:
            if where and not evaluate(where, {"shift": shift, "this": shift}):
                continue
            new_item = dict(item)
            new_item.pop("per_shift", None)
            new_item["shift"] = shift
            if new_item.get("id") and "code" in shift:
                new_item["id"] = f"{new_item['id']}:{shift['code']}"
            expanded.append(new_item)
        return expanded

    def _get_shift_transitions(self, min_rest_hours: int) -> List[dict]:
        if min_rest_hours not in self._transition_cache:
            pairs = self.shift_manager.get_forbidden_transitions(min_rest_hours)
            self._transition_cache[min_rest_hours] = [
                {"from": a, "to": b, "min_rest_hours": min_rest_hours} for a, b in pairs
            ]
        return self._transition_cache[min_rest_hours]

    def _skip_env(self, env: dict) -> bool:
        day = env["i"].get("day")
        shift = env["i"].get("shift")
        if day and shift:
            shift_obj = shift.get("_obj")
            if shift_obj and not self.shift_manager.is_shift_allowed(
                shift_obj, day
            ):
                return True
        return False

    def _add_comparison(self, lhs: Any, op: str, rhs: Any, only_if: Any):
        if isinstance(only_if, bool):
            enforce = None
        else:
            enforce = only_if
        if op == ">=":
            c = self.model.Add(lhs >= rhs)
            if enforce is not None:
                c.OnlyEnforceIf(enforce)
            return
        if op == "<=":
            c = self.model.Add(lhs <= rhs)
            if enforce is not None:
                c.OnlyEnforceIf(enforce)
            return
        if op == "==":
            c = self.model.Add(lhs == rhs)
            if enforce is not None:
                c.OnlyEnforceIf(enforce)
            return
        raise ValueError(f"Unsupported comparison op: {op}")

    def _guard_units(self, units: Any, guard: Any):
        ub = self._estimate_upper_bound(units, {}, {})
        var = self._new_int_var(0, ub, "guard")
        c1 = self.model.Add(var == units)
        c1.OnlyEnforceIf(guard)
        c2 = self.model.Add(var == 0)
        c2.OnlyEnforceIf(guard.Not())
        return var

    def _compile_int(self, expr: Any, env: dict, let_values: dict) -> Any:
        if isinstance(expr, (int, float)):
            return int(expr)
        if isinstance(expr, bool):
            return int(expr)
        if expr is None:
            return 0
        if isinstance(expr, list):
            return [self._compile_int(x, env, let_values) for x in expr]
        if not isinstance(expr, dict):
            return expr

        if "const" in expr:
            return int(expr["const"])
        if "var" in expr:
            return self._resolve_var(expr["var"], env, let_values)
        if "ref" in expr:
            return let_values[expr["ref"]]
        if "sum" in expr:
            return sum((self._compile_int(x, env, let_values) for x in expr["sum"]), 0)
        if "sub" in expr:
            a, b = expr["sub"]
            return self._compile_int(a, env, let_values) - self._compile_int(
                b, env, let_values
            )
        if "mul" in expr:
            a, b = expr["mul"]
            left = self._compile_int(a, env, let_values)
            right = self._compile_int(b, env, let_values)
            if isinstance(left, (int, float)):
                return right * int(left)
            if isinstance(right, (int, float)):
                return left * int(right)
            raise ValueError("mul requires one side to be a constant")
        if "max0" in expr:
            inner = self._compile_int(expr["max0"], env, let_values)
            ub = self._estimate_upper_bound(expr["max0"], env, let_values)
            var = self._new_int_var(0, ub, "max0")
            self.model.AddMaxEquality(var, [0, inner])
            return var
        if "abs" in expr:
            inner = self._compile_int(expr["abs"], env, let_values)
            ub = self._estimate_upper_bound(expr["abs"], env, let_values)
            var = self._new_int_var(0, ub, "abs")
            self.model.AddAbsEquality(var, inner)
            return var
        if "with" in expr:
            payload = expr["with"]
            bindings = payload.get("bindings", {})
            saved = {}
            for key, ref in bindings.items():
                saved[key] = env["i"].get(key)
                env["i"][key] = self._resolve_ref(ref, env)
            try:
                return self._compile_int(payload["expr"], env, let_values)
            finally:
                for key, value in saved.items():
                    if value is None:
                        env["i"].pop(key, None)
                    else:
                        env["i"][key] = value
        if "eval" in expr:
            target = expr["eval"]
            if isinstance(target, dict) and "var" in target:
                target = self._resolve_var(target["var"], env, let_values)
            elif isinstance(target, dict) and "ref" in target:
                target = let_values[target["ref"]]
            elif isinstance(target, str):
                target = self._resolve_ref(target, env)
            if isinstance(target, dict):
                return self._compile_int(target, env, let_values)
            return target
        if "bool_as_int" in expr:
            cond = self._compile_bool(expr["bool_as_int"], env, let_values)
            return self._bool_to_int(cond)
        if "count_assignments" in expr:
            select = expr["count_assignments"]["select"]
            records = self._select_records(select, env)
            return sum((rec.var for rec in records), 0)
        if "sum_assignment_attr" in expr:
            payload = expr["sum_assignment_attr"]
            select = payload["select"]
            attr = payload["attr"]
            records = self._select_records(select, env)
            total = 0
            for rec in records:
                total += rec.var * int(self._get_attr(rec.shift, attr))
            return total
        if "sum_over" in expr:
            payload = expr["sum_over"]
            iter_def = payload["iter"]
            inner = payload["expr"]
            total = 0
            items = self._iter_items(iter_def, env)
            var_name = iter_def["var"]
            for item in items:
                env["i"][var_name] = item
                total += self._compile_int(inner, env, let_values)
            env["i"].pop(var_name, None)
            return total
        if "count_over" in expr:
            iter_def = expr["count_over"]["iter"]
            items = self._iter_items(iter_def, env)
            return len(items)
        if "range_size" in expr:
            spec = expr["range_size"]
            days = self._resolve_day_range(spec, env)
            return len(days)

        return expr

    def _compile_bool(self, expr: Any, env: dict, let_values: dict) -> Any:
        if isinstance(expr, bool):
            return expr
        if expr is None:
            return True
        if isinstance(expr, dict):
            if "jsonlogic" in expr:
                return bool(self._eval_jsonlogic(expr["jsonlogic"], env))
            if "with" in expr:
                payload = expr["with"]
                bindings = payload.get("bindings", {})
                saved = {}
                for key, ref in bindings.items():
                    saved[key] = env["i"].get(key)
                    env["i"][key] = self._resolve_ref(ref, env)
                try:
                    return self._compile_bool(payload["expr"], env, let_values)
                finally:
                    for key, value in saved.items():
                        if value is None:
                            env["i"].pop(key, None)
                        else:
                            env["i"][key] = value
            if "and" in expr:
                parts = [self._compile_bool(x, env, let_values) for x in expr["and"]]
                if all(isinstance(p, bool) for p in parts):
                    return all(parts)
                literals = [p for p in parts if not isinstance(p, bool)]
                if any(isinstance(p, bool) and not p for p in parts):
                    return False
                if not literals:
                    return True
                return self._bool_and(literals)
            if "or" in expr:
                parts = [self._compile_bool(x, env, let_values) for x in expr["or"]]
                if all(isinstance(p, bool) for p in parts):
                    return any(parts)
                literals = [p for p in parts if not isinstance(p, bool)]
                if any(isinstance(p, bool) and p for p in parts):
                    return True
                if not literals:
                    return False
                return self._bool_or(literals)
            if "not" in expr:
                inner = self._compile_bool(expr["not"], env, let_values)
                if isinstance(inner, bool):
                    return not inner
                return inner.Not()
            if "cmp" in expr:
                payload = expr["cmp"]
                lhs = self._compile_int(payload["lhs"], env, let_values)
                rhs = self._compile_int(payload["rhs"], env, let_values)
                return self._reify_comparison(lhs, payload["op"], rhs)
        return bool(expr)

    def _bool_and(self, literals: List[Any]):
        b = self.model.NewBoolVar(self._var_name("and"))
        self.model.AddBoolAnd(literals).OnlyEnforceIf(b)
        self.model.AddBoolOr([lit.Not() for lit in literals]).OnlyEnforceIf(b.Not())
        return b

    def _bool_or(self, literals: List[Any]):
        b = self.model.NewBoolVar(self._var_name("or"))
        self.model.AddBoolOr(literals).OnlyEnforceIf(b)
        self.model.AddBoolAnd([lit.Not() for lit in literals]).OnlyEnforceIf(b.Not())
        return b

    def _bool_to_int(self, cond: Any):
        if isinstance(cond, bool):
            return int(cond)
        if isinstance(cond, cp_model.IntVar):
            return cond
        b = self.model.NewBoolVar(self._var_name("bool"))
        self.model.AddImplication(b, cond)
        self.model.AddImplication(cond, b)
        return b

    def _reify_comparison(self, lhs: Any, op: str, rhs: Any):
        b = self.model.NewBoolVar(self._var_name("cmp"))
        if op == ">=":
            self.model.Add(lhs >= rhs).OnlyEnforceIf(b)
            self.model.Add(lhs <= rhs - 1).OnlyEnforceIf(b.Not())
            return b
        if op == "<=":
            self.model.Add(lhs <= rhs).OnlyEnforceIf(b)
            self.model.Add(lhs >= rhs + 1).OnlyEnforceIf(b.Not())
            return b
        if op == "==":
            ub = self._estimate_upper_bound({"sub": [lhs, rhs]}, {}, {})
            diff = self._new_int_var(0, ub, "eqdiff")
            self.model.AddAbsEquality(diff, lhs - rhs)
            self.model.Add(diff == 0).OnlyEnforceIf(b)
            self.model.Add(diff >= 1).OnlyEnforceIf(b.Not())
            return b
        if op == "<":
            self.model.Add(lhs <= rhs - 1).OnlyEnforceIf(b)
            self.model.Add(lhs >= rhs).OnlyEnforceIf(b.Not())
            return b
        if op == ">":
            self.model.Add(lhs >= rhs + 1).OnlyEnforceIf(b)
            self.model.Add(lhs <= rhs).OnlyEnforceIf(b.Not())
            return b
        raise ValueError(f"Unsupported comparison op: {op}")

    def _select_records(self, select_spec: dict, env: dict) -> List[AssignmentRecord]:
        dims = select_spec.get("dims", {}) or {}
        day_range = select_spec.get("day_range")
        where = select_spec.get("where")

        days = None
        if day_range:
            days = self._resolve_day_range(day_range, env)
        elif "day" in dims:
            days = [self._resolve_day(dims["day"], env)]

        if days is None:
            records = list(self._assignment_records)
        else:
            records = []
            for d in days:
                records.extend(self._index_by_day.get(d, []))

        if "worker" in dims:
            w_id = self._resolve_worker_id(dims["worker"], env)
            records = [r for r in records if r.worker_id == w_id]

        if "shift" in dims:
            code = self._resolve_shift_code(dims["shift"], env)
            records = [r for r in records if r.shift_code == code]

        if where:
            filtered = []
            for r in records:
                ctx = {
                    "day": r.day,
                    "worker": r.worker,
                    "shift": r.shift,
                    "i": env.get("i", {}),
                }
                if evaluate(where, ctx):
                    filtered.append(r)
            records = filtered

        return records

    def _resolve_day(self, spec: dict, env: dict) -> date:
        source = spec.get("from")
        base = self._resolve_ref(source, env)
        if isinstance(base, dict) and "date_obj" in base:
            base_date = base["date_obj"]
        elif isinstance(base, dict) and "week_id" in base:
            base_date = base["week_id"]
        elif isinstance(base, date):
            base_date = base
        else:
            raise ValueError(f"Unsupported day reference: {source}")

        offset = spec.get("offset", 0)
        if isinstance(offset, int):
            return base_date + timedelta(days=offset)
        if offset == "next_saturday":
            return base_date + timedelta(days=6)
        if offset == "next_sunday":
            return base_date + timedelta(days=7)
        raise ValueError(f"Unsupported day offset: {offset}")

    def _resolve_day_range(self, spec: dict, env: dict) -> List[date]:
        if "from" in spec:
            base = self._resolve_ref(spec["from"], env)
            if isinstance(base, dict) and "days" in base:
                days = list(base["days"])
            elif isinstance(base, dict) and "date_obj" in base:
                days = self._window_days(spec.get("window"), base["date_obj"])
            elif isinstance(base, date):
                days = self._window_days(spec.get("window"), base)
            else:
                raise ValueError(f"Unsupported day_range base: {spec['from']}")
        else:
            days = list(self.calendar.dates)

        filter_name = spec.get("filter")
        if filter_name:
            days = [d for d in days if self._day_filter(filter_name, d)]
        return days

    def _window_days(self, window_name: str | None, anchor: date) -> List[date]:
        if window_name is None:
            return [anchor]
        if window_name == "weekdays_same_week":
            monday = self.calendar.get_week_id(anchor)
            return [
                d
                for d in (monday + timedelta(days=i) for i in range(5))
                if d in self.calendar.dates
            ]
        if window_name == "weekdays_week_of_and_after":
            monday = self.calendar.get_week_id(anchor)
            days = []
            for i in range(5):
                d = monday + timedelta(days=i)
                if d in self.calendar.dates:
                    days.append(d)
            monday_next = monday + timedelta(days=7)
            for i in range(5):
                d = monday_next + timedelta(days=i)
                if d in self.calendar.dates:
                    days.append(d)
            return days
        raise ValueError(f"Unknown window: {window_name}")

    def _day_filter(self, name: str, d: date) -> bool:
        if name == "weekdays_only":
            return d.weekday() < 5
        if name == "weekend_only":
            return d.weekday() >= 5
        if name == "holiday_only":
            return self.calendar.is_holiday(d)
        if name == "report_range_only":
            return self.calendar.is_in_report_range(d)
        raise ValueError(f"Unknown day filter: {name}")

    def _resolve_worker_id(self, spec: dict, env: dict) -> str:
        base = self._resolve_ref(spec.get("from"), env)
        if isinstance(base, dict) and "id" in base:
            return base["id"]
        if isinstance(base, str):
            return base
        raise ValueError(f"Unsupported worker reference: {spec}")

    def _resolve_shift_code(self, spec: dict, env: dict) -> str:
        base = self._resolve_ref(spec.get("from"), env)
        if isinstance(base, dict) and "code" in base:
            return base["code"]
        if isinstance(base, dict) and "from" in base:
            return base["from"]
        if isinstance(base, str):
            return base
        raise ValueError(f"Unsupported shift reference: {spec}")

    def _resolve_ref(self, ref: Any, env: dict) -> Any:
        if ref is None:
            return None
        if isinstance(ref, dict):
            return ref
        if not isinstance(ref, str):
            return ref
        return self._get_path(self._build_env_view(env), ref)

    def _resolve_var(self, path: str, env: dict, let_values: dict) -> Any:
        if path in let_values:
            return let_values[path]
        return self._get_path(self._build_env_view(env), path)

    def _build_env_view(self, env: dict) -> dict:
        view = {"i": env.get("i", {})}
        for key, value in env.get("i", {}).items():
            view[key] = value
        return view

    def _get_path(self, data: dict, path: str) -> Any:
        cur: Any = data
        for part in str(path).split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return None
        return cur

    def _get_rulebook_path(self, path: str) -> Any:
        cur: Any = self.rulebook_data
        for part in str(path).split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return None
        return cur

    def _eval_jsonlogic(self, logic: Any, env: dict) -> Any:
        view = self._build_env_view(env)
        return evaluate(logic, view)

    def _get_attr(self, obj: dict, attr: str) -> Any:
        return self._get_path(obj, attr.replace("shift.", ""))

    def _estimate_upper_bound(self, expr: Any, env: dict, let_values: dict) -> int:
        if isinstance(expr, (int, float, bool)):
            return int(abs(expr))
        if isinstance(expr, dict):
            if "const" in expr:
                return abs(int(expr["const"]))
            if "eval" in expr:
                target = expr["eval"]
                if isinstance(target, dict) and "var" in target:
                    target = self._resolve_var(target["var"], env, let_values)
                elif isinstance(target, str):
                    target = self._resolve_ref(target, env)
                if isinstance(target, dict):
                    return self._estimate_upper_bound(target, env, let_values)
                if isinstance(target, (int, float)):
                    return abs(int(target))
            if "with" in expr:
                payload = expr["with"]
                bindings = payload.get("bindings", {})
                saved = {}
                for key, ref in bindings.items():
                    saved[key] = env["i"].get(key)
                    env["i"][key] = self._resolve_ref(ref, env)
                try:
                    return self._estimate_upper_bound(payload["expr"], env, let_values)
                finally:
                    for key, value in saved.items():
                        if value is None:
                            env["i"].pop(key, None)
                        else:
                            env["i"][key] = value
            if "count_assignments" in expr:
                select = expr["count_assignments"]["select"]
                return len(self._select_records(select, env))
            if "sum_assignment_attr" in expr:
                payload = expr["sum_assignment_attr"]
                select = payload["select"]
                attr = payload["attr"]
                records = self._select_records(select, env)
                max_attr = 0
                for rec in records:
                    value = int(self._get_attr(rec.shift, attr))
                    if value > max_attr:
                        max_attr = value
                return len(records) * max_attr
            if "sum" in expr:
                return sum(
                    self._estimate_upper_bound(x, env, let_values)
                    for x in expr["sum"]
                )
            if "sub" in expr:
                a, b = expr["sub"]
                return (
                    self._estimate_upper_bound(a, env, let_values)
                    + self._estimate_upper_bound(b, env, let_values)
                )
            if "mul" in expr:
                a, b = expr["mul"]
                return (
                    self._estimate_upper_bound(a, env, let_values)
                    * self._estimate_upper_bound(b, env, let_values)
                )
        return 10_000_000

    def _new_int_var(self, lb: int, ub: int, prefix: str) -> cp_model.IntVar:
        name = self._var_name(prefix)
        return self.model.NewIntVar(lb, max(ub, lb), name)

    def _var_name(self, prefix: str) -> str:
        self._var_counter += 1
        return f"{prefix}_{self._var_counter}"
