"""
integrations_service.py — Credential encryption, storage, and retrieval.
Only MariaDB connectors are supported.
"""
import uuid
from urllib.parse import quote_plus

from sqlalchemy.orm import Session

from src.domain.entities import Integration
from src.core.security import encrypt_password, decrypt_password


def save_integration(db: Session, data: dict, provider: str = "MariaDB",
                     category: str = "database", name: str | None = None) -> Integration:
    """Encrypt password/token and persist a new integration to PostgreSQL."""
    # MariaDB uses "password"; GitHub uses "token"
    secret = data.get("password") or data.get("token") or ""
    encrypted_pw = encrypt_password(secret)

    if provider == "GitHub":
        integration = Integration(
            id=str(uuid.uuid4()),
            name=name or data.get("name") or "Unnamed",
            provider=provider,
            category=category,
            host=data.get("filepath"),       # reuse host column for filepath
            port=None,
            database_name=data.get("repo"),  # reuse database_name for repo
            username=data.get("owner"),      # reuse username for owner
            password_encrypted=encrypted_pw,
            ssl_mode=data.get("branch") or "main",  # reuse ssl_mode for branch
        )
    else:
        integration = Integration(
            id=str(uuid.uuid4()),
            name=name or data.get("name") or "Unnamed",
            provider=provider,
            category=category,
            host=data.get("host"),
            port=data.get("port"),
            database_name=data.get("database"),
            username=data.get("user"),
            password_encrypted=encrypted_pw,
            ssl_mode=data.get("ssl") or "disable",
        )

    db.add(integration)
    db.commit()
    db.refresh(integration)
    return integration


def get_connection_config(db: Session, integration_id: str) -> dict | None:
    """Fetch and decrypt credentials for an integration."""
    integration = db.query(Integration).filter(Integration.id == integration_id).first()
    if not integration:
        return None

    secret = decrypt_password(str(integration.password_encrypted))

    if integration.provider == "GitHub":
        return {
            "owner":    (integration.username or "").strip(),
            "repo":     (integration.database_name or "").strip(),
            "filepath": (integration.host or "").strip(),
            "branch":   (integration.ssl_mode or "main").strip(),
            "token":    secret,
        }

    return {
        "host":     integration.host,
        "port":     integration.port,
        "database": integration.database_name,
        "user":     integration.username,
        "password": secret,
        "ssl":      integration.ssl_mode,
    }


def build_connection_url(creds: dict) -> str:
    """Build a SQLAlchemy mysql+pymysql URL from a credentials dict."""
    user     = quote_plus(str(creds.get("user",     "")))
    password = quote_plus(str(creds.get("password", "")))
    host     = creds.get("host")     or "localhost"
    port     = creds.get("port")     or 3306
    database = creds.get("database") or ""
    url      = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
    ssl_mode = creds.get("ssl", "disable")
    if ssl_mode and ssl_mode != "disable":
        url += "?ssl_disabled=false"
    return url
