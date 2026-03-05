-- v0_16: follow-ups kernel seed

CREATE TABLE IF NOT EXISTS follow_ups (
    follow_up_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    stakeholder_ref TEXT NOT NULL,
    topic TEXT NOT NULL,
    status TEXT NOT NULL,
    due_at TIMESTAMPTZ NULL,
    channel_hint TEXT NOT NULL,
    notes TEXT NOT NULL,
    source_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_follow_ups_principal_status
ON follow_ups(principal_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_follow_ups_principal_due
ON follow_ups(principal_id, due_at ASC);
