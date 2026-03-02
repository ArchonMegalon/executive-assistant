from __future__ import annotations

import hashlib
import json
import random
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.db import get_db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProactivePlanner:
    def __init__(self) -> None:
        self.db = get_db()

    def _budget_row(self, tenant_key: str) -> dict[str, int]:
        day = date.today()
        self.db.execute(
            """
            INSERT INTO send_budgets (tenant_key, budget_day, sends_used, tokens_used, updated_at)
            VALUES (%s, %s, 0, 0, %s)
            ON CONFLICT (tenant_key, budget_day)
            DO NOTHING
            """,
            (tenant_key, day, _utcnow()),
        )
        row = self.db.fetchone(
            "SELECT sends_used, tokens_used FROM send_budgets WHERE tenant_key=%s AND budget_day=%s",
            (tenant_key, day),
        )
        return {"sends_used": int(row["sends_used"]), "tokens_used": int(row["tokens_used"])}

    def enqueue_candidates(self, *, tenant_key: str, candidates: list[dict[str, Any]]) -> list[int]:
        ids: list[int] = []
        for c in candidates:
            row = self.db.fetchone(
                """
                INSERT INTO planner_candidates (tenant_key, candidate_type, candidate_ref, normalized_payload_json, candidate_status, created_at)
                VALUES (%s, %s, %s, %s::jsonb, 'queued', %s)
                RETURNING candidate_id
                """,
                (tenant_key, str(c.get("type") or "unknown"), str(c.get("ref") or ""), json.dumps(c, ensure_ascii=False), _utcnow()),
            )
            ids.append(int(row["candidate_id"]))
        return ids

    def deterministic_prefilter(self, *, tenant_key: str, now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or _utcnow()
        muted = {
            str(r["candidate_type"])
            for r in (
                self.db.fetchall(
                    """
                    SELECT candidate_type FROM proactive_muted_classes
                    WHERE tenant_key=%s AND (muted_until IS NULL OR muted_until > %s)
                    """,
                    (tenant_key, now),
                )
                or []
            )
        }
        rows = self.db.fetchall(
            """
            SELECT candidate_id, candidate_type, candidate_ref, normalized_payload_json
            FROM planner_candidates
            WHERE tenant_key=%s AND candidate_status='queued'
            ORDER BY candidate_id ASC
            """,
            (tenant_key,),
        ) or []
        out: list[dict[str, Any]] = []
        seen_refs: set[str] = set()
        for r in rows:
            ctype = str(r["candidate_type"])
            cref = str(r["candidate_ref"])
            payload = r["normalized_payload_json"] or {}
            if ctype in muted:
                continue
            if not cref or cref in seen_refs:
                continue
            seen_refs.add(cref)
            # deterministic low-value drop
            text = json.dumps(payload, ensure_ascii=False).lower()
            if any(k in text for k in ("newsletter", "promo", "advert", "coupon")):
                continue
            out.append({"candidate_id": int(r["candidate_id"]), "type": ctype, "ref": cref, "payload": payload})
        return out

    def score_with_budget(
        self,
        *,
        tenant_key: str,
        candidates: list[dict[str, Any]],
        per_tenant_send_cap: int = 20,
        per_day_token_cap: int = 5000,
    ) -> list[dict[str, Any]]:
        budget = self._budget_row(tenant_key)
        remaining_sends = max(0, per_tenant_send_cap - budget["sends_used"])
        remaining_tokens = max(0, per_day_token_cap - budget["tokens_used"])
        scored: list[dict[str, Any]] = []
        for c in candidates:
            if remaining_sends <= 0 or remaining_tokens <= 0:
                break
            token_cost = 30 + min(220, len(json.dumps(c["payload"], ensure_ascii=False)) // 4)
            if token_cost > remaining_tokens:
                continue
            # cheap deterministic heuristic score
            t = c["type"]
            base = {
                "pre_meeting_briefing": 0.9,
                "due_soon_action": 0.8,
                "connector_repair_notice": 0.7,
                "watchlist_update": 0.5,
            }.get(t, 0.35)
            urgency = float((c["payload"] or {}).get("urgency", 0.0))
            score = base + urgency
            scored.append({**c, "score": score, "token_cost": token_cost})
            remaining_tokens -= token_cost
            remaining_sends -= 1
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored

    def schedule_items(
        self,
        *,
        tenant_key: str,
        scored: list[dict[str, Any]],
        channel: str = "telegram",
        jitter_seconds: int = 45,
    ) -> list[int]:
        created: list[int] = []
        now = _utcnow()
        sends_used = 0
        tokens_used = 0
        for item in scored:
            dedupe_key = hashlib.sha256(f"{tenant_key}:{item['type']}:{item['ref']}".encode("utf-8")).hexdigest()[:40]
            self.db.execute(
                """
                INSERT INTO planner_dedupe_keys (tenant_key, dedupe_key, created_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (tenant_key, dedupe_key) DO NOTHING
                """,
                (tenant_key, dedupe_key, now),
            )
            exists = self.db.fetchone(
                "SELECT proactive_item_id FROM proactive_items WHERE tenant_key=%s AND dedupe_key=%s",
                (tenant_key, dedupe_key),
            )
            if exists:
                continue
            send_at = now + timedelta(seconds=random.randint(0, max(0, jitter_seconds)))
            row = self.db.fetchone(
                """
                INSERT INTO proactive_items (tenant_key, candidate_id, channel, send_at, dedupe_key, payload_json, item_status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, 'scheduled', %s)
                RETURNING proactive_item_id
                """,
                (
                    tenant_key,
                    item["candidate_id"],
                    channel,
                    send_at,
                    dedupe_key,
                    json.dumps({"why_now": f"{item['type']} score={item['score']:.2f}", "payload": item["payload"]}, ensure_ascii=False),
                    now,
                ),
            )
            created.append(int(row["proactive_item_id"]))
            sends_used += 1
            tokens_used += int(item["token_cost"])
            self.db.execute(
                "UPDATE planner_candidates SET candidate_status='scheduled' WHERE candidate_id=%s",
                (item["candidate_id"],),
            )
        if sends_used or tokens_used:
            self.db.execute(
                """
                UPDATE send_budgets
                SET sends_used=sends_used+%s, tokens_used=tokens_used+%s, updated_at=%s
                WHERE tenant_key=%s AND budget_day=%s
                """,
                (sends_used, tokens_used, now, tenant_key, date.today()),
            )
        return created

