"""
security.py — Fernet encryption for stored connector passwords/tokens.
"""
from cryptography.fernet import Fernet
import config

if not config.ENCRYPTION_KEY:
    raise RuntimeError(
        "ENCRYPTION_KEY missing in backend/.env\n"
        "Generate: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )

_cipher = Fernet(config.ENCRYPTION_KEY.encode())


def encrypt_password(password: str) -> str:
    return _cipher.encrypt(password.encode()).decode() if password else ""


def decrypt_password(enc: str) -> str:
    try:
        return _cipher.decrypt(enc.encode()).decode() if enc else ""
    except Exception:
        return ""
