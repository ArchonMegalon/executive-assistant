-- Execution ledger legacy compatibility upgrade
-- Older rewrite installations may still expose bigint event IDs and legacy
-- execution-step columns (`status`, `step_key`, `result_json`, `error_text`).
-- Upgrade those tables in place so modern runtime reads/writes remain
-- compatible without resetting operator data.

ALTER TABLE execution_events
    ADD COLUMN IF NOT EXISTS name TEXT;

DO $body$
DECLARE
    event_id_type TEXT;
BEGIN
    SELECT data_type
      INTO event_id_type
      FROM information_schema.columns
     WHERE table_schema = 'public'
       AND table_name = 'execution_events'
       AND column_name = 'event_id';

    IF COALESCE(event_id_type, '') <> 'text' THEN
        EXECUTE 'ALTER TABLE execution_events ALTER COLUMN event_id DROP DEFAULT';
        EXECUTE 'ALTER TABLE execution_events ALTER COLUMN event_id TYPE TEXT USING event_id::text';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'execution_events'
           AND column_name = 'event_type'
    )
    AND EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'execution_events'
           AND column_name = 'message'
    ) THEN
        EXECUTE $sql$
            UPDATE execution_events
               SET name = COALESCE(NULLIF(name, ''), NULLIF(event_type, ''), NULLIF(message, ''), 'event')
             WHERE COALESCE(name, '') = ''
        $sql$;
    ELSIF EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'execution_events'
           AND column_name = 'event_type'
    ) THEN
        EXECUTE $sql$
            UPDATE execution_events
               SET name = COALESCE(NULLIF(name, ''), NULLIF(event_type, ''), 'event')
             WHERE COALESCE(name, '') = ''
        $sql$;
    ELSIF EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'execution_events'
           AND column_name = 'message'
    ) THEN
        EXECUTE $sql$
            UPDATE execution_events
               SET name = COALESCE(NULLIF(name, ''), NULLIF(message, ''), 'event')
             WHERE COALESCE(name, '') = ''
        $sql$;
    ELSE
        UPDATE execution_events
           SET name = 'event'
         WHERE COALESCE(name, '') = '';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'execution_events'
           AND column_name = 'event_type'
    ) THEN
        EXECUTE 'ALTER TABLE execution_events ALTER COLUMN event_type SET DEFAULT ''event''';
        EXECUTE $sql$
            UPDATE execution_events
               SET event_type = COALESCE(NULLIF(event_type, ''), name, 'event')
             WHERE COALESCE(event_type, '') = ''
        $sql$;
    END IF;

    IF EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'execution_events'
           AND column_name = 'message'
    ) THEN
        EXECUTE $$ALTER TABLE execution_events ALTER COLUMN message SET DEFAULT ''$$;
        EXECUTE $$UPDATE execution_events SET message = COALESCE(message, '')$$;
    END IF;

    UPDATE execution_events
       SET payload_json = COALESCE(payload_json, '{}'::jsonb),
           created_at = COALESCE(created_at, NOW());
END
$body$;

ALTER TABLE execution_events
    ALTER COLUMN name SET NOT NULL,
    ALTER COLUMN payload_json SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_execution_events_session_created
ON execution_events(session_id, created_at);

ALTER TABLE execution_steps
    ADD COLUMN IF NOT EXISTS parent_step_id TEXT,
    ADD COLUMN IF NOT EXISTS step_kind TEXT,
    ADD COLUMN IF NOT EXISTS state TEXT,
    ADD COLUMN IF NOT EXISTS attempt_count INT,
    ADD COLUMN IF NOT EXISTS input_json JSONB,
    ADD COLUMN IF NOT EXISTS output_json JSONB,
    ADD COLUMN IF NOT EXISTS error_json JSONB,
    ADD COLUMN IF NOT EXISTS correlation_id TEXT,
    ADD COLUMN IF NOT EXISTS causation_id TEXT,
    ADD COLUMN IF NOT EXISTS actor_type TEXT,
    ADD COLUMN IF NOT EXISTS actor_id TEXT;

