"""
Data Quality router.

Rules are stored in-memory (store.py).
Scan results (findings only — no actual row data) are written to PostgreSQL.

Privacy contract:
  - We query MariaDB to count failures, never to read individual values.
  - 'reason' strings contain only counts, column names, and rule descriptions.
  - 'findings' JSON contains only aggregate stats (min, max, null_count, etc.).
  - No individual cell values, names, emails, or PII ever reach PostgreSQL.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone

import pymysql
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

import store
from database import get_db
from models import QualityScanResult
from schemas import RuleCreate

router = APIRouter()


# ─── Rules ────────────────────────────────────────────────────────────────────

@router.get("/rules")
def get_rules():
    return store.list_rules()


@router.post("/rules", status_code=201)
def add_rule(data: RuleCreate):
    return store.create_rule(data)


# ─── Scan engine ──────────────────────────────────────────────────────────────

def _open_mariadb(integration: dict):
    creds = integration.get("credentials", {})
    return pymysql.connect(
        host=creds.get("host", "localhost"),
        port=int(creds.get("port", 3306)),
        user=creds.get("user", ""),
        password=creds.get("password", ""),
        database=creds.get("database", ""),
        connect_timeout=10,
    )


def _run_null_check(cursor, table: str, column: str, rule: dict) -> dict:
    safe_t = table.replace("`", "")
    safe_c = column.replace("`", "")
    cursor.execute(f"SELECT COUNT(*) FROM `{safe_t}`")
    total = cursor.fetchone()[0]
    cursor.execute(f"SELECT COUNT(*) FROM `{safe_t}` WHERE `{safe_c}` IS NULL")
    nulls = cursor.fetchone()[0]
    failed = nulls
    score = round(((total - failed) / total * 100) if total else 100.0, 1)
    status = "passed" if failed == 0 else ("failed" if rule.get("severity") == "critical" else "warning")
    reason = (
        f"Column '{column}' has {nulls} null value(s) out of {total} rows. "
        f"This violates the 'not null' rule. Affected table: {table}."
        if failed else None
    )
    return {"total": total, "failed": failed, "score": score, "status": status,
            "reason": reason, "findings": {"null_count": nulls, "total_rows": total}}


def _run_range_check(cursor, table: str, column: str, rule: dict) -> dict:
    safe_t = table.replace("`", "")
    safe_c = column.replace("`", "")
    params = rule.get("params", {})
    min_val = params.get("min")
    max_val = params.get("max")

    cursor.execute(f"SELECT COUNT(*) FROM `{safe_t}`")
    total = cursor.fetchone()[0]

    conditions = []
    if min_val is not None:
        conditions.append(f"`{safe_c}` < {float(min_val)}")
    if max_val is not None:
        conditions.append(f"`{safe_c}` > {float(max_val)}")

    if not conditions:
        return {"total": total, "failed": 0, "score": 100.0, "status": "passed",
                "reason": None, "findings": {"total_rows": total}}

    where = " OR ".join(conditions)
    cursor.execute(f"SELECT COUNT(*) FROM `{safe_t}` WHERE {where}")
    failed = cursor.fetchone()[0]

    cursor.execute(f"SELECT MIN(`{safe_c}`), MAX(`{safe_c}`) FROM `{safe_t}`")
    row = cursor.fetchone()
    col_min, col_max = (str(row[0]) if row[0] is not None else None,
                        str(row[1]) if row[1] is not None else None)

    score = round(((total - failed) / total * 100) if total else 100.0, 1)
    status = "passed" if failed == 0 else ("failed" if rule.get("severity") == "critical" else "warning")
    range_desc = f"[{min_val}, {max_val}]" if min_val is not None and max_val is not None else (
        f">= {min_val}" if min_val is not None else f"<= {max_val}"
    )
    reason = (
        f"Column '{column}' has {failed} value(s) outside the expected range {range_desc}. "
        f"Actual range in table: min={col_min}, max={col_max}. Affected table: {table}."
        if failed else None
    )
    return {"total": total, "failed": failed, "score": score, "status": status,
            "reason": reason, "findings": {"out_of_range_count": failed, "col_min": col_min,
                                            "col_max": col_max, "total_rows": total}}


def _run_format_check(cursor, table: str, column: str, rule: dict) -> dict:
    safe_t = table.replace("`", "")
    safe_c = column.replace("`", "")
    params = rule.get("params", {})
    pattern = params.get("pattern", "")

    cursor.execute(f"SELECT COUNT(*) FROM `{safe_t}`")
    total = cursor.fetchone()[0]

    if not pattern:
        return {"total": total, "failed": 0, "score": 100.0, "status": "passed",
                "reason": None, "findings": {"total_rows": total}}

    cursor.execute(
        f"SELECT COUNT(*) FROM `{safe_t}` WHERE `{safe_c}` IS NOT NULL AND `{safe_c}` NOT REGEXP %s",
        (pattern,),
    )
    failed = cursor.fetchone()[0]
    score = round(((total - failed) / total * 100) if total else 100.0, 1)
    status = "passed" if failed == 0 else ("failed" if rule.get("severity") == "critical" else "warning")
    reason = (
        f"Column '{column}' has {failed} value(s) that do not match the expected format '{pattern}'. "
        f"Affected table: {table}."
        if failed else None
    )
    return {"total": total, "failed": failed, "score": score, "status": status,
            "reason": reason, "findings": {"format_violations": failed, "pattern": pattern,
                                            "total_rows": total}}


def _run_duplicate_check(cursor, table: str, column: str, rule: dict) -> dict:
    safe_t = table.replace("`", "")
    safe_c = column.replace("`", "")

    cursor.execute(f"SELECT COUNT(*) FROM `{safe_t}`")
    total = cursor.fetchone()[0]

    cursor.execute(
        f"SELECT COUNT(*) FROM (SELECT `{safe_c}` FROM `{safe_t}` "
        f"WHERE `{safe_c}` IS NOT NULL GROUP BY `{safe_c}` HAVING COUNT(*) > 1) t"
    )
    dup_values = cursor.fetchone()[0]

    cursor.execute(
        f"SELECT SUM(cnt - 1) FROM (SELECT COUNT(*) AS cnt FROM `{safe_t}` "
        f"WHERE `{safe_c}` IS NOT NULL GROUP BY `{safe_c}` HAVING COUNT(*) > 1) t"
    )
    row = cursor.fetchone()
    failed = int(row[0]) if row[0] else 0

    score = round(((total - failed) / total * 100) if total else 100.0, 1)
    status = "passed" if failed == 0 else ("failed" if rule.get("severity") == "critical" else "warning")
    reason = (
        f"Column '{column}' has {dup_values} duplicate value(s) ({failed} duplicate rows). "
        f"All values should be unique. Affected table: {table}."
        if failed else None
    )
    return {"total": total, "failed": failed, "score": score, "status": status,
            "reason": reason, "findings": {"duplicate_values": dup_values,
                                            "duplicate_rows": failed, "total_rows": total}}


_CHECKERS = {
    "null_check": _run_null_check,
    "range_check": _run_range_check,
    "format_check": _run_format_check,
    "duplicate_check": _run_duplicate_check,
}


@router.post("/scan/{integration_id}")
def run_scan(integration_id: str, db: Session = Depends(get_db)):
    integration = store.get_integration(integration_id)
    if not integration:
        raise HTTPException(404, "Integration not found")

    rules = store.list_rules()
    if not rules:
        raise HTTPException(400, "No quality rules defined. Add rules first.")

    batch_id = str(uuid.uuid4())
    scanned_at = datetime.now(timezone.utc)
    results = []

    try:
        conn = _open_mariadb(integration)
        cursor = conn.cursor()
    except Exception as exc:
        raise HTTPException(500, f"Cannot connect to MariaDB: {exc}")

    try:
        for rule in rules:
            checker = _CHECKERS.get(rule["rule_type"])
            if not checker:
                continue
            try:
                outcome = checker(cursor, rule["table_name"], rule["column_name"], rule)
            except Exception as exc:
                outcome = {
                    "total": 0, "failed": 0, "score": 0.0, "status": "failed",
                    "reason": f"Scan error: {exc}",
                    "findings": {"error": str(exc)},
                }

            # Write findings to PostgreSQL — no raw MariaDB row data
            db_record = QualityScanResult(
                id=str(uuid.uuid4()),
                integration_id=integration_id,
                integration_name=integration.get("name"),
                rule_id=rule["id"],
                rule_name=rule["name"],
                rule_type=rule["rule_type"],
                table_name=rule["table_name"],
                column_name=rule["column_name"],
                severity=rule["severity"],
                score=outcome["score"],
                status=outcome["status"],
                failed_rows=outcome["failed"],
                total_rows=outcome["total"],
                reason=outcome["reason"],
                findings=outcome["findings"],
                scanned_at=scanned_at,
                scan_batch_id=batch_id,
            )
            db.add(db_record)
            results.append(db_record)
    finally:
        cursor.close()
        conn.close()

    db.commit()
    for r in results:
        db.refresh(r)

    scores = [r.score for r in results]
    overall = round(sum(scores) / len(scores), 1) if scores else 100.0

    return {
        "scan_batch_id": batch_id,
        "integration_id": integration_id,
        "overall_score": overall,
        "scanned_at": scanned_at.isoformat(),
        "results": [
            {
                "id": str(r.id),
                "rule_id": r.rule_id,
                "rule_name": r.rule_name,
                "rule_type": r.rule_type,
                "table_name": r.table_name,
                "column_name": r.column_name,
                "severity": r.severity,
                "score": r.score,
                "status": r.status,
                "failed_rows": r.failed_rows,
                "total_rows": r.total_rows,
                "reason": r.reason,
                "findings": r.findings,
                "scanned_at": r.scanned_at.isoformat(),
                "scan_batch_id": r.scan_batch_id,
            }
            for r in results
        ],
    }


@router.get("/scan-history")
def scan_history(integration_id: str | None = None, db: Session = Depends(get_db)):
    q = db.query(QualityScanResult)
    if integration_id:
        q = q.filter(QualityScanResult.integration_id == integration_id)
    records = q.order_by(QualityScanResult.scanned_at.desc()).limit(200).all()
    return [
        {
            "id": str(r.id),
            "integration_id": r.integration_id,
            "integration_name": r.integration_name,
            "rule_id": r.rule_id,
            "rule_name": r.rule_name,
            "rule_type": r.rule_type,
            "table_name": r.table_name,
            "column_name": r.column_name,
            "severity": r.severity,
            "score": r.score,
            "status": r.status,
            "failed_rows": r.failed_rows,
            "total_rows": r.total_rows,
            "reason": r.reason,
            "findings": r.findings,
            "scanned_at": r.scanned_at.isoformat(),
            "scan_batch_id": r.scan_batch_id,
        }
        for r in records
    ]
