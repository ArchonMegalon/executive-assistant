import re, logging, builtins

FORBIDDEN_PATTERNS = [
    (r'\{.*"statusCode".*\}', "JSON_ERROR_PAYLOAD"),
    (r'Traceback \(most recent call last\)', "PYTHON_TRACEBACK"),
    (r'OODA Diagnostic', "INTERNAL_DIAGNOSTIC"),
    (r'Diagnostics:', "INTERNAL_DIAGNOSTIC"),
    (r'Provider Response', "PROVIDER_LEAK"),
    (r'template_id=', "INTERNAL_ID_LEAK"),
    (r'FST_ERR_VALIDATION', "RAW_API_ERROR")
]

def sanitize_for_telegram(text, correlation_id="unknown", mode="simplified-first", message_kind="briefing"):
    """
    v1.12.5 Send Boundary Sanitizer.
    Guarantees zero leakage and logs blocked attempts to sanitizer_audits.
    """
    if not isinstance(text, str): return text
    
    tripped = False
    reason = ""

    for pat, reason_code in FORBIDDEN_PATTERNS:
        if re.search(pat, text, re.IGNORECASE | re.DOTALL):
            tripped = True
            reason = reason_code
            break

    if tripped:
        logging.warning(f"🛡️ [SEND BOUNDARY] Blocked unsafe outbound message! Reason: {reason}")
        
        db = getattr(builtins, '_ooda_global_db', None)
        if db:
            try:
                sql = "INSERT INTO sanitizer_audits (correlation_id, message_kind, matched_rule, replacement_kind) VALUES (%s, %s, %s, %s)"
                if hasattr(db, 'execute'): db.execute(sql, (correlation_id, message_kind, reason, mode))
                elif hasattr(db, 'cursor'):
                    with db.cursor() as cur: cur.execute(sql, (correlation_id, message_kind, reason, mode))
                if hasattr(db, 'commit'): db.commit()
                elif hasattr(db, 'conn') and hasattr(db.conn, 'commit'): db.conn.commit()
            except: pass
                
        # v1.12.5 Mandated Fallback Copy based on Mode
        if mode == "status-first":
            return f"⏳ *Preparing your briefing in safe mode...*\n_(Formatting repair in progress - Ticket {correlation_id})_"
        return f"⚠️ *Delivered in simplified mode today.*\nVisual formatting is temporarily unavailable. _(Ticket {correlation_id})_"
        
    return text
