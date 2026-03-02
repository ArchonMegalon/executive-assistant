import os
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

_pool = None


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://postgres:secure_db_pass_2026@ea-db:5432/ea")

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
        CREATE TABLE IF NOT EXISTS audit_log (
            ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            tenant TEXT,
            component TEXT NOT NULL,
            event_type TEXT NOT NULL,
            message TEXT NOT NULL,
            payload JSONB
        );
        CREATE INDEX IF NOT EXISTS audit_log_ts_idx ON audit_log(ts DESC);
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
    builtins._ooda_global_db = raw # Export DB Kontext für den L2 Supervisor Rollback
    if getattr(raw, '_is_type_caster', False): return raw
    proxy = TypeCasterDB(raw)
    proxy._is_type_caster = True
    return proxy
