"""
spline_engine.py
═══════════════════
Constructs and pushes data lineage execution plans and events to the
Spline Producer API.

Two modes:
  1. push_table_spline_lineage() — Legacy static lineage for GitHub pipelines
  2. push_lineage_to_spline()   — Dynamic lineage from LineageTracker (production)
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any, TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from engines.lineage_tracker import LineageTracker

logger = logging.getLogger("dataguard.spline")

# Default Spline Producer URL
PRODUCER_URL = os.getenv("SPLINE_PRODUCER_URL", "http://localhost:8080/producer")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# NEW: Dynamic lineage from LineageTracker
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def push_lineage_to_spline(
    tracker: LineageTracker,
    integration_name: str = "DataGuard",
) -> str | None:
    """
    Build a Spline execution plan from real LineageTracker data and push it.

    Instead of fabricating 1:1 column mappings, this reads the tracker's
    transformation DAG and creates proper multi-step operation nodes
    with accurate attribute lineage.

    Returns the plan_id on success, None on failure.
    """
    try:
        plan_id = str(uuid.uuid4())
        lineage_data = tracker.finalize()

        dataset_lineage = lineage_data.get("dataset_lineage", [])
        if not dataset_lineage:
            logger.warning("No dataset lineage found, skipping Spline push")
            return None

        transformations = lineage_data.get("transformations", [])
        column_lineage = lineage_data.get("column_lineage", [])

        # ── Build attributes ──────────────────────────────────────────────────

        all_attributes: list[dict[str, str]] = []
        # Source attribute IDs: keyed by "dataset:column"
        source_attr_map: dict[str, str] = {}
        # Target attribute IDs: keyed by "dataset:column"
        target_attr_map: dict[str, str] = {}

        # Create source attributes
        for ds in dataset_lineage:
            for cl in ds.get("column_lineage", []):
                src_key = f"{cl['source_dataset']}:{cl['source_column']}"
                if src_key not in source_attr_map:
                    attr_id = str(uuid.uuid4())
                    source_attr_map[src_key] = attr_id
                    all_attributes.append({
                        "id": attr_id,
                        "name": f"{cl['source_dataset']}.{cl['source_column']}",
                    })

        # Create target attributes
        for ds in dataset_lineage:
            for cl in ds.get("column_lineage", []):
                tgt_key = f"{cl['target_dataset']}:{cl['target_column']}"
                if tgt_key not in target_attr_map:
                    attr_id = str(uuid.uuid4())
                    target_attr_map[tgt_key] = attr_id
                    all_attributes.append({
                        "id": attr_id,
                        "name": cl["target_column"],
                    })

        # ── Build operations ──────────────────────────────────────────────────

        # Group transformations by type (skip read_sql and to_sql)
        transform_steps = [
            t for t in transformations
            if t["operation"] not in ("read_sql", "read_csv", "to_sql")
        ]

        # Source URIs (from first dataset lineage)
        source_uris = list({ds["source_uri"] for ds in dataset_lineage})
        target_uris = list({ds["target_uri"] for ds in dataset_lineage})

        # Operation 0: Read
        source_attr_ids = list(source_attr_map.values())
        read_op: dict[str, Any] = {
            "id": 0,
            "name": f"Read: {dataset_lineage[0]['source_dataset']}",
            "inputSources": source_uris,
            "output": source_attr_ids,
        }

        # Build intermediate operations from tracked transformations
        other_ops: list[dict[str, Any]] = []
        prev_op_id = 0  # read op

        # Create intermediate attribute IDs for transformation outputs
        intermediate_attrs: dict[int, list[str]] = {}

        for i, step in enumerate(transform_steps):
            op_id = i + 1
            op_name = step.get("function_name", step.get("operation", "Transform"))
            affected_cols = step.get("columns_affected", [])

            # Describe the operation clearly
            if affected_cols:
                col_desc = ", ".join(affected_cols[:3])
                if len(affected_cols) > 3:
                    col_desc += f" +{len(affected_cols) - 3}"
                op_name = f"{op_name}({col_desc})"

            # Create intermediate attributes for this step's output
            step_attr_ids: list[str] = []
            for col in affected_cols:
                attr_id = str(uuid.uuid4())
                step_attr_ids.append(attr_id)
                all_attributes.append({
                    "id": attr_id,
                    "name": f"{op_name}→{col}",
                })
            intermediate_attrs[op_id] = step_attr_ids

            op: dict[str, Any] = {
                "id": op_id,
                "name": op_name,
                "childIds": [prev_op_id],
            }
            if step_attr_ids:
                op["output"] = step_attr_ids

            # Add extra metadata
            params = step.get("parameters", {})
            if params:
                op["extra"] = {"parameters": params}

            other_ops.append(op)
            prev_op_id = op_id

        # Write operation
        write_op_id = len(transform_steps) + 1

        # Build attribute lineage: target attr → [source attr]
        attribute_lineage: dict[str, list[str]] = {}
        for cl in column_lineage:
            src_key = f"{cl['source_dataset']}:{cl['source_column']}"
            tgt_key = f"{cl['target_dataset']}:{cl['target_column']}"
            src_attr = source_attr_map.get(src_key)
            tgt_attr = target_attr_map.get(tgt_key)
            if src_attr and tgt_attr:
                attribute_lineage[tgt_attr] = [src_attr]

        target_attr_ids = list(target_attr_map.values())

        write_op: dict[str, Any] = {
            "id": write_op_id,
            "name": f"Write: {dataset_lineage[0]['target_dataset']}",
            "childIds": [prev_op_id],
            "outputSource": target_uris[0] if target_uris else "",
            "append": False,
            "output": target_attr_ids,
        }

        if attribute_lineage:
            write_op["attributeLineage"] = attribute_lineage

        # ── Build execution plan ──────────────────────────────────────────────

        plan: dict[str, Any] = {
            "id": plan_id,
            "name": f"DataGuard ETL: {integration_name} - {dataset_lineage[0]['target_dataset']}",
            "operations": {
                "write": write_op,
                "reads": [read_op],
                "other": other_ops,
            },
            "attributes": all_attributes,
            "systemInfo": {"name": "DataGuard", "version": "2.0.0"},
            "agentInfo": {"name": "DataGuard-LineageTracker", "version": "2.0.0"},
        }

        # ── Push plan ─────────────────────────────────────────────────────────

        logger.info("Pushing dynamic execution plan %s to %s...", plan_id, PRODUCER_URL)
        resp = requests.post(f"{PRODUCER_URL}/execution-plans", json=plan, timeout=30)
        if resp.status_code not in (200, 201):
            logger.error("Spline Plan Push failed (%d): %s", resp.status_code, resp.text)
            return None

        # ── Push event ────────────────────────────────────────────────────────

        event: dict[str, Any] = {
            "planId": plan_id,
            "timestamp": int(time.time() * 1000),
            "durationNs": 0,
            "error": None,
            "extra": {
                "app": "DataGuard",
                "lineage_version": "2.0",
                "transformations": len(transform_steps),
                "columns_tracked": len(column_lineage),
            },
        }
        resp_event = requests.post(f"{PRODUCER_URL}/execution-events", json=[event], timeout=30)
        if resp_event.status_code not in (200, 201):
            logger.error("Spline Event Push failed (%d): %s", resp_event.status_code, resp_event.text)
            return None

        logger.info(
            "SUCCESS: Dynamic lineage pushed — plan=%s, %d operations, %d attributes",
            plan_id, len(other_ops) + 2, len(all_attributes),
        )
        return plan_id

    except Exception as exc:
        logger.error("Spline push exception: %s", exc, exc_info=True)
        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LEGACY: Static lineage (kept for GitHub pipeline backward compat)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def push_table_spline_lineage(
    integration_name: str,
    table_name: str,
    columns: list[str],
    source_uri: str,
    target_uri: str,
    duration_seconds: float,
) -> str | None:
    """
    Legacy: pushes static column-wise lineage for a single table to Spline.
    Used only for GitHub pipelines where we don't have real DataFrames.
    """
    try:
        plan_id = str(uuid.uuid4())

        # 1. Attributes (Columns)
        all_attributes: list[dict[str, str]] = []
        source_attr_ids: list[str] = []
        target_attr_ids: list[str] = []
        attribute_lineage: dict[str, list[str]] = {}

        for col in columns:
            attr_id = str(uuid.uuid4())
            all_attributes.append({"id": attr_id, "name": f"{table_name}.{col}"})
            source_attr_ids.append(attr_id)

            target_id = str(uuid.uuid4())
            all_attributes.append({"id": target_id, "name": col})
            target_attr_ids.append(target_id)

            attribute_lineage[target_id] = [attr_id]

        # 2. Operations
        read_op: dict[str, Any] = {
            "id": 0,
            "name": f"Source Table: {table_name}",
            "inputSources": [source_uri],
            "output": source_attr_ids,
        }

        data_op: dict[str, Any] = {
            "id": 1,
            "name": "Deduplication & Clean",
            "childIds": [0],
            "output": target_attr_ids,
        }

        write_op: dict[str, Any] = {
            "id": 2,
            "name": "Target Store",
            "childIds": [1],
            "outputSource": target_uri,
            "append": False,
            "attributeLineage": attribute_lineage,
        }

        # 3. Execution Plan
        plan: dict[str, Any] = {
            "id": plan_id,
            "name": f"DataGuard ETL: {integration_name} - {table_name}",
            "operations": {
                "write": write_op,
                "reads": [read_op],
                "other": [data_op],
            },
            "attributes": all_attributes,
            "systemInfo": {"name": "DataGuard", "version": "1.0.0"},
            "agentInfo": {"name": "DataGuard-Agent", "version": "1.0.0"},
        }

        # 4. Push Plan
        logger.info("Pushing static plan %s for table %s to %s...", plan_id, table_name, PRODUCER_URL)
        resp = requests.post(f"{PRODUCER_URL}/execution-plans", json=plan, timeout=30)
        if resp.status_code not in (200, 201):
            logger.error("Plan push failed (%d): %s", resp.status_code, resp.text)
            return None

        # 5. Push Event
        event: dict[str, Any] = {
            "planId": plan_id,
            "timestamp": int(time.time() * 1000),
            "durationNs": int(duration_seconds * 1_000_000_000),
            "error": None,
            "extra": {"app": "DataGuard"},
        }
        resp_event = requests.post(f"{PRODUCER_URL}/execution-events", json=[event], timeout=30)
        if resp_event.status_code not in (200, 201):
            logger.error("Event push failed (%d): %s", resp_event.status_code, resp_event.text)
            return None

        logger.info("SUCCESS: Static lineage pushed for table %s (ID: %s)", table_name, plan_id)
        return plan_id

    except Exception as exc:
        logger.error("Spline push exception: %s", exc, exc_info=True)
        return None
