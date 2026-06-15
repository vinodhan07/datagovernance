"""
ml_governance.py
────────────────
ML Governance — MLflow-connected model registry with Bias, Drift, Explainability.

Flow:
  1. User provides an MLflow tracking server URL → POST /ml-governance/connect
  2. Backend fetches registered models live from that server → GET /ml-governance/registry
  3. User configures a model (data table + columns) → POST /ml-governance/models
  4. Scan runs: downloads real model from MLflow (proxy fallback) + bias/drift/SHAP

Endpoints:
  POST   /ml-governance/connect              — save + validate MLflow URL
  GET    /ml-governance/connect              — get current connection
  DELETE /ml-governance/connect/{id}         — remove connection
  GET    /ml-governance/registry             — list models from MLflow registry (live)
  GET    /ml-governance/registry/{name}/versions — list all versions of a model
  GET    /ml-governance/models               — list locally-configured models
  POST   /ml-governance/models               — save scan config for a model
  PUT    /ml-governance/models/{id}          — update scan config
  DELETE /ml-governance/models/{id}          — remove scan config
  GET    /ml-governance/models/{id}/scans    — list scans for a model
  POST   /ml-governance/models/{id}/scan     — start a governance scan (SSE stream)
  GET    /ml-governance/scans/{scan_id}      — get scan result
  GET    /ml-governance/summary              — dashboard stats
"""

from __future__ import annotations

import json
import asyncio
import traceback
from datetime import datetime, timezone
from typing import AsyncGenerator, Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from src.core.database import get_db, SessionLocal
from src.domain.entities import MLModel, MLGovernanceScan, MLflowConnection, Integration
from src.modules.observer.audit import log_audit
from src.core.config import MLFLOW_TRACKING_URI

router = APIRouter()


# ── Serialisers ────────────────────────────────────────────────────────────────

