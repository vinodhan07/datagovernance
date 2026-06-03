"""
migrate.py — create / update all DataGuard tables in PostgreSQL.

Run once from the backend folder:
    python migrate.py

Safe to re-run — uses CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS.
Drops policy_scan_results if it still exists (policy feature removed).
"""

import os
from dotenv import load_dotenv

load_dotenv()

import psycopg2

DATABASE_URL = os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "POSTGRES_URL not found. Add it to backend/.env:\n"
        "  POSTGRES_URL=postgresql://user:pass@localhost:5432/dataguard"
    )

conn_str = DATABASE_URL.replace("postgresql://", "postgres://", 1)

migrations = [

    # ── integrations ─────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS integrations (
        id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name              VARCHAR(100)  NOT NULL,
        provider          VARCHAR(50)   NOT NULL,
        category          VARCHAR(50)   NOT NULL,
        host              VARCHAR(255),
        port              INTEGER,
        database_name     VARCHAR(100),
        username          VARCHAR(100),
        password_encrypted TEXT,
        ssl_mode          VARCHAR(20),
        created_at        TIMESTAMPTZ DEFAULT NOW(),
        updated_at        TIMESTAMPTZ DEFAULT NOW()
    );
    """,

    # ── data_assets — VARCHAR integration_id (no FK, supports in-memory IDs) ─
    """
    CREATE TABLE IF NOT EXISTS data_assets (
        id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
        integration_id VARCHAR(100) NOT NULL,
        table_name     VARCHAR(100),
        column_name    VARCHAR(100),
        data_type      VARCHAR(100),
        is_nullable    VARCHAR(10),
        column_key     VARCHAR(20),
        created_at     TIMESTAMPTZ DEFAULT NOW()
    );
    """,

    # Migrate old UUID FK column to VARCHAR if needed
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='data_assets' AND column_name='integration_id'
              AND data_type='uuid'
        ) THEN
            ALTER TABLE data_assets DROP CONSTRAINT IF EXISTS data_assets_integration_id_fkey;
            ALTER TABLE data_assets ALTER COLUMN integration_id TYPE VARCHAR(100) USING integration_id::text;
        END IF;
    END $$;
    """,

    # Add new columns to data_assets if missing
    "ALTER TABLE data_assets ADD COLUMN IF NOT EXISTS is_nullable VARCHAR(10);",
    "ALTER TABLE data_assets ADD COLUMN IF NOT EXISTS column_key  VARCHAR(20);",

    # ── scan_results — VARCHAR integration_id (no FK) ────────────────────────
    """
    CREATE TABLE IF NOT EXISTS scan_results (
        id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
        integration_id VARCHAR(100) NOT NULL,
        table_name     VARCHAR(100),
        column_name    VARCHAR(100),
        issue_type     VARCHAR(100),
        status         VARCHAR(20),
        row_count      INTEGER,
        scan_batch_id  VARCHAR(100),
        created_at     TIMESTAMPTZ DEFAULT NOW()
    );
    """,

    # Migrate old UUID FK column to VARCHAR if needed
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='scan_results' AND column_name='integration_id'
              AND data_type='uuid'
        ) THEN
            ALTER TABLE scan_results DROP CONSTRAINT IF EXISTS scan_results_integration_id_fkey;
            ALTER TABLE scan_results ALTER COLUMN integration_id TYPE VARCHAR(100) USING integration_id::text;
        END IF;
    END $$;
    """,

    # Add new columns to scan_results if missing
    "ALTER TABLE scan_results ADD COLUMN IF NOT EXISTS row_count     INTEGER;",
    "ALTER TABLE scan_results ADD COLUMN IF NOT EXISTS scan_batch_id VARCHAR(100);",

    # ── quality_scan_results ──────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS quality_scan_results (
        id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
        integration_id   VARCHAR(100) NOT NULL,
        integration_name VARCHAR(255),
        rule_id          VARCHAR(100) NOT NULL,
        rule_name        VARCHAR(255) NOT NULL,
        rule_type        VARCHAR(50)  NOT NULL,
        table_name       VARCHAR(255) NOT NULL,
        column_name      VARCHAR(255) NOT NULL,
        severity         VARCHAR(20)  NOT NULL,
        score            FLOAT        NOT NULL DEFAULT 100.0,
        status           VARCHAR(20)  NOT NULL,
        failed_rows      INTEGER      NOT NULL DEFAULT 0,
        total_rows       INTEGER      NOT NULL DEFAULT 0,
        reason           TEXT,
        findings         JSONB,
        scanned_at       TIMESTAMPTZ  DEFAULT NOW(),
        scan_batch_id    VARCHAR(100)
    );
    """,

    # ── pipeline_runs — removed policy_score column ───────────────────────────
    """
    CREATE TABLE IF NOT EXISTS pipeline_runs (
        id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
        integration_id   VARCHAR(100) NOT NULL,
        integration_name VARCHAR(255),
        status           VARCHAR(20)  NOT NULL DEFAULT 'running',
        started_at       TIMESTAMPTZ  DEFAULT NOW(),
        completed_at     TIMESTAMPTZ,
        tables_scanned   JSONB,
        row_counts       JSONB,
        quality_score    FLOAT,
        log_entries      JSONB,
        error_message    TEXT,
        scan_batch_id    VARCHAR(100)
    );
    """,

    # ── audit_logs ────────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        id             SERIAL      PRIMARY KEY,
        event_type     VARCHAR(50)  NOT NULL,
        integration_id VARCHAR(100),
        entity_type    VARCHAR(50),
        entity_id      VARCHAR(100),
        description    TEXT,
        event_metadata JSONB,
        status         VARCHAR(20)  NOT NULL DEFAULT 'success',
        created_at     TIMESTAMPTZ  DEFAULT NOW()
    );
    """,

    # ── catalog_scan_results ──────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS catalog_scan_results (
        id                   SERIAL  PRIMARY KEY,
        integration_id       VARCHAR(100) NOT NULL,
        snapshot_at          TIMESTAMPTZ  DEFAULT NOW(),
        tables               JSONB,
        table_count          INTEGER,
        column_count         INTEGER,
        previous_snapshot_id INTEGER,
        changes_detected     JSONB
    );
    """,

    # ── Drop policy_scan_results (feature removed) ────────────────────────────
    "DROP TABLE IF EXISTS policy_scan_results;",

    # ── indexes ───────────────────────────────────────────────────────────────
    "CREATE INDEX IF NOT EXISTS idx_data_assets_int  ON data_assets(integration_id);",
    "CREATE INDEX IF NOT EXISTS idx_scan_results_int ON scan_results(integration_id);",
    "CREATE INDEX IF NOT EXISTS idx_qsr_integration  ON quality_scan_results(integration_id);",
    "CREATE INDEX IF NOT EXISTS idx_qsr_batch        ON quality_scan_results(scan_batch_id);",
    "CREATE INDEX IF NOT EXISTS idx_pipeline_int     ON pipeline_runs(integration_id);",
    "CREATE INDEX IF NOT EXISTS idx_audit_event      ON audit_logs(event_type);",
    "CREATE INDEX IF NOT EXISTS idx_audit_integration ON audit_logs(integration_id);",
    "CREATE INDEX IF NOT EXISTS idx_catalog_int      ON catalog_scan_results(integration_id);",

    # ── Lineage tables ────────────────────────────────────────────────────────

    """
    CREATE TABLE IF NOT EXISTS lineage_jobs (
        id               VARCHAR(100) PRIMARY KEY,
        name             VARCHAR(255) NOT NULL,
        integration_id   VARCHAR(100),
        job_type         VARCHAR(50)  DEFAULT 'etl',
        created_at       TIMESTAMPTZ  DEFAULT NOW()
    );
    """,

    """
    CREATE TABLE IF NOT EXISTS lineage_datasets (
        id               VARCHAR(100) PRIMARY KEY,
        job_id           VARCHAR(100) NOT NULL,
        name             VARCHAR(255) NOT NULL,
        uri              TEXT,
        dataset_type     VARCHAR(20)  NOT NULL,
        columns_json     JSONB,
        created_at       TIMESTAMPTZ  DEFAULT NOW()
    );
    """,

    """
    CREATE TABLE IF NOT EXISTS lineage_columns (
        id               VARCHAR(100) PRIMARY KEY,
        dataset_id       VARCHAR(100) NOT NULL,
        name             VARCHAR(255) NOT NULL,
        data_type        VARCHAR(100),
        created_at       TIMESTAMPTZ  DEFAULT NOW()
    );
    """,

    """
    CREATE TABLE IF NOT EXISTS lineage_transformations (
        id               VARCHAR(100) PRIMARY KEY,
        job_id           VARCHAR(100) NOT NULL,
        name             VARCHAR(255) NOT NULL,
        operation_type   VARCHAR(100) NOT NULL,
        parameters_json  JSONB,
        order_index      INTEGER      DEFAULT 0,
        columns_affected JSONB,
        created_at       TIMESTAMPTZ  DEFAULT NOW()
    );
    """,

    """
    CREATE TABLE IF NOT EXISTS lineage_edges (
        id                   VARCHAR(100) PRIMARY KEY,
        job_id               VARCHAR(100) NOT NULL,
        source_dataset       VARCHAR(255) NOT NULL,
        source_column        VARCHAR(255) NOT NULL,
        target_dataset       VARCHAR(255) NOT NULL,
        target_column        VARCHAR(255) NOT NULL,
        transformation_id    VARCHAR(100),
        transformations_json JSONB,
        created_at           TIMESTAMPTZ  DEFAULT NOW()
    );
    """,

    """
    CREATE TABLE IF NOT EXISTS lineage_executions (
        id               VARCHAR(100) PRIMARY KEY,
        job_id           VARCHAR(100) NOT NULL,
        pipeline_run_id  VARCHAR(100),
        started_at       TIMESTAMPTZ,
        completed_at     TIMESTAMPTZ,
        status           VARCHAR(20)  DEFAULT 'completed',
        lineage_json     JSONB,
        dag_json         JSONB,
        spline_plan_id   VARCHAR(100),
        created_at       TIMESTAMPTZ  DEFAULT NOW()
    );
    """,

    # ── Lineage indexes ───────────────────────────────────────────────────────
    "CREATE INDEX IF NOT EXISTS idx_lineage_jobs_int     ON lineage_jobs(integration_id);",
    "CREATE INDEX IF NOT EXISTS idx_lineage_ds_job       ON lineage_datasets(job_id);",
    "CREATE INDEX IF NOT EXISTS idx_lineage_col_ds       ON lineage_columns(dataset_id);",
    "CREATE INDEX IF NOT EXISTS idx_lineage_xform_job    ON lineage_transformations(job_id);",
    "CREATE INDEX IF NOT EXISTS idx_lineage_edge_job     ON lineage_edges(job_id);",
    "CREATE INDEX IF NOT EXISTS idx_lineage_edge_src     ON lineage_edges(source_dataset, source_column);",
    "CREATE INDEX IF NOT EXISTS idx_lineage_edge_tgt     ON lineage_edges(target_dataset, target_column);",
    "CREATE INDEX IF NOT EXISTS idx_lineage_exec_job     ON lineage_executions(job_id);",
    "CREATE INDEX IF NOT EXISTS idx_lineage_exec_run     ON lineage_executions(pipeline_run_id);",
]


def run():
    conn = psycopg2.connect(conn_str)
    conn.autocommit = True
    cur = conn.cursor()

    print(f"Connected. Running {len(migrations)} migrations...\n")

    ok = 0
    for i, sql in enumerate(migrations, 1):
        label = sql.strip().splitlines()[0][:70].strip()
        try:
            cur.execute(sql)
            print(f"  [{i:02d}] OK  — {label}")
            ok += 1
        except Exception as e:
            print(f"  [{i:02d}] ERR — {label}\n       {e}")

    cur.close()
    conn.close()
    print(f"\n{ok}/{len(migrations)} migrations succeeded.")
    print("Run: uvicorn main:app --reload")


if __name__ == "__main__":
    run()
