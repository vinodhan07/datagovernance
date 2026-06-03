"""
lineage_persistence.py
═══════════════════════
Persists lineage tracker output into PostgreSQL lineage tables.

Called after a pipeline run completes to save lineage metadata
for later querying by the visualization and impact analysis APIs.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from models import (
    LineageJob,
    LineageDataset,
    LineageColumn,
    LineageTransformation,
    LineageEdge,
    LineageExecution,
)

logger = logging.getLogger("dataguard.lineage.persist")


def persist_lineage(
    db: Session,
    lineage_data: dict[str, Any],
    pipeline_run_id: str | None = None,
    spline_plan_id: str | None = None,
) -> str:
    """
    Save lineage tracker output to the database.

    Args:
        db: SQLAlchemy session
        lineage_data: Output from LineageTracker.finalize()
        pipeline_run_id: Optional pipeline run ID to link to
        spline_plan_id: Optional Spline plan ID

    Returns:
        The job_id of the saved lineage
    """
    try:
        job_info = lineage_data.get("job", {})
        job_id = job_info.get("id", str(uuid.uuid4()))

        # 1. Save LineageJob
        db.add(LineageJob(
            id=job_id,
            name=job_info.get("name", "Unknown ETL"),
            integration_id=job_info.get("integration_id", ""),
            job_type="etl",
        ))

        # 2. Save LineageDatasets (from dataset_lineage)
        dataset_ids: dict[str, str] = {}  # name -> id
        for ds in lineage_data.get("dataset_lineage", []):
            # Source dataset
            src_name = ds.get("source_dataset", "")
            if src_name and src_name not in dataset_ids:
                ds_id = str(uuid.uuid4())
                dataset_ids[src_name] = ds_id
                db.add(LineageDataset(
                    id=ds_id,
                    job_id=job_id,
                    name=src_name,
                    uri=ds.get("source_uri", ""),
                    dataset_type="source",
                    columns_json=[
                        cl.get("source_column")
                        for cl in ds.get("column_lineage", [])
                    ],
                ))

            # Target dataset
            tgt_name = ds.get("target_dataset", "")
            if tgt_name and tgt_name not in dataset_ids:
                ds_id = str(uuid.uuid4())
                dataset_ids[tgt_name] = ds_id
                db.add(LineageDataset(
                    id=ds_id,
                    job_id=job_id,
                    name=tgt_name,
                    uri=ds.get("target_uri", ""),
                    dataset_type="target",
                    columns_json=[
                        cl.get("target_column")
                        for cl in ds.get("column_lineage", [])
                    ],
                ))

        # 3. Save LineageColumns
        for ds_name, ds_id in dataset_ids.items():
            cols_seen: set[str] = set()
            for cl in lineage_data.get("column_lineage", []):
                # Source columns
                if cl.get("source_dataset") == ds_name and cl.get("source_column") not in cols_seen:
                    col_name = cl["source_column"]
                    cols_seen.add(col_name)
                    db.add(LineageColumn(
                        id=str(uuid.uuid4()),
                        dataset_id=ds_id,
                        name=col_name,
                    ))
                # Target columns
                if cl.get("target_dataset") == ds_name and cl.get("target_column") not in cols_seen:
                    col_name = cl["target_column"]
                    cols_seen.add(col_name)
                    db.add(LineageColumn(
                        id=str(uuid.uuid4()),
                        dataset_id=ds_id,
                        name=col_name,
                    ))

        # 4. Save LineageTransformations
        for xform in lineage_data.get("transformations", []):
            db.add(LineageTransformation(
                id=xform.get("id", str(uuid.uuid4())),
                job_id=job_id,
                name=xform.get("function_name", "unknown"),
                operation_type=xform.get("operation", "unknown"),
                parameters_json=xform.get("parameters"),
                order_index=xform.get("order_index", 0),
                columns_affected=xform.get("columns_affected"),
            ))

        # 5. Save LineageEdges (column → column links)
        for cl in lineage_data.get("column_lineage", []):
            db.add(LineageEdge(
                id=str(uuid.uuid4()),
                job_id=job_id,
                source_dataset=cl.get("source_dataset", ""),
                source_column=cl.get("source_column", ""),
                target_dataset=cl.get("target_dataset", ""),
                target_column=cl.get("target_column", ""),
                transformations_json=cl.get("transformations"),
            ))

        # 6. Save LineageExecution
        db.add(LineageExecution(
            id=str(uuid.uuid4()),
            job_id=job_id,
            pipeline_run_id=pipeline_run_id,
            started_at=job_info.get("started_at"),
            completed_at=job_info.get("completed_at"),
            status="completed",
            lineage_json=lineage_data,
            dag_json=lineage_data.get("dag"),
            spline_plan_id=spline_plan_id,
        ))

        db.commit()
        logger.info("Lineage persisted: job_id=%s, pipeline_run=%s", job_id, pipeline_run_id)
        return job_id

    except Exception as exc:
        db.rollback()
        logger.error("Failed to persist lineage: %s", exc, exc_info=True)
        raise


def persist_github_lineage(
    db: Session,
    job_name: str,
    integration_id: str,
    sources: dict[str, list[str]],
    targets: dict[str, list[str]],
    transformations: list[str],
    pipeline_run_id: str | None = None,
    spline_plan_ids: list[str] | None = None,
) -> str:
    """
    Persist lineage metadata for a GitHub ETL pipeline run.

    GitHub pipelines don't execute real DataFrames, so lineage is derived
    from the parsed ETL script. This creates the same DB records as
    persist_lineage() so impact analysis and /lineage/jobs work uniformly.

    Returns the job_id of the saved lineage record.
    """
    from datetime import datetime, timezone

    try:
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        db.add(LineageJob(
            id=job_id,
            name=job_name,
            integration_id=integration_id,
            job_type="github",
        ))

        dataset_ids: dict[str, str] = {}

        for table_name, cols in sources.items():
            ds_id = str(uuid.uuid4())
            dataset_ids[f"src:{table_name}"] = ds_id
            db.add(LineageDataset(
                id=ds_id,
                job_id=job_id,
                name=table_name,
                uri=f"github://{table_name}",
                dataset_type="source",
                columns_json=cols,
            ))

        for table_name, cols in targets.items():
            ds_id = str(uuid.uuid4())
            dataset_ids[f"tgt:{table_name}"] = ds_id
            db.add(LineageDataset(
                id=ds_id,
                job_id=job_id,
                name=table_name,
                uri=f"postgresql://company_data/{table_name}",
                dataset_type="target",
                columns_json=cols,
            ))

        # Save transformations as LineageTransformation records
        for i, xform_name in enumerate(transformations):
            db.add(LineageTransformation(
                id=str(uuid.uuid4()),
                job_id=job_id,
                name=xform_name,
                operation_type="script_detected",
                parameters_json={"detected_from": "script_parse"},
                order_index=i,
                columns_affected=[],
            ))

        # Build column-level edges: source_col → target_col (same-name passthrough)
        for table_name, src_cols in sources.items():
            tgt_cols = targets.get(table_name, src_cols)
            for col in src_cols:
                if col in tgt_cols:
                    db.add(LineageEdge(
                        id=str(uuid.uuid4()),
                        job_id=job_id,
                        source_dataset=table_name,
                        source_column=col,
                        target_dataset=table_name,
                        target_column=col,
                        transformations_json=list(transformations),
                    ))

        # Build DAG for visualization
        dag_nodes = []
        dag_edges = []
        x = 0
        for table_name, cols in sources.items():
            dag_nodes.append({
                "id": f"src:{table_name}",
                "type": "dataset",
                "data": {"label": f"{table_name} (GitHub Source)", "columns": cols},
                "position": {"x": x, "y": 0},
            })
            x += 280

        x = 300
        for xform_name in transformations:
            op_id = f"op:{xform_name.replace(' ', '_')}"
            dag_nodes.append({
                "id": op_id,
                "type": "operation",
                "data": {"label": xform_name, "operation": "script_detected"},
                "position": {"x": x, "y": 150},
            })
            x += 280

        x = 600
        for table_name, cols in targets.items():
            dag_nodes.append({
                "id": f"tgt:{table_name}",
                "type": "dataset",
                "data": {"label": f"{table_name} (Target)", "columns": cols},
                "position": {"x": x, "y": 0},
            })
            x += 280

        # Connect source → first transform → last transform → target
        src_names = list(sources.keys())
        tgt_names = list(targets.keys())
        op_ids = [f"op:{t.replace(' ', '_')}" for t in transformations]

        edge_counter = 0
        if src_names and op_ids:
            dag_edges.append({"id": f"e{edge_counter}", "source": f"src:{src_names[0]}", "target": op_ids[0]})
            edge_counter += 1
        for i in range(1, len(op_ids)):
            dag_edges.append({"id": f"e{edge_counter}", "source": op_ids[i - 1], "target": op_ids[i]})
            edge_counter += 1
        if tgt_names and op_ids:
            dag_edges.append({"id": f"e{edge_counter}", "source": op_ids[-1], "target": f"tgt:{tgt_names[0]}"})
            edge_counter += 1
        elif tgt_names and src_names:
            dag_edges.append({"id": f"e{edge_counter}", "source": f"src:{src_names[0]}", "target": f"tgt:{tgt_names[0]}"})

        dag_json = {"nodes": dag_nodes, "edges": dag_edges}
        lineage_json: dict[str, Any] = {
            "job": {
                "id": job_id,
                "name": job_name,
                "integration_id": integration_id,
                "started_at": now,
                "completed_at": now,
            },
            "dataset_lineage": [],
            "column_lineage": [],
            "transformations": [{"function_name": t, "operation": "script_detected", "order_index": i} for i, t in enumerate(transformations)],
            "dag": dag_json,
        }

        db.add(LineageExecution(
            id=str(uuid.uuid4()),
            job_id=job_id,
            pipeline_run_id=pipeline_run_id,
            started_at=None,
            completed_at=None,
            status="completed",
            lineage_json=lineage_json,
            dag_json=dag_json,
            spline_plan_id=(spline_plan_ids[-1] if spline_plan_ids else None),
        ))

        db.commit()
        logger.info("GitHub lineage persisted: job_id=%s, tables=%s", job_id, list(targets.keys()))
        return job_id

    except Exception as exc:
        db.rollback()
        logger.error("Failed to persist GitHub lineage: %s", exc, exc_info=True)
        raise
