-- Approval workflow kernel
-- Durable approval requests + approval decision audit.
-- Compatibility note:
-- Older installations may have legacy approval tables with integer IDs and
-- different column names. This migration upgrades in place with additive
-- columns so runtime inserts remain compatible.

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

ALTER TABLE approval_requests
    ADD COLUMN IF NOT EXISTS approval_id TEXT,
    ADD COLUMN IF NOT EXISTS session_id TEXT,
    ADD COLUMN IF NOT EXISTS step_id TEXT,
    ADD COLUMN IF NOT EXISTS reason TEXT,
    ADD COLUMN IF NOT EXISTS requested_action_json JSONB,
    ADD COLUMN IF NOT EXISTS status TEXT,
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;

DO $body$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'approval_requests' AND column_name = 'approval_request_id'
    ) THEN
        EXECUTE $sql$
            UPDATE approval_requests
            SET approval_id = 'legacy-' || approval_request_id::text
            WHERE COALESCE(approval_id, '') = ''
        $sql$;
    END IF;

    UPDATE approval_requests
    SET approval_id = md5(random()::text || clock_timestamp()::text)
    WHERE COALESCE(approval_id, '') = '';

    UPDATE approval_requests
    SET session_id = COALESCE(session_id, ''),
        step_id = COALESCE(step_id, ''),
        reason = COALESCE(reason, ''),
        requested_action_json = COALESCE(requested_action_json, '{}'::jsonb),
        status = COALESCE(NULLIF(status, ''), 'pending'),
        created_at = COALESCE(created_at, NOW()),
        updated_at = COALESCE(updated_at, COALESCE(created_at, NOW()));
END
$body$;

ALTER TABLE approval_requests
    ALTER COLUMN approval_id SET NOT NULL,
    ALTER COLUMN session_id SET NOT NULL,
    ALTER COLUMN step_id SET NOT NULL,
    ALTER COLUMN reason SET NOT NULL,
    ALTER COLUMN requested_action_json SET NOT NULL,
    ALTER COLUMN status SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN updated_at SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_approval_requests_approval_id_unique
ON approval_requests(approval_id);

CREATE INDEX IF NOT EXISTS idx_approval_requests_status_created
ON approval_requests(status, created_at DESC);

CREATE TABLE IF NOT EXISTS approval_decisions (
    decision_id TEXT PRIMARY KEY,
    approval_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    decided_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

ALTER TABLE approval_decisions
    ADD COLUMN IF NOT EXISTS decision_id TEXT,
    ADD COLUMN IF NOT EXISTS approval_id TEXT,
    ADD COLUMN IF NOT EXISTS session_id TEXT,
    ADD COLUMN IF NOT EXISTS step_id TEXT,
    ADD COLUMN IF NOT EXISTS decision TEXT,
    ADD COLUMN IF NOT EXISTS decided_by TEXT,
    ADD COLUMN IF NOT EXISTS reason TEXT,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;

DO $body$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'approval_decisions' AND column_name = 'approval_decision_id'
    ) THEN
        EXECUTE $sql$
            UPDATE approval_decisions
            SET decision_id = 'legacy-' || approval_decision_id::text
            WHERE COALESCE(decision_id, '') = ''
        $sql$;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'approval_decisions' AND column_name = 'approval_request_id'
    )
    AND EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'approval_requests' AND column_name = 'approval_request_id'
    ) THEN
        EXECUTE $sql$
            UPDATE approval_decisions d
            SET approval_id = r.approval_id
            FROM approval_requests r
            WHERE d.approval_request_id::text = r.approval_request_id::text
              AND COALESCE(d.approval_id, '') = ''
        $sql$;
    END IF;

    UPDATE approval_decisions
    SET decision_id = COALESCE(NULLIF(decision_id, ''), md5(random()::text || clock_timestamp()::text)),
        approval_id = COALESCE(approval_id, ''),
        session_id = COALESCE(session_id, ''),
        step_id = COALESCE(step_id, ''),
        decision = COALESCE(decision, ''),
        decided_by = COALESCE(decided_by, ''),
        reason = COALESCE(reason, ''),
        created_at = COALESCE(created_at, NOW());
END
$body$;

ALTER TABLE approval_decisions
    ALTER COLUMN decision_id SET NOT NULL,
    ALTER COLUMN approval_id SET NOT NULL,
    ALTER COLUMN session_id SET NOT NULL,
    ALTER COLUMN step_id SET NOT NULL,
    ALTER COLUMN decision SET NOT NULL,
    ALTER COLUMN decided_by SET NOT NULL,
    ALTER COLUMN reason SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_approval_decisions_decision_id_unique
ON approval_decisions(decision_id);

CREATE INDEX IF NOT EXISTS idx_approval_decisions_session_created
ON approval_decisions(session_id, created_at DESC);
