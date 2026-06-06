"""
schemas.py — Pydantic request/response models for the DataGuard API.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any
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
