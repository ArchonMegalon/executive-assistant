import json
import logging
import asyncio
from app.db import get_db
from app.llm import ask_llm

def is_qualifying_coach_event(event: dict, cfg: dict) -> bool:
    title = (event.get("summary") or "").lower()
    desc = (event.get("description") or "").lower()
    keywords = [k.lower() for k in cfg.get("qualifying_keywords", ["coaching", "coach", "mentoring"])]
    if event.get("status") == "cancelled": return False
    haystack = f"{title}\n{desc}"
    return any(k in haystack for k in keywords)

async def resolve_person_role(tenant: str, name: str) -> dict:
    try:
        db = get_db()
        row = await asyncio.to_thread(db.fetchone, "SELECT * FROM person_profiles WHERE tenant = %s AND normalized_name = %s", (tenant, name.lower()))
        if row: return {"role": row['role_title'], "org": row['organization']}
    except Exception: pass
    
    prompt = f"SYSTEM RULE: You are a role resolver. Who is '{name}' in the context of Austrian business/Industriellenvereinigung (IV)? Return STRICT JSON: {{\"role\": \"...\", \"org\": \"...\"}}. If unknown, return nulls."
    try:
        res = await asyncio.to_thread(ask_llm, prompt)
        res = res.replace("```json", "").replace("```", "").strip()
        data = json.loads(res)
        
        # Cache the result
        try:
            db = get_db()
            db.execute("INSERT INTO person_profiles (tenant, normalized_name, full_name, role_title, organization) VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING", 
                       (tenant, name.lower(), name, data.get("role"), data.get("org")))
        except Exception: pass
        return data
    except Exception:
        return {"role": None, "org": None}

async def generate_coach_annex(tenant: str, event: dict) -> str:
    title = event.get("summary", "")
    desc = event.get("description", "")
    
    name = await asyncio.to_thread(ask_llm, f"Extract ONLY the full name of the coaching counterpart from this event. Event: {title} {desc}")
    name = name.replace("```", "").strip()
    if not name or len(name) > 50: name = "Counterpart"
        
    role_data = await resolve_person_role(tenant, name)
    role_str = f"{role_data.get('role', 'Role unresolved')} at {role_data.get('org', 'Org unresolved')}"
    if not role_data.get('role'):
        role_str = "Role unresolved (Keep briefing conservative)"
        
    brief_prompt = f"""SYSTEM RULE: Generate a strict 70/20/10 Coach Briefing Annex for the executive meeting with '{name}'.
Role Context: {role_str}

Format in Telegram Markdown:
- 👤 Person & Rolle: {name}, {role_str}
- 🎯 Kernlage: (4 short sentences on their high-level situation)
- 📈 3 Aktuelle Themen: (Role-relevant developments)
- ⚡ 3 Druckpunkte / Spannungsfelder: (Tension points)
- ❓ 3 Coaching-Fragen: (Open useful angles)
- ⚠️ Watch-out: (Tone guidance)
"""
    return await asyncio.to_thread(ask_llm, brief_prompt)
