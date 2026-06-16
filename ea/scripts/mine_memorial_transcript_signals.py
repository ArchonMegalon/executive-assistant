from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import psycopg


DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:CHANGE_ME_STRONG@ea-db:5432/ea_smoke_runtime")
DEFAULT_SLUG = "manfred"
PROFILE_ROOT = Path("/docker/EA/memorial_data/private_memorial_profiles")
PUBLIC_ROOT = Path("/docker/EA/memorial_data/public_memorials")
ENV_PATH = Path("/docker/EA/.env")
ARCHIVE_ROOT = Path("/mnt/pcloud/EA/pocket-ai-audio")
APP_ROOT = Path("/docker/EA/ea")
_MEMORIAL_TERMS = (
    "manfred",
    "funeral",
    "beerdigung",
    "begraebnis",
    "begraebnis",
    "grabredner",
    "trauer",
    "justice",
    "gerechtigkeit",
)

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


@dataclass
class TranscriptObservation:
    created_at: str
    source_id: str
    title: str
    summary: str
    transcript: str
    excerpt: str

    @property
    def combined_text(self) -> str:
        return " ".join(part for part in (self.title, self.summary, self.transcript, self.excerpt) if part).strip()


def _load_env_defaults() -> None:
    if not ENV_PATH.is_file():
        return
    wanted = {
        "DATABASE_URL",
        "POCKET_API_KEY",
        "ONEMIN_AI_API_KEY",
        "ONEMIN_AI_API_KEY_FALLBACK_1",
        "ONEMIN_AI_API_KEY_FALLBACK_2",
        "ONEMIN_AI_API_KEY_FALLBACK_3",
        "ONEMIN_AI_API_KEY_FALLBACK_4",
        "POCKET_AUDIO_TRANSCRIBE_WEBHOOK_URL",
        "EA_POCKET_AUDIO_ARCHIVE_ROOT",
    }
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name not in wanted or os.environ.get(name):
            continue
        os.environ[name] = value


def _load_memorial_titles(slug: str) -> list[str]:
    path = PUBLIC_ROOT / slug / "memorial.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    titles = [str(item.get("title") or "").strip() for item in (data.get("candidate_recordings") or []) if str(item.get("title") or "").strip()]
    return titles


def _query_db_observations(slug: str) -> list[TranscriptObservation]:
    titles = _load_memorial_titles(slug)
    terms = [
        "hospital",
        "hanusch",
        "psychi",
        "depress",
        "ritalin",
        "elisabeth",
        "family",
        "father",
        "dad",
        "admission",
        "aufnahme",
        "befunde",
        "medicine",
        "funeral",
        "beerdigung",
        "begraebnis",
        "begraebnis",
        "grabredner",
        "trauer",
        "justice",
        "gerechtigkeit",
        "court",
        "gericht",
    ]
    rows: dict[str, TranscriptObservation] = {}
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            for title in titles:
                cur.execute(
                    """
                    select created_at::text,
                           source_id,
                           coalesce(payload_json->>'title',''),
                           coalesce(payload_json->>'summary_markdown',''),
                           coalesce(payload_json->>'transcript_text',''),
                           coalesce(payload_json->>'transcript_excerpt','')
                    from observation_events
                    where payload_json->>'title' = %s
                    order by created_at desc
                    limit 2
                    """,
                    (title,),
                )
                for row in cur.fetchall():
                    source_id = str(row[1] or "").strip()
                    rows[source_id] = TranscriptObservation(
                        created_at=str(row[0] or "").strip(),
                        source_id=source_id,
                        title=str(row[2] or "").strip(),
                        summary=str(row[3] or "").strip(),
                        transcript=str(row[4] or "").strip(),
                        excerpt=str(row[5] or "").strip(),
                    )
            for term in terms:
                cur.execute(
                    """
                    select created_at::text,
                           source_id,
                           coalesce(payload_json->>'title',''),
                           coalesce(payload_json->>'summary_markdown',''),
                           coalesce(payload_json->>'transcript_text',''),
                           coalesce(payload_json->>'transcript_excerpt','')
                    from observation_events
                    where cast(payload_json as text) ilike %s
                    order by created_at desc
                    limit 20
                    """,
                    (f"%{term}%",),
                )
                for row in cur.fetchall():
                    source_id = str(row[1] or "").strip()
                    if not source_id:
                        continue
                    rows.setdefault(
                        source_id,
                        TranscriptObservation(
                            created_at=str(row[0] or "").strip(),
                            source_id=source_id,
                            title=str(row[2] or "").strip(),
                            summary=str(row[3] or "").strip(),
                            transcript=str(row[4] or "").strip(),
                            excerpt=str(row[5] or "").strip(),
                        ),
                    )
    return sorted(rows.values(), key=lambda item: item.created_at, reverse=True)


