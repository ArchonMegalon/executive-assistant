-- Execution ledger v2
-- Adds steps, tool receipts, and run-cost audit tables.
-- Compatibility note:
-- Some older installations use UUID-typed session identifiers. Infer column
-- types from the live schema so this migration applies on both UUID and TEXT
-- ledgers.

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

    EXECUTE format($sql$
        CREATE TABLE IF NOT EXISTS execution_steps (
            step_id TEXT PRIMARY KEY,
            session_id %s NOT NULL REFERENCES execution_sessions(session_id) ON DELETE CASCADE,
            parent_step_id TEXT NULL,
            step_kind TEXT NOT NULL,
            state TEXT NOT NULL,
            attempt_count INT NOT NULL,
            input_json JSONB NOT NULL,
            output_json JSONB NOT NULL,
            error_json JSONB NOT NULL,
            correlation_id TEXT NOT NULL,
            causation_id TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        );
    $sql$, session_id_type);

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
        CREATE TABLE IF NOT EXISTS tool_receipts (
            receipt_id TEXT PRIMARY KEY,
            session_id %s NOT NULL REFERENCES execution_sessions(session_id) ON DELETE CASCADE,
            step_id %s NOT NULL REFERENCES execution_steps(step_id) ON DELETE CASCADE,
            tool_name TEXT NOT NULL,
            action_kind TEXT NOT NULL,
            target_ref TEXT NOT NULL,
            receipt_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        );
    $sql$, session_id_type, step_id_type);

    EXECUTE format($sql$
        CREATE TABLE IF NOT EXISTS run_costs (
            cost_id TEXT PRIMARY KEY,
            session_id %s NOT NULL REFERENCES execution_sessions(session_id) ON DELETE CASCADE,
            model_name TEXT NOT NULL,
            tokens_in BIGINT NOT NULL,
            tokens_out BIGINT NOT NULL,
            cost_usd DOUBLE PRECISION NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        );
    $sql$, session_id_type);
END
$$;

CREATE INDEX IF NOT EXISTS idx_execution_steps_session_created
ON execution_steps(session_id, created_at, step_id);

CREATE INDEX IF NOT EXISTS idx_tool_receipts_session_created
ON tool_receipts(session_id, created_at, receipt_id);

CREATE INDEX IF NOT EXISTS idx_run_costs_session_created
ON run_costs(session_id, created_at, cost_id);
