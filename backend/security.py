import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

_key = os.getenv("ENCRYPTION_KEY")

if not _key:
    raise RuntimeError(
        "\n\nENCRYPTION_KEY is not set in backend/.env\n"
        "Generate a stable key once and add it:\n\n"
        "  python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"\n\n"
        "Then add to backend/.env:\n"
        "  ENCRYPTION_KEY=<paste-key-here>\n"
    )

_cipher = Fernet(_key.encode())


def encrypt_password(password: str) -> str:
    if not password:
        return ""
    return _cipher.encrypt(password.encode()).decode()


def decrypt_password(enc_password: str) -> str:
    if not enc_password:
        return ""
    try:
        return _cipher.decrypt(enc_password.encode()).decode()
    except Exception:
        return ""
