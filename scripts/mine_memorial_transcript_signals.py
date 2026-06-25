#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_NAME = "ea.memorial_transcript_signal_report.v1"
DEFAULT_PRIVATE_PROFILE_ROOTS = (
    ROOT / "memorial_data" / "private_memorial_profiles",
    Path("/mnt/pcloud/EA/private_memorial_profiles"),
)


@dataclass(frozen=True)
class TranscriptObservation:
    created_at: str
    source_id: str
    title: str
    summary: str = ""
    transcript: str = ""
    excerpt: str = ""


@dataclass(frozen=True)
class SignalRule:
    label: str
    group: str
    interpretation: str
    keywords: tuple[str, ...]


SIGNAL_RULES: tuple[SignalRule, ...] = (
    SignalRule(
        label="justice_as_lived_principle_not_theory",
        group="core_persona_signals",
        interpretation=(
            "Justice is framed as a lived principle: legal theory matters, but the emotional signal is whether right is "
            "actually practiced."
        ),
        keywords=("gerechtigkeit", "jusstudium", "recht nicht", "justice", "lived reality", "theory"),
    ),
    SignalRule(
        label="grief_managed_through_logistics_and_duty",
        group="stress_response_signals",
        interpretation=(
            "Grief is being processed through concrete duties and logistics such as funeral timing, cemetery constraints, "
            "and dedicating arrangements."
        ),
        keywords=("begraebnis", "begräbnis", "friedhof", "kranz", "funeral", "cemetery", "arrangements"),
    ),
)


def _load_env_defaults() -> None:
    for env_path in (ROOT / ".env.local", ROOT / ".env"):
        if not env_path.is_file():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export ") :]
            key, value = line.split("=", 1)
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = value.strip().strip('"').strip("'")


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", str(value or "").strip().lower()).strip("-_")
    return slug or "memorial"


