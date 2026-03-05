BEGIN;

CREATE TABLE IF NOT EXISTS commitments (
    commitment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_key TEXT NOT NULL,
    commitment_key TEXT NOT NULL,
    domain TEXT NOT NULL DEFAULT 'general',
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_key, commitment_key)
);
CREATE INDEX IF NOT EXISTS idx_commitments_lookup
    ON commitments(tenant_key, domain, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_key TEXT NOT NULL,
    session_id UUID REFERENCES execution_sessions(session_id) ON DELETE SET NULL,
    commitment_key TEXT,
    artifact_type TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    content_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_artifacts_lookup
    ON artifacts(tenant_key, artifact_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_artifacts_commitment
    ON artifacts(tenant_key, commitment_key, created_at DESC);

CREATE TABLE IF NOT EXISTS followups (
    followup_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_key TEXT NOT NULL,
    commitment_key TEXT NOT NULL,
    artifact_id UUID REFERENCES artifacts(artifact_id) ON DELETE SET NULL,
    due_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'open',
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_followups_lookup
    ON followups(tenant_key, status, due_at NULLS LAST, created_at DESC);

CREATE TABLE IF NOT EXISTS decision_windows (
    decision_window_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_key TEXT NOT NULL,
    commitment_key TEXT NOT NULL,
    window_label TEXT NOT NULL DEFAULT '',
    opens_at TIMESTAMPTZ,
    closes_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_decision_windows_lookup
    ON decision_windows(tenant_key, status, closes_at NULLS LAST, created_at DESC);

COMMIT;
