import uuid, hashlib, json, datetime, builtins
import logging

def generate_safe_callback(user_id, chat_id, action_family, context_dict, ttl_hours=24):
    """
    v1.12.1 M2: Generates a <=64 byte Telegram callback_data token 
    and stores the rich JSON payload securely in the database.
    """
    raw_token = str(uuid.uuid4())
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()[:16] 
    
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=ttl_hours)
    
    try:
        db_conn = getattr(builtins, '_ooda_global_db', None)
        if not db_conn:
            # Fallback import if builtins hook is not active
            from app.db import get_db
            db_conn = get_db()

        sql = "INSERT INTO telegram_callback_states (token_hash, user_id, chat_id, action_family, raw_context_json, expires_at) VALUES (%s, %s, %s, %s, %s, %s)"
        params = (token_hash, str(user_id), str(chat_id), action_family, json.dumps(context_dict), expires_at)
        
        if hasattr(db_conn, 'execute'):
            db_conn.execute(sql, params)
        elif hasattr(db_conn, 'cursor'):
            with db_conn.cursor() as cur:
                cur.execute(sql, params)
                
        if hasattr(db_conn, 'commit'): db_conn.commit()
        elif hasattr(db_conn, 'conn') and hasattr(db_conn.conn, 'commit'): db_conn.conn.commit()
    except Exception as e:
        logging.error(f"Callback generation failed: {e}")
        try:
            if hasattr(db_conn, 'rollback'): db_conn.rollback()
            elif hasattr(db_conn, 'conn') and hasattr(db_conn.conn, 'rollback'): db_conn.conn.rollback()
        except: pass
        
    return f"cb:{token_hash[:8]}:{action_family[:10]}"
