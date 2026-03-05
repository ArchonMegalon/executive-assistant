import os
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

_pool = None


def _database_url() -> str:
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    return url

def _raw_get_db():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 20, _database_url())
    
    class DBMgr:
        def execute(self, query, vars=None):
            conn = _pool.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute(query, vars)
                conn.commit()
            finally:
                _pool.putconn(conn)
                
        def fetchone(self, query, vars=None):
            conn = _pool.getconn()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(query, vars)
                    res = cur.fetchone()
                conn.commit()
                return res
            finally:
                _pool.putconn(conn)
                
        def fetchall(self, query, vars=None):
            conn = _pool.getconn()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(query, vars)
                    res = cur.fetchall()
                conn.commit()
                return res
            finally:
                _pool.putconn(conn)
    return DBMgr()


def init_db_sync() -> None:
    db = get_db()
    db.execute(
        """
        CREATE EXTENSION IF NOT EXISTS pgcrypto;

        CREATE TABLE IF NOT EXISTS audit_log (
            ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            tenant TEXT,
            component TEXT NOT NULL,
            event_type TEXT NOT NULL,
            message TEXT NOT NULL,
            payload JSONB
        );
        CREATE INDEX IF NOT EXISTS audit_log_ts_idx ON audit_log(ts DESC);

        CREATE TABLE IF NOT EXISTS tg_updates (
            tenant TEXT NOT NULL,
            update_id BIGINT NOT NULL,
            payload_json JSONB NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            attempt_count INT NOT NULL DEFAULT 0,
            next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant, update_id)
        );
        CREATE INDEX IF NOT EXISTS idx_tg_updates_ready ON tg_updates(status, next_attempt_at);
        ALTER TABLE IF EXISTS tg_updates ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
        ALTER TABLE IF EXISTS tg_updates ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

        CREATE TABLE IF NOT EXISTS tg_outbox (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant TEXT NOT NULL,
            chat_id BIGINT NOT NULL,
            payload_json JSONB NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            attempt_count INT NOT NULL DEFAULT 0,
            next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_error TEXT,
            idempotency_key TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_tg_outbox_idem ON tg_outbox(tenant, idempotency_key) WHERE idempotency_key IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_tg_outbox_ready ON tg_outbox(status, next_attempt_at);
        ALTER TABLE IF EXISTS tg_outbox ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
        ALTER TABLE IF EXISTS tg_outbox ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
        ALTER TABLE IF EXISTS tg_outbox ALTER COLUMN id SET DEFAULT gen_random_uuid();

        CREATE TABLE IF NOT EXISTS typed_actions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant TEXT NOT NULL,
            action_type TEXT NOT NULL,
            payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            session_id UUID,
            step_id UUID,
            approval_gate_id UUID,
            is_consumed BOOLEAN NOT NULL DEFAULT FALSE,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        ALTER TABLE IF EXISTS typed_actions ADD COLUMN IF NOT EXISTS session_id UUID;
        ALTER TABLE IF EXISTS typed_actions ADD COLUMN IF NOT EXISTS step_id UUID;
        ALTER TABLE IF EXISTS typed_actions ADD COLUMN IF NOT EXISTS approval_gate_id UUID;
        CREATE INDEX IF NOT EXISTS idx_typed_actions_ready ON typed_actions(tenant, action_type, is_consumed, expires_at);
        CREATE INDEX IF NOT EXISTS idx_typed_actions_session ON typed_actions(session_id);
        CREATE INDEX IF NOT EXISTS idx_typed_actions_approval_gate ON typed_actions(approval_gate_id);

        CREATE TABLE IF NOT EXISTS execution_sessions (
            session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'telegram_free_text',
            chat_id BIGINT,
            intent_type TEXT NOT NULL DEFAULT 'free_text',
            objective TEXT NOT NULL DEFAULT '',
            intent_spec_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            status TEXT NOT NULL DEFAULT 'queued',
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            last_error TEXT,
            outcome_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            correlation_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_execution_sessions_poll
            ON execution_sessions(tenant, status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_execution_sessions_corr
            ON execution_sessions(correlation_id);

        CREATE TABLE IF NOT EXISTS execution_steps (
            step_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id UUID NOT NULL REFERENCES execution_sessions(session_id) ON DELETE CASCADE,
            step_order INT NOT NULL,
            step_key TEXT NOT NULL,
            step_title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            preconditions_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            error_text TEXT,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(session_id, step_key)
        );
        CREATE INDEX IF NOT EXISTS idx_execution_steps_poll
            ON execution_steps(session_id, status, step_order);

        CREATE TABLE IF NOT EXISTS execution_events (
            event_id BIGSERIAL PRIMARY KEY,
            session_id UUID NOT NULL REFERENCES execution_sessions(session_id) ON DELETE CASCADE,
            level TEXT NOT NULL DEFAULT 'info',
            event_type TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_execution_events_lookup
            ON execution_events(session_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS approval_gates (
            approval_gate_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id UUID NOT NULL REFERENCES execution_sessions(session_id) ON DELETE CASCADE,
            tenant TEXT NOT NULL,
            chat_id BIGINT,
            approval_class TEXT NOT NULL DEFAULT 'explicit_callback_required',
            decision_status TEXT NOT NULL DEFAULT 'pending',
            action_id TEXT,
            decision_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            decided_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS idx_approval_gates_session
            ON approval_gates(session_id, decision_status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_approval_gates_action
            ON approval_gates(action_id);

        CREATE TABLE IF NOT EXISTS planner_jobs (
            planner_job_id SERIAL PRIMARY KEY,
            tenant_key TEXT NOT NULL,
            job_status TEXT NOT NULL,
            lease_token TEXT,
            lease_expires_at TIMESTAMPTZ,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ
        );

        CREATE TABLE IF NOT EXISTS planner_candidates (
            candidate_id SERIAL PRIMARY KEY,
            tenant_key TEXT NOT NULL,
            candidate_type TEXT NOT NULL,
            candidate_ref TEXT NOT NULL,
            normalized_payload_json JSONB NOT NULL,
            candidate_status TEXT NOT NULL DEFAULT 'queued',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS provider_outcomes (
            provider_outcome_id BIGSERIAL PRIMARY KEY,
            tenant_key TEXT NOT NULL DEFAULT '',
            provider_key TEXT NOT NULL,
            task_type TEXT NOT NULL,
            outcome_status TEXT NOT NULL,
            score_delta INT NOT NULL DEFAULT 0,
            latency_ms INT,
            error_class TEXT,
            source TEXT NOT NULL DEFAULT 'runtime',
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_provider_outcomes_lookup
            ON provider_outcomes(provider_key, task_type, occurred_at DESC);
        CREATE INDEX IF NOT EXISTS idx_provider_outcomes_task_time
            ON provider_outcomes(task_type, occurred_at DESC);

        CREATE TABLE IF NOT EXISTS commitments (
            commitment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_key TEXT NOT NULL,
            commitment_key TEXT NOT NULL,
            domain TEXT NOT NULL DEFAULT 'general',
            title TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open',
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(tenant_key, commitment_key)
        );
        CREATE INDEX IF NOT EXISTS idx_commitments_lookup
            ON commitments(tenant_key, domain, status, updated_at DESC);

        CREATE TABLE IF NOT EXISTS artifacts (
            artifact_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_key TEXT NOT NULL,
            session_id UUID REFERENCES execution_sessions(session_id) ON DELETE SET NULL,
            commitment_key TEXT,
            artifact_type TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            content_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_artifacts_lookup
            ON artifacts(tenant_key, artifact_type, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_artifacts_commitment
            ON artifacts(tenant_key, commitment_key, created_at DESC);

        CREATE TABLE IF NOT EXISTS followups (
            followup_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_key TEXT NOT NULL,
            commitment_key TEXT NOT NULL,
            artifact_id UUID REFERENCES artifacts(artifact_id) ON DELETE SET NULL,
            due_at TIMESTAMPTZ,
            status TEXT NOT NULL DEFAULT 'open',
            notes TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_followups_lookup
            ON followups(tenant_key, status, due_at NULLS LAST, created_at DESC);

        CREATE TABLE IF NOT EXISTS decision_windows (
            decision_window_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_key TEXT NOT NULL,
            commitment_key TEXT NOT NULL,
            window_label TEXT NOT NULL DEFAULT '',
            opens_at TIMESTAMPTZ,
            closes_at TIMESTAMPTZ,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_decision_windows_lookup
            ON decision_windows(tenant_key, status, closes_at NULLS LAST, created_at DESC);

        CREATE TABLE IF NOT EXISTS proactive_items (
            proactive_item_id SERIAL PRIMARY KEY,
            tenant_key TEXT NOT NULL,
            candidate_id BIGINT REFERENCES planner_candidates(candidate_id),
            channel TEXT NOT NULL,
            send_at TIMESTAMPTZ NOT NULL,
            dedupe_key TEXT NOT NULL,
            payload_json JSONB NOT NULL,
            item_status TEXT NOT NULL DEFAULT 'scheduled',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_key, dedupe_key)
        );

        CREATE TABLE IF NOT EXISTS proactive_muted_classes (
            muted_id SERIAL PRIMARY KEY,
            tenant_key TEXT NOT NULL,
            principal_id TEXT,
            candidate_type TEXT NOT NULL,
            muted_until TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS send_budgets (
            budget_id SERIAL PRIMARY KEY,
            tenant_key TEXT NOT NULL,
            budget_day DATE NOT NULL,
            sends_used INT NOT NULL DEFAULT 0,
            tokens_used INT NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_key, budget_day)
        );

        CREATE TABLE IF NOT EXISTS quiet_hours (
            quiet_id SERIAL PRIMARY KEY,
            tenant_key TEXT NOT NULL,
            principal_id TEXT,
            start_local TIME NOT NULL,
            end_local TIME NOT NULL,
            timezone TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_key, principal_id)
        );

        CREATE TABLE IF NOT EXISTS channel_prefs (
            channel_pref_id SERIAL PRIMARY KEY,
            tenant_key TEXT NOT NULL,
            principal_id TEXT,
            channel TEXT NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_key, principal_id, channel)
        );

        CREATE TABLE IF NOT EXISTS urgency_policies (
            urgency_policy_id SERIAL PRIMARY KEY,
            tenant_key TEXT NOT NULL,
            candidate_type TEXT NOT NULL,
            urgency_score NUMERIC NOT NULL DEFAULT 0,
            policy_json JSONB,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_key, candidate_type)
        );

        CREATE TABLE IF NOT EXISTS planner_breakers (
            planner_breaker_id SERIAL PRIMARY KEY,
            breaker_key TEXT NOT NULL UNIQUE,
            breaker_state TEXT NOT NULL,
            reason TEXT,
            opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ
        );

        CREATE TABLE IF NOT EXISTS planner_dedupe_keys (
            dedupe_id SERIAL PRIMARY KEY,
            tenant_key TEXT NOT NULL,
            dedupe_key TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_key, dedupe_key)
        );

        CREATE TABLE IF NOT EXISTS planner_budget_windows (
            budget_window_id SERIAL PRIMARY KEY,
            tenant_key TEXT NOT NULL,
            window_start TIMESTAMPTZ NOT NULL,
            window_end TIMESTAMPTZ NOT NULL,
            token_budget INT NOT NULL,
            tokens_used INT NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_planner_jobs_status
            ON planner_jobs(tenant_key, job_status, started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_planner_candidates_status
            ON planner_candidates(tenant_key, candidate_status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_proactive_items_status
            ON proactive_items(tenant_key, item_status, send_at);
        CREATE INDEX IF NOT EXISTS idx_send_budgets_day
            ON send_budgets(tenant_key, budget_day);
        CREATE INDEX IF NOT EXISTS idx_budget_windows_time
            ON planner_budget_windows(tenant_key, window_start, window_end);

        CREATE TABLE IF NOT EXISTS template_registry (
            tenant TEXT NOT NULL,
            key TEXT NOT NULL,
            provider TEXT NOT NULL,
            template_id TEXT NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            version INT NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant, key, provider)
        );
        CREATE INDEX IF NOT EXISTS idx_template_registry_lookup ON template_registry(key, is_active, version DESC);

        CREATE TABLE IF NOT EXISTS external_approvals (
            approval_id BIGSERIAL PRIMARY KEY,
            tenant TEXT NOT NULL,
            internal_ref_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            provider_request_id TEXT,
            status TEXT NOT NULL DEFAULT 'parked',
            remote_url TEXT,
            decision_payload_json JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant, internal_ref_id, provider)
        );
        CREATE INDEX IF NOT EXISTS idx_external_approvals_status ON external_approvals(status, updated_at DESC);

        CREATE TABLE IF NOT EXISTS external_events (
            event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant TEXT NOT NULL,
            source TEXT NOT NULL,
            event_type TEXT NOT NULL,
            dedupe_key TEXT NOT NULL,
            payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            status TEXT NOT NULL DEFAULT 'queued',
            attempt_count INT NOT NULL DEFAULT 0,
            next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_error TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(tenant, source, dedupe_key)
        );
        CREATE INDEX IF NOT EXISTS idx_ext_events_poll ON external_events(status, next_attempt_at);

        CREATE TABLE IF NOT EXISTS delivery_sessions (
            session_id SERIAL PRIMARY KEY,
            correlation_id TEXT,
            chat_id TEXT,
            initial_message_id TEXT,
            mode TEXT,
            status TEXT,
            enhancement_deadline_ts TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_delivery_sessions_corr ON delivery_sessions(correlation_id);

        CREATE TABLE IF NOT EXISTS location_events (
            id BIGSERIAL PRIMARY KEY,
            tenant TEXT NOT NULL,
            lat DOUBLE PRECISION,
            lon DOUBLE PRECISION,
            ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_location_events_tenant_id ON location_events(tenant, id DESC);

        CREATE TABLE IF NOT EXISTS location_cursors (
            tenant TEXT PRIMARY KEY,
            last_id BIGINT NOT NULL DEFAULT 0,
            updated_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS shopping_list (
            id BIGSERIAL PRIMARY KEY,
            tenant TEXT NOT NULL,
            item TEXT NOT NULL,
            checked BOOLEAN NOT NULL DEFAULT FALSE,
            raw JSONB,
            updated_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_shopping_list_tenant_checked ON shopping_list(tenant, checked, updated_ts DESC);

        CREATE TABLE IF NOT EXISTS location_notifications (
            id BIGSERIAL PRIMARY KEY,
            tenant TEXT NOT NULL,
            place_id TEXT NOT NULL,
            suggestion_key TEXT NOT NULL,
            payload JSONB,
            sent_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_location_notifications_recent
            ON location_notifications(tenant, place_id, suggestion_key, sent_ts DESC);

        CREATE TABLE IF NOT EXISTS survey_blueprints(
            blueprint_key TEXT PRIMARY KEY,
            description TEXT NOT NULL DEFAULT '',
            spec_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS survey_requests(
            request_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant TEXT NOT NULL,
            blueprint_key TEXT NOT NULL,
            owner TEXT NULL,
            target_name TEXT NULL,
            role_hint TEXT NULL,
            event_id TEXT NULL,
            objective TEXT NOT NULL,
            context_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            status TEXT NOT NULL DEFAULT 'queued',
            deadline_ts TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS survey_instances(
            instance_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            request_id UUID NOT NULL REFERENCES survey_requests(request_id),
            provider TEXT NOT NULL DEFAULT 'metasurvey',
            provider_survey_id TEXT NULL,
            public_url TEXT NULL,
            edit_url TEXT NULL,
            hidden_fields_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            status TEXT NOT NULL DEFAULT 'building',
            published_at TIMESTAMPTZ NULL,
            expires_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS survey_submissions(
            submission_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            instance_id UUID NOT NULL REFERENCES survey_instances(instance_id),
            provider_submission_id TEXT NULL,
            submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            raw_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            normalized_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            score_json JSONB NOT NULL DEFAULT '{}'::jsonb
        );

        CREATE TABLE IF NOT EXISTS intake_insights(
            insight_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            insight_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            confidence NUMERIC(4,3) NOT NULL DEFAULT 0.500,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS profile_context_state (
            tenant TEXT NOT NULL,
            person_id TEXT NOT NULL,
            stable_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            situational_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            learned_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            confidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant, person_id)
        );
        CREATE INDEX IF NOT EXISTS idx_profile_context_state_updated
            ON profile_context_state(tenant, person_id, updated_at DESC);

        CREATE TABLE IF NOT EXISTS intelligence_snapshots (
            id BIGSERIAL PRIMARY KEY,
            tenant TEXT NOT NULL,
            person_id TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'briefing_compose',
            compose_mode TEXT NOT NULL DEFAULT '',
            snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_intelligence_snapshots_lookup
            ON intelligence_snapshots(tenant, person_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_intelligence_snapshots_source
            ON intelligence_snapshots(source, created_at DESC);

        CREATE TABLE IF NOT EXISTS llm_egress_policies (
            id BIGSERIAL PRIMARY KEY,
            tenant TEXT NOT NULL DEFAULT '*',
            person_id TEXT NULL,
            task_type TEXT NOT NULL DEFAULT '*',
            data_class TEXT NOT NULL DEFAULT '*',
            action TEXT NOT NULL DEFAULT 'allow',
            active BOOLEAN NOT NULL DEFAULT TRUE,
            notes TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_llm_egress_policies_lookup
            ON llm_egress_policies(tenant, task_type, data_class, active, updated_at DESC);

        CREATE TABLE IF NOT EXISTS browser_jobs (
            job_id BIGSERIAL PRIMARY KEY,
            tenant TEXT NOT NULL,
            target_ltd TEXT NOT NULL,
            script_payload_json JSONB NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        ALTER TABLE IF EXISTS browser_jobs ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
        ALTER TABLE IF EXISTS browser_jobs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
        CREATE INDEX IF NOT EXISTS idx_browser_jobs_ready ON browser_jobs(status, created_at DESC);

        CREATE TABLE IF NOT EXISTS travel_place_history (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant TEXT NOT NULL,
            person_id TEXT NOT NULL,
            place_key TEXT NOT NULL,
            city TEXT,
            country TEXT,
            lat DOUBLE PRECISION,
            lon DOUBLE PRECISION,
            first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            seen_count INT NOT NULL DEFAULT 1,
            UNIQUE (tenant, person_id, place_key)
        );
        CREATE INDEX IF NOT EXISTS idx_travel_place_history_recent
            ON travel_place_history(tenant, person_id, last_seen DESC);

        CREATE TABLE IF NOT EXISTS travel_video_specs (
            spec_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant TEXT NOT NULL,
            person_id TEXT NOT NULL,
            date_key DATE NOT NULL,
            mode TEXT NOT NULL,
            orientation TEXT NOT NULL DEFAULT 'portrait',
            duration_target_sec INT NOT NULL DEFAULT 20,
            route_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            markers_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            signal_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            cache_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            last_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant, person_id, date_key, cache_key)
        );
        CREATE INDEX IF NOT EXISTS idx_travel_video_specs_poll
            ON travel_video_specs(tenant, person_id, date_key, status, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_travel_video_specs_cache
            ON travel_video_specs(tenant, cache_key);

        CREATE TABLE IF NOT EXISTS avomap_jobs (
            job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            spec_id UUID NOT NULL REFERENCES travel_video_specs(spec_id) ON DELETE CASCADE,
            tenant TEXT NOT NULL,
            workflow_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            external_job_id TEXT,
            dedupe_key TEXT,
            last_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant, dedupe_key)
        );
        CREATE INDEX IF NOT EXISTS idx_avomap_jobs_poll
            ON avomap_jobs(status, updated_at DESC);

        CREATE TABLE IF NOT EXISTS avomap_assets (
            asset_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            spec_id UUID NOT NULL REFERENCES travel_video_specs(spec_id) ON DELETE CASCADE,
            tenant TEXT NOT NULL,
            cache_key TEXT NOT NULL,
            object_ref TEXT NOT NULL,
            mime_type TEXT NOT NULL DEFAULT 'video/mp4',
            duration_sec INT,
            external_id TEXT,
            status TEXT NOT NULL DEFAULT 'ready',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant, cache_key),
            UNIQUE (external_id)
        );
        CREATE INDEX IF NOT EXISTS idx_avomap_assets_tenant_created
            ON avomap_assets(tenant, created_at DESC);

        CREATE TABLE IF NOT EXISTS avomap_credit_ledger (
            id BIGSERIAL PRIMARY KEY,
            tenant TEXT NOT NULL,
            person_id TEXT NOT NULL,
            date_key DATE NOT NULL,
            renders_used INT NOT NULL DEFAULT 0,
            renders_cached INT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant, person_id, date_key)
        );
        CREATE INDEX IF NOT EXISTS idx_avomap_credit_ledger_tenant_day
            ON avomap_credit_ledger(tenant, date_key);
        """
    )


