"""
models.py — SQLAlchemy ORM models for the DataGuard ETL Lineage Platform.

PostgreSQL `dataguard` database stores:
  - users               Authenticated user accounts
  - integrations        Encrypted connector credentials
  - pipeline_runs       ETL execution history
  - audit_logs          Immutable event trail
  - lineage_jobs        One record per ETL job
  - lineage_datasets    Source / target dataset metadata
  - lineage_columns     Individual columns per dataset
  - lineage_transformations  Ordered transformation steps
  - lineage_edges       Column-to-column links (source_col → target_col)
  - lineage_executions  Runtime execution record with Spline plan ID
  - quality_rules       SodaCL check definitions per table/column
  - quality_scans       One record per Soda Core scan run
  - quality_findings    One row per check result within a scan
"""

from datetime import datetime

from sqlalchemy import Column, String, Integer, Float, DateTime, Text, JSON, Index, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Users
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class User(Base):
    __tablename__ = "users"
    id            = Column(Integer, primary_key=True, autoincrement=True)
    username      = Column(String(100), unique=True, nullable=False, index=True)
    email         = Column(String(255), unique=True)
    full_name     = Column(String(255))
    password_hash = Column(String(255), nullable=False)
    created_at    = Column(DateTime, default=datetime.utcnow)
    last_login    = Column(DateTime)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Connector credentials
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class Integration(Base):
    """Stores encrypted credentials for an external MariaDB connector."""
    __tablename__ = "integrations"
    id                 = Column(String(100), primary_key=True)
    name               = Column(String(100), nullable=False)
    provider           = Column(String(50),  nullable=False, default="MariaDB")
    category           = Column(String(50),  nullable=False, default="database")
    host               = Column(String(255))
    port               = Column(Integer)
    database_name      = Column(String(100))
    username           = Column(String(100))
    password_encrypted = Column(Text)
    ssl_mode           = Column(String(20),  default="disable")
    created_at         = Column(DateTime(timezone=True), server_default=func.now())
    updated_at         = Column(DateTime(timezone=True), onupdate=func.now())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Pipeline runs
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class PipelineRun(Base):
    """One record per pipeline execution (MariaDB → PySpark ETL → PostgreSQL)."""
    __tablename__ = "pipeline_runs"
    id               = Column(String(100), primary_key=True)
    integration_id   = Column(String(100), nullable=False)
    integration_name = Column(String(255))
    status           = Column(String(20),  nullable=False, default="running")
    started_at       = Column(DateTime(timezone=True), server_default=func.now())
    completed_at     = Column(DateTime(timezone=True))
    tables_scanned   = Column(JSON)     # list of table names processed
    row_counts       = Column(JSON)     # {table: row_count}
    error_message    = Column(Text)
    spline_plan_id   = Column(String(100))  # last Spline plan ID for this run


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Audit log
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class AuditLog(Base):
    """Append-only event trail. Never updated, never deleted."""
    __tablename__ = "audit_logs"
    id             = Column(Integer, primary_key=True, autoincrement=True)
    event_type     = Column(String(50),  nullable=False)   # CONNECT | PIPELINE_START | PIPELINE_DONE | PIPELINE_FAIL
    integration_id = Column(String(100))
    entity_type    = Column(String(50))   # integration | quality_scan | catalog_ingest
    entity_id      = Column(String(100))
    description    = Column(Text)
    event_metadata = Column(JSON)
    status         = Column(String(20),  nullable=False, default="success")
    created_at     = Column(DateTime(timezone=True), server_default=func.now())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Lineage tables
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class LineageJob(Base):
    """One ETL job definition — created once per pipeline run."""
    __tablename__ = "lineage_jobs"
    id             = Column(String(100), primary_key=True)
    name           = Column(String(255), nullable=False)
    integration_id = Column(String(100))
    job_type       = Column(String(50),  default="etl")
    created_at     = Column(DateTime(timezone=True), server_default=func.now())


class LineageDataset(Base):
    """A source or target dataset tracked within a lineage job."""
    __tablename__ = "lineage_datasets"
    __table_args__ = (
        Index("ix_lineage_datasets_job_id", "job_id"),
        Index("ix_lineage_datasets_name",   "name"),
    )
    id           = Column(String(100), primary_key=True)
    job_id       = Column(String(100), nullable=False)
    name         = Column(String(255), nullable=False)
    uri          = Column(Text)
    dataset_type = Column(String(20),  nullable=False)   # "source" | "target"
    columns_json = Column(JSON)                          # list of column names
    created_at   = Column(DateTime(timezone=True), server_default=func.now())


class LineageColumn(Base):
    """An individual column within a tracked dataset."""
    __tablename__ = "lineage_columns"
    id         = Column(String(100), primary_key=True)
    dataset_id = Column(String(100), nullable=False)
    name       = Column(String(255), nullable=False)
    data_type  = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class LineageTransformation(Base):
    """A transformation step applied during an ETL job."""
    __tablename__ = "lineage_transformations"
    __table_args__ = (
        Index("ix_lineage_transformations_job_id", "job_id"),
    )
    id               = Column(String(100), primary_key=True)
    job_id           = Column(String(100), nullable=False)
    name             = Column(String(255), nullable=False)
    operation_type   = Column(String(100), nullable=False)
    parameters_json  = Column(JSON)
    order_index      = Column(Integer,     default=0)
    columns_affected = Column(JSON)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())


