"""
schemas.py — Pydantic request/response models for the DataGuard API.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel


class IntegrationCreate(BaseModel):
    template_id: str
    name: str
    credentials: dict[str, Any]


class IntegrationOut(BaseModel):
    id: str
    name: str
    provider_name: str
    status: str = "active"
    created_at: datetime

    class Config:
        from_attributes = True


class TestResult(BaseModel):
    success: bool
    message: str


class DashboardStats(BaseModel):
    integrations: int
    pipeline_runs: int
    completed_runs: int
    failed_runs: int
    quality_rules: int = 0
    quality_score: Optional[float] = None


# ── Catalog schemas ────────────────────────────────────────────────────────────

class CatalogColumnOut(BaseModel):
    name: str
    data_type: Optional[str] = None
    description: Optional[str] = None
    tags: list[str] = []


class CatalogTableOut(BaseModel):
    fqn: str
    name: str
    description: Optional[str] = None
    tags: list[str] = []
    columns: list[CatalogColumnOut] = []
    service_name: Optional[str] = None


class CatalogTagRequest(BaseModel):
    tags: list[str]


class CatalogIngestResponse(BaseModel):
    tables_pushed: int
    service_fqn: str
    message: str


# ── Quality schemas ────────────────────────────────────────────────────────────

class QualityRuleCreate(BaseModel):
    integration_id: str
    table_name: str
    column_name: Optional[str] = None
    check_type: str       # null_count | duplicate_count | min | max | row_count
    threshold: str        # e.g. "= 0" or "> 0" or "< 100"


class QualityRuleOut(BaseModel):
    id: int
    integration_id: str
    table_name: str
    column_name: Optional[str] = None
    check_type: str
    threshold: str
    check_yaml: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class QualityScanOut(BaseModel):
    id: int
    integration_id: str
    status: str
    score: Optional[float] = None
    started_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class QualityFindingOut(BaseModel):
    id: int
    scan_id: int
    table_name: str
    column_name: Optional[str] = None
    check_type: Optional[str] = None
    status: Optional[str] = None
    value: Optional[str] = None

    class Config:
        from_attributes = True


class QualityScanDetailOut(QualityScanOut):
    findings: list[QualityFindingOut] = []


class QualityScoreOut(BaseModel):
    integration_id: str
    score: Optional[float] = None
    scan_id: Optional[int] = None
    scanned_at: Optional[datetime] = None


# ── Auth schemas ───────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    full_name: Optional[str] = None


class UserLogin(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    full_name: Optional[str] = None


class UserOut(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
