"""
audit.py
────────
Append-only audit trail of all governance actions.

Endpoints:
  GET /audit/logs                      — paginated log, newest first
  GET /audit/logs/{integration_id}     — filtered to one integration

Helper (called from other routers):
  log_audit(db, event_type, description, ...)

Events logged:
  CONNECT            — integration connected / connection tested
  FETCH_STARTED      — pipeline fetch begins
  FETCH_COMPLETED    — pipeline done (quality score stored)
  SCAN_TRIGGERED     — full scan manually triggered
  SCAN_COMPLETED     — scan finished
  SCAN_FAILED        — scan errored
  RULE_CREATED       — new quality rule added
  TEMPLATE_CREATED   — new connector template added

Privacy: metadata JSON must never contain raw row values.
"""

import csv
import io
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database import SessionLocal, is_db_available
from models import AuditLog

router = APIRouter()


# ─── Shared helper ─────────────────────────────────────────────────────────────

def log_audit(
    db: Session,
    event_type: str,
    description: str,
    integration_id: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    metadata: dict | None = None,
    status: str = "success",
) -> None:
    """
    Write one audit log entry. Call this from any router after significant actions.
    Silently skips if DB is unavailable.
    """
    if not is_db_available():
        return
    try:
        db.add(AuditLog(
            event_type=event_type,
            integration_id=integration_id,
            entity_type=entity_type,
            entity_id=entity_id,
            description=description,
            event_metadata=metadata,
            status=status,
        ))
        db.commit()
    except Exception:
        db.rollback()


# ─── Serialiser ────────────────────────────────────────────────────────────────

def _serialize(entry: AuditLog) -> dict:
    return {
        "id": entry.id,
        "event_type": entry.event_type,
        "integration_id": entry.integration_id,
        "entity_type": entry.entity_type,
        "entity_id": entry.entity_id,
        "description": entry.description,
        "metadata": entry.event_metadata or {},
        "status": entry.status,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


# ─── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/logs")
def list_audit_logs(
    integration_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """
    Return paginated audit log, newest first.
    Optional filters: integration_id, event_type.
    """
    if not is_db_available():
        return {"logs": [], "total": 0}

    db = SessionLocal()
    try:
        q = db.query(AuditLog).order_by(AuditLog.created_at.desc())
        if integration_id:
            q = q.filter(AuditLog.integration_id == integration_id)
        if event_type:
            # Support prefix match: "FETCH" matches FETCH_STARTED and FETCH_COMPLETED
            q = q.filter(AuditLog.event_type.like(f"{event_type.upper()}%"))
        total = q.count()
        logs = q.offset(offset).limit(limit).all()
        return {
            "logs": [_serialize(e) for e in logs],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    finally:
        db.close()


@router.get("/logs/{integration_id}")
def get_integration_audit_log(
    integration_id: str,
    limit: int = Query(100, ge=1, le=500),
):
    """Return the full audit trail for one integration, newest first."""
    if not is_db_available():
        return {"integration_id": integration_id, "logs": []}

    db = SessionLocal()
    try:
        logs = (
            db.query(AuditLog)
            .filter(AuditLog.integration_id == integration_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .all()
        )
        return {
            "integration_id": integration_id,
            "logs": [_serialize(e) for e in logs],
        }
    finally:
        db.close()


@router.get("/export")
def export_audit_csv(
    integration_id: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
):
    """
    Download all matching audit log entries as a CSV file.
    Date format: YYYY-MM-DD
    """
    if not is_db_available():
        return StreamingResponse(
            iter(["id,event_type,description,status,created_at\n"]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=audit_export.csv"},
        )

    db = SessionLocal()
    try:
        q = db.query(AuditLog).order_by(AuditLog.created_at.desc())
        if integration_id:
            q = q.filter(AuditLog.integration_id == integration_id)
        if from_date:
            try:
                dt_from = datetime.fromisoformat(from_date).replace(tzinfo=timezone.utc)
                q = q.filter(AuditLog.created_at >= dt_from)
            except ValueError:
                pass
        if to_date:
            try:
                dt_to = datetime.fromisoformat(to_date).replace(tzinfo=timezone.utc)
                q = q.filter(AuditLog.created_at <= dt_to)
            except ValueError:
                pass

        entries = q.limit(5000).all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "event_type", "integration_id", "entity_type",
                          "description", "status", "created_at"])
        for e in entries:
            writer.writerow([
                e.id, e.event_type, e.integration_id or "",
                e.entity_type or "", e.description or "",
                e.status, e.created_at.isoformat() if e.created_at else "",
            ])
        output.seek(0)
        return StreamingResponse(
            iter([output.read()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=audit_export.csv"},
        )
    finally:
        db.close()
