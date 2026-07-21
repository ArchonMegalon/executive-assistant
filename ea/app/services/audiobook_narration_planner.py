from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence


PLANNER_CONTRACT_NAME = "ea.audiobook_narration_plan.v5"
BOUNDARY_POLICY_NAME = "ea.audiobook_boundary_policy.v3"
CASTING_TRAIT_POLICY_NAME = "ea.audiobook_casting_trait_evidence_policy.v1"
RECEIPT_METRICS_CONTRACT_NAME = "ea.audiobook_narration_receipt_metrics.v1"

_QUOTE_PAIRS = {
    '"': '"',
    "“": "”",
    "„": "“",
    "«": "»",
    "»": "«",
    "‹": "›",
    "›": "‹",
}
_DIALOGUE_DASH_MARKER_RE = re.compile(r"(?m)^[ \t]*[—–][ \t]+")
_SPEECH_VERBS = (
    "said|asked|replied|answered|whispered|shouted|called|cried|murmured|added|"
    "sagte|fragte|antwortete|flüsterte|rief|murmelte|erwiderte|fügte"
)
_NAME_SUBJECT = (
    r"(?-i:[^\W\d_][\w'’-]*(?:\s+[^\W\d_][\w'’-]*){0,2})"
)
_SUBJECT = rf"(?:{_NAME_SUBJECT}|he|she|they|er|sie)"
_POST_SUBJECT_VERB_RE = re.compile(
    rf"^\s*[,.;:!?—–-]*\s*(?P<subject>{_SUBJECT})\s+(?P<verb>{_SPEECH_VERBS})\b",
    re.IGNORECASE,
)
_POST_VERB_SUBJECT_RE = re.compile(
    rf"^\s*[,.;:!?—–-]*\s*(?P<verb>{_SPEECH_VERBS})\s+(?P<subject>{_SUBJECT})\b",
    re.IGNORECASE,
)
_PRE_SUBJECT_VERB_RE = re.compile(
    rf"(?P<subject>{_SUBJECT})\s+(?P<verb>{_SPEECH_VERBS})\s*[,;:]?\s*$",
    re.IGNORECASE,
)
_PRE_VERB_SUBJECT_RE = re.compile(
    rf"(?P<verb>{_SPEECH_VERBS})\s+(?P<subject>{_SUBJECT})\s*[,;:]?\s*$",
    re.IGNORECASE,
)
_DASH_REPORTED_CLAUSE_PREFIXES = (
    "as|because|dass|falls|how|if|ob|obwohl|since|that|though|unless|until|"
    "was|weil|wenn|wer|what|when|where|whether|while|who|why|wie|wo"
)
_DASH_POST_ATTRIBUTION_RE = re.compile(
    rf"(?<=[,;!?…])(?P<tag>\s+(?:(?:{_SPEECH_VERBS})\s+(?:{_SUBJECT})|"
    rf"(?:{_SUBJECT})\s+(?:{_SPEECH_VERBS}))\b)"
    rf"(?=$|[.!?…](?:\s|$)|[,;:]\s*(?!(?:{_DASH_REPORTED_CLAUSE_PREFIXES})\b))",
    re.IGNORECASE,
)
_ATTRIBUTION_DISCOURSE_PREFIXES = {
    "and",
    "aber",
    "but",
    "dann",
    "doch",
    "now",
    "nun",
    "so",
    "then",
    "und",
}
_ATTRIBUTION_ARTICLE_PREFIXES = {
    "a",
    "an",
    "das",
    "dem",
    "den",
    "der",
    "die",
    "ein",
    "eine",
    "einem",
    "einen",
    "einer",
    "the",
}
_PRONOUN_GENDER = {
    "she": "feminine",
    "sie": "feminine",
    "he": "masculine",
    "er": "masculine",
    "they": "nonbinary_or_unspecified",
}
_DEFAULT_PAUSE_POLICY = {
    "continuation": 0.12,
    "sentence": 0.18,
    "paragraph": 0.45,
    "speaker": 0.22,
    "scene": 1.25,
    "chapter": 1.5,
}


@dataclass(frozen=True)
class PlannerChapter:
    index: int
    source_href: str
    text: str
    expected_sha256: str = ""


@dataclass
class _SceneState:
    recent_speakers: list[str] = field(default_factory=list)
    unattributed_turn: int = 0

    def remember(self, speaker_id: str) -> None:
        if not speaker_id:
            return
        self.recent_speakers = [value for value in self.recent_speakers if value != speaker_id]
        self.recent_speakers.append(speaker_id)
        self.recent_speakers = self.recent_speakers[-4:]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_json_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _sha256_text(payload)


