import logging, builtins, datetime

def register_delivery_session(correlation_id, chat_id, mode):
    """v1.12.5: Tracks Phase A delivery so Mum Brain (Phase B) knows if it has an enhancement window."""
    db = getattr(builtins, '_ooda_global_db', None)
    if not db: return
    try:
        deadline = datetime.datetime.utcnow() + datetime.timedelta(minutes=5)
        sql = "INSERT INTO delivery_sessions (correlation_id, chat_id, mode, status, enhancement_deadline_ts) VALUES (%s, %s, %s, %s, %s)"
        
        if hasattr(db, 'execute'): db.execute(sql, (correlation_id, str(chat_id), mode, 'active', deadline))
        elif hasattr(db, 'cursor'):
            with db.cursor() as cur: cur.execute(sql, (correlation_id, str(chat_id), mode, 'active', deadline))
            
        if hasattr(db, 'commit'): db.commit()
        elif hasattr(db, 'conn') and hasattr(db.conn, 'commit'): db.conn.commit()
        logging.info(f"📦 [PHASE A] Delivery session registered. Mode: {mode}. CorrID: {correlation_id}")
    except Exception as e:
        logging.error(f"Delivery session registration failed: {e}")
        try:
            if hasattr(db, 'rollback'): db.rollback()
            elif hasattr(db, 'conn') and hasattr(db.conn, 'rollback'): db.conn.rollback()
        except: pass
