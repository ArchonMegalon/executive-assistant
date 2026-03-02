import json
import logging
import time
import builtins
from typing import Any

from app.repair.healer import process_recipe


def _get_db():
    db = getattr(builtins, '_ooda_global_db', None)
    if db:
        return db
    from app.db import get_db

    return get_db()


def _claim_jobs(db: Any, limit: int = 5) -> list[dict[str, Any]]:
    rows = db.fetchall(
        """
        WITH cte AS (
            SELECT job_id
            FROM repair_jobs
            WHERE status='pending'
            ORDER BY started_at ASC, job_id ASC
            LIMIT %s
            FOR UPDATE SKIP LOCKED
        )
        UPDATE repair_jobs j
        SET status='running', started_at=NOW()
        FROM cte
        WHERE j.job_id = cte.job_id
        RETURNING j.job_id, j.correlation_id, j.recipe_key, j.fault_class, COALESCE(j.max_attempts,3) AS max_attempts
        """,
        (limit,),
    )
    return rows or []


def process_repair_jobs(limit: int = 5) -> None:
    """Phase-B autonomous healer: execute real typed repairs and verify outcomes."""
    try:
        db = _get_db()
        jobs = _claim_jobs(db, limit=limit)
        if not jobs:
            return

        for job in jobs:
            job_id = int(job.get('job_id'))
            cid = str(job.get('correlation_id') or '')
            recipe = str(job.get('recipe_key') or '')
            fault_class = str(job.get('fault_class') or '')
            max_attempts = int(job.get('max_attempts') or 3)
            attempt_row = db.fetchone('SELECT COALESCE(MAX(attempt_no),0) AS n FROM repair_attempts WHERE job_id=%s', (job_id,))
            attempt_no = int((attempt_row or {}).get('n') or 0) + 1

            t0 = time.time()
            logging.info("🛠️ [MUM BRAIN] Executing recipe=%s job=%s corr=%s attempt=%s", recipe, job_id, cid or 'none', attempt_no)
            result = process_recipe(db, recipe, fault_class=fault_class, correlation_id=cid, tenant='ea_bot')
            duration_ms = int((time.time() - t0) * 1000)

            db.execute(
                'INSERT INTO repair_attempts (job_id, attempt_no, action_key, outcome, audit_json, duration_ms) VALUES (%s,%s,%s,%s,%s,%s)',
                (
                    job_id,
                    attempt_no,
                    result.action,
                    'success' if result.ok else 'failed',
                    json.dumps({'detail': result.detail[:280], 'recipe': recipe}),
                    duration_ms,
                ),
            )

            if result.ok:
                db.execute("UPDATE repair_jobs SET status='completed', finished_at=NOW() WHERE job_id=%s", (job_id,))
                logging.info("✅ [MUM BRAIN] Repair completed job=%s action=%s", job_id, result.action)
                continue

            if attempt_no < max_attempts:
                db.execute("UPDATE repair_jobs SET status='pending' WHERE job_id=%s", (job_id,))
                logging.warning("↻ [MUM BRAIN] Repair retry scheduled job=%s action=%s detail=%s", job_id, result.action, result.detail[:120])
                continue

            db.execute("UPDATE repair_jobs SET status='failed', finished_at=NOW() WHERE job_id=%s", (job_id,))
            db.execute(
                """
                INSERT INTO operator_tasks (correlation_id, task_type, priority, status, summary)
                VALUES (%s, 'repair_deadletter', 'high', 'open', %s)
                """,
                (cid or f'job_{job_id}', f"Repair failed after {attempt_no} attempts: {recipe} ({result.detail[:140]})"),
            )
            logging.error("🧯 [MUM BRAIN] Repair deadletter job=%s action=%s detail=%s", job_id, result.action, result.detail[:120])
    except Exception:
        logging.debug('repair_engine_suppressed', exc_info=True)
