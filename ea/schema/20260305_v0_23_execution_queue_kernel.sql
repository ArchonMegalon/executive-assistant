-- Execution queue kernel
-- Adds a durable lease-based queue for resumable execution steps.
-- Compatibility note:
-- Some upgraded installations may still use UUID-typed session/step IDs.
-- Infer live column types so the queue references the current ledger schema.

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
        CREATE TABLE IF NOT EXISTS execution_queue (
            queue_id TEXT PRIMARY KEY,
            session_id %s NOT NULL REFERENCES execution_sessions(session_id) ON DELETE CASCADE,
            step_id %s NOT NULL REFERENCES execution_steps(step_id) ON DELETE CASCADE,
            state TEXT NOT NULL,
            lease_owner TEXT NOT NULL,
            lease_expires_at TIMESTAMPTZ NULL,
            attempt_count INT NOT NULL,
            next_attempt_at TIMESTAMPTZ NULL,
            idempotency_key TEXT NOT NULL,
            last_error TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        );
    $sql$, session_id_type, step_id_type);
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_execution_queue_idempotency
ON execution_queue(idempotency_key);

CREATE INDEX IF NOT EXISTS idx_execution_queue_state_next_attempt
ON execution_queue(state, next_attempt_at, created_at, queue_id);

CREATE INDEX IF NOT EXISTS idx_execution_queue_session_created
ON execution_queue(session_id, created_at, queue_id);
