from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class Dossier:
    kind: str
    title: str
    signal_count: int
    exposure_eur: float = 0.0
    risk_hits: tuple[str, ...] = field(default_factory=tuple)
    near_term: bool = False
    evidence: tuple[str, ...] = field(default_factory=tuple)


def _extract_amounts(raw: str) -> list[float]:
    vals: list[float] = []
    if not raw:
        return vals
    pat = re.compile(r"(?i)(?:€|eur|usd|\$|chf|gbp)\s*([0-9][0-9\.,\s]{1,})")
    for m in pat.finditer(str(raw)):
        token = str(m.group(1) or "").strip().replace(" ", "")
        if not token:
            continue
        normalized = token
        if "," in normalized and "." in normalized:
            if normalized.rfind(",") > normalized.rfind("."):
                normalized = normalized.replace(".", "").replace(",", ".")
            else:
                normalized = normalized.replace(",", "")
        elif "," in normalized:
            parts = normalized.split(",")
            if len(parts[-1]) == 2 and len(parts) > 1:
                normalized = "".join(parts[:-1]).replace(".", "") + "." + parts[-1]
            else:
                normalized = normalized.replace(",", "")
        elif "." in normalized:
            parts = normalized.split(".")
            if len(parts[-1]) == 2 and len(parts) > 1:
                normalized = "".join(parts[:-1]).replace(",", "") + "." + parts[-1]
            else:
                normalized = normalized.replace(".", "")
        try:
            v = float(normalized)
            if v > 0:
                vals.append(v)
        except Exception:
            continue
    return vals


def _event_start_ts(ev: dict) -> datetime | None:
    start_val = ev.get("start", {})
    dt_str = ""
    if isinstance(start_val, dict):
        dt_str = str(start_val.get("dateTime") or start_val.get("date") or "").strip()
    else:
        dt_str = str(start_val or "").strip()
    if not dt_str:
        return None
    try:
        if "T" in dt_str:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(dt_str + "T00:00:00+00:00")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def build_trip_dossier(
    *,
    mails: list[dict],
    calendar_events: list[dict],
    risk_keywords: list[str] | None = None,
    near_term_hours: int | None = None,
) -> Dossier:
    travel_kws = [
        "flight",
        "airline",
        "booking",
        "reservation",
        "itinerary",
        "layover",
        "stopover",
        "check-in",
        "airport",
        "hotel",
        "vacation",
        "holiday",
        "trip",
        "reise",
        "flug",
    ]
    default_risk = [
        "iran",
        "israel",
        "tel aviv",
        "tel-aviv",
        "tehran",
        "gaza",
        "lebanon",
        "ukraine",
        "russia",
        "war",
        "conflict",
        "unrest",
        "advisory",
    ]
    rk = list(risk_keywords or default_risk)
    extra_risk = [x.strip().lower() for x in str(os.getenv("EA_TRAVEL_RISK_KEYWORDS", "")).split(",") if x.strip()]
    if extra_risk:
        rk = list(dict.fromkeys([x.lower() for x in rk] + extra_risk))
    hours = max(12, int(near_term_hours or int(os.getenv("EA_CRITICAL_TRAVEL_WINDOW_HOURS", "72"))))
    now_utc = datetime.now(timezone.utc)

    signal_count = 0
    max_amount = 0.0
    risk_hits: set[str] = set()
    near_term = False
    evidence: list[str] = []

    def _track(raw_text: str) -> bool:
        nonlocal max_amount
        lower = str(raw_text or "").lower()
        hit = any(k in lower for k in travel_kws)
        if hit:
            amts = _extract_amounts(raw_text)
            if amts:
                max_amount = max(max_amount, max(amts))
            for r in rk:
                if r in lower:
                    risk_hits.add(r)
        return hit

    for m in mails or []:
        subject = str(m.get("subject") or m.get("title") or "").strip()
        snippet = str(m.get("snippet") or m.get("body") or m.get("text") or "").strip()
        sender = str(m.get("from") or m.get("sender") or "").strip()
        raw = f"{subject}\n{snippet}\n{sender}"
        if _track(raw):
            signal_count += 1
            if subject and len(evidence) < 3:
                evidence.append(subject[:110])

    for ev in calendar_events or []:
        title = str(ev.get("summary") or ev.get("title") or "").strip()
        location = str(ev.get("location") or "").strip()
        cal = str(ev.get("_calendar") or "").strip()
        raw = f"{title}\n{location}\n{cal}"
        if _track(raw):
            signal_count += 1
            if title and len(evidence) < 3:
                evidence.append(title[:110])
            ts = _event_start_ts(ev)
            if ts and now_utc - timedelta(hours=6) <= ts <= now_utc + timedelta(hours=hours):
                near_term = True

    return Dossier(
        kind="trip",
        title="Trip Dossier",
        signal_count=int(signal_count),
        exposure_eur=float(max_amount),
        risk_hits=tuple(sorted(risk_hits)),
        near_term=bool(near_term),
        evidence=tuple(evidence),
    )


