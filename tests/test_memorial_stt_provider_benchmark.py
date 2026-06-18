from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark_memorial_stt_providers.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("benchmark_memorial_stt_providers", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_stt_benchmark_scores_expected_transcript_as_pass() -> None:
    module = _load_module()
    spec = {
        "expected_text": "Hallo Manfred, kannst du jetzt mit mir sprechen?",
        "required_tokens": ["hallo", "manfred", "sprechen"],
        "min_token_f1": 0.65,
        "max_wer": 0.45,
    }

    score = module._score_text("Hallo Manfred, kannst du jetzt mit mir sprechen?", spec)

    assert score["passed"] is True
    assert score["intent_correct"] is True
    assert score["token_f1"] == 1.0
    assert score["wer"] == 0.0


def test_stt_benchmark_rejects_non_empty_generic_transcript() -> None:
    module = _load_module()
    spec = {
        "expected_text": "Hallo Manfred, kannst du jetzt mit mir sprechen?",
        "required_tokens": ["hallo", "manfred", "sprechen"],
        "min_token_f1": 0.65,
        "max_wer": 0.45,
    }

    score = module._score_text("Was ist das?", spec)

    assert score["usable"] is True
    assert score["passed"] is False
    assert score["intent_correct"] is False
    assert score["token_f1"] < 0.65
    assert score["wer"] > 0.45


def test_stt_fixture_manifest_carries_consent_hash_and_expected_text() -> None:
    module = _load_module()

    specs = module._fixture_specs()

    assert {spec["sample"] for spec in specs} >= {"contact_opening", "stt_retry", "technical_retry"}
    for spec in specs:
        assert spec["fixture_sha256"]
        assert spec["expected_text"]
        assert spec["required_tokens"]
        assert spec["provenance"]["speaker_consent"]
        assert spec["provenance"]["allowed_purpose"]
        assert spec["provenance"]["retention"]


def test_stt_provider_ranking_uses_accuracy_before_latency() -> None:
    module = _load_module()
    rows = [
        {
            "full_runtime": {"passed": True, "intent_correct": True, "token_f1": 0.91, "wer": 0.1, "ms": 1200},
            "shadow": {"passed": False, "intent_correct": False, "token_f1": 0.2, "wer": 0.9, "ms": 100},
            "onemin_sample": {"passed": True, "intent_correct": True, "token_f1": 0.8, "wer": 0.2, "ms": 900},
        },
        {
            "full_runtime": {"passed": True, "intent_correct": True, "token_f1": 0.95, "wer": 0.05, "ms": 1300},
            "shadow": {"passed": False, "intent_correct": False, "token_f1": 0.3, "wer": 0.8, "ms": 90},
            "onemin_sample": {"passed": False, "intent_correct": True, "token_f1": 0.7, "wer": 0.4, "ms": 800},
        },
    ]

    ranking = module._rank_providers(rows)

    assert ranking[0]["provider"] == "full_runtime"
    assert ranking[0]["production_eligible"] is True
    assert ranking[-1]["provider"] == "shadow"
