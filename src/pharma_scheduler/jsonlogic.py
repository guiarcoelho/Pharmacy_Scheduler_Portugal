"""Minimal JSONLogic evaluator for config-driven rules.

This is intentionally small and safe (no eval). It supports a subset of JSONLogic
that is sufficient for:
- selecting which shifts exist on which days (`shift.allowed_when`)
- selecting which workers are eligible for which shifts (`worker.allowed_when`)
- filtering rulebook constraints (`constraints.yaml`)

Supported ops:
- `var`
- boolean: `and`, `or`, `!`
- comparisons: `==`, `!=`, `<`, `<=`, `>`, `>=`
- membership: `in`
"""

from __future__ import annotations

from typing import Any


def _get_var(path: Any, data: dict, default: Any = None) -> Any:
    if path is None:
        return data
    if isinstance(path, list):
        path = path[0] if path else None
    if path in (None, ""):
        return data
    cur = data
    for part in str(path).split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


def evaluate(rule: Any, data: dict) -> Any:
    if isinstance(rule, (int, float, str, bool)) or rule is None:
        return rule
    if isinstance(rule, list):
        return [evaluate(item, data) for item in rule]
    if not isinstance(rule, dict):
        return rule

    if "var" in rule:
        return _get_var(rule["var"], data)

    if len(rule) != 1:
        return rule

    op, args = next(iter(rule.items()))
    if not isinstance(args, list):
        args = [args]

    if op == "and":
        result = True
        for arg in args:
            result = evaluate(arg, data)
            if not result:
                return result
        return result

    if op == "or":
        for arg in args:
            result = evaluate(arg, data)
            if result:
                return result
        return result

    if op == "!":
        return not bool(evaluate(args[0], data))

    left = evaluate(args[0], data) if len(args) > 0 else None
    right = evaluate(args[1], data) if len(args) > 1 else None

    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    if op == ">=":
        return left >= right
    if op == "in":
        if isinstance(right, str):
            return str(left) in right
        if isinstance(right, (list, set, tuple)):
            return left in right
        return False

    return rule
