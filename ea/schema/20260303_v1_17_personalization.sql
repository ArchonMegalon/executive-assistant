BEGIN;

CREATE TABLE IF NOT EXISTS user_interest_profiles (
    profile_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    concept_key TEXT NOT NULL,
    weight NUMERIC NOT NULL DEFAULT 0,
    hard_dislike BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_key, principal_id, concept_key)
);

CREATE TABLE IF NOT EXISTS tenant_interest_defaults (
    default_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    concept_key TEXT NOT NULL,
    default_weight NUMERIC NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_key, concept_key)
);

CREATE TABLE IF NOT EXISTS ranking_explanations (
    explanation_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    item_ref TEXT NOT NULL,
    explanation_text TEXT NOT NULL,
    evidence_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS entities (
    entity_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_key, canonical_name, entity_type)
);

CREATE TABLE IF NOT EXISTS entity_aliases (
    alias_id SERIAL PRIMARY KEY,
    entity_id BIGINT NOT NULL REFERENCES entities(entity_id),
    alias TEXT NOT NULL,
    provenance TEXT,
    confidence NUMERIC NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (entity_id, alias)
);

CREATE TABLE IF NOT EXISTS ai_error_reviews (
    review_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    principal_id TEXT,
    item_ref TEXT,
    error_class TEXT NOT NULL,
    raw_reason_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS feedback_caps (
    cap_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    window_day DATE NOT NULL,
    count_total INT NOT NULL DEFAULT 0,
    count_negative INT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_key, principal_id, window_day)
);

CREATE TABLE IF NOT EXISTS anomaly_flags (
    anomaly_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    principal_id TEXT,
    anomaly_type TEXT NOT NULL,
    details_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_interest_profiles_principal ON user_interest_profiles(tenant_key, principal_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_ranking_explanations_principal ON ranking_explanations(tenant_key, principal_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_caps_window ON feedback_caps(tenant_key, principal_id, window_day);
CREATE INDEX IF NOT EXISTS idx_ai_error_reviews_tenant ON ai_error_reviews(tenant_key, created_at DESC);

COMMIT;
