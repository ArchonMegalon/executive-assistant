BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS travel_place_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant TEXT NOT NULL,
    person_id TEXT NOT NULL,
    place_key TEXT NOT NULL,
    city TEXT,
    country TEXT,
    lat DOUBLE PRECISION,
    lon DOUBLE PRECISION,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    seen_count INT NOT NULL DEFAULT 1,
    UNIQUE (tenant, person_id, place_key)
);
CREATE INDEX IF NOT EXISTS idx_travel_place_history_recent
    ON travel_place_history(tenant, person_id, last_seen DESC);

CREATE TABLE IF NOT EXISTS travel_video_specs (
    spec_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant TEXT NOT NULL,
    person_id TEXT NOT NULL,
    date_key DATE NOT NULL,
    mode TEXT NOT NULL,
    orientation TEXT NOT NULL DEFAULT 'portrait',
    duration_target_sec INT NOT NULL DEFAULT 20,
    route_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    markers_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    signal_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    cache_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant, person_id, date_key, cache_key)
);
CREATE INDEX IF NOT EXISTS idx_travel_video_specs_poll
    ON travel_video_specs(tenant, person_id, date_key, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_travel_video_specs_cache
    ON travel_video_specs(tenant, cache_key);

CREATE TABLE IF NOT EXISTS avomap_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    spec_id UUID NOT NULL REFERENCES travel_video_specs(spec_id) ON DELETE CASCADE,
    tenant TEXT NOT NULL,
    workflow_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    external_job_id TEXT,
    dedupe_key TEXT,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant, dedupe_key)
);
CREATE INDEX IF NOT EXISTS idx_avomap_jobs_poll
    ON avomap_jobs(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS avomap_assets (
    asset_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    spec_id UUID NOT NULL REFERENCES travel_video_specs(spec_id) ON DELETE CASCADE,
    tenant TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    object_ref TEXT NOT NULL,
    mime_type TEXT NOT NULL DEFAULT 'video/mp4',
    duration_sec INT,
    external_id TEXT,
    status TEXT NOT NULL DEFAULT 'ready',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant, cache_key),
    UNIQUE (external_id)
);
CREATE INDEX IF NOT EXISTS idx_avomap_assets_tenant_created
    ON avomap_assets(tenant, created_at DESC);

CREATE TABLE IF NOT EXISTS avomap_credit_ledger (
    id BIGSERIAL PRIMARY KEY,
    tenant TEXT NOT NULL,
    person_id TEXT NOT NULL,
    date_key DATE NOT NULL,
    renders_used INT NOT NULL DEFAULT 0,
    renders_cached INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant, person_id, date_key)
);
CREATE INDEX IF NOT EXISTS idx_avomap_credit_ledger_tenant_day
    ON avomap_credit_ledger(tenant, date_key);

COMMIT;
