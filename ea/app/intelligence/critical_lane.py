from __future__ import annotations

import os
from dataclasses import dataclass, field

from app.intelligence.dossiers import Dossier
from app.intelligence.future_situations import FutureSituation
from app.intelligence.missingness import build_missingness_signals
from app.intelligence.profile import PersonProfileContext


@dataclass(frozen=True)
class CriticalLaneResult:
    actions: tuple[str, ...] = field(default_factory=tuple)
    evidence: tuple[str, ...] = field(default_factory=tuple)
    exposure_score: int = 0
    decision_window_score: int = 0


def _score_trip_dossier(d: Dossier, *, threshold: float) -> tuple[int, int]:
    exposure = 0
    window = 0
    if d.exposure_eur >= threshold:
        exposure += 45
    if d.exposure_eur >= threshold * 2:
        exposure += 20
    if d.risk_hits:
        exposure += min(25, 10 * len(d.risk_hits))
    if d.signal_count >= 3:
        exposure += 10
    if d.near_term:
        window += 65
    if d.risk_hits:
        window += 15
    if d.exposure_eur >= threshold:
        window += 10
    return min(100, exposure), min(100, window)


def build_critical_actions(
    profile: PersonProfileContext,
    dossiers: list[Dossier],
    future_situations: tuple[FutureSituation, ...] | list[FutureSituation] = (),
) -> CriticalLaneResult:
    threshold = max(500.0, float(os.getenv("EA_CRITICAL_TRAVEL_EUR_THRESHOLD", "5000")))
    actions: list[str] = []
    evidence: list[str] = []
    exposure_score = 0
    decision_window_score = 0

    if profile.confidence.state == "degraded" and profile.confidence.note:
        actions.append(profile.confidence.note)

    for d in dossiers or []:
        if d.kind == "trip":
            exp, win = _score_trip_dossier(d, threshold=threshold)
            exposure_score = max(exposure_score, exp)
            decision_window_score = max(decision_window_score, win)
            if d.signal_count and d.exposure_eur >= threshold:
                actions.append(
                    f"High-value trip commitment detected (estimated exposure about EUR {int(round(d.exposure_eur)):,}). "
                    "Validate cancellation/rebooking terms today."
                )
            if d.signal_count and d.risk_hits:
                hits = ", ".join(d.risk_hits[:3])
                actions.append(
                    f"Potential route or layover risk signals detected ({hits}). "
                    "Check official advisories and alternative routes now."
                )
            if d.signal_count and d.near_term:
                actions.append("Travel-related commitment is near-term (<72h). Confirm route viability and check-in now.")
        elif d.kind == "finance_commitment" and d.signal_count:
            if d.exposure_eur >= threshold:
                exposure_score = max(exposure_score, 60)
            if d.near_term:
                decision_window_score = max(decision_window_score, 70)
            if d.exposure_eur >= threshold or d.risk_hits or d.near_term:
                actions.append(
                    "Finance commitment needs immediate review: verify due date, amount, and approval/payment path."
                )
        elif d.kind == "project" and d.signal_count:
            if d.near_term:
                decision_window_score = max(decision_window_score, 60)
            if "blocker" in d.risk_hits or "overdue" in d.risk_hits:
                exposure_score = max(exposure_score, 45)
                actions.append(
                    "Project blockers detected in a near-term window. Prepare decisions and unblock critical tasks now."
                )
        elif d.kind == "health" and d.signal_count:
            if d.near_term:
                decision_window_score = max(decision_window_score, 75)
            if "urgent" in d.risk_hits or "worsening" in d.risk_hits:
                exposure_score = max(exposure_score, 70)
                actions.append(
                    "Health urgency indicators detected. Confirm immediate follow-up and next clinical step now."
                )
            elif d.near_term:
                actions.append(
                    "Health follow-up is near-term. Prepare a concise symptom/treatment context before the appointment."
                )
        for ev in d.evidence:
            if ev and ev not in evidence and len(evidence) < 3:
                evidence.append(ev)

    missing = build_missingness_signals(
        dossiers=dossiers,
        future_situations=future_situations,
    )
    for sig in missing:
        if str(getattr(sig, "severity", "")).lower() != "critical":
            continue
        title = str(getattr(sig, "title", "") or "").strip()
        kind = str(getattr(sig, "kind", "") or "").strip().lower()
        if kind == "decision_owner_missing":
            decision_window_score = max(decision_window_score, 85)
            exposure_score = max(exposure_score, 60)
            actions.append("Finance decision owner missing in a near-term deadline window. Assign owner and due-time now.")
        elif kind == "travel_support_gap":
            decision_window_score = max(decision_window_score, 75)
            exposure_score = max(exposure_score, 65)
            actions.append("Near-term travel support gap detected. Confirm accommodation, insurance, and refundability now.")
        elif title:
            decision_window_score = max(decision_window_score, 70)
            actions.append(f"Critical dependency gap detected: {title}")
        for ev in tuple(getattr(sig, "evidence", ())):
            if ev and ev not in evidence and len(evidence) < 3:
                evidence.append(ev)

    # Deduplicate while preserving order.
    dedup_actions: list[str] = []
    seen = set()
    for a in actions:
        key = str(a).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        dedup_actions.append(str(a).strip())

    return CriticalLaneResult(
        actions=tuple(dedup_actions),
        evidence=tuple(evidence),
        exposure_score=int(exposure_score),
        decision_window_score=int(decision_window_score),
    )
