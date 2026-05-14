from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Iterable


FORBIDDEN_TERMS = (
    "ProductLift",
    "Syllabbles",
    "Teable",
    "blipai",
    "Emailit",
    "AppSumo",
)


@dataclass(frozen=True)
class DispatchDraftRequest:
    world_id: str
    turn: int
    source_receipt_ids: tuple[str, ...]
    facts: tuple[str, ...]
    allowed_factions: tuple[str, ...] = ()
    allowed_districts: tuple[str, ...] = ()
    forbidden_claims: tuple[str, ...] = ()
    tone: str = "grim_public_safe"
    length_words: int = 120
    output_count: int = 3


@dataclass(frozen=True)
class DispatchDraft:
    draft_id: str
    tool: str
    prompt_hash: str
    input_fact_hash: str
    title: str
    body_markdown: str
    highlights: tuple[str, ...]
    unsupported_claims_detected: tuple[str, ...]


def _hash_parts(parts: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(str(part).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _detect_unsupported_claims(text: str, forbidden_claims: tuple[str, ...]) -> tuple[str, ...]:
    hits: list[str] = []
    lowered = text.lower()
    for claim in forbidden_claims:
        if str(claim).strip().lower() in lowered:
            hits.append(str(claim))
    for term in FORBIDDEN_TERMS:
        if term.lower() in lowered:
            hits.append(term)
    return tuple(dict.fromkeys(hits))


def create_dispatch_drafts(request: DispatchDraftRequest) -> tuple[DispatchDraft, ...]:
    facts = tuple(str(fact).strip() for fact in request.facts if str(fact).strip())
    fact_hash = _hash_parts(facts)
    prompt_hash = _hash_parts((request.world_id, str(request.turn), request.tone, *request.source_receipt_ids))
    base_titles = (
        f"Turn {request.turn} — The city is moving",
        f"Turn {request.turn} — Pressure shifts in public view",
        f"Turn {request.turn} — Receipts move before rumors do",
    )
    drafts: list[DispatchDraft] = []
    for index in range(max(1, request.output_count)):
        highlights = tuple(facts[:3])
        fact_lines = " ".join(facts[:4])
        body = (
            f"{fact_lines}\n\n"
            f"Generated from Turn {request.turn} receipt · public-safe seeded preview · no private table data."
        ).strip()
        unsupported = _detect_unsupported_claims(body, request.forbidden_claims)
        drafts.append(
            DispatchDraft(
                draft_id=f"dispatch_draft_{request.world_id}_turn_{request.turn:04d}_{index + 1}",
                tool="syllabbles",
                prompt_hash=prompt_hash,
                input_fact_hash=fact_hash,
                title=base_titles[index % len(base_titles)],
                body_markdown=body,
                highlights=highlights,
                unsupported_claims_detected=unsupported,
            )
        )
    return tuple(drafts)
