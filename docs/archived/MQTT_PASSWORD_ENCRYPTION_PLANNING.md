# MQTT Password Encryption (Planning)

> Archived: implemented; kept for historical context.

## Goal
Encrypt the stored MQTT broker password at rest, while preserving the current UX:
- Password is never returned to the frontend (only `hasPassword`).
- Saving without providing a password keeps the existing password.
- MQTT runtime uses the decrypted password in memory only.

## Constraints
- MQTT settings are currently stored in `AlarmSettingsEntry.value` JSON under key `mqtt_connection`.
- The system already uses `.env` for secrets; we will add an app-managed encryption key there.

## Proposed approach

### Key management
- Add a single env var: `SETTINGS_ENCRYPTION_KEY`
  - A 32-byte urlsafe base64 value (Fernet-compatible).
  - Required to decrypt any encrypted values.
- Rotation plan (later):
  - Add `SETTINGS_ENCRYPTION_KEY_PREVIOUS` to allow decrypt with old key and re-encrypt on next save.

### Storage format
- Keep using the existing `mqtt_connection` JSON blob, but store the password as an encrypted token:
  - `password: "enc:<token>"`
- This avoids schema migrations and keeps backward-compat with any existing plaintext passwords.

### Encryption algorithm
- Use `cryptography.fernet.Fernet` for authenticated encryption.
- If `SETTINGS_ENCRYPTION_KEY` is missing:
  - Do not encrypt on save.
  - If a stored password is encrypted and the key is missing, treat MQTT as misconfigured and surface a clear error to admins.

### Migration behavior
- Existing plaintext passwords continue working.
- When the user re-enters the MQTT password in settings, it is stored encrypted going forward.

## Implementation checklist
- Add `cryptography` dependency.
- Add helpers:
  - `encrypt_secret(plain) -> "enc:..."`
  - `decrypt_secret(value) -> plain` (supports plaintext passthrough)
- Update MQTT settings view:
  - Encrypt password when provided.
  - Preserve existing password token when password omitted.
  - Decrypt before calling the MQTT connection manager.
- Update app boot MQTT connect path to decrypt before connecting.

## Security notes
- The encryption key in `.env` must be treated like a production secret.
- Encryption protects database-at-rest exposure; it does not protect a fully compromised running server.
