import json
import time
import uuid
import os
import re
import base64
import requests
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, create_engine, text # type: ignore
from database import get_db, is_db_available
from models import PipelineRun, Integration
from routers.extraction import extract_schema
from engines.spline_engine import push_table_spline_lineage
from integrations_service import get_connection_config, build_connection_url
from datetime import datetime, timezone
from typing import Optional

router = APIRouter()

def emit(level: str, msg: str, data: Optional[dict] = None):
    ts = datetime.now().strftime("%H:%M:%S")
    return f"data: {json.dumps({'level': level, 'msg': msg, 'ts': ts, 'data': data or {}})}\n\n"

def clean_email(email):
    if pd.isna(email) or email == "(NULL)":
        return None
    email = str(email).replace("#", "@")
    if "@" not in email:
        if "gmail.com" in email:
            email = email.replace("gmail.com", "@gmail.com")
        elif "yahoo.com" in email:
            email = email.replace("yahoo.com", "@yahoo.com")
    return email

def process_dataframe(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    # 1. Deduplicate
    id_col = None
    if table_name == "orders":
        id_col = "order_id"
    elif table_name == "transactions":
        id_col = "transaction_id"
    else:
        potential_ids = [c for c in df.columns if "id" in c.lower()]
        if potential_ids:
            id_col = potential_ids[0]
            
    if id_col and id_col in df.columns:
        df = df.drop_duplicates(subset=[id_col], keep='first')
        
    # 2. Clean Email
    if "email" in df.columns:
        df['email'] = df['email'].apply(clean_email)
        
    # 3. Clean Amount
    if "amount" in df.columns:
        df['amount'] = pd.to_numeric(df['amount'], errors='coerce').abs()
        
    # 4. Clean Dates
    date_cols = [c for c in df.columns if 'date' in c.lower() or 'time' in c.lower()]
    for col in date_cols:
        df[col] = df[col].replace("(NULL)", pd.NA)
        df[col] = pd.to_datetime(df[col], errors='coerce')
        
    return df

def parse_postgres_url(url: str | None) -> dict:
    if not url:
        return {"host": "localhost", "port": 5432, "database": "dataguard"}
    try:
        temp = url.split("://")[1]
        if "?" in temp:
            temp = temp.split("?")[0]
        creds_part, conn_part = temp.split("@")
        host_port, database = conn_part.split("/")
        if ":" in host_port:
            host, port = host_port.split(":")
        else:
            host = host_port
            port = 5432
        return {"host": host, "port": int(port), "database": database}
    except Exception:
        return {"host": "localhost", "port": 5432, "database": "dataguard"}

def get_postgres_company_data_url() -> str:
    base_url = os.getenv("POSTGRES_URL", "postgresql://postgres:postgres@localhost:5432/dataguard")
    if "?" in base_url:
        parts = base_url.split("?")
        main_part = parts[0]
        params = "?" + parts[1]
    else:
        main_part = base_url
        params = ""
        
    r_index = main_part.rfind("/")
    if r_index != -1:
        return main_part[:r_index+1] + "company_data" + params
    return "postgresql://postgres:postgres@localhost:5432/company_data"

def create_company_data_db_if_not_exists():
    base_url = os.getenv("POSTGRES_URL", "postgresql://postgres:postgres@localhost:5432/dataguard")
    if "?" in base_url:
        parts = base_url.split("?")
        main_part = parts[0]
        params = "?" + parts[1]
    else:
        main_part = base_url
        params = ""
        
    r_index = main_part.rfind("/")
    postgres_db_url = main_part[:r_index+1] + "postgres" + params
    
    engine = create_engine(postgres_db_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = 'company_data'"))
        if not result.fetchone():
            conn.execute(text("CREATE DATABASE company_data"))

def fetch_file_from_github(owner: str, repo: str, filepath: str, branch: str = "main", token: str | None = None) -> str:
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{filepath}"
    headers = {}
    if token:
        headers["Authorization"] = f"token {token}"
    if branch:
        url += f"?ref={branch}"
        
    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code != 200:
        raise Exception(f"Failed to fetch file from GitHub: {resp.text}")
        
    data = resp.json()
    content_b64 = data.get("content", "")
    content = base64.b64decode(content_b64).decode("utf-8")
    return content

def parse_etl_script(code: str) -> dict:
    sources = {}
    targets = {}
    transformations = []
    
    if "drop_duplicates" in code:
        transformations.append("Deduplication")
    if "clean_email" in code or "email" in code:
        transformations.append("Email cleaning & standardization")
    if "to_numeric" in code or "amount" in code:
        transformations.append("Numeric amount formatting")
    if "to_datetime" in code or "date" in code:
        transformations.append("Datetime standardisation")
        
    if not transformations:
        transformations.append("Standard ETL scan & validation")
        
    csv_matches = re.findall(r"read_csv\(['\"]([^'\"]+)['\"]", code)
    for match in csv_matches:
        name = match.replace("raw_", "").replace(".csv", "")
        if name == "orders":
            sources["orders"] = ["order_id", "customer_name", "email", "amount", "order_date", "status"]
        elif name == "transactions":
            sources["transactions"] = ["transaction_id", "order_id", "payment_method", "transaction_date", "amount", "status"]
        else:
            sources[name] = ["id", "created_at"]
            
    sql_matches = re.findall(r"read_sql\(['\"]SELECT \* FROM (\w+)['\"]", code)
    for match in sql_matches:
        if match == "orders":
            sources["orders"] = ["order_id", "customer_name", "email", "amount", "order_date", "status"]
        elif match == "transactions":
            sources["transactions"] = ["transaction_id", "order_id", "payment_method", "transaction_date", "amount", "status"]
        else:
            sources[match] = ["id", "created_at"]
            
    to_sql_matches = re.findall(r"to_sql\(['\"](\w+)['\"]", code)
    for match in to_sql_matches:
        if match in sources:
            targets[match] = sources[match]
        else:
            targets[match] = ["id", "created_at"]
            
    if not sources:
        sources["orders"] = ["order_id", "customer_name", "email", "amount", "order_date", "status"]
        sources["transactions"] = ["transaction_id", "order_id", "payment_method", "transaction_date", "amount", "status"]
    if not targets:
        targets["orders"] = sources["orders"]
        targets["transactions"] = sources["transactions"]
        
    return {
        "sources": sources,
        "targets": targets,
        "transformations": transformations
    }

@router.get("/{integration_id}/run")
async def run_pipeline(integration_id: str, db: Session = Depends(get_db)): # type: ignore
    """
    Triggers a pipeline run and streams status updates via SSE.
    """
    return StreamingResponse(
        _pipeline_sse(integration_id, db),
        media_type="text/event-stream"
    )

@router.get("/{integration_id}/fetch")
async def fetch_run(integration_id: str, db: Session = Depends(get_db)): # type: ignore
    """
    Fetches the latest status and results for an integration's pipeline run.
    """
    run = db.query(PipelineRun).filter(PipelineRun.integration_id == integration_id).order_by(PipelineRun.started_at.desc()).first()
    if not run:
        raise HTTPException(404, "No pipeline runs found for this integration")
    return run

@router.get("/{integration_id}/latest")
async def get_latest_run(integration_id: str, db: Session = Depends(get_db)): # type: ignore
    return await fetch_run(integration_id, db)

@router.get("/{integration_id}/history")
async def get_history(integration_id: str, db: Session = Depends(get_db)): # type: ignore
    runs = db.query(PipelineRun).filter(PipelineRun.integration_id == integration_id).order_by(PipelineRun.started_at.desc()).limit(20).all()
    return runs

async def _pipeline_sse(integration_id: str, db: Session): # type: ignore
    run_id = None
    try:
        # 1. Initialization
        yield emit("INFO", "Initializing pipeline...")
        
        # Fetch integration details
        integration = db.query(Integration).filter(Integration.id == integration_id).first()
        integration_name = integration.name if integration else "Unknown"
        
        creds = get_connection_config(db, integration_id)
        if not creds:
            yield emit("ERROR", "Integration not found")
            return

        # Create run record
        run_id = str(uuid.uuid4())
        new_run = PipelineRun(
            id=run_id,
            integration_id=integration_id,
            integration_name=integration_name,
            status="running" # type: ignore
        )
        db.add(new_run)
        db.commit()

        # Handle GitHub pipeline
        if integration and integration.provider == "GitHub":
            yield emit("INFO", "Fetching ETL script file from GitHub...")
            owner = str(creds.get("owner", ""))
            repo = str(creds.get("repo", ""))
            filepath = str(creds.get("filepath", ""))
            branch = str(creds.get("branch", "main"))
            token = creds.get("token")
            
            try:
                code = fetch_file_from_github(owner, repo, filepath, branch, token)
                yield emit("OK", f"Successfully fetched '{filepath}' from GitHub.")
            except Exception as exc:
                raise Exception(f"Failed to fetch ETL script from GitHub: {exc}")

            yield emit("INFO", "Parsing ETL script to discover lineage flow...")
            parsed = parse_etl_script(code)
            yield emit("OK", f"Found {len(parsed['sources'])} sources, {len(parsed['transformations'])} operations, and {len(parsed['targets'])} targets.")

            plan_ids = []
            pg_creds = parse_postgres_url(os.getenv("POSTGRES_URL"))
            
            for table, cols in parsed["targets"].items():
                yield emit("INFO", f"Mapping lineage for table '{table}'...")
                
                # URIs for Spline lineage
                source_uri = f"github://{owner}/{repo}/{filepath}/{table}"
                target_uri = f"postgresql://{pg_creds['host']}:{pg_creds['port']}/company_data/{table}"
                
                start_time = time.time()
                plan_id = push_table_spline_lineage(
                    integration_name=f"GitHub ETL: {repo}",
                    table_name=table,
                    columns=cols,
                    source_uri=source_uri,
                    target_uri=target_uri,
                    duration_seconds=0.5
                )
                if plan_id:
                    plan_ids.append(plan_id)
                    yield emit("OK", f"Lineage for '{table}' pushed (ID: {plan_id})")
                else:
                    yield emit("WARNING", f"Lineage push failed for table '{table}'")

            # Finalization
            new_run.status = "completed" # type: ignore
            new_run.completed_at = datetime.now(timezone.utc) # type: ignore
            new_run.tables_scanned = list(parsed["targets"].keys()) # type: ignore
            new_run.row_counts = {t: 0 for t in parsed["targets"].keys()} # type: ignore
            if plan_ids:
                new_run.spline_plan_id = plan_ids[-1] # type: ignore
                
            db.commit()
            yield emit("DONE", "GitHub ETL pipeline analysis completed successfully")
            return

        # 2. Schema Discovery (MariaDB Database Pipeline)
        yield emit("INFO", "Discovering source schema...")
        schema = extract_schema(creds)
        tables = list(schema.keys())
        yield emit("OK", f"Found {len(tables)} tables: {', '.join(tables)}")

        # 3. Create target database if it doesn't exist
        yield emit("INFO", "Creating / verifying PostgreSQL database 'company_data'...")
        create_company_data_db_if_not_exists()

        row_counts = {}
        plan_ids = []
        source_conn_url = build_connection_url(creds)
        source_engine = create_engine(source_conn_url)
        target_conn_url = get_postgres_company_data_url()
        target_engine = create_engine(target_conn_url)
        
        pg_creds = parse_postgres_url(os.getenv("POSTGRES_URL"))
        source_host = creds.get("host", "localhost")
        source_port = creds.get("port", 3306)
        source_db = creds.get("database", "governance_db")

        # 4. Extract, Process, Load loop
        for table in tables:
            yield emit("INFO", f"Extracting raw data from table '{table}' in MariaDB...")
            start_time = time.time()
            
            # Read
            df = pd.read_sql(f"SELECT * FROM `{table}`", con=source_engine)
            yield emit("INFO", f"Extracted {len(df)} rows. Processing/cleaning data...")
            
            # Clean
            df = process_dataframe(df, table)
            
            # Write
            yield emit("INFO", f"Writing processed data to PostgreSQL 'company_data.{table}'...")
            df.to_sql(table, con=target_engine, if_exists='replace', index=False)
            row_counts[table] = len(df)
            
            duration = time.time() - start_time
            yield emit("OK", f"Table '{table}' processed and loaded successfully.")
            
            # 5. Push Lineage to Spline for this table
            yield emit("INFO", f"Mapping and pushing lineage for '{table}' to Spline...")
            source_uri = f"mysql://{source_host}:{source_port}/{source_db}/{table}"
            target_uri = f"postgresql://{pg_creds['host']}:{pg_creds['port']}/company_data/{table}"
            
            plan_id = push_table_spline_lineage(
                integration_name=str(integration_name),
                table_name=table,
                columns=df.columns.tolist(),
                source_uri=source_uri,
                target_uri=target_uri,
                duration_seconds=duration
            )
            if plan_id:
                plan_ids.append(plan_id)
                yield emit("OK", f"Lineage for '{table}' pushed (ID: {plan_id})")
            else:
                yield emit("WARNING", f"Lineage push failed for table '{table}'")

        # 6. Finalization
        new_run.status = "completed" # type: ignore
        new_run.completed_at = datetime.now(timezone.utc) # type: ignore
        new_run.tables_scanned = tables # type: ignore
        new_run.row_counts = row_counts # type: ignore
        if plan_ids:
            new_run.spline_plan_id = plan_ids[-1] # type: ignore
            
        db.commit()
        
        yield emit("DONE", "Pipeline run completed successfully")

    except Exception as e:
        error_msg = str(e)
        try:
            db.rollback()
            if run_id:
                db.query(PipelineRun).filter(PipelineRun.id == run_id).update({
                    "status": "failed",
                    "error_message": error_msg,
                    "completed_at": datetime.now(timezone.utc)
                })
                db.commit()
        except Exception as db_exc:
            print(f"Failed to update PipelineRun to failed state: {db_exc}")
            
        yield emit("ERROR", f"Pipeline failed: {error_msg}")