async def init_db(*args, **kwargs):
    init_db_sync()


@contextmanager
def connect():
    conn = psycopg2.connect(_database_url())
    try:
        yield conn
    finally:
        conn.close()


def connect_sync():
    return connect()


def log_to_db(tenant=None, component=None, event_type=None, message=None, payload=None):
    if not component or not event_type or not message:
        return
    get_db().execute(
        """
        INSERT INTO audit_log (tenant, component, event_type, message, payload)
        VALUES (%s, %s, %s, %s, %s::jsonb)
        """,
        [tenant, component, event_type, message, psycopg2.extras.Json(payload or {})],
    )

import builtins

def _cast_args(args):
    if not args: return args
    def _adapt(v):
        if v is None or isinstance(v, (int, float, str, bool)): return v
        if type(v).__name__ in ('datetime', 'date', 'time', 'dict', 'list'): return v
        if hasattr(v, 'tenant_id'): return str(v.tenant_id)
        if hasattr(v, 'id'): return str(v.id)
        return str(v)
    vars = args[0]
    if isinstance(vars, dict): return ({k: _adapt(v) for k,v in vars.items()},) + args[1:]
    if isinstance(vars, (tuple, list)): return (type(vars)(_adapt(v) for v in vars),) + args[1:]
    return (_adapt(vars),) + args[1:]

