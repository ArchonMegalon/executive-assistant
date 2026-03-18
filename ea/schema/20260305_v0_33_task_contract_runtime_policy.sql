-- Typed runtime-policy storage for task contracts.
-- Keeps runtime routing overrides separate from legacy budget metadata.

ALTER TABLE task_contracts
ADD COLUMN IF NOT EXISTS runtime_policy_json JSONB NOT NULL DEFAULT '{}'::jsonb;
