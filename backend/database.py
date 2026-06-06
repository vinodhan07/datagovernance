"""
database.py — SQLAlchemy session for the dataguard PostgreSQL DB.
All other code uses get_db() to get a session.
"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import config

engine       = create_engine(config.POSTGRES_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def is_db_available() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
