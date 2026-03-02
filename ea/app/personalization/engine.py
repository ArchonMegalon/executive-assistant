from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from app.db import get_db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PersonalizationEngine:
    def __init__(self) -> None:
        self.db = get_db()

    def _upsert_cap(self, *, tenant_key: str, principal_id: str, is_negative: bool) -> dict[str, int]:
        window = date.today()
        self.db.execute(
            """
            INSERT INTO feedback_caps (tenant_key, principal_id, window_day, count_total, count_negative, updated_at)
            VALUES (%s, %s, %s, 1, %s, %s)
            ON CONFLICT (tenant_key, principal_id, window_day)
            DO UPDATE SET
                count_total = feedback_caps.count_total + 1,
                count_negative = feedback_caps.count_negative + EXCLUDED.count_negative,
                updated_at = EXCLUDED.updated_at
            """,
            (tenant_key, principal_id, window, 1 if is_negative else 0, _utcnow()),
        )
        row = self.db.fetchone(
            """
            SELECT count_total, count_negative
            FROM feedback_caps
            WHERE tenant_key=%s AND principal_id=%s AND window_day=%s
            """,
            (tenant_key, principal_id, window),
        )
        return {"count_total": int(row["count_total"]), "count_negative": int(row["count_negative"])}

    def record_feedback(
        self,
        *,
        tenant_key: str,
        principal_id: str,
        concept_key: str,
        feedback_type: str,
        raw_reason_code: str,
        item_ref: str,
    ) -> dict[str, Any]:
        is_negative = feedback_type in ("dislike", "hard_dislike", "ai_error")
        caps = self._upsert_cap(tenant_key=tenant_key, principal_id=principal_id, is_negative=is_negative)
        if caps["count_total"] > 250 or caps["count_negative"] > 120:
            self.db.execute(
                """
                INSERT INTO anomaly_flags (tenant_key, principal_id, anomaly_type, details_json, created_at)
                VALUES (%s, %s, 'feedback_cap_exceeded', %s::jsonb, %s)
                """,
                (tenant_key, principal_id, __import__("json").dumps(caps), _utcnow()),
            )
            return {"status": "rate_limited", "caps": caps}

        self.db.execute(
            """
            INSERT INTO feedback_events (feedback_type, action, briefing_item_id, concept_key, user_id, raw_reason_code, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (feedback_type, "ranking_signal", item_ref, concept_key, principal_id, raw_reason_code, _utcnow()),
        )
        if feedback_type == "ai_error":
            self.db.execute(
                """
                INSERT INTO ai_error_reviews (tenant_key, principal_id, item_ref, error_class, raw_reason_code, created_at)
                VALUES (%s, %s, %s, 'ai_error', %s, %s)
                """,
                (tenant_key, principal_id, item_ref, raw_reason_code, _utcnow()),
            )
            return {"status": "ai_error_recorded", "caps": caps}

        delta = 0.0
        hard_dislike = False
        if feedback_type == "like":
            delta = 0.25
        elif feedback_type == "dislike":
            delta = -0.40
        elif feedback_type == "hard_dislike":
            delta = -1.0
            hard_dislike = True

        self.db.execute(
            """
            INSERT INTO user_interest_profiles (tenant_key, principal_id, concept_key, weight, hard_dislike, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_key, principal_id, concept_key)
            DO UPDATE SET
                weight = GREATEST(-3.0, LEAST(3.0, user_interest_profiles.weight + EXCLUDED.weight)),
                hard_dislike = user_interest_profiles.hard_dislike OR EXCLUDED.hard_dislike,
                updated_at = EXCLUDED.updated_at
            """,
            (tenant_key, principal_id, concept_key, delta, hard_dislike, _utcnow()),
        )
        return {"status": "updated", "caps": caps}

    def rank_items(
        self,
        *,
        tenant_key: str,
        principal_id: str,
        items: list[dict[str, Any]],
        exploration_slot_percent: int = 10,
    ) -> list[dict[str, Any]]:
        prof_rows = self.db.fetchall(
            "SELECT concept_key, weight, hard_dislike FROM user_interest_profiles WHERE tenant_key=%s AND principal_id=%s",
            (tenant_key, principal_id),
        ) or []
        profile = {str(r["concept_key"]): {"weight": float(r["weight"]), "hard_dislike": bool(r["hard_dislike"])} for r in prof_rows}

        scored: list[dict[str, Any]] = []
        for idx, item in enumerate(items):
            concept = str(item.get("concept_key") or "")
            base = float(item.get("base_score") or 0.0)
            sig = profile.get(concept, {"weight": 0.0, "hard_dislike": False})
            if sig["hard_dislike"]:
                final = -999.0
            else:
                final = base + float(sig["weight"])
                if abs(final) < 0.05:
                    final = 0.0  # snap-to-neutral
            scored.append({**item, "_score": final, "_idx": idx})

        scored.sort(key=lambda x: (x["_score"], -x["_idx"]), reverse=True)
        keep_explore = max(0, int(len(scored) * max(0, exploration_slot_percent) / 100))
        if keep_explore > 0 and len(scored) > keep_explore:
            head = scored[:-keep_explore]
            tail = scored[-keep_explore:]
            scored = head + sorted(tail, key=lambda x: x["_idx"])  # deterministic capped exploration
        return scored

    def explain_item(
        self,
        *,
        tenant_key: str,
        principal_id: str,
        item_ref: str,
        concept_key: str,
        provenance: dict[str, Any],
        base_reason: str,
    ) -> str:
        row = self.db.fetchone(
            """
            SELECT weight, hard_dislike
            FROM user_interest_profiles
            WHERE tenant_key=%s AND principal_id=%s AND concept_key=%s
            """,
            (tenant_key, principal_id, concept_key),
        )
        if row and bool(row["hard_dislike"]):
            text = "Hidden by hard dislike preference."
        elif row:
            text = f"{base_reason} (personalization weight {float(row['weight']):+.2f})."
        else:
            text = f"{base_reason} (neutral profile)."
        self.db.execute(
            """
            INSERT INTO ranking_explanations (tenant_key, principal_id, item_ref, explanation_text, evidence_json, created_at)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s)
            """,
            (tenant_key, principal_id, item_ref, text, __import__("json").dumps(provenance), _utcnow()),
        )
        return text

