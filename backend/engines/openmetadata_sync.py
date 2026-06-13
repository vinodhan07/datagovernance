"""
openmetadata_sync.py — Push table/column metadata to OpenMetadata via REST API.

OpenMetadata requires a DatabaseService + Database + Schema hierarchy before
tables can be created. This module handles the full hierarchy upsert so callers
only need to pass a table name + column list.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

import config

logger = logging.getLogger("dataguard.openmetadata")

_OM_URL = config.OPENMETADATA_URL.rstrip("/")


def _headers() -> dict:
    token = config.OPENMETADATA_JWT_TOKEN
    if token:
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    return {"Content-Type": "application/json"}


def _om_available() -> bool:
    """Quick reachability check — silently returns False if OM is down."""
    try:
        r = requests.get(f"{_OM_URL}/v1/system/version", headers=_headers(), timeout=5)
        return r.status_code < 500
    except Exception:
        return False


# ── Service / hierarchy helpers ───────────────────────────────────────────────

def ensure_db_service(service_name: str = "dataguard-postgres") -> Optional[str]:
    """
    Create a DatabaseService for our ETL target (PostgreSQL company_data) in
    OpenMetadata if it doesn't already exist. Returns the service FQN or None.
    """
    url = f"{_OM_URL}/v1/services/databaseServices/name/{service_name}"
    r = requests.get(url, headers=_headers(), timeout=10)
    if r.status_code == 200:
        return r.json().get("fullyQualifiedName", service_name)

    import urllib.parse
    _parsed  = urllib.parse.urlparse(config.POSTGRES_URL)
    pg_user  = _parsed.username or "myuser"
    pg_pass  = _parsed.password or ""
    pg_host  = _parsed.hostname or "localhost"
    pg_port  = _parsed.port or 5432

    payload = {
        "name": service_name,
        "displayName": "DataGuard PostgreSQL",
        "serviceType": "Postgres",
        "connection": {
            "config": {
                "type": "Postgres",
                "username": pg_user,
                "authType": {"password": pg_pass},
                "hostPort": f"{pg_host}:{pg_port}",
                "database": config.TARGET_DB,
            }
        },
    }
    r = requests.post(f"{_OM_URL}/v1/services/databaseServices",
                      json=payload, headers=_headers(), timeout=10)
    if r.status_code in (200, 201):
        return r.json().get("fullyQualifiedName", service_name)
    logger.warning("OpenMetadata: could not create DatabaseService — %s %s", r.status_code, r.text[:200])
    return None


def _ensure_database(service_fqn: str, db_name: str = "company_data") -> Optional[str]:
    fqn = f"{service_fqn}.{db_name}"
    url = f"{_OM_URL}/v1/databases/name/{fqn}"
    r = requests.get(url, headers=_headers(), timeout=10)
    if r.status_code == 200:
        return r.json().get("fullyQualifiedName", fqn)

    payload = {"name": db_name, "service": service_fqn, "displayName": db_name}
    r = requests.post(f"{_OM_URL}/v1/databases", json=payload, headers=_headers(), timeout=10)
    if r.status_code in (200, 201):
        return r.json().get("fullyQualifiedName", fqn)
    logger.warning("OpenMetadata: could not create Database — %s", r.status_code)
    return None


def _ensure_schema(db_fqn: str, schema_name: str = "public") -> Optional[str]:
    fqn = f"{db_fqn}.{schema_name}"
    url = f"{_OM_URL}/v1/databaseSchemas/name/{fqn}"
    r = requests.get(url, headers=_headers(), timeout=10)
    if r.status_code == 200:
        return r.json().get("fullyQualifiedName", fqn)

    payload = {"name": schema_name, "database": db_fqn, "displayName": schema_name}
    r = requests.post(f"{_OM_URL}/v1/databaseSchemas", json=payload, headers=_headers(), timeout=10)
    if r.status_code in (200, 201):
        return r.json().get("fullyQualifiedName", fqn)
    logger.warning("OpenMetadata: could not create DatabaseSchema — %s", r.status_code)
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def push_table_metadata(
    table_name: str,
    columns: list[dict],
    service_name: str = "dataguard-postgres",
) -> bool:
    """
    Upsert table + column metadata into OpenMetadata.

    columns — list of dicts with keys: name (str), data_type (str, optional)
    Returns True on success, False on any failure.
    """
    if not _om_available():
        logger.info("OpenMetadata not reachable — skipping catalog push for '%s'", table_name)
        return False

    service_fqn = ensure_db_service(service_name)
    if not service_fqn:
        return False

    db_fqn = _ensure_database(service_fqn)
    if not db_fqn:
        return False

    schema_fqn = _ensure_schema(db_fqn)
    if not schema_fqn:
        return False

    table_fqn = f"{schema_fqn}.{table_name}"

    # Build column list for OpenMetadata
    om_columns = []
    for idx, col in enumerate(columns):
        col_name = col.get("name") or col.get("Field") or f"col_{idx}"
        raw_type = (col.get("data_type") or col.get("Type") or "VARCHAR").upper()
        # Map SQL types to OpenMetadata DataType enum values
        data_type = _map_data_type(raw_type)
        col_payload = {
            "name": col_name,
            "dataType": data_type,
            "dataTypeDisplay": raw_type,
            "ordinalPosition": idx + 1,
        }
        if data_type in ("VARCHAR", "CHAR", "BINARY", "VARBINARY"):
            col_payload["dataLength"] = 255
        om_columns.append(col_payload)

    payload = {
        "name": table_name,
        "databaseSchema": schema_fqn,
        "tableType": "Regular",
        "columns": om_columns,
    }

    # Try PUT (update) first, fall back to POST (create)
    put_url = f"{_OM_URL}/v1/tables/name/{table_fqn}"
    r = requests.get(put_url, headers=_headers(), timeout=10)
    if r.status_code == 200:
        r2 = requests.put(f"{_OM_URL}/v1/tables",
                          json=payload, headers=_headers(), timeout=10)
        if r2.status_code in (200, 201):
            logger.info("OpenMetadata: updated table '%s'", table_fqn)
            return True
    else:
        r2 = requests.post(f"{_OM_URL}/v1/tables", json=payload, headers=_headers(), timeout=10)
        if r2.status_code in (200, 201):
            logger.info("OpenMetadata: created table '%s'", table_fqn)
            return True

    logger.warning("OpenMetadata: failed to upsert table '%s' — %s %s",
                   table_name, r2.status_code, r2.text[:200])
    return False


def search_tables(query: str = "", limit: int = 50) -> list[dict]:
    """Search tables in OpenMetadata. Returns simplified list for the UI."""
    if not _om_available():
        return []

    url = f"{_OM_URL}/v1/tables"
    params = {"limit": limit, "fields": "columns,tags"}
    try:
        r = requests.get(url, params=params, headers=_headers(), timeout=10)
        if r.status_code != 200:
            return []
        data = r.json().get("data", [])
        
        # Simple local filtering if a specific query is provided
        q = query.strip().lower()
        if q and q != "*":
            data = [t for t in data if q in t.get("name", "").lower()]
            
        return [_format_table_detail(t) for t in data]
    except Exception as exc:
        logger.warning("OpenMetadata search failed: %s", exc)
        return []


def get_table_detail(fqn: str) -> Optional[dict]:
    """Fetch full table detail including columns and tags."""
    if not _om_available():
        return None
    try:
        url = f"{_OM_URL}/v1/tables/name/{fqn}"
        r = requests.get(url, params={"fields": "columns,tags,description"},
                         headers=_headers(), timeout=10)
        if r.status_code != 200:
            return None
        return _format_table_detail(r.json())
    except Exception as exc:
        logger.warning("OpenMetadata get_table_detail failed: %s", exc)
        return None


def add_tags_to_table(fqn: str, tags: list[str]) -> bool:
    """Add tag labels to a table by FQN."""
    if not _om_available():
        return False
    try:
        # First get the table id
        r = requests.get(f"{_OM_URL}/v1/tables/name/{fqn}",
                         headers=_headers(), timeout=10)
        if r.status_code != 200:
            return False
        table_id = r.json()["id"]
        existing_tags = r.json().get("tags", [])

        new_tag_labels = [{"tagFQN": t, "source": "Classification", "labelType": "Manual", "state": "Confirmed"}
                          for t in tags]
        all_tags = existing_tags + new_tag_labels

        patch = [{"op": "add", "path": "/tags", "value": all_tags}]
        r2 = requests.patch(
            f"{_OM_URL}/v1/tables/{table_id}",
            json=patch,
            headers={**_headers(), "Content-Type": "application/json-patch+json"},
            timeout=10,
        )
        return r2.status_code in (200, 201)
    except Exception as exc:
        logger.warning("OpenMetadata add_tags_to_table failed: %s", exc)
        return False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _map_data_type(raw: str) -> str:
    """Map SQL type strings to OpenMetadata DataType enum values."""
    raw = raw.upper().split("(")[0].strip()
    mapping = {
        "INT": "INT", "INTEGER": "INT", "BIGINT": "BIGINT", "SMALLINT": "SMALLINT",
        "TINYINT": "TINYINT", "FLOAT": "FLOAT", "DOUBLE": "DOUBLE", "DECIMAL": "DECIMAL",
        "NUMERIC": "NUMERIC", "VARCHAR": "VARCHAR", "CHAR": "CHAR", "TEXT": "TEXT",
        "LONGTEXT": "TEXT", "MEDIUMTEXT": "TEXT", "TINYTEXT": "TEXT",
        "DATE": "DATE", "DATETIME": "DATETIME", "TIMESTAMP": "TIMESTAMP", "TIME": "TIME",
        "BOOLEAN": "BOOLEAN", "BOOL": "BOOLEAN", "JSON": "JSON", "BLOB": "BLOB",
    }
    return mapping.get(raw, "VARCHAR")


def _format_table_hit(hit: dict) -> dict:
    src = hit.get("_source", {})
    return {
        "fqn": src.get("fullyQualifiedName", ""),
        "name": src.get("name", ""),
        "description": src.get("description", ""),
        "tags": [t.get("tagFQN", "") for t in src.get("tags", [])],
        "columns": [{"name": c.get("name", ""), "data_type": c.get("dataType", "")}
                    for c in src.get("columns", [])],
        "service_name": src.get("service", {}).get("name", ""),
    }


def _format_table_detail(data: dict) -> dict:
    return {
        "fqn": data.get("fullyQualifiedName", ""),
        "name": data.get("name", ""),
        "description": data.get("description", ""),
        "tags": [t.get("tagFQN", "") for t in data.get("tags", [])],
        "columns": [
            {
                "name": c.get("name", ""),
                "data_type": c.get("dataType", ""),
                "description": c.get("description", ""),
                "tags": [t.get("tagFQN", "") for t in c.get("tags", [])],
            }
            for c in data.get("columns", [])
        ],
        "service_name": data.get("service", {}).get("name", ""),
    }
