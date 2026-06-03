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
