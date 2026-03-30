-- Explicit artifact ownership for principal-scoped rewrite/task fetches.

ALTER TABLE artifacts
ADD COLUMN IF NOT EXISTS principal_id TEXT;

UPDATE artifacts
SET principal_id = COALESCE(NULLIF(principal_id, ''), COALESCE(metadata_json->>'principal_id', ''), '')
WHERE principal_id IS NULL OR principal_id = '';

DO $$
BEGIN
    IF to_regclass('public.execution_sessions') IS NOT NULL THEN
        UPDATE artifacts AS a
        SET principal_id = COALESCE(NULLIF(a.principal_id, ''), COALESCE(es.intent_json->>'principal_id', ''))
        FROM execution_sessions AS es
        WHERE a.session_id = es.session_id::text
          AND COALESCE(a.principal_id, '') = '';
    END IF;
END
$$;

ALTER TABLE artifacts
ALTER COLUMN principal_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_artifacts_principal_created
ON artifacts(principal_id, created_at DESC);
