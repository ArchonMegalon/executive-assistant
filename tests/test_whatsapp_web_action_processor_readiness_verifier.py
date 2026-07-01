from __future__ import annotations

import json
from pathlib import Path

import scripts.verify_whatsapp_web_action_processor_readiness as verifier_module
from scripts.verify_whatsapp_web_action_processor_readiness import verify


def _pin_source_state(monkeypatch, *, head: str = "test-source-head", fingerprint: str = "test-source-fingerprint") -> None:
    monkeypatch.setattr(verifier_module, "_git_head", lambda path=verifier_module.ROOT: head)
    monkeypatch.setattr(verifier_module, "_source_fingerprint", lambda path=verifier_module.ROOT: fingerprint)


def _source_fields(*, head: str = "test-source-head", fingerprint: str = "test-source-fingerprint") -> dict[str, str]:
    return {
        "source_git_head": head,
        "head_semantics": "source_state",
        "source_state_fingerprint": fingerprint,
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
    }


def _write_receipt(path: Path, **payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_whatsapp_web_action_processor_readiness_verifier_accepts_ready_receipt(tmp_path: Path, monkeypatch) -> None:
    _pin_source_state(monkeypatch)
    receipt = tmp_path / ".codex-studio/published/whatsapp_web_action_processor_readiness.generated.json"
    _write_receipt(
        receipt,
        contract_name="ea.whatsapp_web_action_processor_readiness.v1",
        generated_by="scripts/materialize_whatsapp_web_action_processor_readiness.py",
        **_source_fields(),
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
            "Ready runtime means WhatsApp can process both button callbacks and degraded text controls for audiobook voice selection when the upstream transport preserves those messages.",
            "A blocked runtime receipt means the WhatsApp action processor cannot be trusted for fresh live EPUB evidence yet.",
            "Live delivery still requires a fresh WhatsApp job receipt plus public-share delivery and playback evidence.",
        ],
    )

    assert verify(receipt, root=tmp_path) == []


def test_whatsapp_web_action_processor_readiness_verifier_rejects_invalid_ready_flags(tmp_path: Path, monkeypatch) -> None:
    _pin_source_state(monkeypatch)
    receipt = tmp_path / ".codex-studio/published/whatsapp_web_action_processor_readiness.generated.json"
    _write_receipt(
        receipt,
        contract_name="ea.whatsapp_web_action_processor_readiness.v1",
        generated_by="scripts/materialize_whatsapp_web_action_processor_readiness.py",
        **_source_fields(),
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
            "Ready runtime means WhatsApp can process both button callbacks and degraded text controls for audiobook voice selection when the upstream transport preserves those messages.",
            "A blocked runtime receipt means the WhatsApp action processor cannot be trusted for fresh live EPUB evidence yet.",
            "Live delivery still requires a fresh WhatsApp job receipt plus public-share delivery and playback evidence.",
        ],
    )

    issues = verify(receipt, root=tmp_path)
    assert "ready status requires ready=true" in issues
    assert "ready status requires runtime_ready_claim_allowed=true" in issues
    assert "ready status requires reason=ready" in issues
    assert "ready status must not list blocking reasons" in issues


def test_whatsapp_web_action_processor_readiness_verifier_rejects_missing_source_head(tmp_path: Path, monkeypatch) -> None:
    _pin_source_state(monkeypatch)
    receipt = tmp_path / ".codex-studio/published/whatsapp_web_action_processor_readiness.generated.json"
    _write_receipt(
        receipt,
        contract_name="ea.whatsapp_web_action_processor_readiness.v1",
        generated_by="scripts/materialize_whatsapp_web_action_processor_readiness.py",
        head_semantics="source_state",
        source_state_fingerprint="test-source-fingerprint",
        source_state_fingerprint_semantics="worktree_source_files_sha256_excluding_generated_only_paths",
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
            "Ready runtime means WhatsApp can process both button callbacks and degraded text controls for audiobook voice selection when the upstream transport preserves those messages.",
            "A blocked runtime receipt means the WhatsApp action processor cannot be trusted for fresh live EPUB evidence yet.",
            "Live delivery still requires a fresh WhatsApp job receipt plus public-share delivery and playback evidence.",
        ],
    )

    issues = verify(receipt, root=tmp_path)
    assert "source_git_head missing" in issues


def test_whatsapp_web_action_processor_readiness_verifier_accepts_post_commit_head_change_when_source_fingerprint_matches(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _pin_source_state(monkeypatch, head="new-generated-only-head", fingerprint="test-source-fingerprint")
    receipt = tmp_path / ".codex-studio/published/whatsapp_web_action_processor_readiness.generated.json"
    _write_receipt(
        receipt,
        contract_name="ea.whatsapp_web_action_processor_readiness.v1",
        generated_by="scripts/materialize_whatsapp_web_action_processor_readiness.py",
        **_source_fields(head="old-source-head", fingerprint="test-source-fingerprint"),
        status="blocked",
        ready=False,
        reason="sidecar_not_ready",
        reasons=["sidecar_not_ready"],
        runtime_ready_claim_allowed=False,
        live_delivery_claim_allowed=False,
        goal_completion_claim_allowed=False,
        next_action="restore_whatsapp_web_session_sidecar_readiness",
        callback_secret_present=True,
        action_processor_enabled=True,
        sidecar_ready=False,
        state_fresh=True,
        rules=[
            "A ready runtime receipt does not prove a live audiobook delivery happened.",
            "Ready runtime means WhatsApp can process both button callbacks and degraded text controls for audiobook voice selection when the upstream transport preserves those messages.",
            "A blocked runtime receipt means the WhatsApp action processor cannot be trusted for fresh live EPUB evidence yet.",
            "Live delivery still requires a fresh WhatsApp job receipt plus public-share delivery and playback evidence.",
        ],
    )

    assert verify(receipt, root=tmp_path) == []


def test_whatsapp_web_action_processor_readiness_verifier_rejects_source_fingerprint_drift(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _pin_source_state(monkeypatch, head="new-source-head", fingerprint="new-source-fingerprint")
    receipt = tmp_path / ".codex-studio/published/whatsapp_web_action_processor_readiness.generated.json"
    _write_receipt(
        receipt,
        contract_name="ea.whatsapp_web_action_processor_readiness.v1",
        generated_by="scripts/materialize_whatsapp_web_action_processor_readiness.py",
        **_source_fields(head="old-source-head", fingerprint="old-source-fingerprint"),
        status="blocked",
        ready=False,
        reason="sidecar_not_ready",
        reasons=["sidecar_not_ready"],
        runtime_ready_claim_allowed=False,
        live_delivery_claim_allowed=False,
        goal_completion_claim_allowed=False,
        next_action="restore_whatsapp_web_session_sidecar_readiness",
        callback_secret_present=True,
        action_processor_enabled=True,
        sidecar_ready=False,
        state_fresh=True,
        rules=[
            "A ready runtime receipt does not prove a live audiobook delivery happened.",
            "Ready runtime means WhatsApp can process both button callbacks and degraded text controls for audiobook voice selection when the upstream transport preserves those messages.",
            "A blocked runtime receipt means the WhatsApp action processor cannot be trusted for fresh live EPUB evidence yet.",
            "Live delivery still requires a fresh WhatsApp job receipt plus public-share delivery and playback evidence.",
        ],
    )

    issues = verify(receipt, root=tmp_path)
    assert "receipt is stale relative to current source HEAD" in issues
    assert "receipt is stale relative to current source fingerprint" in issues
