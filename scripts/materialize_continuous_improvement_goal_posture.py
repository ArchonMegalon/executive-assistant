#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from scripts.source_state_head import resolve_source_state_head
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
DEFAULT_OFFICE_RECEIPT = ROOT / ".codex-studio/published/ea_office_loop_goal.generated.json"
DEFAULT_SIGNAL_RECEIPT = ROOT / ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json"
DEFAULT_MEDIA_RECEIPT = ROOT / ".codex-studio/published/active_media_ltd_goal_bundle.generated.json"
DEFAULT_MANFRED_RECEIPT = ROOT / ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json"
DEFAULT_QUALITY_RECEIPT = ROOT / ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json"
DEFAULT_TEABLE_RECOVERY_READINESS = ROOT / ".codex-studio/published/teable_env_recovery_readiness.generated.json"
DEFAULT_PROACTIVE_OODA_OPERATOR_STATUS = ROOT / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
DEFAULT_PROACTIVE_OODA_GOLD_ACCEPTANCE = ROOT / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
DEFAULT_TELEGRAM_AUDIOBOOK_READINESS = ROOT / ".codex-studio/published/telegram_audiobook_live_readiness.generated.json"
DEFAULT_TELEGRAM_AUDIOBOOK_DELIVERY = ROOT / ".codex-studio/published/telegram_audiobook_live_delivery.generated.json"
DEFAULT_WHATSAPP_AUDIOBOOK_INTAKE = ROOT / ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json"
DEFAULT_WHATSAPP_AUDIOBOOK_BUNDLE = ROOT / ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json"
DEFAULT_WHATSAPP_AUDIOBOOK_DELIVERY = ROOT / ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json"
DEFAULT_WHATSAPP_AUDIOBOOK_SHARE = ROOT / ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json"
DEFAULT_WHATSAPP_AUDIOBOOK_VOICE = ROOT / ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json"

BLOCKING_PREFIXES = ("blocked", "fail", "missing", "waiting", "error")
MORNING_BRIEF_ACCEPTANCE_RECEIPT = "real operator acceptance that the morning brief was worth reading"
WEEKLY_SIGNAL_REVIEW_ACCEPTANCE_RECEIPT = "real weekly signal-to-decision review acceptance receipt"
PROACTIVE_OODA_ACCEPTANCE_RECEIPT = (
    "real proactive OODA packet accepted with action-required-only routed delivery, approved-source or transcript signal, "
    "live browse evidence, auditor-passed chosen candidate, staged reversible artifact, mirrored Teable delivery, "
    "current-packet, stale-approval, and decision facts, and explicit approval outcome"
)
FRESH_HOST_TEABLE_RECOVERY_RECEIPT = "fresh-host Teable recovery drill receipt mirrored into the repo"
MANFRED_REALTIME_ACCEPTANCE_RECEIPT = "consented Manfred STT/TTS realtime conversation proof"
TELEGRAM_AUDIOBOOK_LIVE_DELIVERY_RECEIPT = "passing Telegram audiobook live delivery receipt"
WHATSAPP_AUDIOBOOK_LIVE_DELIVERY_RECEIPT = "passing WhatsApp audiobook live delivery receipt"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head(path: Path) -> str:
    return resolve_source_state_head(path)


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _compact(value: object, default: str = "missing") -> str:
    text = " ".join(str(value or "").split()).strip()
    return text or default


def _status(payload: dict[str, Any], default: str = "missing_receipt") -> str:
    return _compact(payload.get("status"), default=default).lower()


def _is_blocking(status: str) -> bool:
    normalized = _compact(status).lower()
    return normalized.startswith(BLOCKING_PREFIXES) or normalized == "command_backed_no_published_receipt"


def _load_receipt(root: Path, path: Path) -> tuple[dict[str, Any], str]:
    payload = _json(path)
    if payload:
        return payload, _display_path(root, path)
    return {}, _display_path(root, path)


def _source_receipt(path_text: str, payload: dict[str, Any], *, current_source_head: str = "") -> dict[str, Any]:
    receipt = {
        "path": path_text,
        "present": bool(payload),
        "contract_name": _compact(payload.get("contract_name")),
        "status": _status(payload),
    }
    source_head = str(payload.get("source_git_head") or "").strip()
    if source_head:
        receipt["source_git_head"] = source_head
        if current_source_head:
            receipt["source_fresh_to_current_source"] = source_head == current_source_head
    return receipt