def build_project_dossier(
    *,
    mails: list[dict],
    calendar_events: list[dict],
    near_term_hours: int | None = None,
) -> Dossier:
    project_kws = [
        "project",
        "deadline",
        "milestone",
        "launch",
        "proposal",
        "deliverable",
        "client",
        "meeting prep",
        "action required",
    ]
    hours = max(12, int(near_term_hours or int(os.getenv("EA_PROJECT_WINDOW_HOURS", "72"))))
    now_utc = datetime.now(timezone.utc)

    signal_count = 0
    near_term = False
    evidence: list[str] = []
    risk_hits: set[str] = set()

    def _match(raw_text: str) -> bool:
        lower = str(raw_text or "").lower()
        if not any(k in lower for k in project_kws):
            return False
        if "blocked" in lower or "blocker" in lower:
            risk_hits.add("blocker")
        if "overdue" in lower:
            risk_hits.add("overdue")
        return True

    for m in mails or []:
        subject = str(m.get("subject") or m.get("title") or "").strip()
        snippet = str(m.get("snippet") or m.get("body") or m.get("text") or "").strip()
        raw = f"{subject}\n{snippet}"
        if _match(raw):
            signal_count += 1
            if subject and len(evidence) < 3:
                evidence.append(subject[:110])

    for ev in calendar_events or []:
        title = str(ev.get("summary") or ev.get("title") or "").strip()
        location = str(ev.get("location") or "").strip()
        raw = f"{title}\n{location}"
        if _match(raw):
            signal_count += 1
            if title and len(evidence) < 3:
                evidence.append(title[:110])
        ts = _event_start_ts(ev)
        if ts and now_utc - timedelta(hours=6) <= ts <= now_utc + timedelta(hours=hours):
            if _match(raw):
                near_term = True

    return Dossier(
        kind="project",
        title="Project Dossier",
        signal_count=int(signal_count),
        exposure_eur=0.0,
        risk_hits=tuple(sorted(risk_hits)),
        near_term=bool(near_term),
        evidence=tuple(evidence),
    )


def build_finance_commitment_dossier(
    *,
    mails: list[dict],
    calendar_events: list[dict],
    near_term_hours: int | None = None,
) -> Dossier:
    finance_kws = [
        "invoice",
        "payment",
        "due",
        "refund",
        "tax",
        "insurance",
        "subscription",
        "bill",
        "renewal",
    ]
    hours = max(12, int(near_term_hours or int(os.getenv("EA_FINANCE_WINDOW_HOURS", "96"))))
    now_utc = datetime.now(timezone.utc)

    signal_count = 0
    near_term = False
    max_amount = 0.0
    evidence: list[str] = []
    risk_hits: set[str] = set()

    def _match(raw_text: str) -> bool:
        nonlocal max_amount
        lower = str(raw_text or "").lower()
        if not any(k in lower for k in finance_kws):
            return False
        amounts = _extract_amounts(raw_text)
        if amounts:
            max_amount = max(max_amount, max(amounts))
        if "overdue" in lower:
            risk_hits.add("overdue")
        if "final notice" in lower or "last reminder" in lower:
            risk_hits.add("final_notice")
        return True

    for m in mails or []:
        subject = str(m.get("subject") or m.get("title") or "").strip()
        snippet = str(m.get("snippet") or m.get("body") or m.get("text") or "").strip()
        raw = f"{subject}\n{snippet}"
        if _match(raw):
            signal_count += 1
            if subject and len(evidence) < 3:
                evidence.append(subject[:110])
            if "due today" in raw.lower() or "due tomorrow" in raw.lower():
                near_term = True

    for ev in calendar_events or []:
        title = str(ev.get("summary") or ev.get("title") or "").strip()
        location = str(ev.get("location") or "").strip()
        raw = f"{title}\n{location}"
        if _match(raw):
            signal_count += 1
            if title and len(evidence) < 3:
                evidence.append(title[:110])
            ts = _event_start_ts(ev)
            if ts and now_utc - timedelta(hours=6) <= ts <= now_utc + timedelta(hours=hours):
                near_term = True

    return Dossier(
        kind="finance_commitment",
        title="Finance Commitment Dossier",
        signal_count=int(signal_count),
        exposure_eur=float(max_amount),
        risk_hits=tuple(sorted(risk_hits)),
        near_term=bool(near_term),
        evidence=tuple(evidence),
    )


