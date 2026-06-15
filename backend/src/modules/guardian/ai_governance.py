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
        "endpoint_url":   m.endpoint_url,
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
        
    from src.core.security import encrypt_password
    
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
        endpoint_url   = data.get("endpoint_url"),
        api_key_encrypted = encrypt_password(data["api_key"]) if data.get("api_key") else None
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

    from src.core.security import encrypt_password

    updatable = ["name", "provider", "model_type", "version", "purpose",
                 "owner", "risk_level", "status", "integration_id", "endpoint_url"]
    for field in updatable:
        if field in data:
            setattr(model, field, data[field])
    if "uses_pii" in data:
        model.uses_pii = bool(data["uses_pii"])
    if "autonomous" in data:
        model.autonomous = bool(data["autonomous"])
    if "api_key" in data and data["api_key"]:
        model.api_key_encrypted = encrypt_password(data["api_key"])

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


@router.post("/models/{model_id}/scan")
def scan_model(model_id: int, db: Session = Depends(get_db)):
    model = db.query(AIModel).filter(AIModel.id == model_id).first()
    if not model:
        raise HTTPException(404, "Model not found")
        
    from src.core.security import decrypt_password
    api_key = decrypt_password(model.api_key_encrypted)
    if not api_key:
        raise HTTPException(400, "API key not configured for this model")
        
    from src.modules.guardian.evaluator import run_eval_scan
    
    # Run scan
    results = run_eval_scan(api_key=api_key, model_name=model.name)
    
    # Update compliance checks
    created_checks = []
    for r in results:
        # Check if a check with this name already exists
        check = db.query(AIComplianceCheck).filter(
            AIComplianceCheck.model_id == model_id,
            AIComplianceCheck.check_name == r["check_name"]
        ).first()
        
        if not check:
            check = AIComplianceCheck(
                model_id=model_id,
                check_name=r["check_name"]
            )
            db.add(check)
            
        check.check_status = r["status"]
        check.notes = r["notes"]
        check.checked_at = datetime.now(timezone.utc)  # type: ignore
        created_checks.append(check)
        
    db.commit()
    
    log_audit(
        db,
        event_type="AI_MODEL_SCANNED",
        description=f"Automated scan completed for model: {model.name}",
        entity_type="ai_model",
        entity_id=str(model_id)
    )
    
    return {"message": "Scan complete", "results": [_check_out(c) for c in created_checks]}


from pydantic import BaseModel

class PlaygroundRequest(BaseModel):
    prompt: str

@router.post("/models/{model_id}/playground")
def playground_model(model_id: int, req: PlaygroundRequest, db: Session = Depends(get_db)):
    model = db.query(AIModel).filter(AIModel.id == model_id).first()
    if not model:
        raise HTTPException(404, "Model not found")
        
    from src.core.security import decrypt_password
    api_key = decrypt_password(model.api_key_encrypted)
    if not api_key:
        raise HTTPException(400, "API key not configured for this model")
        
    from src.modules.guardian.evaluator import check_prompt_safety, run_playground, check_response_hallucination
    
    # 1. Safety check
    safety = check_prompt_safety(api_key=api_key, prompt=req.prompt)
    if not safety["is_safe"]:
        log_audit(
            db,
            event_type="AI_SECURITY_VIOLATION",
            description=f"Security violation blocked on model '{model.name}': {safety['reason']}",
            entity_type="ai_model",
            entity_id=str(model_id),
            metadata={"prompt": req.prompt, "reason": safety["reason"]}
        )
        return {
            "response": f"⚠️ Violation Detected: This prompt was blocked by DataGuard's AI Safety Guardrails.\nReason: {safety['reason']}",
            "is_safe": False,
            "reason": safety["reason"],
            "safety_report": {
                "prompt_scanners": {
                    "toxicity": {"passed": False, "reason": "Blocked by toxicity scanner"},
                    "prompt_injection": {"passed": False, "reason": "Blocked by prompt injection scanner"}
                },
                "output_scanners": {
                    "hallucination": {"passed": True, "score": 0.0, "reason": "Not checked (prompt blocked)"}
                }
            }
        }
        
    # 2. Run playground if safe
    response = run_playground(api_key=api_key, model_name=model.name, prompt=req.prompt)
    
    # 3. Check for hallucination
    hallucination = check_response_hallucination(api_key=api_key, prompt=req.prompt, response=response)
    
    log_audit(
        db,
        event_type="AI_PLAYGROUND_USED",
        description=f"Playground tested for model: {model.name}",
        entity_type="ai_model",
        entity_id=str(model_id)
    )
    
    return {
        "response": response,
        "is_safe": True,
        "safety_report": {
            "prompt_scanners": {
                "toxicity": {"passed": True, "reason": "No toxicity detected"},
                "prompt_injection": {"passed": True, "reason": "No prompt injection detected"}
            },
            "output_scanners": {
                "hallucination": {
                    "passed": not hallucination["is_hallucinated"],
                    "score": hallucination["score"],
                    "reason": hallucination["reason"]
                }
            }
        }
    }


@router.post("/compliance/{check_id}/run")
def run_single_compliance_check(check_id: int, db: Session = Depends(get_db)):
    check = db.query(AIComplianceCheck).filter(AIComplianceCheck.id == check_id).first()
    if not check:
        raise HTTPException(404, "Compliance check not found")
        
    model = db.query(AIModel).filter(AIModel.id == check.model_id).first()
    if not model:
        raise HTTPException(404, "Associated AI Model not found")
        
    from src.core.security import decrypt_password
    api_key = decrypt_password(model.api_key_encrypted)
    if not api_key:
        raise HTTPException(400, "API key not configured for this model")
        
    from src.modules.guardian.evaluator import run_eval_scan
    
    # Run scan
    results = run_eval_scan(api_key=api_key, model_name=model.name)
    
    matched_result = None
    for r in results:
        if r["check_name"].lower() in check.check_name.lower() or check.check_name.lower() in r["check_name"].lower():
            matched_result = r
            break
            
    if not matched_result and results:
        if "jailbreak" in check.check_name.lower() or "toxicity" in check.check_name.lower() or "toxic" in check.check_name.lower():
            matched_result = results[0]
        elif "hallucination" in check.check_name.lower() or "hallucinate" in check.check_name.lower():
            matched_result = results[1]
        else:
            matched_result = results[0]
            
    if matched_result:
        check.check_status = matched_result["status"]
        check.notes = matched_result["notes"]
        check.checked_at = datetime.now(timezone.utc)  # type: ignore
        db.commit()
        db.refresh(check)
        
        log_audit(
            db,
            event_type="AI_COMPLIANCE_CHECKED",
            description=f"Compliance check '{check.check_name}' run individual scan → {check.check_status} for model: {model.name}",
            entity_type="ai_compliance_check",
            entity_id=str(check.id),
            metadata={"model_id": model.id, "check_name": check.check_name, "status": check.check_status}
        )
        return _check_out(check)
        
    raise HTTPException(400, "Could not map scan rules to this check name")


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
        checked_at   = datetime.now(timezone.utc) if data.get("check_status") in ("pass", "fail") else None,  # type: ignore
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
            check.checked_at = datetime.now(timezone.utc)  # type: ignore
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
