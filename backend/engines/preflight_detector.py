"""
preflight_detector.py — Pre-flight capability detection for MariaDB and GitHub integrations.

Probes the integration source BEFORE running the pipeline and returns which
features (lineage / catalog / quality) are available and why.
"""
from __future__ import annotations

import logging
import os
from pathlib import PurePosixPath
from typing import Optional

import requests

logger = logging.getLogger("dataguard.preflight")

# File extension categories
SCRIPT_EXT = {".py", ".ipynb", ".scala", ".r", ".rb"}
DATA_EXT   = {".csv", ".json", ".xlsx", ".tsv", ".parquet", ".jsonl"}
SQL_EXT    = {".sql"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MariaDB detection
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_mariadb_capabilities(creds: dict) -> dict:
    """
    Connect to MariaDB and probe what's present:
      - tables with data
      - empty tables
      - views
      - stored procedures
    Returns a structured dict with capability flags and human-readable reasons.
    """
    result = {
        "provider": "MariaDB",
        "has_tables": False,
        "has_data": False,
        "has_views": False,
        "has_procedures": False,
        "table_count": 0,
        "tables_with_data": [],
        "empty_tables": [],
        "view_names": [],
        "procedure_names": [],
        "capabilities": {
            "lineage": {"available": False, "reason": ""},
            "catalog": {"available": False, "reason": ""},
            "quality": {"available": False, "reason": ""},
        },
        "error": None,
    }

    try:
        import pymysql
        conn = pymysql.connect(
            host=creds["host"],
            port=int(creds["port"]),
            user=creds["user"],
            password=creds["password"],
            database=creds["database"],
            connect_timeout=10,
        )
    except Exception as exc:
        result["error"] = f"Cannot connect to MariaDB: {exc}"
        result["capabilities"]["lineage"]["reason"] = result["error"]
        result["capabilities"]["catalog"]["reason"] = result["error"]
        result["capabilities"]["quality"]["reason"] = result["error"]
        return result

    try:
        with conn.cursor() as cur:
            # ── Base tables ──────────────────────────────────────────────
            cur.execute("SHOW FULL TABLES WHERE Table_type = 'BASE TABLE'")
            base_tables = [row[0] for row in cur.fetchall()]

            # ── Views ────────────────────────────────────────────────────
            cur.execute("SHOW FULL TABLES WHERE Table_type = 'VIEW'")
            views = [row[0] for row in cur.fetchall()]

            # ── Stored procedures ────────────────────────────────────────
            try:
                cur.execute(
                    "SELECT ROUTINE_NAME FROM INFORMATION_SCHEMA.ROUTINES "
                    "WHERE ROUTINE_TYPE = 'PROCEDURE' AND ROUTINE_SCHEMA = %s",
                    (creds["database"],),
                )
                procedures = [row[0] for row in cur.fetchall()]
            except Exception:
                procedures = []

            # ── Row counts (lightweight estimate) ────────────────────────
            tables_with_data: list[str] = []
            empty_tables: list[str]     = []
            for tbl in base_tables:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM `{tbl}` LIMIT 1")
                    count = cur.fetchone()[0]
                    if count > 0:
                        tables_with_data.append(tbl)
                    else:
                        empty_tables.append(tbl)
                except Exception:
                    empty_tables.append(tbl)

    finally:
        conn.close()

    result["has_tables"]      = len(base_tables) > 0
    result["has_data"]        = len(tables_with_data) > 0
    result["has_views"]       = len(views) > 0
    result["has_procedures"]  = len(procedures) > 0
    result["table_count"]     = len(base_tables)
    result["tables_with_data"] = tables_with_data
    result["empty_tables"]    = empty_tables
    result["view_names"]      = views
    result["procedure_names"] = procedures

    # ── Capability rules ──────────────────────────────────────────────────
    n_tables = len(base_tables)
    n_data   = len(tables_with_data)

    # Lineage: PySpark ETL works on any table (even empty — schema is still captured)
    if result["has_tables"]:
        extras = []
        if result["has_views"]:       extras.append(f"{len(views)} view(s)")
        if result["has_procedures"]:  extras.append(f"{len(procedures)} procedure(s)")
        extra_str = f" + {', '.join(extras)}" if extras else ""
        result["capabilities"]["lineage"] = {
            "available": True,
            "reason": f"{n_tables} table(s) found{extra_str} — PySpark ETL will capture column lineage",
        }
    else:
        result["capabilities"]["lineage"] = {
            "available": False,
            "reason": "No tables found in database — nothing to run ETL on",
        }

    # Catalog: any tables (even empty) have columns worth cataloguing
    if result["has_tables"]:
        result["capabilities"]["catalog"] = {
            "available": True,
            "reason": f"{n_tables} table(s) with column schemas ready for OpenMetadata",
        }
    else:
        result["capabilities"]["catalog"] = {
            "available": False,
            "reason": "No tables found — catalog will be empty",
        }

    # Quality: Soda Core needs rows to evaluate checks
    if result["has_data"]:
        result["capabilities"]["quality"] = {
            "available": True,
            "reason": f"{n_data} table(s) contain data — quality checks can run",
        }
    elif result["has_tables"]:
        result["capabilities"]["quality"] = {
            "available": False,
            "reason": f"All {n_tables} table(s) are empty — run ETL first to load data",
        }
    else:
        result["capabilities"]["quality"] = {
            "available": False,
            "reason": "No tables found — quality scan not possible",
        }

    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GitHub detection
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_github_capabilities(
    token: str,
    owner: str,
    repo: str,
    branch: str = "main",
) -> dict:
    """
    Scan a GitHub repository tree to detect what file types are present.
    Categorises files into:
      - script_files  (.py, .ipynb, .scala, .r) → lineage via Spline
      - data_files    (.csv, .json, .xlsx, .tsv, .parquet) → catalog + quality
      - sql_files     (.sql) → catalog + quality (and possibly lineage if DDL/DML)

    Returns a structured dict with capability flags and human-readable reasons.
    """
    result = {
        "provider": "GitHub",
        "has_python_scripts": False,
        "has_sql_files": False,
        "has_data_files": False,
        "script_files": [],
        "data_files": [],
        "sql_files": [],
        "total_files": 0,
        "capabilities": {
            "lineage": {"available": False, "reason": ""},
            "catalog": {"available": False, "reason": ""},
            "quality": {"available": False, "reason": ""},
        },
        "error": None,
    }

    headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"token {token}"

    # Try both main and master if branch not specified
    branches_to_try = [branch] if branch else ["main", "master"]

    tree_data = None
    for b in branches_to_try:
        url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{b}?recursive=1"
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                tree_data = r.json()
                break
            elif r.status_code == 404:
                continue
            else:
                result["error"] = f"GitHub API error: HTTP {r.status_code}"
                break
        except Exception as exc:
            result["error"] = f"GitHub connection failed: {exc}"
            break

    if not tree_data:
        if not result["error"]:
            result["error"] = f"Repository {owner}/{repo} not found or branch '{branch}' does not exist"
        for feature in ("lineage", "catalog", "quality"):
            result["capabilities"][feature]["reason"] = result["error"]
        return result

    script_files: list[str] = []
    data_files: list[str]   = []
    sql_files: list[str]    = []

    for item in tree_data.get("tree", []):
        if item.get("type") != "blob":
            continue
        path = item.get("path", "")
        ext  = PurePosixPath(path).suffix.lower()

        if ext in SCRIPT_EXT:
            script_files.append(path)
        elif ext in DATA_EXT:
            data_files.append(path)
        elif ext in SQL_EXT:
            sql_files.append(path)

    result["script_files"]       = script_files
    result["data_files"]         = data_files
    result["sql_files"]          = sql_files
    result["has_python_scripts"] = len(script_files) > 0
    result["has_sql_files"]      = len(sql_files) > 0
    result["has_data_files"]     = len(data_files) > 0
    result["total_files"]        = len(tree_data.get("tree", []))

    # ── Capability rules ──────────────────────────────────────────────────
    n_scripts = len(script_files)
    n_data    = len(data_files)
    n_sql     = len(sql_files)

    # Lineage: Python/Scala scripts that likely use Spark → Spline captures lineage
    # SQL files can also define ETL (DDL + DML)
    if result["has_python_scripts"]:
        result["capabilities"]["lineage"] = {
            "available": True,
            "reason": f"{n_scripts} script file(s) found — lineage captured if script uses PySpark+Spline",
        }
    elif result["has_sql_files"]:
        result["capabilities"]["lineage"] = {
            "available": True,
            "reason": f"{n_sql} SQL file(s) found — executed against target database",
        }
    else:
        result["capabilities"]["lineage"] = {
            "available": False,
            "reason": "No scripts (.py, .sql, .scala) found in repository",
        }

    # Catalog: data files load tables, SQL files can create tables, scripts might too
    if result["has_data_files"] or result["has_sql_files"]:
        parts = []
        if n_data > 0: parts.append(f"{n_data} data file(s)")
        if n_sql  > 0: parts.append(f"{n_sql} SQL file(s)")
        result["capabilities"]["catalog"] = {
            "available": True,
            "reason": f"{', '.join(parts)} will load tables into catalog",
        }
    elif result["has_python_scripts"]:
        result["capabilities"]["catalog"] = {
            "available": False,
            "reason": f"{n_scripts} script(s) found — catalog will populate only if the script writes data to PostgreSQL",
        }
    else:
        result["capabilities"]["catalog"] = {
            "available": False,
            "reason": "No data files (.csv, .json, .xlsx) or SQL files found",
        }

    # Quality: needs data files or SQL inserts to populate tables with rows
    if result["has_data_files"]:
        result["capabilities"]["quality"] = {
            "available": True,
            "reason": f"{n_data} data file(s) will be loaded — quality rules auto-generated",
        }
    elif result["has_sql_files"]:
        result["capabilities"]["quality"] = {
            "available": True,
            "reason": f"{n_sql} SQL file(s) may insert rows — quality checks will run if data exists",
        }
    else:
        result["capabilities"]["quality"] = {
            "available": False,
            "reason": "No data files found — quality scan requires rows in tables",
        }

    return result
