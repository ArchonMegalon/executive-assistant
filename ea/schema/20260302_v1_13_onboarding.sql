BEGIN;

CREATE TABLE IF NOT EXISTS tenant_invites (
    invite_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    invite_token_hash VARCHAR(64) NOT NULL UNIQUE,
    invite_status TEXT NOT NULL DEFAULT 'invited',
    expires_at TIMESTAMPTZ NOT NULL,
    created_by TEXT,
    consumed_by_principal_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    consumed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS onboarding_sessions (
    session_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    invite_id BIGINT REFERENCES tenant_invites(invite_id),
    status TEXT NOT NULL DEFAULT 'invited',
    current_step TEXT,
    principal_id BIGINT,
    channel_binding_id BIGINT,
    locale TEXT,
    timezone TEXT,
    metadata_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS principals (
    principal_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    external_user_id TEXT NOT NULL,
    display_name TEXT,
    locale TEXT,
    timezone TEXT,
    principal_status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_key, external_user_id)
);

CREATE TABLE IF NOT EXISTS channel_bindings (
    binding_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    principal_id BIGINT NOT NULL REFERENCES principals(principal_id),
    channel_type TEXT NOT NULL,
    channel_user_id TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    quiet_hours_json JSONB,
    is_primary BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (channel_type, channel_user_id),
    UNIQUE (channel_type, chat_id)
);

CREATE TABLE IF NOT EXISTS oauth_connections (
    oauth_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    principal_id BIGINT NOT NULL REFERENCES principals(principal_id),
    provider TEXT NOT NULL,
    scope_inventory TEXT[] NOT NULL DEFAULT '{}',
    oauth_status TEXT NOT NULL DEFAULT 'oauth_partial',
    secret_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_key, principal_id, provider)
);

CREATE TABLE IF NOT EXISTS source_connections (
    source_connection_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    principal_id BIGINT NOT NULL REFERENCES principals(principal_id),
    connector_type TEXT NOT NULL,
    connector_name TEXT NOT NULL,
    connector_status TEXT NOT NULL DEFAULT 'sources_partial',
    network_mode TEXT NOT NULL DEFAULT 'hosted',
    endpoint_url TEXT,
    secret_ref TEXT,
    capability_flags JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS source_test_runs (
    source_test_run_id SERIAL PRIMARY KEY,
    source_connection_id BIGINT REFERENCES source_connections(source_connection_id),
    tenant_key TEXT NOT NULL,
    result_status TEXT NOT NULL,
    failure_code TEXT,
    redacted_details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tenant_provision_jobs (
    provision_job_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    session_id BIGINT REFERENCES onboarding_sessions(session_id),
    job_type TEXT NOT NULL,
    job_status TEXT NOT NULL,
    attempt_count INT NOT NULL DEFAULT 0,
    correlation_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS onboarding_audit_events (
    event_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    session_id BIGINT REFERENCES onboarding_sessions(session_id),
    principal_id BIGINT,
    event_type TEXT NOT NULL,
    event_status TEXT NOT NULL,
    correlation_id TEXT,
    redacted_payload_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS connector_network_modes (
    connector_type TEXT NOT NULL,
    tenant_key TEXT NOT NULL,
    network_mode TEXT NOT NULL DEFAULT 'hosted',
    allow_private_targets BOOLEAN NOT NULL DEFAULT FALSE,
    allow_metadata_targets BOOLEAN NOT NULL DEFAULT FALSE,
    allowed_host_patterns TEXT[] NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (connector_type, tenant_key)
);

CREATE INDEX IF NOT EXISTS idx_tenant_invites_status ON tenant_invites (invite_status);
CREATE INDEX IF NOT EXISTS idx_tenant_invites_expires ON tenant_invites (expires_at);
CREATE INDEX IF NOT EXISTS idx_onboarding_sessions_status ON onboarding_sessions (status);
CREATE INDEX IF NOT EXISTS idx_onboarding_sessions_tenant ON onboarding_sessions (tenant_key);
CREATE INDEX IF NOT EXISTS idx_channel_bindings_principal ON channel_bindings (principal_id);
CREATE INDEX IF NOT EXISTS idx_oauth_connections_status ON oauth_connections (oauth_status);
CREATE INDEX IF NOT EXISTS idx_source_connections_tenant_status ON source_connections (tenant_key, connector_status);
CREATE INDEX IF NOT EXISTS idx_source_test_runs_tenant ON source_test_runs (tenant_key, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tenant_provision_jobs_status ON tenant_provision_jobs (job_status);
CREATE INDEX IF NOT EXISTS idx_onboarding_audit_events_session ON onboarding_audit_events (session_id, created_at DESC);

COMMIT;
