from __future__ import annotations

from app.intelligence.dossiers import Dossier
from app.intelligence.profile import PersonProfileContext


def _clamp(value: int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, int(value)))


def exposure_score(dossier: Dossier, *, threshold_eur: float = 5000.0) -> int:
    if dossier.kind != "trip" or dossier.signal_count <= 0:
        return 0
    score = 0
    if dossier.exposure_eur >= threshold_eur:
        score += 45
    if dossier.exposure_eur >= threshold_eur * 2:
        score += 20
    score += min(20, 8 * len(dossier.risk_hits))
    if dossier.signal_count >= 3:
        score += 10
    return _clamp(score)


def decision_window_score(dossier: Dossier) -> int:
    if dossier.kind != "trip" or dossier.signal_count <= 0:
        return 0
    score = 0
    if dossier.near_term:
        score += 65
    if dossier.risk_hits:
        score += 20
    if dossier.exposure_eur > 0:
        score += 10
    return _clamp(score)


def readiness_score(
    profile: PersonProfileContext,
    dossiers: list[Dossier],
    *,
    has_future_risk_intersection: bool = False,
) -> int:
    score = 92
    if profile.confidence.state == "degraded":
        score -= 18
    for dossier in dossiers or []:
        score -= min(25, int(exposure_score(dossier) / 5))
        score -= min(20, int(decision_window_score(dossier) / 6))
    if has_future_risk_intersection:
        score -= 12
    return _clamp(score)


def priority_score(*, exposure: int, decision_window: int, readiness: int) -> int:
    # High exposure/window increases urgency; high readiness decreases it.
    raw = int(0.45 * exposure + 0.40 * decision_window + 0.15 * (100 - readiness))
    return _clamp(raw)
