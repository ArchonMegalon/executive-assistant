def is_qualifying_coach_event(event: dict, cfg: dict) -> bool:
    title = (event.get("summary") or "").lower()
    desc = (event.get("description") or "").lower()
    keywords = [k.lower() for k in cfg.get("qualifying_keywords", ["coaching", "coach", "mentoring"])]
    if event.get("status") == "cancelled": return False
    haystack = f"{title}\n{desc}"
    return any(k in haystack for k in keywords)
