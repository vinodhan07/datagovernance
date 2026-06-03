from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import uuid
from database import get_db
from models import Integration, DataAsset
from routers.extraction import extract_schema

router = APIRouter()

@router.post("/{integration_id}/scan")
def run_scanner(integration_id: str, db: Session = Depends(get_db)): # type: ignore
    """
    Scans the integration schema and updates the catalog.
    """
    integration = db.query(Integration).filter(Integration.id == integration_id).first()
    if not integration:
        raise HTTPException(404, "Integration not found")

    # Fetch credentials
    from integrations_service import get_connection_config
    creds = get_connection_config(db, integration_id)
    if not creds:
        raise HTTPException(400, "Invalid integration credentials")

    try:
        schema = extract_schema(creds)
        
        # Clear old assets
        db.query(DataAsset).filter(DataAsset.integration_id == integration_id).delete()
        
        # Add new assets
        for table, columns in schema.items():
            for col in columns:
                asset = DataAsset(
                    id=str(uuid.uuid4()),
                    integration_id=integration_id,
                    table_name=table,
                    column_name=col.get("Field"),
                    data_type=col.get("Type"),
                    is_nullable=col.get("Null"),
                    column_key=col.get("Key")
                )
                db.add(asset)
        
        db.commit()
        return {"status": "success", "tables_found": len(schema)}

    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail=f"Scan failed: {str(e)}")
