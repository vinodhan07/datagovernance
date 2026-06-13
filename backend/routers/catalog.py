"""
catalog.py — Data Catalog endpoints backed by OpenMetadata.

Reads lineage metadata already stored in PostgreSQL (from Spline ETL runs)
and pushes it to OpenMetadata. Also proxies search/detail queries so the
frontend never speaks to OpenMetadata directly.
"""
from __future__ import annotations

import logging
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import LineageDataset, LineageColumn, LineageJob
from schemas import CatalogIngestResponse, CatalogTagRequest, CatalogTableOut, CatalogColumnOut
from engines.openmetadata_sync import (
    ensure_db_service,
    push_table_metadata,
    search_tables,
    get_table_detail,
    add_tags_to_table,
)

logger = logging.getLogger("dataguard.catalog")
router = APIRouter()


# ── POST /catalog/ingest/{integration_id} ─────────────────────────────────────

@router.post("/ingest/{integration_id}", response_model=CatalogIngestResponse)
def ingest_catalog(integration_id: str, db: Session = Depends(get_db)):
    """
    Push all table metadata (discovered from Spline lineage runs) for this
    integration into OpenMetadata. Safe to call multiple times — upserts.
    """
    # Collect unique tables from lineage datasets recorded for this integration
    datasets = (
        db.query(LineageDataset)
        .join(LineageJob, LineageDataset.job_id == LineageJob.id)
        .filter(LineageJob.integration_id == integration_id)
        .all()
    )

    if not datasets:
        # Fall back to all datasets if no integration filter matches (useful for demo)
        datasets = db.query(LineageDataset).all()

    # Deduplicate by table name
    seen: set[str] = set()
    tables_pushed = 0

    service_fqn = ensure_db_service() or "dataguard-postgres"

    for ds in datasets:
        if ds.name in seen:
            continue
        seen.add(ds.name)

        # Collect columns for this dataset
        cols = db.query(LineageColumn).filter(LineageColumn.dataset_id == ds.id).all()
        column_list = [{"name": c.name, "data_type": c.data_type or "VARCHAR"} for c in cols]

        # If no LineageColumn rows exist, fall back to columns_json
        if not column_list and ds.columns_json:
            column_list = [{"name": n, "data_type": "VARCHAR"} for n in ds.columns_json]

        ok = push_table_metadata(ds.name, column_list)
        if ok:
            tables_pushed += 1

    return CatalogIngestResponse(
        tables_pushed=tables_pushed,
        service_fqn=service_fqn,
        message=f"Pushed {tables_pushed} table(s) to OpenMetadata",
    )


# ── GET /catalog/tables ────────────────────────────────────────────────────────

@router.get("/tables")
def list_catalog_tables(q: str = "", limit: int = 50):
    """Search tables in OpenMetadata catalog."""
    results = search_tables(query=q, limit=limit)
    return results


# ── GET /catalog/tables/{table_fqn} ───────────────────────────────────────────

@router.get("/tables/{table_fqn:path}", response_model=CatalogTableOut)
def get_catalog_table(table_fqn: str):
    """Fetch a single table's full detail (columns, tags, description)."""
    fqn = unquote(table_fqn)
    result = get_table_detail(fqn)
    if not result:
        raise HTTPException(404, f"Table '{fqn}' not found in catalog")
    return CatalogTableOut(
        fqn=result.get("fqn", fqn),
        name=result.get("name", fqn),
        description=result.get("description"),
        tags=result.get("tags", []),
        columns=[
            CatalogColumnOut(
                name=c["name"],
                data_type=c.get("data_type"),
                description=c.get("description"),
                tags=c.get("tags", []),
            )
            for c in result.get("columns", [])
        ],
        service_name=result.get("service_name"),
    )


# ── POST /catalog/tables/{table_fqn}/tags ─────────────────────────────────────

@router.post("/tables/{table_fqn:path}/tags")
def tag_catalog_table(table_fqn: str, body: CatalogTagRequest):
    """Add business tags or glossary terms to a table in OpenMetadata."""
    fqn = unquote(table_fqn)
    success = add_tags_to_table(fqn, body.tags)
    if not success:
        raise HTTPException(400, f"Failed to tag table '{fqn}' — is OpenMetadata running?")
    return {"fqn": fqn, "tags_applied": body.tags}
