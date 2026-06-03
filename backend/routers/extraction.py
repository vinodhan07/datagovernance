"""
extraction.py
─────────────
Read-only data extraction from MariaDB.
Data lives in Python RAM only — never written to disk or PostgreSQL.
Returns structured dicts for the engine layer.

Uses the same credential format as connectors.py:
  { "host": "...", "port": 3306, "user": "...", "password": "...", "database": "...", "ssl": "disable" }
"""

import pymysql
from fastapi import HTTPException


def _open_connection(creds: dict):
    """Open a read-only connection to MariaDB using stored credentials."""
    try:
        ssl = _build_ssl(creds.get("ssl", "disable"))
        conn = pymysql.connect(
            host=creds.get("host", "127.0.0.1"),
            port=int(creds.get("port", 3307)),
            user=creds.get("user", ""),
            password=creds.get("password", ""),
            database=creds.get("database", ""),
            ssl=ssl,
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=10,
            read_timeout=30,
        )
        return conn
    except pymysql.err.OperationalError as e:
        raise HTTPException(status_code=400, detail=f"MariaDB connection failed: {str(e)}")


def _build_ssl(ssl_mode: str) -> dict | None:
    """Convert SSL mode string to pymysql SSL dict."""
    if ssl_mode in (None, "disable", ""):
        return None
    if ssl_mode == "require":
        return {"ssl": True}
    return {"ssl": True}


# ─── Schema extraction ────────────────────────────────────────────────────────

def extract_schema(creds: dict) -> dict:
    """
    Returns table schema metadata ONLY — no row data.
    Shape: { "employees": [{"Field": "name", "Type": "varchar(100)", "Null": "YES"}, ...] }
    """
    conn = _open_connection(creds)
    schema = {}
    try:
        with conn.cursor() as cursor:
            cursor.execute("SHOW TABLES")
            tables = [list(row.values())[0] for row in cursor.fetchall()]
            for table in tables:
                cursor.execute(f"DESCRIBE `{table}`")
                schema[table] = cursor.fetchall()
    finally:
        conn.close()
    return schema


# ─── Row extraction ───────────────────────────────────────────────────────────

def extract_table_data(creds: dict, table_names: list[str], limit: int = 1000) -> dict[str, list[dict]]:
    """
    Pull rows from specified tables into RAM.
    Returns { "table_name": [row_dict, ...] }
    Data exists only in this dict — garbage collected after engines run.
    """
    conn = _open_connection(creds)
    table_data = {}
    try:
        with conn.cursor() as cursor:
            for table in table_names:
                safe_table = table.replace("`", "")
                cursor.execute(f"SELECT * FROM `{safe_table}` LIMIT %s", (limit,))
                rows = cursor.fetchall()
                # Convert non-serialisable types to str for engine compatibility
                clean_rows = []
                for row in rows:
                    clean_rows.append(
                        {k: (str(v) if v is not None and not isinstance(v, (int, float, str, bool)) else v)
                         for k, v in row.items()}
                    )
                table_data[safe_table] = clean_rows
    finally:
        conn.close()
    return table_data


# ─── Full extraction (schema + data in one connection) ────────────────────────

def extract_all(creds: dict, limit_per_table: int = 1000) -> tuple[dict, dict]:
    """
    Single-connection full extraction.
    Returns (schema, table_data) — both in-memory only.
    Used by the scanner for full governance scans.
    """
    conn = _open_connection(creds)
    schema = {}
    table_data = {}
    try:
        with conn.cursor() as cursor:
            # Schema
            cursor.execute("SHOW TABLES")
            tables = [list(row.values())[0] for row in cursor.fetchall()]
            for table in tables:
                cursor.execute(f"DESCRIBE `{table}`")
                schema[table] = cursor.fetchall()
            # Rows — read-only SELECT only
            for table in tables:
                cursor.execute(f"SELECT * FROM `{table}` LIMIT %s", (limit_per_table,))
                rows = cursor.fetchall()
                clean_rows = []
                for row in rows:
                    clean_rows.append(
                        {k: (str(v) if v is not None and not isinstance(v, (int, float, str, bool)) else v)
                         for k, v in row.items()}
                    )
                table_data[table] = clean_rows
    finally:
        conn.close()
    return schema, table_data
