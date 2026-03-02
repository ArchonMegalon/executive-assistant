BEGIN;

CREATE TABLE IF NOT EXISTS source_objects (
    source_object_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    connector_id TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    external_object_id TEXT NOT NULL,
    file_class TEXT,
    etag TEXT,
    content_fingerprint TEXT,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_key, connector_id, external_object_id)
);

CREATE TABLE IF NOT EXISTS source_permissions (
    source_permission_id SERIAL PRIMARY KEY,
    source_object_id BIGINT NOT NULL REFERENCES source_objects(source_object_id),
    principal_id TEXT NOT NULL,
    permission_level TEXT NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS extraction_runs (
    extraction_run_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    source_object_id BIGINT NOT NULL REFERENCES source_objects(source_object_id),
    run_status TEXT NOT NULL,
    error_code TEXT,
    cache_mode TEXT NOT NULL DEFAULT 'ephemeral',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS extracted_documents (
    extracted_document_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    source_object_id BIGINT NOT NULL REFERENCES source_objects(source_object_id),
    normalized_text TEXT,
    metadata_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS retrieval_chunks (
    chunk_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    extracted_document_id BIGINT NOT NULL REFERENCES extracted_documents(extracted_document_id),
    chunk_index INT NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding_ref TEXT,
    provenance_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS retrieval_acl_rules (
    retrieval_acl_rule_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    source_object_id BIGINT NOT NULL REFERENCES source_objects(source_object_id),
    policy TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS connector_cursors (
    cursor_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    connector_id TEXT NOT NULL,
    cursor_value TEXT,
    last_sync_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_key, connector_id)
);

CREATE TABLE IF NOT EXISTS retrieval_audit_events (
    retrieval_event_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    event_type TEXT NOT NULL,
    correlation_id TEXT,
    details_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS extraction_cache_jobs (
    extraction_cache_job_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    source_object_id BIGINT NOT NULL REFERENCES source_objects(source_object_id),
    cache_status TEXT NOT NULL,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_source_objects_tenant_connector ON source_objects(tenant_key, connector_id);
CREATE INDEX IF NOT EXISTS idx_extraction_runs_status ON extraction_runs(tenant_key, run_status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_retrieval_chunks_doc ON retrieval_chunks(extracted_document_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_retrieval_acl_rules_principal ON retrieval_acl_rules(tenant_key, principal_id);
CREATE INDEX IF NOT EXISTS idx_connector_cursors_sync ON connector_cursors(tenant_key, connector_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_retrieval_audit_corr ON retrieval_audit_events(correlation_id, created_at DESC);

COMMIT;
