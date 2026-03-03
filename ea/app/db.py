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
            is_consumed BOOLEAN NOT NULL DEFAULT FALSE,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_typed_actions_ready ON typed_actions(tenant, action_type, is_consumed, expires_at);

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

        CREATE TABLE IF NOT EXISTS browser_jobs (
            job_id BIGSERIAL PRIMARY KEY,
            tenant TEXT NOT NULL,
            target_ltd TEXT NOT NULL,
            script_payload_json JSONB NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_browser_jobs_ready ON browser_jobs(status, created_at DESC);
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