def build_health_dossier(
    *,
    mails: list[dict],
    calendar_events: list[dict],
    near_term_hours: int | None = None,
) -> Dossier:
    health_kws = [
        "doctor",
        "clinic",
        "therapy",
        "physio",
        "ergotherapy",
        "stimulation",
        "hospital",
        "medication",
        "prescription",
        "appointment",
        "neurolog",
        "nms",
    ]
    hours = max(12, int(near_term_hours or int(os.getenv("EA_HEALTH_WINDOW_HOURS", "72"))))
    now_utc = datetime.now(timezone.utc)

    signal_count = 0
    near_term = False
    evidence: list[str] = []
    risk_hits: set[str] = set()

    def _match(raw_text: str) -> bool:
        lower = str(raw_text or "").lower()
        if not any(k in lower for k in health_kws):
            return False
        if "urgent" in lower or "emergency" in lower:
            risk_hits.add("urgent")
        if "worsening" in lower or "severe" in lower or "critical" in lower:
            risk_hits.add("worsening")
        if "abnormal" in lower:
            risk_hits.add("abnormal")
        return True

    for m in mails or []:
        subject = str(m.get("subject") or m.get("title") or "").strip()
        snippet = str(m.get("snippet") or m.get("body") or m.get("text") or "").strip()
        raw = f"{subject}\n{snippet}"
        if _match(raw):
            signal_count += 1
            if subject and len(evidence) < 3:
                evidence.append(subject[:110])

    for ev in calendar_events or []:
        title = str(ev.get("summary") or ev.get("title") or "").strip()
        location = str(ev.get("location") or "").strip()
        raw = f"{title}\n{location}"
        if _match(raw):
            signal_count += 1
            if title and len(evidence) < 3:
                evidence.append(title[:110])
            ts = _event_start_ts(ev)
            if ts and now_utc - timedelta(hours=6) <= ts <= now_utc + timedelta(hours=hours):
                near_term = True

    return Dossier(
        kind="health",
        title="Health Dossier",
        signal_count=int(signal_count),
        exposure_eur=0.0,
        risk_hits=tuple(sorted(risk_hits)),
        near_term=bool(near_term),
        evidence=tuple(evidence),
    )


def build_household_ops_dossier(
    *,
    mails: list[dict],
    calendar_events: list[dict],
    near_term_hours: int | None = None,
) -> Dossier:
    ops_kws = [
        "maintenance",
        "repair",
        "plumber",
        "electrician",
        "utility",
        "invoice",
        "bill",
        "contractor",
        "service visit",
        "renovation",
        "school",
        "enrollment",
        "insurance claim",
        "property",
    ]
    hours = max(24, int(near_term_hours or int(os.getenv("EA_HOUSEHOLD_OPS_WINDOW_HOURS", "96"))))
    now_utc = datetime.now(timezone.utc)

    signal_count = 0
    near_term = False
    evidence: list[str] = []
    risk_hits: set[str] = set()

    def _match(raw_text: str) -> bool:
        lower = str(raw_text or "").lower()
        if not any(k in lower for k in ops_kws):
            return False
        if "overdue" in lower or "final notice" in lower:
            risk_hits.add("overdue")
        if "cancel" in lower or "termination" in lower:
            risk_hits.add("cancellation_risk")
        if "outage" in lower or "service interruption" in lower:
            risk_hits.add("service_interruption")
        if "urgent" in lower:
            risk_hits.add("urgent")
        return True

    for m in mails or []:
        subject = str(m.get("subject") or m.get("title") or "").strip()
        snippet = str(m.get("snippet") or m.get("body") or m.get("text") or "").strip()
        raw = f"{subject}\n{snippet}"
        if _match(raw):
            signal_count += 1
            if subject and len(evidence) < 3:
                evidence.append(subject[:110])

    for ev in calendar_events or []:
        title = str(ev.get("summary") or ev.get("title") or "").strip()
        location = str(ev.get("location") or "").strip()
        raw = f"{title}\n{location}"
        if _match(raw):
            signal_count += 1
            if title and len(evidence) < 3:
                evidence.append(title[:110])
            ts = _event_start_ts(ev)
            if ts and now_utc - timedelta(hours=6) <= ts <= now_utc + timedelta(hours=hours):
                near_term = True

    return Dossier(
        kind="household_ops",
        title="Household Ops Dossier",
        signal_count=int(signal_count),
        exposure_eur=0.0,
        risk_hits=tuple(sorted(risk_hits)),
        near_term=bool(near_term),
        evidence=tuple(evidence),
    )
