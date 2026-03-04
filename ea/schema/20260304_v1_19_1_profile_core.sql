BEGIN;

CREATE TABLE IF NOT EXISTS profile_context_state (
    tenant TEXT NOT NULL,
    person_id TEXT NOT NULL,
    stable_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    situational_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    learned_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant, person_id)
);

CREATE INDEX IF NOT EXISTS idx_profile_context_state_updated
    ON profile_context_state(tenant, person_id, updated_at DESC);

COMMIT;
