-- v0_13: commitments kernel seed

CREATE TABLE IF NOT EXISTS commitments (
    commitment_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    title TEXT NOT NULL,
    details TEXT NOT NULL,
    status TEXT NOT NULL,
    priority TEXT NOT NULL,
    due_at TIMESTAMPTZ NULL,
    source_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_commitments_principal_updated
ON commitments(principal_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_commitments_principal_status
ON commitments(principal_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_commitments_due_at
ON commitments(principal_id, due_at ASC);