def _dialogue_attribution_evidence_rows(
    spans: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    return [
        {
            "speaker_id": str(span.get("speaker_id") or ""),
            "source_chapter_index": int(
                span.get("source_chapter_index") or 0
            ),
            "source_href": str(span.get("source_href") or ""),
            "char_start": int(span.get("char_start") or 0),
            "char_end": int(span.get("char_end") or 0),
            "source_text_sha256": str(
                span.get("source_text_sha256") or ""
            ),
            "attribution_provenance": str(
                span.get("attribution_provenance") or ""
            ),
            "attribution_confidence": round(
                float(span.get("attribution_confidence") or 0.0), 3
            ),
        }
        for span in spans
        if str(span.get("kind") or "") == "dialogue"
    ]


def _normalized_label(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return re.sub(r"\s+", " ", text)


def _looks_like_named_subject(value: object) -> bool:
    label = _normalized_label(value)
    if not label:
        return False
    first = label[0]
    return first.isupper() or (
        first.isalpha() and not first.islower() and not first.isupper()
    )


def _normalized_attribution_subject(value: object) -> str:
    subject = _normalized_label(value)
    tokens = subject.split()
    while (
        len(tokens) > 1
        and tokens[0].casefold().rstrip(",")
        in _ATTRIBUTION_DISCOURSE_PREFIXES
    ):
        tokens.pop(0)
    if (
        len(tokens) > 1
        and tokens[0].casefold().rstrip(",")
        in _ATTRIBUTION_ARTICLE_PREFIXES
    ):
        tokens.pop(0)
        while len(tokens) > 1 and not _looks_like_named_subject(tokens[0]):
            tokens.pop(0)
    return _normalized_label(" ".join(tokens))


def _profile_key(value: object) -> str:
    text = unicodedata.normalize("NFKD", _normalized_label(value)).casefold()
    return "".join(char for char in text if char.isalnum())


def _speaker_id_for_label(label: str) -> str:
    return f"speaker_{_sha256_text(_profile_key(label))[:16]}"


def _unknown_speaker_id(*, chapter_index: int, scene_index: int, token: str) -> str:
    digest = _sha256_text(f"{chapter_index}:{scene_index}:{token}")[:16]
    return f"speaker_unknown_{digest}"


def _trait(
    value: str,
    *,
    provenance: str,
    confidence: float,
    sensitive: bool = False,
    casting_eligible: bool = True,
    requires_human_approval: bool = False,
    casting_approved: bool = False,
) -> dict[str, object]:
    return {
        "value": value,
        "provenance": provenance,
        "confidence": round(max(0.0, min(float(confidence), 1.0)), 3),
        "sensitive_hint": bool(sensitive),
        "casting_eligible": bool(casting_eligible),
        "requires_human_approval": bool(requires_human_approval),
        "casting_approved": bool(casting_approved),
    }


def _approved_casting_trait(value: Mapping[str, object]) -> bool:
    return (
        str(value.get("provenance") or "") == "approved_casting_notes"
        and value.get("casting_eligible") is True
        and value.get("requires_human_approval") is not True
        and value.get("casting_approved") is True
    )


def _merge_traits(
    existing: dict[str, dict[str, object]],
    incoming: Mapping[str, Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    merged = {key: dict(value) for key, value in existing.items()}
    for key, raw_value in incoming.items():
        value = dict(raw_value)
        if not str(value.get("value") or "").strip():
            continue
        if key not in merged:
            merged[key] = value
            continue
        if str(merged[key].get("value")) == str(value.get("value")):
            if float(value.get("confidence") or 0.0) > float(merged[key].get("confidence") or 0.0):
                merged[key] = value
            continue
        existing_approved = _approved_casting_trait(merged[key])
        incoming_approved = _approved_casting_trait(value)
        if existing_approved != incoming_approved:
            authoritative = dict(merged[key] if existing_approved else value)
            weaker = value if existing_approved else merged[key]
            authoritative["conflicting_evidence_present"] = True
            authoritative["superseded_provenance"] = str(
                weaker.get("provenance") or "unknown"
            )
            authoritative["superseded_evidence_sha256"] = (
                _stable_json_sha256(dict(weaker))
            )
            merged[key] = authoritative
            continue
        merged[key] = _trait(
            "unknown",
            provenance="conflicting_evidence",
            confidence=0.0,
            sensitive=bool(merged[key].get("sensitive_hint") or value.get("sensitive_hint")),
            casting_eligible=False,
            requires_human_approval=True,
        )
    return merged


def _approved_traits(value: Mapping[str, object] | None) -> dict[str, dict[str, object]]:
    if not value:
        return {}
    aliases = {
        "gender_presentation": ("gender_presentation", "gender"),
        "age_band": ("age_band", "approximate_age", "age_range", "age"),
        "cultural_or_ethnic_background": (
            "cultural_or_ethnic_background",
            "cultural_background",
            "cultural_identity",
            "ethnic_background",
            "ethnicity",
        ),
        "accent": ("accent", "dialect"),
        "language": ("language", "locale", "spoken_language", "native_language"),
        "role": ("role", "character_role"),
        "style": ("style", "performance_style"),
    }
    traits: dict[str, dict[str, object]] = {}
    for key, source_keys in aliases.items():
        normalized = ""
        for source_key in source_keys:
            normalized = _normalized_label(value.get(source_key))
            if normalized:
                break
        if normalized:
            traits[key] = _trait(
                normalized,
                provenance="approved_casting_notes",
                confidence=1.0,
                sensitive=key == "cultural_or_ethnic_background",
                casting_approved=True,
            )
    return traits


def _source_traits(context: str, *, pronoun: str = "") -> dict[str, dict[str, object]]:
    traits: dict[str, dict[str, object]] = {}
    normalized_pronoun = pronoun.casefold()
    if normalized_pronoun in _PRONOUN_GENDER:
        traits["gender_presentation"] = _trait(
            _PRONOUN_GENDER[normalized_pronoun],
            provenance="explicit_attribution_pronoun",
            confidence=0.75,
            casting_eligible=False,
            requires_human_approval=True,
        )

    lowered = context.casefold()
    if re.search(r"\b(?:woman|female|frau)\b", lowered):
        traits["gender_presentation"] = _trait(
            "feminine",
            provenance="explicit_source_phrase",
            confidence=0.9,
            casting_eligible=False,
            requires_human_approval=True,
        )
    elif re.search(r"\b(?:man|male|mann)\b", lowered):
        traits["gender_presentation"] = _trait(
            "masculine",
            provenance="explicit_source_phrase",
            confidence=0.9,
            casting_eligible=False,
            requires_human_approval=True,
        )

    age_rules = (
        (
            r"\b(?:young adult|junge erwachsene|junger erwachsener|"
            r"young(?:\s+[\wÀ-ÿ'’-]+){0,4}\s+(?:woman|man)|"
            r"jung(?:e|er|en)?(?:\s+[\wÀ-ÿ'’-]+){0,4}\s+(?:frau|mann))\b",
            "young_adult",
        ),
        (r"\b(?:child|kid|kind|mädchen|(?:ein|der)\s+junge)\b", "child"),
        (r"\b(?:teen|teenage|teenager|jugendlich(?:e|er|en)?)\b", "teen"),
        (r"\b(?:elderly|older adult|senior|betagt(?:e|er|en)?|ältere[nr]?)\b", "older_adult"),
        (r"\b(?:middle[- ]aged|mittleren alters)\b", "middle_aged"),
    )
    for pattern, value in age_rules:
        if re.search(pattern, lowered, re.IGNORECASE):
            traits["age_band"] = _trait(
                value,
                provenance="explicit_source_phrase",
                confidence=0.9,
                casting_eligible=False,
                requires_human_approval=True,
            )
            break

    accent_match = re.search(
        r"\b(?:with|in|mit)\s+(?:an?\s+|einem?\s+)?([A-Za-zÀ-ÿ-]{2,32})\s+(?:accent|akzent)\b",
        context,
        re.IGNORECASE,
    )
    if accent_match:
        traits["accent"] = _trait(
            _normalized_label(accent_match.group(1)),
            provenance="explicit_source_phrase",
            confidence=0.95,
            casting_eligible=False,
            requires_human_approval=True,
        )

    background_match = re.search(
        r"\b(?:of\s+)?([A-Za-zÀ-ÿ-]{2,40})\s+(?:descent|heritage|ethnicity|abstammung|herkunft)\b",
        context,
        re.IGNORECASE,
    )
    if background_match:
        traits["cultural_or_ethnic_background"] = _trait(
            _normalized_label(background_match.group(1)),
            provenance="explicit_source_phrase",
            confidence=0.95,
            sensitive=True,
            casting_eligible=False,
            requires_human_approval=True,
        )

    style_rules = (
        (r"\b(?:calm|ruhig)\b", "calm"),
        (r"\b(?:warm|warmherzig)\b", "warm"),
        (r"\b(?:raspy|heiser)\b", "raspy"),
        (r"\b(?:soft[- ]spoken|leise)\b", "soft"),
        (r"\b(?:authoritative|bestimmt)\b", "authoritative"),
        (r"\b(?:energetic|lebhaft)\b", "energetic"),
    )
    for pattern, value in style_rules:
        if re.search(pattern, lowered, re.IGNORECASE):
            traits["style"] = _trait(value, provenance="explicit_source_phrase", confidence=0.8)
            break
    return traits


def _speaker_descriptor_context(paragraph: str, subject: str) -> str:
    """Return only a descriptor grammatically tied to the exact named speaker."""
    normalized_subject = _normalized_label(subject)
    if not normalized_subject:
        return ""
    escaped_subject = re.escape(normalized_subject)
    name_start = r"(?<![\wÀ-ÿ'’-])"
    name_end = r"(?![\wÀ-ÿ'’-])"
    token = r"[\wÀ-ÿ'’-]+"
    article = r"(?:the|a|an|die|der|den|dem|das|ein|eine|einer|einem|einen)"
    gender_noun = r"(?:woman|man|frau|mann)"

    preceding = re.search(
        rf"(?P<descriptor>\b{article}\b\s+(?:{token}\s+){{0,7}}{gender_noun})\s+"
        rf"{name_start}{escaped_subject}{name_end}",
        paragraph,
        re.IGNORECASE,
    )
    if preceding is not None:
        return _normalized_label(preceding.group("descriptor"))

    appositive = re.search(
        rf"{name_start}{escaped_subject}{name_end}\s*,\s*"
        rf"(?P<descriptor>\b{article}\b[^.!?…]{{0,180}})",
        paragraph,
        re.IGNORECASE,
    )
    if appositive is None:
        return ""
    descriptor = _normalized_label(appositive.group("descriptor"))
    if not re.search(
        r"\b(?:woman|man|frau|mann|descent|heritage|ethnicity|abstammung|herkunft)\b",
        descriptor,
        re.IGNORECASE,
    ):
        return ""
    return descriptor


def _quote_regions(paragraph: str) -> list[tuple[int, int]] | None:
    regions: list[tuple[int, int]] = []
    cursor = 0
    while cursor < len(paragraph):
        opener_index = -1
        opener = ""
        for index in range(cursor, len(paragraph)):
            if paragraph[index] in _QUOTE_PAIRS:
                opener_index = index
                opener = paragraph[index]
                break
        if opener_index < 0:
            break
        closer = _QUOTE_PAIRS[opener]
        closer_index = paragraph.find(closer, opener_index + 1)
        if closer_index < 0:
            return None
        if closer_index == opener_index + 1:
            cursor = closer_index + 1
            continue
        regions.append((opener_index, closer_index + 1))
        cursor = closer_index + 1
    return regions


def _post_attribution_trait_context(candidate: re.Match[str], after: str) -> str:
    evidence = _normalized_label(candidate.group(0))
    tail = after[candidate.end() :]
    appositive = re.match(
        r"\s*,\s*(?P<descriptor>(?:(?:a|an|the|ein|eine|einer|der|die|das)\b)[^.!?…]*)",
        tail,
        re.IGNORECASE,
    )
    if appositive is None:
        return evidence
    descriptor = _normalized_label(appositive.group("descriptor"))
    if not descriptor:
        return evidence
    direct_descriptor, separator, relational_tail = descriptor.partition(" with ")
    scoped_descriptor = direct_descriptor
    if separator:
        # Only keep a directly attached accent phrase (and an optional descent
        # phrase attached to that accent). Other "with ..." objects describe a
        # nearby person or prop and must not influence the speaker cast.
        accent = re.match(
            r"(?:(?:a|an)\s+)?[A-ZÀ-Þ][\wÀ-ÿ'’-]*(?:\s+[A-ZÀ-Þ][\wÀ-ÿ'’-]*)?\s+accent"
            r"(?:\s+of\s+[A-ZÀ-Þ][\wÀ-ÿ'’-]*(?:\s+[A-ZÀ-Þ][\wÀ-ÿ'’-]*)?\s+descent)?",
            relational_tail,
            re.IGNORECASE,
        )
        if accent is not None:
            scoped_descriptor = f"{direct_descriptor} with {accent.group(0)}"
    return _normalized_label(f"{evidence}, {scoped_descriptor}")


def _attribution(paragraph: str, start: int, end: int) -> dict[str, object]:
    before = paragraph[max(0, start - 140) : start]
    after = paragraph[end : min(len(paragraph), end + 140)]
    # A tag immediately before the quote belongs to that quote. Prefer it over
    # text following the quote, which may introduce the next speaker turn.
    for candidate, provenance, position in (
        (_PRE_SUBJECT_VERB_RE.search(before), "explicit_pre_attribution", "pre"),
        (_PRE_VERB_SUBJECT_RE.search(before), "explicit_pre_attribution", "pre"),
        (_POST_SUBJECT_VERB_RE.match(after), "explicit_post_attribution", "post"),
        (_POST_VERB_SUBJECT_RE.match(after), "explicit_post_attribution", "post"),
    ):
        if candidate is None:
            continue
        subject = _normalized_attribution_subject(candidate.group("subject"))
        pronoun = subject.casefold() if subject.casefold() in _PRONOUN_GENDER else ""
        if not pronoun and not _looks_like_named_subject(subject):
            continue
        attribution_context = (
            _post_attribution_trait_context(candidate, after)
            if position == "post"
            else _normalized_label(candidate.group(0))
        )
        if not pronoun:
            descriptor_context = _speaker_descriptor_context(paragraph, subject)
            if descriptor_context and descriptor_context not in attribution_context:
                attribution_context = _normalized_label(
                    f"{attribution_context}, {descriptor_context}"
                )
        return {
            "subject": subject,
            "pronoun": pronoun,
            "provenance": provenance if not pronoun else f"{provenance}_pronoun",
            "confidence": 0.98 if not pronoun else 0.75,
            "evidence": _normalized_label(candidate.group(0))[:160],
            "context": attribution_context,
        }
    return {
        "subject": "",
        "pronoun": "",
        "provenance": "unattributed_dialogue",
        "confidence": 0.35,
        "evidence": "",
        "context": f"{before[-100:]} {after[:100]}",
    }


def _confirmed_quote_dialogue(paragraph: str, start: int, end: int, attribution: Mapping[str, object]) -> bool:
    if str(attribution.get("subject") or "").strip():
        return True
    before = paragraph[:start]
    quoted = paragraph[start:end]
    if not before.strip():
        return True
    if before.rstrip().endswith((":", "—", "–", ".", "!", "?")) and re.search(r"[.!?…][\"”»›]$", quoted):
        return True
    return False


def _resolved_speaker(
    *,
    attribution: Mapping[str, object],
    chapter_index: int,
    scene_index: int,
    scene_state: _SceneState,
    speakers: dict[str, dict[str, object]],
    approved_profiles: Mapping[str, Mapping[str, object]],
) -> tuple[str, str, dict[str, dict[str, object]], str, float]:
    subject = _normalized_label(attribution.get("subject"))
    pronoun = _normalized_label(attribution.get("pronoun")).casefold()
    provenance = str(attribution.get("provenance") or "unattributed_dialogue")
    confidence = float(attribution.get("confidence") or 0.0)
    context = str(attribution.get("context") or "")
    evidence_traits = _source_traits(context, pronoun=pronoun)

    if subject and not pronoun:
        speaker_id = _speaker_id_for_label(subject)
        approved = approved_profiles.get(_profile_key(subject)) or {}
        traits = _merge_traits(evidence_traits, _approved_traits(approved))
        return speaker_id, subject, traits, provenance, confidence

    if pronoun:
        gender = _PRONOUN_GENDER.get(pronoun, "")
        recent_unique = list(dict.fromkeys(scene_state.recent_speakers[-4:]))
        matching_recent = []
        for speaker_id in reversed(recent_unique):
            profile = speakers.get(speaker_id) or {}
            trait_value = str(dict(profile.get("traits") or {}).get("gender_presentation", {}).get("value") or "")
            if gender and trait_value == gender:
                matching_recent.append(speaker_id)
        if len(set(matching_recent)) == 1:
            speaker_id = matching_recent[0]
            profile = speakers.get(speaker_id) or {}
            traits = _merge_traits(dict(profile.get("traits") or {}), evidence_traits)
            return (
                speaker_id,
                str(profile.get("speaker_label") or "Unknown speaker"),
                traits,
                f"{provenance}_resolved_from_gendered_scene_context_uncertain",
                min(confidence, 0.68),
            )
        if len(recent_unique) == 1:
            speaker_id = recent_unique[0]
            profile = speakers.get(speaker_id) or {}
            trait_value = str(
                dict(profile.get("traits") or {})
                .get("gender_presentation", {})
                .get("value")
                or ""
            )
            if not trait_value or trait_value in {"unknown", gender}:
                traits = _merge_traits(
                    dict(profile.get("traits") or {}),
                    evidence_traits,
                )
                return (
                    speaker_id,
                    str(profile.get("speaker_label") or "Unknown speaker"),
                    traits,
                    f"{provenance}_resolved_from_unique_recent_speaker_uncertain",
                    min(confidence, 0.65),
                )
        speaker_id = _unknown_speaker_id(
            chapter_index=chapter_index,
            scene_index=scene_index,
            token=f"pronoun:{gender or pronoun}",
        )
        return speaker_id, "Unknown speaker", evidence_traits, provenance, min(confidence, 0.6)

    recent_unique = list(dict.fromkeys(scene_state.recent_speakers))
    if len(recent_unique) >= 2:
        speaker_id = recent_unique[-2]
        profile = speakers.get(speaker_id) or {}
        return (
            speaker_id,
            str(profile.get("speaker_label") or "Unknown speaker"),
            dict(profile.get("traits") or {}),
            "alternating_scene_fallback",
            0.45,
        )
    token = "turn_b" if recent_unique else ("turn_a" if scene_state.unattributed_turn % 2 == 0 else "turn_b")
    scene_state.unattributed_turn += 1
    speaker_id = _unknown_speaker_id(
        chapter_index=chapter_index,
        scene_index=scene_index,
        token=token,
    )
    return speaker_id, "Unknown speaker", {}, "alternating_scene_fallback", 0.35


def _dialogue_dash_regions(
    paragraph: str,
) -> list[tuple[int, int, int, dict[str, object]]]:
    """Return sequential dash-turn layout/body ranges within one paragraph."""
    markers = list(_DIALOGUE_DASH_MARKER_RE.finditer(paragraph))
    if not markers:
        return []

    layout_starts: list[int] = []
    for marker in markers:
        layout_start = marker.start()
        if layout_start >= 2 and paragraph[layout_start - 2 : layout_start] == "\r\n":
            layout_start -= 2
        elif layout_start >= 1 and paragraph[layout_start - 1] in "\r\n":
            layout_start -= 1
        layout_starts.append(layout_start)

    regions: list[tuple[int, int, int, dict[str, object]]] = []
    for index, marker in enumerate(markers):
        body_start = marker.end()
        turn_end = (
            layout_starts[index + 1]
            if index + 1 < len(layout_starts)
            else len(paragraph)
        )
        if body_start >= turn_end:
            continue
        trailing_tag = _DASH_POST_ATTRIBUTION_RE.search(
            paragraph,
            body_start,
            turn_end,
        )
        dialogue_end = (
            trailing_tag.start("tag")
            if trailing_tag is not None and trailing_tag.start("tag") > body_start
            else turn_end
        )
        attribution = _attribution(paragraph, body_start, dialogue_end)
        regions.append(
            (layout_starts[index], body_start, dialogue_end, attribution)
        )
    return regions


def _append_span(
    spans: list[dict[str, object]],
    *,
    chapter: PlannerChapter,
    scene_index: int,
    paragraph_index: int,
    start: int,
    end: int,
    kind: str,
    speaker_id: str,
    speaker_label: str,
    attribution_provenance: str,
    attribution_confidence: float,
    traits: Mapping[str, Mapping[str, object]] | None = None,
    layout_kind: str = "",
) -> None:
    if end <= start:
        return
    source_text = chapter.text[start:end]
    spans.append(
        {
            "span_index": len(spans) + 1,
            "source_chapter_index": chapter.index,
            "source_href": chapter.source_href,
            "source_scene_index": scene_index,
            "source_paragraph_index": paragraph_index,
            "char_start": start,
            "char_end": end,
            "source_text": source_text,
            "source_text_sha256": _sha256_text(source_text),
            "kind": kind,
            "render": kind in {"narration", "dialogue"},
            "speaker_role": "dialogue" if kind == "dialogue" else "narrator",
            "speaker_id": speaker_id,
            "speaker_label": speaker_label,
            "attribution_provenance": attribution_provenance,
            "attribution_confidence": round(float(attribution_confidence), 3),
            "traits": {key: dict(value) for key, value in dict(traits or {}).items()},
            "layout_kind": layout_kind,
        }
    )


def _parse_paragraph(
    *,
    chapter: PlannerChapter,
    paragraph_start: int,
    paragraph_end: int,
    scene_index: int,
    paragraph_index: int,
    scene_state: _SceneState,
    speakers: dict[str, dict[str, object]],
    approved_profiles: Mapping[str, Mapping[str, object]],
    spans: list[dict[str, object]],
) -> None:
    paragraph = chapter.text[paragraph_start:paragraph_end]
    regions: list[tuple[int, int, str, dict[str, object] | None]] = []
    cursor = 0
    dash_regions = _dialogue_dash_regions(paragraph)
    if dash_regions:
        for layout_start, body_start, dialogue_end, attribution in dash_regions:
            regions.append((layout_start, body_start, "layout", None))
            regions.append((body_start, dialogue_end, "dialogue", attribution))
    else:
        quote_regions = _quote_regions(paragraph)
        if quote_regions is not None:
            for start, end in quote_regions:
                attribution = _attribution(paragraph, start, end)
                if _confirmed_quote_dialogue(paragraph, start, end, attribution):
                    regions.append((start, end, "dialogue", attribution))

    for local_start, local_end, region_kind, attribution in regions:
        if local_start > cursor:
            _append_span(
                spans,
                chapter=chapter,
                scene_index=scene_index,
                paragraph_index=paragraph_index,
                start=paragraph_start + cursor,
                end=paragraph_start + local_start,
                kind="narration",
                speaker_id="narrator",
                speaker_label="Narrator",
                attribution_provenance="narrator_source",
                attribution_confidence=1.0,
            )
        if region_kind == "layout":
            _append_span(
                spans,
                chapter=chapter,
                scene_index=scene_index,
                paragraph_index=paragraph_index,
                start=paragraph_start + local_start,
                end=paragraph_start + local_end,
                kind="layout",
                speaker_id="",
                speaker_label="",
                attribution_provenance="source_layout",
                attribution_confidence=1.0,
                layout_kind="dialogue_marker",
            )
            cursor = local_end
            continue
        if attribution is None:
            raise AssertionError("dialogue_region_requires_attribution")
        speaker_id, speaker_label, traits, provenance, confidence = _resolved_speaker(
            attribution=attribution,
            chapter_index=chapter.index,
            scene_index=scene_index,
            scene_state=scene_state,
            speakers=speakers,
            approved_profiles=approved_profiles,
        )
        existing_profile = speakers.get(speaker_id) or {}
        merged_traits = _merge_traits(dict(existing_profile.get("traits") or {}), traits)
        speakers[speaker_id] = {
            "speaker_id": speaker_id,
            "speaker_label": speaker_label,
            "traits": merged_traits,
            "attribution_provenance": provenance,
            "attribution_confidence": round(confidence, 3),
            "identity_claimed": False,
        }
        _append_span(
            spans,
            chapter=chapter,
            scene_index=scene_index,
            paragraph_index=paragraph_index,
            start=paragraph_start + local_start,
            end=paragraph_start + local_end,
            kind="dialogue",
            speaker_id=speaker_id,
            speaker_label=speaker_label,
            attribution_provenance=provenance,
            attribution_confidence=confidence,
            traits=merged_traits,
        )
        scene_state.remember(speaker_id)
        cursor = local_end
    if cursor < len(paragraph):
        _append_span(
            spans,
            chapter=chapter,
            scene_index=scene_index,
            paragraph_index=paragraph_index,
            start=paragraph_start + cursor,
            end=paragraph_end,
            kind="narration",
            speaker_id="narrator",
            speaker_label="Narrator",
            attribution_provenance="narrator_source",
            attribution_confidence=1.0,
        )


def _chapter_spans(
    *,
    chapter: PlannerChapter,
    speakers: dict[str, dict[str, object]],
    approved_profiles: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    spans: list[dict[str, object]] = []
    scene_index = 0
    scene_cursor = 0
    for scene_break in re.finditer(r"\n{3,}", chapter.text):
        _scene_spans(
            chapter=chapter,
            start=scene_cursor,
            end=scene_break.start(),
            scene_index=scene_index,
            speakers=speakers,
            approved_profiles=approved_profiles,
            spans=spans,
        )
        _append_span(
            spans,
            chapter=chapter,
            scene_index=scene_index,
            paragraph_index=-1,
            start=scene_break.start(),
            end=scene_break.end(),
            kind="layout",
            speaker_id="",
            speaker_label="",
            attribution_provenance="source_layout",
            attribution_confidence=1.0,
            layout_kind="scene",
        )
        scene_cursor = scene_break.end()
        scene_index += 1
    _scene_spans(
        chapter=chapter,
        start=scene_cursor,
        end=len(chapter.text),
        scene_index=scene_index,
        speakers=speakers,
        approved_profiles=approved_profiles,
        spans=spans,
    )
    return spans


def _scene_spans(
    *,
    chapter: PlannerChapter,
    start: int,
    end: int,
    scene_index: int,
    speakers: dict[str, dict[str, object]],
    approved_profiles: Mapping[str, Mapping[str, object]],
    spans: list[dict[str, object]],
) -> None:
    state = _SceneState()
    paragraph_index = 0
    paragraph_cursor = start
    for paragraph_break in re.finditer(r"\n{2}", chapter.text[start:end]):
        break_start = start + paragraph_break.start()
        break_end = start + paragraph_break.end()
        _parse_paragraph(
            chapter=chapter,
            paragraph_start=paragraph_cursor,
            paragraph_end=break_start,
            scene_index=scene_index,
            paragraph_index=paragraph_index,
            scene_state=state,
            speakers=speakers,
            approved_profiles=approved_profiles,
            spans=spans,
        )
        _append_span(
            spans,
            chapter=chapter,
            scene_index=scene_index,
            paragraph_index=paragraph_index,
            start=break_start,
            end=break_end,
            kind="layout",
            speaker_id="",
            speaker_label="",
            attribution_provenance="source_layout",
            attribution_confidence=1.0,
            layout_kind="paragraph",
        )
        paragraph_cursor = break_end
        paragraph_index += 1
    _parse_paragraph(
        chapter=chapter,
        paragraph_start=paragraph_cursor,
        paragraph_end=end,
        scene_index=scene_index,
        paragraph_index=paragraph_index,
        scene_state=state,
        speakers=speakers,
        approved_profiles=approved_profiles,
        spans=spans,
    )


def _split_exact_narration(text: str, max_chars: int) -> list[tuple[int, int]]:
    """Split exactly at natural, word-safe boundaries outside quote pairs."""
    if len(text) <= max_chars:
        return [(0, len(text))]
    ranges: list[tuple[int, int]] = []
    cursor = 0
    quote_regions = _quote_regions(text)
    if quote_regions is None:
        unmatched_quote = next(
            (index for index, char in enumerate(text) if char in _QUOTE_PAIRS),
            len(text),
        )
        quote_regions = [(unmatched_quote, len(text))]

    def boundary_is_quote_safe(boundary: int) -> bool:
        return not any(start < boundary < end for start, end in quote_regions or ())

    sentence = re.compile(r"[.!?…]+(?:[\"'”’»›)\]]+)?\s+")
    clause = re.compile(r"[;:,](?:[\"'”’»›)\]]+)?\s+")
    while len(text) - cursor > max_chars:
        window_end = cursor + max_chars
        minimum = cursor + max(1, int(max_chars * 0.35))
        split_at = 0
        window = text[cursor : window_end + 1]
        for pattern in (sentence, clause):
            for match in pattern.finditer(window):
                absolute = cursor + match.end()
                if (
                    minimum <= absolute <= window_end
                    and boundary_is_quote_safe(absolute)
                ):
                    split_at = absolute
            if split_at:
                break
        if not split_at:
            whitespace = [
                match.end()
                for match in re.finditer(r"\s+", window)
                if cursor < cursor + match.end() <= window_end
                and boundary_is_quote_safe(cursor + match.end())
            ]
            if whitespace:
                split_at = cursor + whitespace[-1]
        if not split_at:
            return [(0, len(text))]
        ranges.append((cursor, split_at))
        cursor = split_at
    if cursor < len(text):
        ranges.append((cursor, len(text)))
    return ranges


def _boundary_between(current: Mapping[str, object], following: Mapping[str, object]) -> str:
    if int(current["source_chapter_index"]) != int(following["source_chapter_index"]):
        return "chapter"
    if int(current["source_scene_index"]) != int(following["source_scene_index"]):
        return "scene"
    if str(current["speaker_id"]) != str(following["speaker_id"]):
        return "speaker"
    if following.get("continuation_from_previous") is True:
        return "continuation"
    if int(current["source_paragraph_end"]) != int(following["source_paragraph_start"]):
        return "paragraph"
    return "sentence"


def _pause_for_boundary(kind: str, text: str, policy: Mapping[str, float]) -> float:
    value = float(policy.get(kind, 0.0))
    if kind == "continuation" and text.rstrip().endswith((".", "!", "?", "…")):
        value = max(value, float(policy.get("sentence", value)))
    return round(max(value, 0.0), 3)


def _passages_from_spans(
    spans: Sequence[Mapping[str, object]],
    *,
    max_chars: int,
    pause_policy: Mapping[str, float],
    batch_paragraphs_with_natural_pauses: bool,
) -> tuple[list[dict[str, object]], list[str]]:
    units: list[dict[str, object]] = []
    pending_layout = ""
    pending_layout_kind = ""
    unsafe: list[str] = []
    for span in spans:
        if span.get("render") is not True:
            pending_layout += str(span.get("source_text") or "")
            if str(span.get("layout_kind") or "") == "scene":
                pending_layout_kind = "scene"
            elif not pending_layout_kind:
                pending_layout_kind = str(span.get("layout_kind") or "")
            continue
        text = str(span.get("source_text") or "")
        split_ranges = _split_exact_narration(text, max_chars)
        if any(end - start > max_chars for start, end in split_ranges):
            issue_kind = (
                "dialogue_span_exceeds_provider_limit"
                if str(span.get("kind") or "") == "dialogue"
                else "unsplittable_span_exceeds_provider_limit"
            )
            unsafe.append(f"{issue_kind}:{span['span_index']}")
        for split_index, (start, end) in enumerate(split_ranges):
            piece = text[start:end]
            units.append(
                {
                    "text": piece,
                    "speaker_role": span["speaker_role"],
                    "speaker_id": span["speaker_id"],
                    "speaker_label": span["speaker_label"],
                    "attribution_provenance": span["attribution_provenance"],
                    "attribution_confidence": span["attribution_confidence"],
                    "traits": dict(span.get("traits") or {}),
                    "source_chapter_index": span["source_chapter_index"],
                    "source_href": span["source_href"],
                    "source_scene_index": span["source_scene_index"],
                    "source_paragraph_start": span["source_paragraph_index"],
                    "source_paragraph_end": span["source_paragraph_index"],
                    "char_start": int(span["char_start"]) + start,
                    "char_end": int(span["char_start"]) + end,
                    "source_span_indexes": [span["span_index"]],
                    "leading_layout": pending_layout if split_index == 0 else "",
                    "leading_layout_kind": pending_layout_kind if split_index == 0 else "",
                    "continuation_from_previous": split_index > 0,
                    "internal_boundaries": [],
                }
            )
            pending_layout = ""
            pending_layout_kind = ""

    passages: list[dict[str, object]] = []
    for unit in units:
        separator = str(unit.pop("leading_layout") or "")
        layout_kind = str(unit.pop("leading_layout_kind") or "")
        can_merge = bool(
            passages
            and passages[-1]["speaker_id"] == unit["speaker_id"]
            and passages[-1]["speaker_role"] == unit["speaker_role"]
            and passages[-1]["source_chapter_index"] == unit["source_chapter_index"]
            and passages[-1]["source_scene_index"] == unit["source_scene_index"]
            and layout_kind != "scene"
            and (layout_kind != "paragraph" or batch_paragraphs_with_natural_pauses)
            and len(str(passages[-1]["text"])) + len(separator) + len(str(unit["text"])) <= max_chars
        )
        if can_merge:
            previous_text = str(passages[-1]["text"])
            if layout_kind:
                passages[-1]["internal_boundaries"].append(
                    {
                        "kind": layout_kind,
                        "char_offset": len(previous_text),
                        "layout_char_count": len(separator),
                        "pause_intent_seconds": _pause_for_boundary(
                            layout_kind,
                            previous_text,
                            pause_policy,
                        ),
                        "application": "natural_layout_hint_not_mastered_silence",
                    }
                )
            passages[-1]["text"] = f"{previous_text}{separator}{unit['text']}"
            passages[-1]["char_end"] = unit["char_end"]
            passages[-1]["source_paragraph_end"] = unit["source_paragraph_end"]
            passages[-1]["source_span_indexes"].extend(unit["source_span_indexes"])
            continue
        unit["leading_boundary_hint"] = layout_kind
        passages.append(unit)

    for index, passage in enumerate(passages):
        passage["passage_index"] = index + 1
        text = str(passage["text"])
        passage["text_sha256"] = _sha256_text(text)
        passage["char_count"] = len(text)
        passage["unsafe_or_very_short"] = len(text.strip()) < 12 or len(text) > max_chars
        if index + 1 < len(passages):
            boundary = _boundary_between(passage, passages[index + 1])
        else:
            boundary = ""
        passage["boundary_kind_after"] = boundary
        passage["pause_kind"] = boundary
        passage["pause_seconds_after"] = _pause_for_boundary(boundary, text, pause_policy)
        passage["internal_pause_intent_seconds"] = round(
            sum(
                float(item.get("pause_intent_seconds") or 0.0)
                for item in passage["internal_boundaries"]
            ),
            3,
        )
        passage["paragraph_break_after"] = passage["pause_seconds_after"] > 0
        passage["passage_fingerprint"] = _stable_json_sha256(
            {
                "contract": PLANNER_CONTRACT_NAME,
                "boundary_policy": BOUNDARY_POLICY_NAME,
                "text_sha256": passage["text_sha256"],
                "speaker_id": passage["speaker_id"],
                "boundary_kind_after": boundary,
                "pause_seconds_after": passage["pause_seconds_after"],
                "internal_boundaries": passage["internal_boundaries"],
            }
        )
        passage.pop("leading_boundary_hint", None)
        passage.pop("continuation_from_previous", None)
    return passages, unsafe


def _validate_coverage(
    chapters: Sequence[PlannerChapter],
    spans: Sequence[Mapping[str, object]],
) -> tuple[list[str], list[dict[str, object]]]:
    issues: list[str] = []
    chapter_rows: list[dict[str, object]] = []
    for chapter in chapters:
        chapter_spans = [row for row in spans if int(row["source_chapter_index"]) == chapter.index]
        cursor = 0
        reconstructed: list[str] = []
        for row in chapter_spans:
            start = int(row["char_start"])
            end = int(row["char_end"])
            source_text = str(row["source_text"])
            if start != cursor:
                issues.append(f"chapter_span_gap_or_overlap:{chapter.index}:{cursor}:{start}")
            if end <= start or chapter.text[start:end] != source_text:
                issues.append(f"chapter_span_offset_or_text_mismatch:{chapter.index}:{row['span_index']}")
            if _sha256_text(source_text) != str(row["source_text_sha256"]):
                issues.append(f"chapter_span_hash_mismatch:{chapter.index}:{row['span_index']}")
            reconstructed.append(source_text)
            cursor = end
        reconstructed_text = "".join(reconstructed)
        if cursor != len(chapter.text) or reconstructed_text != chapter.text:
            issues.append(f"chapter_exact_reconstruction_mismatch:{chapter.index}")
        actual_sha256 = _sha256_text(chapter.text)
        expected = str(chapter.expected_sha256 or "").strip().lower()
        if expected and (not re.fullmatch(r"[0-9a-f]{64}", expected) or expected != actual_sha256):
            issues.append(f"chapter_source_hash_mismatch:{chapter.index}")
        chapter_rows.append(
            {
                "chapter_index": chapter.index,
                "source_href": chapter.source_href,
                "source_text_sha256": actual_sha256,
                "char_count": len(chapter.text),
                "span_count": len(chapter_spans),
                "exact_reconstruction": reconstructed_text == chapter.text and cursor == len(chapter.text),
            }
        )
    return list(dict.fromkeys(issues)), chapter_rows


def plan_narration(
    chapters: Sequence[PlannerChapter],
    *,
    language: str,
    max_chars: int,
    approved_speaker_profiles: Mapping[str, Mapping[str, object]] | None = None,
    pause_policy: Mapping[str, float] | None = None,
    batch_paragraphs_with_natural_pauses: bool = True,
) -> dict[str, object]:
    if max_chars < 64:
        raise ValueError("max_chars_must_be_at_least_64")
    normalized_chapters = tuple(chapters)
    if not normalized_chapters:
        raise ValueError("at_least_one_chapter_required")
    if len({chapter.index for chapter in normalized_chapters}) != len(normalized_chapters):
        raise ValueError("chapter_indexes_must_be_unique")
    chapter_indexes = [chapter.index for chapter in normalized_chapters]
    order_issues = (
        []
        if chapter_indexes == sorted(chapter_indexes)
        else ["chapter_indexes_must_be_strictly_increasing"]
    )

    approved_profiles = {
        _profile_key(key): dict(value)
        for key, value in dict(approved_speaker_profiles or {}).items()
        if _profile_key(key) and isinstance(value, Mapping)
    }
    policy = dict(_DEFAULT_PAUSE_POLICY)
    for key, value in dict(pause_policy or {}).items():
        if key in policy:
            policy[key] = max(float(value), 0.0)

    speakers: dict[str, dict[str, object]] = {
        "narrator": {
            "speaker_id": "narrator",
            "speaker_label": "Narrator",
            "traits": {},
            "attribution_provenance": "narrator_source",
            "attribution_confidence": 1.0,
            "identity_claimed": False,
        }
    }
    spans: list[dict[str, object]] = []
    for chapter in normalized_chapters:
        spans.extend(
            _chapter_spans(
                chapter=chapter,
                speakers=speakers,
                approved_profiles=approved_profiles,
            )
        )
    for index, span in enumerate(spans, start=1):
        span["span_index"] = index

    coverage_issues, chapter_coverage = _validate_coverage(normalized_chapters, spans)
    coverage_issues = [*order_issues, *coverage_issues]
    passages, unsafe_issues = _passages_from_spans(
        spans,
        max_chars=max_chars,
        pause_policy=policy,
        batch_paragraphs_with_natural_pauses=batch_paragraphs_with_natural_pauses,
    )
    issues = [*coverage_issues, *unsafe_issues]
    boundary_counts = {
        kind: sum(
            1
            for passage in passages
            if passage["boundary_kind_after"] == kind
        )
        + sum(
            1
            for passage in passages
            for boundary in passage["internal_boundaries"]
            if boundary["kind"] == kind
        )
        for kind in _DEFAULT_PAUSE_POLICY
    }
    inserted_pause_seconds_by_kind = {
        kind: round(
            sum(
                float(passage["pause_seconds_after"])
                for passage in passages
                if passage["boundary_kind_after"] == kind
            ),
            3,
        )
        for kind in _DEFAULT_PAUSE_POLICY
    }
    passage_char_counts = [int(passage["char_count"]) for passage in passages]
    passage_size_evidence = {
        "minimum_chars": min(passage_char_counts, default=0),
        "maximum_chars": max(passage_char_counts, default=0),
        "total_chars": sum(passage_char_counts),
        "average_chars": round(
            sum(passage_char_counts) / len(passage_char_counts),
            3,
        )
        if passage_char_counts
        else 0.0,
    }
    unsafe_passage_runs: list[dict[str, int]] = []
    unsafe_run_start = 0
    for passage_position, passage in enumerate(passages, start=1):
        if passage["unsafe_or_very_short"] and not unsafe_run_start:
            unsafe_run_start = passage_position
        if unsafe_run_start and (
            not passage["unsafe_or_very_short"]
            or passage_position == len(passages)
        ):
            unsafe_run_end = (
                passage_position
                if passage["unsafe_or_very_short"]
                else passage_position - 1
            )
            unsafe_passage_runs.append(
                {
                    "start_passage_index": unsafe_run_start,
                    "end_passage_index": unsafe_run_end,
                    "passage_count": unsafe_run_end - unsafe_run_start + 1,
                }
            )
            unsafe_run_start = 0
    dialogue_spans = [span for span in spans if span["kind"] == "dialogue"]
    attributed = [
        span
        for span in dialogue_spans
        if str(span["attribution_provenance"]).startswith("explicit_")
    ]
    uncertain = [
        span
        for span in dialogue_spans
        if float(span["attribution_confidence"]) < 0.7
    ]
    casting_review_spans = [
        span
        for span in dialogue_spans
        if float(span["attribution_confidence"]) < 0.8
        or str(span.get("speaker_id") or "").startswith("speaker_unknown_")
    ]
    review_required_trait_kinds = sorted(
        {
            str(kind)
            for speaker in speakers.values()
            for kind, evidence in dict(speaker.get("traits") or {}).items()
            if isinstance(evidence, Mapping)
            and (
                evidence.get("casting_eligible") is False
                or evidence.get("requires_human_approval") is True
                or evidence.get("conflicting_evidence_present") is True
            )
        }
    )
    source_aggregate = [
        {
            "chapter_index": chapter.index,
            "source_href": chapter.source_href,
            "source_text_sha256": _sha256_text(chapter.text),
        }
        for chapter in normalized_chapters
    ]
    structural_payload = {
        "contract_name": PLANNER_CONTRACT_NAME,
        "casting_trait_policy": CASTING_TRAIT_POLICY_NAME,
        "language": language,
        "max_chars": max_chars,
        "source_aggregate": source_aggregate,
        "span_fingerprints": [
            {
                "chapter": span["source_chapter_index"],
                "start": span["char_start"],
                "end": span["char_end"],
                "text_sha256": span["source_text_sha256"],
                "speaker_id": span["speaker_id"],
                "kind": span["kind"],
                "attribution_provenance": span["attribution_provenance"],
                "attribution_confidence": round(
                    float(span["attribution_confidence"]), 3
                ),
            }
            for span in spans
        ],
        "passage_fingerprints": [passage["passage_fingerprint"] for passage in passages],
        "speaker_evidence_fingerprints": [
            {
                "speaker_id": speaker_id,
                "attribution_provenance": str(
                    (speakers.get(speaker_id) or {}).get("attribution_provenance") or ""
                ),
                "attribution_confidence": float(
                    (speakers.get(speaker_id) or {}).get("attribution_confidence") or 0.0
                ),
                "traits": dict((speakers.get(speaker_id) or {}).get("traits") or {}),
            }
            for speaker_id in sorted(speakers)
            if speaker_id != "narrator"
        ],
        "pause_policy": policy,
        "batch_paragraphs_with_natural_pauses": batch_paragraphs_with_natural_pauses,
    }
    plan_sha256 = _stable_json_sha256(structural_payload)
    return {
        "contract_name": PLANNER_CONTRACT_NAME,
        "receipt_metrics_contract": RECEIPT_METRICS_CONTRACT_NAME,
        "version": 5,
        "status": "ready" if not issues else "blocked_source_integrity_or_planning",
        "language": language,
        "max_chars": max_chars,
        "boundary_policy": BOUNDARY_POLICY_NAME,
        "casting_trait_policy": CASTING_TRAIT_POLICY_NAME,
        "pause_policy": {key: round(float(value), 3) for key, value in policy.items()},
        "batch_paragraphs_with_natural_pauses": batch_paragraphs_with_natural_pauses,
        "source_aggregate_sha256": _stable_json_sha256(source_aggregate),
        "plan_sha256": plan_sha256,
        "dialogue_attribution_evidence_sha256": _stable_json_sha256(
            _dialogue_attribution_evidence_rows(spans)
        ),
        "source_coverage": "complete" if not coverage_issues else "mismatch",
        "coverage_complete": not coverage_issues,
        "source_integrity_verified": not coverage_issues,
        "source_integrity_issues": issues,
        "chapter_coverage": chapter_coverage,
        "chapter_count": len(normalized_chapters),
        "source_char_count": sum(len(chapter.text) for chapter in normalized_chapters),
        "covered_char_count": sum(len(str(span["source_text"])) for span in spans),
        "span_count": len(spans),
        "dialogue_span_count": len(dialogue_spans),
        "attributed_dialogue_span_count": len(attributed),
        "uncertain_dialogue_span_count": len(uncertain),
        "casting_review_dialogue_span_count": len(casting_review_spans),
        "casting_review_required": bool(
            casting_review_spans or review_required_trait_kinds
        ),
        "automatic_casting_eligible": not bool(
            casting_review_spans or review_required_trait_kinds
        ),
        "review_required_trait_kinds": review_required_trait_kinds,
        "speaker_count": len([speaker for speaker in speakers if speaker != "narrator"]),
        "passage_count": len(passages),
        "unsafe_or_very_short_passage_count": sum(
            1 for passage in passages if passage["unsafe_or_very_short"]
        ),
        "passage_size_evidence": passage_size_evidence,
        "unsafe_or_very_short_passage_runs": unsafe_passage_runs,
        "boundary_counts": boundary_counts,
        "inserted_pause_seconds_by_kind": inserted_pause_seconds_by_kind,
        "total_inserted_pause_seconds": round(
            sum(float(passage["pause_seconds_after"]) for passage in passages),
            3,
        ),
        "total_internal_pause_intent_seconds": round(
            sum(
                float(passage["internal_pause_intent_seconds"])
                for passage in passages
            ),
            3,
        ),
        "speakers": [speakers[key] for key in sorted(speakers)],
        "spans": spans,
        "passages": passages,
        "private_payload": True,
        "raw_source_text_embedded": True,
        "public_projection_raw_text_allowed": False,
    }
