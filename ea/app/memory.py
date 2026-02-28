import uuid
import logging

def save_button_context(prompt: str) -> str:
    action_id = str(uuid.uuid4().hex)[:16]
    try:
        from app.db import get_db
        db = get_db()
        db.execute("CREATE TABLE IF NOT EXISTS button_contexts (id VARCHAR(64) PRIMARY KEY, prompt TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW())")
        db.execute("INSERT INTO button_contexts (id, prompt) VALUES (%s, %s)", (action_id, prompt))
    except Exception as e:
        logging.error(f"Failed to save button context to Postgres: {e}")
    return action_id

def get_button_context(action_id: str) -> str:
    try:
        from app.db import get_db
        db = get_db()
        row = db.fetchone("SELECT prompt FROM button_contexts WHERE id = %s", (action_id,))
        if row:
            return row['prompt'] if isinstance(row, dict) else row[0]
    except Exception as e:
        logging.error(f"Failed to get button context: {e}")
    return None
