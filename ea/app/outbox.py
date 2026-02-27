import json, uuid
from app.db import get_db

def init_outbox_schema():
    db = get_db()
    db.execute("""
    CREATE TABLE IF NOT EXISTS tg_outbox(
      id UUID PRIMARY KEY,
      tenant TEXT NOT NULL,
      chat_id BIGINT NOT NULL,
      payload_json JSONB NOT NULL,
      status TEXT NOT NULL DEFAULT 'queued',
      attempt_count INT NOT NULL DEFAULT 0,
      next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      last_error TEXT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_tg_outbox_ready ON tg_outbox(status, next_attempt_at);")

def enqueue_outbox(tenant: str, chat_id: int, payload_dict: dict) -> str:
    db = get_db()
    outbox_id = str(uuid.uuid4())
    db.execute("""
        INSERT INTO tg_outbox (id, tenant, chat_id, payload_json)
        VALUES (%s, %s, %s, %s)
    """, (outbox_id, tenant, chat_id, json.dumps(payload_dict)))
    return outbox_id
