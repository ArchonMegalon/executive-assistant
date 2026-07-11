from __future__ import annotations

import hashlib

from app.services.audiobook_narration_planner import (
    PLANNER_CONTRACT_NAME,
    PlannerChapter,
    plan_narration,
)


def _chapter(index: int, text: str, *, href: str | None = None) -> PlannerChapter:
    return PlannerChapter(
        index=index,
        source_href=href or f"chapter-{index}.xhtml",
        text=text,
        expected_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def _reconstruct(plan: dict[str, object], chapter_index: int) -> str:
    return "".join(
        str(span["source_text"])
        for span in plan["spans"]
        if span["source_chapter_index"] == chapter_index
    )


def test_inline_english_dialogue_keeps_tags_as_narrator_and_stable_named_speakers() -> None:
    first = 'Anna said, “Come now.” The hall was quiet. “I will,” Ben replied.'
    second = 'Ben asked, “Are you ready?” Anna replied, “Yes.”'

    plan = plan_narration(
        (_chapter(1, first), _chapter(2, second)),
        language="en-US",
        max_chars=180,
    )

    assert plan["contract_name"] == PLANNER_CONTRACT_NAME
    assert plan["status"] == "ready"
    assert _reconstruct(plan, 1) == first
    assert _reconstruct(plan, 2) == second
    dialogue = [span for span in plan["spans"] if span["kind"] == "dialogue"]
    assert [span["source_text"] for span in dialogue] == [
        "“Come now.”",
        "“I will,”",
        "“Are you ready?”",
        "“Yes.”",
    ]
    assert [span["speaker_label"] for span in dialogue] == ["Anna", "Ben", "Ben", "Anna"]
    anna_ids = {span["speaker_id"] for span in dialogue if span["speaker_label"] == "Anna"}
    ben_ids = {span["speaker_id"] for span in dialogue if span["speaker_label"] == "Ben"}
    assert len(anna_ids) == 1
    assert len(ben_ids) == 1
    assert anna_ids != ben_ids
    narrator_text = "".join(
        str(span["source_text"])
        for span in plan["spans"]
        if span["kind"] == "narration"
    )
    assert "Anna said" in narrator_text
    assert "Ben replied" in narrator_text


def test_german_quotes_guillemets_and_dialogue_tags_preserve_exact_coverage() -> None:
    text = '„Guten Morgen“, sagte Anna. Ben antwortete: «Komm herein.»'

    plan = plan_narration((_chapter(1, text),), language="de-AT", max_chars=180)

    assert plan["status"] == "ready"
    assert _reconstruct(plan, 1) == text
    dialogue = [span for span in plan["spans"] if span["kind"] == "dialogue"]
    assert [span["source_text"] for span in dialogue] == ["„Guten Morgen“", "«Komm herein.»"]
    assert [span["speaker_label"] for span in dialogue] == ["Anna", "Ben"]
    assert plan["dialogue_span_count"] == 2
    assert plan["attributed_dialogue_span_count"] == 2


def test_malformed_or_non_speech_quotes_fail_conservatively_to_narrator() -> None:
    malformed = 'The note began “This never closes.'
    inline_reference = 'The narrator mentions "an inline quotation" here.'

    plan = plan_narration(
        (_chapter(1, malformed), _chapter(2, inline_reference)),
        language="en",
        max_chars=180,
    )

    assert plan["status"] == "ready"
    assert plan["dialogue_span_count"] == 0
    assert _reconstruct(plan, 1) == malformed
    assert _reconstruct(plan, 2) == inline_reference
    assert {span["speaker_role"] for span in plan["spans"] if span["render"]} == {"narrator"}


def test_unattributed_turns_alternate_deterministically_with_uncertainty() -> None:
    text = '“First.”\n\n“Second.”\n\n“Third.”'

    first_plan = plan_narration((_chapter(1, text),), language="en", max_chars=180)
    second_plan = plan_narration((_chapter(1, text),), language="en", max_chars=180)

    first_dialogue = [span for span in first_plan["spans"] if span["kind"] == "dialogue"]
    second_dialogue = [span for span in second_plan["spans"] if span["kind"] == "dialogue"]
    assert [span["speaker_id"] for span in first_dialogue] == [
        first_dialogue[0]["speaker_id"],
        first_dialogue[1]["speaker_id"],
        first_dialogue[0]["speaker_id"],
    ]
    assert first_dialogue[0]["speaker_id"] != first_dialogue[1]["speaker_id"]
    assert [span["speaker_id"] for span in first_dialogue] == [
        span["speaker_id"] for span in second_dialogue
    ]
    assert first_plan["uncertain_dialogue_span_count"] == 3


def test_explicit_and_approved_traits_are_provenance_bearing_cast_hints() -> None:
    text = '“Hello,” said Anna, a young adult woman with an Austrian accent of Nigerian descent.'

    plan = plan_narration(
        (_chapter(1, text),),
        language="en-AT",
        max_chars=180,
        approved_speaker_profiles={"Anna": {"style": "warm", "language": "de-AT"}},
    )

    anna = next(speaker for speaker in plan["speakers"] if speaker["speaker_label"] == "Anna")
    traits = anna["traits"]
    assert traits["gender_presentation"]["value"] == "feminine"
    assert traits["age_band"]["value"] == "young_adult"
    assert traits["accent"]["value"] == "Austrian"
    assert traits["cultural_or_ethnic_background"]["value"] == "Nigerian"
    assert traits["cultural_or_ethnic_background"]["sensitive_hint"] is True
    assert traits["style"] == {
        "value": "warm",
        "provenance": "approved_casting_notes",
        "confidence": 1.0,
        "sensitive_hint": False,
    }
    assert anna["identity_claimed"] is False


def test_nearby_person_traits_do_not_leak_into_the_speaker_cast() -> None:
    text = '“Hello,” Anna said to the elderly man of Nigerian descent.'

    plan = plan_narration((_chapter(1, text),), language="en", max_chars=180)

    anna = next(speaker for speaker in plan["speakers"] if speaker["speaker_label"] == "Anna")
    assert anna["traits"] == {}


def test_dialogue_dash_keeps_trailing_attribution_with_the_narrator() -> None:
    text = "— Come now, said Anna."

    plan = plan_narration((_chapter(1, text),), language="en", max_chars=180)

    assert _reconstruct(plan, 1) == text
    dialogue = [span for span in plan["spans"] if span["kind"] == "dialogue"]
    narration = [span for span in plan["spans"] if span["kind"] == "narration"]
    layout = [span for span in plan["spans"] if span["kind"] == "layout"]
    assert [(span["source_text"], span["speaker_label"]) for span in dialogue] == [
        ("Come now,", "Anna")
    ]
    assert [span["source_text"] for span in narration] == [" said Anna."]
    assert [span["source_text"] for span in layout] == ["— "]


def test_german_dialogue_dash_turns_keep_tags_and_named_speakers_stable() -> None:
    text = "— Komm jetzt, sagte Anna.\n\n— Warte, antwortete Ben."

    plan = plan_narration((_chapter(1, text),), language="de-AT", max_chars=180)

    assert _reconstruct(plan, 1) == text
    dialogue = [span for span in plan["spans"] if span["kind"] == "dialogue"]
    narration = [span for span in plan["spans"] if span["kind"] == "narration"]
    assert [(span["source_text"], span["speaker_label"]) for span in dialogue] == [
        ("Komm jetzt,", "Anna"),
        ("Warte,", "Ben"),
    ]
    assert [span["source_text"] for span in narration] == [
        " sagte Anna.",
        " antwortete Ben.",
    ]
    assert dialogue[0]["speaker_id"] != dialogue[1]["speaker_id"]


def test_provider_limit_split_is_word_safe_and_records_continuation_boundary() -> None:
    text = (
        "This opening sentence establishes the room and its quiet atmosphere. "
        "The second sentence keeps the performance natural and continuous. "
        "The final sentence closes the passage without splitting a word."
    )

    plan = plan_narration((_chapter(1, text),), language="en", max_chars=80)

    passages = plan["passages"]
    assert plan["status"] == "ready"
    assert len(passages) == 3
    assert all(passage["char_count"] <= 80 for passage in passages)
    assert all(passage["boundary_kind_after"] == "continuation" for passage in passages[:-1])
    assert "".join(passage["text"] for passage in passages) == text
    assert all(not passage["text"].startswith(" ") or index > 0 for index, passage in enumerate(passages))


def test_oversize_dialogue_is_blocked_instead_of_splitting_a_quote_pair() -> None:
    spoken = "word " * 30
    text = f'“{spoken.strip()}” Anna said.'

    plan = plan_narration((_chapter(1, text),), language="en", max_chars=80)

    dialogue_passages = [passage for passage in plan["passages"] if passage["speaker_role"] == "dialogue"]
    assert plan["status"] == "blocked_source_integrity_or_planning"
    assert any(
        str(issue).startswith("dialogue_span_exceeds_provider_limit:")
        for issue in plan["source_integrity_issues"]
    )
    assert len(dialogue_passages) == 1
    assert dialogue_passages[0]["text"].startswith("“")
    assert dialogue_passages[0]["text"].endswith("”")


def test_wrong_expected_source_hash_blocks_even_when_offsets_reconstruct() -> None:
    text = "Exact source text."
    chapter = PlannerChapter(
        index=1,
        source_href="chapter.xhtml",
        text=text,
        expected_sha256="0" * 64,
    )

    plan = plan_narration((chapter,), language="en", max_chars=180)

    assert plan["status"] == "blocked_source_integrity_or_planning"
    assert plan["source_coverage"] == "mismatch"
    assert plan["coverage_complete"] is False
    assert "chapter_source_hash_mismatch:1" in plan["source_integrity_issues"]


def test_explicit_paragraph_pauses_keep_paragraphs_as_distinct_passages() -> None:
    text = "First paragraph.\n\nSecond paragraph.\n\n\nNew scene."

    plan = plan_narration(
        (_chapter(1, text),),
        language="en",
        max_chars=180,
        batch_paragraphs_with_natural_pauses=False,
        pause_policy={"paragraph": 0.35, "scene": 1.2},
    )

    passages = plan["passages"]
    assert [passage["text"] for passage in passages] == [
        "First paragraph.",
        "Second paragraph.",
        "New scene.",
    ]
    assert [passage["boundary_kind_after"] for passage in passages] == [
        "paragraph",
        "scene",
        "",
    ]
    assert [passage["pause_seconds_after"] for passage in passages] == [0.35, 1.2, 0.0]
