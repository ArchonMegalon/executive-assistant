import json
from app.db import get_db
from app.meta_ai import trigger_browseract_rpa

async def plan_and_build_survey(tenant: str, target_name: str, event_id: str):
    db = get_db()
    
    # 1. Logische Spezifikation des Formulars berechnen
    spec = {
        "title": f"Coaching Prep: {target_name}",
        "questions": [
            "What is your biggest operational tension right now?",
            "What do we need to decide today?"
        ],
        "hidden_fields": {"tenant": tenant, "event_id": event_id}
    }
    
    # 2. Request abspeichern
    row = db.fetchone("INSERT INTO survey_requests (tenant, blueprint_key, target_name, event_id, objective, context_json) VALUES (%s, 'coaching_prep', %s, %s, 'Coaching', %s) RETURNING request_id", (tenant, target_name, event_id, json.dumps(spec)))
    req_id = row['request_id'] if isinstance(row, dict) else row[0]
    
    # 3. THE "DON'T BE LAZY" MOVE: Roboter anweisen, das Formular physisch in MetaSurvey zu bauen
    await trigger_browseract_rpa(tenant, 'metasurvey', 'create_survey', {"request_id": str(req_id), "spec": spec})
    return req_id
