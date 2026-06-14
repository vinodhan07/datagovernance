"""
store.py — In-memory fallback for when PostgreSQL is unavailable.
Holds integrations and connector templates (MariaDB + GitHub).
"""
import uuid
from datetime import datetime

MARIADB_TEMPLATE_ID = "mariadb-builtin"
GITHUB_TEMPLATE_ID  = "github-builtin"
_templates: dict = {}
_integrations: dict = {}


def ensure_mariadb_template() -> None:
    if MARIADB_TEMPLATE_ID not in _templates:
        _templates[MARIADB_TEMPLATE_ID] = {
            "id": MARIADB_TEMPLATE_ID,
            "provider_name": "MariaDB",
            "category": "database",
            "description": "Connect to an external MariaDB / MySQL database.",
            "credential_fields": [
                {"key": "host",     "label": "Host",          "placeholder": "localhost",    "required": True},
                {"key": "port",     "label": "Port",          "placeholder": "3307",         "required": True},
                {"key": "database", "label": "Database Name", "placeholder": "my_database",  "required": True},
                {"key": "user",     "label": "Username",      "placeholder": "root",         "required": True},
                {"key": "password", "label": "Password",      "type": "password",            "required": True},
                {"key": "ssl",      "label": "SSL Mode",      "placeholder": "disable",      "required": False},
            ],
            "created_at": datetime.now(),
        }
        _templates["tmpl_mariadb_standard"] = _templates[MARIADB_TEMPLATE_ID]


def ensure_github_template() -> None:
    if GITHUB_TEMPLATE_ID not in _templates:
        _templates[GITHUB_TEMPLATE_ID] = {
            "id": GITHUB_TEMPLATE_ID,
            "provider_name": "GitHub",
            "category": "git",
            "description": "Fetch a PySpark ETL script from GitHub and run it with Spline lineage.",
            "credential_fields": [
                {"key": "owner",    "label": "Owner / Org",           "placeholder": "your-username", "required": True},
                {"key": "repo",     "label": "Repository",            "placeholder": "my-repo",       "required": True},
                {"key": "filepath", "label": "Script path in repo",   "placeholder": "etl_pipeline.py","required": True},
                {"key": "branch",   "label": "Branch",                "placeholder": "main",          "required": False},
                {"key": "token",    "label": "Personal Access Token", "type": "password",             "required": False},
            ],
            "created_at": datetime.now(),
        }
        _templates["tmpl_github_standard"] = _templates[GITHUB_TEMPLATE_ID]


def get_template(template_id: str):
    ensure_mariadb_template()
    ensure_github_template()
    return _templates.get(template_id)


def list_integrations():
    return [
        {
            "id": k,
            "name": v["name"],
            "provider_name": v["provider_name"],
            "category": "database",
            "status": "active",
            "created_at": v["created_at"],
        }
        for k, v in _integrations.items()
    ]


def get_integration(integration_id: str):
    return _integrations.get(integration_id)


def create_integration(data, provider_name: str):
    integration_id = str(uuid.uuid4())
    _integrations[integration_id] = {
        "id": integration_id,
        "name": data.name,
        "provider_name": provider_name,
        "credentials": data.credentials,
        "created_at": datetime.now(),
    }
    return {
        "id": integration_id,
        "name": data.name,
        "provider_name": provider_name,
        "status": "active",
        "created_at": _integrations[integration_id]["created_at"],
    }


def delete_integration(integration_id: str) -> bool:
    if integration_id in _integrations:
        del _integrations[integration_id]
        return True
    return False


ensure_mariadb_template()
