"""
catalog.py
──────────
Enhanced data catalog — point-in-time schema snapshots with column statistics.

Connects to MariaDB read-only, runs DESCRIBE + aggregate COUNT queries per column,
stores only metadata (types, null counts, unique counts) — never raw row values.

Endpoints:
  POST /catalog/{integration_id}/snapshot   — take a fresh snapshot
  GET  /catalog/{integration_id}/latest     — most recent snapshot
  GET  /catalog/{integration_id}/diff       — compare latest two snapshots
  GET  /catalog/{integration_id}/history    — all snapshots (summary only)
"""

from datetime import datetime, timezone

import pymysql # type: ignore
import pymysql.cursors # type: ignore
from fastapi import APIRouter, HTTPException

from database import SessionLocal, is_db_available
from models import CatalogSnapshot

router = APIRouter()


# ─── Credential loader (same pattern as pipeline.py) ──────────────────────────

def _load_creds(integration_id: str):
    import store
    from integrations_service import get_connection_config

    creds = None
    name = None

    if is_db_available():
        db = SessionLocal()
        try:
            from models import Integration as IntModel
            try:
                int_obj = db.query(IntModel).filter(
                    IntModel.id == integration_id
                ).first()
                if int_obj:
                    name = int_obj.name
                    creds = get_connection_config(db, integration_id)
            except (ValueError, Exception):
                pass
        finally:
            db.close()

    if not creds:
        ig = store.get_integration(integration_id)
        if ig:
            creds = ig.get("credentials", {})
            name = ig.get("name")

    return creds, name


def _open_conn(creds: dict):
    ssl_mode = creds.get("ssl", "disable")
    ssl = None if ssl_mode in (None, "disable", "") else {"ssl": True}
    return pymysql.connect( # type: ignore
        host=creds.get("host", "localhost"),
        port=int(creds.get("port", 3306)),
        user=creds.get("user", ""),
        password=creds.get("password", ""),
        database=creds.get("database", ""),
        ssl=ssl,
        cursorclass=pymysql.cursors.DictCursor, # type: ignore
        connect_timeout=10,
        read_timeout=30,
    )


# ─── Snapshot builder ──────────────────────────────────────────────────────────

def _build_snapshot(creds: dict) -> dict:
    """
    Connect to MariaDB, run DESCRIBE + aggregate stats per column.
    Returns the 'tables' JSON dict — no raw row data.

    Shape per column:
      {
        "type": "varchar(100)",
        "nullable": true,
        "null_count": 3,
        "null_pct": 3.0,
        "unique_count": 97,
        "sample_values": []   ← always empty, never stored
      }
    """
    conn = _open_conn(creds)
    tables_meta = {}
    try:
        with conn.cursor() as cur:
            # Get table list
            cur.execute("SHOW TABLES")
            tables = [list(row.values())[0] for row in cur.fetchall()]

            for tbl in tables:
                safe = tbl.replace("`", "")

                # Row count
                cur.execute(f"SELECT COUNT(*) AS cnt FROM `{safe}`")
                row_count = (cur.fetchone() or {}).get("cnt", 0)

                # Column definitions
                cur.execute(f"DESCRIBE `{safe}`")
                columns_def = cur.fetchall()

                columns_meta = {}
                for col_def in columns_def:
                    col_name = col_def.get("Field", "")
                    col_type = col_def.get("Type", "")
                    nullable = col_def.get("Null", "YES") == "YES"
                    is_pk = col_def.get("Key", "") == "PRI"

                    safe_col = col_name.replace("`", "")

                    # Null count
                    null_count = 0
                    try:
                        cur.execute(
                            f"SELECT SUM(CASE WHEN `{safe_col}` IS NULL THEN 1 ELSE 0 END) AS nc "
                            f"FROM `{safe}`"
                        )
                        result = cur.fetchone() or {}
                        null_count = int(result.get("nc") or 0)
                    except Exception:
                        pass

                    # Unique count
                    unique_count = 0
                    try:
                        cur.execute(
                            f"SELECT COUNT(DISTINCT `{safe_col}`) AS uc FROM `{safe}`"
                        )
                        result = cur.fetchone() or {}
                        unique_count = int(result.get("uc") or 0)
                    except Exception:
                        pass

                    null_pct = round((null_count / row_count * 100), 1) if row_count > 0 else 0.0

                    columns_meta[col_name] = {
                        "type": col_type,
                        "nullable": nullable,
                        "is_primary_key": is_pk,
                        "null_count": null_count,
                        "null_pct": null_pct,
                        "unique_count": unique_count,
                        "sample_values": [],  # intentionally empty — privacy
                    }

                tables_meta[tbl] = {
                    "row_count": row_count,
                    "columns": columns_meta,
                }
    finally:
        conn.close()

    return tables_meta


def _count_columns(tables_meta: dict) -> int:
    return sum(len(t.get("columns", {})) for t in tables_meta.values())


# ─── Diff helper ───────────────────────────────────────────────────────────────

