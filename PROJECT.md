# DataGuard — My Project Notes

## What this project does

ETL pipeline from MariaDB → PySpark → PostgreSQL with automatic
column-level lineage captured by Spline and displayed in a UI.

---

## File Structure

```
DATA GOVERENCE/
│
├── docker-compose.yml        ← Start ALL services (Postgres, MariaDB, Spline stack)
├── nginx-spline.conf         ← Nginx routes /consumer and /producer to Spline REST server
├── etl_pipeline.py           ← Reference ETL script (upload this to GitHub as etl.py)
│
├── backend/                  ← FastAPI Python app
│   ├── main.py               ← App entry point — registers 4 routers
│   ├── database.py           ← SQLAlchemy session for PostgreSQL (dataguard DB)
│   ├── models.py             ← 9 DB tables (Integration, PipelineRun, Lineage*)
│   ├── schemas.py            ← Pydantic request/response shapes
│   ├── store.py              ← In-memory fallback when Postgres is down; connector templates
│   ├── security.py           ← Fernet encrypt/decrypt for stored passwords
│   ├── integrations_service.py ← Save/load connector credentials (encrypted)
│   ├── init_dbs.py           ← One-time setup: create dataguard + company_data DBs
│   ├── .env                  ← POSTGRES_URL, SPLINE_PRODUCER_URL, SPLINE_CONSUMER_URL
│   │
│   ├── routers/
│   │   ├── connectors.py     ← CRUD for integrations (MariaDB + GitHub), test connection
│   │   ├── pipeline.py       ← Run ETL pipeline, stream SSE logs to browser
│   │   ├── lineage.py        ← Read lineage records from dataguard DB
│   │   └── audit.py          ← Read audit log entries
│   │
│   └── engines/
│       ├── spark_etl.py           ← PySpark session + Spline init + per-table ETL logic
│       ├── spline_consumer_sync.py ← After ETL: query Spline + ArangoDB for column lineage
│       └── lineage_persistence.py  ← Write lineage_data dict into PostgreSQL tables
│
└── frontend/                 ← React + Vite UI
    └── src/
        ├── App.jsx           ← Top-level routing
        ├── pages/
        │   ├── Dashboard.jsx     ← Stats: integrations count, run counts
        │   ├── Connectors.jsx    ← Add/test/delete MariaDB or GitHub connectors
        │   └── EvidenceBoard.jsx ← Lineage graph viewer
        └── components/
            ├── ConnectMariaDB.jsx    ← Form for MariaDB credentials
            ├── ConnectGitHub.jsx     ← Form for GitHub repo/token
            ├── PipelineTerminal.jsx  ← SSE log stream shown as terminal
            ├── LineageGraph.jsx      ← D3/React lineage DAG
            ├── AuditTimeline.jsx     ← Audit log list
            ├── Modal.jsx             ← Reusable modal wrapper
            └── Badge.jsx             ← Status badge chip
```

---

## How it works — full flow

```
YOU (browser)
  │
  │  1. Add Connector
  ▼
Connectors page
  │  POST /connectors/integrations  {template_id, name, credentials}
  │  → connectors.py saves to PostgreSQL (integrations table, password encrypted)
  │
  │  2. Run Pipeline
  ▼
Connectors page → "Run" button
  │  GET /pipeline/{integration_id}/run  (SSE stream)
  │
  ├── If provider = MariaDB ──────────────────────────────────────────────────
  │     pipeline.py
  │       1. pymysql DESCRIBE → discover tables + columns
  │       2. CREATE DATABASE company_data (if not exists)
  │       3. spark_etl.py → create SparkSession (downloads JARs first time ~3 min)
  │          └── SparkLineageInitializer.enableLineageTracking()  ← Spline Agent ON
  │       4. For each table:
  │            df = spark.read JDBC (MariaDB) → select() → clean → select() → write JDBC (PostgreSQL)
  │            Spline Agent intercepts the .write → pushes plan + event to http://localhost:8080/producer
  │       5. spline_consumer_sync.py
  │            GET /consumer/execution-events  → find the plan ID
  │            GET /consumer/execution-plans/{id}  → get source/target URIs + attributes
  │            ArangoDB query → get column derivations (produces + derivesFrom edges)
  │            → build column_lineage list
  │       6. lineage_persistence.py → save to dataguard DB (lineage_jobs, lineage_columns, etc.)
  │
  └── If provider = GitHub ──────────────────────────────────────────────────
        pipeline.py
          1. Download etl.py from raw.githubusercontent.com
          2. Patch MODULE$.method() → getattr(obj, "MODULE$").method()  ← fixes Scala syntax
          3. subprocess.run(python etl.py)
             └── etl.py runs the same MariaDB→PostgreSQL ETL with Spline inside
          4. Same Spline sync + lineage persist as above


  │  3. View Lineage
  ▼
EvidenceBoard page
  │  GET /lineage/jobs, GET /lineage/columns
  │  → shows source table → transforms → target table graph
  │
  │  OR open http://localhost:9090  ← Spline Web UI (native lineage graph)
  │     click any execution → see column-level flow: MariaDB.col → [transform] → PostgreSQL.col
```

---

## Docker services (docker-compose.yml)

| Container        | Port  | What it does                                      |
|------------------|-------|---------------------------------------------------|
| my-postgres      | 5432  | Stores app data: integrations, pipeline runs, lineage |
| mariadb          | 3307  | Source data (governance_db) — customers, orders, products, transactions |
| spline-arangodb  | 8529  | Spline's graph DB — stores execution plans + column lineage |
| spline-rest-server | 8080 | Producer API (receives from PySpark) + Consumer API (read by our sync) |
| spline-web-ui    | —     | Spline's lineage UI (accessed via proxy) |
| spline-proxy     | 9090  | Nginx: / → web-ui, /consumer → rest-server, /producer → rest-server |

**Start everything:** `docker compose up -d`

---

## Two PostgreSQL databases (same container port 5432)

| Database     | Purpose                                  | Created by    |
|--------------|------------------------------------------|---------------|
| dataguard    | App metadata (integrations, lineage, audit) | init_dbs.py  |
| company_data | ETL output (customers, orders, etc.)    | pipeline at runtime |

---

## Column-level lineage — how Spline captures it

1. Spline Agent intercepts every `df.write` in PySpark
2. It reads Spark's logical plan → finds Read/Project/Deduplicate/Write nodes
3. Stores attribute IDs + derivesFrom edges in ArangoDB

Our sync code reads ArangoDB directly (Consumer API strips node details):
- `produces` edges → which columns come from the Read node (source cols)
- `derivesFrom` edges → which columns are derived/transformed

Result: `amount → amount [transform]`, `transaction_date → transaction_date [transform]`, 6 passthrough columns

---

## Run the project

```bash
# 1. Start Docker services
docker compose up -d

# 2. Setup databases (first time only)
cd backend
python init_dbs.py

# 3. Start backend
uvicorn main:app --reload

# 4. Start frontend (separate terminal)
cd frontend
npm run dev

# 5. Open browser
#   DataGuard UI:  http://localhost:5173
#   Spline UI:     http://localhost:9090
```

---

## MariaDB seed data (already loaded)

```
governance_db tables: customers, orders, products, transactions
Connect: localhost:3307  user=root  password=root123
```
