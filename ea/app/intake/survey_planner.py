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


async def plan_article_preference_survey(*, tenant: str, principal: str, article_refs: list[dict]) -> bool:
    """
    Post-briefing learning loop:
    Ask lightweight preference questions so future article ranking adapts to user taste.
    """
    db = get_db()
    refs = article_refs[:8]
    spec = {
        "title": "Reading Preference Calibration",
        "questions": [
            "Which publishers were most useful today?",
            "Which topics should be prioritized next time?",
            "How deep should article detail be? (short / medium / full)",
            "What should be suppressed in future reading briefs?",
        ],
        "choices": {
            "publishers": ["The Economist", "The Atlantic", "The New York Times", "Other"],
            "depth": ["short", "medium", "full"],
        },
        "hidden_fields": {
            "tenant": tenant,
            "principal": principal,
            "article_refs": refs,
        },
    }
    row = db.fetchone(
        """
        INSERT INTO survey_requests (tenant, blueprint_key, target_name, event_id, objective, context_json)
        VALUES (%s, 'article_preference', %s, %s, 'Personalization', %s)
        RETURNING request_id
        """,
        (tenant, principal, f"article_pref_{principal}", json.dumps(spec)),
    )
    req_id = row["request_id"] if isinstance(row, dict) else row[0]
    await trigger_browseract_rpa(
        tenant,
        "metasurvey",
        "create_survey",
        {"request_id": str(req_id), "spec": spec},
    )
    return True


async def plan_briefing_feedback_survey(*, tenant: str, principal: str, briefing_excerpt: str) -> bool:
    """
    Post-/brief feedback loop for personalization:
    asks what to prioritize/suppress and preferred depth.
    """
    db = get_db()
    spec = {
        "title": "Briefing Feedback Calibration",
        "questions": [
            "Which topics should be prioritized in your next briefing?",
            "Which topics should be suppressed?",
            "Which sources/publishers were useful today?",
            "Preferred detail depth for briefings? (short / medium / full)",
        ],
        "choices": {
            "depth": ["short", "medium", "full"],
        },
        "hidden_fields": {
            "tenant": tenant,
            "principal": principal,
            "kind": "briefing_feedback",
            "briefing_excerpt": (briefing_excerpt or "")[:1200],
        },
    }
    row = db.fetchone(
        """
        INSERT INTO survey_requests (tenant, blueprint_key, target_name, event_id, objective, context_json)
        VALUES (%s, 'briefing_feedback', %s, %s, 'Personalization', %s)
        RETURNING request_id
        """,
        (tenant, principal, f"brief_pref_{principal}", json.dumps(spec)),
    )
    req_id = row["request_id"] if isinstance(row, dict) else row[0]
    await trigger_browseract_rpa(
        tenant,
        "metasurvey",
        "create_survey",
        {"request_id": str(req_id), "spec": spec},
    )
    return True
