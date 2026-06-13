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

def _get_pg_table_info(table_name: str) -> tuple[list[dict], int]:
    """Query column definitions and row count for a PostgreSQL table in target DB."""
    user, pw, host, port, _ = _pg_parts()
    target_url = f"postgresql://{user}:{pw}@{host}:{port}/{config.TARGET_DB}"
    engine = create_engine(target_url)
    cols = []
    row_count = 0
    try:
        with engine.connect() as conn:
            res = conn.execute(
                text("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :tbl"),
                {"tbl": table_name}
            ).fetchall()
            for r in res:
                cols.append({"Field": r[0], "Type": r[1]})
            row_res = conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).fetchone()
            if row_res:
                row_count = row_res[0]
    except Exception as e:
        logger.warning(f"Could not get PG table info for {table_name}: {e}")
    return cols, row_count


def _sync_lineage(db: Session, app_name: str, start_ms: int, run_id: str, integration_id: str) -> tuple[str | None, str, dict]:
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
        return None, "no_spline_event", {}

    plan_id = event.get("executionPlanId")
    plan    = fetch_execution_plan(plan_id) if plan_id else None

    lineage_data = (
        build_lineage_data_from_plan(plan, event, integration_id)
        if plan else
        build_fallback_lineage_data("etl", "", "", [], integration_id, app_name)
    )
    persist_lineage(db, lineage_data, pipeline_run_id=run_id, spline_plan_id=plan_id)

    target_info = {}
    for dl in lineage_data.get("dataset_lineage", []):
        t = dl.get("target_dataset")
        if t and t not in ("target", "source"):
            cols, row_cnt = _get_pg_table_info(t)
            if not cols:
                seen_cols = set()
                for cl in dl.get("column_lineage", []):
                    if cl.get("target_dataset") == t:
                        seen_cols.add(cl.get("target_column"))
                cols = [{"Field": c, "Type": "VARCHAR"} for c in seen_cols if c]
            target_info[t] = {
                "schema": cols,
                "row_count": row_cnt
            }

    return plan_id, "ok", target_info


# ── Route handlers ────────────────────────────────────────────────────────────

@router.get("/{integration_id}/capabilities")
def get_capabilities(integration_id: str, db: Session = Depends(get_db)):
    """
    Pre-flight check — probe the integration source and return which features
    (lineage / catalog / quality) are available and why.
    """
    from engines.preflight_detector import detect_mariadb_capabilities, detect_github_capabilities
    from integrations_service import get_connection_config

    integration = db.query(Integration).filter(Integration.id == integration_id).first()
    if not integration:
        raise HTTPException(404, "Integration not found")

    creds = get_connection_config(db, integration_id)
    if not creds:
        return {
            "provider": integration.provider,
            "lineage":  {"available": False, "reason": "Credentials not found"},
            "catalog":  {"available": False, "reason": "Credentials not found"},
            "quality":  {"available": False, "reason": "Credentials not found"},
        }

    if integration.provider == "GitHub":
        result = detect_github_capabilities(
            token=creds.get("token", ""),
            owner=creds.get("owner", ""),
            repo=creds.get("repo", ""),
            branch=creds.get("branch", "main"),
        )
    else:
        result = detect_mariadb_capabilities(creds)

    return {
        "provider":   result.get("provider", integration.provider),
        "lineage":    result["capabilities"]["lineage"],
        "catalog":    result["capabilities"]["catalog"],
        "quality":    result["capabilities"]["quality"],
        "details":    {k: v for k, v in result.items() if k not in ("capabilities", "error", "provider")},
        "error":      result.get("error"),
    }


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

        # ── Auto-generate quality rules from schema (skips if rules exist) ────
        try:
            from engines.quality_auto_rules import auto_generate_rules
            n_rules = auto_generate_rules(db, integration_id, schema)
            if n_rules:
                yield _event("OK", f"Auto-generated {n_rules} quality rule(s) from schema")
        except Exception as qr_err:
            yield _event("INFO", f"Quality rule auto-generation skipped: {qr_err}")

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
            plan_id, status, _ = _sync_lineage(db, app_name, start_ms, run_id, integration_id)
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

        # ── Push table metadata to OpenMetadata catalog (non-blocking) ────────
        yield _event("INFO", "Pushing table metadata to catalog...")
        try:
            from engines.openmetadata_sync import push_table_metadata
            pushed = 0
            for table in tables:
                cols = [{"name": c["Field"], "data_type": c.get("Type", "VARCHAR")}
                        for c in schema.get(table, [])]
                if push_table_metadata(table, cols):
                    pushed += 1
            if pushed:
                yield _event("OK", f"Catalog updated — {pushed} table(s) pushed to OpenMetadata")
            else:
                yield _event("INFO", "Catalog push skipped (OpenMetadata not running or not configured)")
        except Exception as cat_err:
            yield _event("WARNING", f"Catalog push failed (non-fatal): {cat_err}")

        yield _event("DONE", f"Pipeline complete — {len(tables)} tables, lineage captured in Spline")

    except Exception as exc:
        logger.error("MariaDB pipeline failed: %s", exc, exc_info=True)
        _fail_run(db, run_id, exc)
        yield _event("ERROR", f"Pipeline failed: {exc}")