def _lens(
    *,
    key: str,
    title: str,
    status: str,
    summary: str,
    next_action: str,
    verifier_commands: list[str],
    source_receipts: list[dict[str, Any]],
    components: list[dict[str, Any]] | None = None,
    status_class: str | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": status,
        "status_class": status_class or ("blocking" if _is_blocking(status) else "progress"),
        "summary": summary,
        "next_action": next_action,
        "verifier_commands": verifier_commands,
        "source_receipts": source_receipts,
        "components": components or [],
    }


def _deliver_component(
    *,
    key: str,
    title: str,
    payload: dict[str, Any] | None = None,
    fallback_status: str = "missing_receipt",
    summary: str,
    next_action: str,
    receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    status = _status(payload or {}, default=fallback_status)
    return {
        "key": key,
        "title": title,
        "status": status,
        "status_class": "blocking" if _is_blocking(status) else "progress",
        "summary": summary,
        "next_action": next_action,
        "source_receipts": receipts,
    }


def _acceptance_proof_requirement(
    *,
    key: str,
    title: str,
    lens: str,
    required_next_receipt: str,
    evidence_kind: str,
    capture_surfaces: list[str],
    next_action: str,
    claim_boundary: str,
    source_receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "lens": lens,
        "status": "pending_real_world_evidence",
        "required_next_receipt": required_next_receipt,
        "evidence_kind": evidence_kind,
        "capture_surfaces": [surface for surface in capture_surfaces if str(surface or "").strip()],
        "next_action": next_action,
        "claim_boundary": claim_boundary,
        "source_receipts": source_receipts,
    }


def build_goal_posture(
    *,
    root: Path = ROOT,
    output_path: Path = DEFAULT_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    current_source_head = _git_head(root)
    office, office_path = _load_receipt(root, root / DEFAULT_OFFICE_RECEIPT.relative_to(ROOT))
    signal, signal_path = _load_receipt(root, root / DEFAULT_SIGNAL_RECEIPT.relative_to(ROOT))
    media, media_path = _load_receipt(root, root / DEFAULT_MEDIA_RECEIPT.relative_to(ROOT))
    manfred, manfred_path = _load_receipt(root, root / DEFAULT_MANFRED_RECEIPT.relative_to(ROOT))
    quality, quality_path = _load_receipt(root, root / DEFAULT_QUALITY_RECEIPT.relative_to(ROOT))
    recovery, recovery_path = _load_receipt(root, root / DEFAULT_TEABLE_RECOVERY_READINESS.relative_to(ROOT))
    ooda_status, ooda_status_path = _load_receipt(root, root / DEFAULT_PROACTIVE_OODA_OPERATOR_STATUS.relative_to(ROOT))
    ooda_gold, ooda_gold_path = _load_receipt(root, root / DEFAULT_PROACTIVE_OODA_GOLD_ACCEPTANCE.relative_to(ROOT))
    tg_ready, tg_ready_path = _load_receipt(root, root / DEFAULT_TELEGRAM_AUDIOBOOK_READINESS.relative_to(ROOT))
    tg_live, tg_live_path = _load_receipt(root, root / DEFAULT_TELEGRAM_AUDIOBOOK_DELIVERY.relative_to(ROOT))
    wa_intake, wa_intake_path = _load_receipt(root, root / DEFAULT_WHATSAPP_AUDIOBOOK_INTAKE.relative_to(ROOT))
    wa_bundle, wa_bundle_path = _load_receipt(root, root / DEFAULT_WHATSAPP_AUDIOBOOK_BUNDLE.relative_to(ROOT))
    wa_live, wa_live_path = _load_receipt(root, root / DEFAULT_WHATSAPP_AUDIOBOOK_DELIVERY.relative_to(ROOT))
    wa_share, wa_share_path = _load_receipt(root, root / DEFAULT_WHATSAPP_AUDIOBOOK_SHARE.relative_to(ROOT))
    wa_voice, wa_voice_path = _load_receipt(root, root / DEFAULT_WHATSAPP_AUDIOBOOK_VOICE.relative_to(ROOT))

    detect_lens = _lens(
        key="detect",
        title="Signal ingest and prioritization",
        status=_status(signal),
        summary="Turn incoming signals into a bounded operator packet and proactive OODA shortlist that can become decision-ready packets instead of letting them pile up as ambient noise.",
        next_action=_compact(signal.get("next_action"), default="review_weekly_signal_to_decision_packet_with_operator"),
        verifier_commands=[
            "make verify-whole-project-signal-to-decision-receipt",
            "make verify-proactive-ooda",
        ],
        source_receipts=[_source_receipt(signal_path, signal, current_source_head=current_source_head)],
    )

    decide_lens = _lens(
        key="decide",
        title="Decision and office-loop closure",
        status=_status(office),
        summary="Keep the morning brief, decision queue, commitment loop, and proactive OODA packet loop coherent enough to drive ordinary daily work and stage decision-ready approvals.",
        next_action=_compact(office.get("next_action"), default="collect_real_daily_office_loop_acceptance_evidence"),
        verifier_commands=[
            "make verify-office-loop-goal-receipt",
        ],
        source_receipts=[_source_receipt(office_path, office, current_source_head=current_source_head)],
    )

    tg_summary = (
        f"live delivery {_status(tg_live)}; readiness {_status(tg_ready)}"
        if tg_live or tg_ready
        else "Telegram audiobook live receipts are not mirrored."
    )
    wa_summary = (
        f"intake {_status(wa_intake)}; bundle {_status(wa_bundle)}; live {_status(wa_live)}; share {_status(wa_share)}; voice {_status(wa_voice)}"
        if wa_intake or wa_bundle or wa_live or wa_share or wa_voice
        else "WhatsApp audiobook receipts are not mirrored."
    )

    deliver_components = [
        _deliver_component(
            key="promo_media",
            title="Promo and cinematic media",
            payload=media,
            summary="Premium public media must sound good, cover the runtime, and keep provider claims honest.",
            next_action=_compact(
                media.get("next_action"),
                default="collect_external_provider_and_public_route_proofs_before_any_gold_or_live_provider_claim",
            ),
            receipts=[_source_receipt(media_path, media, current_source_head=current_source_head)],
        ),
        _deliver_component(
            key="manfred_speech",
            title="Manfred realtime speech",
            payload=manfred,
            summary=_compact(manfred.get("current_label"), default="Realtime conversation evidence is not mirrored."),
            next_action=_compact(
                manfred.get("next_action"),
                default="promote only a consented real captured STT fixture that passes the provider benchmark",
            ),
            receipts=[_source_receipt(manfred_path, manfred, current_source_head=current_source_head)],
        ),
        _deliver_component(
            key="telegram_audiobook",
            title="Telegram audiobook delivery",
            payload=tg_live or tg_ready,
            summary=tg_summary,
            next_action="keep live Telegram audiobook delivery passing while widening playback acceptance evidence",
            receipts=[
                _source_receipt(tg_ready_path, tg_ready, current_source_head=current_source_head),
                _source_receipt(tg_live_path, tg_live, current_source_head=current_source_head),
            ],
        ),
        _deliver_component(
            key="whatsapp_audiobook",
            title="WhatsApp audiobook delivery",
            payload=wa_live or wa_bundle or wa_intake,
            summary=wa_summary,
            next_action="clear blocked WhatsApp live delivery and keep share-link playback plus voice-selection flow honest",
            receipts=[
                _source_receipt(wa_intake_path, wa_intake, current_source_head=current_source_head),
                _source_receipt(wa_bundle_path, wa_bundle, current_source_head=current_source_head),
                _source_receipt(wa_live_path, wa_live, current_source_head=current_source_head),
                _source_receipt(wa_share_path, wa_share, current_source_head=current_source_head),
                _source_receipt(wa_voice_path, wa_voice, current_source_head=current_source_head),
            ],
        ),
    ]

    deliver_has_blocker = any(_is_blocking(str(component.get("status") or "")) for component in deliver_components)
    deliver_status = "mixed_local_progress" if deliver_has_blocker else "ready_local_evidence"
    deliver_next_action = next(
        (
            _compact(component.get("next_action"))
            for component in deliver_components
            if _is_blocking(str(component.get("status") or ""))
        ),
        "keep user-facing delivery proofs current and human-reviewed",
    )
    deliver_lens = _lens(
        key="deliver",
        title="User-facing delivery",
        status=deliver_status,
        summary="Complete real user-facing loops across media, speech, and audiobook channels instead of stopping at local generation.",
        next_action=deliver_next_action,
        verifier_commands=[
            "make verify-active-media-ltd-goal-bundle",
            "make verify-manfred-realtime-conversation-readiness",
            "make verify-telegram-audiobook-live-readiness",
            "make verify-telegram-audiobook-live-delivery-receipt",
            "make verify-whatsapp-audiobook-local-intake-proof",
            "make verify-whatsapp-audiobook-operator-proof-bundle",
            "make verify-whatsapp-audiobook-live-delivery-receipt",
            "make verify-whatsapp-audiobook-public-share-playback",
        ],
        source_receipts=[],
        components=deliver_components,
        status_class="blocking" if deliver_has_blocker else "progress",
    )

    if recovery:
        recover_lens = _lens(
            key="recover",
            title="Fresh-host recovery",
            status=_status(recovery),
            summary=_compact(
                recovery.get("summary"),
                default="Teable recovery readiness is mirrored locally, but fresh-host drill proof is still pending.",
            ),
            next_action=_compact(
                recovery.get("next_action"),
                default="run_shell_seeded_fresh_host_probe_and_mirror_drill_evidence",
            ),
            verifier_commands=[
                "make verify-teable-env-recovery-readiness",
                "make verify-env-teable-recovery",
                "make probe-teable-recovery",
                "make env-check-teable",
                "make env-fresh-host-teable",
                "make env-probe-teable",
            ],
            source_receipts=[_source_receipt(recovery_path, recovery, current_source_head=current_source_head)],
        )
    else:
        recover_lens = _lens(
            key="recover",
            title="Fresh-host recovery",
            status="command_backed_no_published_receipt",
            summary="Teable recovery has runnable operator commands, but no mirrored published recovery receipt is attached yet.",
            next_action="rehearse fresh-host Teable restore before widening claims",
            verifier_commands=[
                "make probe-teable-recovery",
                "make env-check-teable",
                "make env-fresh-host-teable",
                "make verify-env-teable-recovery",
            ],
            source_receipts=[],
            status_class="blocking",
        )

    prove_lens = _lens(
        key="prove",
        title="Real-world acceptance and claim limits",
        status=_status(quality),
        summary="Keep local route confidence separate from real operator/principal acceptance before calling EA a good executive assistant.",
        next_action=_compact(
            quality.get("next_action"),
            default="collect real principal/operator acceptance that the morning brief was worth reading and one proactive OODA packet was worth approving",
        ),
        verifier_commands=[
            "make verify-executive-assistant-quality-readiness",
        ],
        source_receipts=[_source_receipt(quality_path, quality, current_source_head=current_source_head)],
    )

    lenses = [detect_lens, decide_lens, deliver_lens, recover_lens, prove_lens]
    blocking_reasons: list[str] = []
    for lens in lenses:
        if lens["key"] == "deliver":
            for component in lens["components"]:
                component_status = _compact(component.get("status")).lower()
                if _is_blocking(component_status):
                    blocking_reasons.append(f"deliver:{component['key']}={component_status}")
        elif _is_blocking(str(lens["status"])):
            blocking_reasons.append(f"{lens['key']}={lens['status']}")

    if _status(quality) == "blocked_real_world_acceptance":
        overall_status = "blocked_real_world_acceptance"
    elif blocking_reasons:
        overall_status = "active_with_blockers"
    else:
        overall_status = "ready_local_direction"

    acceptance_proof_requirements = [
        _acceptance_proof_requirement(
            key="morning_brief_operator_acceptance",
            title="Morning brief operator acceptance",
            lens="prove",
            required_next_receipt=MORNING_BRIEF_ACCEPTANCE_RECEIPT,
            evidence_kind="real_operator_acceptance",
            capture_surfaces=[
                ".codex-studio/published/ea_executive_assistant_acceptance_evidence.generated.json",
                quality_path,
            ],
            next_action="record_redacted_operator_acceptance_for_real_morning_brief",
            claim_boundary="does_not_prove_good_executive_assistant_until_real_operator_or_principal_acceptance_is_recorded",
            source_receipts=[_source_receipt(quality_path, quality, current_source_head=current_source_head)],
        ),
        _acceptance_proof_requirement(
            key="weekly_signal_to_decision_review_acceptance",
            title="Weekly signal-to-decision review acceptance",
            lens="detect",
            required_next_receipt=WEEKLY_SIGNAL_REVIEW_ACCEPTANCE_RECEIPT,
            evidence_kind="real_review_acceptance",
            capture_surfaces=[signal_path],
            next_action="record_weekly_signal_to_decision_review_acceptance",
            claim_boundary="does_not_prove_signal_loop_value_until_a_real_operator_review_is_recorded",
            source_receipts=[_source_receipt(signal_path, signal, current_source_head=current_source_head)],
        ),
        _acceptance_proof_requirement(
            key="proactive_ooda_packet_acceptance",
            title="Proactive OODA packet approval outcome",
            lens="decide",
            required_next_receipt=PROACTIVE_OODA_ACCEPTANCE_RECEIPT,
            evidence_kind="approval_outcome",
            capture_surfaces=[ooda_gold_path, ooda_status_path],
            next_action="tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome",
            claim_boundary="does_not_prove_assistant_grade_proactive_ooda_until_a_real_approval_outcome_is_captured",
            source_receipts=[
                _source_receipt(ooda_gold_path, ooda_gold, current_source_head=current_source_head),
                _source_receipt(ooda_status_path, ooda_status, current_source_head=current_source_head),
            ],
        ),
        _acceptance_proof_requirement(
            key="fresh_host_teable_recovery_drill",
            title="Fresh-host Teable recovery drill",
            lens="recover",
            required_next_receipt=FRESH_HOST_TEABLE_RECOVERY_RECEIPT,
            evidence_kind="fresh_host_recovery_drill",
            capture_surfaces=[recovery_path],
            next_action="run_shell_seeded_fresh_host_probe_and_mirror_drill_evidence",
            claim_boundary="does_not_prove_recovery_readiness_until_fresh_host_drill_evidence_is_mirrored",
            source_receipts=[_source_receipt(recovery_path, recovery, current_source_head=current_source_head)],
        ),
    ]
    if any(reason.startswith("deliver:manfred_speech") for reason in blocking_reasons):
        acceptance_proof_requirements.append(
            _acceptance_proof_requirement(
                key="manfred_stt_tts_realtime_conversation",
                title="Consented Manfred realtime conversation proof",
                lens="deliver",
                required_next_receipt=MANFRED_REALTIME_ACCEPTANCE_RECEIPT,
                evidence_kind="consented_realtime_media_proof",
                capture_surfaces=[manfred_path],
                next_action="capture_consented_manfred_stt_tts_realtime_proof",
                claim_boundary="does_not_prove_realtime_speech_delivery_until_a_consented_room_conversation_receipt_passes",
                source_receipts=[_source_receipt(manfred_path, manfred, current_source_head=current_source_head)],
            )
        )
    if any(reason.startswith("deliver:telegram_audiobook") for reason in blocking_reasons):
        acceptance_proof_requirements.append(
            _acceptance_proof_requirement(
                key="telegram_audiobook_live_delivery",
                title="Telegram audiobook live delivery receipt",
                lens="deliver",
                required_next_receipt=TELEGRAM_AUDIOBOOK_LIVE_DELIVERY_RECEIPT,
                evidence_kind="live_delivery_receipt",
                capture_surfaces=[tg_live_path, tg_ready_path],
                next_action=_compact(
                    tg_live.get("next_action") or tg_ready.get("next_action"),
                    default="capture_passing_telegram_audiobook_live_delivery_receipt",
                ),
                claim_boundary="does_not_prove_telegram_audiobook_delivery_until_live_delivery_and_playback_receipts_pass",
                source_receipts=[
                    _source_receipt(tg_live_path, tg_live, current_source_head=current_source_head),
                    _source_receipt(tg_ready_path, tg_ready, current_source_head=current_source_head),
                ],
            )
        )
    if any(reason.startswith("deliver:whatsapp_audiobook") for reason in blocking_reasons):
        acceptance_proof_requirements.append(
            _acceptance_proof_requirement(
                key="whatsapp_audiobook_live_delivery",
                title="WhatsApp audiobook live delivery receipt",
                lens="deliver",
                required_next_receipt=WHATSAPP_AUDIOBOOK_LIVE_DELIVERY_RECEIPT,
                evidence_kind="live_delivery_receipt",
                capture_surfaces=[wa_live_path, wa_bundle_path, wa_share_path, wa_voice_path],
                next_action="capture_passing_whatsapp_audiobook_live_delivery_receipt",
                claim_boundary="does_not_prove_whatsapp_delivery_until_live_delivery_and_playback_receipts_pass",
                source_receipts=[
                    _source_receipt(wa_live_path, wa_live, current_source_head=current_source_head),
                    _source_receipt(wa_bundle_path, wa_bundle, current_source_head=current_source_head),
                    _source_receipt(wa_share_path, wa_share, current_source_head=current_source_head),
                    _source_receipt(wa_voice_path, wa_voice, current_source_head=current_source_head),
                ],
            )
        )
    required_next_receipts = [
        str(requirement.get("required_next_receipt") or "").strip()
        for requirement in acceptance_proof_requirements
        if str(requirement.get("required_next_receipt") or "").strip()
    ]

    receipt = {
        "contract_name": "ea.continuous_improvement_goal_posture.v1",
        "generated_at": generated_at or _utc_now(),
        "generated_by": "scripts/materialize_continuous_improvement_goal_posture.py",
        "source_git_head": current_source_head,
        "head_semantics": "source_state",
        "output_path": _display_path(root, output_path),
        "goal_doc": ".codex-design/ea/CONTINUOUS_IMPROVEMENT_GOAL.md",
        "goal_shorthand": "Make EA the user's dependable executive operating system: paid-human-assistant-grade proactive OODA with transcript-aware ingest, auditor-passed decision-ready packets, staged follow-through, Teable-mirrored current/stale state, self-healing, and governed by owning truth planes rather than assistant-local lore.",
        "execution_lenses": [lens["key"] for lens in lenses],
        "overall_status": overall_status,
        "goal_completion_claim_allowed": False,
        "real_use_claim_allowed": overall_status == "ready_local_direction" and _status(quality) == "pass",
        "lenses": lenses,
        "blocking_reasons": blocking_reasons,
        "required_next_receipts": required_next_receipts,
        "acceptance_proof_requirements": acceptance_proof_requirements,
        "rules": [
            "Local route receipts and operator commands may guide work, but they do not by themselves prove real daily usefulness.",
            "Irreversible purchases, bookings, cancellations, outbound commitments, and sent messages must stay consent-gated even when proactive OODA staging is automated.",
            "Telegram is an action surface, not a progress log; proactive delivery must stay quiet unless the user needs to approve, choose, unblock, review, or answer something.",
            "Proactive OODA packets must pass a context/provider-fit auditor before user delivery; reachable URLs, extracted email addresses, or generic search hits are not sufficient.",
            "Pocket.ai or other consented audio transcripts may feed OODA only as approved signals with privacy, retention, source, and current/stale status preserved.",
            "The recover lens may use a mirrored local readiness receipt, but it must not claim pass until a fresh-host Teable recovery drill receipt is mirrored.",
            "Teable may mirror important proactive OODA facts and blockers, but it remains an admin projection rather than canonical truth.",
            "The prove lens controls good-executive-assistant overclaims; if it is blocked, the goal stays open.",
        ],
    }
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize the long-running continuous-improvement goal posture receipt.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    output_path = args.output if args.output.is_absolute() else args.root / args.output
    receipt = build_goal_posture(root=args.root, output_path=output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.pretty:
        print(json.dumps(receipt, indent=2, sort_keys=True))
    else:
        print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
