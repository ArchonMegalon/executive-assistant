import functools, logging, uuid, builtins, asyncio, json

def trigger_mum_brain(db_conn, e_msg, fallback="telegram_text", failure_class="system_error", intent="unknown"):
    """v1.12.1 L2 Supervisor Programmatic API"""
    cid = uuid.uuid4().hex[:8]
    logging.error(f"🚨 [L2 SUPERVISOR] Escalation triggered for '{intent}'. CorrID: {cid}. Msg: {str(e_msg)[:100]}...")
    
    # MANDATORY: Erase dirty transaction state!
    if db_conn:
        try:
            if hasattr(db_conn, 'rollback'): db_conn.rollback()
            elif hasattr(db_conn, 'conn') and hasattr(db_conn.conn, 'rollback'): db_conn.conn.rollback()
            logging.info("🧹 [L1: CHILD] DB transaction cleanly rolled back.")
        except: pass
        
        # Async Ticketing (Stuck Event)
        try:
            sql = "INSERT INTO stuck_events (intent, failure_class, correlation_id, user_safe_context_json) VALUES (%s, %s, %s, %s)"
            ctx = json.dumps({"error_snippet": str(e_msg)[:200]})
            if hasattr(db_conn, 'execute'): db_conn.execute(sql, (intent, failure_class, cid, ctx))
            elif hasattr(db_conn, 'cursor'):
                with db_conn.cursor() as cur: cur.execute(sql, (intent, failure_class, cid, ctx))
            if hasattr(db_conn, 'commit'): db_conn.commit()
            elif hasattr(db_conn, 'conn') and hasattr(db_conn.conn, 'commit'): db_conn.conn.commit()
        except Exception as log_e:
            logging.error(f"⚠️ [L2 SUPERVISOR] Failed to write event logs: {log_e}")
            try:
                if hasattr(db_conn, 'rollback'): db_conn.rollback()
                elif hasattr(db_conn, 'conn') and hasattr(db_conn.conn, 'rollback'): db_conn.conn.rollback()
            except: pass
            
    return cid

def supervised(fallback="telegram_text", failure_class="system_error", intent="unknown"):
    """v1.12.1 L2 Supervisor Decorator"""
    def decorator(func):
        def _handle_failure(e, args, func_name):
            db = getattr(builtins, '_ooda_global_db', None)
            cid = trigger_mum_brain(db, str(e), fallback, failure_class, intent)
            if fallback == "telegram_text":
                logging.warning("⚠️ [L2 SUPERVISOR] Dropping visual layer. Executing inline text fallback.")
                return f"⚠️ *Degraded Service*\nVisual rendering for `{intent}` failed, but your briefing is safe.\n\n_(Error logged for engineering: `{cid}`)_"
            return fallback

        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                try: return await func(*args, **kwargs)
                except Exception as e: return _handle_failure(e, args, func.__name__)
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                try: return func(*args, **kwargs)
                except Exception as e: return _handle_failure(e, args, func.__name__)
            return sync_wrapper
    return decorator