def _conn_out(c: MLflowConnection) -> dict:
    return {
        "id":         c.id,
        "url":        c.url,
        "alias":      c.alias,
        "status":     c.status,
        "error_msg":  c.error_msg,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def _model_out(m: MLModel) -> dict:
    return {
        "id":                m.id,
        "name":              m.name,
        "framework":         m.framework,
        "task_type":         m.task_type,
        "version":           m.version,
        "description":       m.description,
        "owner":             m.owner,
        "integration_id":    m.integration_id,
        "target_table":      m.target_table,
        "target_column":     m.target_column,
        "feature_columns":   m.feature_columns or [],
        "protected_attrs":   m.protected_attrs or [],
        "status":            m.status or "active",
        "mlflow_server_url": m.mlflow_server_url,
        "mlflow_model_name": m.mlflow_model_name,
        "mlflow_version":    m.mlflow_version,
        "mlflow_stage":      m.mlflow_stage,
        "created_at":        m.created_at.isoformat() if m.created_at else None,
    }


def _scan_out(s: MLGovernanceScan) -> dict:
    return {
        "id":            s.id,
        "model_id":      s.model_id,
        "scan_type":     s.scan_type,
        "status":        s.status,
        "bias_results":  s.bias_results,
        "drift_results": s.drift_results,
        "shap_results":  s.shap_results,
        "model_card":    s.model_card,
        "mlflow_run_id": s.mlflow_run_id,
        "error_message": s.error_message,
        "started_at":    s.started_at.isoformat() if s.started_at else None,
        "completed_at":  s.completed_at.isoformat() if s.completed_at else None,
    }


# ── MLflow Auto-Configuration & Scans ──────────────────────────────────────────

def _extract_signature_from_mlflow(client, model_name, version):
    import json
    import tempfile
    import yaml
    import mlflow
    from mlflow.artifacts import download_artifacts
    
    try:
        mlflow.set_tracking_uri(client.tracking_uri)
        mv = client.get_model_version(model_name, version)
        run_id = mv.run_id
        
        # Determine model artifact directory in the run
        model_dir = "model"
        try:
            artifacts = client.list_artifacts(run_id)
            for art in artifacts:
                if art.is_dir and ("model" in art.path or "classifier" in art.path or "regressor" in art.path):
                    model_dir = art.path
                    break
        except Exception:
            pass
            
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = download_artifacts(artifact_uri=f"runs:/{run_id}/{model_dir}/MLmodel", dst_path=tmpdir)
            with open(local_path, "r") as f:
                meta = yaml.safe_load(f)
                signature = meta.get("signature")
                if signature:
                    inputs = signature.get("inputs", [])
                    outputs = signature.get("outputs", [])
                    
                    if isinstance(inputs, str):
                        inputs = json.loads(inputs)
                    if isinstance(outputs, str):
                        outputs = json.loads(outputs)
                        
                    feature_cols = [inp.get("name") for inp in inputs if inp.get("name")]
                    target_cols = [out.get("name") for out in outputs if out.get("name")]
                    return feature_cols, (target_cols[0] if target_cols else None)
    except Exception as e:
        print(f"Error reading model signature: {e}")
    return [], None



def _provision_adult_income_dataset_if_needed():
    from sqlalchemy import create_engine as _ce
    from sqlalchemy import inspect
    import requests
    import io
    try:
        mariadb_url = "mysql+pymysql://root:root123@127.0.0.1:3307/governance_db"
        mariadb_engine = _ce(mariadb_url)
        inspector = inspect(mariadb_engine)
        if "adult_income" not in inspector.get_table_names():
            print("Downloading Adult Income dataset automatically to MariaDB...")
            url = "https://archive.ics.uci.edu/ml/machine-learning-databases/adult/adult.data"
            columns = [
                "age", "workclass", "fnlwgt", "education", "education_num",
                "marital_status", "occupation", "relationship", "race", "sex",
                "capital_gain", "capital_loss", "hours_per_week", "native_country", "income"
            ]
            res = requests.get(url, timeout=10)
            df = pd.read_csv(io.StringIO(res.text), names=columns, na_values=" ?", skipinitialspace=True)
            df.dropna(inplace=True)
            df.to_sql("adult_income", mariadb_engine, if_exists="replace", index=False)
            print("Successfully provisioned adult_income table on MariaDB.")
    except Exception as e:
        print(f"Error provisioning adult_income on MariaDB: {e}")


def run_scan_sync(model_id: int, db: Session):
    scan = MLGovernanceScan(model_id=model_id, status="running")
    db.add(scan)
    db.commit()
    db.refresh(scan)
    
    try:
        ml_model = db.query(MLModel).filter(MLModel.id == model_id).first()
        conn = db.query(MLflowConnection).filter(MLflowConnection.status == "connected").first()
        
        df = _load_data(db, ml_model)
        if df is None or df.empty:
            setattr(scan, "status", "failed")
            setattr(scan, "error_message", "No data available. Set a target table in the model configuration.")
            setattr(scan, "completed_at", datetime.now(timezone.utc))
            db.commit()
            return
            
        feature_cols = ml_model.feature_columns or []
        target_col = ml_model.target_column
        protected = ml_model.protected_attrs or []

        if not feature_cols:
            exclude = set([target_col] + protected) if target_col else set(protected)
            feature_cols = [c for c in df.columns if c not in exclude]

        model_card, proxy, X_train, X_test, y_train, y_test, mlflow_run_id = \
            _load_or_train(df, feature_cols, target_col, ml_model, conn)

        bias_results = _run_bias(proxy, X_test, y_test, df, protected, feature_cols, ml_model.task_type)
        drift_results = _run_drift(df, feature_cols)
        shap_results = _run_shap(proxy, X_test, feature_cols)

        setattr(scan, "bias_results", bias_results)
        setattr(scan, "drift_results", drift_results)
        setattr(scan, "shap_results", shap_results)
        setattr(scan, "model_card", model_card)
        setattr(scan, "mlflow_run_id", mlflow_run_id)
        setattr(scan, "status", "completed")
        setattr(scan, "completed_at", datetime.now(timezone.utc))
        db.commit()
        
        log_audit(db, "ML_GOVERNANCE_SCAN", description=f"Governance scan completed for model '{ml_model.name}'", entity_type="ml_model", entity_id=str(model_id))
    except Exception as e:
        setattr(scan, "status", "failed")
        setattr(scan, "error_message", str(e))
        setattr(scan, "completed_at", datetime.now(timezone.utc))
        db.commit()


def sync_and_autoscan_models_background(url: str):
    from src.core.database import SessionLocal
    db = SessionLocal()
    try:
        from mlflow.tracking import MlflowClient
        client = MlflowClient(tracking_uri=url)
        try:
            models = client.search_registered_models()
        except Exception as e:
            print(f"Error listing registry: {e}")
            return
            
        for m in models:
            if not m.latest_versions:
                continue
            latest_version_obj = m.latest_versions[0]
            version = latest_version_obj.version
            run_id = latest_version_obj.run_id
            stage = latest_version_obj.current_stage
            
            feature_cols, target_col = _extract_signature_from_mlflow(client, m.name, version)
            existing = db.query(MLModel).filter(MLModel.mlflow_model_name == m.name).first()
            
            task_type = "classification"
            try:
                run = client.get_run(run_id)
                metrics = run.data.metrics
                if "r2_score" in metrics or "rmse" in metrics:
                    task_type = "regression"
            except Exception:
                pass
                
            target_table = None
            if "adult" in m.name.lower() or "income" in m.name.lower():
                _provision_adult_income_dataset_if_needed()
                target_table = "adult_income"
                if not target_col:
                    target_col = "income"
                if not feature_cols:
                    feature_cols = ["age", "workclass", "education", "education_num", "marital_status", "occupation", "relationship", "race", "sex", "capital_gain", "capital_loss", "hours_per_week", "native_country"]
            else:
                from src.core.database import engine as pg_engine
                from sqlalchemy import inspect
                try:
                    inspector = inspect(pg_engine)
                    for t_name in inspector.get_table_names():
                        cols = [c["name"] for c in inspector.get_columns(t_name)]
                        if target_col and target_col in cols:
                            target_table = t_name
                            break
                        if any(f in cols for f in feature_cols):
                            target_table = t_name
                            break
                except Exception:
                    pass
            
            protected_attrs = []
            all_possible_cols = feature_cols + ([target_col] if target_col else [])
            for col in all_possible_cols:
                if col.lower() in ["sex", "gender", "race", "age", "age_group"]:
                    if col not in protected_attrs:
                        protected_attrs.append(col)
            
            if existing:
                existing.mlflow_version = version
                existing.mlflow_stage = stage
                existing.mlflow_server_url = url
                if not existing.target_table and target_table:
                    existing.target_table = target_table
                if not existing.target_column and target_col:
                    existing.target_column = target_col
                if not existing.feature_columns and feature_cols:
                    existing.feature_columns = feature_cols
                if not existing.protected_attrs and protected_attrs:
                    existing.protected_attrs = protected_attrs
                db.commit()
                model_id = getattr(existing, "id")
            else:
                new_model = MLModel(
                    name=m.name,
                    framework="sklearn",
                    task_type=task_type,
                    version=version,
                    description=m.description or f"Auto-configured from MLflow model {m.name}",
                    owner="auto",
                    target_table=target_table,
                    target_column=target_col,
                    feature_columns=feature_cols,
                    protected_attrs=protected_attrs,
                    status="active",
                    mlflow_server_url=url,
                    mlflow_model_name=m.name,
                    mlflow_version=version,
                    mlflow_stage=stage
                )
                db.add(new_model)
                db.commit()
                db.refresh(new_model)
                model_id = getattr(new_model, "id")
                log_audit(db, "ML_MODEL_CONFIGURED", description=f"ML model '{m.name}' auto-configured for governance", entity_type="ml_model", entity_id=str(model_id))
            
            run_scan_sync(model_id, db)
            
    except Exception as e:
        print(f"Error in sync task: {e}")
    finally:
        db.close()


@router.post("/sync-and-scan")
def manual_sync_and_scan(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    conn = db.query(MLflowConnection).filter(MLflowConnection.status == "connected").first()
    if not conn:
        raise HTTPException(400, "No active MLflow connection.")
    background_tasks.add_task(sync_and_autoscan_models_background, str(conn.url))
    return {"message": "Sync and auto-scan started in background."}


@router.post("/train-register", status_code=201)
def train_and_register_endpoint(data: dict, db: Session = Depends(get_db)):
    conn = db.query(MLflowConnection).filter(MLflowConnection.status == "connected").first()
    if not conn:
        raise HTTPException(400, "No active MLflow connection. Connect to MLflow server first.")
        
    model_name = (data.get("model_name") or "").strip()
    if not model_name:
        raise HTTPException(400, "Model Name is required")
        
    task_type = data.get("task_type", "classification")
    db_host = data.get("db_host") or "127.0.0.1"
    
    db_port_val = data.get("db_port")
    db_port = int(db_port_val) if db_port_val and str(db_port_val).strip() else 3307
    
    db_user = data.get("db_user") or "root"
    db_password = data.get("db_password") or "root123"
    db_name = data.get("db_name") or "governance_db"
    target_table = (data.get("target_table") or "").strip()
    target_column = (data.get("target_column") or "").strip()
    feature_columns = data.get("feature_columns", [])
    protected_attrs = data.get("protected_attrs", [])
    
    if not target_table:
        raise HTTPException(400, "Target Table is required")
    if not target_column:
        raise HTTPException(400, "Target Column is required")
        
    # Parse feature_columns / protected_attrs if they are strings
    if isinstance(feature_columns, str):
        feature_columns = [s.strip() for s in feature_columns.split(",") if s.strip()]
    if isinstance(protected_attrs, str):
        protected_attrs = [s.strip() for s in protected_attrs.split(",") if s.strip()]

    # Connect to database and load data
    from sqlalchemy import create_engine as _ce
    try:
        db_url = f"mysql+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
        mariadb_engine = _ce(db_url)
        df = pd.read_sql(f"SELECT * FROM `{target_table}` LIMIT 5000", mariadb_engine)
    except Exception as e:
        raise HTTPException(400, f"Failed to load data from database: {e}")
        
    if df.empty:
        raise HTTPException(400, "The dataset table is empty")
        
    if target_column not in df.columns:
        raise HTTPException(400, f"Target column '{target_column}' not found in the table")
        
    # Find or dynamically create/save an integration for these database credentials
    from src.core.security import encrypt_password
    import uuid
    
    existing_intg = db.query(Integration).filter(
        Integration.host == db_host,
        Integration.port == db_port,
        Integration.database_name == db_name,
        Integration.username == db_user
    ).first()
    
    if existing_intg:
        integration_id = existing_intg.id
    else:
        integration_id = f"mariadb_auto_{uuid.uuid4().hex[:8]}"
        pwd_enc = encrypt_password(db_password)
        new_intg = Integration(
            id=integration_id,
            name=f"Auto DB {db_name} ({db_host})",
            provider="MariaDB",
            category="database",
            host=db_host,
            port=db_port,
            database_name=db_name,
            username=db_user,
            password_encrypted=pwd_enc
        )
        db.add(new_intg)
        db.commit()

    # Preprocess data and train
    import mlflow
    import mlflow.sklearn
    from mlflow.models.signature import infer_signature
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import LabelEncoder
    from sklearn.metrics import accuracy_score, r2_score
    
    available = [c for c in feature_columns if c in df.columns] if feature_columns else [c for c in df.columns if c != target_column]
    if not available:
        raise HTTPException(400, "No valid feature columns found")
        
    X = df[available].copy()
    for col in X.select_dtypes(include=["object", "category"]).columns:
        le = LabelEncoder()
        X[col] = le.fit_transform(X[col].astype(str))
    X = X.fillna(X.median(numeric_only=True)).fillna(0)
    X = X.astype(float) # Cast to float to avoid schema mismatches
    
    y_raw = df[target_column]
    if task_type == "classification" or y_raw.dtype == object:
        le = LabelEncoder()
        y = le.fit_transform(y_raw.astype(str))
        is_clf = True
    else:
        y = y_raw.values
        is_clf = False
        
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.25, random_state=42)
    
    # Train, log & register to MLflow
    try:
        mlflow.set_tracking_uri(conn.url)
        mlflow.set_experiment("dataguard_ml_governance")
        
        if is_clf:
            model_obj = RandomForestClassifier(n_estimators=50, max_depth=6, random_state=42)
            model_obj.fit(X_train, y_train)
            preds = model_obj.predict(X_test)
            acc = float(accuracy_score(y_test, preds))
            metric_key, metric_val = "accuracy", round(acc, 4)
        else:
            model_obj = RandomForestRegressor(n_estimators=50, max_depth=6, random_state=42)
            model_obj.fit(X_train, y_train)
            preds = model_obj.predict(X_test)
            r2 = float(r2_score(y_test, preds))
            metric_key, metric_val = "r2_score", round(r2, 4)
            
        signature = infer_signature(X_train, y_train)
        
        with mlflow.start_run(run_name=f"train_{model_name}") as run:
            mlflow.log_params({
                "model_type": "RandomForest" + ("Classifier" if is_clf else "Regressor"),
                "n_estimators": 50,
                "max_depth": 6,
                "n_samples": len(df),
                "n_features": len(available)
            })
            mlflow.log_metric(metric_key, metric_val)
            
            mlflow.sklearn.log_model(
                sk_model=model_obj,
                artifact_path="model",
                signature=signature,
                registered_model_name=model_name
            )
            run_id = run.info.run_id
            
        from mlflow.tracking import MlflowClient
        client = MlflowClient(tracking_uri=conn.url)
        versions = client.search_model_versions(f"name='{model_name}'")
        latest_version = versions[0].version if versions else "1"
        
    except Exception as e:
        raise HTTPException(502, f"Failed to train & register model in MLflow: {e}")
        
    m = db.query(MLModel).filter(MLModel.mlflow_model_name == model_name).first()
    if not m:
        m = MLModel(
            name=model_name,
            framework="sklearn",
            task_type=task_type,
            version=latest_version,
            description=f"Automatically trained and registered model: {model_name}",
            owner="auto",
            integration_id=integration_id,
            target_table=target_table,
            target_column=target_column,
            feature_columns=available,
            protected_attrs=protected_attrs,
            status="active",
            mlflow_server_url=conn.url,
            mlflow_model_name=model_name,
            mlflow_version=latest_version,
            mlflow_stage="None"
        )
        db.add(m)
    else:
        m.task_type = task_type
        m.version = latest_version
        m.integration_id = integration_id
        m.target_table = target_table
        m.target_column = target_column
        m.feature_columns = available
        m.protected_attrs = protected_attrs
        m.mlflow_server_url = conn.url
        m.mlflow_version = latest_version
        
    db.commit()
    db.refresh(m)
    
    run_scan_sync(int(getattr(m, 'id')), db)
    return _model_out(m)



# ── MLflow Connection ──────────────────────────────────────────────────────────

@router.get("/connect")
def get_connection(db: Session = Depends(get_db)):
    connections = db.query(MLflowConnection).order_by(MLflowConnection.created_at.desc()).all()
    return [_conn_out(c) for c in connections]


@router.post("/connect", status_code=201)
def connect_mlflow(data: dict, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    url = (data.get("url") or "").strip().rstrip("/")
    if not url:
        raise HTTPException(400, "MLflow server URL is required")

    # Validate connection
    try:
        from mlflow.tracking import MlflowClient
        client = MlflowClient(tracking_uri=url)
        client.search_registered_models(max_results=1)
        status = "connected"
        error_msg = None
    except Exception as e:
        status = "error"
        error_msg = str(e)[:500]

    # Upsert — only one connection at a time
    existing = db.query(MLflowConnection).first()
    if existing:
        setattr(existing, "url", url)
        setattr(existing, "alias", data.get("alias", "default"))
        setattr(existing, "status", status)
        setattr(existing, "error_msg", error_msg)
        db.commit()
        db.refresh(existing)
        if status == "connected":
            background_tasks.add_task(sync_and_autoscan_models_background, url)
        return _conn_out(existing)

    conn = MLflowConnection(
        url=url,
        alias=data.get("alias", "default"),
        status=status,
        error_msg=error_msg,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    log_audit(db, "MLFLOW_CONNECTED", description=f"MLflow server connected: {url}", entity_type="mlflow_connection", entity_id=str(conn.id))
    if status == "connected":
        background_tasks.add_task(sync_and_autoscan_models_background, url)
    return _conn_out(conn)


@router.delete("/connect/{conn_id}", status_code=204)
def disconnect_mlflow(conn_id: int, db: Session = Depends(get_db)):
    conn = db.query(MLflowConnection).filter(MLflowConnection.id == conn_id).first()
    if not conn:
        raise HTTPException(404, "Connection not found")
    db.delete(conn)
    db.commit()


# ── MLflow Registry (live) ─────────────────────────────────────────────────────

def _get_active_client(db: Session):
    conn = db.query(MLflowConnection).filter(MLflowConnection.status == "connected").first()
    if not conn:
        raise HTTPException(400, "No active MLflow connection. Connect a server first.")
    from mlflow.tracking import MlflowClient
    return MlflowClient(tracking_uri=conn.url), conn


@router.get("/registry")
def list_registry(db: Session = Depends(get_db)):
    client, conn = _get_active_client(db)
    try:
        models = client.search_registered_models()
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch models from MLflow: {e}")

    result = []
    for m in models:
        latest = []
        for v in (m.latest_versions or []):
            run_metrics = {}
            try:
                run = client.get_run(v.run_id)
                run_metrics = {k: round(float(val), 4) for k, val in run.data.metrics.items()}
            except Exception:
                pass
            latest.append({
                "version":            v.version,
                "stage":              v.current_stage,
                "run_id":             v.run_id,
                "status":             v.status,
                "creation_timestamp": v.creation_timestamp,
                "metrics":            run_metrics,
            })
        result.append({
            "name":            m.name,
            "description":     m.description or "",
            "tags":            dict(m.tags) if m.tags else {},
            "latest_versions": latest,
            "mlflow_url":      conn.url,
        })
    return result


@router.get("/registry/{model_name}/versions")
def list_versions(model_name: str, db: Session = Depends(get_db)):
    client, _ = _get_active_client(db)
    try:
        versions = client.search_model_versions(f"name='{model_name}'")
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch versions: {e}")
    return [
        {
            "version": v.version,
            "stage":   v.current_stage,
            "run_id":  v.run_id,
            "status":  v.status,
            "creation_timestamp": v.creation_timestamp,
        }
        for v in sorted(versions, key=lambda x: int(x.version), reverse=True)
    ]


# ── Scan Config (local) ────────────────────────────────────────────────────────

@router.get("/models")
def list_ml_models(db: Session = Depends(get_db)):
    return [_model_out(m) for m in db.query(MLModel).order_by(MLModel.created_at.desc()).all()]


@router.post("/models", status_code=201)
def configure_ml_model(data: dict, db: Session = Depends(get_db)):
    mlflow_name = data.get("mlflow_model_name") or data.get("name", "Unnamed")
    m = MLModel(
        name=data.get("name") or mlflow_name,
        framework=data.get("framework"),
        task_type=data.get("task_type", "classification"),
        version=data.get("version"),
        description=data.get("description"),
        owner=data.get("owner"),
        integration_id=data.get("integration_id"),
        target_table=data.get("target_table"),
        target_column=data.get("target_column"),
        feature_columns=data.get("feature_columns", []),
        protected_attrs=data.get("protected_attrs", []),
        status="active",
        mlflow_server_url=data.get("mlflow_server_url"),
        mlflow_model_name=mlflow_name,
        mlflow_version=data.get("mlflow_version"),
        mlflow_stage=data.get("mlflow_stage"),
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    log_audit(db, "ML_MODEL_CONFIGURED", description=f"ML model '{m.name}' configured for governance", entity_type="ml_model", entity_id=str(m.id))
    return _model_out(m)


@router.put("/models/{model_id}")
def update_ml_model(model_id: int, data: dict, db: Session = Depends(get_db)):
    m = db.query(MLModel).filter(MLModel.id == model_id).first()
    if not m:
        raise HTTPException(404, "Model not found")
    for field in ["name", "framework", "task_type", "version", "description", "owner",
                  "integration_id", "target_table", "target_column", "feature_columns",
                  "protected_attrs", "status", "mlflow_server_url", "mlflow_model_name",
                  "mlflow_version", "mlflow_stage"]:
        if field in data:
            setattr(m, field, data[field])
    db.commit()
    db.refresh(m)
    return _model_out(m)


@router.delete("/models/{model_id}", status_code=204)
def delete_ml_model(model_id: int, db: Session = Depends(get_db)):
    m = db.query(MLModel).filter(MLModel.id == model_id).first()
    if not m:
        raise HTTPException(404, "Model not found")
    name = m.name
    mlflow_model_name = m.mlflow_model_name
    
    # Try to delete from MLflow registry
    if m.mlflow_server_url and mlflow_model_name:
        try:
            from mlflow.tracking import MlflowClient
            client = MlflowClient(tracking_uri=m.mlflow_server_url)
            client.delete_registered_model(name=mlflow_model_name)
        except Exception as e:
            print(f"Failed to delete model from MLflow registry: {e}")

    db.query(MLGovernanceScan).filter(MLGovernanceScan.model_id == model_id).delete()
    db.delete(m)
    db.commit()
    log_audit(db, "ML_MODEL_REMOVED", description=f"ML model config '{name}' removed", entity_type="ml_model", entity_id=str(model_id))


# ── Scans ──────────────────────────────────────────────────────────────────────

@router.get("/models/{model_id}/scans")
def list_scans(model_id: int, db: Session = Depends(get_db)):
    return [_scan_out(s) for s in
            db.query(MLGovernanceScan).filter(MLGovernanceScan.model_id == model_id)
              .order_by(MLGovernanceScan.started_at.desc()).all()]


@router.get("/scans/{scan_id}")
def get_scan(scan_id: int, db: Session = Depends(get_db)):
    s = db.query(MLGovernanceScan).filter(MLGovernanceScan.id == scan_id).first()
    if not s:
        raise HTTPException(404, "Scan not found")
    return _scan_out(s)


@router.post("/models/{model_id}/scan")
def start_scan(model_id: int, db: Session = Depends(get_db)):
    m = db.query(MLModel).filter(MLModel.id == model_id).first()
    if not m:
        raise HTTPException(404, "Model not found")

    scan = MLGovernanceScan(model_id=model_id, status="running")
    db.add(scan)
    db.commit()
    db.refresh(scan)
    scan_id = scan.id

    async def _stream() -> AsyncGenerator[str, None]:
        def _send(event: str, payload: dict) -> str:
            return f"data: {json.dumps({'event': event, **payload})}\n\n"

        yield _send("started", {"scan_id": scan_id, "model_id": model_id})
        await asyncio.sleep(0.1)

        db2 = SessionLocal()
        try:
            ml_model = db2.query(MLModel).filter(MLModel.id == model_id).first()
            conn = db2.query(MLflowConnection).filter(MLflowConnection.status == "connected").first()
            scan_rec = db2.query(MLGovernanceScan).filter(MLGovernanceScan.id == scan_id).first()

            # ── 1. Load data ───────────────────────────────────────────────
            yield _send("progress", {"step": "load_data", "message": "Loading data..."})
            await asyncio.sleep(0.3)

            df = await asyncio.get_event_loop().run_in_executor(
                None, lambda: _load_data(db2, ml_model)
            )

            if df is None or df.empty:
                scan_rec.status = "failed"
                scan_rec.error_message = "No data available. Set a target table in the model configuration."
                scan_rec.completed_at = datetime.now(timezone.utc)
                db2.commit()
                yield _send("error", {"message": scan_rec.error_message})
                return

            yield _send("progress", {"step": "load_data", "message": f"Loaded {len(df)} rows, {len(df.columns)} columns", "rows": len(df)})
            await asyncio.sleep(0.2)

            feature_cols = ml_model.feature_columns or []
            target_col = ml_model.target_column
            protected = ml_model.protected_attrs or []

            if not feature_cols:
                exclude = set([target_col] + protected) if target_col else set(protected)
                feature_cols = [c for c in df.columns if c not in exclude]

            # ── 2. Load/train model ────────────────────────────────────────
            yield _send("progress", {"step": "train_model", "message": "Loading model from MLflow..." if (conn and ml_model.mlflow_model_name) else "Training proxy model..."})
            await asyncio.sleep(0.2)

            model_card, proxy, X_train, X_test, y_train, y_test, mlflow_run_id = \
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: _load_or_train(df, feature_cols, target_col, ml_model, conn)
                )

            yield _send("progress", {"step": "train_model", "message": f"Model ready. {model_card.get('source', 'proxy')} — {model_card.get('accuracy') or model_card.get('r2_score', '')}"})
            await asyncio.sleep(0.2)

            # ── 3. Bias detection ──────────────────────────────────────────
            yield _send("progress", {"step": "bias", "message": "Running bias analysis with Fairlearn..."})
            await asyncio.sleep(0.2)

            bias_results = await asyncio.get_event_loop().run_in_executor(
                None, lambda: _run_bias(proxy, X_test, y_test, df, protected, feature_cols, ml_model.task_type)
            )

            yield _send("progress", {"step": "bias", "message": "Bias analysis complete", "results": bias_results})
            await asyncio.sleep(0.2)

            # ── 4. Drift detection ─────────────────────────────────────────
            yield _send("progress", {"step": "drift", "message": "Running drift detection with KS/Chi2 tests..."})
            await asyncio.sleep(0.2)

            drift_results = await asyncio.get_event_loop().run_in_executor(
                None, lambda: _run_drift(df, feature_cols)
            )

            yield _send("progress", {"step": "drift", "message": "Drift analysis complete", "results": drift_results})
            await asyncio.sleep(0.2)

            # ── 5. Explainability (SHAP) ───────────────────────────────────
            yield _send("progress", {"step": "shap", "message": "Computing SHAP feature importance..."})
            await asyncio.sleep(0.2)

            shap_results = await asyncio.get_event_loop().run_in_executor(
                None, lambda: _run_shap(proxy, X_test, feature_cols)
            )

            yield _send("progress", {"step": "shap", "message": "SHAP analysis complete", "results": shap_results})
            await asyncio.sleep(0.2)

            # ── 6. Save results ────────────────────────────────────────────
            scan_rec.bias_results = bias_results
            scan_rec.drift_results = drift_results
            scan_rec.shap_results = shap_results
            scan_rec.model_card = model_card
            scan_rec.mlflow_run_id = mlflow_run_id
            scan_rec.status = "completed"
            scan_rec.completed_at = datetime.now(timezone.utc)
            db2.commit()

            log_audit(db2, "ML_GOVERNANCE_SCAN", description=f"Governance scan completed for model '{ml_model.name}'", entity_type="ml_model", entity_id=str(model_id))

            yield _send("completed", {"scan_id": scan_id, "model_card": model_card, "bias": bias_results, "drift": drift_results, "shap": shap_results})

        except Exception as exc:
            tb = traceback.format_exc()
            try:
                scan_rec2 = db2.query(MLGovernanceScan).filter(MLGovernanceScan.id == scan_id).first()
                if scan_rec2:
                    scan_rec2.status = "failed"
                    scan_rec2.error_message = str(exc)
                    scan_rec2.completed_at = datetime.now(timezone.utc)
                    db2.commit()
            except Exception:
                pass
            yield _send("error", {"message": str(exc), "detail": tb[:500]})
        finally:
            db2.close()

    return StreamingResponse(_stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


# ── Summary ────────────────────────────────────────────────────────────────────

@router.get("/summary")
def ml_summary(db: Session = Depends(get_db)):
    models = db.query(MLModel).all()
    scans = db.query(MLGovernanceScan).filter(MLGovernanceScan.status == "completed").all()
    conn = db.query(MLflowConnection).filter(MLflowConnection.status == "connected").first()

    high_bias = sum(
        1 for s in scans
        if s.bias_results and s.bias_results.get("overall_verdict") == "biased"
    )
    high_drift = sum(
        1 for s in scans
        if s.drift_results and s.drift_results.get("drifted_features", 0) > 0
    )

    return {
        "mlflow_connected":  conn is not None,
        "mlflow_url":        conn.url if conn else None,
        "total_models":      len(models),
        "configured_models": len(models),
        "total_scans":       len(scans),
        "high_bias_count":   high_bias,
        "high_drift_count":  high_drift,
    }


# ── Analysis Engine ────────────────────────────────────────────────────────────

def _load_data(db: Session, ml_model: MLModel) -> pd.DataFrame | None:
    from src.core.database import engine as pg_engine

    table = (ml_model.target_table or "").replace(";", "").strip()
    if not table:
        return None

    if ml_model.integration_id:
        try:
            from src.core.security import decrypt_password
            from sqlalchemy import create_engine as _ce
            intg = db.query(Integration).filter(Integration.id == ml_model.integration_id).first()
            if intg:
                pwd = decrypt_password(intg.password_encrypted)
                url = (f"mysql+pymysql://{intg.username}:{pwd}"
                       f"@{intg.host}:{intg.port}/{intg.database_name}")
                eng = _ce(url, connect_args={"connect_timeout": 10})
                df = pd.read_sql(f"SELECT * FROM `{table}` LIMIT 5000", eng)
                if not df.empty:
                    return df
        except Exception:
            pass

    try:
        from sqlalchemy import create_engine as _ce
        mariadb_url = "mysql+pymysql://root:root123@127.0.0.1:3307/governance_db"
        mariadb_engine = _ce(mariadb_url)
        df = pd.read_sql(f"SELECT * FROM `{table}` LIMIT 5000", mariadb_engine)
        return df if not df.empty else None
    except Exception:
        return None


def _load_or_train(df: pd.DataFrame, feature_cols: list, target_col: str | None,
                   ml_model: MLModel, conn: MLflowConnection | None):
    """
    Try to download the real model from MLflow first.
    Fall back to training a proxy RandomForest if download fails.
    """
    if conn and ml_model.mlflow_model_name and ml_model.mlflow_version:
        try:
            return _download_mlflow_model(df, feature_cols, target_col, ml_model, conn)
        except Exception:
            pass  # fall through to proxy
    return _train_proxy(df, feature_cols, target_col, ml_model)


def _download_mlflow_model(df: pd.DataFrame, feature_cols: list, target_col: str | None,
                            ml_model: MLModel, conn: MLflowConnection):
    """Download model artifact from MLflow and use it directly."""
    import tempfile, os
    import mlflow.pyfunc
    from mlflow.tracking import MlflowClient
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import LabelEncoder

    from typing import Any
    tracking_uri = str(getattr(conn, "url"))
    client = MlflowClient(tracking_uri=tracking_uri)
    model_name = str(getattr(ml_model, "mlflow_model_name"))
    model_version = str(getattr(ml_model, "mlflow_version"))
    mv = client.get_model_version(model_name, model_version)

    available = [c for c in feature_cols if c in df.columns]
    if not available:
        available = [c for c in df.columns if c != target_col][:10]

    X = df[available].copy()
    for col in X.select_dtypes(include=["object", "category"]).columns:
        le = LabelEncoder()
        X[col] = le.fit_transform(X[col].astype(str))
    X = X.fillna(X.median(numeric_only=True)).fillna(0)
    X = X.astype(float)

    task_type = ml_model.task_type or "classification"
    if target_col and target_col in df.columns:
        y_raw = df[target_col]
        if task_type == "classification" or y_raw.dtype == object:
            le = LabelEncoder()
            y = le.fit_transform(y_raw.astype(str))
        else:
            y = y_raw.values
    else:
        from sklearn.cluster import KMeans
        km = KMeans(n_clusters=2, random_state=42, n_init=10)
        y = km.fit_predict(X)

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.25, random_state=42)

    run_id = str(mv.run_id)
    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = client.download_artifacts(run_id, "model", tmpdir)
        pyfunc_model = mlflow.pyfunc.load_model(local_path)

    # Wrap pyfunc model so SHAP TreeExplainer works (needs sklearn-like interface)
    # Try unwrapping the underlying sklearn model
    try:
        proxy = pyfunc_model._model_impl.python_model if hasattr(pyfunc_model, '_model_impl') else pyfunc_model
        # For sklearn flavour, get the raw model
        if hasattr(pyfunc_model, '_model_impl') and hasattr(pyfunc_model._model_impl, 'sklearn_model'):
            proxy = pyfunc_model._model_impl.sklearn_model
        else:
            import mlflow.sklearn
            proxy = mlflow.sklearn.load_model(f"runs:/{run_id}/model")
    except Exception:
        proxy = pyfunc_model

    # Wrap predict and predict_proba to ensure they always receive a DataFrame with column names
    proxy_any: Any = proxy
    if proxy_any is not None:
        if hasattr(proxy_any, "predict"):
            original_predict = proxy_any.predict
            def wrapped_predict(data, *args, **kwargs):
                if not isinstance(data, pd.DataFrame):
                    data = pd.DataFrame(data, columns=available)
                else:
                    # If columns are not correct or are integers, recreate DataFrame to enforce column schema
                    data = pd.DataFrame(data.values, columns=available)
                return original_predict(data, *args, **kwargs)
            proxy_any.predict = wrapped_predict

        if hasattr(proxy_any, "predict_proba"):
            original_predict_proba = proxy_any.predict_proba
            def wrapped_predict_proba(data, *args, **kwargs):
                if not isinstance(data, pd.DataFrame):
                    data = pd.DataFrame(data, columns=available)
                else:
                    data = pd.DataFrame(data.values, columns=available)
                return original_predict_proba(data, *args, **kwargs)
            proxy_any.predict_proba = wrapped_predict_proba

    run_metrics = {}
    try:
        run = client.get_run(run_id)
        run_metrics = {k: round(float(v), 4) for k, v in run.data.metrics.items()}
    except Exception:
        pass

    model_card = {
        "model_name":       ml_model.name,
        "mlflow_model":     ml_model.mlflow_model_name,
        "mlflow_version":   ml_model.mlflow_version,
        "mlflow_stage":     ml_model.mlflow_stage or mv.current_stage,
        "source":           "mlflow_registry",
        "n_samples":        len(df),
        "n_features":       len(available),
        "feature_columns":  available,
        "target_column":    target_col,
        "run_metrics":      run_metrics,
        **run_metrics,
    }

    # Validate that the downloaded model can actually predict on our X_test data
    proxy_any: Any = proxy
    if proxy_any is None:
        raise ValueError("Downloaded model is None")
    try:
        proxy_any.predict(X_test[:5])
    except Exception as e:
        raise ValueError(f"Downloaded model fails when applied to the dataset: {e}")

    return model_card, proxy_any, X_train, X_test, y_train, y_test, run_id


def _train_proxy(df: pd.DataFrame, feature_cols: list, target_col: str | None,
                 ml_model: MLModel):
    """Train a RandomForest proxy model and track it with MLflow."""
    import mlflow, os
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import LabelEncoder
    from sklearn.metrics import accuracy_score, r2_score

    available = [c for c in feature_cols if c in df.columns]
    if not available:
        available = [c for c in df.columns if c != target_col][:10]

    X = df[available].copy()
    for col in X.select_dtypes(include=["object", "category"]).columns:
        le = LabelEncoder()
        X[col] = le.fit_transform(X[col].astype(str))
    X = X.fillna(X.median(numeric_only=True)).fillna(0)
    X = X.astype(float)

    task_type = ml_model.task_type or "classification"

    if target_col and target_col in df.columns:
        y_raw = df[target_col]
        if task_type == "classification" or y_raw.dtype == object:
            le = LabelEncoder()
            y = le.fit_transform(y_raw.astype(str))
            is_clf = True
        else:
            y = y_raw.values
            is_clf = False
    else:
        from sklearn.cluster import KMeans
        km = KMeans(n_clusters=2, random_state=42, n_init=10)
        y = km.fit_predict(X)
        is_clf = True

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.25, random_state=42)

    tracking_uri = None
    try:
        from src.core.database import SessionLocal
        from src.domain.entities import MLflowConnection
        db_s = SessionLocal()
        conn = db_s.query(MLflowConnection).filter(MLflowConnection.status == "connected").first()
        if conn:
            tracking_uri = conn.url
        db_s.close()
    except Exception:
        pass
    if not tracking_uri:
        tracking_uri = MLFLOW_TRACKING_URI

    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment("dataguard_ml_governance")

    with mlflow.start_run(run_name=f"governance_{ml_model.name}") as run:
        if is_clf:
            proxy = RandomForestClassifier(n_estimators=50, max_depth=6, random_state=42)
            proxy.fit(X_train, y_train)
            preds = proxy.predict(X_test)
            acc = float(accuracy_score(y_test, preds))
            mlflow.log_metric("accuracy", acc)
            metric_key, metric_val = "accuracy", round(acc, 4)
        else:
            proxy = RandomForestRegressor(n_estimators=50, max_depth=6, random_state=42)
            proxy.fit(X_train, y_train)
            preds = proxy.predict(X_test)
            r2 = float(r2_score(y_test, preds))
            mlflow.log_metric("r2_score", r2)
            metric_key, metric_val = "r2_score", round(r2, 4)

        mlflow.log_param("model_name", ml_model.name)
        mlflow.log_param("n_features", len(available))
        mlflow.log_param("n_samples", len(df))
        import mlflow.sklearn
        mlflow.sklearn.log_model(proxy, artifact_path="model", registered_model_name=None)
        run_id = run.info.run_id

    model_card = {
        "model_name":      ml_model.name,
        "source":          "proxy_model",
        "framework":       ml_model.framework or "sklearn",
        "task_type":       task_type,
        "n_samples":       len(df),
        "n_features":      len(available),
        "feature_columns": available,
        "target_column":   target_col,
        metric_key:        metric_val,
        "mlflow_run_id":   run_id,
    }

    return model_card, proxy, X_train, X_test, y_train, y_test, run_id


def _run_bias(proxy, X_test, y_test, df: pd.DataFrame, protected_attrs: list,
              feature_cols: list, task_type: str) -> dict:
    try:
        from fairlearn.metrics import (
            demographic_parity_difference,
            equalized_odds_difference,
            MetricFrame,
        )
        from sklearn.metrics import accuracy_score

        results: dict = {"attributes": {}, "overall_verdict": "fair"}

        if not protected_attrs:
            return {"message": "No protected attributes configured", "overall_verdict": "unknown", "attributes": {}}

        # Handle both sklearn models and mlflow pyfunc wrappers
        try:
            preds = proxy.predict(X_test)
        except Exception:
            preds = proxy.predict(pd.DataFrame(X_test))

        any_biased = False

        for attr in protected_attrs:
            if attr not in df.columns:
                continue

            sensitive = df[attr].iloc[X_test.index] if hasattr(X_test, 'index') else df[attr].iloc[:len(X_test)]
            sensitive = sensitive.reset_index(drop=True)
            
            # Map labels to binary 0/1 representation to satisfy Fairlearn
            raw_y_true = np.array(y_test)
            raw_y_pred = np.array(preds)
            
            if raw_y_true.dtype.kind in 'UOS':  # String/object type
                y_true = np.array([1 if str(val).strip() in [">50K", "1", "1.0", "y", "yes", "true", "True"] else 0 for val in raw_y_true])
            else:
                y_true = np.array([1 if val else 0 for val in raw_y_true])
                
            if raw_y_pred.dtype.kind in 'UOS':  # String/object type
                y_pred = np.array([1 if str(val).strip() in [">50K", "1", "1.0", "y", "yes", "true", "True"] else 0 for val in raw_y_pred])
            else:
                y_pred = np.array([1 if val else 0 for val in raw_y_pred])

            try:
                dpd = demographic_parity_difference(y_true, y_pred, sensitive_features=sensitive)
                eod = equalized_odds_difference(y_true, y_pred, sensitive_features=sensitive)

                mf = MetricFrame(
                    metrics=accuracy_score,
                    y_true=y_true,
                    y_pred=y_pred,
                    sensitive_features=sensitive,
                )
                per_group = {str(k): round(float(v), 4) for k, v in mf.by_group.items()}
                overall_val: Any = mf.overall
                overall_acc = round(float(overall_val), 4)

                biased = abs(dpd) > 0.1 or abs(eod) > 0.1
                if biased:
                    any_biased = True

                results["attributes"][attr] = {
                    "demographic_parity_difference": round(dpd, 4),
                    "equalized_odds_difference":     round(eod, 4),
                    "accuracy_by_group":             per_group,
                    "overall_accuracy":              overall_acc,
                    "verdict":                       "biased" if biased else "fair",
                    "groups":                        list(per_group.keys()),
                }
            except Exception as e:
                results["attributes"][attr] = {"error": str(e), "verdict": "unknown"}

        results["overall_verdict"] = "biased" if any_biased else "fair"
        return results

    except ImportError:
        return {"error": "fairlearn not installed", "overall_verdict": "unknown", "attributes": {}}
    except Exception as e:
        return {"error": str(e), "overall_verdict": "unknown", "attributes": {}}


def _run_drift(df: pd.DataFrame, feature_cols: list) -> dict:
    from scipy import stats

    available = [c for c in feature_cols if c in df.columns]
    if not available:
        available = list(df.columns[:10])

    n = len(df)
    if n < 20:
        return {"message": "Not enough data for drift detection (need ≥20 rows)", "drifted_features": 0, "features": {}}

    mid = n // 2
    ref = df.iloc[:mid]
    cur = df.iloc[mid:]

    feature_results: dict = {}
    drifted = 0
    p_threshold = 0.05

    for col in available:
        try:
            if col not in df.columns:
                continue
            col_ref = ref[col].dropna()
            col_cur = cur[col].dropna()
            if len(col_ref) < 5 or len(col_cur) < 5:
                continue

            if df[col].dtype in [np.float64, np.float32, np.int64, np.int32, float, int]:
                stat, p_val = stats.ks_2samp(col_ref.values, col_cur.values)
                test = "ks"
            else:
                all_cats = list(set(col_ref.astype(str)) | set(col_cur.astype(str)))
                ref_counts = col_ref.astype(str).value_counts()
                cur_counts = col_cur.astype(str).value_counts()
                ref_arr = np.array([ref_counts.get(c, 0) for c in all_cats])
                cur_arr = np.array([cur_counts.get(c, 0) for c in all_cats])
                if ref_arr.sum() == 0 or cur_arr.sum() == 0:
                    continue
                stat, p_val, *_ = stats.chi2_contingency(np.array([ref_arr, cur_arr]))
                test = "chi2"

            drifted_flag = bool(p_val < p_threshold)
            if drifted_flag:
                drifted += 1

            feature_results[col] = {
                "test":      test,
                "statistic": round(float(stat), 4),
                "p_value":   round(float(p_val), 4),
                "drifted":   drifted_flag,
                "severity":  "high" if p_val < 0.01 else "medium" if p_val < 0.05 else "low",
            }
        except Exception as e:
            feature_results[col] = {"error": str(e), "drifted": False}

    return {
        "total_features":  len(feature_results),
        "drifted_features": drifted,
        "drift_rate":      round(drifted / max(len(feature_results), 1), 3),
        "p_threshold":     p_threshold,
        "verdict":         "drift_detected" if drifted > 0 else "stable",
        "features":        feature_results,
    }


def _run_shap(proxy, X_test, feature_cols: list) -> dict:
    try:
        import shap

        available = [c for c in feature_cols if c in X_test.columns] if hasattr(X_test, 'columns') else feature_cols
        X_sample = X_test[:min(200, len(X_test))]

        try:
            explainer = shap.TreeExplainer(proxy)
            shap_values = explainer.shap_values(X_sample)
        except Exception:
            # Fall back to KernelExplainer for non-tree models
            background = shap.sample(X_sample, min(50, len(X_sample)))
            explainer = shap.KernelExplainer(proxy.predict, background)
            shap_values = explainer.shap_values(X_sample[:50])

        if hasattr(shap_values, "values"):
            shap_values = shap_values.values

        if isinstance(shap_values, list):
            sv = np.abs(shap_values[1] if len(shap_values) > 1 else shap_values[0])
        else:
            sv = np.abs(shap_values)

        # Handle 3D arrays e.g. (n_samples, n_features, n_classes) or (n_samples, n_classes, n_features)
        if sv.ndim == 3:
            if sv.shape[2] == len(available):
                # Shape is (n_samples, n_classes, n_features)
                sv = sv[:, 1, :] if sv.shape[1] > 1 else sv[:, 0, :]
            else:
                # Shape is (n_samples, n_features, n_classes)
                sv = sv[:, :, 1] if sv.shape[2] > 1 else sv[:, :, 0]

        mean_abs = sv.mean(axis=0)
        
        # Flatten mean_abs if it still has multiple dimensions
        if hasattr(mean_abs, "ndim") and mean_abs.ndim > 1:
            mean_abs = mean_abs.mean(axis=tuple(range(1, mean_abs.ndim)))

        cols = list(X_sample.columns) if hasattr(X_sample, 'columns') else available

        importance = dict(sorted(
            {col: round(float(val), 6) for col, val in zip(cols, mean_abs)}.items(),
            key=lambda x: x[1], reverse=True
        ))
        top_features = list(importance.items())[:10]

        return {
            "method":             "TreeExplainer",
            "n_samples":          len(X_sample),
            "feature_importance": importance,
            "top_features":       [{"feature": f, "importance": v} for f, v in top_features],
            "most_important":     top_features[0][0] if top_features else None,
        }
    except Exception as e:
        return {"error": str(e), "feature_importance": {}, "top_features": []}
