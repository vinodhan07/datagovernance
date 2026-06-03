"""
quality_engine.py
─────────────────
Runs data quality checks entirely in-memory.
Receives: list of row dicts (from MariaDB, never stored)
Returns:  list of QualityFinding objects

Adapted to work with store.py RuleOut dicts (string UUIDs, params dict).
"""

import re
from dataclasses import dataclass, field
from typing import Any, Optional


# ─── Result shape ─────────────────────────────────────────────────────────────

@dataclass
class QualityFinding:
    rule_id: str
    rule_name: str
    rule_type: str
    table_name: str
    column_name: str
    total_rows: int
    failed_rows: int
    score: float
    status: str          # "passed" | "failed" | "warning"
    severity: str        # "critical" | "warning" | "info"
    reason: str          # plain-English explanation for the frontend
    failed_samples: list = field(default_factory=list)  # up to 3 example bad values


# ─── Individual checkers ──────────────────────────────────────────────────────

def _null_check(rows: list[dict], column: str) -> tuple[int, list]:
    """Count rows where column is None or empty string."""
    failed = []
    for i, row in enumerate(rows):
        val = row.get(column)
        if val is None or str(val).strip() == "":
            failed.append({"row_index": i, "value": val})
    return len(failed), failed


def _range_check_explicit(
    rows: list[dict], column: str,
    min_val: Optional[float], max_val: Optional[float],
) -> tuple[int, list]:
    """Explicit min/max range check."""
    failed = []
    for i, row in enumerate(rows):
        val = row.get(column)
        if val is None:
            continue
        try:
            numeric = float(val)
            if min_val is not None and numeric < min_val:
                failed.append({"row_index": i, "value": val, "reason": f"< {min_val}"})
            elif max_val is not None and numeric > max_val:
                failed.append({"row_index": i, "value": val, "reason": f"> {max_val}"})
        except (TypeError, ValueError):
            continue
    return len(failed), failed


def _duplicate_check(rows: list[dict], column: str) -> tuple[int, list, dict]:
    """Find duplicate values in a column."""
    from collections import Counter
    values = [row.get(column) for row in rows if row.get(column) is not None]
    counts = Counter(values)
    duplicates = {val: count for val, count in counts.items() if count > 1}
    failed_count = sum(count - 1 for count in duplicates.values())
    failed_samples = [{"value": v, "occurrences": c} for v, c in list(duplicates.items())[:3]]
    return failed_count, failed_samples, duplicates


def _format_check(rows: list[dict], column: str, pattern: str) -> tuple[int, list]:
    """Check values against a regex pattern."""
    named_patterns = {
        "email":    r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$',
        "phone":    r'^\+?[\d\s\-\(\)]{7,15}$',
        "date":     r'^\d{4}-\d{2}-\d{2}$',
        "uuid":     r'^[0-9a-fA-F\-]{36}$',
        "url":      r'^https?://.+',
        "integer":  r'^\-?\d+$',
        "positive": r'^[1-9]\d*$',
    }
    regex = named_patterns.get(pattern, pattern)
    failed = []
    for i, row in enumerate(rows):
        val = row.get(column)
        if val is None:
            continue
        if not re.match(regex, str(val).strip()):
            failed.append({"row_index": i, "value": str(val)[:50]})
    return len(failed), failed


# ─── Reason builder ───────────────────────────────────────────────────────────

