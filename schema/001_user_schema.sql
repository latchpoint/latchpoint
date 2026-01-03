-- User and auth schema (PostgreSQL)
-- Extension prerequisites
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

-- Enum for allowed alarm states (used by code-state junction)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'alarm_state') THEN
        CREATE TYPE alarm_state AS ENUM (
            'disarmed',
            'armed_home',
            'armed_away',
            'armed_night',
            'armed_vacation',
            'armed_custom_bypass'
        );
    END IF;
END$$;

CREATE TABLE users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email citext NOT NULL UNIQUE,
    password_hash text NOT NULL,
    password_updated_at timestamptz NOT NULL DEFAULT now(),
    first_name text,
    last_name text,
    display_name text,
    timezone text DEFAULT 'UTC',
    locale text DEFAULT 'en',
    access_expires_at timestamptz,
    is_active boolean NOT NULL DEFAULT true,
    is_staff boolean NOT NULL DEFAULT false,
    is_superuser boolean NOT NULL DEFAULT false,
    onboarding_completed_at timestamptz,
    last_login_at timestamptz,
    failed_login_attempts integer NOT NULL DEFAULT 0 CHECK (failed_login_attempts >= 0),
    locked_until timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_users_last_login_at ON users (last_login_at);
CREATE INDEX idx_users_is_active ON users (is_active);

CREATE TABLE roles (
    id smallserial PRIMARY KEY,
    slug text NOT NULL UNIQUE,
    name text NOT NULL,
    description text
);

CREATE TABLE user_role_assignments (
    id bigserial PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id smallint NOT NULL REFERENCES roles(id) ON DELETE RESTRICT,
    assigned_by uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, role_id)
);
CREATE INDEX idx_user_role_assignments_role_id ON user_role_assignments (role_id);

CREATE TABLE user_codes (
    id bigserial PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash text NOT NULL,
    label text,
    code_type text NOT NULL CHECK (code_type IN ('permanent', 'temporary', 'one_time', 'service')),
    pin_length smallint NOT NULL CHECK (pin_length BETWEEN 4 AND 8),
    is_active boolean NOT NULL DEFAULT true,
    max_uses integer CHECK (max_uses IS NULL OR max_uses > 0),
    uses_count integer NOT NULL DEFAULT 0 CHECK (uses_count >= 0),
    start_at timestamptz,
    end_at timestamptz,
    days_of_week smallint CHECK (days_of_week BETWEEN 0 AND 127),
    window_start time,
    window_end time,
    last_used_at timestamptz,
    last_entry_point text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_user_codes_user_id ON user_codes (user_id);
CREATE INDEX idx_user_codes_active ON user_codes (is_active) WHERE is_active = true;
CREATE INDEX idx_user_codes_end_at ON user_codes (end_at) WHERE end_at IS NOT NULL;

CREATE TABLE user_code_allowed_states (
    id bigserial PRIMARY KEY,
    code_id bigint NOT NULL REFERENCES user_codes(id) ON DELETE CASCADE,
    state alarm_state NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (code_id, state)
);
CREATE INDEX idx_user_code_allowed_states_state ON user_code_allowed_states (state);

CREATE TABLE user_totp_devices (
    id bigserial PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    label text,
    secret_encrypted bytea NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    confirmed_at timestamptz,
    last_used_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_user_totp_devices_active ON user_totp_devices (user_id, is_active);

-- Seed roles
INSERT INTO roles (slug, name, description) VALUES
    ('admin', 'Admin', 'Full system control'),
    ('resident', 'Resident', 'Arm/disarm and manage own codes'),
    ('guest', 'Guest', 'Limited access via temporary codes'),
    ('service', 'Service', 'Scheduled service providers')
ON CONFLICT (slug) DO NOTHING;
