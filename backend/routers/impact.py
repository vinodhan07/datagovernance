"""
impact.py
═════════
Impact analysis router — find all downstream columns, datasets, and jobs
affected by a change to a given source column.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from database import SessionLocal, is_db_available
from models import LineageEdge, LineageJob

logger = logging.getLogger("dataguard.impact")

router = APIRouter()


@router.get("/column/{column_name}")
def get_column_impact(
    column_name: str,
    dataset: Optional[str] = Query(None, description="Filter by source dataset name"),
) -> dict[str, Any]:
    """
    Impact analysis: given a source column name, find all downstream
    columns, datasets, and jobs that depend on it.

    Uses BFS traversal of the lineage_edges table.
    """
    if not is_db_available():
        return {
            "source": {"column": column_name, "dataset": dataset},
            "affected_columns": [],
            "affected_datasets": [],
            "affected_jobs": [],
        }

    db = SessionLocal()
    try:
        # Query all edges where the source column matches
        query = db.query(LineageEdge).filter(LineageEdge.source_column == column_name)
        if dataset:
            query = query.filter(LineageEdge.source_dataset == dataset)

        edges = query.all()

        if not edges:
            return {
                "source": {"column": column_name, "dataset": dataset},
                "affected_columns": [],
                "affected_datasets": [],
                "affected_jobs": [],
                "message": f"No lineage found for column '{column_name}'",
            }

        # Collect affected columns
        affected_columns: list[dict[str, Any]] = []
        affected_datasets: set[str] = set()
        affected_job_ids: set[str] = set()

        # BFS: also find transitive dependencies
        visited: set[str] = set()
        queue: list[tuple[str, str]] = [(column_name, dataset or "")]

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
                })
                affected_datasets.add(edge.target_dataset)
                affected_job_ids.add(edge.job_id)

                # Add target to BFS queue for transitive deps
                tgt_key = f"{edge.target_dataset}:{edge.target_column}"
                if tgt_key not in visited:
                    queue.append((edge.target_column, edge.target_dataset))

        # Fetch job names
        affected_jobs: list[dict[str, str]] = []
        if affected_job_ids:
            jobs = db.query(LineageJob).filter(LineageJob.id.in_(list(affected_job_ids))).all()
            affected_jobs = [{"id": j.id, "name": j.name} for j in jobs]

        return {
            "source": {"column": column_name, "dataset": dataset},
            "affected_columns": affected_columns,
            "affected_datasets": sorted(affected_datasets),
            "affected_jobs": affected_jobs,
        }

    finally:
        db.close()


@router.get("/dataset/{dataset_name}")
def get_dataset_impact(dataset_name: str) -> dict[str, Any]:
    """
    Impact analysis for an entire dataset: find all downstream datasets.
    """
    if not is_db_available():
        return {
            "source_dataset": dataset_name,
            "affected_columns": [],
            "affected_datasets": [],
        }

    db = SessionLocal()
    try:
        edges = (
            db.query(LineageEdge)
            .filter(LineageEdge.source_dataset == dataset_name)
            .all()
        )

        affected_columns: list[dict[str, Any]] = []
        affected_datasets: set[str] = set()

        for edge in edges:
            affected_columns.append({
                "source_column": edge.source_column,
                "target_dataset": edge.target_dataset,
                "target_column": edge.target_column,
                "transformations": edge.transformations_json or [],
            })
            affected_datasets.add(edge.target_dataset)

        return {
            "source_dataset": dataset_name,
            "affected_columns": affected_columns,
            "affected_datasets": sorted(affected_datasets),
        }

    finally:
        db.close()
