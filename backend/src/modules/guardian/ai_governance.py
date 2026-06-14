"""
ai_governance.py
────────────────
GenAI Governance — Model Registry, Risk Assessment, Compliance Checks.

Endpoints:
  GET    /ai-governance/models                    — list all registered AI models
  POST   /ai-governance/models                    — register a new model
  PUT    /ai-governance/models/{id}               — update model details / status
  DELETE /ai-governance/models/{id}               — remove a model
  GET    /ai-governance/models/{id}/compliance    — list compliance checks for a model
  POST   /ai-governance/models/{id}/compliance    — add / update a compliance check
  DELETE /ai-governance/compliance/{check_id}     — remove a compliance check
  GET    /ai-governance/summary                   — dashboard stats (counts, risk breakdown)
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.domain.entities import AIModel, AIComplianceCheck
from src.modules.observer.audit import log_audit

router = APIRouter()


# ── Helpers ────────────────────────────────────────────────────────────────────

RISK_ORDER = {"minimal": 0, "limited": 1, "high": 2, "unacceptable": 3}

def _model_out(m: AIModel) -> dict:
    return {
        "id":             m.id,
        "name":           m.name,
        "provider":       m.provider,
        "model_type":     m.model_type,
        "version":        m.version,
        "purpose":        m.purpose,
        "owner":          m.owner,
        "risk_level":     m.risk_level or "minimal",
        "status":         m.status or "active",
        "uses_pii":       bool(m.uses_pii),
        "autonomous":     bool(m.autonomous),
        "integration_id": m.integration_id,
        "created_at":     m.created_at.isoformat() if m.created_at else None,
        "updated_at":     m.updated_at.isoformat() if m.updated_at else None,
    }

def _check_out(c: AIComplianceCheck) -> dict:
    return {
        "id":           c.id,
        "model_id":     c.model_id,
        "check_name":   c.check_name,
        "check_status": c.check_status or "pending",
        "notes":        c.notes,
        "checked_at":   c.checked_at.isoformat() if c.checked_at else None,
        "created_at":   c.created_at.isoformat() if c.created_at else None,
    }


# ── Model Registry ─────────────────────────────────────────────────────────────

@router.get("/models")
def list_models(db: Session = Depends(get_db)):
    models = db.query(AIModel).order_by(AIModel.created_at.desc()).all()
    return [_model_out(m) for m in models]


@router.post("/models", status_code=201)
def register_model(data: dict, db: Session = Depends(get_db)):
    if not data.get("name"):
        raise HTTPException(400, "name is required")
    model = AIModel(
        name           = data["name"],
        provider       = data.get("provider"),
        model_type     = data.get("model_type"),
        version        = data.get("version"),
        purpose        = data.get("purpose"),
        owner          = data.get("owner"),
        risk_level     = data.get("risk_level", "minimal"),
        status         = data.get("status", "active"),
        uses_pii       = bool(data.get("uses_pii")),
        autonomous     = bool(data.get("autonomous")),
        integration_id = data.get("integration_id"),
    )
    db.add(model)
    db.commit()
    db.refresh(model)

    log_audit(
        db,
        event_type   = "AI_MODEL_REGISTERED",
        description  = f"AI model registered: {model.name} ({model.provider or 'unknown provider'})",
        entity_type  = "ai_model",
        entity_id    = str(model.id),
        metadata     = {"name": model.name, "risk_level": model.risk_level},
    )
    return _model_out(model)


@router.put("/models/{model_id}")
def update_model(model_id: int, data: dict, db: Session = Depends(get_db)):
    model = db.query(AIModel).filter(AIModel.id == model_id).first()
    if not model:
        raise HTTPException(404, "Model not found")

    updatable = ["name", "provider", "model_type", "version", "purpose",
                 "owner", "risk_level", "status", "integration_id"]
    for field in updatable:
        if field in data:
            setattr(model, field, data[field])
    if "uses_pii" in data:
        model.uses_pii = bool(data["uses_pii"])
    if "autonomous" in data:
        model.autonomous = bool(data["autonomous"])

    db.commit()
    db.refresh(model)

    log_audit(
        db,
        event_type  = "AI_MODEL_UPDATED",
        description = f"AI model updated: {model.name}",
        entity_type = "ai_model",
        entity_id   = str(model.id),
        metadata    = {"status": model.status, "risk_level": model.risk_level},
    )
    return _model_out(model)


@router.delete("/models/{model_id}", status_code=204)
def delete_model(model_id: int, db: Session = Depends(get_db)):
    model = db.query(AIModel).filter(AIModel.id == model_id).first()
    if not model:
        raise HTTPException(404, "Model not found")
    name = model.name
    db.query(AIComplianceCheck).filter(AIComplianceCheck.model_id == model_id).delete()
    db.delete(model)
    db.commit()
    log_audit(
        db,
        event_type  = "AI_MODEL_REMOVED",
        description = f"AI model removed: {name}",
        entity_type = "ai_model",
        entity_id   = str(model_id),
    )


# ── Compliance Checks ──────────────────────────────────────────────────────────

@router.get("/models/{model_id}/compliance")
def list_compliance(model_id: int, db: Session = Depends(get_db)):
    checks = (db.query(AIComplianceCheck)
               .filter(AIComplianceCheck.model_id == model_id)
               .order_by(AIComplianceCheck.created_at.asc())
               .all())
    return [_check_out(c) for c in checks]


@router.post("/models/{model_id}/compliance", status_code=201)
def add_compliance_check(model_id: int, data: dict, db: Session = Depends(get_db)):
    model = db.query(AIModel).filter(AIModel.id == model_id).first()
    if not model:
        raise HTTPException(404, "Model not found")
    if not data.get("check_name"):
        raise HTTPException(400, "check_name is required")

    check = AIComplianceCheck(
        model_id     = model_id,
        check_name   = data["check_name"],
        check_status = data.get("check_status", "pending"),
        notes        = data.get("notes"),
        checked_at   = datetime.now(timezone.utc) if data.get("check_status") in ("pass", "fail") else None,
    )
    db.add(check)
    db.commit()
    db.refresh(check)

    log_audit(
        db,
        event_type  = "AI_COMPLIANCE_CHECKED",
        description = f"Compliance check '{check.check_name}' → {check.check_status} for model: {model.name}",
        entity_type = "ai_compliance_check",
        entity_id   = str(check.id),
        metadata    = {"model_id": model_id, "check_name": check.check_name, "status": check.check_status},
    )
    return _check_out(check)


@router.put("/compliance/{check_id}")
def update_compliance_check(check_id: int, data: dict, db: Session = Depends(get_db)):
    check = db.query(AIComplianceCheck).filter(AIComplianceCheck.id == check_id).first()
    if not check:
        raise HTTPException(404, "Check not found")

    model = db.query(AIModel).filter(AIModel.id == check.model_id).first()

    if "check_status" in data:
        check.check_status = data["check_status"]
        if data["check_status"] in ("pass", "fail"):
            check.checked_at = datetime.now(timezone.utc)
        else:
            check.checked_at = None
    if "notes" in data:
        check.notes = data["notes"]
    if "check_name" in data:
        check.check_name = data["check_name"]

    db.commit()
    db.refresh(check)

    if "check_status" in data and model:
        log_audit(
            db,
            event_type  = "AI_COMPLIANCE_CHECKED",
            description = f"Compliance check '{check.check_name}' updated → {check.check_status} for model: {model.name}",
            entity_type = "ai_compliance_check",
            entity_id   = str(check.id),
            metadata    = {"model_id": model.id, "check_name": check.check_name, "status": check.check_status},
        )
    return _check_out(check)


@router.delete("/compliance/{check_id}", status_code=204)
def delete_compliance_check(check_id: int, db: Session = Depends(get_db)):
    check = db.query(AIComplianceCheck).filter(AIComplianceCheck.id == check_id).first()
    if not check:
        raise HTTPException(404, "Check not found")
    
    check_name = check.check_name
    model = db.query(AIModel).filter(AIModel.id == check.model_id).first()
    
    db.delete(check)
    db.commit()

    if model:
        log_audit(
            db,
            event_type  = "AI_COMPLIANCE_CHECKED",
            description = f"Compliance check '{check_name}' removed for model: {model.name}",
            entity_type = "ai_compliance_check",
            entity_id   = str(check_id),
            metadata    = {"model_id": model.id, "action": "deleted"},
        )


# ── Summary Dashboard ──────────────────────────────────────────────────────────

@router.get("/summary")
def ai_governance_summary(db: Session = Depends(get_db)):
    models = db.query(AIModel).all()
    checks = db.query(AIComplianceCheck).all()

    risk_counts = {"minimal": 0, "limited": 0, "high": 0, "unacceptable": 0}
    for m in models:
        rl = str(m.risk_level) if m.risk_level else "minimal"
        risk_counts[rl] = risk_counts.get(rl, 0) + 1

    total_checks = len(checks)
    passed       = sum(1 for c in checks if c.check_status == "pass")
    failed       = sum(1 for c in checks if c.check_status == "fail")
    compliance_pct = round(passed / total_checks * 100, 1) if total_checks else None

    return {
        "total_models":    len(models),
        "active_models":   sum(1 for m in models if m.status == "active"),
        "high_risk":       risk_counts["high"] + risk_counts["unacceptable"],
        "uses_pii":        sum(1 for m in models if m.uses_pii),
        "autonomous":      sum(1 for m in models if m.autonomous),
        "risk_breakdown":  risk_counts,
        "total_checks":    total_checks,
        "passed_checks":   passed,
        "failed_checks":   failed,
        "compliance_pct":  compliance_pct,
    }
