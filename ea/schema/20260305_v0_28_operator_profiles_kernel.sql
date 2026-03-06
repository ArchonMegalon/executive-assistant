CREATE TABLE IF NOT EXISTS operator_profiles (
    operator_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    roles_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    skill_tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    trust_tier TEXT NOT NULL DEFAULT 'standard',
    status TEXT NOT NULL DEFAULT 'active',
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_operator_profiles_principal_status
ON operator_profiles(principal_id, status, updated_at DESC);