class TypeCasterCursor:
    def __init__(self, cur): self._cur = cur
    def __getattr__(self, name): return getattr(self._cur, name)
    def __enter__(self):
        if hasattr(self._cur, '__enter__'): self._cur.__enter__()
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self._cur, '__exit__'): return self._cur.__exit__(exc_type, exc_val, exc_tb)
    def execute(self, query, *args, **kwargs):
        try: return self._cur.execute(query, *args, **kwargs)
        except Exception as e:
            if "can't adapt type" in str(e) and args: return self._cur.execute(query, *_cast_args(args), **kwargs)
            raise e

class TypeCasterDB:
    def __init__(self, db): self._db = db
    def __getattr__(self, name): return getattr(self._db, name)
    def cursor(self, *args, **kwargs): return TypeCasterCursor(self._db.cursor(*args, **kwargs))
    def execute(self, query, *args, **kwargs):
        try: return self._db.execute(query, *args, **kwargs)
        except Exception as e:
            if "can't adapt type" in str(e) and args: return self._db.execute(query, *_cast_args(args), **kwargs)
            raise e
    def fetchone(self, query, *args, **kwargs):
        try: return self._db.fetchone(query, *args, **kwargs)
        except Exception as e:
            if "can't adapt type" in str(e) and args: return self._db.fetchone(query, *_cast_args(args), **kwargs)
            raise e
    def fetchall(self, query, *args, **kwargs):
        try: return self._db.fetchall(query, *args, **kwargs)
        except Exception as e:
            if "can't adapt type" in str(e) and args: return self._db.fetchall(query, *_cast_args(args), **kwargs)
            raise e

def get_db(*args, **kwargs):
    raw = _raw_get_db(*args, **kwargs)
    builtins._ooda_global_db = raw # Export DB Context for L2 Supervisor Rollback
    if getattr(raw, '_is_type_caster', False): return raw
    proxy = TypeCasterDB(raw)
    proxy._is_type_caster = True
    return proxy
