BEGIN;
CREATE TABLE IF NOT EXISTS delivery_sessions (
    session_id SERIAL PRIMARY KEY, 
    correlation_id TEXT, 
    chat_id TEXT, 
    initial_message_id TEXT, 
    mode TEXT, 
    status TEXT, 
    enhancement_deadline_ts TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS repair_jobs (
    job_id SERIAL PRIMARY KEY, 
    correlation_id TEXT, 
    fault_class TEXT, 
    recipe_key TEXT, 
    status TEXT, 
    max_attempts INT DEFAULT 3, 
    deadline_ts TIMESTAMP,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS repair_attempts (
    attempt_id SERIAL PRIMARY KEY, 
    job_id INT, 
    attempt_no INT, 
    action_key TEXT, 
    outcome TEXT, 
    breaker_state TEXT, 
    audit_json TEXT, 
    duration_ms INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sanitizer_audits (
    audit_id SERIAL PRIMARY KEY, 
    correlation_id TEXT, 
    message_kind TEXT, 
    matched_rule TEXT, 
    replacement_kind TEXT, 
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS operator_tasks (
    task_id SERIAL PRIMARY KEY, 
    correlation_id TEXT, 
    task_type TEXT, 
    priority TEXT, 
    status TEXT, 
    summary TEXT, 
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS circuit_breakers (
    breaker_key TEXT PRIMARY KEY, 
    state TEXT, 
    reason TEXT, 
    opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, 
    expires_at TIMESTAMP, 
    correlation_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_delivery_sessions_corr ON delivery_sessions (correlation_id);
CREATE INDEX IF NOT EXISTS idx_repair_jobs_corr ON repair_jobs (correlation_id);
CREATE INDEX IF NOT EXISTS idx_sanitizer_audits_corr ON sanitizer_audits (correlation_id);
COMMIT;
