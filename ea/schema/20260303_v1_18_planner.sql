BEGIN;

CREATE TABLE IF NOT EXISTS planner_jobs (
    planner_job_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    job_status TEXT NOT NULL,
    lease_token TEXT,
    lease_expires_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS planner_candidates (
    candidate_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    candidate_type TEXT NOT NULL,
    candidate_ref TEXT NOT NULL,
    normalized_payload_json JSONB NOT NULL,
    candidate_status TEXT NOT NULL DEFAULT 'queued',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS proactive_items (
    proactive_item_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    candidate_id BIGINT REFERENCES planner_candidates(candidate_id),
    channel TEXT NOT NULL,
    send_at TIMESTAMPTZ NOT NULL,
    dedupe_key TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    item_status TEXT NOT NULL DEFAULT 'scheduled',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_key, dedupe_key)
);

CREATE TABLE IF NOT EXISTS proactive_muted_classes (
    muted_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    principal_id TEXT,
    candidate_type TEXT NOT NULL,
    muted_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS send_budgets (
    budget_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    budget_day DATE NOT NULL,
    sends_used INT NOT NULL DEFAULT 0,
    tokens_used INT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_key, budget_day)
);

CREATE TABLE IF NOT EXISTS quiet_hours (
    quiet_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    principal_id TEXT,
    start_local TIME NOT NULL,
    end_local TIME NOT NULL,
    timezone TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_key, principal_id)
);

CREATE TABLE IF NOT EXISTS channel_prefs (
    channel_pref_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    principal_id TEXT,
    channel TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_key, principal_id, channel)
);

CREATE TABLE IF NOT EXISTS urgency_policies (
    urgency_policy_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    candidate_type TEXT NOT NULL,
    urgency_score NUMERIC NOT NULL DEFAULT 0,
    policy_json JSONB,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_key, candidate_type)
);

CREATE TABLE IF NOT EXISTS planner_breakers (
    planner_breaker_id SERIAL PRIMARY KEY,
    breaker_key TEXT NOT NULL UNIQUE,
    breaker_state TEXT NOT NULL,
    reason TEXT,
    opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS planner_dedupe_keys (
    dedupe_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_key, dedupe_key)
);

CREATE TABLE IF NOT EXISTS planner_budget_windows (
    budget_window_id SERIAL PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    token_budget INT NOT NULL,
    tokens_used INT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_planner_jobs_status ON planner_jobs(tenant_key, job_status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_planner_candidates_status ON planner_candidates(tenant_key, candidate_status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_proactive_items_status ON proactive_items(tenant_key, item_status, send_at);
CREATE INDEX IF NOT EXISTS idx_send_budgets_day ON send_budgets(tenant_key, budget_day);
CREATE INDEX IF NOT EXISTS idx_budget_windows_time ON planner_budget_windows(tenant_key, window_start, window_end);

COMMIT;
