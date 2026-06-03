import os
import requests
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db, is_db_available
from models import PipelineRun

router = APIRouter()

@router.get("/{integration_id}/graph")
def get_lineage_graph(integration_id: str, db: Session = Depends(get_db)): # type: ignore
    """
    Returns the Spline URL for the most recent pipeline run of this integration.
    """
    if not is_db_available():
        return {"spline_url": None, "last_run": None}
        
    run = (
        db.query(PipelineRun)
        .filter(PipelineRun.integration_id == integration_id)
        .order_by(PipelineRun.started_at.desc())
        .first()
    )
    
    if not run or not run.spline_plan_id:
        return {"spline_url": None, "last_run": None}
        
    spline_web_ui_url = os.getenv("SPLINE_WEB_UI_URL", "http://localhost:9090")
    consumer_url = os.getenv("SPLINE_CONSUMER_URL", "http://localhost:8080/consumer")
    
    # Attempt to resolve the event ID for the plan
    event_id = None
    try:
        resp = requests.get(f"{consumer_url}/execution-events?limit=200", timeout=5)
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            for item in items:
                if item.get("executionPlanId") == run.spline_plan_id:
                    event_id = item.get("executionEventId")
                    break
    except Exception as exc:
        print(f"Error fetching event ID from Spline consumer: {exc}")
        
    # If we couldn't resolve the event ID, fallback to generating URL with plan ID
    if event_id:
        spline_url = f"{spline_web_ui_url}/app/events/overview/{event_id}"
    else:
        spline_url = f"{spline_web_ui_url}/app/plans/overview/{run.spline_plan_id}"
        
    return {
        "spline_url": spline_url,
        "last_run": {
            "id": run.id,
            "status": run.status,
            "started_at": run.started_at,
            "completed_at": run.completed_at
        }
    }

