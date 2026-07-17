from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_generated_release_artifacts_clean.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("verify_generated_release_artifacts_clean", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_generated_release_artifact_normalizer_ignores_host_runner_execution_fields() -> None:
    module = _load_module()
    head = {
        "status": "pass",
        "source_backed_journey_proof": {
            "as_of": "2026-05-31",
            "command": ".venv/bin/python -m pytest -q tests/test_product_browser_journeys.py",
            "cwd": "/docker/EA",
            "python_bin": ".venv/bin/python",
            "git_branch": "completion/absolute-product-finish",
            "output_excerpt": ["4 passed in 1.2s"],
            "exit_code": 0,
        },
    }
    hosted = {
        "status": "pass",
        "source_backed_journey_proof": {
            "as_of": "2026-06-01",
            "command": "/opt/hostedtoolcache/Python/3.12.*/bin/python -m pytest -q tests/test_product_browser_journeys.py",
            "cwd": "/home/runner/work/executive-assistant/executive-assistant",
            "python_bin": "/opt/hostedtoolcache/Python/3.12.*/bin/python",
            "git_branch": "main",
            "output_excerpt": ["4 passed in 1.0s"],
            "exit_code": 0,
        },
    }

    assert module._normalize(head) == module._normalize(hosted)


def test_generated_release_artifact_normalizer_ignores_raw_junit_timing_not_outcomes() -> None:
    module = _load_module()
    before = {
        "status": "pass",
        "source_backed_journey_proof": {
            "status": "pass",
            "terminal_summary": "4 passed in 9.20s",
            "junit_xml": (
                '<testsuite name="pytest" tests="4" failures="0" time="9.20" '
                'timestamp="2026-07-17T14:49:50Z" hostname="runner-a">'
                '<testcase classname="tests.test_journeys" name="test_memorial" time="3.20" />'
                "</testsuite>"
            ),
            "junit_xml_sha256": "a" * 64,
            "passed_count": 4,
            "failed_count": 0,
        },
    }
    after = {
        "status": "pass",
        "source_backed_journey_proof": {
            "status": "pass",
            "terminal_summary": "4 passed in 9.41s",
            "junit_xml": (
                '<testsuite name="pytest" tests="4" failures="0" time="9.41" '
                'timestamp="2026-07-17T14:51:12Z" hostname="runner-b">'
                '<testcase classname="tests.test_journeys" name="test_memorial" time="3.41" />'
                "</testsuite>"
            ),
            "junit_xml_sha256": "b" * 64,
            "passed_count": 4,
            "failed_count": 0,
        },
    }

    assert module._normalize(before) == module._normalize(after)
    after["source_backed_journey_proof"]["status"] = "blocked"
    assert module._normalize(before) != module._normalize(after)
    after["source_backed_journey_proof"]["status"] = "pass"
    after["source_backed_journey_proof"]["passed_count"] = 3
    assert module._normalize(before) != module._normalize(after)
    after["source_backed_journey_proof"]["passed_count"] = 4
    after["source_backed_journey_proof"]["junit_xml"] = str(
        after["source_backed_journey_proof"]["junit_xml"]
    ).replace('name="test_memorial"', 'name="test_different_journey"')
    assert module._normalize(before) != module._normalize(after)
    after["source_backed_journey_proof"]["junit_xml"] = str(
        before["source_backed_journey_proof"]["junit_xml"]
    ).replace(
        ' time="3.20" />',
        ' time="3.20"><failure message="page unreachable">HTTP 404</failure></testcase>',
    )
    assert module._normalize(before) != module._normalize(after)
    after["source_backed_journey_proof"]["junit_xml"] = before["source_backed_journey_proof"]["junit_xml"]
    after["source_backed_journey_proof"]["terminal_summary"] = "3 passed, 1 skipped in 9.41s"
    assert module._normalize(before) != module._normalize(after)


def test_generated_release_artifact_normalizer_ignores_current_head_provenance_field() -> None:
    module = _load_module()
    before = {
        "status": "blocked",
        "readiness": {
            "current_head": "abc123",
            "room_audio_issues": ["room_receipt_missing_or_invalid"],
        },
    }
    after = {
        "status": "blocked",
        "readiness": {
            "current_head": "def456",
            "room_audio_issues": ["room_receipt_missing_or_invalid"],
        },
    }

    assert module._normalize(before) == module._normalize(after)


def test_generated_release_artifact_normalizer_ignores_evidence_head_provenance_fields() -> None:
    module = _load_module()
    before = {
        "status": "pass",
        "evidence_heads": {
            "whole_project_map": "abc123",
            "public_voice_receipt": "abc123",
        },
    }
    after = {
        "status": "pass",
        "evidence_heads": {
            "whole_project_map": "def456",
            "public_voice_receipt": "def456",
        },
    }

    assert module._normalize(before) == module._normalize(after)


def test_generated_release_artifact_normalizer_ignores_live_whatsapp_qr_timestamps() -> None:
    module = _load_module()
    before = {
        "status": "blocked",
        "reason": "sidecar_not_ready",
        "sidecar_last_qr_at": "2026-06-25T16:30:10.325Z",
        "sidecar_qr_age_seconds": 0,
        "state_updated_at": "2026-06-25T16:30:06Z",
        "state_age_seconds": 4,
    }
    after = {
        "status": "blocked",
        "reason": "sidecar_not_ready",
        "sidecar_last_qr_at": "2026-06-25T16:30:50.328Z",
        "sidecar_qr_age_seconds": 39,
        "state_updated_at": "2026-06-25T16:31:27Z",
        "state_age_seconds": 2,
    }

    assert module._normalize(before) == module._normalize(after)


def test_generated_release_artifact_normalizer_preserves_semantic_status_drift() -> None:
    module = _load_module()

    assert module._normalize({"status": "pass"}) != module._normalize({"status": "blocked"})


def test_generated_release_artifact_clean_tracks_mymedia_readiness_materializer_and_receipt() -> None:
    module = _load_module()

    assert Path(".codex-studio/published/mymedia_alexa_readiness.generated.json") in module.GENERATED_ARTIFACTS
    assert ("scripts/materialize_mymedia_alexa_readiness.py",) in module.MATERIALIZER_COMMANDS