# ════════════════════════════════════════════════════════════════════════════════
# PATH B — GitHub pipeline (multi-file: scripts + data files + SQL files)
# ════════════════════════════════════════════════════════════════════════════════

async def _github_pipeline(integration_id: str, db: Session, integration: Integration):
    run_id = None
    try:
        yield _event("INFO", "GitHub pipeline initialising...")

        creds  = get_connection_config(db, integration_id)
        if not creds:
            yield _event("ERROR", "Integration credentials not found"); return

        owner  = creds["owner"]
        repo   = creds["repo"]
        branch = creds.get("branch", "main")
        token  = creds.get("token", "")
        gh_headers = {"Authorization": f"token {token}"} if token else {}

        # ── Detect what's in the repo ─────────────────────────────────────────
        yield _event("INFO", f"Scanning repository {owner}/{repo}@{branch}...")
        from engines.preflight_detector import detect_github_capabilities
        caps = detect_github_capabilities(token, owner, repo, branch)

        if caps.get("error"):
            yield _event("ERROR", caps["error"]); return

        script_files = caps["script_files"]
        data_files   = caps["data_files"]
        sql_files    = caps["sql_files"]

        total_files = len(script_files) + len(data_files) + len(sql_files)
        if total_files == 0:
            yield _event("ERROR",
                "No processable files found in repository.\n"
                "Expected: Python scripts (.py), data files (.csv/.json/.xlsx), or SQL files (.sql)."
            )
            return

        yield _event("OK",
            f"Found: {len(script_files)} script(s), {len(data_files)} data file(s), "
            f"{len(sql_files)} SQL file(s)"
        )

        # ── Create run record ─────────────────────────────────────────────────
        run_id = str(uuid.uuid4())
        db.add(PipelineRun(id=run_id, integration_id=integration_id,
                           integration_name=integration.name, status="running"))
        db.commit()

        # ── Ensure target DB exists ───────────────────────────────────────────
        yield _event("INFO", f"Ensuring '{config.TARGET_DB}' database exists...")
        _ensure_target_db()
        yield _event("OK", f"'{config.TARGET_DB}' ready")

        # Build MariaDB env vars for scripts that need them
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

        script_env = {
            **os.environ,
            "JDK_JAVA_OPTIONS":    "--add-opens=java.base/sun.net.www.protocol.jar=ALL-UNNAMED",
            "MARIADB_HOST":        m_host,
            "MARIADB_PORT":        m_port,
            "MARIADB_DB":          m_db,
            "MARIADB_USER":        m_user,
            "MARIADB_PASS":        m_pass,
            "POSTGRES_URL":        config.POSTGRES_URL,
            "SPLINE_PRODUCER_URL": config.SPLINE_PRODUCER,
        }

        venv_python = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", ".venv", "bin", "python")
        )
        if not os.path.isfile(venv_python):
            venv_python = sys.executable

        tables_loaded: dict[str, int]    = {}   # {table_name: row_count}
        loaded_schema: dict[str, list]   = {}   # for quality rule auto-generation
        all_plan_ids:  list[str]         = []

        # ════════════════════════════════════════════════════════════════════════
        # STEP 1 — Execute Python / script files (lineage via Spline)
        # ════════════════════════════════════════════════════════════════════════
        for filepath in script_files:
            ext = os.path.splitext(filepath)[1].lower()
            if ext not in (".py", ".ipynb", ".r", ".rb", ".scala"):
                continue

            yield _event("INFO", f"[script] Downloading {filepath}...")
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{filepath}"
            resp = http_requests.get(raw_url, headers=gh_headers, timeout=15)
            if resp.status_code != 200:
                yield _event("WARNING", f"[script] Cannot download {filepath}: HTTP {resp.status_code}")
                continue

            if ext == ".py":
                script = re.sub(r'(\w+)\.MODULE\$\.(\w+)\(', r'getattr(\1, "MODULE$").\2(', resp.text)
                script = script.replace("jdbc:mariadb://", "jdbc:mysql://")
                script = script.replace("/{MARIADB_DB}\"", "/{MARIADB_DB}?permitMysqlScheme\"")
                script = script.replace("/{MARIADB_DB}'", "/{MARIADB_DB}?permitMysqlScheme'")

                # ── Auto-inject Spline into any PySpark script ────────────────
                # If the script creates a SparkSession but hasn't configured the
                # Spline agent, patch it so lineage is captured automatically.
                if "SparkSession" in script and "spark.spline" not in script:
                    spline_pkg = (
                        f"za.co.absa.spline.agent.spark:"
                        f"spark-3.5-spline-agent-bundle_2.12:{config.SPLINE_AGENT_VER}"
                    )
                    spline_configs = (
                        f'\n    .config("spark.spline.producer.url",'
                        f' os.getenv("SPLINE_PRODUCER_URL", "{config.SPLINE_PRODUCER}"))'
                        f'\n    .config("spark.spline.mode", "ENABLED")'
                    )
                    # Inject Spline producer + mode before .getOrCreate()
                    script = re.sub(
                        r'(\.getOrCreate\(\))',
                        spline_configs + r'\1',
                        script,
                        count=1,
                    )
                    # Add Spline JAR to existing packages list, or inject new packages config
                    pkg_pattern = re.compile(
                        r'(\.config\(["\']spark\.jars\.packages["\'],\s*["\'])([^"\']+)(["\'])'
                    )
                    if pkg_pattern.search(script):
                        script = pkg_pattern.sub(
                            lambda m: m.group(1) + m.group(2) + f",{spline_pkg}" + m.group(3),
                            script,
                        )
                    else:
                        pkg_injection = (
                            f'\n    .config("spark.jars.packages", "{spline_pkg}")'
                        )
                        script = re.sub(
                            r'(\.getOrCreate\(\))',
                            pkg_injection + r'\1',
                            script,
                            count=1,
                        )
                    yield _event("INFO", f"[script] Spline auto-instrumentation injected into {filepath}")

                with tempfile.NamedTemporaryFile(mode="w", suffix=".py", prefix="etl_",
                                                 delete=False, dir="/tmp") as tmp:
                    tmp.write(script)
                    tmp_path = tmp.name

                yield _event("INFO", f"[script] Executing {filepath}...")
                start_ms = int(time.time() * 1000)
                t0 = time.time()
                try:
                    proc = subprocess.run([venv_python, tmp_path],
                                          capture_output=True, text=True, timeout=600,
                                          env=script_env)
                finally:
                    try: os.unlink(tmp_path)
                    except OSError: pass

                elapsed = time.time() - t0
                if proc.returncode != 0:
                    errs = [l for l in (proc.stderr or "").splitlines()
                            if any(k in l for k in ("Exception", "Error:", "Caused by"))]
                    summary = "\n".join(errs[-15:]) if errs else (proc.stderr or "")[-1000:]
                    yield _event("WARNING", f"[script] {filepath} failed (exit {proc.returncode}): {summary}")
                else:
                    yield _event("OK", f"[script] {filepath} completed in {elapsed:.0f}s")
                    for line in (proc.stdout or "").splitlines()[-10:]:
                        if line.strip():
                            yield _event("LOG", line.strip())

                    plan_id, _, target_info = _sync_lineage(db, "DataGuard ETL", start_ms, run_id, integration_id)
                    if plan_id:
                        all_plan_ids.append(plan_id)
                        yield _event("OK", f"[script] Lineage saved — plan {plan_id[:8]}...")
                        if target_info:
                            for tbl, info in target_info.items():
                                tables_loaded[tbl] = info["row_count"]
                                loaded_schema[tbl] = info["schema"]
                                yield _event("OK", f"[script] Detected target table '{tbl}' ({info['row_count']} rows)")
                    else:
                        yield _event("INFO", "[script] No Spline event detected (script may not use PySpark)")

        # ════════════════════════════════════════════════════════════════════════
        # STEP 2 — Load data files (.csv, .json, .xlsx, .tsv, .parquet)
        # ════════════════════════════════════════════════════════════════════════
        if data_files:
            yield _event("INFO", f"Loading {len(data_files)} data file(s) into '{config.TARGET_DB}'...")
            user, pw, host, port, _ = _pg_parts()
            pg_url = f"postgresql://{user}:{pw}@{host}:{port}/{config.TARGET_DB}"

            for filepath in data_files:
                table_name, row_count, schema_entry, err = _load_data_file(
                    filepath, owner, repo, branch, gh_headers, pg_url
                )
                if err:
                    yield _event("WARNING", f"[data] {filepath}: {err}")
                else:
                    tables_loaded[table_name] = row_count
                    loaded_schema.update(schema_entry)
                    yield _event("OK", f"[data] {filepath} → table '{table_name}' ({row_count} rows)")

        # ════════════════════════════════════════════════════════════════════════
        # STEP 3 — Execute SQL files (.sql)
        # ════════════════════════════════════════════════════════════════════════
        if sql_files:
            yield _event("INFO", f"Executing {len(sql_files)} SQL file(s) against '{config.TARGET_DB}'...")
            user, pw, host, port, _ = _pg_parts()
            pg_url = f"postgresql://{user}:{pw}@{host}:{port}/{config.TARGET_DB}"

            for filepath in sql_files:
                n_stmts, err = _execute_sql_file(filepath, owner, repo, branch, gh_headers, pg_url)
                if err:
                    yield _event("WARNING", f"[sql] {filepath}: {err}")
                else:
                    yield _event("OK", f"[sql] {filepath} — {n_stmts} statement(s) executed")

        # ════════════════════════════════════════════════════════════════════════
        # STEP 4 — Push loaded tables to catalog + auto-generate quality rules
        # ════════════════════════════════════════════════════════════════════════
        if tables_loaded or sql_files:
            # Auto-generate quality rules for data-file loaded tables
            if loaded_schema:
                try:
                    from engines.quality_auto_rules import auto_generate_rules
                    n_rules = auto_generate_rules(db, integration_id, loaded_schema)
                    if n_rules:
                        yield _event("OK", f"Auto-generated {n_rules} quality rule(s) for loaded tables")
                except Exception as qr_err:
                    yield _event("INFO", f"Quality rule generation skipped: {qr_err}")

            # Push to OpenMetadata catalog
            try:
                from engines.openmetadata_sync import push_table_metadata
                pushed = 0
                for table_name, schema_cols in loaded_schema.items():
                    cols = [{"name": c["Field"], "data_type": c.get("Type", "VARCHAR")}
                            for c in schema_cols]
                    if push_table_metadata(table_name, cols):
                        pushed += 1
                if pushed:
                    yield _event("OK", f"Catalog updated — {pushed} table(s) pushed to OpenMetadata")
                else:
                    yield _event("INFO", "Catalog push skipped (OpenMetadata not running or not configured)")
            except Exception as cat_err:
                yield _event("WARNING", f"Catalog push failed (non-fatal): {cat_err}")

        # ── Finalise run record ───────────────────────────────────────────────
        db.query(PipelineRun).filter(PipelineRun.id == run_id).update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc),
            "tables_scanned": list(tables_loaded.keys()),
            "row_counts": tables_loaded,
            "spline_plan_id": all_plan_ids[-1] if all_plan_ids else None,
        })
        db.commit()

        summary_parts = []
        if script_files:  summary_parts.append(f"{len(script_files)} script(s) run")
        if tables_loaded: summary_parts.append(f"{len(tables_loaded)} data table(s) loaded")
        if sql_files:     summary_parts.append(f"{len(sql_files)} SQL file(s) executed")
        if all_plan_ids:  summary_parts.append("lineage captured")

        yield _event("DONE", "GitHub pipeline complete — " + ", ".join(summary_parts))

    except Exception as exc:
        logger.error("GitHub pipeline failed: %s", exc, exc_info=True)
        _fail_run(db, run_id, exc)
        yield _event("ERROR", f"Pipeline failed: {exc}")


