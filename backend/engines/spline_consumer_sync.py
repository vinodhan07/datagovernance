"""
spline_consumer_sync.py — After ETL completes, sync lineage from Spline.

Flow:
  1. Poll Spline Consumer API for the execution event matching this run
  2. Fetch the execution plan (source/target URIs + attribute names)
  3. Query ArangoDB directly for column derivations
     (Consumer API returns properties:{} for nodes — ArangoDB has the real data)
  4. Return a lineage_data dict that lineage_persistence.py saves to PostgreSQL
"""

from __future__ import annotations
import logging
import time
import uuid
from datetime import datetime, timezone

import requests
import config  # noqa: E402

logger = logging.getLogger("dataguard.spline_sync")


# ── ArangoDB query helper ─────────────────────────────────────────────────────

def _arango(aql: str, bind_vars: dict | None = None) -> list:
    """Run an AQL query against Spline's ArangoDB. Returns result list."""
    try:
        resp = requests.post(
            f"{config.ARANGO_URL}/_db/{config.ARANGO_DB}/_api/cursor",
            json={"query": aql, "bindVars": bind_vars or {}, "batchSize": 200},
            timeout=8,
        )
        if resp.status_code in (200, 201):
            return resp.json().get("result", [])
    except Exception as exc:
        logger.debug("ArangoDB query failed: %s", exc)
    return []


# ── Column lineage from ArangoDB ──────────────────────────────────────────────

def _column_lineage_from_arango(plan_id: str, attr_map: dict[str, str],
                                 source_name: str, target_name: str) -> list[dict]:
    """
    Build column-level lineage by querying ArangoDB edge collections:
      produces    : Read operation → attributes it outputs  (source columns)
      derivesFrom : derived_attr  → source_attr             (transformed columns)

    For passthrough columns (not in derivesFrom), source_col == target_col.
    For transformed columns (e.g. abs(amount)), derivesFrom maps the new attr to old.
    """
    ep_id = f"executionPlan/{plan_id}"

    # Step 1: find source attribute IDs (produced by the Read operation)
    read_op_ids = _arango(
        "FOR op IN operation FILTER op._belongsTo == @ep AND op.type == 'Read' RETURN op._id",
        {"ep": ep_id},
    )
    if not read_op_ids:
        return []

    source_attr_ids: set[str] = set()
    for read_id in read_op_ids:
        produced = _arango("FOR e IN produces FILTER e._from == @op RETURN e._to", {"op": read_id})
        source_attr_ids.update(produced)

    # Step 2: derivesFrom  (new_attr_full_id → source_attr_full_id)
    derivations = _arango(
        "FOR e IN derivesFrom FILTER e._belongsTo == @ep RETURN {d: e._from, s: e._to}",
        {"ep": ep_id},
    )

    def _clean(full_id: str) -> str:
        return full_id.replace("attribute/", "")

    def _name(full_id: str) -> str:
        clean = _clean(full_id)
        return attr_map.get(clean, clean.split(":")[-1])

    # source_attr_id → derived_attr_id  (what the source becomes after transform)
    source_to_derived = {_clean(r["s"]): _clean(r["d"]) for r in derivations}

    result = []
    for src_full_id in source_attr_ids:
        src_id = _clean(src_full_id)
        src_col = _name(src_full_id)

        derived_id = source_to_derived.get(src_id)
        tgt_col = attr_map.get(derived_id, src_col) if derived_id else src_col
        is_transformed = derived_id is not None

        result.append({
            "source_dataset": source_name,
            "source_column":  src_col,
            "target_dataset": target_name,
            "target_column":  tgt_col,
            "transformations": ["transform"] if is_transformed else [],
        })

    return result


# ── Consumer API helpers ──────────────────────────────────────────────────────

def fetch_latest_event(app_name: str, since_ms: int) -> dict | None:
    """Poll Spline Consumer for the first event after since_ms matching app_name."""
    for attempt in range(config.SPLINE_POLL_RETRIES):
        try:
            resp = requests.get(
                f"{config.SPLINE_CONSUMER}/execution-events",
                params={"limit": config.SPLINE_PAGE_SIZE},
                timeout=10,
            )
            if resp.status_code == 200:
                for item in resp.json().get("items", []):
                    if item.get("timestamp", 0) < since_ms:
                        continue
                    # Fast path: applicationName field populated
                    if app_name.lower() in (item.get("applicationName") or "").lower():
                        return item
                    # Slow path: check plan's appName in ArangoDB extra field
                    plan_id = item.get("executionPlanId")
                    if plan_id:
                        plan = fetch_execution_plan(plan_id)
                        if not plan:
                            continue
                        stored = (plan.get("executionPlan", {}).get("extra") or {}).get("appName", "")
                        if app_name.lower() in stored.lower():
                            item["_resolved_plan"] = plan
                            return item
        except Exception as exc:
            logger.warning("Spline poll attempt %d failed: %s", attempt + 1, exc)

        if attempt < config.SPLINE_POLL_RETRIES - 1:
            time.sleep(config.SPLINE_POLL_DELAY)

    return None


