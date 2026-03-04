from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.intelligence.dossiers import Dossier
from app.intelligence.profile import PersonProfileContext


@dataclass(frozen=True)
class FutureSituation:
    kind: str
    title: str
    horizon_hours: int
    confidence: float
    evidence: tuple[str, ...] = field(default_factory=tuple)


def _event_start_utc(event: dict) -> datetime | None:
    start = event.get("start", {})
    value = ""
    if isinstance(start, dict):
        value = str(start.get("dateTime") or start.get("date") or "").strip()
    else:
        value = str(start or "").strip()
    if not value:
        return None
    try:
        if "T" in value:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(value + "T00:00:00+00:00")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def build_future_situations(
    *,
    profile: PersonProfileContext,
    dossiers: list[Dossier],
    calendar_events: list[dict] | None = None,
    horizon_hours: int = 72,
) -> tuple[FutureSituation, ...]:
    now = datetime.now(timezone.utc)
    out: list[FutureSituation] = []

    for dossier in dossiers or []:
        if dossier.kind != "trip" or dossier.signal_count <= 0:
            continue
        if dossier.near_term:
            out.append(
                FutureSituation(
                    kind="travel_window",
                    title="Near-term travel window",
                    horizon_hours=horizon_hours,
                    confidence=0.78,
                    evidence=tuple(dossier.evidence[:2]),
                )
            )
        if dossier.risk_hits:
            hits = ", ".join(dossier.risk_hits[:3])
            out.append(
                FutureSituation(
                    kind="risk_intersection",
                    title=f"Travel route intersects risk signals ({hits})",
                    horizon_hours=horizon_hours,
                    confidence=0.82,
                    evidence=tuple(dossier.evidence[:2]),
                )
            )

    upcoming = 0
    for event in calendar_events or []:
        ts = _event_start_utc(event)
        if ts and now <= ts <= now + timedelta(hours=max(12, int(horizon_hours))):
            upcoming += 1
    if upcoming >= 5:
        out.append(
            FutureSituation(
                kind="schedule_density",
                title="High schedule density in the next 72 hours",
                horizon_hours=horizon_hours,
                confidence=0.72,
                evidence=(f"{upcoming} upcoming events",),
            )
        )

    if profile.confidence.state == "degraded":
        out.append(
            FutureSituation(
                kind="runtime_confidence",
                title="Runtime confidence is reduced",
                horizon_hours=horizon_hours,
                confidence=0.95,
                evidence=(profile.confidence.note,) if profile.confidence.note else tuple(),
            )
        )
    return tuple(out)
