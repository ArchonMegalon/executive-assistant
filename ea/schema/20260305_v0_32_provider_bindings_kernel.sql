-- Provider-binding kernel baseline
-- Stores principal-scoped provider routing and probe state.

CREATE TABLE IF NOT EXISTS provider_bindings (
    binding_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    provider_key TEXT NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL,
    probe_state TEXT NOT NULL,
    probe_details_json JSONB NOT NULL,
    scope_json JSONB NOT NULL,
    auth_metadata_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_provider_bindings_principal_provider
ON provider_bindings(principal_id, provider_key, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_provider_bindings_principal_updated
ON provider_bindings(principal_id, updated_at DESC);
