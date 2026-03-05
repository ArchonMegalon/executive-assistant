-- v0_19: decision windows kernel seed

CREATE TABLE IF NOT EXISTS decision_windows (
    decision_window_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    title TEXT NOT NULL,
    context TEXT NOT NULL,
    opens_at TIMESTAMPTZ NULL,
    closes_at TIMESTAMPTZ NULL,
    urgency TEXT NOT NULL,
    authority_required TEXT NOT NULL,
    status TEXT NOT NULL,
    notes TEXT NOT NULL,
    source_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_decision_windows_principal_status
ON decision_windows(principal_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_decision_windows_principal_closes
ON decision_windows(principal_id, closes_at ASC);
