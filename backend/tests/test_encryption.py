"""Tests for the encryption module."""

import os
import pytest
from app.encryption import encrypt_value, decrypt_value, EncryptedString


class TestEncryptDecrypt:
    def test_round_trip(self):
        original = "sk-test-api-key-123456"
        encrypted = encrypt_value(original)
        assert encrypted is not None
        assert encrypted != original
        decrypted = decrypt_value(encrypted)
        assert decrypted == original

    def test_encrypt_none_returns_none(self):
        assert encrypt_value(None) is None

    def test_decrypt_none_returns_none(self):
        assert decrypt_value(None) is None

    def test_decrypt_plaintext_fallback(self):
        """Legacy plaintext values should be returned as-is."""
        plaintext = "old-plaintext-key"
        result = decrypt_value(plaintext)
        assert result == plaintext

    def test_different_keys_produce_different_ciphertext(self):
        """Same plaintext encrypted twice should produce different ciphertext (random IV)."""
        plaintext = "my-secret"
        ct1 = encrypt_value(plaintext)
        ct2 = encrypt_value(plaintext)
        assert ct1 != ct2
        assert decrypt_value(ct1) == plaintext
        assert decrypt_value(ct2) == plaintext

    def test_empty_string(self):
        encrypted = encrypt_value("")
        assert encrypted is not None
        assert decrypt_value(encrypted) == ""

    def test_missing_key_raises(self):
        old_jwt = os.environ.pop("JWT_SECRET_KEY", None)
        old_enc = os.environ.pop("ENCRYPTION_KEY", None)
        try:
            with pytest.raises(RuntimeError, match="Neither ENCRYPTION_KEY nor JWT_SECRET_KEY"):
                encrypt_value("test")
        finally:
            if old_jwt is not None:
                os.environ["JWT_SECRET_KEY"] = old_jwt
            if old_enc is not None:
                os.environ["ENCRYPTION_KEY"] = old_enc
