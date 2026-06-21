"""
Symmetric encryption for sensitive fields (e.g. llm_api_key).
Uses Fernet with a dedicated ENCRYPTION_KEY env var.

In production, ENCRYPTION_KEY is required and must be set independently
from JWT_SECRET_KEY.  Deriving from JWT_SECRET_KEY is only allowed in
development mode, and logs a prominent warning each time.
"""
import base64
import hashlib
import logging
import os
from cryptography.fernet import Fernet

from sqlalchemy.types import TypeDecorator, String

logger = logging.getLogger("trad_account")

_warned_fallback = False


def _get_fernet() -> Fernet:
    global _warned_fallback
    raw = os.environ.get("ENCRYPTION_KEY", "")
    if raw:
        key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
    else:
        env = os.environ.get("ENVIRONMENT", "development")
        if env == "production":
            raise RuntimeError(
                "ENCRYPTION_KEY environment variable is required in production. "
                "Generate a random 64-character hex string and set it separately from JWT_SECRET_KEY. "
                "Do NOT derive it from JWT_SECRET_KEY — rotating the JWT key would destroy all encrypted data."
            )
        jwt_key = os.environ.get("JWT_SECRET_KEY", "")
        if not jwt_key:
            raise RuntimeError("Neither ENCRYPTION_KEY nor JWT_SECRET_KEY is set")
        if not _warned_fallback:
            logger.warning(
                "ENCRYPTION_KEY not set — deriving encryption key from JWT_SECRET_KEY. "
                "This is acceptable for development ONLY. "
                "In production, set a separate ENCRYPTION_KEY to avoid data loss when rotating JWT keys."
            )
            _warned_fallback = True
        key = base64.urlsafe_b64encode(
            hashlib.sha256(("encryption:" + jwt_key).encode()).digest()
        )
    return Fernet(key)


def encrypt_value(plaintext: str | None) -> str | None:
    if plaintext is None:
        return None
    return _get_fernet().encrypt(plaintext.encode()).decode()


def _looks_like_fernet(value: str) -> bool:
    """Heuristic: Fernet tokens are URL-safe base64, start with 'gAAAAA', and are long."""
    return len(value) > 50 and value.startswith("gAAAAA")


def decrypt_value(ciphertext: str | None) -> str | None:
    if ciphertext is None:
        return None
    if not _looks_like_fernet(ciphertext):
        # Legacy plaintext value — never encrypted
        logger.warning(
            "Decrypting a value that does not appear to be Fernet-encrypted. "
            "It will be returned as-is. Consider re-encrypting this data."
        )
        return ciphertext
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except Exception:
        logger.exception(
            "Failed to decrypt stored Fernet value — possible key rotation or data corruption. "
            "Check that ENCRYPTION_KEY matches the key used when the data was encrypted."
        )
        raise RuntimeError(
            "Decryption failed. The ENCRYPTION_KEY may have been changed or the stored "
            "data is corrupted. Restore the original ENCRYPTION_KEY or re-encrypt the data."
        )


class EncryptedString(TypeDecorator):
    """Transparently encrypts/decrypts a String column via Fernet."""
    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return encrypt_value(str(value))
        return None

    def process_result_value(self, value, dialect):
        if value is not None:
            return decrypt_value(str(value))
        return None
