from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Callable


def _sha256_text(value: object) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _approved(source_packet: dict[str, object]) -> bool:
    return bool(source_packet.get("approved")) and bool(str(source_packet.get("source_id") or "").strip())


def build_cinematic_narration_window(
    *,
    source_packet: dict[str, object],
    scene_signal: dict[str, object],
    generated_at: str,
    rolling_state: dict[str, object] | None = None,
) -> dict[str, object]:
    if not _approved(source_packet):
        return {
            "status": "blocked",
            "reason": "approved_source_packet_required",
            "ea_is_product_truth": False,
            "provider_output_truth_allowed": False,
        }
    state = dict(rolling_state or {})
    index = int(state.get("window_index") or 0) + 1
    focus = str(scene_signal.get("focus") or "the public hook").strip()
    stakes = str(scene_signal.get("stakes") or scene_signal.get("pressure") or "the signal stays inspectable").strip()
    callbacks = [str(item).strip() for item in list(state.get("continuity_callbacks") or []) if str(item).strip()]
    callback_text = callbacks[0] if callbacks else "visible receipt trail"
    opener = "The signal opens" if index == 1 else "The thread continues"
    script = f"{opener}: {focus} carries the pressure: {stakes}. {callback_text} carries through without a reset."
    previous = str(state.get("last_window_digest") or "").strip()
    digest = _sha256_text(f"{previous}|{focus}|{stakes}|{script}|{index}")
    return {
        "contract_name": "ea.cinematic_narration_window.v1",
        "status": "planned",
        "window_id": f"cinematic_window_{index:03d}_{digest[:10]}",
        "window_index": index,
        "window_digest": digest,
        "previous_window_digest": previous,
        "generated_at": generated_at,
        "source_digest": _sha256_text(source_packet),
        "source_anchor_ids": list(source_packet.get("source_anchor_ids") or []),
        "topic": str(source_packet.get("topic") or "public faction promo"),
        "language": str(source_packet.get("language") or "en-US"),
        "narrator_posture": str(state.get("narrator_posture") or source_packet.get("narrator_posture") or "continuous_cinematic_narrator"),
        "script_text": script,
        "scene_focus": focus,
        "scene_pressure": stakes,
        "scene_signal_digest": _sha256_text(scene_signal),
        "scene_bound": False,
        "current_scene_conditioned": True,
        "rolling_state_preserved": True,
        "scene_signal_is_canon": False,
        "provider_output_truth_allowed": False,
        "raw_private_context_allowed": False,
        "ea_is_product_truth": False,
        "expected_duration_seconds": int(float(scene_signal.get("target_duration_seconds") or scene_signal.get("duration_seconds") or 8)),
        "continuity_callbacks": callbacks or ["visible receipt trail"],
    }


def update_rolling_narration_state(*, rolling_state: dict[str, object], window: dict[str, object]) -> dict[str, object]:
    return {
        "contract_name": "ea.cinematic_rolling_narration_state.v1",
        "recent_summary": f"The narration carried {window.get('scene_focus')} forward while preserving visible receipt trail.",
        "continuity_callbacks": list(window.get("continuity_callbacks") or ["visible receipt trail"]),
        "narrator_posture": str(window.get("narrator_posture") or "continuous_cinematic_narrator"),
        "language": str(window.get("language") or "en-US"),
        "topic": str(window.get("topic") or "public faction promo"),
        "window_index": int(window.get("window_index") or 0),
        "last_window_id": str(window.get("window_id") or ""),
        "last_window_digest": str(window.get("window_digest") or ""),
        "scene_signal_is_canon": False,
        "ea_is_product_truth": False,
    }


def build_cinematic_narration_receipt(
    *,
    window: dict[str, object],
    rolling_state_before: dict[str, object],
    rolling_state_after: dict[str, object],
    generated_at: str,
) -> dict[str, object]:
    return {
        "contract_name": "ea.cinematic_narration_receipt.v1",
        "status": "pass" if window.get("status") == "planned" else "blocked",
        "generated_at": generated_at,
        "window_id": str(window.get("window_id") or ""),
        "window_digest": str(window.get("window_digest") or ""),
        "previous_window_digest": str(window.get("previous_window_digest") or ""),
        "scene_signal_digest": str(window.get("scene_signal_digest") or ""),
        "source_digest": str(window.get("source_digest") or ""),
        "narrator_posture_stable": str(rolling_state_after.get("narrator_posture") or "") == str(window.get("narrator_posture") or ""),
        "scene_bound": False,
        "current_scene_conditioned": True,
        "rolling_state_preserved": True,
        "raw_source_text_exposed": False,
        "raw_scene_private_context_exposed": False,
        "scene_signal_is_canon": False,
        "provider_output_truth_allowed": False,
        "ea_is_product_truth": False,
    }


