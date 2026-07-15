from __future__ import annotations

import json
from pathlib import Path

from ea.scripts.verify_telegram_audiobook_live_delivery_receipt import verify
from scripts.source_state_head import resolve_source_state_head
from scripts.source_state_head import resolve_source_worktree_fingerprint


ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, **payload: object) -> None:
    payload.setdefault("source_git_head", resolve_source_state_head(ROOT))
    payload.setdefault("head_semantics", "source_state")
    payload.setdefault("source_state_fingerprint", resolve_source_worktree_fingerprint(ROOT))
    payload.setdefault(
        "source_state_fingerprint_semantics",
        "worktree_source_files_sha256_excluding_generated_only_paths",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _pass_receipt(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "contract_name": "ea.telegram_audiobook_live_delivery_receipt.v1",
        "generated_by": "ea/scripts/materialize_telegram_audiobook_live_delivery_receipt.py",
        "status": "pass",
        "live_delivery_claim_allowed": True,
        "machine_playback_e2e_verified": True,
        "real_user_playback_acceptance_verified": False,
        "goal_completion_claim_allowed": False,
        "failed_codes": [],
        "next_action": "capture_real_user_playback_acceptance_or_close_operator_loop",
        "next_action_href": "/integrations/telegram",
        "next_action_label": "Open Telegram",
        "next_action_method": "get",
        "operator_action_packet": {
            "user_action_required": False,
            "reason": "no_user_voice_choice_required",
            "raw_voice_ids_exposed": False,
            "callback_tokens_exposed": False,
        },
        "pending_user_selected_voice_job_count": 0,
        "duplicate_suppression": {
            "action_required_only": True,
            "only_current_jobs_can_require_user_action": True,
            "active_pending_voice_job_count": 0,
            "duplicate_active_pending_source_key_count": 0,
            "raw_voice_ids_exposed": False,
            "callback_tokens_exposed": False,
        },
        "privacy": {
            "provider_secret_exposed": False,
            "audiobookshelf_token_exposed": False,
        },
    }
    payload.update(overrides)
    return payload


def test_telegram_audiobook_live_delivery_verifier_accepts_machine_playable_pass(tmp_path: Path) -> None:
    receipt = tmp_path / ".codex-studio/published/telegram_audiobook_live_delivery.generated.json"
    _write(receipt, **_pass_receipt())

    assert verify(receipt) == []


def test_telegram_audiobook_live_delivery_verifier_accepts_human_accepted_closeout(tmp_path: Path) -> None:
    receipt = tmp_path / ".codex-studio/published/telegram_audiobook_live_delivery.generated.json"
    _write(
        receipt,
        **_pass_receipt(
            real_user_playback_acceptance_verified=True,
            next_action="close_operator_loop",
            next_action_href="/app/channel-loop",
            next_action_label="Open channel loop",
        ),
    )

    assert verify(receipt) == []


def test_telegram_audiobook_live_delivery_verifier_rejects_missing_surface(tmp_path: Path) -> None:
    receipt = tmp_path / ".codex-studio/published/telegram_audiobook_live_delivery.generated.json"
    _write(
        receipt,
        contract_name="ea.telegram_audiobook_live_delivery_receipt.v1",
        generated_by="ea/scripts/materialize_telegram_audiobook_live_delivery_receipt.py",
        status="blocked",
        live_delivery_claim_allowed=False,
        machine_playback_e2e_verified=False,
        real_user_playback_acceptance_verified=False,
        goal_completion_claim_allowed=False,
        failed_codes=["user_selected_voice_delivery_not_ready"],
        next_action="choose_one_telegram_audiobook_voice_sample",
        next_action_href="",
        next_action_label="",
        next_action_method="",
        privacy={
            "provider_secret_exposed": False,
            "audiobookshelf_token_exposed": False,
        },
    )

    issues = verify(receipt)
    assert "next_action_href must match the mapped Telegram operator surface" in issues
    assert "next_action_label must match the mapped Telegram operator surface" in issues
    assert "next_action_method must match the mapped Telegram operator surface" in issues


def test_telegram_audiobook_live_delivery_verifier_rejects_human_accepted_pass_without_closeout(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / ".codex-studio/published/telegram_audiobook_live_delivery.generated.json"
    _write(
        receipt,
        **_pass_receipt(
            real_user_playback_acceptance_verified=True,
            next_action="capture_real_user_playback_acceptance_or_close_operator_loop",
            next_action_href="/integrations/telegram",
            next_action_label="Open Telegram",
        ),
    )

    issues = verify(receipt)
    assert "accepted human playback must close the operator loop" in issues
