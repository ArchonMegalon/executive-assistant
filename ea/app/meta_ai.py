import json
import logging
from app.db import get_db

async def trigger_browseract_rpa(tenant: str, platform: str, task: str, payload: dict):
    """
    META AI CORE (The Anti-Lazy Engine): 
    When APIs fail or don't exist, we don't bother the human. 
    We spawn a headless browser (BrowserAct) to do the UI clicking autonomously.
    """
    db = get_db()
    logging.warning(f"🤖 META AI ACTIVATED: Dispatching UI-RPA for {platform}. Task: {task}")
    
    script_payload = {
        "platform": platform,
        "task": task,
        "data": payload,
        "headless": True
    }
    
    # Der Roboter-Job wandert in die Warteschlange
    db.execute(
        "INSERT INTO browser_jobs (tenant, target_ltd, script_payload_json, status) VALUES (%s, %s, %s, 'queued')",
        (tenant, platform, json.dumps(script_payload))
    )
    return True
