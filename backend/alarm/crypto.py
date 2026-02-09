from __future__ import annotations

import base64
import os
from copy import deepcopy
from functools import lru_cache
from typing import Any


ENCRYPTION_PREFIX = "enc:"
SETTINGS_ENCRYPTION_KEY_ENV = "SETTINGS_ENCRYPTION_KEY"


class EncryptionNotConfigured(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _get_fernet():
    """Return a configured Fernet instance, or None when encryption key is missing."""
    key = (os.environ.get(SETTINGS_ENCRYPTION_KEY_ENV) or "").strip()
    if not key:
        return None
    try:
        # Validate it's base64-ish and the right length for Fernet (32 bytes key -> 44 chars b64).
        decoded = base64.urlsafe_b64decode(key)
        if len(decoded) != 32:
            raise ValueError("Invalid key length.")
    except Exception as exc:
        raise EncryptionNotConfigured(f"{SETTINGS_ENCRYPTION_KEY_ENV} is not a valid Fernet key.") from exc

    try:
        from cryptography.fernet import Fernet  # type: ignore[import-not-found]
    except Exception as exc:
        raise EncryptionNotConfigured("Missing dependency: cryptography.") from exc

    return Fernet(key.encode("utf-8"))


def can_encrypt() -> bool:
    """Return True if encryption is configured and dependencies are available."""
    try:
        return _get_fernet() is not None
    except EncryptionNotConfigured:
        return False


def encrypt_secret(value: str) -> str:
    """
    Encrypts a secret string, returning an `enc:`-prefixed token.

    Raises `EncryptionNotConfigured` if encryption is not available.
    """

    if value is None:
        return ""
    value = str(value)
    if value == "":
        return ""
    f = _get_fernet()
    if f is None:
        raise EncryptionNotConfigured(
            f"{SETTINGS_ENCRYPTION_KEY_ENV} is required to encrypt secrets."
        )
    token = f.encrypt(value.encode("utf-8")).decode("utf-8")
    return f"{ENCRYPTION_PREFIX}{token}"


def decrypt_secret(value: str) -> str:
    """
    Decrypts a secret string.

    Raises `ValueError` for non-empty plaintext values (missing `enc:` prefix).
    Raises `EncryptionNotConfigured` when decryption is needed but no key is set.
    """

    if value is None:
        return ""
    value = str(value)
    if value == "":
        return ""
    if not value.startswith(ENCRYPTION_PREFIX):
        raise ValueError(
            "Plaintext secret detected. Run `manage.py encrypt_plaintext_secrets` to migrate."
        )
    f = _get_fernet()
    if f is None:
        raise EncryptionNotConfigured(f"{SETTINGS_ENCRYPTION_KEY_ENV} is required to decrypt stored secrets.")
    token = value[len(ENCRYPTION_PREFIX) :]
    return f.decrypt(token.encode("utf-8")).decode("utf-8")


def encrypt_config(config: dict[str, Any] | None, encrypted_fields: list[str]) -> dict[str, Any] | None:
    """
    Encrypt sensitive fields in a configuration dictionary.

    - Fields that are missing are left untouched.
    - `None` values for encrypted fields are normalized to `""`.
    - Values that already start with `enc:` are not re-encrypted.
    """
    if not config:
        return config

    result: dict[str, Any] = dict(config)
    for field in encrypted_fields:
        if field not in result:
            continue
        value = result[field]
        if value is None:
            result[field] = ""
            continue
        if isinstance(value, str) and value.startswith(ENCRYPTION_PREFIX):
            continue
        result[field] = encrypt_secret(value)
    return result


def decrypt_config(config: dict[str, Any] | None, encrypted_fields: list[str]) -> dict[str, Any] | None:
    """
    Decrypt sensitive fields in a configuration dictionary.

    Plaintext values (missing ``enc:`` prefix) are passed through with a warning
    so that runtime decryption does not crash before ``encrypt_plaintext_secrets``
    has been run.
    """
    if not config:
        return config

    result: dict[str, Any] = dict(config)
    for field in encrypted_fields:
        if field not in result:
            continue
        value = result[field]
        if value is None:
            result[field] = ""
            continue
        try:
            result[field] = decrypt_secret(value)
        except ValueError:
            # Plaintext value — pass through so runtime stays functional.
            import logging

            logging.getLogger(__name__).warning(
                "Plaintext secret in field %r. Run manage.py encrypt_plaintext_secrets.", field,
            )
    return result


def mask_config(config: dict[str, Any] | None, encrypted_fields: list[str]) -> dict[str, Any] | None:
    """
    Mask sensitive fields for API responses.

    Replaces each secret field with `has_<field>` boolean indicator.
    """
    if not config:
        return config

    result: dict[str, Any] = dict(config)
    for field in encrypted_fields:
        has_field = f"has_{field}"
        if field in result:
            value = result.pop(field)
            result[has_field] = bool(value)
        else:
            result[has_field] = False
    return result


def prepare_runtime_config(
    raw: object,
    *,
    encrypted_fields: list[str],
    defaults: dict[str, Any],
) -> dict[str, Any]:
    """
    Prepare a configuration dict for runtime usage:

    - Normalize against `defaults` (drop unknown keys).
    - Decrypt encrypted fields.
    """
    normalized: dict[str, Any] = deepcopy(defaults)
    if isinstance(raw, dict):
        normalized.update({k: v for k, v in raw.items() if k in normalized})
    decrypted = decrypt_config(normalized, encrypted_fields) or {}
    return dict(decrypted)
