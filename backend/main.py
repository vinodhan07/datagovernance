import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware # type: ignore
from routers import (
    audit, catalog, connectors, data_quality, 
    extraction, lineage, pipeline, scanner
)

app = FastAPI(title="DataGuard Governance Platform")

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(audit.router, prefix="/audit", tags=["Audit"])
app.include_router(catalog.router, prefix="/catalog", tags=["Catalog"])
app.include_router(connectors.router, prefix="/connectors", tags=["Connectors"])
app.include_router(data_quality.router, prefix="/data-quality", tags=["Quality"])
app.include_router(lineage.router, prefix="/lineage", tags=["Lineage"])
app.include_router(pipeline.router, prefix="/pipeline", tags=["Pipeline"])
app.include_router(scanner.router, prefix="/scanner", tags=["Scanner"])

@app.get("/")
async def root():
    return {"message": "DataGuard API is online"}

@app.get("/dashboard/stats")
async def dashboard_stats():
    from store import list_integrations, list_rules
    from database import SessionLocal, is_db_available
    from models import QualityScanResult
    
    integrations = list_integrations()
    rules = list_rules()
    quality_score = 100.0
    
    if is_db_available():
        db = SessionLocal()
        try:
            latest = (
                db.query(QualityScanResult.score)
                .order_by(QualityScanResult.scanned_at.desc())
                .limit(50)
                .all()
            )
            if latest:
                scores = [r.score for r in latest]
                quality_score = round(sum(scores) / len(scores), 1)
        finally:
            db.close()
            
    return {
        "integrations": len(integrations),
        "quality_rules": len(rules),
        "quality_score": quality_score,
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