def _build_reason(
    rule_type: str, column: str, table: str,
    total: int, failed: int, samples: list,
    extra: dict = None,
) -> str:
    pct = round((failed / total * 100), 1) if total > 0 else 0
    extra = extra or {}

    if rule_type == "null_check":
        return (
            f"Column '{column}' has {failed} null or empty value(s) "
            f"out of {total} rows ({pct}% failure rate). "
            f"Expected: all values to be present and non-empty. "
            f"Table: '{table}'."
        )

    elif rule_type == "range_check":
        sample_vals = [str(s.get("value", "")) for s in samples[:3]]
        sample_str = ", ".join(sample_vals) if sample_vals else "—"
        min_v = extra.get("min_val", "")
        max_v = extra.get("max_val", "")
        range_desc = ""
        if min_v != "" and min_v is not None and max_v != "" and max_v is not None:
            range_desc = f"between {min_v} and {max_v}"
        elif min_v != "" and min_v is not None:
            range_desc = f"greater than or equal to {min_v}"
        elif max_v != "" and max_v is not None:
            range_desc = f"less than or equal to {max_v}"
        return (
            f"Column '{column}' has {failed} value(s) outside the allowed range ({range_desc}). "
            f"{pct}% of rows failed. "
            f"Example bad values: {sample_str}. "
            f"Table: '{table}'."
        )

    elif rule_type == "duplicate_check":
        dup_examples = [f"'{s['value']}' ({s['occurrences']}x)" for s in samples[:3]]
        dup_str = ", ".join(dup_examples) if dup_examples else "—"
        return (
            f"Column '{column}' has {failed} duplicate value(s) that should be unique. "
            f"Duplicated entries: {dup_str}. "
            f"Table: '{table}'."
        )

    elif rule_type == "format_check":
        pattern_name = extra.get("pattern", "the required pattern")
        sample_vals = [str(s.get("value", "")) for s in samples[:3]]
        sample_str = ", ".join(sample_vals) if sample_vals else "—"
        return (
            f"Column '{column}' has {failed} value(s) that do not match the expected format ({pattern_name}). "
            f"{pct}% of rows failed. "
            f"Example invalid values: {sample_str}. "
            f"Table: '{table}'."
        )

    return f"Column '{column}' failed {rule_type} check. {failed} of {total} rows affected."


# ─── Score & status ───────────────────────────────────────────────────────────

def _score(total: int, failed: int) -> float:
    if total == 0:
        return 100.0
    return round((total - failed) / total * 100, 2)


def _status(score: float, severity: str) -> str:
    if score == 100.0:
        return "passed"
    if severity == "critical" and score < 100.0:
        return "failed"
    if score >= 80:
        return "warning"
    return "failed"


# ─── Main entry point ─────────────────────────────────────────────────────────

def run_quality_checks(
    rules: list[dict],
    table_data: dict[str, list[dict]],
) -> list[QualityFinding]:
    """
    rules       — list of rule dicts from store.py (RuleOut.model_dump())
                   Keys: id, name, rule_type, table_name, column_name,
                         severity, params (dict)
    table_data  — { "employees": [{...}, ...], "orders": [...] }
    Returns list of QualityFinding (never touches DB).
    """
    findings = []

    for rule in rules:
        rows = table_data.get(rule["table_name"], [])
        total = len(rows)

        if total == 0:
            findings.append(QualityFinding(
                rule_id=rule["id"],
                rule_name=rule["name"],
                rule_type=rule["rule_type"],
                table_name=rule["table_name"],
                column_name=rule["column_name"],
                total_rows=0,
                failed_rows=0,
                score=100.0,
                status="passed",
                severity=rule["severity"],
                reason=f"Table '{rule['table_name']}' is empty — no rows to check.",
                failed_samples=[],
            ))
            continue

        failed_count = 0
        samples = []
        extra = {}
        params = rule.get("params", {})
        rtype = rule["rule_type"]

        # ── Run the right check ──────────────────────────────────────────
        if rtype == "null_check":
            failed_count, samples = _null_check(rows, rule["column_name"])

        elif rtype == "range_check":
            min_v = params.get("min")
            max_v = params.get("max")
            extra = {"min_val": min_v, "max_val": max_v}
            failed_count, samples = _range_check_explicit(
                rows, rule["column_name"], min_v, max_v,
            )

        elif rtype == "duplicate_check":
            failed_count, samples, _ = _duplicate_check(rows, rule["column_name"])

        elif rtype == "format_check":
            pattern = params.get("pattern", "email")
            extra = {"pattern": pattern}
            failed_count, samples = _format_check(
                rows, rule["column_name"], pattern,
            )

        # ── Build result ─────────────────────────────────────────────────
        sc = _score(total, failed_count)
        st = _status(sc, rule["severity"])
        reason = _build_reason(
            rtype, rule["column_name"], rule["table_name"],
            total, failed_count, samples[:3], extra,
        )

        findings.append(QualityFinding(
            rule_id=rule["id"],
            rule_name=rule["name"],
            rule_type=rtype,
            table_name=rule["table_name"],
            column_name=rule["column_name"],
            total_rows=total,
            failed_rows=failed_count,
            score=sc,
            status=st,
            severity=rule["severity"],
            reason=reason,
            failed_samples=samples[:3],
        ))

    return findings
