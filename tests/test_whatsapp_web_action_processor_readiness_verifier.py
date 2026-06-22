from __future__ import annotations

import json
from pathlib import Path

from scripts.verify_whatsapp_web_action_processor_readiness import verify


def _write_receipt(path: Path, **payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_whatsapp_web_action_processor_readiness_verifier_accepts_ready_receipt(tmp_path: Path) -> None:
    receipt = tmp_path / ".codex-studio/published/whatsapp_web_action_processor_readiness.generated.json"
    _write_receipt(
        receipt,
        contract_name="ea.whatsapp_web_action_processor_readiness.v1",
        generated_by="scripts/materialize_whatsapp_web_action_processor_readiness.py",
        source_git_head="test-source-head",
        head_semantics="source_state",
        status="ready",
        ready=True,
        reason="ready",
        reasons=[],
        runtime_ready_claim_allowed=True,
        live_delivery_claim_allowed=False,
        goal_completion_claim_allowed=False,
        next_action="send_epub_over_whatsapp_to_start_or_refresh_live_audiobook_flow",
        callback_secret_present=True,
        action_processor_enabled=True,
        sidecar_ready=True,
        state_fresh=True,
        rules=[
            "A ready runtime receipt does not prove a live audiobook delivery happened.",
            "A blocked runtime receipt means the WhatsApp action processor cannot be trusted for fresh live EPUB evidence yet.",
            "Live delivery still requires a fresh WhatsApp job receipt plus public-share delivery and playback evidence.",
        ],
    )

    assert verify(receipt, root=tmp_path) == []


def test_whatsapp_web_action_processor_readiness_verifier_rejects_invalid_ready_flags(tmp_path: Path) -> None:
    receipt = tmp_path / ".codex-studio/published/whatsapp_web_action_processor_readiness.generated.json"
    _write_receipt(
        receipt,
        contract_name="ea.whatsapp_web_action_processor_readiness.v1",
        generated_by="scripts/materialize_whatsapp_web_action_processor_readiness.py",
        source_git_head="test-source-head",
        head_semantics="source_state",
        status="ready",
        ready=False,
        reason="callback_secret_missing",
        reasons=["callback_secret_missing"],
        runtime_ready_claim_allowed=False,
        live_delivery_claim_allowed=False,
        goal_completion_claim_allowed=False,
        next_action="seed_whatsapp_callback_secret_and_rerun_readiness",
        callback_secret_present=False,
        action_processor_enabled=True,
        sidecar_ready=True,
        state_fresh=True,
        rules=[
            "A ready runtime receipt does not prove a live audiobook delivery happened.",
            "A blocked runtime receipt means the WhatsApp action processor cannot be trusted for fresh live EPUB evidence yet.",
            "Live delivery still requires a fresh WhatsApp job receipt plus public-share delivery and playback evidence.",
        ],
    )

    issues = verify(receipt, root=tmp_path)
    assert "ready status requires ready=true" in issues
    assert "ready status requires runtime_ready_claim_allowed=true" in issues
    assert "ready status requires reason=ready" in issues
    assert "ready status must not list blocking reasons" in issues


def test_whatsapp_web_action_processor_readiness_verifier_rejects_missing_source_head(tmp_path: Path) -> None:
    receipt = tmp_path / ".codex-studio/published/whatsapp_web_action_processor_readiness.generated.json"
    _write_receipt(
        receipt,
        contract_name="ea.whatsapp_web_action_processor_readiness.v1",
        generated_by="scripts/materialize_whatsapp_web_action_processor_readiness.py",
        head_semantics="source_state",
        status="ready",
        ready=True,
        reason="ready",
        reasons=[],
        runtime_ready_claim_allowed=True,
        live_delivery_claim_allowed=False,
        goal_completion_claim_allowed=False,
        next_action="send_epub_over_whatsapp_to_start_or_refresh_live_audiobook_flow",
        callback_secret_present=True,
        action_processor_enabled=True,
        sidecar_ready=True,
        state_fresh=True,
        rules=[
            "A ready runtime receipt does not prove a live audiobook delivery happened.",
            "A blocked runtime receipt means the WhatsApp action processor cannot be trusted for fresh live EPUB evidence yet.",
            "Live delivery still requires a fresh WhatsApp job receipt plus public-share delivery and playback evidence.",
        ],
    )

    issues = verify(receipt, root=tmp_path)
    assert "source_git_head missing" in issues
