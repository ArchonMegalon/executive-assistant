-- v0_22: interruption budgets kernel seed

CREATE TABLE IF NOT EXISTS interruption_budgets (
    budget_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    window_kind TEXT NOT NULL,
    budget_minutes INTEGER NOT NULL,
    used_minutes INTEGER NOT NULL,
    reset_at TIMESTAMPTZ NULL,
    quiet_hours_json JSONB NOT NULL,
    status TEXT NOT NULL,
    notes TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_interrupt_budgets_principal_status
ON interruption_budgets(principal_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_interrupt_budgets_principal_scope
ON interruption_budgets(principal_id, scope);
