"""
connectors.py — MariaDB and GitHub integration management.
Credentials are stored encrypted in PostgreSQL; in-memory store is the fallback.
"""
from __future__ import annotations

import pymysql
import requests
import os
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, text

import store
from database import get_db, is_db_available
from schemas import IntegrationCreate, TestResult
from integrations_service import save_integration, get_connection_config, build_connection_url
from models import Integration

router = APIRouter()


# ── List / create / delete integrations ───────────────────────────────────────

@router.get("/integrations")
def get_integrations(db: Session = Depends(get_db)):
    if is_db_available():
        return [
            {
                "id": str(i.id),
                "name": i.name,
                "provider_name": i.provider,
                "category": i.category,
                "status": "active",
                "created_at": i.created_at,
            }
            for i in db.query(Integration).all()
        ]
    return store.list_integrations()


@router.get("/templates")
def get_templates():
    store.ensure_mariadb_template()
    return list(store._templates.values())


@router.get("/templates/mariadb-id")
def get_mariadb_template_id():
    return {"template_id": store.MARIADB_TEMPLATE_ID}


@router.post("/integrations", status_code=201)
def add_integration(data: IntegrationCreate, db: Session = Depends(get_db)):
    tmpl = store.get_template(data.template_id)
    if not tmpl:
        raise HTTPException(404, f"Template '{data.template_id}' not found. Available: mariadb-builtin, github-builtin")

    if is_db_available():
        new_int = save_integration(db, data.credentials, provider=tmpl["provider_name"], name=data.name)
        return {
            "id": str(new_int.id),
            "name": new_int.name,
            "provider_name": new_int.provider,
            "status": "active",
            "created_at": new_int.created_at,
        }
    return store.create_integration(data, provider_name=tmpl["provider_name"])


@router.delete("/integrations/{integration_id}", status_code=204)
def delete_integration(integration_id: str, db: Session = Depends(get_db)):
    if is_db_available():
        obj = db.query(Integration).filter(Integration.id == integration_id).first()
        if obj:
            db.delete(obj)
            db.commit()
            return
    if not store.delete_integration(integration_id):
        raise HTTPException(404, "Integration not found")


# ── Test connection ────────────────────────────────────────────────────────────

@router.post("/integrations/{integration_id}/test")
def test_integration(integration_id: str, db: Session = Depends(get_db)) -> TestResult:
    creds = None
    provider = "MariaDB"
    if is_db_available():
        integration = db.query(Integration).filter(Integration.id == integration_id).first()
        if integration:
            provider = integration.provider
            creds = get_connection_config(db, integration_id)
    if not creds:
        obj = store.get_integration(integration_id)
        if not obj:
            raise HTTPException(404, "Integration not found")
        provider = obj.get("provider_name", "MariaDB")
        creds = obj.get("credentials", {})

    # ── GitHub test ──────────────────────────────────────────────────────────
    if provider == "GitHub":
        owner = creds.get("owner", "")
        repo  = creds.get("repo",  "")
        token = creds.get("token", "")
        headers = {"Authorization": f"token {token}"} if token else {}
        try:
            resp = requests.get(
                f"https://api.github.com/repos/{owner}/{repo}",
                headers=headers, timeout=8,
            )
            if resp.status_code == 200:
                return TestResult(success=True, message=f"GitHub repo '{owner}/{repo}' accessible")
            return TestResult(success=False, message=f"GitHub returned {resp.status_code}: {resp.json().get('message','')}")
        except Exception as exc:
            return TestResult(success=False, message=f"GitHub connection failed: {exc}")

    # ── MariaDB test ─────────────────────────────────────────────────────────
    ssl_mode = creds.get("ssl", "disable")
    try:
        conn = pymysql.connect(
            host=str(creds.get("host") or "127.0.0.1"),
            port=int(str(creds.get("port", 3306))),
            user=str(creds.get("user", "")),
            password=str(creds.get("password", "")),
            database=str(creds.get("database", "")),
            connect_timeout=5,
            ssl={} if ssl_mode and ssl_mode != "disable" else None,
        )
        conn.close()
        return TestResult(success=True, message="MariaDB connection successful")
    except Exception as exc:
        return TestResult(success=False, message=str(exc))


# ── Schema metadata ────────────────────────────────────────────────────────────

@router.get("/integrations/{integration_id}/tables")
def get_tables(integration_id: str, db: Session = Depends(get_db)):
    creds = None
    provider = "MariaDB"
    if is_db_available():
        integration = db.query(Integration).filter(Integration.id == integration_id).first()
        if integration:
            provider = integration.provider
            creds = get_connection_config(db, integration_id)
    if not creds:
        obj = store.get_integration(integration_id)
        if not obj:
            raise HTTPException(404, "Integration not found")
        provider = obj.get("provider_name", "MariaDB")
        creds = obj.get("credentials", {})

    # ── GitHub: fetch script and return its filename as the "table" ──────────
    if provider == "GitHub":
        owner    = creds.get("owner", "")
        repo     = creds.get("repo", "")
        filepath = creds.get("filepath", "etl_pipeline.py")
        branch   = creds.get("branch", "main")
        token    = creds.get("token", "")
        headers  = {"Authorization": f"token {token}"} if token else {}
        try:
            url  = f"https://api.github.com/repos/{owner}/{repo}/contents/{filepath}?ref={branch}"
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                raise HTTPException(400, f"Cannot fetch script: {resp.json().get('message','')}")
            return [{"name": filepath, "columns": [], "column_count": 0, "type": "pyspark_script"}]
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, detail=f"GitHub fetch failed: {exc}")

    # ── MariaDB: SHOW TABLES ─────────────────────────────────────────────────
    try:
        engine = create_engine(build_connection_url(creds))
        tables = []
        with engine.connect() as conn:
            for (tbl,) in conn.execute(text("SHOW TABLES")).fetchall():
                cols = [
                    {"name": r[0], "type": r[1], "nullable": r[2] == "YES"}
                    for r in conn.execute(text(f"DESCRIBE `{tbl}`")).fetchall()
                ]
                tables.append({"name": tbl, "columns": cols, "column_count": len(cols)})
        return tables
    except Exception as exc:
        raise HTTPException(500, detail=f"Failed to fetch schema: {exc}")


@router.get("/integrations/{integration_id}/tables/{table_name}/data")
def get_table_data(integration_id: str, table_name: str, limit: int = 100, db: Session = Depends(get_db)):
    """Read-only preview — up to 100 rows. Never persisted."""
    creds = None
    if is_db_available():
        creds = get_connection_config(db, integration_id)
    if not creds:
        integration = store.get_integration(integration_id)
        if not integration:
            raise HTTPException(404, "Integration not found")
        creds = integration.get("credentials", {})

    try:
        engine = create_engine(build_connection_url(creds))
        safe_table = table_name.replace("`", "")
        with engine.connect() as conn:
            rows = [dict(r._mapping) for r in conn.execute(
                text(f"SELECT * FROM `{safe_table}` LIMIT :lim"),
                {"lim": min(limit, 100)},
            ).fetchall()]
        serialisable = [
            {k: (str(v) if v is not None and not isinstance(v, (int, float, str, bool)) else v)
             for k, v in row.items()}
            for row in rows
        ]
        return {"table": table_name, "rows": serialisable, "count": len(serialisable)}
    except Exception as exc:
        raise HTTPException(500, detail=f"Failed to fetch table data: {exc}")
