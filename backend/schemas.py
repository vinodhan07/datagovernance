"""
Pydantic schemas for request/response validation.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


class CredentialField(BaseModel):
    key: str
    label: str
    type: str = "text"
    placeholder: str = ""
    required: bool = True


class TemplateCreate(BaseModel):
    provider_name: str
    category: str
    description: str = ""
    logo_url: str = ""
    credential_fields: list[CredentialField] = []


class TemplateOut(TemplateCreate):
    id: str
    created_at: datetime

    class Config:
        from_attributes = True


class IntegrationCreate(BaseModel):
    template_id: str
    name: str
    credentials: dict[str, Any]


class IntegrationOut(BaseModel):
    id: str
    template_id: str
    name: str
    provider_name: str
    status: str = "active"
    created_at: datetime

    class Config:
        from_attributes = True


class TestResult(BaseModel):
    success: bool
    message: str


class RuleCreate(BaseModel):
    name: str
    rule_type: str              # null_check | range_check | format_check | duplicate_check
    table_name: str
    column_name: str
    severity: str = "warning"
    params: dict[str, Any] = Field(default_factory=dict)


class RuleOut(RuleCreate):
    id: str
    created_at: datetime

    class Config:
        from_attributes = True


class ScanResultOut(BaseModel):
    id: str
    integration_id: str
    integration_name: Optional[str]
    rule_id: str
    rule_name: str
    rule_type: str
    table_name: str
    column_name: str
    severity: str
    score: float
    status: str
    failed_rows: int
    total_rows: int
    reason: Optional[str]
    findings: Optional[dict[str, Any]]
    scanned_at: datetime
    scan_batch_id: Optional[str]

    class Config:
        from_attributes = True


class ScanResponse(BaseModel):
    scan_batch_id: str
    integration_id: str
    results: list[ScanResultOut]
    overall_score: float
    scanned_at: datetime


class DashboardStats(BaseModel):
    integrations: int
    quality_rules: int
    quality_score: float = 100.0
