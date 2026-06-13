import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import audit, auth, catalog, connectors, lineage, pipeline, quality

app = FastAPI(title="DataGuard ETL Lineage Platform")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,       prefix="/auth",       tags=["Auth"])
app.include_router(audit.router,      prefix="/audit",      tags=["Audit"])
app.include_router(catalog.router,    prefix="/catalog",    tags=["Catalog"])
app.include_router(connectors.router, prefix="/connectors", tags=["Connectors"])
app.include_router(lineage.router,    prefix="/lineage",    tags=["Lineage"])
app.include_router(pipeline.router,   prefix="/pipeline",   tags=["Pipeline"])
app.include_router(quality.router,    prefix="/quality",    tags=["Quality"])


@app.get("/")
async def root():
    return {"message": "DataGuard ETL Lineage API is online"}


@app.get("/dashboard/stats")
async def dashboard_stats():
    from store import list_integrations
    from database import SessionLocal, is_db_available
    from models import PipelineRun, QualityRule, QualityScan

    integrations = list_integrations()
    recent_runs = []
    quality_rules_count = 0
    latest_quality_score = None

    if is_db_available():
        db = SessionLocal()
        try:
            recent_runs = (
                db.query(PipelineRun)
                .order_by(PipelineRun.started_at.desc())
                .limit(10)
                .all()
            )
            quality_rules_count = db.query(QualityRule).count()
            latest_scan = (
                db.query(QualityScan)
                .filter(QualityScan.status == "completed")
                .order_by(QualityScan.started_at.desc())
                .first()
            )
            if latest_scan:
                latest_quality_score = latest_scan.score
        finally:
            db.close()

    completed = sum(1 for r in recent_runs if r.status == "completed")
    failed    = sum(1 for r in recent_runs if r.status == "failed")

    return {
        "integrations": len(integrations),
        "pipeline_runs": len(recent_runs),
        "completed_runs": completed,
        "failed_runs": failed,
        "quality_rules": quality_rules_count,
        "quality_score": latest_quality_score,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)