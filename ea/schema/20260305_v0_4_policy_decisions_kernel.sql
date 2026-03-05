-- Policy decision audit baseline

CREATE TABLE IF NOT EXISTS policy_decisions (
    decision_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    allow BOOLEAN NOT NULL,
    requires_approval BOOLEAN NOT NULL,
    reason TEXT NOT NULL,
    retention_policy TEXT NOT NULL,
    memory_write_allowed BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_policy_decisions_created
ON policy_decisions(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_policy_decisions_session_created
ON policy_decisions(session_id, created_at DESC);