def _memorial_archive_root() -> Path:
    raw = str(os.environ.get("EA_POCKET_AUDIO_ARCHIVE_ROOT") or "").strip()
    return Path(raw) if raw else ARCHIVE_ROOT


def _archive_metadata_paths() -> list[Path]:
    root = _memorial_archive_root()
    if not root.is_dir():
        return []
    return sorted(root.glob("*/*/*/*.json"), reverse=True)


def _archive_metadata_candidates(slug: str) -> list[dict[str, object]]:
    titles = {title.lower() for title in _load_memorial_titles(slug)}
    rows: list[dict[str, object]] = []
    for path in _archive_metadata_paths():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        title = str(payload.get("title") or "").strip()
        if not title:
            continue
        haystack = " ".join(
            [
                title.lower(),
                str(payload.get("recording_id") or "").strip().lower(),
            ]
        )
        if title.lower() in titles or any(term in haystack for term in _MEMORIAL_TERMS):
            rows.append(payload)
    deduped: dict[str, dict[str, object]] = {}
    for row in rows:
        recording_id = str(row.get("recording_id") or "").strip()
        if recording_id:
            deduped.setdefault(recording_id, row)
    return list(deduped.values())


def _fetch_pocket_observation(*, recording_id: str, created_at: str = "") -> TranscriptObservation | None:
    from app.container import build_container
    from app.product.service import build_product_service

    service = build_product_service(build_container())
    try:
        detail = service.get_pocket_recording_detail(
            recording_id=recording_id,
            include_audio=True,
            prefer_audio_fallback=True,
            principal_id="",
            actor="memorial_transcript_miner",
        )
    except Exception:
        return None
    title = str(detail.get("title") or "").strip()
    summary = str(detail.get("summary_markdown") or "").strip()
    transcript = str(detail.get("transcript_text") or "").strip()
    excerpt = str(detail.get("transcript_excerpt") or "").strip()
    if not any((title, summary, transcript, excerpt)):
        return None
    return TranscriptObservation(
        created_at=created_at,
        source_id=recording_id,
        title=title,
        summary=summary,
        transcript=transcript,
        excerpt=excerpt,
    )


def _query_archive_observations(slug: str) -> list[TranscriptObservation]:
    observations: list[TranscriptObservation] = []
    for row in _archive_metadata_candidates(slug):
        recording_id = str(row.get("recording_id") or "").strip()
        if not recording_id:
            continue
        obs = _fetch_pocket_observation(
            recording_id=recording_id,
            created_at=str(row.get("recording_at") or row.get("created_at") or "").strip(),
        )
        if obs is not None:
            observations.append(obs)
    return observations


def _query_observations(slug: str) -> list[TranscriptObservation]:
    _load_env_defaults()
    rows: dict[str, TranscriptObservation] = {}
    try:
        for obs in _query_db_observations(slug):
            rows.setdefault(obs.source_id, obs)
    except Exception:
        pass
    for obs in _query_archive_observations(slug):
        if obs.source_id and obs.source_id in rows:
            existing = rows[obs.source_id]
            if len(obs.combined_text) > len(existing.combined_text):
                rows[obs.source_id] = obs
            continue
        rows[obs.source_id or f"archive:{obs.title}"] = obs
    return sorted(rows.values(), key=lambda item: item.created_at, reverse=True)


def _first_snippet(text: str, markers: Iterable[str], *, fallback_len: int = 260) -> str:
    lowered = text.lower()
    for marker in markers:
        pos = lowered.find(marker.lower())
        if pos >= 0:
            snippet = text[max(0, pos - 80): pos + 180].strip()
            return " ".join(snippet.split())
    return " ".join(text[:fallback_len].split())


def _hospital_relevance_score(obs: TranscriptObservation) -> int:
    text = obs.combined_text.lower()
    score = 0
    if "hospital" in text or "hanusch" in text:
        score += 4
    if any(token in text for token in ("psychi", "depress", "ritalin", "selbstvernach", "stroke", "notfall", "emergency")):
        score += 6
    if any(token in text for token in ("elisabeth", "family", "kinder", "children", "wife", "frau")):
        score += 4
    if any(token in text for token in ("befunde", "documentation", "file", "versicherung", "aufnahme", "zuständig")):
        score += 3
    if "hospital call about emergency admission" in text:
        score += 20
    if "psychiatry appointment and referral" in text:
        score += 12
    if "go to the hospital again" in text:
        score -= 8
    if any(token in text for token in ("justice", "gerechtigkeit", "ungerecht", "gericht", "rechtlich", "theorie", "wahrheit")):
        score += 8
    if any(token in text for token in ("funeral", "beerdigung", "begraebnis", "begraebnis", "trauer", "kranz", "bestatter")):
        score += 6
    if len(obs.summary) + len(obs.transcript) >= 1200:
        score += 6
    if len(obs.summary) + len(obs.transcript) < 300:
        score -= 6
    return score


