CREATE TABLE IF NOT EXISTS human_tasks (
    human_task_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES execution_sessions(session_id) ON DELETE CASCADE,
    step_id TEXT NULL REFERENCES execution_steps(step_id) ON DELETE SET NULL,
    principal_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    role_required TEXT NOT NULL,
    brief TEXT NOT NULL,
    input_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    desired_output_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    priority TEXT NOT NULL DEFAULT 'normal',
    sla_due_at TIMESTAMPTZ NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    assigned_operator_id TEXT NOT NULL DEFAULT '',
    resolution TEXT NOT NULL DEFAULT '',
    returned_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    provenance_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_human_tasks_principal_status_created
ON human_tasks(principal_id, status, created_at DESC, human_task_id DESC);

CREATE INDEX IF NOT EXISTS idx_human_tasks_session_created
ON human_tasks(session_id, created_at ASC, human_task_id ASC);
