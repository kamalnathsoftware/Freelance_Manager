"""Encryption helpers for the token/credential vault (Fernet)."""

import base64
import hashlib

from cryptography.fernet import Fernet

from app.core.config import get_settings


def _fernet() -> Fernet:
    s = get_settings()
    key = s.encryption_key
    if not key:
        # Dev fallback derived from SECRET_KEY. Production must set ENCRYPTION_KEY.
        key = base64.urlsafe_b64encode(hashlib.sha256(s.secret_key.encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()
