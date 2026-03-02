import functools, logging, uuid, builtins, asyncio, json
from app.delivery import register_delivery_session

def trigger_mum_brain(db_conn, e_msg, fallback_mode="simplified-first", failure_class="system_error", intent="unknown", chat_id="system"):
    """v1.12.5 L2 Supervisor Orchestrator (Phase A / Phase B)"""
    cid = uuid.uuid4().hex[:8]
    logging.error(f"🚨 [MUM BRAIN] Phase A Escalation for '{intent}'. Mode: {fallback_mode}. CorrID: {cid}")
    
    if db_conn is None:
        try:
            from app.db import get_db
            db_conn = get_db()
        except: pass

    def _db_commit(db):
        try:
            if hasattr(db, 'commit'):
                db.commit()
            elif hasattr(db, 'conn') and hasattr(db.conn, 'commit'):
                db.conn.commit()
        except:
            pass

    def _db_rollback(db):
        try:
            if hasattr(db, 'rollback'):
                db.rollback()
            elif hasattr(db, 'conn') and hasattr(db.conn, 'rollback'):
                db.conn.rollback()
        except:
            pass

    def _db_exec(db, query, params):
        # Prefer execute() for DB manager wrappers that do not expose raw cursors.
        if hasattr(db, 'execute'):
            db.execute(query, params)
            return
        if hasattr(db, 'cursor'):
            with db.cursor() as cur:
                cur.execute(query, params)
            return
        raise AttributeError("db_execute_unavailable")

    if db_conn:
        try:
            # MANDATORY: Rollback dirty transactions before continuing
            _db_rollback(db_conn)
            logging.info("🧹 [L1: CHILD] DB transaction cleanly rolled back before fallback.")
        except: pass
        
        try:
            sql_stuck = "INSERT INTO stuck_events (intent, failure_class, service_name, correlation_id, user_safe_context_json) VALUES (%s, %s, %s, %s, %s)"
            ctx = json.dumps({"error_snippet": str(e_msg)[:200]})
            
            recipe_key = "breaker_open_optional"
            if "markup" in failure_class.lower() or "render" in intent.lower() or "fst" in failure_class.lower():
                recipe_key = "renderer_template_swap"
                
            sql_repair = "INSERT INTO repair_jobs (correlation_id, fault_class, recipe_key, status) VALUES (%s, %s, %s, %s)"
            
            _db_exec(db_conn, sql_stuck, (intent, failure_class, 'inline_fallback', cid, ctx))
            _db_exec(db_conn, sql_repair, (cid, failure_class, recipe_key, 'pending'))

            _db_commit(db_conn)
            logging.info(f"📋 [PHASE B] Bounded repair recipe scheduled: {recipe_key}")
        except Exception as log_e:
            logging.error(f"⚠️ [MUM BRAIN] Failed to write event logs: {log_e}")
            _db_rollback(db_conn)
            
    # Phase A Registration
    register_delivery_session(cid, chat_id, fallback_mode)
    return cid

def supervised(fallback_mode="simplified-first", failure_class="system_error", intent="unknown"):
    """v1.12.5 L2 Supervisor Decorator"""
    def decorator(func):
        def _handle_failure(e, args, func_name):
            from app.telegram.safety import sanitize_for_telegram
            db = getattr(builtins, '_ooda_global_db', None)
            cid = trigger_mum_brain(db, str(e), fallback_mode=fallback_mode, failure_class=failure_class, intent=intent)
            return sanitize_for_telegram(str(e), cid, mode=fallback_mode)

        import asyncio
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