# ── GitHub data file loader ───────────────────────────────────────────────────

def _load_data_file(
    filepath: str, owner: str, repo: str, branch: str,
    headers: dict, pg_url: str,
) -> tuple[str, int, dict, str | None]:
    """
    Download a data file from GitHub and load it into PostgreSQL company_data.
    Returns (table_name, row_count, schema_dict, error_or_None).
    """
    import io
    from pathlib import PurePosixPath

    try:
        import pandas as pd
        from sqlalchemy import create_engine as _create_engine
    except ImportError:
        return "", 0, {}, "pandas not installed — run: pip install pandas openpyxl"

    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{filepath}"
    resp = http_requests.get(raw_url, headers=headers, timeout=30)
    if resp.status_code != 200:
        return "", 0, {}, f"HTTP {resp.status_code} fetching {filepath}"

    # Derive table name from filename (e.g. data/customers.csv → customers)
    stem = PurePosixPath(filepath).stem
    # Sanitise: lowercase, replace non-alphanumeric with underscore
    import re as _re
    table_name = _re.sub(r"[^a-z0-9_]", "_", stem.lower()).strip("_") or "imported_data"

    ext = PurePosixPath(filepath).suffix.lower()
    content = resp.content

    try:
        if ext == ".csv":
            df = pd.read_csv(io.BytesIO(content))
        elif ext in (".json", ".jsonl"):
            try:
                df = pd.read_json(io.BytesIO(content))
            except Exception:
                # Try newline-delimited JSON
                df = pd.read_json(io.BytesIO(content), lines=True)
        elif ext in (".xlsx", ".xls"):
            df = pd.read_excel(io.BytesIO(content))
        elif ext == ".tsv":
            df = pd.read_csv(io.BytesIO(content), sep="\t")
        elif ext == ".parquet":
            df = pd.read_parquet(io.BytesIO(content))
        else:
            return "", 0, {}, f"Unsupported file type: {ext}"
    except Exception as parse_err:
        return "", 0, {}, f"Cannot parse {filepath}: {parse_err}"

    if df.empty:
        return table_name, 0, {}, None

    # Sanitise column names
    df.columns = [
        _re.sub(r"[^a-z0-9_]", "_", str(c).lower()).strip("_") or f"col_{i}"
        for i, c in enumerate(df.columns)
    ]

    try:
        engine = _create_engine(pg_url)
        df.to_sql(table_name, engine, if_exists="replace", index=False)
        engine.dispose()
    except Exception as pg_err:
        return table_name, 0, {}, f"PostgreSQL write failed: {pg_err}"

    # Build schema dict for quality rule generation
    from engines.quality_auto_rules import build_schema_from_dataframe
    schema_entry = build_schema_from_dataframe(table_name, df)

    return table_name, len(df), schema_entry, None


# ── GitHub SQL file executor ─────────────────────────────────────────────────

def _execute_sql_file(
    filepath: str, owner: str, repo: str, branch: str,
    headers: dict, pg_url: str,
) -> tuple[int, str | None]:
    """
    Download a .sql file from GitHub and execute each statement against PostgreSQL.
    Returns (statements_executed, error_or_None).
    """
    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{filepath}"
    resp = http_requests.get(raw_url, headers=headers, timeout=15)
    if resp.status_code != 200:
        return 0, f"HTTP {resp.status_code} fetching {filepath}"

    sql_content = resp.text
    if not sql_content.strip():
        return 0, None

    try:
        from sqlalchemy import create_engine as _create_engine, text as _text
        engine = _create_engine(pg_url)
        statements = [s.strip() for s in sql_content.split(";") if s.strip()]
        executed = 0
        with engine.connect() as conn:
            for stmt in statements:
                try:
                    conn.execute(_text(stmt))
                    executed += 1
                except Exception:
                    pass  # Some statements may fail (e.g. CREATE TABLE IF NOT EXISTS already exists)
            conn.commit()
        engine.dispose()
        return executed, None
    except Exception as exc:
        return 0, f"SQL execution failed: {exc}"


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
