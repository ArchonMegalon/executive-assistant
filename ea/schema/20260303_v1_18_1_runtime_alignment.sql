BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS tg_updates (
    tenant TEXT NOT NULL,
    update_id BIGINT NOT NULL,
    payload_json JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    attempt_count INT NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant, update_id)
);

CREATE TABLE IF NOT EXISTS tg_outbox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant TEXT NOT NULL,
    chat_id BIGINT NOT NULL,
    payload_json JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    attempt_count INT NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_error TEXT,
    idempotency_key TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS typed_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant TEXT NOT NULL,
    action_type TEXT NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_consumed BOOLEAN NOT NULL DEFAULT FALSE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS template_registry (
    tenant TEXT NOT NULL,
    key TEXT NOT NULL,
    provider TEXT NOT NULL,
    template_id TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    version INT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant, key, provider)
);

CREATE TABLE IF NOT EXISTS external_approvals (
    approval_id BIGSERIAL PRIMARY KEY,
    tenant TEXT NOT NULL,
    internal_ref_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_request_id TEXT,
    status TEXT NOT NULL DEFAULT 'parked',
    remote_url TEXT,
    decision_payload_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant, internal_ref_id, provider)
);

CREATE INDEX IF NOT EXISTS idx_tg_updates_ready ON tg_updates(status, next_attempt_at);
ALTER TABLE IF EXISTS tg_updates ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE IF EXISTS tg_updates ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
CREATE INDEX IF NOT EXISTS idx_tg_outbox_ready ON tg_outbox(status, next_attempt_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tg_outbox_idem ON tg_outbox(tenant, idempotency_key) WHERE idempotency_key IS NOT NULL;
ALTER TABLE IF EXISTS tg_outbox ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE IF EXISTS tg_outbox ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE IF EXISTS tg_outbox ALTER COLUMN id SET DEFAULT gen_random_uuid();
CREATE INDEX IF NOT EXISTS idx_typed_actions_ready ON typed_actions(tenant, action_type, is_consumed, expires_at);
CREATE INDEX IF NOT EXISTS idx_template_registry_lookup ON template_registry(key, is_active, version DESC);
CREATE INDEX IF NOT EXISTS idx_external_approvals_status ON external_approvals(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS external_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant TEXT NOT NULL,
    source TEXT NOT NULL,
    event_type TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'queued',
    attempt_count INT NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_error TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant, source, dedupe_key)
);
CREATE INDEX IF NOT EXISTS idx_ext_events_poll ON external_events(status, next_attempt_at);

CREATE TABLE IF NOT EXISTS delivery_sessions (
    session_id SERIAL PRIMARY KEY,
    correlation_id TEXT,
    chat_id TEXT,
    initial_message_id TEXT,
    mode TEXT,
    status TEXT,
    enhancement_deadline_ts TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_delivery_sessions_corr ON delivery_sessions(correlation_id);

CREATE TABLE IF NOT EXISTS location_events (
    id BIGSERIAL PRIMARY KEY,
    tenant TEXT NOT NULL,
    lat DOUBLE PRECISION,
    lon DOUBLE PRECISION,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_location_events_tenant_id ON location_events(tenant, id DESC);

CREATE TABLE IF NOT EXISTS location_cursors (
    tenant TEXT PRIMARY KEY,
    last_id BIGINT NOT NULL DEFAULT 0,
    updated_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shopping_list (
    id BIGSERIAL PRIMARY KEY,
    tenant TEXT NOT NULL,
    item TEXT NOT NULL,
    checked BOOLEAN NOT NULL DEFAULT FALSE,
    raw JSONB,
    updated_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_shopping_list_tenant_checked ON shopping_list(tenant, checked, updated_ts DESC);

CREATE TABLE IF NOT EXISTS location_notifications (
    id BIGSERIAL PRIMARY KEY,
    tenant TEXT NOT NULL,
    place_id TEXT NOT NULL,
    suggestion_key TEXT NOT NULL,
    payload JSONB,
    sent_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_location_notifications_recent
    ON location_notifications(tenant, place_id, suggestion_key, sent_ts DESC);

CREATE TABLE IF NOT EXISTS survey_blueprints(
  blueprint_key TEXT PRIMARY KEY,
  description TEXT NOT NULL DEFAULT '',
  spec_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS survey_requests(
  request_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant TEXT NOT NULL,
  blueprint_key TEXT NOT NULL,
  owner TEXT NULL,
  target_name TEXT NULL,
  role_hint TEXT NULL,
  event_id TEXT NULL,
  objective TEXT NOT NULL,
  context_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'queued',
  deadline_ts TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS survey_instances(
  instance_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id UUID NOT NULL REFERENCES survey_requests(request_id),
  provider TEXT NOT NULL DEFAULT 'metasurvey',
  provider_survey_id TEXT NULL,
  public_url TEXT NULL,
  edit_url TEXT NULL,
  hidden_fields_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'building',
  published_at TIMESTAMPTZ NULL,
  expires_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS survey_submissions(
  submission_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  instance_id UUID NOT NULL REFERENCES survey_instances(instance_id),
  provider_submission_id TEXT NULL,
  submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  raw_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  normalized_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  score_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS intake_insights(
  insight_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_id TEXT NOT NULL,
  insight_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  confidence NUMERIC(4,3) NOT NULL DEFAULT 0.500,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS browser_jobs (
    job_id BIGSERIAL PRIMARY KEY,
    tenant TEXT NOT NULL,
    target_ltd TEXT NOT NULL,
    script_payload_json JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE IF EXISTS browser_jobs ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE IF EXISTS browser_jobs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
CREATE INDEX IF NOT EXISTS idx_browser_jobs_ready ON browser_jobs(status, created_at DESC);

COMMIT;
