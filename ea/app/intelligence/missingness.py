from __future__ import annotations

from dataclasses import dataclass, field

from app.intelligence.dossiers import Dossier
from app.intelligence.future_situations import FutureSituation


@dataclass(frozen=True)
class MissingnessSignal:
    kind: str
    title: str
    severity: str  # watch | critical
    evidence: tuple[str, ...] = field(default_factory=tuple)


def _evidence_text(dossier: Dossier) -> str:
    return " ".join(str(x or "") for x in (dossier.evidence or ())).lower()


def build_missingness_signals(
    *,
    dossiers: list[Dossier],
    future_situations: tuple[FutureSituation, ...] | list[FutureSituation],
) -> tuple[MissingnessSignal, ...]:
    out: list[MissingnessSignal] = []
    seen: set[tuple[str, str]] = set()
    future_kinds = {str(getattr(s, "kind", "") or "").strip().lower() for s in (future_situations or ())}

    def _emit(kind: str, title: str, severity: str, evidence: tuple[str, ...]) -> None:
        key = (kind, title)
        if key in seen:
            return
        seen.add(key)
        out.append(
            MissingnessSignal(
                kind=str(kind),
                title=str(title),
                severity="critical" if str(severity).lower() == "critical" else "watch",
                evidence=tuple(evidence or ()),
            )
        )

    for dossier in dossiers or []:
        if int(getattr(dossier, "signal_count", 0)) <= 0:
            continue
        e_txt = _evidence_text(dossier)
        if dossier.kind == "trip":
            if dossier.exposure_eur >= 3000 and "hotel" not in e_txt and "accommodation" not in e_txt:
                _emit(
                    "travel_support_gap",
                    "Trip detected but accommodation signal is missing.",
                    "critical" if dossier.near_term else "watch",
                    tuple(dossier.evidence[:2]),
                )
            if dossier.near_term and "insurance" not in e_txt and "refund" not in e_txt:
                _emit(
                    "travel_support_gap",
                    "Near-term trip has no insurance/refundability evidence.",
                    "watch",
                    tuple(dossier.evidence[:2]),
                )
        elif dossier.kind == "project":
            if dossier.near_term and "prep" not in e_txt and "agenda" not in e_txt and "brief" not in e_txt:
                _emit(
                    "prep_gap",
                    "Near-term project window has no prep-pack evidence.",
                    "watch",
                    tuple(dossier.evidence[:2]),
                )
        elif dossier.kind == "finance_commitment":
            if dossier.near_term and "approved" not in e_txt and "owner" not in e_txt and "assigned" not in e_txt:
                _emit(
                    "decision_owner_missing",
                    "Finance deadline is near-term but no decision owner is visible.",
                    "critical",
                    tuple(dossier.evidence[:2]),
                )

    if "deadline_window" in future_kinds and not any(d.kind == "finance_commitment" and d.signal_count > 0 for d in dossiers or []):
        _emit(
            "missing_dependency",
            "Deadline window detected without linked finance commitment dossier.",
            "watch",
            tuple(),
        )

    if "meeting_prep_window" in future_kinds and not any(d.kind == "project" and d.signal_count > 0 for d in dossiers or []):
        _emit(
            "missing_dependency",
            "Meeting prep window detected without linked project dossier.",
            "watch",
            tuple(),
        )

    return tuple(out)
