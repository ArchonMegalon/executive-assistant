from __future__ import annotations

from dataclasses import dataclass, field

from app.intelligence.epics import Epic, rank_epics
from app.intelligence.profile import PersonProfileContext
from app.intelligence.readiness import ReadinessDossier


@dataclass(frozen=True)
class PreparationPlan:
    actions: tuple[str, ...] = field(default_factory=tuple)
    deferred: tuple[str, ...] = field(default_factory=tuple)
    confidence_note: str = ""


def build_preparation_plan(
    *,
    profile: PersonProfileContext,
    readiness: ReadinessDossier,
    epics: tuple[Epic, ...] | list[Epic] = (),
) -> PreparationPlan:
    actions: list[str] = []
    deferred: list[str] = []

    for action in readiness.suggested_actions:
        if action and len(actions) < 5:
            actions.append(str(action))

    ranked = rank_epics(epics)
    for epic in ranked[:3]:
        if int(epic.unresolved_count) > 0 and int(epic.salience) >= 60:
            actions.append(
                f"Resolve open items for {epic.title} (salience {int(epic.salience)})."
            )
        elif int(epic.unresolved_count) == 0:
            deferred.append(f"{epic.title}: monitor only.")

    if readiness.status == "critical":
        actions.insert(0, "Treat readiness as critical and handle blockers first.")

    # Deduplicate while preserving order.
    dedup_actions: list[str] = []
    seen = set()
    for action in actions:
        key = action.lower().strip()
        if key and key not in seen:
            seen.add(key)
            dedup_actions.append(action)

    confidence_note = ""
    if profile.confidence.state == "degraded":
        confidence_note = profile.confidence.note or "Runtime confidence reduced."

    return PreparationPlan(
        actions=tuple(dedup_actions[:6]),
        deferred=tuple(deferred[:4]),
        confidence_note=str(confidence_note).strip(),
    )
