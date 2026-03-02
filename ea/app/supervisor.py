import functools, logging, uuid, builtins, json

def supervised(fallback="telegram_text", failure_class="system_error", intent="unknown"):
    """
    v1.12.1 L2 Supervisor Decorator (Mum Brain).
    Catches optional skill failures, rolls back dirty transactions, logs to Mum Brain, 
    and returns safe text synchronously without blocking the user.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                db_conn = getattr(builtins, '_ooda_global_db', None)
                correlation_id = uuid.uuid4().hex[:8]
                err_msg = str(e).splitlines()[0][:150]
                
                logging.error(f"🚨 [L2 SUPERVISOR] Caught {type(e).__name__} in {func.__name__}. CorrID: {correlation_id}")
                
                # MANDATORY v1.12.1 RULE: Always rollback dirty DB state before fallback!
                if db_conn:
                    try:
                        if hasattr(db_conn, 'rollback'): db_conn.rollback()
                        elif hasattr(db_conn, 'conn') and hasattr(db_conn.conn, 'rollback'): db.conn.rollback()
                        logging.info("🧹 [L1: CHILD] DB transaction safely rolled back.")
                    except: pass

                # Asynchronous L2 Ticketing (AgentStuckEvent)
                if db_conn:
                    try:
                        sql = "INSERT INTO stuck_events (intent, failure_class, service_name, correlation_id, user_safe_context_json) VALUES (%s, %s, %s, %s, %s)"
                        ctx = json.dumps({"args_type": str(type(args)), "error_snippet": err_msg})
                        if hasattr(db_conn, 'execute'): db_conn.execute(sql, (intent, failure_class, func.__name__, correlation_id, ctx))
                        elif hasattr(db_conn, 'cursor'):
                            with db_conn.cursor() as cur: cur.execute(sql, (intent, failure_class, func.__name__, correlation_id, ctx))
                        
                        if hasattr(db_conn, 'commit'): db_conn.commit()
                        elif hasattr(db_conn, 'conn') and hasattr(db_conn.conn, 'commit'): db_conn.conn.commit()
                    except Exception as log_e:
                        logging.error(f"⚠️ [L2 SUPERVISOR] Failed to write event logs: {log_e}")
                        try:
                            if hasattr(db_conn, 'rollback'): db_conn.rollback()
                            elif hasattr(db_conn, 'conn') and hasattr(db_conn.conn, 'rollback'): db_conn.conn.rollback()
                        except: pass

                # SYNCHRONOUS FALLBACK: Return degraded text immediately to the user
                if fallback == "telegram_text":
                    logging.warning("⚠️ [L2 SUPERVISOR] Dropping visual layer. Executing inline text fallback.")
                    return f"⚠️ *Degraded Service*\nVisual rendering for {intent} failed. Showing plain text fallback."
                return fallback
        return wrapper
    return decorator
