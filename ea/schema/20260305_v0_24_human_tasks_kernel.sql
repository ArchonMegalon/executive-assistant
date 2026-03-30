-- Human tasks kernel
-- Compatibility note:
-- Some upgraded installations may still use UUID-typed session identifiers.
-- Infer the live session column type so human-task foreign keys match the
-- upgraded execution ledger schema.

DO $$
DECLARE
    session_id_type TEXT;
    step_id_type TEXT;
BEGIN
    SELECT format_type(a.atttypid, a.atttypmod)
      INTO session_id_type
      FROM pg_attribute a
      JOIN pg_class c ON c.oid = a.attrelid
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public'
       AND c.relname = 'execution_sessions'
       AND a.attname = 'session_id'
       AND a.attnum > 0
       AND NOT a.attisdropped;

    IF session_id_type IS NULL THEN
        session_id_type := 'text';
    END IF;

    SELECT format_type(a.atttypid, a.atttypmod)
      INTO step_id_type
      FROM pg_attribute a
      JOIN pg_class c ON c.oid = a.attrelid
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public'
       AND c.relname = 'execution_steps'
       AND a.attname = 'step_id'
       AND a.attnum > 0
       AND NOT a.attisdropped;

    IF step_id_type IS NULL THEN
        step_id_type := 'text';
    END IF;

    EXECUTE format($sql$
        CREATE TABLE IF NOT EXISTS human_tasks (
            human_task_id TEXT PRIMARY KEY,
            session_id %s NOT NULL REFERENCES execution_sessions(session_id) ON DELETE CASCADE,
            step_id %s NULL REFERENCES execution_steps(step_id) ON DELETE SET NULL,
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
    $sql$, session_id_type, step_id_type);
END
$$;

CREATE INDEX IF NOT EXISTS idx_human_tasks_principal_status_created
ON human_tasks(principal_id, status, created_at DESC, human_task_id DESC);

CREATE INDEX IF NOT EXISTS idx_human_tasks_session_created
ON human_tasks(session_id, created_at ASC, human_task_id ASC);
