"""
quality_auto_rules.py — Auto-generate default SodaCL quality rules from a discovered schema.

Called after pipeline ETL completes so the Quality page already has sensible
default checks without requiring the user to manually enter every rule.
"""
from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger("dataguard.quality_auto")

# Data types that are good candidates for null/missing checks
_NULLABLE_TYPES = {"varchar", "text", "char", "longtext", "mediumtext", "tinytext", "string"}
_NUMERIC_TYPES  = {"int", "integer", "bigint", "smallint", "tinyint", "float", "double", "decimal", "numeric"}

# Max non-PK columns to auto-add missing_count rules for (keeps rule list short)
_MAX_MISSING_CHECKS_PER_TABLE = 3


def auto_generate_rules(
    db,                          # SQLAlchemy Session
    integration_id: str,
    tables_schema: dict,         # {table_name: [{"Field": str, "Type": str, "Key": str}]}
) -> int:
    """
    For each table in tables_schema, create default SodaCL rules if none exist yet.

    Default rules created per table:
      1. row_count > 0                     — table should not be empty
      2. missing_count(pk_col) = 0         — primary key must never be null
      3. missing_count(col) = 0            — for up to N NOT NULL string/numeric cols

    Returns the number of new rules created.
    """
    from src.domain.entities import QualityRule

    created = 0

    for table_name, columns in tables_schema.items():
        # Skip tables we already have rules for
        existing = (
            db.query(QualityRule)
            .filter(
                QualityRule.integration_id == integration_id,
                QualityRule.table_name == table_name,
            )
            .first()
        )
        if existing:
            logger.debug("Skipping auto-rules for '%s' — rules already exist", table_name)
            continue

        new_rules: list[QualityRule] = []

        # Rule 1: row_count > 0
        new_rules.append(
            QualityRule(
                integration_id=integration_id,
                table_name=table_name,
                column_name=None,
                check_type="row_count",
                threshold="> 0",
                check_yaml=f"checks for {table_name}:\n  - row_count > 0",
            )
        )

        pk_cols   = [c["Field"] for c in columns if c.get("Key") == "PRI"]
        null_cols: list[str] = []

        for col in columns:
            field = col.get("Field", "")
            key   = col.get("Key", "")
            dtype = col.get("Type", "").lower().split("(")[0].strip()

            # Rule 2: missing_count for PK columns
            if key == "PRI":
                new_rules.append(
                    QualityRule(
                        integration_id=integration_id,
                        table_name=table_name,
                        column_name=field,
                        check_type="missing_count",
                        threshold="= 0",
                        check_yaml=f"checks for {table_name}:\n  - missing_count({field}) = 0",
                    )
                )
                continue

            # Rule 3: missing_count for string/numeric non-PK columns (limited count)
            if dtype in _NULLABLE_TYPES or dtype in _NUMERIC_TYPES:
                null_cols.append(field)

        for col_name in null_cols[:_MAX_MISSING_CHECKS_PER_TABLE]:
            new_rules.append(
                QualityRule(
                    integration_id=integration_id,
                    table_name=table_name,
                    column_name=col_name,
                    check_type="missing_count",
                    threshold="= 0",
                    check_yaml=f"checks for {table_name}:\n  - missing_count({col_name}) = 0",
                )
            )

        for rule in new_rules:
            db.add(rule)
        created += len(new_rules)
        logger.info("Auto-generated %d quality rule(s) for table '%s'", len(new_rules), table_name)

    if created:
        db.commit()

    return created


def build_schema_from_dataframe(table_name: str, df) -> dict:
    """
    Build a tables_schema dict entry from a pandas DataFrame.
    Used when GitHub data files (CSV/JSON) are loaded — we don't have DESCRIBE output.

    Returns: {table_name: [{"Field": col, "Type": dtype_str, "Key": ""}]}
    """
    columns = []
    for col_name in df.columns:
        dtype = str(df[col_name].dtype)
        if "int" in dtype:
            sql_type = "int"
        elif "float" in dtype:
            sql_type = "float"
        elif "object" in dtype or "string" in dtype:
            sql_type = "varchar"
        elif "datetime" in dtype or "date" in dtype:
            sql_type = "datetime"
        elif "bool" in dtype:
            sql_type = "tinyint"
        else:
            sql_type = "varchar"
        columns.append({"Field": col_name, "Type": sql_type, "Key": ""})
    return {table_name: columns}
