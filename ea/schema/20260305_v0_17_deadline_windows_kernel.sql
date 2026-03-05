-- v0_17: deadline windows kernel seed

CREATE TABLE IF NOT EXISTS deadline_windows (
    window_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    title TEXT NOT NULL,
    start_at TIMESTAMPTZ NULL,
    end_at TIMESTAMPTZ NULL,
    status TEXT NOT NULL,
    priority TEXT NOT NULL,
    notes TEXT NOT NULL,
    source_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_deadline_windows_principal_status
ON deadline_windows(principal_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_deadline_windows_principal_end
ON deadline_windows(principal_id, end_at ASC);
