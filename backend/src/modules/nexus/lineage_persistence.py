"""
lineage_persistence.py — Save lineage_data dict to PostgreSQL.

Called after every pipeline run. Takes the dict built by
spline_consumer_sync.py and saves it across 6 tables:
  LineageJob → LineageDataset → LineageColumn
  LineageTransformation → LineageEdge → LineageExecution
"""
from __future__ import annotations
import logging
import uuid
from sqlalchemy.orm import Session

import src.core.config as config
from src.domain.entities import (
    LineageJob, LineageDataset, LineageColumn,
    LineageTransformation, LineageEdge, LineageExecution,
)

logger = logging.getLogger("dataguard.lineage.persist")


def persist_lineage(db: Session, lineage_data: dict,
                    pipeline_run_id: str | None = None,
                    spline_plan_id: str | None = None) -> str:
    """
    Save lineage_data to PostgreSQL. Returns the job_id saved.

    lineage_data shape (from spline_consumer_sync.build_lineage_data_from_plan):
      {
        "job":            {id, name, integration_id, started_at, completed_at}
        "dataset_lineage":[{source_dataset, source_uri, target_dataset, target_uri,
                            transformation, column_lineage:[...]}]
        "column_lineage": [{source_dataset, source_column, target_dataset,
                            target_column, transformations:[...]}]
        "transformations":[{id, function_name, operation, parameters,
                            order_index, columns_affected}]
        "dag":            {nodes:[], edges:[]}
      }
    """
    try:
        job_info = lineage_data.get("job", {})
        job_id   = job_info.get("id") or str(uuid.uuid4())

        # ── 1. Job ────────────────────────────────────────────────────────────
        db.add(LineageJob(
            id=job_id,
            name=job_info.get("name", "ETL"),
            integration_id=job_info.get("integration_id", ""),
            job_type="etl",
        ))

        # ── 2. Datasets (source + target) ─────────────────────────────────────
        dataset_ids: dict[str, str] = {}
        for ds in lineage_data.get("dataset_lineage", []):
            for role, name_key, uri_key, col_key in [
                ("source", "source_dataset", "source_uri",  "source_column"),
                ("target", "target_dataset", "target_uri",  "target_column"),
            ]:
                name = ds.get(name_key, "")
                if not name or name in dataset_ids:
                    continue
                ds_id = str(uuid.uuid4())
                dataset_ids[name] = ds_id
                db.add(LineageDataset(
                    id=ds_id, job_id=job_id, name=name,
                    uri=ds.get(uri_key, ""),
                    dataset_type=role,
                    columns_json=[cl.get(col_key) for cl in ds.get("column_lineage", [])],
                ))

        # ── 3. Columns ────────────────────────────────────────────────────────
        for ds_name, ds_id in dataset_ids.items():
            seen: set[str] = set()
            for cl in lineage_data.get("column_lineage", []):
                for col_key in ("source_column", "target_column"):
                    if cl.get(f"{col_key.split('_')[0]}_dataset") == ds_name:
                        col = cl.get(col_key, "")
                        if col and col not in seen:
                            seen.add(col)
                            db.add(LineageColumn(id=str(uuid.uuid4()), dataset_id=ds_id, name=col))

        # ── 4. Transformations ────────────────────────────────────────────────
        for xf in lineage_data.get("transformations", []):
            db.add(LineageTransformation(
                id=xf.get("id") or str(uuid.uuid4()),
                job_id=job_id,
                name=xf.get("function_name", "unknown"),
                operation_type=xf.get("operation", "unknown"),
                parameters_json=xf.get("parameters"),
                order_index=xf.get("order_index", 0),
                columns_affected=xf.get("columns_affected"),
            ))

        # ── 5. Column edges (source_col → target_col) ─────────────────────────
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

        # ── 6. Execution record (links to pipeline run + Spline plan) ─────────
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
        logger.info("Lineage saved: job=%s run=%s spline=%s", job_id, pipeline_run_id, spline_plan_id)
        return job_id

    except Exception as exc:
        db.rollback()
        logger.error("persist_lineage failed: %s", exc, exc_info=True)
        raise
