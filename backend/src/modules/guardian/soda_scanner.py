"""
soda_scanner.py — Run SodaCL data quality checks against PostgreSQL via Soda Core.

Soda Core scans the ETL target database (company_data) which is populated
by the PySpark ETL pipeline. Source MariaDB is never scanned directly.
"""
from __future__ import annotations

import io
import json
import logging
import textwrap
from datetime import datetime
from typing import TYPE_CHECKING

import src.core.config as config

if TYPE_CHECKING:
    from src.domain.entities import QualityRule

logger = logging.getLogger("dataguard.soda")

# Soda check types that operate on a column
_COLUMN_CHECKS = {"null_count", "missing_count", "duplicate_count", "min", "max", "avg", "stddev"}
# Soda check types that operate on a table (no column needed)
_TABLE_CHECKS  = {"row_count"}


def build_sodacl_yaml(rules: list["QualityRule"]) -> str:
    """
    Build a SodaCL YAML string from a list of QualityRule ORM objects.

    Example output:
        checks for customers:
          - missing_count(email) = 0
          - duplicate_count(customer_id) = 0

        checks for orders:
          - row_count > 0
    """
    by_table: dict[str, list[str]] = {}
    for rule in rules:
        table = rule.table_name
        if table not in by_table:
            by_table[table] = []

        col   = rule.column_name
        ctype = rule.check_type
        thresh = rule.threshold.strip()

        if ctype in _TABLE_CHECKS or not col:
            line = f"- {ctype} {thresh}"
        else:
            line = f"- {ctype}({col}) {thresh}"

        by_table[table].append(line)

    sections = []
    for table, checks in by_table.items():
        block = f"checks for {table}:\n"
        block += "\n".join(f"  {c}" for c in checks)
        sections.append(block)

    return "\n\n".join(sections)


def _pg_datasource_config() -> dict:
    """
    Build the Soda datasource config dict for the company_data PostgreSQL DB.
    Parses POSTGRES_URL to extract connection parts.
    """
    url = config.POSTGRES_URL
    # postgresql://user:pass@host:port/dataguard  →  strip to company_data
    creds_rest = url.split("://", 1)[1]
    creds, rest = creds_rest.split("@", 1)
    user, pw    = (creds.split(":", 1) + [""])[:2]
    host_port, _ = rest.split("/", 1)
    host, port   = (host_port.split(":") + ["5432"])[:2]

    return {
        "type": "postgres",
        "host": host,
        "port": int(port),
        "username": user,
        "password": pw,
        "database": config.TARGET_DB,
        "schema": "public",
    }


def run_scan(rules: list["QualityRule"]) -> dict:
    """
    Execute a Soda Core scan against the rules and return a result dict:
        {
          "checks_total": int,
          "checks_passed": int,
          "checks_failed": int,
          "score": float,           # 0–100
          "findings": [
            {"table_name", "column_name", "check_type", "status", "value"},
            ...
          ],
          "raw_output": str,        # Soda log output
        }

    Returns a safe error dict if soda-core is not installed or scan fails.
    """
    try:
        from soda.scan import Scan  # type: ignore[import]
    except ImportError:
        logger.error("soda-core is not installed — run: pip install soda-core soda-core-postgres")
        return _error_result("soda-core package not installed")

    if not rules:
        return {"checks_total": 0, "checks_passed": 0, "checks_failed": 0,
                "score": 100.0, "findings": [], "raw_output": "No rules defined"}

    yaml_str = build_sodacl_yaml(rules)
    logger.debug("SodaCL YAML:\n%s", yaml_str)

    ds_cfg   = _pg_datasource_config()
    log_buf  = io.StringIO()

    try:
        scan = Scan()
        scan.set_data_source_name("dataguard_pg")
        scan.add_configuration_yaml_str(_build_ds_yaml(ds_cfg))
        scan.add_sodacl_yaml_str(yaml_str)

        # Redirect Soda's verbose output to our buffer
        import logging as _logging
        soda_logger = _logging.getLogger("soda")
        buf_handler = _logging.StreamHandler(log_buf)
        buf_handler.setLevel(_logging.DEBUG)
        soda_logger.addHandler(buf_handler)

        scan.execute()

        soda_logger.removeHandler(buf_handler)

    except Exception as exc:
        logger.error("Soda scan execution error: %s", exc, exc_info=True)
        return _error_result(str(exc))

    return _parse_scan_results(scan, rules, log_buf.getvalue())


def _build_ds_yaml(cfg: dict) -> str:
    """Build Soda datasource YAML from config dict."""
    return textwrap.dedent(f"""
        data_source dataguard_pg:
          type: postgres
          host: {cfg['host']}
          port: {cfg['port']}
          username: {cfg['username']}
          password: {cfg['password']}
          database: {cfg['database']}
          schema: {cfg['schema']}
    """).strip()


def _parse_scan_results(scan: Scan, rules: list["QualityRule"], raw_output: str) -> dict:
    findings = []
    passed = 0
    failed = 0
    try:
        for check in scan._checks:
            cdict = check.get_dict()
            outcome = cdict.get("outcome")  # 'pass', 'fail', 'warn', etc.

            table_name = cdict.get("table") or _extract_table(check)
            column_name = cdict.get("column") or _extract_column(check.name)
            check_type = _extract_check_type(check.name)

            status = "pass"
            if outcome in ("fail", "error"):
                status = "fail"
                failed += 1
            elif outcome == "warn":
                status = "warn"
                failed += 1
            else:
                passed += 1

            value = str(check.check_value) if check.check_value is not None else "N/A"

            findings.append({
                "table_name": table_name,
                "column_name": column_name,
                "check_type": check_type,
                "status": status,
                "value": value,
            })

    except Exception as exc:
        logger.warning("Could not parse Soda check results: %s", exc)
        # Produce one finding per rule as unknown
        for rule in rules:
            findings.append({
                "table_name":  rule.table_name,
                "column_name": rule.column_name,
                "check_type":  rule.check_type,
                "status":      "warn",
                "value":       "parse_error",
            })
        failed = len(rules)
        passed = 0

    total = passed + failed
    score = round((passed / total) * 100, 1) if total > 0 else 100.0

    return {
        "checks_total":  total,
        "checks_passed": passed,
        "checks_failed": failed,
        "score":         score,
        "findings":      findings,
        "raw_output":    raw_output,
    }


def _error_result(msg: str) -> dict:
    return {
        "checks_total": 0, "checks_passed": 0, "checks_failed": 0,
        "score": None, "findings": [], "raw_output": msg,
    }


def _extract_table(check: object) -> str:
    try:
        partition = getattr(check, "partition", None)
        if partition:
            table = getattr(partition, "table", None)
            if table:
                table_name = getattr(table, "table_name", None) or getattr(table, "name", None)
                if table_name:
                    return str(table_name)
    except Exception:
        pass
    try:
        if hasattr(check, "table_name") and check.table_name:
            return str(check.table_name)
    except Exception:
        pass
    try:
        check_cfg = getattr(check, "check_cfg", None)
        if check_cfg:
            table_name = getattr(check_cfg, "table_name", None)
            if table_name:
                return str(table_name)
    except Exception:
        pass
    return ""


def _extract_column(check_name: str) -> str | None:
    """Extract column name from 'missing_count(email) = 0' → 'email'."""
    import re
    m = re.search(r"\((\w+)\)", check_name)
    return m.group(1) if m else None


def _extract_check_type(check_name: str) -> str:
    """Extract check type from 'missing_count(email) = 0' → 'missing_count'."""
    import re
    m = re.match(r"(\w+)", check_name)
    return m.group(1) if m else check_name
