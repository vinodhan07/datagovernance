"""
quality.py — Data Quality endpoints powered by Soda Core.

Rules are stored in PostgreSQL. Scans are triggered on-demand and stream
progress back via Server-Sent Events (same pattern as pipeline.py).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database import get_db
from models import QualityRule, QualityScan, QualityFinding
from schemas import (
    QualityRuleCreate, QualityRuleOut,
    QualityScanOut, QualityScanDetailOut, QualityFindingOut,
    QualityScoreOut,
)
from engines.soda_scanner import build_sodacl_yaml, run_scan

logger = logging.getLogger("dataguard.quality")
router = APIRouter()


# ── SSE helper (mirrors pipeline.py) ─────────────────────────────────────────

def _event(level: str, msg: str) -> str:
    ts = datetime.now().strftime("%H:%M:%S")
    return f"data: {json.dumps({'level': level, 'msg': msg, 'ts': ts})}\n\n"


# ── Rules CRUD ────────────────────────────────────────────────────────────────

@router.get("/rules", response_model=list[QualityRuleOut])
def get_rules(integration_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(QualityRule)
    if integration_id:
        q = q.filter(QualityRule.integration_id == integration_id)
    return q.order_by(QualityRule.created_at.desc()).all()


@router.post("/rules", response_model=QualityRuleOut, status_code=201)
def create_rule(data: QualityRuleCreate, db: Session = Depends(get_db)):
    """Create a new SodaCL check rule for a table/column."""
    # Build check YAML snippet for display
    if data.column_name:
        yaml_line = f"- {data.check_type}({data.column_name}) {data.threshold}"
    else:
        yaml_line = f"- {data.check_type} {data.threshold}"
    check_yaml = f"checks for {data.table_name}:\n  {yaml_line}"

    rule = QualityRule(
        integration_id=data.integration_id,
        table_name=data.table_name,
        column_name=data.column_name,
        check_type=data.check_type,
        threshold=data.threshold,
        check_yaml=check_yaml,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.query(QualityRule).filter(QualityRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Rule not found")
    db.delete(rule)
    db.commit()


# ── Scan (SSE stream) ─────────────────────────────────────────────────────────

@router.get("/scan/{integration_id}")
async def trigger_scan(integration_id: str, db: Session = Depends(get_db)):
    """
    Run a Soda Core scan for all quality rules associated with this integration.
    Streams progress events as SSE and persists results to PostgreSQL.
    """
    return StreamingResponse(
        _scan_sse(integration_id, db),
        media_type="text/event-stream",
    )


async def _scan_sse(integration_id: str, db: Session):
    scan_record = None
    try:
        yield _event("INFO", "Initialising quality scan...")

        rules = (
            db.query(QualityRule)
            .filter(QualityRule.integration_id == integration_id)
            .all()
        )

        if not rules:
            yield _event("INFO", "No rules defined. Auto-generating default rules for available tables...")
            from models import LineageDataset, LineageJob
            datasets = (
                db.query(LineageDataset)
                .join(LineageJob, LineageDataset.job_id == LineageJob.id)
                .filter(LineageJob.integration_id == integration_id)
                .all()
            )
            seen_tables = set()
            for ds in datasets:
                if ds.name in seen_tables:
                    continue
                seen_tables.add(ds.name)
                rule = QualityRule(
                    integration_id=integration_id,
                    table_name=ds.name,
                    check_type="row_count",
                    threshold="> 0",
                    check_yaml=f"checks for {ds.name}:\n  - row_count > 0"
                )
                db.add(rule)
            
            if seen_tables:
                db.commit()
                rules = db.query(QualityRule).filter(QualityRule.integration_id == integration_id).all()
                yield _event("INFO", f"Auto-generated {len(rules)} basic row_count rules.")
            else:
                yield _event("WARNING", "No quality rules defined and no tables found in lineage to generate rules.")
                yield _event("DONE", "No rules to scan — run ETL pipeline first")
                return

        yield _event("INFO", f"Found {len(rules)} rule(s) across "
                     f"{len(set(r.table_name for r in rules))} table(s)")

        # Create scan record
        scan_record = QualityScan(integration_id=integration_id, status="running")
        db.add(scan_record)
        db.commit()
        db.refresh(scan_record)

        yield _event("INFO", "Building SodaCL checks YAML...")
        yaml_str = build_sodacl_yaml(rules)
        for line in yaml_str.splitlines():
            if line.strip():
                yield _event("DEBUG", f"  {line}")

        yield _event("INFO", "Connecting to PostgreSQL company_data database...")
        yield _event("INFO", "Running Soda Core scan...")

        result = run_scan(rules)

        total   = result["checks_total"]
        passed  = result["checks_passed"]
        failed  = result["checks_failed"]
        score   = result["score"]
        findings_data = result["findings"]

        yield _event("OK", f"Scan complete: {passed}/{total} checks passed — score {score}%")

        # Log individual findings
        for f in findings_data:
            icon  = "✓" if f["status"] == "pass" else "✗"
            col   = f"({f['column_name']})" if f.get("column_name") else ""
            yield _event(
                "OK" if f["status"] == "pass" else "ERROR",
                f"[{f['table_name']}] {icon} {f['check_type']}{col}: {f['value']} [{f['status'].upper()}]",
            )

        # Persist findings
        for f in findings_data:
            db.add(QualityFinding(
                scan_id=scan_record.id,
                table_name=f["table_name"],
                column_name=f.get("column_name"),
                check_type=f.get("check_type"),
                status=f.get("status"),
                value=f.get("value"),
            ))

        # Update scan record
        db.query(QualityScan).filter(QualityScan.id == scan_record.id).update({
            "status": "completed",
            "score": score,
            "completed_at": datetime.now(timezone.utc),
            "result_json": json.dumps(result["findings"]),
        })
        db.commit()

        yield _event("DONE", f"Quality scan saved — overall score: {score}%")

    except Exception as exc:
        logger.error("Quality scan failed: %s", exc, exc_info=True)
        if scan_record:
            db.query(QualityScan).filter(QualityScan.id == scan_record.id).update({
                "status": "failed",
                "completed_at": datetime.now(timezone.utc),
            })
            db.commit()
        yield _event("ERROR", f"Scan failed: {exc}")


# ── Scan history ──────────────────────────────────────────────────────────────

@router.get("/scans", response_model=list[QualityScanOut])
def list_scans(integration_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(QualityScan)
    if integration_id:
        q = q.filter(QualityScan.integration_id == integration_id)
    return q.order_by(QualityScan.started_at.desc()).limit(50).all()


@router.get("/scans/{scan_id}", response_model=QualityScanDetailOut)
def get_scan_detail(scan_id: int, db: Session = Depends(get_db)):
    scan = db.query(QualityScan).filter(QualityScan.id == scan_id).first()
    if not scan:
        raise HTTPException(404, "Scan not found")
    findings = db.query(QualityFinding).filter(QualityFinding.scan_id == scan_id).all()
    return QualityScanDetailOut(
        id=scan.id,
        integration_id=scan.integration_id,
        status=scan.status,
        score=scan.score,
        started_at=scan.started_at,
        completed_at=scan.completed_at,
        findings=[QualityFindingOut.model_validate(f) for f in findings],
    )


# ── Score ─────────────────────────────────────────────────────────────────────

@router.get("/score/{integration_id}", response_model=QualityScoreOut)
def get_quality_score(integration_id: str, db: Session = Depends(get_db)):
    """Return the latest completed scan score for an integration."""
    scan = (
        db.query(QualityScan)
        .filter(
            QualityScan.integration_id == integration_id,
            QualityScan.status == "completed",
        )
        .order_by(QualityScan.started_at.desc())
        .first()
    )
    if not scan:
        return QualityScoreOut(integration_id=integration_id)
    return QualityScoreOut(
        integration_id=integration_id,
        score=scan.score,
        scan_id=scan.id,
        scanned_at=scan.completed_at or scan.started_at,
    )
