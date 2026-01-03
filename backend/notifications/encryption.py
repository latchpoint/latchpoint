"""
Encryption utilities for notification provider configurations.

Re-exports from alarm.crypto for backward compatibility.
"""

from alarm.crypto import decrypt_config, encrypt_config, mask_config

__all__ = ["encrypt_config", "decrypt_config", "mask_config"]
