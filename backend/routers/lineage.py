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

from database import get_db, SessionLocal, is_db_available
from models import (
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

@router.get("/graph")
def get_lineage_graph_data(
    job_id: Optional[str] = Query(None, description="Job ID to show graph for"),
    integration_id: Optional[str] = Query(None, description="Integration ID"),
) -> dict[str, Any]:
    """
    Return the transformation DAG in React Flow compatible format.

    Returns nodes (datasets + operations) and edges with column metadata.
    """
    if not is_db_available():
        return {"nodes": [], "edges": []}

    db = SessionLocal()
    try:
        # Find the latest execution with a DAG
        q = db.query(LineageExecution)
        if job_id:
            q = q.filter(LineageExecution.job_id == job_id)
        elif integration_id:
            # Find jobs for this integration
            job_ids = [
                j.id for j in
                db.query(LineageJob).filter(LineageJob.integration_id == integration_id).all()
            ]
            if job_ids:
                q = q.filter(LineageExecution.job_id.in_(job_ids))

        execution = q.order_by(LineageExecution.created_at.desc()).first()

        if execution and execution.dag_json:
            return execution.dag_json

        # Fallback: build from edges
        edges = db.query(LineageEdge)
        if integration_id:
            job_ids_list = [
                j.id for j in
                db.query(LineageJob).filter(LineageJob.integration_id == integration_id).all()
            ]
            if job_ids_list:
                edges = edges.filter(LineageEdge.job_id.in_(job_ids_list))

        edge_list = edges.all()
        if not edge_list:
            return {"nodes": [], "edges": []}

        # Build simple graph from edges
        nodes_dict: dict[str, dict[str, Any]] = {}
        graph_edges: list[dict[str, Any]] = []

        for i, e in enumerate(edge_list):
            # Source node
            src_id = f"ds:{e.source_dataset}"
            if src_id not in nodes_dict:
                nodes_dict[src_id] = {
                    "id": src_id,
                    "type": "dataset",
                    "data": {"label": f"{e.source_dataset} (Source)", "columns": []},
                    "position": {"x": 0, "y": 0},
                }
            if e.source_column not in nodes_dict[src_id]["data"]["columns"]:
                nodes_dict[src_id]["data"]["columns"].append(e.source_column)

            # Target node
            tgt_id = f"ds:{e.target_dataset}"
            if tgt_id not in nodes_dict:
                nodes_dict[tgt_id] = {
                    "id": tgt_id,
                    "type": "dataset",
                    "data": {"label": f"{e.target_dataset} (Target)", "columns": []},
                    "position": {"x": 500, "y": 0},
                }
            if e.target_column not in nodes_dict[tgt_id]["data"]["columns"]:
                nodes_dict[tgt_id]["data"]["columns"].append(e.target_column)

            # Transform nodes from transformations
            transforms = e.transformations_json or []
            if transforms:
                for j, t_name in enumerate(transforms):
                    op_id = f"op:{e.source_column}:{t_name}"
                    if op_id not in nodes_dict:
                        nodes_dict[op_id] = {
                            "id": op_id,
                            "type": "operation",
                            "data": {
                                "label": f"{t_name}({e.source_column})",
                                "operation": t_name,
                            },
                            "position": {"x": 250, "y": j * 80},
                        }

            # Edges
            if transforms:
                first_op = f"op:{e.source_column}:{transforms[0]}"
                graph_edges.append({
                    "id": f"e-src-{i}-0",
                    "source": src_id,
                    "target": first_op,
                    "data": {"columns": [e.source_column]},
                })
                for j in range(1, len(transforms)):
                    prev_op = f"op:{e.source_column}:{transforms[j-1]}"
                    curr_op = f"op:{e.source_column}:{transforms[j]}"
                    graph_edges.append({
                        "id": f"e-op-{i}-{j}",
                        "source": prev_op,
                        "target": curr_op,
                        "data": {"columns": [e.source_column]},
                    })
                last_op = f"op:{e.source_column}:{transforms[-1]}"
                graph_edges.append({
                    "id": f"e-tgt-{i}",
                    "source": last_op,
                    "target": tgt_id,
                    "data": {"columns": [e.target_column]},
                })
            else:
                graph_edges.append({
                    "id": f"e-direct-{i}",
                    "source": src_id,
                    "target": tgt_id,
                    "data": {"columns": [e.source_column]},
                })

        # Layout nodes
        nodes = list(nodes_dict.values())
        _layout_nodes(nodes)

        return {"nodes": nodes, "edges": graph_edges}

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

    if not run or not run.spline_plan_id:
        return {"spline_url": None, "last_run": None}

    spline_web_ui_url = os.getenv("SPLINE_WEB_UI_URL", "http://localhost:9090")
    consumer_url = os.getenv("SPLINE_CONSUMER_URL", "http://localhost:8080/consumer")

    # Attempt to resolve the event ID for the plan
    event_id = None
    try:
        resp = requests.get(f"{consumer_url}/execution-events?limit=200", timeout=5)
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            for item in items:
                if item.get("executionPlanId") == run.spline_plan_id:
                    event_id = item.get("executionEventId")
                    break
    except Exception as exc:
        logger.warning("Error fetching event ID from Spline consumer: %s", exc)

    if event_id:
        spline_url = f"{spline_web_ui_url}/app/events/overview/{event_id}"
    else:
        spline_url = f"{spline_web_ui_url}/app/plans/overview/{run.spline_plan_id}"

    return {
        "spline_url": spline_url,
        "last_run": {
            "id": run.id,
            "status": run.status,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
        },
    }