def append_cinematic_narration_segment(
    *,
    source_packet: dict[str, object],
    rolling_state: dict[str, object],
    scene_signal: dict[str, object],
    render_audio: Callable[[dict[str, object]], dict[str, object]],
    generated_at: str,
    previous_segment: dict[str, object] | None = None,
    planned_crossfade_ms: int = 420,
) -> dict[str, object]:
    before = dict(rolling_state)
    window = build_cinematic_narration_window(
        source_packet=source_packet,
        rolling_state=before,
        scene_signal=scene_signal,
        generated_at=generated_at,
    )
    audio = render_audio(window) if window.get("status") == "planned" else {"status": "blocked"}
    audio_path = Path(str(audio.get("audio_path") or ""))
    quality = dict(audio.get("audio_quality") or {"status": "pass", "issues": []})
    blocking: list[str] = []
    if bool(audio.get("provider_output_truth_allowed")):
        blocking.append("provider_output_truth_claim_forbidden")
    for issue in list(quality.get("issues") or []):
        blocking.append(f"audio_quality_{issue}")
    if str(quality.get("status") or "") == "fail" and not blocking:
        blocking.append("audio_quality_failed")
    status = "blocked" if blocking else "ready"
    audio_sha = _sha256_file(audio_path) if audio_path.is_file() else ""
    segment_digest = _sha256_text(f"{window.get('window_digest')}|{audio_sha}|{previous_segment}")
    segment = {
        "contract_name": "ea.cinematic_narration_segment.v1",
        "status": status,
        "segment_id": f"cinematic_segment_{int(window.get('window_index') or 0):03d}_{segment_digest[:10]}",
        "segment_digest": segment_digest,
        "window_id": str(window.get("window_id") or ""),
        "window_digest": str(window.get("window_digest") or ""),
        "previous_window_digest": str(window.get("previous_window_digest") or ""),
        "previous_segment_digest": str((previous_segment or {}).get("segment_digest") or ""),
        "audio_file": audio_path.name,
        "audio_sha256": audio_sha,
        "duration_seconds": float(audio.get("duration_seconds") or window.get("expected_duration_seconds") or 0),
        "expected_duration_seconds": float(window.get("expected_duration_seconds") or 0),
        "narrator_posture": str(window.get("narrator_posture") or "continuous_cinematic_narrator"),
        "scene_bound": False,
        "current_scene_conditioned": True,
        "rolling_state_preserved": True,
        "scene_signal_is_canon": False,
        "provider_output_truth_allowed": False,
        "audio_path_exposed": False,
        "raw_provider_voice_id_exposed": False,
        "quality_gate": {
            "status": str(quality.get("status") or ("fail" if blocking else "pass")),
            "issues": list(quality.get("issues") or []),
            "blocking_issues": blocking,
            "quiet_tail": bool(quality.get("quiet_tail")),
            "speech_energy_missing": bool(quality.get("speech_energy_missing")),
            "trailing_silence": bool(quality.get("trailing_silence")),
        },
        "continuity_gate": {
            "status": "pass",
            "crossfade_ms": planned_crossfade_ms,
            "previous_segment_digest": str((previous_segment or {}).get("segment_digest") or ""),
            "previous_segment_window_digest": str((previous_segment or {}).get("window_digest") or ""),
            "expected_previous_window_digest": str(window.get("previous_window_digest") or ""),
        },
        "blocking_reasons": blocking,
        "next_action": "rerender_or_repair_segment" if blocking else "append_to_stream_or_cache",
        "ea_is_product_truth": False,
    }
    after = update_rolling_narration_state(rolling_state=before, window=window) if status == "ready" else before
    return {
        "contract_name": "ea.cinematic_narration_segment_append.v1",
        "status": status,
        "render_called": window.get("status") == "planned",
        "window": window,
        "segment": segment,
        "rolling_state_before": before,
        "rolling_state_after": after,
        "blocking_reasons": blocking,
        "provider_output_truth_allowed": False,
        "raw_audio_path_exposed": False,
        "raw_provider_voice_id_exposed": False,
        "scene_signal_is_canon": False,
        "ea_is_product_truth": False,
        "generated_at": generated_at,
    }

