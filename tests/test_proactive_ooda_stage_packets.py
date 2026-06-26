from __future__ import annotations

import json

from app.services.proactive_ooda_service import ProactiveOodaService
from app.services.proactive_ooda_stage_packets import (
    STAGE_PACKET_SCHEMA,
    build_stage_packets,
    default_stage_packet_dir,
    persist_stage_packets,
)


def _digest_with_stage():
    return ProactiveOodaService().build_digest(
        principal_id="cf-email:user@example.test",
        signals=[
            {
                "source_ref": "opportunity:private-source",
                "signal_type": "opportunity",
                "channel": "assistant_opportunity",
                "title": "Review vendor options",
                "summary": "Private summary.",
                "payload": {
                    "ooda_loop": {
                        "reviewed": True,
                        "observe": {"summary": "Review a reversible vendor candidate"},
                        "orient": {"summary": "The window is useful but not urgent."},
                        "decide": {
                            "summary": "Approve whether EA should proceed.",
                            "approval_required": True,
                        },
                        "act": {
                            "summary": "Stage the vendor candidate for approval.",
                            "action_plan": ["Compare constraints", "Prepare approval packet"],
                            "stage": {
                                "kind": "approval_packet",
                                "summary": "One vendor candidate ready for approval.",
                                "artifacts": ["shortlist", "approval_prompt"],
                                "candidate_items": [
                                    {"label": "Candidate A", "url": "https://example.test/candidate-a"}
                                ],
                                "approval_url": "https://example.test/approve",
                                "approval_gate": "User must approve before any purchase or booking.",
                            },
                            "external_action_policy": "Do not buy, book, send, cancel, or commit without explicit approval.",
                        },
                    }
                },
            }
        ],
    )


def test_stage_packet_preserves_reversible_action_contract_without_raw_identity() -> None:
    digest = _digest_with_stage()

    packets = build_stage_packets(digest)
    serialized = json.dumps(packets[0], sort_keys=True)

    assert len(packets) == 1
    packet = packets[0]
    assert packet["schema"] == STAGE_PACKET_SCHEMA
    assert packet["packet_ref"].startswith("stage_packet:proactive-ooda-stage-")
    assert packet["stage"]["kind"] == "approval_packet"
    assert packet["stage"]["payload"]["candidate_items"] == [
        {"label": "Candidate A", "url": "https://example.test/candidate-a"}
    ]
    assert packet["stage"]["payload"]["approval_url"] == "https://example.test/approve"
    assert packet["approval"]["required"] is True
    assert packet["approval"]["irreversible_actions_require_explicit_approval"] is True
    assert "purchase" in packet["execution_policy"]["forbidden_without_explicit_approval"]
    assert "cf-email:user@example.test" not in serialized
    assert "opportunity:private-source" not in serialized


def test_persist_stage_packets_writes_private_packet_files(tmp_path) -> None:
    digest = _digest_with_stage()

    result = persist_stage_packets(digest=digest, output_dir=tmp_path)

    assert not result.errors
    assert len(result.paths) == 1
    assert len(result.packet_refs) == 1
    packet = json.loads((tmp_path / f"{result.packet_refs[0].removeprefix('stage_packet:')}.json").read_text(encoding="utf-8"))
    assert packet["packet_ref"] == result.packet_refs[0]
    assert packet["stage"]["summary"] == "One vendor candidate ready for approval."


def test_persist_stage_packets_reports_directory_errors(tmp_path) -> None:
    digest = _digest_with_stage()
    blocked_path = tmp_path / "blocked"
    blocked_path.write_text("not a directory", encoding="utf-8")

    result = persist_stage_packets(digest=digest, output_dir=blocked_path)

    assert result.paths == ()
    assert result.packet_refs == ()
    assert result.errors == ("stage_packet_dir:FileExistsError",)


def test_default_stage_packet_dir_sits_next_to_state_file(tmp_path) -> None:
    target = default_stage_packet_dir(root=tmp_path, state_path="state/proactive_ooda_notified.json")

    assert target == tmp_path / "state" / "proactive_ooda_stage_packets"
