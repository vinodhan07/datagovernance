"""
config.py — single source of truth for all settings.

Every value comes from .env (or the defaults here as fallback).
No other file should call os.getenv() directly.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── PostgreSQL (app metadata DB) ──────────────────────────────────────────────
POSTGRES_URL = os.getenv("POSTGRES_URL", "postgresql://myuser:mypassword@localhost:5432/dataguard")
TARGET_DB    = os.getenv("TARGET_DB_NAME", "company_data")   # ETL output DB

# ── MariaDB (source data) ─────────────────────────────────────────────────────
# Docker exposes MariaDB on host port 3307 → container port 3306
MARIADB_HOST = os.getenv("MARIADB_HOST", "")
MARIADB_PORT = int(os.getenv("MARIADB_PORT", "0"))
MARIADB_DB   = os.getenv("MARIADB_DB",   "")
MARIADB_USER = os.getenv("MARIADB_USER", "")
MARIADB_PASS = os.getenv("MARIADB_PASS", "")

# ── Spline (lineage stack) ────────────────────────────────────────────────────
SPLINE_PRODUCER = os.getenv("SPLINE_PRODUCER_URL", "http://localhost:8080/producer")
SPLINE_CONSUMER = os.getenv("SPLINE_CONSUMER_URL", "http://localhost:8080/consumer")
SPLINE_WEB_UI   = os.getenv("SPLINE_WEB_UI_URL",   "http://localhost:9090")
ARANGO_URL      = os.getenv("ARANGO_URL",           "http://localhost:8529")
ARANGO_DB       = os.getenv("ARANGO_DB",            "spline")

# ── Spark session ─────────────────────────────────────────────────────────────
# Why JDBC JARs? PySpark runs on the JVM. The actual data transfer happens in
# Java, not Python. JDBC is Java's database connector — same role as pymysql
# for Python. These JAR versions are downloaded from Maven Central by Spark.
SPARK_MASTER       = os.getenv("SPARK_MASTER",              "local[*]")
SPARK_PARTITIONS   = os.getenv("SPARK_SHUFFLE_PARTITIONS",  "4")
SPLINE_AGENT_VER   = os.getenv("SPLINE_AGENT_VERSION",      "2.2.1")
MARIADB_JAR_VER    = os.getenv("MARIADB_DRIVER_VERSION",    "2.7.9")
POSTGRES_JAR_VER   = os.getenv("POSTGRES_DRIVER_VERSION",   "42.7.3")

# ── Security ──────────────────────────────────────────────────────────────────
ENCRYPTION_KEY   = os.getenv("ENCRYPTION_KEY", "")
JWT_SECRET       = os.getenv("JWT_SECRET", "dataguard-dev-secret-change-in-production")
JWT_ALGORITHM    = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

# ── OpenMetadata catalog ───────────────────────────────────────────────────────
OPENMETADATA_URL       = os.getenv("OPENMETADATA_URL",       "http://localhost:8585/api")
OPENMETADATA_JWT_TOKEN = os.getenv("OPENMETADATA_JWT_TOKEN", "")

# ── Spline consumer polling ───────────────────────────────────────────────────
SPLINE_POLL_RETRIES = int(os.getenv("SPLINE_CONSUMER_POLL_RETRIES", "6"))
SPLINE_POLL_DELAY   = float(os.getenv("SPLINE_CONSUMER_POLL_DELAY", "2.0"))
SPLINE_PAGE_SIZE    = int(os.getenv("SPLINE_CONSUMER_PAGE_SIZE",    "20"))