def _infer_signals(observations: list[TranscriptObservation]) -> list[dict[str, object]]:
    signals: list[dict[str, object]] = []
    for obs in observations:
        text = obs.combined_text
        lowered = text.lower()
        if any(token in lowered for token in ("stationäre aufnahme", "sos-nummer", "zuständig", "man muss dort hinfahren", "entschieden, ob aufgenommen")):
            signals.append(
                {
                    "label": "procedural_crisis_orientation",
                    "confidence": "medium_transcript_derived",
                    "source_title": obs.title,
                    "source_priority": _hospital_relevance_score(obs),
                    "evidence_snippet": _first_snippet(text, ["zuständig", "stationäre Aufnahme", "aufgenommen wird"]),
                    "interpretation": "In akuter Belastung geht er schnell auf Zuständigkeit, Aufnahmeweg, nächste Schritte und formales Vorgehen.",
                }
            )
        if any(token in lowered for token in ("ich lass jetzt mal meine", "buffer", "suppressing", "nicht der böse", "ich weiß, dass das wichtig ist")):
            signals.append(
                {
                    "label": "emotion_buffering_under_family_stress",
                    "confidence": "medium_transcript_derived",
                    "source_title": obs.title,
                    "source_priority": _hospital_relevance_score(obs),
                    "evidence_snippet": _first_snippet(text, ["ich weiß, dass das wichtig ist", "nicht der Böse", "buffer"]),
                    "interpretation": "Er versucht in familiären Krisen seine eigene Emotionalität zurückzudrängen und in einen Puffer- oder Funktionsmodus zu gehen.",
                }
            )
        if any(token in lowered for token in ("medical reports", "befunde", "runterlädst", "allgemeinen befunden", "documentation", "file")):
            signals.append(
                {
                    "label": "documentation_and_case_file_mindset",
                    "confidence": "high_transcript_derived",
                    "source_title": obs.title,
                    "source_priority": _hospital_relevance_score(obs),
                    "evidence_snippet": _first_snippet(text, ["Befunde", "runterlädst", "general medical assessments", "file"]),
                    "interpretation": "Er denkt auch im Familien- und Gesundheitskontext in Unterlagen, zentralen Akten und sauberer Dokumentation.",
                }
            )
        if any(token in lowered for token in ("strictness", "strict", "muss", "eindeutig", "firm boundary", "you have to drink your medicine first")):
            signals.append(
                {
                    "label": "controlling_care_and_boundary_style",
                    "confidence": "medium_transcript_derived",
                    "source_title": obs.title,
                    "source_priority": _hospital_relevance_score(obs),
                    "evidence_snippet": _first_snippet(text, ["you have to drink your medicine first", "eindeutig", "strictness"]),
                    "interpretation": "Sorge erscheint oft in Form klarer Pflichten, strikter Reihenfolge und wenig weicher Aushandlung.",
                }
            )
        if any(token in lowered for token in ("technical troubleshooting", "robot vacuum", "weather", "samsung", "charger", "same model")):
            signals.append(
                {
                    "label": "systems_and_repair_frame",
                    "confidence": "medium_transcript_derived",
                    "source_title": obs.title,
                    "source_priority": _hospital_relevance_score(obs),
                    "evidence_snippet": _first_snippet(text, ["robot vacuum", "Samsung", "charger", "same model"]),
                    "interpretation": "Er rahmt Alltags- und Familienprobleme oft als Systeme, Fehlerbilder, Reparaturen und Optimierungsaufgaben.",
                }
            )
        if any(token in lowered for token in ("staying with him despite his self-described", "egoistic", "vital to the family's stability")):
            signals.append(
                {
                    "label": "guarded_dependence_on_elisabeth",
                    "confidence": "low_to_medium_summary_derived",
                    "source_title": obs.title,
                    "source_priority": _hospital_relevance_score(obs),
                    "evidence_snippet": _first_snippet(text, ["egoistic", "stability"]),
                    "interpretation": "Es gibt Anzeichen dafür, dass er Elisabeth als stabilisierende Figur braucht, dies aber eher indirekt und kontrolliert ausdrückt.",
                }
            )
        if any(token in lowered for token in ("self-neglect", "lack of drive", "performed as chores", "survived rather than enjoyed", "complete neglect")):
            signals.append(
                {
                    "label": "severity_framing_over_sentiment",
                    "confidence": "medium_to_high_summary_derived",
                    "source_title": obs.title,
                    "source_priority": _hospital_relevance_score(obs),
                    "evidence_snippet": _first_snippet(text, ["self-neglect", "lack of drive", "performed as chores", "complete neglect"]),
                    "interpretation": "Er rahmt schwere familiäre oder psychische Krisen eher als ernsten Sachverhalt mit Funktions- und Pflichtverlust als als offene Gefühlsaussprache.",
                }
            )
        if any(token in lowered for token in ("you know how far i will go for us", "for us", "i know that this is important")):
            signals.append(
                {
                    "label": "loyalty_expressed_as_resolve",
                    "confidence": "medium_transcript_derived",
                    "source_title": obs.title,
                    "source_priority": _hospital_relevance_score(obs),
                    "evidence_snippet": _first_snippet(text, ["you know how far i will go for us", "i know that this is important"]),
                    "interpretation": "Bindung und Loyalität erscheinen eher als Entschlossenheit und Einsatzbereitschaft denn als weiche Gefühlsbekundung.",
                }
            )
        justice_tokens = ("gerechtigkeit", "ungerecht", "justice", "recht nicht immer")
        justice_combo = all(token in lowered for token in ("theorie", "wahrheit")) and ("recht" in lowered or "jus " in lowered)
        if any(token in lowered for token in justice_tokens) or justice_combo:
            signals.append(
                {
                    "label": "justice_as_lived_principle_not_theory",
                    "confidence": "high_transcript_derived",
                    "source_title": obs.title,
                    "source_priority": _hospital_relevance_score(obs),
                    "evidence_snippet": _first_snippet(text, ["Gerechtigkeit", "Theorie", "Wahrheit", "unter dem Tisch"]),
                    "interpretation": "Gerechtigkeit erscheint nicht als abstraktes Ideal, sondern als gelebter Massstab: Theorie reicht ihm nicht, er will sehen, ob Recht und Wirklichkeit zusammenpassen.",
                }
            )
        institutional_hit = any(token in lowered for token in ("mensch für menschen", "mensch fuer menschen", "zu teuer geworden", "aufdeckte dinge"))
        institutional_combo = any(token in lowered for token in ("gericht", "court")) and any(token in lowered for token in ("system", "versetzung"))
        if institutional_hit or institutional_combo:
            signals.append(
                {
                    "label": "institutional_critique_in_service_of_people",
                    "confidence": "medium_to_high_summary_derived",
                    "source_title": obs.title,
                    "source_priority": _hospital_relevance_score(obs),
                    "evidence_snippet": _first_snippet(text, ["Mensch fuer Menschen", "System", "Gericht", "zu teuer geworden"]),
                    "interpretation": "Er wirkt wie jemand, der Institutionen ernst nimmt, ihnen aber nur vertraut, wenn sie den Menschen wirklich dienen und Widersprueche nicht zugedeckt werden.",
                }
            )
        if any(token in lowered for token in ("begraebnis", "beerdigung", "friedhof", "bestatter", "kranz", "trauer")):
            signals.append(
                {
                    "label": "grief_managed_through_logistics_and_duty",
                    "confidence": "medium_transcript_derived",
                    "source_title": obs.title,
                    "source_priority": _hospital_relevance_score(obs),
                    "evidence_snippet": _first_snippet(text, ["Begräbnis", "Friedhof", "Bestatter", "Kranz", "Dienstag", "Donnerstag"]),
                    "interpretation": "Auch in Trauer wird Belastung zuerst ueber Termine, Zustaendigkeiten, Reiseplaene und konkrete Pflichten bearbeitet statt ueber ausfuehrliche Gefuehlssprache.",
                }
            )
    deduped: dict[tuple[str, str], dict[str, object]] = {}
    for signal in signals:
        key = (str(signal.get("label") or ""), str(signal.get("source_title") or ""))
        deduped.setdefault(key, signal)
    return list(deduped.values())


