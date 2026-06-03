from sqlalchemy.orm import Session
from models import Integration
from security import encrypt_password, decrypt_password
import uuid

def save_integration(db: Session, data: dict, provider: str, category: str = "database", name: str | None = None): # type: ignore
    """
    Encrypts password/token and saves integration to PostgreSQL.
    """
    password_val = data.get("password", "") or data.get("token", "")
    encrypted_pw = encrypt_password(password_val)

    new_integration = Integration(
        id=str(uuid.uuid4()),
        name=name or data.get("name") or "Unnamed",
        provider=provider,
        category=category,
        host=data.get("host") or data.get("filepath"),
        port=data.get("port"),
        database_name=data.get("database") or data.get("repo"),
        username=data.get("user") or data.get("owner"),
        password_encrypted=encrypted_pw,
        ssl_mode=data.get("ssl") or data.get("branch") or "disable"
    )
    
    db.add(new_integration)
    db.commit()
    db.refresh(new_integration)
    return new_integration

def get_connection_config(db: Session, integration_id: str): # type: ignore
    """
    Fetches integration from DB and decrypts password.
    """
    integration = db.query(Integration).filter(Integration.id == integration_id).first()
    if not integration:
        return None
        
    password_decrypted = decrypt_password(str(integration.password_encrypted))
    
    if integration.provider == "GitHub":
        return {
            "owner": integration.username,
            "repo": integration.database_name,
            "filepath": integration.host,
            "branch": integration.ssl_mode,
            "token": password_decrypted
        }
        
    return {
        "host": integration.host,
        "port": integration.port,
        "database": integration.database_name,
        "user": integration.username, # Note: user instead of username to match current creds usage
        "password": password_decrypted,
        "ssl": integration.ssl_mode
    }

from urllib.parse import quote_plus

def build_connection_url(config: dict):
    """
    Builds SQLAlchemy connection string from config.
    """
    user = quote_plus(str(config.get('user', '')))
    password = quote_plus(str(config.get('password', '')))
    host = config.get('host', 'localhost')
    port = config.get('port', 3306)
    database = config.get('database', '')
    
    url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
    ssl_mode = config.get("ssl", "disable")
    if ssl_mode and ssl_mode != "disable":
        url += "?ssl_disabled=false"
    return url
