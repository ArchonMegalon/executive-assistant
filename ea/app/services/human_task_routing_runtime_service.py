from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from app.domain.models import ExecutionEvent, HumanTask, OperatorProfile
from app.repositories.human_tasks import _parse_assignment_source_filter

SortKey = str | None
FetchEventsFn = Callable[[str], list[ExecutionEvent]]


class HumanTaskRoutingService:
    _TRUST_RANK = {
        "junior": 0,
        "standard": 1,
        "senior": 2,
        "exec_delegate": 3,
        "principal_delegate": 3,
    }
    _HUMAN_TASK_PRIORITY_RANK = {
        "urgent": 3,
        "high": 2,
        "normal": 1,
        "medium": 1,
        "low": 0,
    }
    _HUMAN_TASK_ASSIGNMENT_EVENT_NAMES = {
        "human_task_created",
        "human_task_assigned",
        "human_task_claimed",
        "human_task_returned",
    }
    _AUTHORITY_RANK = {
        "": 0,
        "review": 0,
        "draft_review": 0,
        "send_on_behalf_review": 2,
        "principal_sensitive_review": 3,
        "principal_review": 3,
    }
    _RANK_TO_TIER = {
        0: "junior",
        1: "standard",
        2: "senior",
        3: "principal_delegate",
    }

    def __init__(
        self,
        *,
        list_profiles_for_principal: Callable[[str], list[OperatorProfile]],
        fetch_session_events: FetchEventsFn,
    ) -> None:
        self._list_profiles_for_principal = list_profiles_for_principal
        self._fetch_session_events = fetch_session_events

    def _required_skill_tags(self, row: HumanTask) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    str(v).strip().lower()
                    for v in ((row.quality_rubric_json or {}).get("checks") or [])
                    if str(v).strip()
                }
            )
        )

    def required_skill_tags(self, row: HumanTask) -> tuple[str, ...]:
        return self._required_skill_tags(row)

    def _required_trust_rank(self, authority_required: str) -> int:
        return self._AUTHORITY_RANK.get(str(authority_required or "").strip().lower(), 0)

    def required_trust_rank(self, authority_required: str) -> int:
        return self._required_trust_rank(authority_required)

    def _required_trust_tier(self, authority_required: str) -> str:
        return self._RANK_TO_TIER.get(self._required_trust_rank(authority_required), "standard")

    def required_trust_tier(self, authority_required: str) -> str:
        return self._required_trust_tier(authority_required)

    def build_human_task_routing_hints(self, row: HumanTask) -> dict[str, object]:
        profiles = self._list_profiles_for_principal(
            principal_id=row.principal_id,
        )
        suggestions: list[dict[str, object]] = []
        exact_matches: list[dict[str, object]] = []
        for profile in profiles:
            details = self.operator_match_details(profile, row)
            if not bool(details["role_match"]) or not bool(details["authority_ok"]):
                continue
            suggestion = {
                "operator_id": profile.operator_id,
                "display_name": profile.display_name,
                "trust_tier": profile.trust_tier,
                "score": int(details["score"]),
                "matched_skill_tags": list(details["matched_skill_tags"]),
                "missing_skill_tags": list(details["missing_skill_tags"]),
            }
            suggestions.append(suggestion)
            if bool(details["exact_match"]):
                exact_matches.append(suggestion)
        suggestions.sort(
            key=lambda item: (
                len(item["missing_skill_tags"]),  # type: ignore[arg-type]
                -int(item["score"]),
                str(item["display_name"]),
                str(item["operator_id"]),
            )
        )
        exact_matches.sort(
            key=lambda item: (
                -int(item["score"]),
                str(item["display_name"]),
                str(item["operator_id"]),
            )
        )
        suggested_operator_ids = [str(item["operator_id"]) for item in suggestions[:3]]
        recommended_operator_id = str(suggested_operator_ids[0]) if suggested_operator_ids else ""
        auto_assign_operator_id = ""
        if (
            row.status == "pending"
            and row.assignment_state == "unassigned"
            and len(exact_matches) == 1
            and exact_matches[0]["operator_id"] == recommended_operator_id
        ):
            auto_assign_operator_id = recommended_operator_id
        return {
            "required_skill_tags": list(self._required_skill_tags(row)),
            "required_trust_tier": self._required_trust_tier(row.authority_required),
            "candidate_count": len(suggestions),
            "suggested_operator_ids": suggested_operator_ids,
            "recommended_operator_id": recommended_operator_id,
            "auto_assign_operator_id": auto_assign_operator_id,
            "suggestions": suggestions[:3],
        }

    def operator_match_details(self, profile: OperatorProfile, row: HumanTask) -> dict[str, object]:
        roles = {str(v).strip() for v in profile.roles if str(v).strip()}
        role_required = str(row.role_required or "").strip()
        role_match = not role_required or not roles or role_required in roles
        required_skill_tags = set(self._required_skill_tags(row))
        operator_skill_tags = {str(v).strip().lower() for v in profile.skill_tags if str(v).strip()}
        matched_skill_tags = tuple(sorted(required_skill_tags & operator_skill_tags))
        missing_skill_tags = tuple(sorted(required_skill_tags - operator_skill_tags))
        trust_rank = self._TRUST_RANK.get(str(profile.trust_tier or "").strip().lower(), 1)
        required_rank = self._required_trust_rank(row.authority_required)
        authority_ok = trust_rank >= required_rank
        exact_match = role_match and authority_ok and not missing_skill_tags
        score = (
            (100 if exact_match else 0)
            + (20 if role_match else 0)
            + (len(matched_skill_tags) * 10)
            - (len(missing_skill_tags) * 5)
            + trust_rank
        )
        return {
            "role_match": role_match,
            "matched_skill_tags": matched_skill_tags,
            "missing_skill_tags": missing_skill_tags,
            "authority_ok": authority_ok,
            "exact_match": exact_match,
            "score": score,
        }

    def _human_task_assignment_events(self, row: HumanTask) -> list[ExecutionEvent]:
        return [
            event
            for event in self._fetch_session_events(row.session_id)
            if event.name in self._HUMAN_TASK_ASSIGNMENT_EVENT_NAMES
            and str((event.payload or {}).get("human_task_id") or "") == row.human_task_id
        ]

    def human_task_assignment_events(self, row: HumanTask) -> list[ExecutionEvent]:
        return self._human_task_assignment_events(row)

    def build_human_task_last_transition_summary(self, row: HumanTask) -> dict[str, object]:
        events = self._human_task_assignment_events(row)
        if not events:
            return {
                "last_transition_event_name": "",
                "last_transition_at": None,
                "last_transition_assignment_state": "",
                "last_transition_operator_id": "",
                "last_transition_assignment_source": "",
                "last_transition_by_actor_id": "",
            }
        last = events[-1]
        payload = dict(last.payload or {})
        return {
            "last_transition_event_name": last.name,
            "last_transition_at": str(last.created_at or "") or None,
            "last_transition_assignment_state": str(payload.get("assignment_state") or row.assignment_state or ""),
            "last_transition_operator_id": str(
                payload.get("assigned_operator_id") or payload.get("operator_id") or row.assigned_operator_id or ""
            ),
            "last_transition_assignment_source": str(payload.get("assignment_source") or row.assignment_source or ""),
            "last_transition_by_actor_id": str(payload.get("assigned_by_actor_id") or row.assigned_by_actor_id or ""),
        }

    def sort_human_tasks(self, rows: list[HumanTask], *, sort: SortKey = None) -> list[HumanTask]:
        sort_key = str(sort or "").strip().lower()
        if sort_key == "priority_desc_created_asc":
            return sorted(
                rows,
                key=lambda row: (
                    -self._HUMAN_TASK_PRIORITY_RANK.get(str(row.priority or "").strip().lower(), 1),
                    str(row.created_at or ""),
                    str(row.human_task_id or ""),
                ),
            )
        if sort_key == "created_asc":
            return sorted(
                rows,
                key=lambda row: (str(row.created_at or ""), str(row.human_task_id or "")),
            )
        if sort_key == "created_desc":
            return sorted(
                rows,
                key=lambda row: (str(row.created_at or ""), str(row.human_task_id or "")),
                reverse=True,
            )
        if sort_key == "last_transition_desc":
            return sorted(
                rows,
                key=lambda row: (
                    str(row.last_transition_at or ""),
                    str(row.created_at or ""),
                    str(row.human_task_id or ""),
                ),
                reverse=True,
            )
        if sort_key == "sla_due_at_asc":
            with_sla = sorted(
                [row for row in rows if row.sla_due_at],
                key=lambda row: (
                    str(row.sla_due_at or ""),
                    str(row.created_at or ""),
                    str(row.human_task_id or ""),
                ),
            )
            without_sla = sorted(
                [row for row in rows if not row.sla_due_at],
                key=lambda row: (
                    str(row.created_at or ""),
                    str(row.human_task_id or ""),
                ),
            )
            return with_sla + without_sla
        if sort_key == "sla_due_at_asc_last_transition_desc":
            with_sla = sorted(
                self.sort_human_tasks([row for row in rows if row.sla_due_at], sort="last_transition_desc"),
                key=lambda row: str(row.sla_due_at or ""),
            )
            without_sla = sorted(
                [row for row in rows if not row.sla_due_at],
                key=(
                    lambda row: (
                        str(row.created_at or ""),
                        str(row.human_task_id or ""),
                    )
                ),
            )
            return with_sla + without_sla
        return rows

    def filter_human_task_rows(
        self,
        rows: list[HumanTask],
        *,
        principal_id: str,
        status: str | None = None,
        role_required: str | None = None,
        priority: str | None = None,
        assigned_operator_id: str | None = None,
        assignment_state: str | None = None,
        assignment_source: str | None = None,
        overdue_only: bool = False,
    ) -> list[HumanTask]:
        principal = str(principal_id or "").strip()
        status_filter = str(status or "").strip()
        role_filter = str(role_required or "").strip()
        priority_filters = {
            value.strip().lower()
            for value in str(priority or "").split(",")
            if value.strip()
        }
        operator_filter = str(assigned_operator_id or "").strip()
        assignment_filter = str(assignment_state or "").strip().lower()
        has_source_filter, source_filter = _parse_assignment_source_filter(assignment_source)

        filtered = [row for row in rows if row.principal_id == principal]
        if status_filter:
            filtered = [row for row in filtered if row.status == status_filter]
        if role_filter:
            filtered = [row for row in filtered if row.role_required == role_filter]
        if priority_filters:
            filtered = [row for row in filtered if str(row.priority or "").strip().lower() in priority_filters]
        if operator_filter:
            filtered = [row for row in filtered if row.assigned_operator_id == operator_filter]
        if assignment_filter:
            filtered = [row for row in filtered if row.assignment_state == assignment_filter]
        if has_source_filter:
            filtered = [row for row in filtered if row.assignment_source == source_filter]
        if overdue_only:
            now = datetime.now(timezone.utc)
            overdue_rows: list[HumanTask] = []
            for row in filtered:
                raw = str(row.sla_due_at or "").strip()
                if not raw:
                    continue
                try:
                    due = datetime.fromisoformat(raw)
                except ValueError:
                    continue
                if due.tzinfo is None:
                    due = due.replace(tzinfo=timezone.utc)
                if due <= now:
                    overdue_rows.append(row)
            filtered = overdue_rows
        return filtered

    def operator_matches_human_task(self, profile: OperatorProfile, row: HumanTask) -> bool:
        details = self.operator_match_details(profile, row)
        return bool(details["exact_match"])

    def decorate_human_task(self, row: HumanTask) -> HumanTask:
        return row.replace(
            routing_hints_json=self.build_human_task_routing_hints(row),
            **self.build_human_task_last_transition_summary(row),
        )
