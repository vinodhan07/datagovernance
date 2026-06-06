"""
pipeline.py — Run ETL pipeline and stream progress to the browser via SSE.

Two paths:
  MariaDB → discover tables → PySpark ETL → Spline lineage sync
  GitHub  → fetch etl.py   → subprocess   → Spline lineage sync

All DB connection values come from config.py (loaded from .env).
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
import time
import uuid
import os
from datetime import datetime, timezone

import requests as http_requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import config
from database import get_db
from models import PipelineRun, Integration
from integrations_service import get_connection_config
from engines.spline_consumer_sync import (
    fetch_latest_event, fetch_execution_plan,
    build_lineage_data_from_plan, build_fallback_lineage_data,
)
from engines.lineage_persistence import persist_lineage

logger = logging.getLogger("dataguard.pipeline")
router = APIRouter()


# ── SSE helpers ───────────────────────────────────────────────────────────────

def _event(level: str, msg: str) -> str:
    ts = datetime.now().strftime("%H:%M:%S")
    return f"data: {json.dumps({'level': level, 'msg': msg, 'ts': ts})}\n\n"


# ── PostgreSQL helpers ────────────────────────────────────────────────────────

def _pg_parts() -> tuple[str, str, str, int, str]:
    """
    Parse POSTGRES_URL → (user, password, host, port, dbname).
    Used to build JDBC URLs and to connect to 'postgres' for CREATE DATABASE.
    """
    url = config.POSTGRES_URL               # e.g. postgresql://user:pass@host:5432/dataguard
    creds_rest  = url.split("://", 1)[1]    # user:pass@host:5432/dataguard
    creds, rest = creds_rest.split("@", 1)  # user:pass  |  host:5432/dataguard
    user, pw    = (creds.split(":", 1) + [""])[:2]
    host_port, db = rest.split("/", 1)
    host, port  = (host_port.split(":") + ["5432"])[:2]
    return user, pw, host, int(port), db


def _ensure_target_db() -> None:
    """Create company_data DB in PostgreSQL if it doesn't exist yet."""
    user, pw, host, port, _ = _pg_parts()
    admin_url = f"postgresql://{user}:{pw}@{host}:{port}/postgres"
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :db"),
            {"db": config.TARGET_DB},
        ).fetchone()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{config.TARGET_DB}"'))


def _target_jdbc() -> str:
    """JDBC URL pointing to the ETL output DB (company_data)."""
    user, pw, host, port, _ = _pg_parts()
    return f"jdbc:postgresql://{host}:{port}/{config.TARGET_DB}"


def _source_jdbc(creds: dict) -> str:
    """JDBC URL pointing to the MariaDB source DB."""
    return f"jdbc:mysql://{creds['host']}:{creds['port']}/{creds['database']}?permitMysqlScheme"


# ── Schema discovery (Python — fast, no Spark needed) ────────────────────────

def _discover_schema(creds: dict) -> dict[str, list]:
    """
    Return {table_name: [{"Field", "Type", "Key"}]} via pymysql.
    We use pymysql here (not JDBC) because it's instant — no JVM startup.
    The same tables are later read by Spark using JDBC for the bulk transfer.
    """
    import pymysql
    conn = pymysql.connect(
        host=creds["host"], port=int(creds["port"]),
        user=creds["user"], password=creds["password"],
        database=creds["database"], connect_timeout=10,
    )
    schema: dict[str, list] = {}
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW TABLES")
            for (tbl,) in cur.fetchall():
                cur.execute(f"DESCRIBE `{tbl}`")
                schema[tbl] = [{"Field": r[0], "Type": r[1], "Key": r[3]} for r in cur.fetchall()]
    finally:
        conn.close()
    return schema


# ── Spline lineage sync (shared by both pipeline paths) ──────────────────────