def fetch_execution_plan(plan_id: str) -> dict | None:
    try:
        resp = requests.get(f"{config.SPLINE_CONSUMER}/execution-plans/{plan_id}", timeout=10)
        return resp.json() if resp.status_code == 200 else None
    except Exception as exc:
        logger.warning("Failed to fetch plan %s: %s", plan_id, exc)
        return None


# ── Build lineage_data from Spline plan ───────────────────────────────────────

def _table_name(uri: str) -> str:
    """Extract table name from JDBC URI. Spline appends :tablename to the DB name."""
    last = uri.split("/")[-1].split("?")[0]
    return last.rsplit(":", 1)[-1] if ":" in last else last


def build_lineage_data_from_plan(plan: dict, event: dict, integration_id: str) -> dict:
    """Convert a Spline plan + event into the lineage_data dict for persist_lineage()."""
    now     = datetime.now(timezone.utc).isoformat()
    ts_ms   = event.get("timestamp", 0)
    started = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat() if ts_ms else now

    ep       = plan.get("executionPlan", plan)
    plan_id  = ep.get("_id", "")

    # Source and target JDBC URIs (available directly in Consumer API response)
    raw_inputs = ep.get("inputs") or []
    source_uri = raw_inputs[0].get("source", "") if raw_inputs else ""
    target_uri = (ep.get("output") or {}).get("source", "")

    source_name = _table_name(source_uri) if source_uri else "source"
    target_name = _table_name(target_uri) if target_uri else "target"

    # Attribute map: full_attr_id → column_name
    attrs     = (ep.get("extra") or {}).get("attributes", [])
    attr_map  = {a["id"]: a["name"] for a in attrs if "id" in a}

    # Column lineage from ArangoDB (Consumer API strips node properties)
    col_lineage = _column_lineage_from_arango(plan_id, attr_map, source_name, target_name)

    # Fallback: passthrough by name if ArangoDB returned nothing
    if not col_lineage:
        seen: set[str] = set()
        for name in attr_map.values():
            if name not in seen:
                col_lineage.append({
                    "source_dataset": source_name, "source_column": name,
                    "target_dataset": target_name, "target_column": name,
                    "transformations": [],
                })
                seen.add(name)

    return {
        "job": {
            "id": str(uuid.uuid4()),
            "name": ep.get("name", plan_id or "PySpark ETL"),
            "integration_id": integration_id,
            "started_at": started,
            "completed_at": now,
        },
        "dataset_lineage": [{
            "source_dataset": source_name, "source_uri": source_uri,
            "target_dataset": target_name, "target_uri": target_uri,
            "transformation": "PySpark ETL",
            "column_lineage": col_lineage,
        }],
        "column_lineage": col_lineage,
        "transformations": [],
        "dag": {"nodes": [], "edges": []},
    }


def build_fallback_lineage_data(table: str, source_uri: str, target_uri: str,
                                 columns: list[str], integration_id: str, job_name: str) -> dict:
    """Used when Spline Consumer is unreachable. Creates passthrough column lineage."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "job": {"id": str(uuid.uuid4()), "name": job_name,
                "integration_id": integration_id, "started_at": now, "completed_at": now},
        "dataset_lineage": [{
            "source_dataset": table, "source_uri": source_uri,
            "target_dataset": table, "target_uri": target_uri,
            "transformation": "PySpark ETL",
            "column_lineage": [
                {"source_dataset": table, "source_column": c,
                 "target_dataset": table, "target_column": c, "transformations": []}
                for c in columns
            ],
        }],
        "column_lineage": [
            {"source_dataset": table, "source_column": c,
             "target_dataset": table, "target_column": c, "transformations": []}
            for c in columns
        ],
        "transformations": [],
        "dag": {"nodes": [], "edges": []},
    }
