"""
lineage.py
══════════
Lineage visualization and query router.

Provides endpoints for:
  - Dataset lineage listing
  - Column lineage details
  - Transformation DAG (React Flow compatible)
  - Individual job lineage
  - Spline iframe URL (backward compatible)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.core.database import get_db, SessionLocal, is_db_available
from src.domain.entities import (
    PipelineRun,
    LineageJob,
    LineageDataset,
    LineageColumn,
    LineageTransformation,
    LineageEdge,
    LineageExecution,
)

logger = logging.getLogger("dataguard.lineage")

router = APIRouter()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GET /lineage/datasets — List all tracked datasets
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/datasets")
def list_datasets(
    job_id: Optional[str] = Query(None, description="Filter by job ID"),
    dataset_type: Optional[str] = Query(None, description="Filter by type: source or target"),
) -> dict[str, Any]:
    """Return all tracked datasets with their source/target relationships."""
    if not is_db_available():
        return {"datasets": [], "total": 0}

    db = SessionLocal()
    try:
        q = db.query(LineageDataset)
        if job_id:
            q = q.filter(LineageDataset.job_id == job_id)
        if dataset_type:
            q = q.filter(LineageDataset.dataset_type == dataset_type)

        datasets = q.order_by(LineageDataset.created_at.desc()).all()

        return {
            "datasets": [
                {
                    "id": ds.id,
                    "job_id": ds.job_id,
                    "name": ds.name,
                    "uri": ds.uri,
                    "type": ds.dataset_type,
                    "columns": ds.columns_json or [],
                    "created_at": ds.created_at.isoformat() if ds.created_at else None,
                }
                for ds in datasets
            ],
            "total": len(datasets),
        }
    finally:
        db.close()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GET /lineage/columns — Column lineage for a dataset
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/columns")
def get_column_lineage(
    dataset: Optional[str] = Query(None, description="Dataset name"),
    job_id: Optional[str] = Query(None, description="Job ID"),
) -> dict[str, Any]:
    """Return column-level lineage with transformation chains."""
    if not is_db_available():
        return {"columns": [], "total": 0}

    db = SessionLocal()
    try:
        q = db.query(LineageEdge)
        if dataset:
            q = q.filter(
                (LineageEdge.source_dataset == dataset) |
                (LineageEdge.target_dataset == dataset)
            )
        if job_id:
            q = q.filter(LineageEdge.job_id == job_id)

        edges = q.order_by(LineageEdge.created_at.desc()).all()

        return {
            "columns": [
                {
                    "id": e.id,
                    "job_id": e.job_id,
                    "source_dataset": e.source_dataset,
                    "source_column": e.source_column,
                    "target_dataset": e.target_dataset,
                    "target_column": e.target_column,
                    "transformations": e.transformations_json or [],
                }
                for e in edges
            ],
            "total": len(edges),
        }
    finally:
        db.close()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GET /lineage/graph — Full DAG for visualization
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _build_graph_for_integration(
    db,
    integration_id: Optional[str] = None,
    job_id: Optional[str] = None,
) -> dict[str, Any]:
    """Shared helper: build a nodes/edges graph from the lineage DB."""
    q = db.query(LineageExecution)
    if job_id:
        q = q.filter(LineageExecution.job_id == job_id)
    elif integration_id:
        job_ids = [
            j.id for j in
            db.query(LineageJob).filter(LineageJob.integration_id == integration_id).all()
        ]
        if job_ids:
            q = q.filter(LineageExecution.job_id.in_(job_ids))

    execution = q.order_by(LineageExecution.created_at.desc()).first()
    if execution and execution.dag_json:
        return execution.dag_json

    edges_q = db.query(LineageEdge)
    if job_id:
        edges_q = edges_q.filter(LineageEdge.job_id == job_id)
    elif integration_id:
        job_ids_list = [
            j.id for j in
            db.query(LineageJob).filter(LineageJob.integration_id == integration_id).all()
        ]
        if job_ids_list:
            edges_q = edges_q.filter(LineageEdge.job_id.in_(job_ids_list))

    edge_list = edges_q.all()
    if not edge_list:
        return {"nodes": [], "edges": []}

    nodes_dict: dict[str, dict[str, Any]] = {}
    graph_edges: list[dict[str, Any]] = []
    edge_id_counter = 0

    pair_transforms: dict[tuple[str, str], set[str]] = {}
    pair_src_cols: dict[tuple[str, str], list[str]] = {}
    pair_tgt_cols: dict[tuple[str, str], list[str]] = {}

    for e in edge_list:
        pair = (e.source_dataset, e.target_dataset)
        transforms = e.transformations_json or []
        for t in transforms:
            pair_transforms.setdefault(pair, set()).add(t)
        if e.source_column not in pair_src_cols.get(pair, []):
            pair_src_cols.setdefault(pair, []).append(e.source_column)
        if e.target_column not in pair_tgt_cols.get(pair, []):
            pair_tgt_cols.setdefault(pair, []).append(e.target_column)

    for pair, transforms in pair_transforms.items():
        src_ds, tgt_ds = pair
        src_cols = pair_src_cols.get(pair, [])
        tgt_cols = pair_tgt_cols.get(pair, [])
        src_id = f"ds:{src_ds}"
        tgt_id = f"ds:{tgt_ds}"

        if src_id not in nodes_dict:
            nodes_dict[src_id] = {
                "id": src_id, "type": "source",
                "label": src_ds, "sub": "Source",
                "status": "success",
            }
        else:
            existing_cols: list[str] = nodes_dict[src_id].get("columns", [])
            for c in src_cols:
                if c not in existing_cols:
                    existing_cols.append(c)

        if tgt_id not in nodes_dict:
            nodes_dict[tgt_id] = {
                "id": tgt_id, "type": "destination",
                "label": tgt_ds, "sub": "Target",
                "status": "success",
            }

        sorted_transforms = sorted(transforms)
        if sorted_transforms:
            prev_node_id = src_id
            for t_name in sorted_transforms:
                op_id = f"op:{src_ds}:{tgt_ds}:{t_name}"
                if op_id not in nodes_dict:
                    nodes_dict[op_id] = {
                        "id": op_id, "type": "operation",
                        "label": t_name, "sub": "transform",
                        "status": "success",
                    }
                graph_edges.append({
                    "id": f"e{edge_id_counter}",
                    "from": prev_node_id, "to": op_id,
                    "label": "→", "status": "success",
                })
                edge_id_counter += 1
                prev_node_id = op_id
            graph_edges.append({
                "id": f"e{edge_id_counter}",
                "from": prev_node_id, "to": tgt_id,
                "label": "load", "status": "success",
            })
            edge_id_counter += 1
        else:
            graph_edges.append({
                "id": f"e{edge_id_counter}",
                "from": src_id, "to": tgt_id,
                "label": "→", "status": "success",
            })
            edge_id_counter += 1

    return {"nodes": list(nodes_dict.values()), "edges": graph_edges}


@router.get("/graph")
def get_lineage_graph_data(
    job_id: Optional[str] = Query(None, description="Job ID to show graph for"),
    integration_id: Optional[str] = Query(None, description="Integration ID"),
) -> dict[str, Any]:
    """Return the transformation DAG in React Flow compatible format."""
    if not is_db_available():
        return {"nodes": [], "edges": []}

    db = SessionLocal()
    try:
        return _build_graph_for_integration(db, integration_id=integration_id, job_id=job_id)
    finally:
        db.close()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GET /lineage/columns/{column_name}/graph — Column-specific lineage subgraph
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/columns/{column_name}/graph")
def get_column_lineage_graph(
    column_name: str,
    dataset: Optional[str] = Query(None, description="Narrow to a specific dataset"),
) -> dict[str, Any]:
    """
    Return a React Flow-compatible subgraph showing the full lineage path for
    a specific column — both upstream dependencies and downstream consumers.

    Useful for column-level drill-down in the UI.
    """
    if not is_db_available():
        return {"nodes": [], "edges": [], "column": column_name}

    db = SessionLocal()
    try:
        # Collect all edges that reference this column (as source or target)
        q = db.query(LineageEdge).filter(
            (LineageEdge.source_column == column_name) |
            (LineageEdge.target_column == column_name)
        )
        if dataset:
            q = q.filter(
                (LineageEdge.source_dataset == dataset) |
                (LineageEdge.target_dataset == dataset)
            )

        edges = q.all()
        if not edges:
            return {"nodes": [], "edges": [], "column": column_name, "dataset": dataset}

        nodes_dict: dict[str, dict[str, Any]] = {}
        graph_edges: list[dict[str, Any]] = []
        edge_counter = 0

        def ensure_dataset_node(ds_name: str, role: str) -> str:
            node_id = f"ds:{ds_name}"
            if node_id not in nodes_dict:
                nodes_dict[node_id] = {
                    "id": node_id,
                    "type": "dataset",
                    "data": {"label": f"{ds_name} ({role})", "columns": []},
                    "position": {"x": 0, "y": 0},
                }
            return node_id

        def ensure_column_node(ds_name: str, col_name: str, highlighted: bool) -> str:
            node_id = f"col:{ds_name}:{col_name}"
            if node_id not in nodes_dict:
                nodes_dict[node_id] = {
                    "id": node_id,
                    "type": "column",
                    "data": {
                        "label": f"{col_name}",
                        "dataset": ds_name,
                        "highlighted": highlighted,
                    },
                    "position": {"x": 0, "y": 0},
                }
            return node_id

        for e in edges:
            is_src = e.source_column == column_name
            is_tgt = e.target_column == column_name

            ensure_dataset_node(e.source_dataset, "Source")
            ensure_dataset_node(e.target_dataset, "Target")
            src_col_id = ensure_column_node(e.source_dataset, e.source_column, is_src)
            tgt_col_id = ensure_column_node(e.target_dataset, e.target_column, is_tgt)

            transforms = e.transformations_json or []
            prev_id = src_col_id

            for t_name in transforms:
                op_id = f"op:{e.source_dataset}:{e.source_column}:{t_name}"
                if op_id not in nodes_dict:
                    nodes_dict[op_id] = {
                        "id": op_id,
                        "type": "operation",
                        "data": {"label": t_name, "operation": t_name},
                        "position": {"x": 0, "y": 0},
                    }
                graph_edges.append({
                    "id": f"e{edge_counter}",
                    "source": prev_id,
                    "target": op_id,
                })
                edge_counter += 1
                prev_id = op_id

            graph_edges.append({
                "id": f"e{edge_counter}",
                "source": prev_id,
                "target": tgt_col_id,
            })
            edge_counter += 1

        nodes = list(nodes_dict.values())
        _layout_nodes(nodes)

        return {
            "column": column_name,
            "dataset": dataset,
            "nodes": nodes,
            "edges": graph_edges,
        }

    finally:
        db.close()


def _layout_nodes(nodes: list[dict[str, Any]]) -> None:
    """Simple left-to-right layout."""
    datasets = [n for n in nodes if n["type"] == "dataset"]
    operations = [n for n in nodes if n["type"] == "operation"]

    # Sources on left, targets on right
    sources = [n for n in datasets if "Source" in n["data"]["label"]]
    targets = [n for n in datasets if "Target" in n["data"]["label"]]

    for i, n in enumerate(sources):
        n["position"] = {"x": 0, "y": i * 200}
    for i, n in enumerate(operations):
        n["position"] = {"x": 300, "y": i * 80}
    for i, n in enumerate(targets):
        n["position"] = {"x": 600, "y": i * 200}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GET /lineage/job/{job_id} — Full lineage for a job
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/job/{job_id}")
def get_job_lineage(job_id: str) -> dict[str, Any]:
    """Return complete lineage metadata for a specific job."""
    if not is_db_available():
        raise HTTPException(503, "Database not available")

    db = SessionLocal()
    try:
        job = db.query(LineageJob).filter(LineageJob.id == job_id).first()
        if not job:
            raise HTTPException(404, f"Lineage job '{job_id}' not found")

        datasets = db.query(LineageDataset).filter(LineageDataset.job_id == job_id).all()
        transformations = (
            db.query(LineageTransformation)
            .filter(LineageTransformation.job_id == job_id)
            .order_by(LineageTransformation.order_index)
            .all()
        )
        edges = db.query(LineageEdge).filter(LineageEdge.job_id == job_id).all()
        execution = (
            db.query(LineageExecution)
            .filter(LineageExecution.job_id == job_id)
            .order_by(LineageExecution.created_at.desc())
            .first()
        )

        return {
            "job": {
                "id": job.id,
                "name": job.name,
                "integration_id": job.integration_id,
                "job_type": job.job_type,
                "created_at": job.created_at.isoformat() if job.created_at else None,
            },
            "datasets": [
                {
                    "id": ds.id,
                    "name": ds.name,
                    "uri": ds.uri,
                    "type": ds.dataset_type,
                    "columns": ds.columns_json or [],
                }
                for ds in datasets
            ],
            "transformations": [
                {
                    "id": t.id,
                    "name": t.name,
                    "operation_type": t.operation_type,
                    "parameters": t.parameters_json,
                    "order_index": t.order_index,
                    "columns_affected": t.columns_affected or [],
                }
                for t in transformations
            ],
            "column_lineage": [
                {
                    "source_dataset": e.source_dataset,
                    "source_column": e.source_column,
                    "target_dataset": e.target_dataset,
                    "target_column": e.target_column,
                    "transformations": e.transformations_json or [],
                }
                for e in edges
            ],
            "dag": execution.dag_json if execution else None,
            "execution": {
                "id": execution.id,
                "started_at": execution.started_at.isoformat() if execution and execution.started_at else None,
                "completed_at": execution.completed_at.isoformat() if execution and execution.completed_at else None,
                "status": execution.status if execution else None,
                "spline_plan_id": execution.spline_plan_id if execution else None,
            } if execution else None,
        }

    finally:
        db.close()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GET /lineage/jobs — List all lineage jobs
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/jobs")
def list_lineage_jobs(
    integration_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """List all lineage jobs, newest first."""
    if not is_db_available():
        return {"jobs": [], "total": 0}

    db = SessionLocal()
    try:
        q = db.query(LineageJob)
        if integration_id:
            q = q.filter(LineageJob.integration_id == integration_id)

        total = q.count()
        jobs = q.order_by(LineageJob.created_at.desc()).limit(limit).all()

        return {
            "jobs": [
                {
                    "id": j.id,
                    "name": j.name,
                    "integration_id": j.integration_id,
                    "job_type": j.job_type,
                    "created_at": j.created_at.isoformat() if j.created_at else None,
                }
                for j in jobs
            ],
            "total": total,
        }
    finally:
        db.close()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GET /lineage/{integration_id}/graph — Spline URL (backward compatible)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/{integration_id}/graph")
def get_spline_graph_url(
    integration_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Returns the Spline URL for the most recent pipeline run of this integration.
    Backward-compatible with the original endpoint.
    """
    if not is_db_available():
        return {"spline_url": None, "last_run": None}

    run = (
        db.query(PipelineRun)
        .filter(PipelineRun.integration_id == integration_id)
        .order_by(PipelineRun.started_at.desc())
        .first()
    )

    last_run_data = None
    if run:
        last_run_data = {
            "id": run.id,
            "status": run.status,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "tables_scanned": run.tables_scanned or [],
            "row_counts": run.row_counts or {},
            "integration_name": run.integration_name,
        }

    # ── Build Spline Web UI URL directly from stored plan ID ─────────────────
    spline_url = None
    if run and run.spline_plan_id:
        import src.core.config as config
        # Use plan overview URL — no need to re-query consumer to find event ID
        spline_url = f"{config.SPLINE_WEB_UI}/app/plans/overview/{run.spline_plan_id}"

    return {
        "spline_url": spline_url,
        "last_run": last_run_data,
    }

