"""
spark_etl.py — PySpark session + per-table ETL (MariaDB → PostgreSQL).

WHY JDBC?
  PySpark runs on the JVM (Java Virtual Machine), not Python.
  spark.read.format("jdbc") triggers Java code to transfer data.
  JDBC is Java's database connector — same role as pymysql for Python.
  We use pymysql only for fast schema discovery (DESCRIBE table).
  Bulk data transfer MUST go through JDBC because Spark distributes
  the work across JVM threads — Python connectors can't participate.
"""

from __future__ import annotations
import logging
import os
import src.core.config as config

logger = logging.getLogger("dataguard.spark_etl")

# ── Java 17 fix: required before any SparkSession starts ─────────────────────
# Spline 2.x reads its config from a JAR URL using Scala reflection.
# Java 9+ JPMS blocks this by default — this flag re-opens the module.
_JAVA_OPENS = "--add-opens=java.base/sun.net.www.protocol.jar=ALL-UNNAMED"
if _JAVA_OPENS not in os.environ.get("JDK_JAVA_OPTIONS", ""):
    os.environ["JDK_JAVA_OPTIONS"] = f"{os.environ.get('JDK_JAVA_OPTIONS','').strip()} {_JAVA_OPENS}".strip()


# ── Session ───────────────────────────────────────────────────────────────────

def create_spark_session(app_name: str):
    """
    Create a SparkSession with:
      - Spline Agent JAR  → auto-captures lineage on every df.write
      - MariaDB JDBC JAR  → reads from source DB
      - PostgreSQL JDBC JAR → writes to target DB

    JARs are downloaded from Maven Central on first run (~3 min) and
    cached in ~/.ivy2 for all future runs.
    """
    from pyspark.sql import SparkSession

    packages = ",".join([
        f"za.co.absa.spline.agent.spark:spark-3.5-spline-agent-bundle_2.12:{config.SPLINE_AGENT_VER}",
        f"org.mariadb.jdbc:mariadb-java-client:{config.MARIADB_JAR_VER}",
        f"org.postgresql:postgresql:{config.POSTGRES_JAR_VER}",
    ])

    # Stop existing session so JVM restarts and picks up the --add-opens flag
    existing = SparkSession.getActiveSession()
    if existing:
        existing.stop()

    spark = (
        SparkSession.builder
        .appName(app_name)
        .master(config.SPARK_MASTER)
        .config("spark.jars.packages",          packages)
        .config("spark.spline.producer.url",    config.SPLINE_PRODUCER)
        .config("spark.spline.mode",            "ENABLED")
        .config("spark.ui.enabled",             "false")
        .config("spark.sql.shuffle.partitions", config.SPARK_PARTITIONS)
        .getOrCreate()
    )

    # ── Activate Spline Agent ─────────────────────────────────────────────────
    # SparkLineageInitializer$ is a Scala companion object (singleton).
    # MODULE$ is Scala syntax for the singleton instance — $ is illegal in
    # Python identifiers so we must use getattr() instead of dot notation.
    init_cls = getattr(spark._jvm, "za.co.absa.spline.harvester.SparkLineageInitializer$")
    getattr(init_cls, "MODULE$").enableLineageTracking(spark._jsparkSession)
    logger.info("Spline Agent active for session '%s'", app_name)

    return spark


# ── Data cleaning ─────────────────────────────────────────────────────────────

def clean_dataframe(df, primary_key: str | None = None):
    """
    Apply standard data cleaning rules to a DataFrame:
      1. Deduplicate on primary key
      2. Fix email: null out sentinel strings, repair broken '@'
      3. abs(amount) and abs(price)
      4. Parse date/time columns with to_timestamp
    """
    from pyspark.sql import functions as F

    null_sentinel = os.getenv("DB_NULL_SENTINEL", "(NULL)")
    broken_char   = os.getenv("EMAIL_BROKEN_CHAR", "#")

    # 1. Deduplicate
    pk = primary_key or next((c for c in df.columns if c.lower().endswith("_id")), None)
    if pk and pk in df.columns:
        df = df.dropDuplicates([pk])

    # 2. Email
    if "email" in df.columns:
        df = df.withColumn("email",
            F.when(F.col("email").isin(null_sentinel, ""), None)
             .otherwise(F.regexp_replace(F.col("email"), broken_char, "@"))
        )

    # 3. Numeric
    if "amount" in df.columns:
        df = df.withColumn("amount", F.abs(F.col("amount").cast("double")))
    if "price" in df.columns:
        df = df.withColumn("price", F.abs(F.col("price").cast("double")))

    # 4. Dates
    for col in df.columns:
        if "date" in col.lower() or "time" in col.lower():
            df = df.withColumn(col,
                F.when(F.col(col).isin(null_sentinel, ""), None)
                 .otherwise(F.to_timestamp(F.col(col)))
            )

    return df


# ── ETL for one table ─────────────────────────────────────────────────────────

def run_table_etl(table, source_jdbc, source_user, source_pass,
                  target_jdbc, target_user, target_pass, spark,
                  primary_key=None) -> tuple[list[str], int]:
    """
    Read one table from MariaDB, clean it, write to PostgreSQL.

    The explicit select() calls before and after transforms are REQUIRED
    for Spline column-level lineage. Without them, Spline sees anonymous
    attribute IDs instead of named columns in its UI.

    Returns: (list_of_output_columns, row_count)
    """
    from pyspark.sql import functions as F

    # ── Read from MariaDB via JDBC ────────────────────────────────────────────
    df = (
        spark.read.format("jdbc")
        .option("url",      source_jdbc)
        .option("dbtable",  table)
        .option("driver",   "org.mariadb.jdbc.Driver")
        .option("user",     source_user)
        .option("password", source_pass)
        .load()
    )

    # Named select → Spline registers each column as an AttributeReference
    df = df.select([F.col(c) for c in df.columns])

    # ── Transform ─────────────────────────────────────────────────────────────
    df = clean_dataframe(df, primary_key=primary_key)

    # Named select before write → Spline maps output_col ← source_col
    df = df.select([F.col(c) for c in df.columns])

    row_count = df.count()

    # ── Write to PostgreSQL via JDBC ──────────────────────────────────────────
    (
        df.write.format("jdbc")
        .option("url",      target_jdbc)
        .option("dbtable",  table)
        .option("driver",   "org.postgresql.Driver")
        .option("user",     target_user)
        .option("password", target_pass)
        .mode("overwrite")
        .save()
    )

    logger.info("ETL done: table=%s rows=%d", table, row_count)
    return list(df.columns), row_count