DO $body$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'execution_steps'
           AND column_name = 'step_key'
    )
    AND EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'execution_steps'
           AND column_name = 'step_title'
    ) THEN
        EXECUTE $sql$
            UPDATE execution_steps
               SET step_kind = COALESCE(NULLIF(step_kind, ''), NULLIF(step_key, ''), NULLIF(step_title, ''), 'step')
             WHERE COALESCE(step_kind, '') = ''
        $sql$;
    ELSIF EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'execution_steps'
           AND column_name = 'step_key'
    ) THEN
        EXECUTE $sql$
            UPDATE execution_steps
               SET step_kind = COALESCE(NULLIF(step_kind, ''), NULLIF(step_key, ''), 'step')
             WHERE COALESCE(step_kind, '') = ''
        $sql$;
    ELSIF EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'execution_steps'
           AND column_name = 'step_title'
    ) THEN
        EXECUTE $sql$
            UPDATE execution_steps
               SET step_kind = COALESCE(NULLIF(step_kind, ''), NULLIF(step_title, ''), 'step')
             WHERE COALESCE(step_kind, '') = ''
        $sql$;
    ELSE
        UPDATE execution_steps
           SET step_kind = 'step'
         WHERE COALESCE(step_kind, '') = '';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'execution_steps'
           AND column_name = 'status'
    ) THEN
        EXECUTE $sql$
            UPDATE execution_steps
               SET state = COALESCE(NULLIF(state, ''), NULLIF(status, ''), 'queued')
             WHERE COALESCE(state, '') = ''
        $sql$;
    ELSE
        UPDATE execution_steps
           SET state = 'queued'
         WHERE COALESCE(state, '') = '';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'execution_steps'
           AND column_name = 'preconditions_json'
    ) THEN
        EXECUTE $sql$
            UPDATE execution_steps
               SET input_json = COALESCE(input_json, preconditions_json, '{}'::jsonb)
             WHERE input_json IS NULL
        $sql$;
    ELSE
        UPDATE execution_steps
           SET input_json = '{}'::jsonb
         WHERE input_json IS NULL;
    END IF;

    IF EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'execution_steps'
           AND column_name = 'result_json'
    )
    AND EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'execution_steps'
           AND column_name = 'evidence_json'
    ) THEN
        EXECUTE $sql$
            UPDATE execution_steps
               SET output_json = COALESCE(output_json, NULLIF(result_json, '{}'::jsonb), NULLIF(evidence_json, '{}'::jsonb), '{}'::jsonb)
             WHERE output_json IS NULL
        $sql$;
    ELSIF EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'execution_steps'
           AND column_name = 'result_json'
    ) THEN
        EXECUTE $sql$
            UPDATE execution_steps
               SET output_json = COALESCE(output_json, NULLIF(result_json, '{}'::jsonb), '{}'::jsonb)
             WHERE output_json IS NULL
        $sql$;
    ELSIF EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'execution_steps'
           AND column_name = 'evidence_json'
    ) THEN
        EXECUTE $sql$
            UPDATE execution_steps
               SET output_json = COALESCE(output_json, NULLIF(evidence_json, '{}'::jsonb), '{}'::jsonb)
             WHERE output_json IS NULL
        $sql$;
    ELSE
        UPDATE execution_steps
           SET output_json = '{}'::jsonb
         WHERE output_json IS NULL;
    END IF;

    IF EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'execution_steps'
           AND column_name = 'error_text'
    ) THEN
        EXECUTE $sql$
            UPDATE execution_steps
               SET error_json = CASE
                   WHEN COALESCE(BTRIM(error_text), '') <> '' THEN jsonb_build_object('message', error_text)
                   ELSE '{}'::jsonb
               END
             WHERE error_json IS NULL
        $sql$;
    ELSE
        UPDATE execution_steps
           SET error_json = '{}'::jsonb
         WHERE error_json IS NULL;
    END IF;

    UPDATE execution_steps
       SET attempt_count = COALESCE(attempt_count, 0),
           correlation_id = COALESCE(correlation_id, ''),
           causation_id = COALESCE(causation_id, ''),
           actor_type = COALESCE(NULLIF(actor_type, ''), 'system'),
           actor_id = COALESCE(NULLIF(actor_id, ''), 'orchestrator');
END
$body$;

ALTER TABLE execution_steps
    ALTER COLUMN step_kind SET NOT NULL,
    ALTER COLUMN state SET NOT NULL,
    ALTER COLUMN attempt_count SET NOT NULL,
    ALTER COLUMN input_json SET NOT NULL,
    ALTER COLUMN output_json SET NOT NULL,
    ALTER COLUMN error_json SET NOT NULL,
    ALTER COLUMN correlation_id SET NOT NULL,
    ALTER COLUMN causation_id SET NOT NULL,
    ALTER COLUMN actor_type SET NOT NULL,
    ALTER COLUMN actor_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_execution_steps_session_created
ON execution_steps(session_id, created_at, step_id);
