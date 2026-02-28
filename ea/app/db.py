import os, psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

_pool = None

def get_db():
    global _pool
    if _pool is None:
        url = os.environ.get("DATABASE_URL", "postgresql://postgres:secure_db_pass_2026@ea-db:5432/ea")
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 20, url)
    
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


# --- V1.5 EMERGENCY STUB ---
# Befriedigt den Python-Compiler nach dem Cache-Nuke
def log_to_db(*args, **kwargs):
    pass

# --- V1.7.1 BOOT STUBS ---
async def init_db(*args, **kwargs): pass
def init_db_sync(*args, **kwargs): pass

async def connect(*args, **kwargs): pass
def connect_sync(*args, **kwargs): pass
