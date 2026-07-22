from __future__ import annotations

import hashlib

from app.services.audiobook_narration_planner import (
    CASTING_TRAIT_POLICY_NAME,
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
    assert plan["casting_trait_policy"] == CASTING_TRAIT_POLICY_NAME
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


def test_noncanonical_chapter_order_fails_closed_without_losing_source() -> None:
    first = "First chapter."
    second = "Second chapter."

    plan = plan_narration(
        (_chapter(2, second), _chapter(1, first)),
        language="en-US",
        max_chars=180,
    )

    assert plan["status"] == "blocked_source_integrity_or_planning"
    assert plan["coverage_complete"] is False
    assert plan["source_integrity_verified"] is False
    assert (
        "chapter_indexes_must_be_strictly_increasing"
        in plan["source_integrity_issues"]
    )
    assert _reconstruct(plan, 1) == first
    assert _reconstruct(plan, 2) == second


def test_attribution_modifiers_do_not_fragment_one_named_speaker() -> None:
    text = (
        'Anna said, “One.” Then Anna said, “Two.” '
        'The tired Anna said, “Three.”'
    )

    plan = plan_narration((_chapter(1, text),), language="en-US", max_chars=180)

    dialogue = [span for span in plan["spans"] if span["kind"] == "dialogue"]
    assert [span["speaker_label"] for span in dialogue] == ["Anna"] * 3
    assert len({span["speaker_id"] for span in dialogue}) == 1
    assert plan["speaker_count"] == 1


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
    assert first_plan["casting_review_dialogue_span_count"] == 3
    assert first_plan["casting_review_required"] is True
    assert first_plan["automatic_casting_eligible"] is False


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
    assert traits["cultural_or_ethnic_background"]["casting_eligible"] is False
    assert (
        traits["cultural_or_ethnic_background"]["requires_human_approval"]
        is True
    )
    assert traits["style"] == {
        "value": "warm",
        "provenance": "approved_casting_notes",
        "confidence": 1.0,
        "sensitive_hint": False,
        "casting_eligible": True,
        "requires_human_approval": False,
        "casting_approved": True,
    }
    assert plan["casting_review_required"] is True
    assert plan["automatic_casting_eligible"] is False
    assert plan["review_required_trait_kinds"] == [
        "accent",
        "age_band",
        "cultural_or_ethnic_background",
        "gender_presentation",
    ]
    assert anna["identity_claimed"] is False


def test_approved_casting_aliases_normalize_cultural_linguistic_and_age_metadata() -> None:
    text = 'Anna said, “Hello.”'

    plan = plan_narration(
        (_chapter(1, text),),
        language="en-US",
        max_chars=180,
        approved_speaker_profiles={
            "Anna": {
                "gender": "non-binary",
                "approximate_age": "middle-aged",
                "cultural_identity": "Austrian Nigerian",
                "dialect": "Viennese",
                "locale": "de-AT",
            }
        },
    )

    anna = next(speaker for speaker in plan["speakers"] if speaker["speaker_label"] == "Anna")
    traits = anna["traits"]
    assert traits["gender_presentation"]["value"] == "non-binary"
    assert traits["age_band"]["value"] == "middle-aged"
    assert traits["cultural_or_ethnic_background"] == {
        "value": "Austrian Nigerian",
        "provenance": "approved_casting_notes",
        "confidence": 1.0,
        "sensitive_hint": True,
        "casting_eligible": True,
        "requires_human_approval": False,
        "casting_approved": True,
    }
    assert traits["accent"]["value"] == "Viennese"
    assert traits["language"]["value"] == "de-AT"


def test_nearby_person_traits_do_not_leak_into_the_speaker_cast() -> None:
    text = '“Hello,” Anna said to the elderly man of Nigerian descent.'

    plan = plan_narration((_chapter(1, text),), language="en", max_chars=180)

    anna = next(speaker for speaker in plan["speakers"] if speaker["speaker_label"] == "Anna")
    assert anna["traits"] == {}


def test_named_appositives_elsewhere_in_paragraph_are_source_grounded_cast_hints() -> None:
    text = (
        "Anna, a young adult woman of Nigerian descent, waited by the door. "
        "Ben, an older adult man of Austrian heritage, checked the clock. "
        "“Ready,” Anna said. “Ready,” Ben answered."
    )

    plan = plan_narration((_chapter(1, text),), language="en", max_chars=240)

    anna = next(speaker for speaker in plan["speakers"] if speaker["speaker_label"] == "Anna")
    ben = next(speaker for speaker in plan["speakers"] if speaker["speaker_label"] == "Ben")
    assert anna["traits"]["gender_presentation"]["value"] == "feminine"
    assert anna["traits"]["age_band"]["value"] == "young_adult"
    assert anna["traits"]["cultural_or_ethnic_background"]["value"] == "Nigerian"
    assert anna["traits"]["cultural_or_ethnic_background"]["sensitive_hint"] is True
    assert (
        anna["traits"]["cultural_or_ethnic_background"]["casting_eligible"]
        is False
    )
    assert ben["traits"]["gender_presentation"]["value"] == "masculine"
    assert ben["traits"]["age_band"]["value"] == "older_adult"
    assert ben["traits"]["cultural_or_ethnic_background"]["value"] == "Austrian"
    assert all(speaker["identity_claimed"] is False for speaker in (anna, ben))


def test_approved_casting_trait_wins_over_conflicting_source_hint() -> None:
    text = '“Hello,” said Anna, an older adult man.'

    plan = plan_narration(
        (_chapter(1, text),),
        language="en-US",
        max_chars=180,
        approved_speaker_profiles={
            "Anna": {
                "gender": "feminine",
                "age_band": "young_adult",
            }
        },
    )

    anna = next(
        speaker for speaker in plan["speakers"] if speaker["speaker_label"] == "Anna"
    )
    assert anna["traits"]["gender_presentation"]["value"] == "feminine"
    assert anna["traits"]["age_band"]["value"] == "young_adult"
    assert anna["traits"]["gender_presentation"]["casting_eligible"] is True
    assert anna["traits"]["age_band"]["casting_eligible"] is True
    assert anna["traits"]["gender_presentation"]["conflicting_evidence_present"] is True
    assert anna["traits"]["age_band"]["conflicting_evidence_present"] is True
    assert anna["traits"]["gender_presentation"]["superseded_provenance"] == (
        "explicit_source_phrase"
    )
    assert plan["casting_review_required"] is True
    assert plan["automatic_casting_eligible"] is False
    assert plan["review_required_trait_kinds"] == ["age_band", "gender_presentation"]


def test_german_attributive_age_and_gender_description_is_not_misread_as_child() -> None:
    text = "Die junge Frau Anna wartete am Fenster. „Ich bin bereit“, sagte Anna."

    plan = plan_narration((_chapter(1, text),), language="de-AT", max_chars=180)

    anna = next(speaker for speaker in plan["speakers"] if speaker["speaker_label"] == "Anna")
    assert anna["traits"]["gender_presentation"]["value"] == "feminine"
    assert anna["traits"]["age_band"]["value"] == "young_adult"
    assert anna["identity_claimed"] is False


def test_approved_speaker_trait_change_invalidates_plan_hash() -> None:
    text = 'Anna said, “Hello.”'
    warm = plan_narration(
        (_chapter(1, text),),
        language="en-US",
        max_chars=180,
        approved_speaker_profiles={"Anna": {"style": "warm"}},
    )
    calm = plan_narration(
        (_chapter(1, text),),
        language="en-US",
        max_chars=180,
        approved_speaker_profiles={"Anna": {"style": "calm"}},
    )

    assert warm["version"] == 5
    assert calm["version"] == 5
    assert warm["plan_sha256"] != calm["plan_sha256"]


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


def test_english_dialogue_dash_keeps_tag_and_action_with_the_narrator() -> None:
    text = "— Come now, Anna said, smiling at Ben."

    plan = plan_narration((_chapter(1, text),), language="en", max_chars=180)

    assert plan["status"] == "ready"
    assert _reconstruct(plan, 1) == text
    dialogue = [span for span in plan["spans"] if span["kind"] == "dialogue"]
    narration = [span for span in plan["spans"] if span["kind"] == "narration"]
    assert [(span["source_text"], span["speaker_label"]) for span in dialogue] == [
        ("Come now,", "Anna")
    ]
    assert [span["source_text"] for span in narration] == [
        " Anna said, smiling at Ben."
    ]


def test_german_dialogue_dash_keeps_tag_and_action_with_the_narrator() -> None:
    text = "— Guten Morgen, sagte Anna, und lächelte."

    plan = plan_narration((_chapter(1, text),), language="de-AT", max_chars=180)

    assert plan["status"] == "ready"
    assert _reconstruct(plan, 1) == text
    dialogue = [span for span in plan["spans"] if span["kind"] == "dialogue"]
    narration = [span for span in plan["spans"] if span["kind"] == "narration"]
    assert [(span["source_text"], span["speaker_label"]) for span in dialogue] == [
        ("Guten Morgen,", "Anna")
    ]
    assert [span["source_text"] for span in narration] == [
        " sagte Anna, und lächelte."
    ]


def test_dialogue_dash_does_not_misread_reported_speech_as_a_speaker_tag() -> None:
    texts = (
        "— I was afraid; Anna said she would help, but she never came.",
        "— I asked, because Anna said the door was open.",
    )

    plan = plan_narration(
        tuple(_chapter(index, text) for index, text in enumerate(texts, start=1)),
        language="en",
        max_chars=180,
    )

    assert plan["status"] == "ready"
    for index, text in enumerate(texts, start=1):
        assert _reconstruct(plan, index) == text
    dialogue = [span for span in plan["spans"] if span["kind"] == "dialogue"]
    assert [span["source_text"] for span in dialogue] == [
        "I was afraid; Anna said she would help, but she never came.",
        "I asked, because Anna said the door was open.",
    ]
    assert all(span["speaker_label"] == "Unknown speaker" for span in dialogue)
    assert not [span for span in plan["spans"] if span["kind"] == "narration"]


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


def test_multiple_dialogue_dash_turns_in_one_paragraph_are_sequential() -> None:
    text = "— Come now, said Anna.\n— Wait here, Ben replied."

    plan = plan_narration((_chapter(1, text),), language="en", max_chars=180)

    assert plan["status"] == "ready"
    assert _reconstruct(plan, 1) == text
    dialogue = [span for span in plan["spans"] if span["kind"] == "dialogue"]
    narration = [span for span in plan["spans"] if span["kind"] == "narration"]
    layout = [span for span in plan["spans"] if span["kind"] == "layout"]
    assert [(span["source_text"], span["speaker_label"]) for span in dialogue] == [
        ("Come now,", "Anna"),
        ("Wait here,", "Ben"),
    ]
    assert [span["source_text"] for span in narration] == [
        " said Anna.",
        " Ben replied.",
    ]
    assert [span["source_text"] for span in layout] == ["— ", "\n— "]


def test_multiple_german_dash_turns_in_one_paragraph_keep_tags_as_narration() -> None:
    text = "— Komm jetzt, sagte Anna.\n— Warte, antwortete Ben."

    plan = plan_narration((_chapter(1, text),), language="de-AT", max_chars=180)

    assert plan["status"] == "ready"
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


def test_unique_recent_speaker_pronoun_resolution_is_explicitly_uncertain() -> None:
    text = 'Anna said, “One.” “Two,” she replied.'

    plan = plan_narration((_chapter(1, text),), language="en", max_chars=180)

    assert _reconstruct(plan, 1) == text
    dialogue = [span for span in plan["spans"] if span["kind"] == "dialogue"]
    assert [span["speaker_label"] for span in dialogue] == ["Anna", "Anna"]
    assert dialogue[0]["speaker_id"] == dialogue[1]["speaker_id"]
    assert dialogue[1]["attribution_provenance"] == (
        "explicit_post_attribution_pronoun_"
        "resolved_from_unique_recent_speaker_uncertain"
    )
    assert dialogue[1]["attribution_confidence"] == 0.65
    assert plan["uncertain_dialogue_span_count"] == 1
    assert plan["casting_review_required"] is True


def test_pronoun_resolution_remains_unknown_with_multiple_recent_speakers() -> None:
    text = 'Anna said, “One.” Ben said, “Two.” “Three,” she replied.'

    plan = plan_narration((_chapter(1, text),), language="en", max_chars=180)

    assert _reconstruct(plan, 1) == text
    dialogue = [span for span in plan["spans"] if span["kind"] == "dialogue"]
    assert [span["speaker_label"] for span in dialogue[:2]] == ["Anna", "Ben"]
    assert dialogue[2]["speaker_label"] == "Unknown speaker"
    assert str(dialogue[2]["speaker_id"]).startswith("speaker_unknown_")
    assert dialogue[2]["attribution_provenance"] == (
        "explicit_post_attribution_pronoun"
    )


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
    assert all(float(passage["pause_seconds_after"]) > 0.0 for passage in passages[:-1])
    assert float(plan["inserted_pause_seconds_by_kind"]["continuation"]) > 0.0
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


def test_oversize_single_token_is_blocked_instead_of_hard_split() -> None:
    text = "x" * 160

    plan = plan_narration((_chapter(1, text),), language="en", max_chars=80)

    assert plan["status"] == "blocked_source_integrity_or_planning"
    assert any(
        str(issue).startswith("unsplittable_span_exceeds_provider_limit:")
        for issue in plan["source_integrity_issues"]
    )
    assert len(plan["passages"]) == 1
    assert plan["passages"][0]["text"] == text


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


def test_batched_paragraphs_preserve_internal_boundary_intent_and_timing() -> None:
    text = "First paragraph.\n\nSecond paragraph."

    plan = plan_narration(
        (_chapter(1, text),),
        language="en",
        max_chars=180,
        batch_paragraphs_with_natural_pauses=True,
        pause_policy={"paragraph": 0.35},
    )

    assert plan["status"] == "ready"
    assert len(plan["passages"]) == 1
    passage = plan["passages"][0]
    assert passage["text"] == text
    assert passage["internal_boundaries"] == [
        {
            "kind": "paragraph",
            "char_offset": len("First paragraph."),
            "layout_char_count": 2,
            "pause_intent_seconds": 0.35,
            "application": "natural_layout_hint_not_mastered_silence",
        }
    ]
    assert passage["internal_pause_intent_seconds"] == 0.35
    assert plan["boundary_counts"]["paragraph"] == 1
    assert plan["inserted_pause_seconds_by_kind"]["paragraph"] == 0.0
    assert plan["total_inserted_pause_seconds"] == 0.0
    assert plan["total_internal_pause_intent_seconds"] == 0.35
    assert plan["passage_size_evidence"] == {
        "minimum_chars": len(text),
        "maximum_chars": len(text),
        "total_chars": len(text),
        "average_chars": float(len(text)),
    }
    assert plan["unsafe_or_very_short_passage_runs"] == []


def test_plan_reports_inserted_pause_totals_by_kind_and_unsafe_runs() -> None:
    text = "A.\n\nB.\n\nA sufficiently long final passage."

    plan = plan_narration(
        (_chapter(1, text),),
        language="en",
        max_chars=180,
        batch_paragraphs_with_natural_pauses=False,
        pause_policy={"paragraph": 0.35},
    )

    assert plan["inserted_pause_seconds_by_kind"]["paragraph"] == 0.7
    assert plan["total_inserted_pause_seconds"] == 0.7
    assert plan["passage_size_evidence"] == {
        "minimum_chars": 2,
        "maximum_chars": len("A sufficiently long final passage."),
        "total_chars": 2 + 2 + len("A sufficiently long final passage."),
        "average_chars": 12.667,
    }
    assert plan["unsafe_or_very_short_passage_count"] == 2
    assert plan["unsafe_or_very_short_passage_runs"] == [
        {
            "start_passage_index": 1,
            "end_passage_index": 2,
            "passage_count": 2,
        }
    ]
