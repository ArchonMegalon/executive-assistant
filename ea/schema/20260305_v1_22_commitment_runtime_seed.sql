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
ALTER TABLE commitments ADD COLUMN IF NOT EXISTS tenant_key TEXT;
ALTER TABLE commitments ADD COLUMN IF NOT EXISTS tenant TEXT;
ALTER TABLE commitments ADD COLUMN IF NOT EXISTS commitment_id UUID;
ALTER TABLE commitments ADD COLUMN IF NOT EXISTS commitment_key TEXT;
ALTER TABLE commitments ADD COLUMN IF NOT EXISTS domain TEXT NOT NULL DEFAULT 'general';
ALTER TABLE commitments ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT '';
ALTER TABLE commitments ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'open';
ALTER TABLE commitments ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE commitments ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE commitments ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
UPDATE commitments SET tenant_key = COALESCE(NULLIF(tenant_key, ''), tenant) WHERE tenant_key IS NULL OR tenant_key = '';
UPDATE commitments SET tenant_key = 'unknown' WHERE tenant_key IS NULL OR tenant_key = '';
UPDATE commitments SET commitment_id = COALESCE(commitment_id, gen_random_uuid());
UPDATE commitments SET commitment_key = COALESCE(NULLIF(commitment_key, ''), 'legacy:' || substr(md5(gen_random_uuid()::text), 1, 12))
WHERE commitment_key IS NULL OR commitment_key = '';
ALTER TABLE commitments ALTER COLUMN tenant_key SET NOT NULL;
ALTER TABLE commitments ALTER COLUMN commitment_id SET NOT NULL;
ALTER TABLE commitments ALTER COLUMN commitment_id SET DEFAULT gen_random_uuid();
CREATE UNIQUE INDEX IF NOT EXISTS uq_commitments_commitment_id ON commitments(commitment_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_commitments_tenant_key_commitment_key ON commitments(tenant_key, commitment_key);
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
ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS tenant_key TEXT;
ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS tenant TEXT;
ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS artifact_id UUID;
ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS session_id UUID;
ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS commitment_key TEXT;
ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS artifact_type TEXT;
ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS summary TEXT;
ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS content_json JSONB;
ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
UPDATE artifacts SET tenant_key = COALESCE(NULLIF(tenant_key, ''), tenant) WHERE tenant_key IS NULL OR tenant_key = '';
UPDATE artifacts SET tenant_key = 'unknown' WHERE tenant_key IS NULL OR tenant_key = '';
UPDATE artifacts SET artifact_id = COALESCE(artifact_id, gen_random_uuid());
UPDATE artifacts SET artifact_type = COALESCE(NULLIF(artifact_type, ''), 'legacy_artifact')
WHERE artifact_type IS NULL OR artifact_type = '';
UPDATE artifacts SET summary = COALESCE(summary, '');
UPDATE artifacts SET content_json = COALESCE(content_json, '{}'::jsonb);
ALTER TABLE artifacts ALTER COLUMN tenant_key SET NOT NULL;
ALTER TABLE artifacts ALTER COLUMN artifact_id SET NOT NULL;
ALTER TABLE artifacts ALTER COLUMN artifact_id SET DEFAULT gen_random_uuid();
ALTER TABLE artifacts ALTER COLUMN artifact_type SET NOT NULL;
ALTER TABLE artifacts ALTER COLUMN artifact_type SET DEFAULT 'legacy_artifact';
ALTER TABLE artifacts ALTER COLUMN summary SET NOT NULL;
ALTER TABLE artifacts ALTER COLUMN summary SET DEFAULT '';
ALTER TABLE artifacts ALTER COLUMN content_json SET NOT NULL;
ALTER TABLE artifacts ALTER COLUMN content_json SET DEFAULT '{}'::jsonb;
CREATE UNIQUE INDEX IF NOT EXISTS uq_artifacts_artifact_id ON artifacts(artifact_id);
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
ALTER TABLE followups ADD COLUMN IF NOT EXISTS tenant_key TEXT;
ALTER TABLE followups ADD COLUMN IF NOT EXISTS tenant TEXT;
ALTER TABLE followups ADD COLUMN IF NOT EXISTS followup_id UUID;
ALTER TABLE followups ADD COLUMN IF NOT EXISTS commitment_key TEXT;
ALTER TABLE followups ADD COLUMN IF NOT EXISTS artifact_id UUID;
ALTER TABLE followups ADD COLUMN IF NOT EXISTS due_at TIMESTAMPTZ;
ALTER TABLE followups ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'open';
ALTER TABLE followups ADD COLUMN IF NOT EXISTS notes TEXT NOT NULL DEFAULT '';
ALTER TABLE followups ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE followups ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
UPDATE followups SET tenant_key = COALESCE(NULLIF(tenant_key, ''), tenant) WHERE tenant_key IS NULL OR tenant_key = '';
UPDATE followups SET tenant_key = 'unknown' WHERE tenant_key IS NULL OR tenant_key = '';
UPDATE followups SET followup_id = COALESCE(followup_id, gen_random_uuid());
UPDATE followups SET commitment_key = COALESCE(NULLIF(commitment_key, ''), 'legacy:' || substr(md5(gen_random_uuid()::text), 1, 12))
WHERE commitment_key IS NULL OR commitment_key = '';
ALTER TABLE followups ALTER COLUMN tenant_key SET NOT NULL;
ALTER TABLE followups ALTER COLUMN followup_id SET NOT NULL;
ALTER TABLE followups ALTER COLUMN followup_id SET DEFAULT gen_random_uuid();
ALTER TABLE followups ALTER COLUMN commitment_key SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_followups_followup_id ON followups(followup_id);
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
ALTER TABLE decision_windows ADD COLUMN IF NOT EXISTS tenant_key TEXT;
ALTER TABLE decision_windows ADD COLUMN IF NOT EXISTS tenant TEXT;
ALTER TABLE decision_windows ADD COLUMN IF NOT EXISTS decision_window_id UUID;
ALTER TABLE decision_windows ADD COLUMN IF NOT EXISTS commitment_key TEXT;
ALTER TABLE decision_windows ADD COLUMN IF NOT EXISTS window_label TEXT NOT NULL DEFAULT '';
ALTER TABLE decision_windows ADD COLUMN IF NOT EXISTS opens_at TIMESTAMPTZ;
ALTER TABLE decision_windows ADD COLUMN IF NOT EXISTS closes_at TIMESTAMPTZ;
ALTER TABLE decision_windows ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'open';
ALTER TABLE decision_windows ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE decision_windows ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
UPDATE decision_windows SET tenant_key = COALESCE(NULLIF(tenant_key, ''), tenant) WHERE tenant_key IS NULL OR tenant_key = '';
UPDATE decision_windows SET tenant_key = 'unknown' WHERE tenant_key IS NULL OR tenant_key = '';
UPDATE decision_windows SET decision_window_id = COALESCE(decision_window_id, gen_random_uuid());
UPDATE decision_windows
SET commitment_key = COALESCE(NULLIF(commitment_key, ''), 'legacy:' || substr(md5(gen_random_uuid()::text), 1, 12))
WHERE commitment_key IS NULL OR commitment_key = '';
ALTER TABLE decision_windows ALTER COLUMN tenant_key SET NOT NULL;
ALTER TABLE decision_windows ALTER COLUMN decision_window_id SET NOT NULL;
ALTER TABLE decision_windows ALTER COLUMN decision_window_id SET DEFAULT gen_random_uuid();
ALTER TABLE decision_windows ALTER COLUMN commitment_key SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_decision_windows_id ON decision_windows(decision_window_id);
CREATE INDEX IF NOT EXISTS idx_decision_windows_lookup
    ON decision_windows(tenant_key, status, closes_at NULLS LAST, created_at DESC);

COMMIT;
