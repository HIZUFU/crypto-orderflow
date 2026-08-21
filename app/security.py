import base64
import hashlib
from pathlib import Path

from cryptography.fernet import Fernet

from app.config import get_settings


def _fernet() -> Fernet:
    secret = get_settings().app_secret_key.encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def encrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet().decrypt(value.encode("ascii")).decode("utf-8")


def mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    return f"{value[:4]}...{value[-4:]}" if len(value) > 8 else "****"