def _compact_text(value: object, *, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _observation_text(row: TranscriptObservation) -> str:
    return " ".join(
        part
        for part in (
            row.title,
            row.summary,
            row.transcript,
            row.excerpt,
        )
        if str(part or "").strip()
    )


def _row_from_mapping(payload: dict[str, Any]) -> TranscriptObservation | None:
    title = str(payload.get("title") or payload.get("subject") or payload.get("name") or "").strip()
    transcript = str(payload.get("transcript") or payload.get("transcript_text") or payload.get("text") or "").strip()
    summary = str(payload.get("summary") or payload.get("note") or payload.get("body") or "").strip()
    excerpt = str(payload.get("excerpt") or payload.get("quote") or payload.get("preview") or "").strip()
    if not any((title, transcript, summary, excerpt)):
        return None
    return TranscriptObservation(
        created_at=str(payload.get("created_at") or payload.get("date") or "").strip(),
        source_id=str(payload.get("source_id") or payload.get("id") or payload.get("external_id") or title or "archive").strip(),
        title=title or _compact_text(summary or transcript or excerpt, limit=80),
        summary=summary,
        transcript=transcript,
        excerpt=excerpt,
    )


def _walk_payload_for_observations(payload: object) -> list[TranscriptObservation]:
    rows: list[TranscriptObservation] = []
    if isinstance(payload, dict):
        maybe = _row_from_mapping(payload)
        if maybe:
            rows.append(maybe)
        for value in payload.values():
            rows.extend(_walk_payload_for_observations(value))
    elif isinstance(payload, list):
        for item in payload:
            rows.extend(_walk_payload_for_observations(item))
    return rows


def _query_db_observations(slug: str) -> list[TranscriptObservation]:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return []
    try:
        import psycopg  # type: ignore
    except Exception as exc:  # pragma: no cover - dependency is optional for local archives.
        raise RuntimeError("psycopg_unavailable") from exc

    safe_slug = _safe_slug(slug)
    query = """
        select payload_json, created_at, source_id
          from observation_events
         where payload_json::text ilike %s
         order by created_at desc
         limit 200
    """
    rows: list[TranscriptObservation] = []
    with psycopg.connect(database_url, connect_timeout=5) as conn:  # type: ignore[attr-defined]
        with conn.cursor() as cur:
            cur.execute(query, (f"%{safe_slug}%",))
            for payload, created_at, source_id in cur.fetchall():
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except json.JSONDecodeError:
                        payload = {"text": payload}
                for row in _walk_payload_for_observations(payload):
                    rows.append(
                        TranscriptObservation(
                            created_at=row.created_at or str(created_at or ""),
                            source_id=row.source_id or str(source_id or ""),
                            title=row.title,
                            summary=row.summary,
                            transcript=row.transcript,
                            excerpt=row.excerpt,
                        )
                    )
    return rows


def _archive_roots(slug: str) -> list[Path]:
    safe_slug = _safe_slug(slug)
    roots: list[Path] = []
    configured = os.environ.get("EA_MEMORIAL_PRIVATE_PROFILE_ROOT", "").strip()
    if configured:
        roots.append(Path(configured) / safe_slug)
    for root in DEFAULT_PRIVATE_PROFILE_ROOTS:
        roots.append(root / safe_slug)
    return roots


def _query_archive_observations(slug: str) -> list[TranscriptObservation]:
    rows: list[TranscriptObservation] = []
    seen_files: set[Path] = set()
    for root in _archive_roots(slug):
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.json")):
            resolved = path.resolve()
            if resolved in seen_files:
                continue
            seen_files.add(resolved)
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            rows.extend(_walk_payload_for_observations(payload))
    return rows


def _query_observations(slug: str) -> list[TranscriptObservation]:
    _load_env_defaults()
    try:
        rows = _query_db_observations(slug)
    except Exception:
        rows = []
    if rows:
        return rows
    return _query_archive_observations(slug)


def _matched_keywords(text: str, rule: SignalRule) -> list[str]:
    normalized = text.casefold()
    return [keyword for keyword in rule.keywords if keyword.casefold() in normalized]


def _signal_for_rule(rule: SignalRule, observations: list[TranscriptObservation]) -> dict[str, object] | None:
    matched: list[TranscriptObservation] = []
    matched_keywords: set[str] = set()
    for row in observations:
        keywords = _matched_keywords(_observation_text(row), rule)
        if keywords:
            matched.append(row)
            matched_keywords.update(keywords)
    if not matched:
        return None
    return {
        "label": rule.label,
        "group": rule.group,
        "interpretation": rule.interpretation,
        "evidence_count": len(matched),
        "evidence_titles": [row.title for row in matched[:5] if row.title],
        "source_ids": [row.source_id for row in matched[:5] if row.source_id],
        "matched_keywords": sorted(matched_keywords),
        "evidence_excerpt": _compact_text(matched[0].excerpt or matched[0].summary or matched[0].transcript or matched[0].title),
    }


def build_report(slug: str) -> dict[str, object]:
    safe_slug = _safe_slug(slug)
    observations = _query_observations(safe_slug)
    signals = [signal for rule in SIGNAL_RULES if (signal := _signal_for_rule(rule, observations))]
    grouped: dict[str, list[dict[str, object]]] = {}
    for signal in signals:
        grouped.setdefault(str(signal["group"]), []).append(signal)
    return {
        "contract_name": CONTRACT_NAME,
        "slug": safe_slug,
        "observation_count": len(observations),
        "titles_seen": [row.title for row in observations if row.title],
        "signals": signals,
        "grouped_signals": grouped,
        "rules": [
            "Transcript signal mining is deterministic and source-bounded.",
            "The report stores compact excerpts, not full raw transcript dumps.",
            "If Postgres is unavailable, local archive/profile JSON is used as fallback.",
        ],
    }


def default_output_path(slug: str) -> Path:
    configured = os.environ.get("EA_MEMORIAL_PRIVATE_PROFILE_ROOT", "").strip()
    root = Path(configured) if configured else DEFAULT_PRIVATE_PROFILE_ROOTS[0]
    return root / _safe_slug(slug) / "transcript_signal_report.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Mine compact source-grounded signals from memorial transcripts.")
    parser.add_argument("--slug", default=os.environ.get("EA_MEMORIAL_SLUG", "manfred"))
    parser.add_argument("--output", default="")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    report = build_report(args.slug)
    indent = 2 if args.pretty else None
    text = json.dumps(report, ensure_ascii=False, indent=indent, sort_keys=bool(indent)) + "\n"
    if args.output:
        output = Path(args.output)
    else:
        output = default_output_path(args.slug)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