def _diff_snapshots(old_tables: dict, new_tables: dict) -> dict:
    """Compare two snapshot dicts and return what changed."""
    old_set = set(old_tables.keys())
    new_set = set(new_tables.keys())

    new_tables_list = sorted(new_set - old_set)
    dropped_tables = sorted(old_set - new_set)

    changed_columns = []
    new_columns = []

    for tbl in old_set & new_set:
        old_cols = old_tables[tbl].get("columns", {})
        new_cols = new_tables[tbl].get("columns", {})

        for col, new_meta in new_cols.items():
            if col not in old_cols:
                new_columns.append({"table": tbl, "column": col, "type": new_meta.get("type")})
            elif old_cols[col].get("type") != new_meta.get("type"):
                changed_columns.append({
                    "table": tbl,
                    "column": col,
                    "old_type": old_cols[col].get("type"),
                    "new_type": new_meta.get("type"),
                })

    return {
        "new_tables": new_tables_list,
        "dropped_tables": dropped_tables,
        "new_columns": new_columns,
        "changed_columns": changed_columns,
        "has_changes": bool(new_tables_list or dropped_tables or new_columns or changed_columns),
    }


# ─── Serialiser ────────────────────────────────────────────────────────────────

def _serialize(snap: CatalogSnapshot) -> dict:
    return {
        "id": snap.id,
        "integration_id": snap.integration_id,
        "snapshot_at": snap.snapshot_at.isoformat() if snap.snapshot_at else None,
        "table_count": snap.table_count,
        "column_count": snap.column_count,
        "tables": snap.tables or {},
        "changes_detected": snap.changes_detected,
        "previous_snapshot_id": snap.previous_snapshot_id,
    }


# ─── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/{integration_id}/snapshot")
def take_snapshot(integration_id: str):
    """
    Connect to MariaDB, snapshot schema + column stats, save to PostgreSQL.
    Compares against previous snapshot to detect changes.
    """
    creds, _ = _load_creds(integration_id)
    if not creds:
        raise HTTPException(status_code=404, detail="Integration not found")

    try:
        tables_meta = _build_snapshot(creds)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Snapshot failed: {str(exc)}")

    table_count = len(tables_meta)
    column_count = _count_columns(tables_meta)
    changes = None
    prev_id = None

    if is_db_available():
        db = SessionLocal()
        try:
            prev = (
                db.query(CatalogSnapshot)
                .filter(CatalogSnapshot.integration_id == integration_id)
                .order_by(CatalogSnapshot.snapshot_at.desc())
                .first()
            )
            if prev and prev.tables:
                changes = _diff_snapshots(prev.tables, tables_meta)
                prev_id = prev.id

            snap = CatalogSnapshot(
                integration_id=integration_id,
                tables=tables_meta,
                table_count=table_count,
                column_count=column_count,
                previous_snapshot_id=prev_id,
                changes_detected=changes,
            )
            db.add(snap)
            db.commit()
            db.refresh(snap)
            return _serialize(snap)
        finally:
            db.close()

    # DB not available — return in-memory result
    return {
        "id": None,
        "integration_id": integration_id,
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "table_count": table_count,
        "column_count": column_count,
        "tables": tables_meta,
        "changes_detected": None,
        "previous_snapshot_id": None,
    }


@router.get("/{integration_id}/latest")
def get_latest_snapshot(integration_id: str):
    """Return the most recent catalog snapshot for this integration."""
    if not is_db_available():
        return {"integration_id": integration_id, "snapshot": None}

    db = SessionLocal()
    try:
        snap = (
            db.query(CatalogSnapshot)
            .filter(CatalogSnapshot.integration_id == integration_id)
            .order_by(CatalogSnapshot.snapshot_at.desc())
            .first()
        )
        if not snap:
            return {"integration_id": integration_id, "snapshot": None}
        return {"integration_id": integration_id, "snapshot": _serialize(snap)}
    finally:
        db.close()


@router.get("/{integration_id}/diff")
def get_snapshot_diff(integration_id: str):
    """
    Compare the two most recent snapshots and return what changed.
    Returns None if fewer than 2 snapshots exist.
    """
    if not is_db_available():
        return {"integration_id": integration_id, "diff": None}

    db = SessionLocal()
    try:
        snaps = (
            db.query(CatalogSnapshot)
            .filter(CatalogSnapshot.integration_id == integration_id)
            .order_by(CatalogSnapshot.snapshot_at.desc())
            .limit(2)
            .all()
        )
        if len(snaps) < 2:
            return {"integration_id": integration_id, "diff": None,
                    "message": "Need at least 2 snapshots to diff"}
        newest, previous = snaps[0], snaps[1]
        diff = _diff_snapshots(previous.tables or {}, newest.tables or {})
        return {
            "integration_id": integration_id,
            "newest_snapshot_at": newest.snapshot_at.isoformat(),
            "previous_snapshot_at": previous.snapshot_at.isoformat(),
            "diff": diff,
        }
    finally:
        db.close()


@router.get("/{integration_id}/history")
def get_snapshot_history(integration_id: str):
    """Return summary of all snapshots (no tables JSON — too large)."""
    if not is_db_available():
        return {"integration_id": integration_id, "snapshots": []}

    db = SessionLocal()
    try:
        snaps = (
            db.query(CatalogSnapshot)
            .filter(CatalogSnapshot.integration_id == integration_id)
            .order_by(CatalogSnapshot.snapshot_at.desc())
            .limit(20)
            .all()
        )
        return {
            "integration_id": integration_id,
            "snapshots": [
                {
                    "id": s.id,
                    "snapshot_at": s.snapshot_at.isoformat() if s.snapshot_at else None,
                    "table_count": s.table_count,
                    "column_count": s.column_count,
                    "has_changes": bool(
                        s.changes_detected and s.changes_detected.get("has_changes")
                    ),
                }
                for s in snaps
            ],
        }
    finally:
        db.close()
