BEGIN;

CREATE TABLE IF NOT EXISTS intelligence_snapshots (
    id BIGSERIAL PRIMARY KEY,
    tenant TEXT NOT NULL,
    person_id TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'briefing_compose',
    compose_mode TEXT NOT NULL DEFAULT '',
    snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_intelligence_snapshots_lookup
    ON intelligence_snapshots(tenant, person_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_intelligence_snapshots_source
    ON intelligence_snapshots(source, created_at DESC);

COMMIT;