class LineageEdge(Base):
    """
    Column-to-column lineage edge: source_col → target_col via a transformation.
    Indexed for fast BFS in both directions (upstream / downstream impact analysis).
    """
    __tablename__ = "lineage_edges"
    __table_args__ = (
        Index("ix_lineage_edges_src",    "source_column", "source_dataset"),
        Index("ix_lineage_edges_tgt",    "target_column", "target_dataset"),
        Index("ix_lineage_edges_job_id", "job_id"),
    )
    id                 = Column(String(100), primary_key=True)
    job_id             = Column(String(100), nullable=False)
    source_dataset     = Column(String(255), nullable=False)
    source_column      = Column(String(255), nullable=False)
    target_dataset     = Column(String(255), nullable=False)
    target_column      = Column(String(255), nullable=False)
    transformation_id  = Column(String(100))
    transformations_json = Column(JSON)     # list of transform names applied
    created_at         = Column(DateTime(timezone=True), server_default=func.now())


class LineageExecution(Base):
    """Runtime record of a lineage-tracked pipeline execution."""
    __tablename__ = "lineage_executions"
    __table_args__ = (
        Index("ix_lineage_executions_job_id", "job_id"),
    )
    id              = Column(String(100), primary_key=True)
    job_id          = Column(String(100), nullable=False)
    pipeline_run_id = Column(String(100))
    started_at      = Column(DateTime(timezone=True))
    completed_at    = Column(DateTime(timezone=True))
    status          = Column(String(20),  default="completed")
    lineage_json    = Column(JSON)   # full lineage output
    dag_json        = Column(JSON)   # React Flow nodes + edges
    spline_plan_id  = Column(String(100))
    created_at      = Column(DateTime(timezone=True), server_default=func.now())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Data quality (Soda Core)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class QualityRule(Base):
    """One SodaCL check definition — tied to a specific table/column."""
    __tablename__ = "quality_rules"
    __table_args__ = (
        Index("ix_quality_rules_integration_id", "integration_id"),
    )
    id             = Column(Integer, primary_key=True, autoincrement=True)
    integration_id = Column(String(100), nullable=False)
    table_name     = Column(String(255), nullable=False)
    column_name    = Column(String(255))          # None = table-level check
    check_type     = Column(String(100), nullable=False)  # null_count | duplicate_count | min | max | row_count
    threshold      = Column(String(100), nullable=False)  # e.g. "= 0" or "< 100"
    check_yaml     = Column(Text)                 # generated SodaCL YAML snippet (for display)
    created_at     = Column(DateTime, default=datetime.utcnow)


class QualityScan(Base):
    """One Soda Core scan execution — covers all rules for one integration."""
    __tablename__ = "quality_scans"
    __table_args__ = (
        Index("ix_quality_scans_integration_id", "integration_id"),
    )
    id             = Column(Integer, primary_key=True, autoincrement=True)
    integration_id = Column(String(100), nullable=False)
    status         = Column(String(20), default="running")   # running | completed | failed
    score          = Column(Float)                            # passed / total * 100
    started_at     = Column(DateTime, default=datetime.utcnow)
    completed_at   = Column(DateTime)
    result_json    = Column(Text)                             # raw Soda output JSON


class QualityFinding(Base):
    """One row per check result within a scan."""
    __tablename__ = "quality_findings"
    __table_args__ = (
        Index("ix_quality_findings_scan_id", "scan_id"),
    )
    id          = Column(Integer, primary_key=True, autoincrement=True)
    scan_id     = Column(Integer, ForeignKey("quality_scans.id"), nullable=False)
    table_name  = Column(String(255), nullable=False)
    column_name = Column(String(255))
    check_type  = Column(String(100))
    status      = Column(String(20))    # pass | fail | warn
    value       = Column(String(255))   # actual measured value


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AI Governance
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class AIModel(Base):
    """Registry of AI / GenAI models used by the organisation."""
    __tablename__ = "ai_models"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    name           = Column(String(255), nullable=False)
    provider       = Column(String(100))          # OpenAI | Anthropic | HuggingFace | Custom
    model_type     = Column(String(50))           # LLM | ML | CV | NLP
    version        = Column(String(50))
    purpose        = Column(Text)
    owner          = Column(String(255))
    risk_level     = Column(String(20), default="minimal")  # minimal | limited | high | unacceptable
    status         = Column(String(20), default="active")   # active | deprecated | under_review
    uses_pii       = Column(Boolean, default=False)
    autonomous     = Column(Boolean, default=False)
    integration_id = Column(String(100))          # optional link to a connector's data source
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
    updated_at     = Column(DateTime(timezone=True), onupdate=func.now())


class AIComplianceCheck(Base):
    """Per-model compliance checklist items."""
    __tablename__ = "ai_compliance_checks"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    model_id     = Column(Integer, nullable=False)  # logical ref to ai_models.id
    check_name   = Column(String(255), nullable=False)
    check_status = Column(String(20), default="pending")  # pass | fail | pending
    notes        = Column(Text)
    checked_at   = Column(DateTime(timezone=True))
    created_at   = Column(DateTime(timezone=True), server_default=func.now())