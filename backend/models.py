from sqlalchemy import Column, String, Integer, Float, DateTime, Text, JSON, Boolean # type: ignore
from sqlalchemy.ext.declarative import declarative_base # type: ignore
from sqlalchemy.sql import func # type: ignore
import uuid

Base = declarative_base()

class Integration(Base):
    __tablename__ = "integrations"
    id = Column(String(100), primary_key=True)
    name = Column(String(100), nullable=False)
    provider = Column(String(50), nullable=False)
    category = Column(String(50), nullable=False)
    host = Column(String(255))
    port = Column(Integer)
    database_name = Column(String(100))
    username = Column(String(100))
    password_encrypted = Column(Text)
    ssl_mode = Column(String(20))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class DataAsset(Base):
    __tablename__ = "data_assets"
    id = Column(String(100), primary_key=True)
    integration_id = Column(String(100), nullable=False)
    table_name = Column(String(100))
    column_name = Column(String(100))
    data_type = Column(String(100))
    is_nullable = Column(String(10))
    column_key = Column(String(20))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ScanResult(Base):
    __tablename__ = "scan_results"
    id = Column(String(100), primary_key=True)
    integration_id = Column(String(100), nullable=False)
    table_name = Column(String(100))
    column_name = Column(String(100))
    issue_type = Column(String(100))
    status = Column(String(20))
    row_count = Column(Integer)
    scan_batch_id = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class QualityScanResult(Base):
    __tablename__ = "quality_scan_results"
    id = Column(String(100), primary_key=True)
    integration_id = Column(String(100), nullable=False)
    integration_name = Column(String(255))
    rule_id = Column(String(100), nullable=False)
    rule_name = Column(String(255), nullable=False)
    rule_type = Column(String(50), nullable=False)
    table_name = Column(String(255), nullable=False)
    column_name = Column(String(255), nullable=False)
    severity = Column(String(20), nullable=False)
    score = Column(Float, default=100.0)
    status = Column(String(20), nullable=False)
    failed_rows = Column(Integer, default=0)
    total_rows = Column(Integer, default=0)
    reason = Column(Text)
    findings = Column(JSON)
    scanned_at = Column(DateTime(timezone=True), server_default=func.now())
    scan_batch_id = Column(String(100))

class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    id = Column(String(100), primary_key=True)
    integration_id = Column(String(100), nullable=False)
    integration_name = Column(String(255))
    status = Column(String(20), nullable=False, default='running')
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
    tables_scanned = Column(JSON)
    row_counts = Column(JSON)
    quality_score = Column(Float)
    log_entries = Column(JSON)
    error_message = Column(Text)
    scan_batch_id = Column(String(100))
    spline_plan_id = Column(String(100))

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(50), nullable=False)
    integration_id = Column(String(100))
    entity_type = Column(String(50))
    entity_id = Column(String(100))
    description = Column(Text)
    event_metadata = Column(JSON)
    status = Column(String(20), nullable=False, default='success')
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class CatalogSnapshot(Base):
    __tablename__ = "catalog_scan_results"
    id = Column(Integer, primary_key=True, autoincrement=True)
    integration_id = Column(String(100), nullable=False)
    snapshot_at = Column(DateTime(timezone=True), server_default=func.now())
    tables = Column(JSON)
    table_count = Column(Integer)
    column_count = Column(Integer)
    previous_snapshot_id = Column(Integer)
    changes_detected = Column(JSON)

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(50), unique=True)
    customer_name = Column(String(100))
    email = Column(String(100))
    amount = Column(Float)
    order_date = Column(DateTime)
    status = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = {'extend_existing': True}
    id = Column(Integer, primary_key=True, autoincrement=True)
    transaction_id = Column(String(50), unique=True)
    order_id = Column(String(50))
    payment_method = Column(String(50))
    transaction_date = Column(DateTime)
    amount = Column(Float)
    status = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
