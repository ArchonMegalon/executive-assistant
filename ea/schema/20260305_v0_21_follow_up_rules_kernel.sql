-- v0_21: follow-up rules kernel seed

CREATE TABLE IF NOT EXISTS follow_up_rules (
    rule_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    name TEXT NOT NULL,
    trigger_kind TEXT NOT NULL,
    channel_scope_json JSONB NOT NULL,
    delay_minutes INTEGER NOT NULL,
    max_attempts INTEGER NOT NULL,
    escalation_policy TEXT NOT NULL,
    conditions_json JSONB NOT NULL,
    action_json JSONB NOT NULL,
    status TEXT NOT NULL,
    notes TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_follow_up_rules_principal_status
ON follow_up_rules(principal_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_follow_up_rules_principal_trigger
ON follow_up_rules(principal_id, trigger_kind);
