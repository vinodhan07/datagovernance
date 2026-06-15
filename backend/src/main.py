import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.core import auth
from src.modules.observer import audit
from src.modules.registry import catalog, connectors
from src.modules.nexus import lineage, pipeline
from src.modules.guardian import quality, ai_governance, ml_governance

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
app.include_router(ai_governance.router, prefix="/ai-governance", tags=["AI Governance"])
app.include_router(ml_governance.router, prefix="/ml-governance", tags=["ML Governance"])


@app.get("/")
async def root():
    frontend_dist_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../frontend/dist"))
    index_path = os.path.join(frontend_dist_path, "index.html")
    if os.path.exists(index_path):
        from fastapi.responses import FileResponse
        return FileResponse(index_path)
    return {"message": "DataGuard ETL Lineage API is online"}


from fastapi.staticfiles import StaticFiles

frontend_dist_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../frontend/dist"))
if os.path.exists(frontend_dist_path):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist_path, "assets")), name="assets")


@app.get("/dashboard/stats")
async def dashboard_stats():
    from src.core.database import SessionLocal, is_db_available
    from src.domain.entities import PipelineRun, QualityRule, QualityScan, Integration

    integrations_count = 0
    recent_runs = []
    quality_rules_count = 0
    latest_quality_score = None

    if is_db_available():
        db = SessionLocal()
        try:
            integrations_count = db.query(Integration).count()
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
        "integrations": integrations_count,
        "pipeline_runs": len(recent_runs),
        "completed_runs": completed,
        "failed_runs": failed,
        "quality_rules": quality_rules_count,
        "quality_score": latest_quality_score,
    }


@app.get("/{catchall:path}")
async def serve_frontend(catchall: str):
    if not catchall:
        return await root()
    
    parts = [p for p in catchall.split("/") if p]
    if len(parts) > 1 and parts[0] in ["auth", "audit", "catalog", "connectors", "lineage", "pipeline", "quality", "ai-governance", "ml-governance", "dashboard"]:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not Found")
        
    frontend_dist_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../frontend/dist"))
    file_path = os.path.join(frontend_dist_path, catchall)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        from fastapi.responses import FileResponse
        return FileResponse(file_path)
        
    index_path = os.path.join(frontend_dist_path, "index.html")
    if os.path.exists(index_path):
        from fastapi.responses import FileResponse
        return FileResponse(index_path)
        
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail="Not Found")



if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)