"""
impact.py
═════════
Impact analysis router — find all upstream/downstream columns, datasets,
and jobs affected by a change to a given source column or dataset.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from database import SessionLocal, is_db_available
from models import LineageEdge, LineageJob

logger = logging.getLogger("dataguard.impact")

router = APIRouter()


def _bfs_downstream(
    db: Any,
    start_column: str,
    start_dataset: str | None,
) -> tuple[list[dict[str, Any]], set[str], set[str]]:
    """BFS forward through lineage_edges (source → target)."""
    affected_columns: list[dict[str, Any]] = []
    affected_datasets: set[str] = set()
    affected_job_ids: set[str] = set()

    visited: set[str] = set()
    queue: list[tuple[str, str]] = [(start_column, start_dataset or "")]

    while queue:
        current_col, current_ds = queue.pop(0)
        key = f"{current_ds}:{current_col}"
        if key in visited:
            continue
        visited.add(key)

        q = db.query(LineageEdge).filter(LineageEdge.source_column == current_col)
        if current_ds:
            q = q.filter(LineageEdge.source_dataset == current_ds)

        for edge in q.all():
            affected_columns.append({
                "source_dataset": edge.source_dataset,
                "source_column": edge.source_column,
                "target_dataset": edge.target_dataset,
                "target_column": edge.target_column,
                "transformations": edge.transformations_json or [],
                "direction": "downstream",
            })
            affected_datasets.add(edge.target_dataset)
            affected_job_ids.add(edge.job_id)

            tgt_key = f"{edge.target_dataset}:{edge.target_column}"
            if tgt_key not in visited:
                queue.append((edge.target_column, edge.target_dataset))

    return affected_columns, affected_datasets, affected_job_ids


def _bfs_upstream(
    db: Any,
    start_column: str,
    start_dataset: str | None,
) -> tuple[list[dict[str, Any]], set[str], set[str]]:
    """BFS backward through lineage_edges (target → source)."""
    affected_columns: list[dict[str, Any]] = []
    affected_datasets: set[str] = set()
    affected_job_ids: set[str] = set()

    visited: set[str] = set()
    queue: list[tuple[str, str]] = [(start_column, start_dataset or "")]

    while queue:
        current_col, current_ds = queue.pop(0)
        key = f"{current_ds}:{current_col}"
        if key in visited:
            continue
        visited.add(key)

        q = db.query(LineageEdge).filter(LineageEdge.target_column == current_col)
        if current_ds:
            q = q.filter(LineageEdge.target_dataset == current_ds)

        for edge in q.all():
            affected_columns.append({
                "source_dataset": edge.source_dataset,
                "source_column": edge.source_column,
                "target_dataset": edge.target_dataset,
                "target_column": edge.target_column,
                "transformations": edge.transformations_json or [],
                "direction": "upstream",
            })
            affected_datasets.add(edge.source_dataset)
            affected_job_ids.add(edge.job_id)

            src_key = f"{edge.source_dataset}:{edge.source_column}"
            if src_key not in visited:
                queue.append((edge.source_column, edge.source_dataset))

    return affected_columns, affected_datasets, affected_job_ids


@router.get("/column/{column_name}")
def get_column_impact(
    column_name: str,
    dataset: Optional[str] = Query(None, description="Filter by dataset name"),
    upstream: bool = Query(False, description="Traverse upstream instead of downstream"),
) -> dict[str, Any]:
    """
    Impact analysis for a column.

    By default returns downstream impact (what depends on this column).
    Set upstream=true to return upstream dependencies (what this column depends on).
    """
    if not is_db_available():
        return {
            "source": {"column": column_name, "dataset": dataset},
            "direction": "upstream" if upstream else "downstream",
            "affected_columns": [],
            "affected_datasets": [],
            "affected_jobs": [],
        }

    db = SessionLocal()
    try:
        if upstream:
            cols, datasets, job_ids = _bfs_upstream(db, column_name, dataset)
        else:
            cols, datasets, job_ids = _bfs_downstream(db, column_name, dataset)

        if not cols:
            return {
                "source": {"column": column_name, "dataset": dataset},
                "direction": "upstream" if upstream else "downstream",
                "affected_columns": [],
                "affected_datasets": [],
                "affected_jobs": [],
                "message": f"No lineage found for column '{column_name}'",
            }

        affected_jobs: list[dict[str, str]] = []
        if job_ids:
            jobs = db.query(LineageJob).filter(LineageJob.id.in_(list(job_ids))).all()
            affected_jobs = [{"id": j.id, "name": j.name, "type": j.job_type} for j in jobs]

        return {
            "source": {"column": column_name, "dataset": dataset},
            "direction": "upstream" if upstream else "downstream",
            "affected_columns": cols,
            "affected_datasets": sorted(datasets),
            "affected_jobs": affected_jobs,
        }

    finally:
        db.close()


@router.get("/dataset/{dataset_name}")
def get_dataset_impact(
    dataset_name: str,
    upstream: bool = Query(False, description="Traverse upstream instead of downstream"),
) -> dict[str, Any]:
    """
    Impact analysis for an entire dataset: find all downstream (or upstream) datasets
    and the jobs that connect them.
    """
    if not is_db_available():
        return {
            "source_dataset": dataset_name,
            "direction": "upstream" if upstream else "downstream",
            "affected_columns": [],
            "affected_datasets": [],
            "affected_jobs": [],
        }

    db = SessionLocal()
    try:
        if upstream:
            q = db.query(LineageEdge).filter(LineageEdge.target_dataset == dataset_name)
        else:
            q = db.query(LineageEdge).filter(LineageEdge.source_dataset == dataset_name)

        edges = q.all()

        affected_columns: list[dict[str, Any]] = []
        affected_datasets: set[str] = set()
        affected_job_ids: set[str] = set()

        for edge in edges:
            affected_columns.append({
                "source_column": edge.source_column,
                "source_dataset": edge.source_dataset,
                "target_dataset": edge.target_dataset,
                "target_column": edge.target_column,
                "transformations": edge.transformations_json or [],
            })
            if upstream:
                affected_datasets.add(edge.source_dataset)
            else:
                affected_datasets.add(edge.target_dataset)
            affected_job_ids.add(edge.job_id)

        affected_jobs: list[dict[str, str]] = []
        if affected_job_ids:
            jobs = db.query(LineageJob).filter(LineageJob.id.in_(list(affected_job_ids))).all()
            affected_jobs = [{"id": j.id, "name": j.name, "type": j.job_type} for j in jobs]

        return {
            "source_dataset": dataset_name,
            "direction": "upstream" if upstream else "downstream",
            "affected_columns": affected_columns,
            "affected_datasets": sorted(affected_datasets),
            "affected_jobs": affected_jobs,
        }

    finally:
        db.close()
