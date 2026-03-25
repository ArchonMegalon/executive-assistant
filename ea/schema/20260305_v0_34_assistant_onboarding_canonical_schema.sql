-- Canonical Postgres schema for assistant onboarding and message ingestion
-- This file is an implementation scaffold for phase-2 persistence migration.

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id TEXT PRIMARY KEY,
    tenant_name TEXT NOT NULL,
    tenant_slug TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS principals (
    principal_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    display_name TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    principal_type TEXT NOT NULL DEFAULT 'user',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS identity_accounts (
    identity_account_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL REFERENCES principals(principal_id) ON DELETE CASCADE,
    provider_key TEXT NOT NULL,
    external_subject TEXT NOT NULL,
    external_username TEXT NOT NULL DEFAULT '',
    profile_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (provider_key, external_subject)
);

CREATE TABLE IF NOT EXISTS channel_accounts (
    channel_account_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    principal_id TEXT NOT NULL REFERENCES principals(principal_id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    identity_account_id TEXT NOT NULL REFERENCES identity_accounts(identity_account_id) ON DELETE RESTRICT,
    external_ref TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'staged',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (principal_id, channel, external_ref)
);

CREATE TABLE IF NOT EXISTS channel_bindings (
    channel_binding_id TEXT PRIMARY KEY,
    channel_account_id TEXT NOT NULL REFERENCES channel_accounts(channel_account_id) ON DELETE CASCADE,
    connector_name TEXT NOT NULL,
    binding_external_ref TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (channel_account_id, connector_name, binding_external_ref)
);

CREATE TABLE IF NOT EXISTS channel_scope_grants (
    scope_grant_id TEXT PRIMARY KEY,
    channel_binding_id TEXT NOT NULL REFERENCES channel_bindings(channel_binding_id) ON DELETE CASCADE,
    scope_name TEXT NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    granted_by JSONB NOT NULL DEFAULT '{}'::jsonb,
    scope_metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS oauth_refresh_token_refs (
    oauth_refresh_token_ref_id TEXT PRIMARY KEY,
    channel_binding_id TEXT NOT NULL REFERENCES channel_bindings(channel_binding_id) ON DELETE CASCADE,
    provider_key TEXT NOT NULL,
    encrypted_token_ref TEXT NOT NULL,
    rotation_count INT NOT NULL DEFAULT 0,
    last_refreshed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    token_state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (channel_binding_id, provider_key)
);

CREATE TABLE IF NOT EXISTS consent_bundles (
    consent_bundle_id TEXT PRIMARY KEY,
    channel_binding_id TEXT NOT NULL REFERENCES channel_bindings(channel_binding_id) ON DELETE CASCADE,
    bundle_key TEXT NOT NULL,
    granted_scopes_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    requested_scopes_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    consent_url TEXT NOT NULL DEFAULT '',
    consent_version TEXT NOT NULL DEFAULT '',
    granted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (channel_binding_id, bundle_key)
);

CREATE TABLE IF NOT EXISTS consent_events (
    consent_event_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL REFERENCES principals(principal_id) ON DELETE CASCADE,
    channel_account_id TEXT NOT NULL REFERENCES channel_accounts(channel_account_id) ON DELETE CASCADE,
    event_kind TEXT NOT NULL,
    event_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    event_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    principal_id TEXT NOT NULL REFERENCES principals(principal_id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    external_thread_ref TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    participants_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, principal_id, channel, external_thread_ref)
);

CREATE TABLE IF NOT EXISTS conversation_participants (
    conversation_participant_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    identity_account_id TEXT NOT NULL REFERENCES identity_accounts(identity_account_id) ON DELETE RESTRICT,
    channel_display_name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'participant',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    sender_account_id TEXT NOT NULL REFERENCES identity_accounts(identity_account_id) ON DELETE RESTRICT,
    sender_handle TEXT NOT NULL DEFAULT '',
    external_message_ref TEXT NOT NULL,
    sent_at TIMESTAMPTZ,
    body_text TEXT NOT NULL DEFAULT '',
    body_metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (conversation_id, external_message_ref)
);

CREATE TABLE IF NOT EXISTS message_parts (
    message_part_id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES messages(message_id) ON DELETE CASCADE,
    part_sequence INT NOT NULL DEFAULT 0,
    part_type TEXT NOT NULL DEFAULT 'text',
    part_payload TEXT NOT NULL DEFAULT '',
    part_metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS attachments (
    attachment_id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES messages(message_id) ON DELETE CASCADE,
    storage_uri TEXT NOT NULL DEFAULT '',
    mime_type TEXT NOT NULL DEFAULT '',
    filename TEXT NOT NULL DEFAULT '',
    byte_size BIGINT NOT NULL DEFAULT 0,
    attachment_metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS message_source_receipts (
    message_source_receipt_id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES messages(message_id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_uri TEXT NOT NULL DEFAULT '',
    source_timestamp TIMESTAMPTZ,
    ingestion_run_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (message_id, channel, source_id)
);

CREATE TABLE IF NOT EXISTS history_import_jobs (
    history_import_job_id TEXT PRIMARY KEY,
    channel_account_id TEXT NOT NULL REFERENCES channel_accounts(channel_account_id) ON DELETE CASCADE,
    import_path TEXT NOT NULL,
    import_status TEXT NOT NULL DEFAULT 'planned',
    source_kind TEXT NOT NULL DEFAULT 'unknown',
    import_plan_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS history_import_chunks (
    history_import_chunk_id TEXT PRIMARY KEY,
    history_import_job_id TEXT NOT NULL REFERENCES history_import_jobs(history_import_job_id) ON DELETE CASCADE,
    chunk_no INT NOT NULL DEFAULT 0,
    chunk_status TEXT NOT NULL DEFAULT 'planned',
    batch_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    message_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sync_cursors (
    sync_cursor_id TEXT PRIMARY KEY,
    channel_account_id TEXT NOT NULL REFERENCES channel_accounts(channel_account_id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    cursor_name TEXT NOT NULL,
    cursor_value TEXT NOT NULL DEFAULT '',
    cursor_metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (channel_account_id, channel, cursor_name)
);

CREATE TABLE IF NOT EXISTS channel_checkpoints (
    channel_checkpoint_id TEXT PRIMARY KEY,
    channel_account_id TEXT NOT NULL REFERENCES channel_accounts(channel_account_id) ON DELETE CASCADE,
    checkpoint_key TEXT NOT NULL,
    checkpoint_value TEXT NOT NULL DEFAULT '',
    checkpoint_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (channel_account_id, checkpoint_key)
);

CREATE TABLE IF NOT EXISTS channel_health_events (
    channel_health_event_id TEXT PRIMARY KEY,
    channel_account_id TEXT NOT NULL REFERENCES channel_accounts(channel_account_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL,
    detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS import_verification_events (
    import_verification_event_id TEXT PRIMARY KEY,
    history_import_job_id TEXT NOT NULL REFERENCES history_import_jobs(history_import_job_id) ON DELETE CASCADE,
    verified_by TEXT NOT NULL,
    verification_status TEXT NOT NULL DEFAULT 'pending',
    result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    verified_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
