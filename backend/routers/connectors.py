"""
Connectors router — manages integration templates and active integrations.

Integrations are stored in PostgreSQL with encrypted passwords.
Fallback to in-memory store (store.py) if DB is unavailable.
"""
from __future__ import annotations
import pymysql
import uuid
import requests
import os
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

import store
from database import get_db, is_db_available
from schemas import IntegrationCreate, TestResult
from integrations_service import save_integration, get_connection_config, build_connection_url
from models import Integration

from sqlalchemy import create_engine, text # type: ignore

router = APIRouter()


# ─── Integrations ─────────────────────────────────────────────────────────────

@router.get("/integrations")
def get_integrations(db: Session = Depends(get_db)): # type: ignore
    if is_db_available():
        integrations = db.query(Integration).all()
        return [
            {
                "id": str(i.id),
                "name": i.name,
                "provider_name": i.provider,
                "category": i.category,
                "status": "active",
                "created_at": i.created_at
            }
            for i in integrations
        ]
    return store.list_integrations()


@router.get("/templates")
def get_templates():
    """Returns the list of available integration templates."""
    store.ensure_mariadb_template()
    return list(store._templates.values())

@router.get("/templates/mariadb-id")
def get_mariadb_template_id():
    """Returns the stable built-in MariaDB template ID for the frontend."""
    return {"template_id": store.MARIADB_TEMPLATE_ID}


@router.post("/integrations", status_code=201)
def add_integration(data: IntegrationCreate, db: Session = Depends(get_db)): # type: ignore
    tmpl = store.get_template(data.template_id)
    if not tmpl:
        raise HTTPException(404, f"Template '{data.template_id}' not found")
    
    if is_db_available():
        new_int = save_integration(db, data.credentials, provider=tmpl["provider_name"], name=data.name)
        return {
            "id": str(new_int.id),
            "name": new_int.name,
            "provider_name": new_int.provider,
            "status": "active",
            "created_at": new_int.created_at
        }
    
    return store.create_integration(data, provider_name=tmpl["provider_name"])


@router.delete("/integrations/{integration_id}", status_code=204)
def delete_integration(integration_id: str, db: Session = Depends(get_db)): # type: ignore
    if is_db_available():
        try:
            target_id = uuid.UUID(integration_id)
            integration = db.query(Integration).filter(Integration.id == target_id).first()
            if integration:
                db.delete(integration)
                db.commit()
                return
        except ValueError:
            pass # fallback to in-memory check if UUID is invalid

    if not store.delete_integration(integration_id):
        raise HTTPException(404, "Integration not found")


@router.post("/integrations/{integration_id}/test")
def test_integration(integration_id: str, db: Session = Depends(get_db)) -> TestResult: # type: ignore
    # Try database first
    creds = None
    provider = "MariaDB"
    if is_db_available():
        integration = db.query(Integration).filter(Integration.id == integration_id).first()
        if integration:
            provider = integration.provider
            creds = get_connection_config(db, integration_id)

    # Fallback to in-memory
    if not creds:
        integration = store.get_integration(integration_id)
        if not integration:
            raise HTTPException(404, "Integration not found")
        provider = integration.get("provider_name", "MariaDB")
        creds = integration.get("credentials", {})

    if provider == "GitHub":
        owner = creds.get("owner", "")
        repo = creds.get("repo", "")
        token = creds.get("token", "")
        headers = {}
        if token:
            headers["Authorization"] = f"token {token}"
            
        url = f"https://api.github.com/repos/{owner}/{repo}"
        try:
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                return TestResult(success=True, message="GitHub repository connection successful")
            else:
                err_msg = resp.json().get("message", "Check repository path & credentials")
                return TestResult(success=False, message=f"Failed (Status {resp.status_code}): {err_msg}")
        except Exception as exc:
            return TestResult(success=False, message=f"GitHub connection failed: {exc}")

    ssl_mode = creds.get("ssl", "disable")

    try:
        ssl_config = None
        if ssl_mode and ssl_mode != "disable":
            ssl_config = {}

        conn = pymysql.connect( # type: ignore
            host=str(creds.get("host", "localhost")), # type: ignore
            port=int(str(creds.get("port", 3306))), # type: ignore
            user=str(creds.get("user", "")), # type: ignore
            password=str(creds.get("password", "")), # type: ignore
            database=str(creds.get("database", "")), # type: ignore
            connect_timeout=5,
            ssl=ssl_config # type: ignore
        )
        conn.close()
        return TestResult(success=True, message="Connection successful")
    except Exception as exc:
        print("🔥 FULL ERROR (test):", repr(exc))
        return TestResult(success=False, message=str(exc))