def _sync_lineage(db: Session, app_name: str, start_ms: int, run_id: str, integration_id: str):
    """
    After ETL completes, poll Spline Consumer and save column lineage to PostgreSQL.
    Retries up to 3 times (Spline may take a few seconds to process the event).
    """
    event = None
    for _ in range(3):
        event = fetch_latest_event(app_name, start_ms)
        if event:
            break
        time.sleep(3)

    if not event:
        return None, "no_spline_event"

    plan_id = event.get("executionPlanId")
    plan    = fetch_execution_plan(plan_id) if plan_id else None

    lineage_data = (
        build_lineage_data_from_plan(plan, event, integration_id)
        if plan else
        build_fallback_lineage_data("etl", "", "", [], integration_id, app_name)
    )
    persist_lineage(db, lineage_data, pipeline_run_id=run_id, spline_plan_id=plan_id)
    return plan_id, "ok"


# ── Route handlers ────────────────────────────────────────────────────────────

@router.get("/{integration_id}/run")
async def run_pipeline(integration_id: str, db: Session = Depends(get_db)):
    return StreamingResponse(_pipeline_sse(integration_id, db), media_type="text/event-stream")


@router.get("/{integration_id}/latest")
async def get_latest_run(integration_id: str, db: Session = Depends(get_db)):
    run = (
        db.query(PipelineRun)
        .filter(PipelineRun.integration_id == integration_id)
        .order_by(PipelineRun.started_at.desc())
        .first()
    )
    if not run:
        raise HTTPException(404, "No pipeline runs found")
    return run


@router.get("/{integration_id}/history")
async def get_history(integration_id: str, db: Session = Depends(get_db)):
    return (
        db.query(PipelineRun)
        .filter(PipelineRun.integration_id == integration_id)
        .order_by(PipelineRun.started_at.desc())
        .limit(20)
        .all()
    )


# ── Pipeline dispatcher ───────────────────────────────────────────────────────

async def _pipeline_sse(integration_id: str, db: Session):
    integration = db.query(Integration).filter(Integration.id == integration_id).first()
    if integration and integration.provider == "GitHub":
        async for chunk in _github_pipeline(integration_id, db, integration):
            yield chunk
    else:
        async for chunk in _mariadb_pipeline(integration_id, db):
            yield chunk


# ════════════════════════════════════════════════════════════════════════════════
# PATH A — MariaDB pipeline
# ════════════════════════════════════════════════════════════════════════════════

async def _mariadb_pipeline(integration_id: str, db: Session):
    run_id = None
    try:
        yield _event("INFO", "Initialising MariaDB pipeline...")

        integration = db.query(Integration).filter(Integration.id == integration_id).first()
        creds       = get_connection_config(db, integration_id)
        if not creds:
            yield _event("ERROR", "Integration credentials not found"); return

        # ── Create run record ─────────────────────────────────────────────────
        run_id = str(uuid.uuid4())
        db.add(PipelineRun(id=run_id, integration_id=integration_id,
                           integration_name=integration.name if integration else "Unknown",
                           status="running"))
        db.commit()

        # ── Discover source schema via pymysql ────────────────────────────────
        yield _event("INFO", "Discovering source tables...")
        schema = _discover_schema(creds)
        tables = list(schema.keys())
        if not tables:
            yield _event("ERROR", "No tables found in source database"); return
        yield _event("OK", f"Found {len(tables)} table(s): {', '.join(tables)}")

        # ── Create target DB ──────────────────────────────────────────────────
        yield _event("INFO", f"Ensuring PostgreSQL target '{config.TARGET_DB}' exists...")
        _ensure_target_db()
        yield _event("OK", f"Target database '{config.TARGET_DB}' ready")

        # ── Start Spark session (downloads JARs on first run ~3 min) ──────────
        from engines.spark_etl import create_spark_session, run_table_etl
        app_name  = f"DataGuard ETL: {creds.get('database', '')}"
        yield _event("INFO", "Starting Spark + Spline Agent (first run downloads JARs)...")
        spark = create_spark_session(app_name)
        yield _event("OK", "Spark ready — Spline Agent capturing column lineage")

        # ── ETL per table ─────────────────────────────────────────────────────
        source_jdbc = _source_jdbc(creds)
        target_jdbc = _target_jdbc()
        user, pw, _, _, _ = _pg_parts()
        row_counts: dict[str, int] = {}
        all_plan_ids: list[str]    = []

        for table in tables:
            yield _event("INFO", f"[{table}] Running ETL...")
            start_ms = int(time.time() * 1000)
            t0 = time.time()
            pk = next((c["Field"] for c in schema[table] if c.get("Key") == "PRI"), None)

            try:
                cols, rows = run_table_etl(
                    table, source_jdbc, creds["user"], creds["password"],
                    target_jdbc, user, pw, spark, primary_key=pk,
                )
                row_counts[table] = rows
                yield _event("OK", f"[{table}] {rows} rows in {time.time()-t0:.1f}s")
            except Exception as etl_err:
                yield _event("ERROR", f"[{table}] ETL failed: {etl_err}")
                row_counts[table] = 0
                cols = [c["Field"] for c in schema[table]]

            # ── Sync Spline lineage for this table ────────────────────────────
            yield _event("INFO", f"[{table}] Syncing lineage...")
            plan_id, status = _sync_lineage(db, app_name, start_ms, run_id, integration_id)
            if plan_id:
                all_plan_ids.append(plan_id)
                yield _event("OK", f"[{table}] Lineage saved (plan {plan_id[:8]}...)")
            else:
                yield _event("WARNING", f"[{table}] Spline event not found — fallback lineage saved")

        # ── Finalise run record ───────────────────────────────────────────────
        db.query(PipelineRun).filter(PipelineRun.id == run_id).update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc),
            "tables_scanned": tables,
            "row_counts": row_counts,
            "spline_plan_id": all_plan_ids[-1] if all_plan_ids else None,
        })
        db.commit()
        yield _event("DONE", f"Pipeline complete — {len(tables)} tables, lineage captured in Spline")

    except Exception as exc:
        logger.error("MariaDB pipeline failed: %s", exc, exc_info=True)
        _fail_run(db, run_id, exc)
        yield _event("ERROR", f"Pipeline failed: {exc}")


