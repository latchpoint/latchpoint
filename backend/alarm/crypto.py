"""
Centralized encryption service for settings stored in AlarmSettingsEntry
and NotificationProvider JSON blobs.

Uses Fernet symmetric encryption with a versioned ``enc:v1:`` prefix to
support future algorithm migration without a flag-day data migration.

Key resolution order:
1. ``SETTINGS_ENCRYPTION_KEY`` env var (explicit operator choice)
2. Persisted key file in data volume (auto-generated on first boot)
3. Generate new key, write to key file, return it
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

ENCRYPTED_PREFIX = "enc:v1:"

_KEY_FILE = Path(os.environ.get("DATA_DIR", "/data")) / ".encryption_key"


def ensure_encryption_key() -> str:
    """Return the encryption key, generating one if needed.

    Raises ``RuntimeError`` if the data directory does not exist and no
    explicit key is provided via the environment.
    """
    # 1. Explicit env var takes priority
    key = os.environ.get("SETTINGS_ENCRYPTION_KEY", "").strip()
    if key:
        return key

    # 2. Previously auto-generated key
    if _KEY_FILE.exists():
        return _KEY_FILE.read_text().strip()

    # 3. First boot — generate and persist
    if not _KEY_FILE.parent.exists():
        raise RuntimeError(
            f"Data directory {_KEY_FILE.parent} does not exist. "
            "Mount a persistent volume or set SETTINGS_ENCRYPTION_KEY."
        )
    key = Fernet.generate_key().decode()
    _KEY_FILE.write_text(key)
    _KEY_FILE.chmod(0o600)
    return key


class SettingsEncryption:
    """Fernet-based encryption for secret fields within JSON settings blobs.

    Singleton — access via ``SettingsEncryption.get()``.
    """

    _instance: SettingsEncryption | None = None
    _fernet: Fernet | None = None

    @classmethod
    def get(cls) -> SettingsEncryption:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton — for tests only."""
        cls._instance = None

    def __init__(self) -> None:
        key = ensure_encryption_key()
        self._fernet = Fernet(key.encode())

    # ------------------------------------------------------------------
    # Primitive operations
    # ------------------------------------------------------------------

    def encrypt(self, value: str) -> str:
        """Encrypt a plaintext string. Returns ``enc:v1:``-prefixed token."""
        if not value:
            return ""
        if value.startswith(ENCRYPTED_PREFIX):
            return value  # already encrypted
        return ENCRYPTED_PREFIX + self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        """Decrypt an ``enc:v1:``-prefixed token.

        Raises ``ValueError`` if the value is not prefixed (plaintext where
        encrypted was expected) and ``InvalidToken`` if decryption fails
        (wrong key or corrupted data).
        """
        if not value:
            return ""
        if not value.startswith(ENCRYPTED_PREFIX):
            raise ValueError(
                f"Expected encrypted value with '{ENCRYPTED_PREFIX}' prefix, got plaintext. Run the data migration."
            )
        return self._fernet.decrypt(value[len(ENCRYPTED_PREFIX) :].encode()).decode()

    def is_encrypted(self, value: str) -> bool:
        """Check whether a string carries the encryption prefix."""
        return bool(value) and value.startswith(ENCRYPTED_PREFIX)

    # ------------------------------------------------------------------
    # Dict-level helpers
    # ------------------------------------------------------------------

    def encrypt_fields(self, config: dict, fields: list[str]) -> dict:
        """Encrypt specified fields in a config dict. Returns a copy."""
        result = config.copy()
        for field in fields:
            if field in result and result[field]:
                result[field] = self.encrypt(str(result[field]))
        return result

    def decrypt_fields(self, config: dict, fields: list[str]) -> dict:
        """Decrypt specified fields in a config dict. Returns a copy."""
        result = config.copy()
        for field in fields:
            if field in result and result[field]:
                result[field] = self.decrypt(str(result[field]))
        return result

    def mask_fields(self, config: dict, fields: list[str]) -> dict:
        """Replace secret fields with ``has_<field>`` booleans. Returns a copy."""
        result = config.copy()
        for field in fields:
            raw = result.pop(field, "")
            result[f"has_{field}"] = bool(raw) and raw != ""
        return result


__all__ = [
    "ENCRYPTED_PREFIX",
    "InvalidToken",
    "SettingsEncryption",
    "ensure_encryption_key",
]
