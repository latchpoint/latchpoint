# User Database Schema Plan

Planning notes for the core user/auth schema to support the alarm system (roles, codes, onboarding, security). Target DB: PostgreSQL; Django will use a custom user model (email as username).

## Goals & Scope
- Single source of truth for user identity, auth state, and authorization roles.
- Store only necessary PII; enforce uniqueness and integrity constraints in DB.
- Support permanent and time-bound codes with auditing and lockout controls.
- Ready for optional 2FA (TOTP) and notification preferences without schema churn.
- Compatible with HA/automation auditing (who did what, when, via which code).

## Entity Overview
- `users` — primary identity; holds login credentials and status.
- `roles` — fixed role catalog (admin, resident, guest, service).
- `user_role_assignments` — user-to-role mapping (allows future multi-role).
- `user_codes` — per-user alarm codes (permanent/temporary/one-time).
- `user_code_allowed_states` — junction for which alarm states a code can operate.
- `user_totp_devices` — optional TOTP factors per user.

## Tables & Columns

### users
- `id uuid pk`
- `email citext unique not null` — canonical lower-case.
- `password_hash text not null` — Argon2/bcrypt; store verifier only.
- `password_updated_at timestamptz not null default now()` — rotation/audit.
- `first_name text`, `last_name text`, `display_name text`
- `timezone text default 'UTC'`, `locale text default 'en'`
- `access_expires_at timestamptz` — optional account-level expiry (service/guest).
- `is_active bool default true` — soft-disable login.
- `is_staff bool default false`, `is_superuser bool default false`
- `onboarding_completed_at timestamptz`, `last_login_at timestamptz`
- `failed_login_attempts int default 0`, `locked_until timestamptz` — rate limit/lockout.
- `created_at timestamptz not null default now()`, `updated_at timestamptz not null default now()`

Indexes/constraints:
- `unique(email)`
- `index(last_login_at)`, `index(is_active)` for admin filtering.
- Check: `failed_login_attempts >= 0`.

### roles
- `id smallserial pk`
- `slug text unique not null` — `admin|resident|guest|service`.
- `name text not null`
- `description text`

Seed rows on migration to lock canonical slugs.

### user_role_assignments
- `id bigserial pk`
- `user_id uuid fk -> users(id) on delete cascade`
- `role_id smallint fk -> roles(id) on delete restrict`
- `assigned_by uuid fk -> users(id) null` — who granted.
- `created_at timestamptz not null default now()`

Indexes/constraints:
- `unique(user_id, role_id)` — prevent duplicates.
- `index(role_id)` — filter users by role quickly.

### user_codes
- `id bigserial pk`
- `user_id uuid fk -> users(id) on delete cascade`
- `code_hash text not null` — hashed PIN (Argon2id + pepper).
- `label text` — e.g., "Front door", "Dog walker".
- `code_type text not null` — `permanent|temporary|one_time|service`.
- `pin_length smallint not null` — enforce 4–8 digits.
- `is_active bool default true`
- `max_uses int` — null = unlimited.
- `uses_count int default 0`
- `start_at timestamptz`, `end_at timestamptz` — validity window.
- `days_of_week smallint` — bitmask 0–127 for allowed days.
- `window_start time`, `window_end time` — daily time window (local to user TZ).
- `last_used_at timestamptz`, `last_entry_point text`
- `created_at timestamptz not null default now()`, `updated_at timestamptz not null default now()`

Indexes/constraints:
- `index(user_id)`
- Partial indexes for enforcement/query speed:
  - `WHERE is_active = true`
  - `WHERE end_at IS NOT NULL`
- Checks:
  - `pin_length BETWEEN 4 AND 8`
  - `days_of_week BETWEEN 0 AND 127`
  - `uses_count >= 0`

### user_code_allowed_states
- `id bigserial pk`
- `code_id bigint fk -> user_codes(id) on delete cascade`
- `state enum/alarm_state not null` — constrained to known alarm states.
- `created_at timestamptz not null default now()`

Indexes/constraints:
- `unique(code_id, state)`
- `index(state)`

### user_totp_devices (optional 2FA)
- `id bigserial pk`
- `user_id uuid fk -> users(id) on delete cascade`
- `label text` — e.g., "iPhone", "YubiKey OTP".
- `secret_encrypted bytea not null` — envelope-encrypted TOTP secret.
- `is_active bool default true`, `confirmed_at timestamptz`
- `last_used_at timestamptz`
- `created_at timestamptz not null default now()`, `updated_at timestamptz not null default now()`

Indexes:
- `index(user_id, is_active)`

## Relationships & Behavior
- Users can have multiple roles; UI may restrict to one, but schema allows growth.
- Codes are per-user; deletion of a user cascades to codes; deactivation preferred to maintain audit integrity.
- TOTP devices optional; login flow should check `is_active` and `confirmed_at`.
- Code validation runs through hashed comparison + validity window + allowed states and counts.

## Security Notes
- Use `citext` for case-insensitive emails; enforce lower-case in app layer too.
- Hash passwords with Django’s Argon2; store pepper in environment.
- Hash codes separately from passwords; never store clear-text PINs.
- Encrypt TOTP secrets with application-level key management (env + key rotation plan).
- Audit on code use and role assignment will live in the broader audit log (separate table).

## Migration Outline (Django)
1) Create custom user model (email as `USERNAME_FIELD`), apply `users` table migration.
2) Create `roles` + seed canonical slugs.
3) Create `user_role_assignments` with unique constraint.
4) Create `user_codes` with indexes and checks.
5) Create `user_totp_devices` (may be delayed until 2FA feature).
6) Backfill admin during onboarding wizard (first-run flow).

## Decisions & Open Questions
- Multiple active codes per user: yes. Schema already supports this; app logic should enforce per-code validity and limits at runtime.
- Service/guest expiry meaning: optional `access_expires_at` on `users` disables the account after a date/time even if a code’s window is still valid. Recommended to set both `access_expires_at` and per-code `end_at` for service/guest users; runtime should reject login/code use when the account is expired.
- `allowed_states` is normalized via `user_code_allowed_states` to enforce valid states and simplify querying/filtering.
