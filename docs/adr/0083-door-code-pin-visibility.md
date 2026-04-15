# ADR 0083: Door Code PIN Visibility with Encrypted Storage

## Status
**Proposed**

## Context

Door code PINs are currently treated like passwords — hashed with PBKDF2 (`make_password()`) on creation or sync, and never recoverable. The UI explicitly states: *"Codes are stored hashed on the server. Enter a 4–8 digit PIN; you cannot view it later."*

This was a deliberate security decision (ADR 0068/0069), but door codes are not passwords. They are PINs that users physically punch into a keypad, share with guests, or give to service technicians. The inability to look up a code after entry defeats the purpose of centralized code management. Practically:

- **Manual codes**: The user enters a PIN at creation and can never see it again. If they forget which code they gave a guest, they must delete and re-create it.
- **Synced codes**: The PIN is read from the Z-Wave lock during sync (the same PIN that's freely visible in the Z-Wave JS admin UI), hashed, and discarded. The user sees only `PIN length: 6` and `PIN known/unknown`.

The hashing model also has a functional cost: `check_password()` with PBKDF2 is intentionally slow (~15-40ms per call), which adds up during sync when comparing PINs across 30+ slots.

### Relevant ADRs
- **ADR 0068** — Z-Wave JS Lock Config Sync (established PIN hashing policy)
- **ADR 0069** — Lock Config Sync: Operational, Security & UX Concerns (PIN exposure risk analysis)
- **ADR 0082** — Z-Wave JS Lock Domain, Synced Code Lifecycle, Code-Capable Lock Filtering

## Decision

### Replace PBKDF2 hashing with Fernet encryption for door code PINs

Store PINs using the existing `SettingsEncryption` (Fernet symmetric encryption from `alarm/crypto.py`) instead of one-way PBKDF2 hashing. PINs are encrypted at rest with the `enc:v1:` prefix and decryptable for display.

This reuses the same encryption infrastructure already protecting MQTT passwords, Home Assistant tokens, and notification provider credentials.

### Model change

Rename `code_hash` → `encrypted_pin` on the `DoorCode` model:

```python
# Before
code_hash = models.TextField(null=True, blank=True)

# After
encrypted_pin = models.TextField(null=True, blank=True)
```

- On create (manual): `encrypted_pin = SettingsEncryption.get().encrypt(raw_code)`
- On sync: `encrypted_pin = SettingsEncryption.get().encrypt(raw_pin)` if PIN is known, else `None`
- On update (manual, new code provided): re-encrypt with the new PIN
- `pin_length` is retained as a fast non-decrypting metadata field

### API response includes `pin` field

Add a `pin` field to `DoorCodeSerializer`:

```python
pin = serializers.SerializerMethodField()

def get_pin(self, obj: DoorCode) -> str | None:
    if not obj.encrypted_pin:
        return None
    try:
        return SettingsEncryption.get().decrypt(obj.encrypted_pin)
    except (ValueError, InvalidToken):
        return None
```

The PIN is always present in the API response for authorized users. Visibility toggling is a frontend concern — the backend does not distinguish between "masked" and "revealed" requests.

**Access control**: The existing endpoint permissions apply — only the code's owner or an admin can fetch door codes. No additional permission layer is needed for PIN visibility.

### Code validation changes

`code_validation.py` currently uses `check_password(raw_code, code_hash)` to match entered PINs against stored hashes. With encryption, this becomes a direct string comparison:

```python
# Before
if check_password(raw_code, candidate.code_hash):

# After
if candidate.encrypted_pin:
    stored_pin = SettingsEncryption.get().decrypt(candidate.encrypted_pin)
    if raw_code == stored_pin:
```

This is faster (no PBKDF2 iterations) and functionally equivalent.

### Lock config sync changes

In `lock_config_sync.py`, replace all `make_password()`/`check_password()` calls with `SettingsEncryption.get().encrypt()`/`decrypt()`:

- **PIN change detection** (update path): decrypt stored PIN and compare directly instead of `check_password()`
- **New code creation**: encrypt PIN instead of hashing
- **Race-condition path**: encrypt PIN instead of hashing

### Frontend: eye icon toggle for PIN visibility

PINs are hidden by default and revealed on demand with a toggle button.

#### DoorCodeCard (read view)

Replace the current `PIN length: 4` display with a masked/revealed PIN:

```
PIN: •••• [👁 toggle]     ← default (hidden)
PIN: 1234 [👁 toggle]     ← revealed
```

- Default state: masked with `•` characters repeated to `pinLength` (or `pin.length` if available)
- Toggle: eye icon button (Lucide `Eye` / `EyeOff`) switches between masked and plaintext
- If `pin` is `null` (masked/unknown synced code): show `PIN: unknown` with no toggle
- State is local to each card — toggling one code doesn't reveal others

#### DoorCodeCreateBasicsFields (create form)

- Remove the text *"Codes are stored hashed on the server. Enter a 4–8 digit PIN; you cannot view it later."*
- Replace with *"Enter a 4–8 digit PIN."*
- The code input field remains a standard text input with `inputMode="numeric"` (already the case)
- Remove the description *"Codes are never shown again after creation."*

#### LockConfigSyncCard (sync results)

Replace the `PIN known` / `PIN unknown` labels with the actual masked/revealable PIN for known slots.

### Migration strategy

This is an unreleased application — no backwards compatibility with legacy PBKDF2 hashes.

The migration drops `code_hash` and adds `encrypted_pin`. Existing door code rows will have `encrypted_pin = NULL` after migration. The user re-syncs locks and re-creates manual codes to populate PINs. No legacy hash detection or "not recoverable" UI states needed.

## Alternatives Considered

### A. Fetch PINs on-demand from Z-Wave JS (no storage)
Read the PIN from the physical lock each time the user clicks the eye icon. This avoids storing PINs entirely but requires the Z-Wave JS server to be online and connected, adds ~2-5s latency per reveal (WebSocket round-trip), generates RF traffic to the lock, and only works for synced codes — manual codes would still need storage.

### B. Separate authenticated endpoint for PIN reveal
Require re-authentication (password entry) each time the user wants to see a PIN. This adds friction that doesn't match the use case — a user looking up a guest code to text it shouldn't need to re-enter their password every time. The existing endpoint auth (session cookie + RBAC) is sufficient.

### C. Keep PBKDF2 hashing, add a separate encrypted field alongside
Store both a hash (for validation) and an encrypted PIN (for display). This doubles storage and creates a consistency risk — if one is updated without the other, validation and display diverge. Since we can compare directly against the decrypted PIN, the hash is redundant.

## Consequences

### Positive
- Users can look up door codes they've created or synced — the primary use case for centralized code management
- Synced codes show the same PINs visible in the Z-Wave JS admin UI, eliminating the need to switch tools
- PIN validation during sync is faster (direct string compare vs. PBKDF2 iterations)
- Consistent encryption approach — PINs use the same Fernet infrastructure as all other secrets in the system
- Toggle UX matches the universal "password eye icon" pattern — zero learning curve

### Negative
- PINs are now reversibly encrypted rather than one-way hashed — a database breach with the encryption key exposes PINs in plaintext. Mitigation: the encryption key is already the single secret protecting MQTT passwords, HA tokens, and notification credentials. If it's compromised, door code PINs are the least of the problems.
- PIN is always present in the API response JSON — a browser dev-tools inspection reveals it even when the UI shows dots. This is acceptable for a self-hosted system where the user controls the browser.

### Risks
- If `SETTINGS_ENCRYPTION_KEY` is lost or rotated without data migration, all encrypted PINs become unrecoverable. This is the same risk that already exists for all other encrypted settings — mitigated by the key file persistence in the data volume.

## Files to Modify

### Backend
| File | Change |
|------|--------|
| `locks/models.py` | Rename `code_hash` → `encrypted_pin` |
| `locks/migrations/NNNN_*.py` | Rename column, migrate legacy hashes |
| `locks/serializers.py` | Add `pin` field to `DoorCodeSerializer` |
| `locks/use_cases/door_codes.py` | Replace `make_password()` with `SettingsEncryption.encrypt()` |
| `locks/use_cases/lock_config_sync.py` | Replace `make_password()`/`check_password()` with encrypt/decrypt |
| `locks/use_cases/code_validation.py` | Replace `check_password()` with decrypt + string compare |
| `locks/tests/test_door_codes_api.py` | Update `code_hash` references → `encrypted_pin` |
| `locks/tests/test_door_code_validation.py` | Update to use encrypted PINs |
| `locks/tests/test_lock_config_sync_api.py` | Update hash assertions → encryption assertions |

### Frontend
| File | Change |
|------|--------|
| `types/doorCode.ts` | Add `pin: string \| null` to `DoorCode` type |
| `features/doorCodes/components/DoorCodeCard.tsx` | Add eye icon toggle, show masked/revealed PIN |
| `features/doorCodes/components/DoorCodeCreateBasicsFields.tsx` | Remove "cannot view later" warning text |
| `features/doorCodes/components/LockConfigSyncCard.tsx` | Show PIN in sync results (masked/revealable) |

## Todos
- [ ] Backend: model rename + migration
- [ ] Backend: encryption in create/update/sync paths
- [ ] Backend: serializer `pin` field
- [ ] Backend: code validation decrypt path
- [ ] Backend: update all tests
- [ ] Frontend: `DoorCode` type update
- [ ] Frontend: eye icon toggle on `DoorCodeCard`
- [ ] Frontend: update create form help text
- [ ] Frontend: sync results PIN display
- [ ] Manual test: create code → verify PIN visible via toggle
- [ ] Manual test: sync codes → verify known PINs visible, unknown PINs show "unknown"
- [ ] Re-sync locks and re-create manual codes after migration
