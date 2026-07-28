from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from app.services.workllm_sidecar import WorkLLMTaskPacket

from scripts.prepare_workllm_manual_canary import (
    DEFAULT_CORPUS,
    prepare_manual_canary,
)


def test_preparer_stages_twenty_unexecuted_source_bound_packets(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    output_path = tmp_path / "preparation-receipt.json"

    receipt = prepare_manual_canary(
        corpus_path=DEFAULT_CORPUS,
        runtime_root=runtime_root,
        output_path=output_path,
        batch_id="fixture-canary-v1",
        created_at="2026-07-28T05:00:00Z",
    )

    plan_path = Path(str(receipt["execution_plan_path"]))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert receipt["verdict"] == "PREPARED_NOT_EXECUTED"
    assert receipt["task_count"] == 20
    assert receipt["unique_request_count"] == 20
    assert receipt["total_credit_ceiling"] == 136
    assert receipt["provider_interaction_observed"] is False
    assert receipt["credit_reservations_created"] == 0
    assert receipt["submissions_authorized"] == 0
    assert receipt["promotion_eligible_candidate"] is False
    assert receipt["canonical_promotion_authority"] is False
    assert plan["status"] == "prepared_not_authorized"
    assert plan["provider_file_upload_allowed"] is False
    assert plan["provider_web_search_allowed"] is False
    assert plan["organization_memory_allowed"] is False
    assert len(plan["tasks"]) == 20
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(plan_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(plan_path.parent.stat().st_mode) == 0o700

    for task in plan["tasks"]:
        packet_path = Path(task["task_packet_path"])
        packet_payload = json.loads(packet_path.read_text(encoding="utf-8"))
        packet = WorkLLMTaskPacket.from_dict(packet_payload)
        assert packet.data_classification == "public"
        assert packet.request_sha256 == task["request_sha256"]
        assert packet.source_manifest[0].ref == (
            "config/workllm_manual_canary_corpus.json"
        )
        assert task["operator_payload"]["output_schema"] == (
            packet_payload["output_schema"]
        )
        assert task["status"] == "prepared_not_authorized"
        assert not Path(task["provider_output_capture_path"]).exists()
        assert not Path(
            task["provider_output_surface_artifact_path"]
        ).exists()
        assert not Path(task["provider_surface_receipt_path"]).exists()
        assert not Path(task["run_receipt_path"]).exists()
        assert stat.S_IMODE(packet_path.stat().st_mode) == 0o600


def test_preparer_rejects_incomplete_corpus(tmp_path: Path) -> None:
    corpus = json.loads(DEFAULT_CORPUS.read_text(encoding="utf-8"))
    corpus["tasks"] = corpus["tasks"][:-1]
    corpus_path = tmp_path / "incomplete.json"
    corpus_path.write_text(json.dumps(corpus), encoding="utf-8")

    with pytest.raises(
        SystemExit,
        match="workllm_canary_corpus_contract_invalid",
    ):
        prepare_manual_canary(
            corpus_path=corpus_path,
            runtime_root=tmp_path / "runtime",
            output_path=tmp_path / "receipt.json",
            batch_id="fixture-canary-v1",
            created_at="2026-07-28T05:00:00Z",
        )


def test_preparer_rejects_sensitive_fixture_text(tmp_path: Path) -> None:
    corpus = json.loads(DEFAULT_CORPUS.read_text(encoding="utf-8"))
    corpus["tasks"][0]["prepared_context"] += " owner@example.test"
    corpus_path = tmp_path / "sensitive.json"
    corpus_path.write_text(json.dumps(corpus), encoding="utf-8")

    with pytest.raises(
        SystemExit,
        match="workllm_canary_corpus_contains_sensitive_data",
    ):
        prepare_manual_canary(
            corpus_path=corpus_path,
            runtime_root=tmp_path / "runtime",
            output_path=tmp_path / "receipt.json",
            batch_id="fixture-canary-v1",
            created_at="2026-07-28T05:00:00Z",
        )