def _grouped_signals(signals: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    groups = {
        "core_persona_signals": [],
        "family_relationship_signals": [],
        "stress_response_signals": [],
        "caregiving_style_signals": [],
    }
    for signal in signals:
        label = str(signal.get("label") or "")
        if label in {
            "procedural_crisis_orientation",
            "documentation_and_case_file_mindset",
            "systems_and_repair_frame",
            "severity_framing_over_sentiment",
            "justice_as_lived_principle_not_theory",
            "institutional_critique_in_service_of_people",
        }:
            groups["core_persona_signals"].append(signal)
        if label in {
            "guarded_dependence_on_elisabeth",
            "loyalty_expressed_as_resolve",
            "emotion_buffering_under_family_stress",
            "grief_managed_through_logistics_and_duty",
        }:
            groups["family_relationship_signals"].append(signal)
        if label in {
            "procedural_crisis_orientation",
            "emotion_buffering_under_family_stress",
            "severity_framing_over_sentiment",
            "grief_managed_through_logistics_and_duty",
        }:
            groups["stress_response_signals"].append(signal)
        if label in {
            "controlling_care_and_boundary_style",
            "documentation_and_case_file_mindset",
            "loyalty_expressed_as_resolve",
        }:
            groups["caregiving_style_signals"].append(signal)
    confidence_rank = {
        "high_transcript_derived": 5,
        "medium_to_high_summary_derived": 4,
        "medium_transcript_derived": 3,
        "low_to_medium_summary_derived": 2,
        "low_to_medium_transcript_derived": 1,
    }
    for key, items in groups.items():
        groups[key] = sorted(
            items,
            key=lambda item: (
                int(item.get("source_priority") or 0),
                confidence_rank.get(str(item.get("confidence") or ""), 0),
            ),
            reverse=True,
        )
    return groups


def build_report(slug: str = DEFAULT_SLUG) -> dict[str, object]:
    observations = _query_observations(slug)
    signals = _infer_signals(observations)
    grouped = _grouped_signals(signals)
    latest_hospital = next(
        (
            obs for obs in observations
            if "hospital" in obs.combined_text.lower() or "hanusch" in obs.combined_text.lower()
        ),
        None,
    )
    hospital_candidates = [
        obs for obs in observations
        if any(token in obs.combined_text.lower() for token in ("hospital", "hanusch", "psychi", "depress", "ritalin", "admission", "aufnahme"))
    ]
    latest_substantive_hospital = max(hospital_candidates, key=_hospital_relevance_score) if hospital_candidates else latest_hospital
    signal_counts: dict[str, int] = {}
    for item in signals:
        label = str(item.get("label") or "").strip()
        if not label:
            continue
        signal_counts[label] = signal_counts.get(label, 0) + 1
    return {
        "slug": slug,
        "observation_count": len(observations),
        "latest_hospital_conversation": (
            {
                "created_at": latest_hospital.created_at,
                "source_id": latest_hospital.source_id,
                "title": latest_hospital.title,
                "summary": latest_hospital.summary,
                "excerpt": latest_hospital.excerpt,
                "transcript_excerpt": " ".join((latest_hospital.transcript or "")[:2400].split()),
            }
            if latest_hospital
            else {}
        ),
        "latest_substantive_hospital_conversation": (
            {
                "created_at": latest_substantive_hospital.created_at,
                "source_id": latest_substantive_hospital.source_id,
                "title": latest_substantive_hospital.title,
                "summary": latest_substantive_hospital.summary,
                "excerpt": latest_substantive_hospital.excerpt,
                "transcript_excerpt": " ".join((latest_substantive_hospital.transcript or "")[:3200].split()),
            }
            if latest_substantive_hospital
            else {}
        ),
        "signal_counts": signal_counts,
        "signals": signals,
        "grouped_signals": grouped,
        "workflow": {
            "steps": [
                "Find transcript-like observation events with hospital, family, psychiatry, medication, Elisabeth, and care markers.",
                "Also pull memorial, funeral, justice, and tribute recordings from the Pocket archive when they are available.",
                "Prefer substantive summaries and transcripts over trivial short mentions.",
                "Extract signals into persona, family-relationship, stress-response, and caregiving-style buckets.",
                "Only then write compact persona notes; do not import raw diagnosis claims as direct persona truth.",
            ],
            "voice_policy": "Use transcript content for persona and relation modelling, but do not use hospital material for voice cloning.",
        },
        "titles_seen": [obs.title for obs in observations if obs.title][:40],
    }


def main() -> None:
    slug = os.getenv("MEMORIAL_SLUG", DEFAULT_SLUG).strip() or DEFAULT_SLUG
    report = build_report(slug)
    configured_output = os.getenv("OUTPUT_PATH", "").strip()
    out_path = Path(configured_output) if configured_output else (PROFILE_ROOT / slug / "transcript_signal_report.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "path": str(out_path), "signals": len(report.get("signals") or []), "observation_count": report.get("observation_count")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
