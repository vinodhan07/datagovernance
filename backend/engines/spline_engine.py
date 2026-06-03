"""
spline_engine.py
Constructs and pushes data lineage execution plans and events to the Spline Producer API.
Sanitized URIs to prevent btoa errors in Spline UI.
"""
import uuid
import time
import requests
import os
import json

# Default Spline Producer URL
PRODUCER_URL = os.getenv("SPLINE_PRODUCER_URL", "http://localhost:8080/producer")

def push_table_spline_lineage(
    integration_name: str, 
    table_name: str, 
    columns: list[str], 
    source_uri: str, 
    target_uri: str, 
    duration_seconds: float
) -> str | None:
    """
    Pushes granular column-wise lineage for a single table to Spline.
    """
    try:
        plan_id = str(uuid.uuid4())
        
        # 1. Attributes (Columns)
        all_attributes = []
        source_attr_ids = []
        target_attr_ids = []
        attribute_lineage = {} # targetId -> [sourceId]
        
        for col in columns:
            attr_id = str(uuid.uuid4())
            all_attributes.append({
                "id": attr_id,
                "name": f"{table_name}.{col}"
            })
            source_attr_ids.append(attr_id)
            
            target_id = str(uuid.uuid4())
            all_attributes.append({
                "id": target_id,
                "name": col
            })
            target_attr_ids.append(target_id)
            
            attribute_lineage[target_id] = [attr_id]
            
        # 2. Operations (Workflow)
        source_op_id = 0
        read_op = {
            "id": source_op_id,
            "name": f"Source Table: {table_name}",
            "inputSources": [source_uri],
            "output": source_attr_ids
        }
        
        data_op_id = 1
        data_op = {
            "id": data_op_id,
            "name": "Deduplication & Clean",
            "childIds": [source_op_id],
            "output": target_attr_ids
        }
        
        write_op_id = 2
        write_op = {
            "id": write_op_id,
            "name": "Target Store",
            "childIds": [data_op_id],
            "outputSource": target_uri,
            "append": False,
            "attributeLineage": attribute_lineage
        }
        
        # 3. Execution Plan
        plan = {
            "id": plan_id,
            "name": f"DataGuard ETL: {integration_name} - {table_name}",
            "operations": {
                "write": write_op,
                "reads": [read_op],
                "other": [data_op]
            },
            "attributes": all_attributes,
            "systemInfo": {"name": "DataGuard", "version": "1.0.0"},
            "agentInfo": {"name": "DataGuard-Agent", "version": "1.0.0"}
        }
        
        # 4. Push Plan
        print(f"STATUS: Pushing execution plan {plan_id} for table {table_name} to {PRODUCER_URL}...")
        resp = requests.post(f"{PRODUCER_URL}/execution-plans", json=plan, timeout=30)
        if resp.status_code not in (200, 201):
            print(f"ERROR: Spline Plan Push failed ({resp.status_code}): {resp.text}")
            return None
            
        # 5. Push Event
        event = {
            "planId": plan_id,
            "timestamp": int(time.time() * 1000),
            "durationNs": int(duration_seconds * 1_000_000_000),
            "error": None,
            "extra": {"app": "DataGuard"}
        }
        resp_event = requests.post(f"{PRODUCER_URL}/execution-events", json=[event], timeout=30)
        if resp_event.status_code not in (200, 201):
            print(f"ERROR: Spline Event Push failed ({resp_event.status_code}): {resp_event.text}")
            return None
            
        print(f"SUCCESS: Lineage pushed to Spline for table {table_name} (ID: {plan_id})")
        return plan_id
        
    except Exception as exc:
        print(f"ERROR: Spline push exception: {exc}")
        return None
