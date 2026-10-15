"""Rule engine for excluding chemically-impossible reaction conditions.

A rule is an AND-combination of clauses. A candidate (a component-value dict) is
*excluded* if it matches ALL clauses of ANY active rule.

Rule shape (stored as JSON on the project)::

    {
      "id": "...", "name": "水相不可高温", "active": true,
      "clauses": [
        {"component": "solvent_SMILES", "op": "eq", "value": "O"},
        {"component": "temperature",    "op": "ge", "value": 100}
      ]
    }

Supported ops: eq, ne, in, nin, ge, le, gt, lt.
"""
from __future__ import annotations

from typing import Any


def _norm(v: Any) -> str:
    try:
        f = float(v)
        return str(int(f)) if f.is_integer() else str(f)
    except (TypeError, ValueError):
        return str(v)


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def clause_matches(components: dict, clause: dict) -> bool:
    comp = clause.get("component")
    op = (clause.get("op") or "eq").lower()
    target = clause.get("value")
    if comp not in components:
        return False
    actual = components[comp]

    if op == "eq":
        return _norm(actual) == _norm(target)
    if op == "ne":
        return _norm(actual) != _norm(target)
    if op in ("in", "nin"):
        vals = target if isinstance(target, (list, tuple)) else [target]
        hit = _norm(actual) in {_norm(v) for v in vals}
        return hit if op == "in" else not hit
    # numeric comparisons
    a, t = _num(actual), _num(target)
    if a is None or t is None:
        return False
    if op == "ge":
        return a >= t
    if op == "le":
        return a <= t
    if op == "gt":
        return a > t
    if op == "lt":
        return a < t
    return False


def rule_matches(components: dict, rule: dict) -> bool:
    clauses = rule.get("clauses") or []
    if not clauses:
        return False
    return all(clause_matches(components, c) for c in clauses)


def is_excluded(components: dict, rules: list[dict] | None) -> bool:
    for rule in rules or []:
        if rule.get("active", True) and rule_matches(components, rule):
            return True
    return False


def matched_rules(components: dict, rules: list[dict] | None) -> list[str]:
    """Names/ids of active rules that this candidate violates."""
    out = []
    for rule in rules or []:
        if rule.get("active", True) and rule_matches(components, rule):
            out.append(rule.get("name") or rule.get("id") or "rule")
    return out
