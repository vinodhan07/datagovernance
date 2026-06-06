"""
init_dbs.py — One-time database setup. Run once before starting the server:
    python init_dbs.py

Creates two PostgreSQL databases (both in the same Docker container):
  dataguard    — app metadata: integrations, lineage, audit, pipeline runs
  company_data — ETL output tables (tables created at runtime by the pipeline)
"""
import urllib.parse
from sqlalchemy import create_engine, text

import config

# Parse POSTGRES_URL to get the base URL without database name
_parsed = urllib.parse.urlparse(config.POSTGRES_URL)
_BASE   = f"{_parsed.scheme}://{_parsed.username}:{_parsed.password}@{_parsed.hostname}:{_parsed.port}"


def _ensure_db(name: str) -> None:
    """Create a PostgreSQL database if it doesn't already exist."""
    engine = create_engine(f"{_BASE}/postgres", isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :db"), {"db": name}
        ).fetchone()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
            print(f"  [+] Created '{name}'")
        else:
            print(f"  [=] '{name}' already exists")
    engine.dispose()


def init_dataguard() -> None:
    """Create dataguard DB + all app tables."""
    print("\n── dataguard (app metadata) ─────────────────────────")
    _ensure_db("dataguard")
    from models import Base
    engine = create_engine(f"{_BASE}/dataguard")
    Base.metadata.create_all(engine)
    print("  [+] Tables verified")
    engine.dispose()


def init_company_data() -> None:
    """Create company_data DB (ETL output). Tables are added by the pipeline at runtime."""
    print(f"\n── {config.TARGET_DB} (ETL output) ──────────────────────────")
    _ensure_db(config.TARGET_DB)
    print("  [i] Tables are created automatically when the pipeline first runs")


if __name__ == "__main__":
    print("═══════════════════════════════════════════════════════")
    print("  DataGuard — Database Initialisation")
    print("═══════════════════════════════════════════════════════")
    try:
        init_dataguard()
        init_company_data()
        print("\n  [✓] Done — run: uvicorn main:app --reload")
    except Exception as exc:
        print(f"\n  [✗] Failed: {exc}")
        raise
