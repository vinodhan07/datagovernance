import uuid
from datetime import datetime

# Stable ID for the built-in MariaDB template
MARIADB_TEMPLATE_ID = "mariadb-builtin"

_templates = {}
_integrations = {}

def ensure_mariadb_template() -> None:
    template_data = {
        "provider_name": "MariaDB",
        "category": "Database",
        "description": "Connect to a MariaDB or MySQL database (read-only governance).",
        "logo_url": "https://mariadb.com/wp-content/uploads/2019/11/mariadb-logo-vert_blue-transparent.png",
        "credential_fields": [
            {"key": "host", "label": "Host", "placeholder": "localhost", "required": True},
            {"key": "port", "label": "Port", "placeholder": "3307", "required": True},
            {"key": "database", "label": "Database Name", "placeholder": "governance_db", "required": True},
            {"key": "user", "label": "Username", "placeholder": "root", "required": True},
            {"key": "password", "label": "Password", "type": "password", "required": True},
            {"key": "ssl", "label": "SSL Mode", "placeholder": "disable", "required": False}
        ],
        "created_at": datetime.now()
    }
    
    # Register with both IDs for compatibility
    for tid in ["mariadb-builtin", "tmpl_mariadb_standard"]:
        if tid not in _templates:
            _templates[tid] = {"id": tid, **template_data}

def ensure_github_template() -> None:
    template_data = {
        "provider_name": "GitHub",
        "category": "Git",
        "description": "Connect to a GitHub repository to analyze ETL code and generate data lineage.",
        "logo_url": "https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png",
        "credential_fields": [
            {"key": "owner", "label": "Owner / Org", "placeholder": "octocat", "required": True},
            {"key": "repo", "label": "Repository Name", "placeholder": "hello-world", "required": True},
            {"key": "token", "label": "Personal Access Token", "type": "password", "required": False},
            {"key": "filepath", "label": "ETL File Path", "placeholder": "src/etl.py", "required": True},
            {"key": "branch", "label": "Branch", "placeholder": "main", "required": False}
        ],
        "created_at": datetime.now()
    }
    
    for tid in ["github-builtin", "tmpl_github_standard"]:
        if tid not in _templates:
            _templates[tid] = {"id": tid, **template_data}

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
            "created_at": v["created_at"]
        }
        for k, v in _integrations.items()
    ]

def get_integration(integration_id: str):
    return _integrations.get(integration_id)

def create_integration(data, provider_name: str):
    integration_id = str(uuid.uuid4())
    new_int = {
        "id": integration_id,
        "name": data.name,
        "provider_name": provider_name,
        "credentials": data.credentials,
        "created_at": datetime.now()
    }
    _integrations[integration_id] = new_int
    return {
        "id": integration_id,
        "name": new_int["name"],
        "provider_name": new_int["provider_name"],
        "status": "active",
        "created_at": new_int["created_at"]
    }

def delete_integration(integration_id: str) -> bool:
    if integration_id in _integrations:
        del _integrations[integration_id]
        return True
    return False

# Initialize templates on load
ensure_mariadb_template()
ensure_github_template()

# Quality Rules
_rules = {}

def list_rules():
    return list(_rules.values())

def get_rule(rule_id: str):
    return _rules.get(rule_id)

def create_rule(data):
    rule_id = str(uuid.uuid4())
    new_rule = {
        "id": rule_id,
        "name": data.name,
        "rule_type": data.rule_type,
        "table_name": data.table_name,
        "column_name": data.column_name,
        "severity": data.severity,
        "params": data.params,
        "created_at": datetime.now()
    }
    _rules[rule_id] = new_rule
    return new_rule
