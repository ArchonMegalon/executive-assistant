-- Approval workflow kernel
-- Durable approval requests + approval decision audit.

CREATE TABLE IF NOT EXISTS approval_requests (
    approval_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    requested_action_json JSONB NOT NULL,
    status TEXT NOT NULL,
    expires_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_approval_requests_status_created
ON approval_requests(status, created_at DESC);

CREATE TABLE IF NOT EXISTS approval_decisions (
    decision_id TEXT PRIMARY KEY,
    approval_id TEXT NOT NULL REFERENCES approval_requests(approval_id) ON DELETE CASCADE,
    session_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    decided_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_approval_decisions_session_created
ON approval_decisions(session_id, created_at DESC);