# ════════════════════════════════════════════════════════════════════════════════
# PATH B — GitHub pipeline
# ════════════════════════════════════════════════════════════════════════════════

async def _github_pipeline(integration_id: str, db: Session, integration: Integration):
    run_id = None
    try:
        yield _event("INFO", "GitHub pipeline initialising...")

        creds    = get_connection_config(db, integration_id)
        if not creds:
            yield _event("ERROR", "Integration credentials not found"); return

        owner    = creds["owner"]
        repo     = creds["repo"]
        filepath = creds["filepath"]
        branch   = creds["branch"]
        token    = creds["token"]
        headers  = {"Authorization": f"token {token}"} if token else {}

        # ── Download ETL script from GitHub ───────────────────────────────────
        yield _event("INFO", f"Fetching '{filepath}' from {owner}/{repo}@{branch}...")
        raw_url  = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{filepath}"
        resp     = http_requests.get(raw_url, headers=headers, timeout=15)
        if resp.status_code != 200:
            yield _event("ERROR", f"Cannot download script: HTTP {resp.status_code}"); return

        # Patch Scala companion-object syntax illegal in Python:
        # init_cls.MODULE$.method() → getattr(init_cls, "MODULE$").method()
        script = re.sub(r'(\w+)\.MODULE\$\.(\w+)\(', r'getattr(\1, "MODULE$").\2(', resp.text)
        # Patch jdbc:mariadb to jdbc:mysql with permitMysqlScheme to fix PySpark decoding issues
        script = script.replace("jdbc:mariadb://", "jdbc:mysql://")
        script = script.replace("/{MARIADB_DB}\"", "/{MARIADB_DB}?permitMysqlScheme\"")
        script = script.replace("/{MARIADB_DB}'", "/{MARIADB_DB}?permitMysqlScheme'")
        yield _event("OK", f"Script downloaded ({len(script)} bytes)")

        # ── Create run record ─────────────────────────────────────────────────
        run_id = str(uuid.uuid4())
        db.add(PipelineRun(id=run_id, integration_id=integration_id,
                           integration_name=integration.name, status="running"))
        db.commit()

        # ── Ensure target DB exists before script tries to write ──────────────
        yield _event("INFO", f"Ensuring '{config.TARGET_DB}' database exists...")
        _ensure_target_db()
        yield _event("OK", f"'{config.TARGET_DB}' ready")

        # ── Write to temp file and execute ────────────────────────────────────
        venv_python = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", ".venv", "bin", "python")
        )
        if not os.path.isfile(venv_python):
            venv_python = sys.executable

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", prefix="etl_",
                                         delete=False, dir="/tmp") as tmp:
            tmp.write(script)
            tmp_path = tmp.name

        # Try to find a MariaDB integration in the database to pass dynamic credentials to the script
        mariadb_integration = db.query(Integration).filter(Integration.provider == "MariaDB").first()
        if mariadb_integration:
            m_creds = get_connection_config(db, mariadb_integration.id) or {}
            m_host = m_creds.get("host") or config.MARIADB_HOST
            m_port = str(m_creds.get("port") or config.MARIADB_PORT)
            m_db   = m_creds.get("database") or config.MARIADB_DB
            m_user = m_creds.get("user") or config.MARIADB_USER
            m_pass = m_creds.get("password") or config.MARIADB_PASS
        else:
            m_host = config.MARIADB_HOST
            m_port = str(config.MARIADB_PORT)
            m_db   = config.MARIADB_DB
            m_user = config.MARIADB_USER
            m_pass = config.MARIADB_PASS

        # Pass all DB connection values dynamically so script doesn't need them hardcoded
        env = {
            **os.environ,
            "JDK_JAVA_OPTIONS":   "--add-opens=java.base/sun.net.www.protocol.jar=ALL-UNNAMED",
            "MARIADB_HOST":        m_host,
            "MARIADB_PORT":        m_port,
            "MARIADB_DB":          m_db,
            "MARIADB_USER":        m_user,
            "MARIADB_PASS":        m_pass,
            "POSTGRES_URL":        config.POSTGRES_URL,
            "SPLINE_PRODUCER_URL": config.SPLINE_PRODUCER,
        }

        yield _event("INFO", "Executing ETL script (first run ~3 min for JAR downloads)...")
        start_ms = int(time.time() * 1000)
        start_ts = time.time()

        try:
            proc = subprocess.run([venv_python, tmp_path],
                                  capture_output=True, text=True, timeout=600, env=env)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        elapsed = time.time() - start_ts

        if proc.returncode != 0:
            stderr = proc.stderr or ""
            # Extract the most useful lines: exception messages + last stack frames
            error_lines = [l for l in stderr.splitlines()
                           if any(k in l for k in ("Exception", "Error:", "Caused by", "WARN Failed", "[WARN]"))]
            summary = "\n".join(error_lines[-30:]) if error_lines else stderr[-2000:]
            yield _event("ERROR", f"ETL script failed (exit {proc.returncode}) after {elapsed:.0f}s:\n{summary}")
            _fail_run(db, run_id, proc.stderr[-2000:])
            return

        yield _event("OK", f"ETL script completed in {elapsed:.0f}s")
        for line in (proc.stdout or "").splitlines()[-20:]:
            if line.strip():
                yield _event("LOG", line.strip())

        # ── Sync Spline lineage ───────────────────────────────────────────────
        yield _event("INFO", "Syncing Spline lineage...")
        plan_id, status = _sync_lineage(db, "DataGuard ETL", start_ms, run_id, integration_id)

        db.query(PipelineRun).filter(PipelineRun.id == run_id).update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc),
            "spline_plan_id": plan_id,
        })
        db.commit()

        if plan_id:
            yield _event("OK", f"Lineage saved — plan {plan_id[:8]}...")
        else:
            yield _event("WARNING", "Spline event not found — check Spline UI at {config.SPLINE_WEB_UI}")

        yield _event("DONE", "GitHub ETL pipeline completed — view lineage at {config.SPLINE_WEB_UI}")

    except Exception as exc:
        logger.error("GitHub pipeline failed: %s", exc, exc_info=True)
        _fail_run(db, run_id, exc)
        yield _event("ERROR", f"Pipeline failed: {exc}")


# ── Shared helper ─────────────────────────────────────────────────────────────

def _fail_run(db: Session, run_id: str | None, error) -> None:
    if not run_id:
        return
    try:
        db.rollback()
        db.query(PipelineRun).filter(PipelineRun.id == run_id).update({
            "status": "failed",
            "error_message": str(error)[:2000],
            "completed_at": datetime.now(timezone.utc),
        })
        db.commit()
    except Exception:
        pass