# ─── Schema metadata (no row data) ────────────────────────────────────────────

@router.get("/integrations/{integration_id}/tables")
def get_tables(integration_id: str, db: Session = Depends(get_db)): # type: ignore
    # Try database first
    creds = None
    provider = "MariaDB"
    if is_db_available():
        integration = db.query(Integration).filter(Integration.id == integration_id).first()
        if integration:
            provider = integration.provider
            creds = get_connection_config(db, integration_id)

    # Fallback to in-memory
    if not creds:
        integration = store.get_integration(integration_id)
        if not integration:
            raise HTTPException(404, "Integration not found")
        provider = integration.get("provider_name", "MariaDB")
        creds = integration.get("credentials", {})

    if provider == "GitHub":
        try:
            from routers.pipeline import fetch_file_from_github, parse_etl_script
            owner = str(creds.get("owner", ""))
            repo = str(creds.get("repo", ""))
            filepath = str(creds.get("filepath", ""))
            branch = str(creds.get("branch", "main"))
            token = creds.get("token")
            
            code = fetch_file_from_github(owner, repo, filepath, branch, token)
                    
            parsed = parse_etl_script(code)
            tables = []
            for name, cols in parsed["targets"].items():
                tables.append({
                    "name": name,
                    "columns": [{"name": c, "type": "VARCHAR(100)", "nullable": True} for c in cols],
                    "column_count": len(cols)
                })
            return tables
        except Exception as exc:
            raise HTTPException(500, detail=f"Failed to fetch GitHub ETL schema: {exc}")

    try:
        url = build_connection_url(creds)
        # Don't print password in logs
        safe_url = url.replace(str(creds.get('password', '')), '****') if creds.get('password') else url # type: ignore
        print(f"DEBUG: Connection string: {safe_url}")
        
        engine = create_engine(url)
        tables = []
 
        with engine.connect() as conn:
            # Fetch table names
            result = conn.execute(text("SHOW TABLES"))
            tables_raw = [row[0] for row in result]

            for table_name in tables_raw:
                # Fetch column details
                col_result = conn.execute(text(f"DESCRIBE `{table_name}`"))
                columns = [
                    {
                        "name": row[0],
                        "type": row[1],
                        "nullable": row[2] == "YES",
                    }
                    for row in col_result
                ]
                tables.append({
                    "name": table_name, 
                    "columns": columns, 
                    "column_count": len(columns)
                })

        return tables
    except Exception as exc:
        print("🔥 FULL ERROR (SQLAlchemy):", repr(exc))
        raise HTTPException(status_code=500, detail=f"Failed to fetch schema: {exc}")


@router.get("/integrations/{integration_id}/tables/{table_name}/data")
def get_table_data(integration_id: str, table_name: str, limit: int = 100, db: Session = Depends(get_db)): # type: ignore
    """
    Read-only data preview — up to `limit` rows.
    This data is returned to the frontend for display ONLY.
    It is NEVER written to PostgreSQL.
    """
    # Try database first
    creds = None
    if is_db_available():
        creds = get_connection_config(db, integration_id)

    # Fallback to in-memory
    if not creds:
        integration = store.get_integration(integration_id)
        if not integration:
            raise HTTPException(404, "Integration not found")
        creds = integration.get("credentials", {})

    try:
        url = build_connection_url(creds)
        engine = create_engine(url)
        
        # Use parameterised limit; table name is schema metadata so we sanitise it
        safe_table = table_name.replace("`", "")
        
        serialisable = []
        with engine.connect() as conn:
            # SQLAlchemy 2.x requires text() for queries
            # and returns Row objects that we can convert to dicts
            result = conn.execute(
                text(f"SELECT * FROM `{safe_table}` LIMIT :limit"),
                {"limit": min(limit, 100)}
            )
            
            # Fetch all rows and convert to dicts
            rows = [dict(row._mapping) for row in result]

            # Convert non-serialisable types (Decimal, date, etc.) to str
            for row in rows:
                serialisable.append(
                    {k: (str(v) if v is not None and not isinstance(v, (int, float, str, bool)) else v)
                     for k, v in row.items()}
                )

        return {"table": table_name, "rows": serialisable, "count": len(serialisable)}
    except Exception as exc:
        print("🔥 FULL ERROR (get_table_data):", repr(exc))
        raise HTTPException(500, detail=f"Failed to fetch table data: {exc}")
