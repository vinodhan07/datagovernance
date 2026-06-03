import os
from sqlalchemy import create_engine, text # type: ignore
from sqlalchemy.orm import sessionmaker, Session # type: ignore
from dotenv import load_dotenv

load_dotenv()

# Use POSTGRES_URL from .env
POSTGRES_URL = os.getenv("POSTGRES_URL")

if not POSTGRES_URL:
    # Fallback/Default for development
    POSTGRES_URL = "postgresql://postgres:postgres@localhost:5432/dataguard"

engine = create_engine(POSTGRES_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def is_db_available() -> bool:
    """Check if the database is reachable."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
