-- v0_18: stakeholders kernel seed

CREATE TABLE IF NOT EXISTS stakeholders (
    stakeholder_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    channel_ref TEXT NOT NULL,
    authority_level TEXT NOT NULL,
    importance TEXT NOT NULL,
    response_cadence TEXT NOT NULL,
    tone_pref TEXT NOT NULL,
    sensitivity TEXT NOT NULL,
    escalation_policy TEXT NOT NULL,
    open_loops_json JSONB NOT NULL,
    friction_points_json JSONB NOT NULL,
    last_interaction_at TIMESTAMPTZ NULL,
    status TEXT NOT NULL,
    notes TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_stakeholders_principal_status
ON stakeholders(principal_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_stakeholders_principal_name
ON stakeholders(principal_id, display_name);
