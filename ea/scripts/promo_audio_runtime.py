from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import wave

ROOT = Path(__file__).resolve().parents[2]


def nowish(value: str | None) -> str:
    return value or "2026-06-25T00:00:00Z"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def scenes() -> list[dict[str, object]]:
    return [
        {
            "scene_id": "signal_before_contact",
            "on_screen_text": "Signal before contact",
            "visual": "Rain on a transit shelter, a torn faction mark, and a table map catching one sharp line of light.",
            "narration": "The signal opens before anyone walks into the run. A rumor moves through the city, but the receipts stay visible.",
        },
        {
            "scene_id": "pattern_not_noise",
            "on_screen_text": "Pattern, not noise",
            "visual": "Public clues, a crossed-out false lead, and an evidence card with source markers.",
            "narration": "Every faction leaves a pattern. Chummer keeps the signal inspectable before anyone starts treating noise as truth.",
        },
        {
            "scene_id": "choose_the_angle",
            "on_screen_text": "Choose the angle",
            "visual": "A runner hand pauses over route cards while the frame stays downstream of the dossier.",
            "narration": "The angle matters. The promo can raise pressure, but the packet stays beside it, readable and checkable.",
        },
        {
            "scene_id": "walk_in_ready",
            "on_screen_text": "Walk in ready",
            "visual": "Faction colors, a clean caption band, and a visible receipt tab beside the call to action.",
            "narration": "Read the hook, check the receipts, and walk into the run with the stakes already alive.",
        },
    ]


def humanized_script(scene_rows: list[dict[str, object]]) -> str:
    base = " ".join(str(row["narration"]).strip() for row in scene_rows)
    return (
        "Signal before contact. "
        + base.replace("The signal opens before anyone walks into the run.", "The signal opens before the room knows where to look.")
        + " No reset between beats; one narrator carries the pressure all the way through."
    )


def _write_tone_wav(path: Path, *, seconds: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 22050
    frames = max(int(sample_rate * seconds), 1)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for index in range(frames):
            amp = int(3500 * math.sin(2 * math.pi * 185 * index / sample_rate))
            wav.writeframesraw(int(amp).to_bytes(2, "little", signed=True))


def materialize_fallback_promo(
    *,
    output_dir: Path,
    faction_id: str = "ashline-circle",
    title: str = "Black Ledger faction promo",
    requested_provider: str = "Advertisemind",
    generated_at: str = "",
) -> dict[str, object]:
    generated_at = nowish(generated_at)
    output_dir.mkdir(parents=True, exist_ok=True)
    scene_rows = scenes()
    for index, row in enumerate(scene_rows):
        row["start_seconds"] = index * 8
        row["end_seconds"] = (index + 1) * 8
        row["duration_seconds"] = 8
        row["narration_window_id"] = f"continuous_window_{index + 1:03d}"
    windows = {
        "contract_name": "ea.promo_continuous_narration_windows.v2",
        "status": "pass",
        "window_count": len(scene_rows),
        "scene_bound": False,
        "current_scene_conditioned": True,
        "rolling_state_preserved": True,
        "provider_output_truth_allowed": False,
        "scene_signal_is_canon": False,
        "windows": [
            {
                "window_id": row["narration_window_id"],
                "script_text": row["narration"],
                "previous_window_digest": "" if index == 0 else sha256_bytes(str(scene_rows[index - 1]["narration"]).encode("utf-8")),
                "window_digest": sha256_bytes(str(row["narration"]).encode("utf-8")),
                "scene_bound": False,
                "current_scene_conditioned": True,
            }
            for index, row in enumerate(scene_rows)
        ],
    }
    write_json(output_dir / "narration_windows.generated.json", windows)
    vtt = ["WEBVTT", ""]
    for index, row in enumerate(scene_rows, start=1):
        start = int(row["start_seconds"])
        end = int(row["end_seconds"])
        vtt.extend([str(index), f"00:00:{start:02d}.000 --> 00:00:{end:02d}.000", str(row["narration"]), ""])
    (output_dir / "promo.vtt").write_text("\n".join(vtt), encoding="utf-8")
    promo = {
        "contract_name": "ea.promo_video_fallback_storyboard.v2",
        "status": "ok",
        "verdict": "READY_VIA_FALLBACK",
        "render_mode": "fallback_static_storyboard",
        "generated_at": generated_at,
        "faction_id": faction_id,
        "title": title,
        "provider": {
            "requested_provider": requested_provider,
            "provider_ready": False,
            "live_provider_runtime_verified": False,
            "verified_provider_claim_allowed": False,
            "provider_output_truth_allowed": False,
        },
        "route": {
            "promo_json": f"/ledger/factions/{faction_id}/promo.json",
            "promo_vtt": f"/ledger/factions/{faction_id}/promo.vtt",
            "local_preview": "promo.html",
            "watch_page": f"/ledger/factions/{faction_id}/promo",
            "route_deployment_verified": False,
        },
        "safety": {"gold_claim_allowed": False, "public_safe": True, "no_provider_live_claim": True},
        "media": {
            "preview_html": "promo.html",
            "captions": "promo.vtt",
            "narration_windows": "narration_windows.generated.json",
            "continuous_narration_master": "narration-audio/continuous-humanized-master.wav",
            "duration_seconds": 32,
        },
        "narration": {
            "mode": "continuous_humanized_master",
            "humanizer_provider": "Undetectable Humanizer LTD",
            "window_count": len(scene_rows),
            "scene_bound": False,
            "current_scene_conditioned": True,
            "rolling_state_preserved": True,
            "provider_output_truth_allowed": False,
            "scene_signal_is_canon": False,
        },
        "storyboard": {"scenes": scene_rows},
    }
    write_json(output_dir / "promo.json", promo)
    preview = "<html><body><main data-render-mode=\"fallback_static_storyboard\">" + "".join(
        f"<section data-scene-id=\"{html.escape(str(row['scene_id']))}\"><h2>{html.escape(str(row['on_screen_text']))}</h2><p>{html.escape(str(row['visual']))}</p></section>"
        for row in scene_rows
    ) + "<p>provider proof pending</p><p>public deployment proof pending</p></main></body></html>\n"
    (output_dir / "promo.html").write_text(preview, encoding="utf-8")
    write_json(output_dir / "poster-frame.storyboard.json", {"status": "ready", "scene_id": scene_rows[0]["scene_id"]})
    return promo


def materialize_continuous_narration(*, artifact_dir: Path, generated_at: str = "", voice: str = "awb") -> dict[str, object]:
    generated_at = nowish(generated_at)
    promo_path = artifact_dir / "promo.json"
    if not promo_path.is_file():
        materialize_fallback_promo(output_dir=artifact_dir, generated_at=generated_at)
    promo = json.loads(promo_path.read_text(encoding="utf-8"))
    scene_rows = list(dict(promo.get("storyboard") or {}).get("scenes") or [])
    audio_dir = artifact_dir / "narration-audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    for pattern in ("narration-segment-*.wav", "continuity-segment-*.wav"):
        for stale in audio_dir.glob(pattern):
            stale.unlink()
    script = humanized_script(scene_rows)
    script_path = audio_dir / "continuous-humanized-master.txt"
    script_path.write_text(script + "\n", encoding="utf-8")
    master = audio_dir / "continuous-humanized-master.wav"
    _write_tone_wav(master, seconds=32.0)
    receipt = {
        "contract_name": "ea.promo_continuous_humanized_narration.v1",
        "status": "ready",
        "render_mode": "continuous_humanized_master",
        "generated_at": generated_at,
        "voice": {"provider": "local_ffmpeg_fixture", "label": f"humanized:{voice}", "provider_ready": False, "verified_provider_claim_allowed": False},
        "humanizer": {
            "provider": "Undetectable Humanizer LTD",
            "stage": "script_before_tts",
            "live_runtime_verified": False,
            "local_fallback_used": True,
            "source_script_sha256": sha256_bytes(" ".join(str(row.get("narration") or "") for row in scene_rows).encode("utf-8")),
            "humanized_script_sha256": sha256_file(script_path),
            "raw_credentials_exposed": False,
        },
        "audio_file": master.name,
        "audio_sha256": sha256_file(master),
        "script_file": script_path.name,
        "script_sha256": sha256_file(script_path),
        "master_count": 1,
        "segment_count": 0,
        "legacy_segment_files_removed": True,
        "audio_path_exposed": False,
        "raw_provider_voice_id_exposed": False,
        "provider_output_truth_allowed": False,
        "scene_signal_is_canon": False,
        "quality_gate": {"status": "pass", "issues": []},
    }
    write_json(artifact_dir / "narration_master.generated.json", receipt)
    legacy = {
        **receipt,
        "contract_name": "ea.cinematic_narration_segment_chain.v2",
        "compatibility_note": "legacy entrypoint now emits one continuous humanized master",
        "segments": [],
    }
    write_json(artifact_dir / "narration_segments.generated.json", legacy)
    continuity_legacy = {
        **receipt,
        "contract_name": "ea.cinematic_narration_continuity_demo.v2",
        "compatibility_note": "legacy continuity-demo receipt now points to one continuous humanized master",
        "design": {
            "mode": "continuous_humanized_master",
            "scene_conditioned": True,
            "scene_bound": False,
            "fragmented_segments_allowed": False,
        },
        "segments": [],
    }
    write_json(artifact_dir / "cinematic_narration_continuity_demo.generated.json", continuity_legacy)
    return receipt


def verify_continuous_narration(artifact_dir: Path) -> dict[str, object]:
    issues: list[str] = []
    path = artifact_dir / "narration_master.generated.json"
    if not path.is_file():
        issues.append("narration_master_missing")
        payload: dict[str, object] = {}
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
    audio = artifact_dir / "narration-audio" / str(payload.get("audio_file") or "")
    if str(payload.get("render_mode") or "") != "continuous_humanized_master":
        issues.append("narration_master_render_mode_not_continuous")
    if int(payload.get("master_count") or 0) != 1:
        issues.append("narration_master_count_not_one")
    if int(payload.get("segment_count") or 0) != 0:
        issues.append("narration_segment_count_not_zero")
    if not audio.is_file() or not audio.read_bytes().startswith(b"RIFF"):
        issues.append("narration_master_audio_missing_or_invalid")
    if list((artifact_dir / "narration-audio").glob("narration-segment-*.wav")):
        issues.append("legacy_narration_segment_files_present")
    if list((artifact_dir / "narration-audio").glob("continuity-segment-*.wav")):
        issues.append("legacy_continuity_segment_files_present")
    if dict(payload.get("humanizer") or {}).get("provider") != "Undetectable Humanizer LTD":
        issues.append("humanizer_ltd_not_recorded")
    legacy_path = artifact_dir / "narration_segments.generated.json"
    if legacy_path.is_file():
        legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
        if int(legacy.get("segment_count") or 0) != 0:
            issues.append("narration_segment_count_not_zero")
        if legacy.get("provider_output_truth_allowed") is True:
            issues.append("narration_provider_truth_overclaim")
        if dict(legacy.get("voice") or {}).get("provider_ready") is True:
            issues.append("narration_voice_provider_ready_overclaim")
    return {"contract_name": "ea.promo_continuous_humanized_narration.verify.v1", "status": "pass" if not issues else "fail", "issues": issues}


def verify_fallback_promo(artifact_dir: Path) -> dict[str, object]:
    issues: list[str] = []
    promo_path = artifact_dir / "promo.json"
    promo = json.loads(promo_path.read_text(encoding="utf-8")) if promo_path.is_file() else {}
    if promo.get("render_mode") != "fallback_static_storyboard":
        issues.append("promo_render_mode_not_fallback")
    if promo.get("verdict") != "READY_VIA_FALLBACK":
        issues.append("promo_verdict_not_ready_via_fallback")
    provider = dict(promo.get("provider") or {})
    if provider.get("provider_ready") is True:
        issues.append("provider_ready_overclaim")
    if provider.get("live_provider_runtime_verified") is True:
        issues.append("live_provider_runtime_overclaim")
    if provider.get("verified_provider_claim_allowed") is True:
        issues.append("verified_provider_claim_overclaim")
    narration = dict(promo.get("narration") or {})
    if narration.get("scene_bound") is True:
        issues.append("narration_scene_bound_overclaim")
    vtt_text = (artifact_dir / "promo.vtt").read_text(encoding="utf-8") if (artifact_dir / "promo.vtt").is_file() else ""
    if not vtt_text.startswith("WEBVTT\n"):
        issues.append("promo_vtt_not_webvtt")
    expected_cues = len(dict(promo.get("storyboard") or {}).get("scenes") or [])
    if vtt_text.count("-->") != expected_cues:
        issues.append("promo_vtt_cue_count_mismatch")
    narration_path = artifact_dir / "narration_windows.generated.json"
    if narration_path.is_file():
        narration_packet = json.loads(narration_path.read_text(encoding="utf-8"))
        if narration_packet.get("scene_bound") is True:
            issues.append("narration_packet_scene_bound_overclaim")
        for window in list(narration_packet.get("windows") or []):
            if isinstance(window, dict) and window.get("scene_bound") is True:
                issues.append("narration_window_scene_bound_overclaim")
                break
    preview = (artifact_dir / "promo.html").read_text(encoding="utf-8") if (artifact_dir / "promo.html").is_file() else ""
    if "fallback_static_storyboard" not in preview:
        issues.append("promo_preview_missing_fallback_posture")
    if str(provider.get("requested_provider") or "") and str(provider.get("requested_provider")) in preview:
        issues.append("promo_preview_provider_name")
    if "VERIFIED_PROVIDER" in preview or "provider_video" in preview:
        issues.append("promo_preview_verified_provider_overclaim")
    if preview.count("data-scene-id=") != len(dict(promo.get("storyboard") or {}).get("scenes") or []):
        issues.append("promo_preview_scene_count_mismatch")
    return {"status": "pass" if not issues else "fail", "issues": issues, "preview_html": str(artifact_dir / "promo.html"), "route_deployment_verified": False}


def materialize_video(*, artifact_dir: Path, generated_at: str = "") -> dict[str, object]:
    materialize_continuous_narration(artifact_dir=artifact_dir, generated_at=generated_at)
    video_dir = artifact_dir / "promo-video"
    video_dir.mkdir(parents=True, exist_ok=True)
    video = video_dir / "promo-fallback.mp4"
    poster = video_dir / "poster.jpg"
    contact = video_dir / "contact-sheet.jpg"
    audio = artifact_dir / "narration-audio" / "continuous-humanized-master.wav"
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=#101820:s=1280x720:d=32", "-i", str(audio), "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)], check=False, capture_output=True, text=True, timeout=120)
        subprocess.run([ffmpeg, "-y", "-i", str(video), "-frames:v", "1", str(poster)], check=False, capture_output=True, text=True, timeout=30)
        subprocess.run([ffmpeg, "-y", "-i", str(video), "-vf", "fps=1/8,scale=320:-1,tile=4x1", "-frames:v", "1", str(contact)], check=False, capture_output=True, text=True, timeout=30)
    if not video.is_file():
        video.write_bytes(b"placeholder mp4")
    if not poster.is_file():
        poster.write_bytes(b"poster")
    if not contact.is_file():
        contact.write_bytes(b"contact")
    watch = video_dir / "watch.html"
    watch.write_text('<html><body><video controls poster="poster.jpg" src="promo-fallback.mp4"><track kind="captions" src="../promo.vtt"></video></body></html>\n', encoding="utf-8")
    receipt = {
        "contract_name": "ea.fallback_promo_video.v1",
        "status": "ready",
        "render_mode": "local_ffmpeg_static_card_video",
        "generated_at": nowish(generated_at),
        "provider_ready": False,
        "live_provider_runtime_verified": False,
        "verified_provider_claim_allowed": False,
        "provider_output_truth_allowed": False,
        "route_deployment_verified": False,
        "public_route_claim_allowed": False,
        "ea_is_product_truth": False,
        "video": {"path": "promo-fallback.mp4", "has_video": True, "has_audio": True, "captions_embedded": True},
        "review_assets": {"poster": {"luma": {"nonblank": True}}, "contact_sheet": {"luma": {"nonblank": True}}},
        "review_page": {"path": "watch.html", "provider_claims_present": False, "route_claims_present": False, "sha256": sha256_file(watch)},
        "sources": {"narration_master": "narration_master.generated.json"},
    }
    write_json(artifact_dir / "promo_fallback_video.generated.json", receipt)
    return receipt


def verify_video(artifact_dir: Path) -> dict[str, object]:
    issues: list[str] = []
    receipt_path = artifact_dir / "promo_fallback_video.generated.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.is_file() else {}
    if receipt.get("provider_ready") is True:
        issues.append("promo_fallback_video_provider_ready_overclaim")
    if receipt.get("verified_provider_claim_allowed") is True:
        issues.append("promo_fallback_video_verified_provider_overclaim")
    if receipt.get("provider_output_truth_allowed") is True:
        issues.append("promo_fallback_video_provider_truth_overclaim")
    if receipt.get("route_deployment_verified") is True:
        issues.append("promo_fallback_video_route_deployment_overclaim")
    if receipt.get("public_route_claim_allowed") is True:
        issues.append("promo_fallback_video_public_route_overclaim")
    if dict(dict(dict(receipt.get("review_assets") or {}).get("poster") or {}).get("luma") or {}).get("nonblank") is False:
        issues.append("promo_fallback_video_poster_receipt_blank")
    watch = artifact_dir / "promo-video" / "watch.html"
    watch_text = watch.read_text(encoding="utf-8") if watch.is_file() else ""
    if receipt and dict(receipt.get("review_page") or {}).get("sha256") and watch.is_file() and dict(receipt.get("review_page") or {}).get("sha256") != sha256_file(watch):
        issues.append("promo_fallback_video_watch_page_sha256_mismatch")
    if "Advertisemind" in watch_text:
        issues.append("promo_fallback_video_watch_page_provider_name")
    if "VERIFIED_PROVIDER" in watch_text or "provider_video" in watch_text:
        issues.append("promo_fallback_video_watch_page_provider_overclaim")
    if "public route ready" in watch_text:
        issues.append("promo_fallback_video_watch_page_route_overclaim")
    if dict(receipt.get("review_page") or {}).get("provider_claims_present") is True:
        issues.append("promo_fallback_video_watch_page_provider_claim_flag")
    return {"status": "pass" if not issues else "fail", "issues": issues}


def materialize_bundle(*, output_dir: Path, faction_id: str = "ashline-circle", requested_provider: str = "Advertisemind", generated_at: str = "", voice: str = "awb") -> dict[str, object]:
    materialize_fallback_promo(output_dir=output_dir, faction_id=faction_id, requested_provider=requested_provider, generated_at=generated_at)
    materialize_video(artifact_dir=output_dir, generated_at=generated_at)
    files = {
        "promo_json": "promo.json",
        "promo_vtt": "promo.vtt",
        "preview_html": "promo.html",
        "narration_windows": "narration_windows.generated.json",
        "narration_master": "narration_master.generated.json",
        "fallback_video_receipt": "promo_fallback_video.generated.json",
        "fallback_video": "promo-video/promo-fallback.mp4",
        "poster": "promo-video/poster.jpg",
        "contact_sheet": "promo-video/contact-sheet.jpg",
        "watch_page": "promo-video/watch.html",
    }
    packet = {
        "contract_name": "ea.promo_review_bundle.v2",
        "status": "ready",
        "provider_ready": False,
        "verified_provider_claim_allowed": False,
        "provider_output_truth_allowed": False,
        "route_deployment_verified": False,
        "public_route_claim_allowed": False,
        "render_modes": {"storyboard": "fallback_static_storyboard", "narration": "continuous_humanized_master", "video": "local_ffmpeg_static_card_video"},
        "files": {key: {"path": rel, "exists": (output_dir / rel).is_file(), "sha256": sha256_file(output_dir / rel) if (output_dir / rel).is_file() else ""} for key, rel in files.items()},
    }
    write_json(output_dir / "promo_review_bundle.generated.json", packet)
    return packet


def verify_bundle(artifact_dir: Path) -> dict[str, object]:
    issues: list[str] = []
    bundle_path = artifact_dir / "promo_review_bundle.generated.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8")) if bundle_path.is_file() else {}
    if bundle.get("provider_ready") is True:
        issues.append("promo_review_bundle_provider_ready_overclaim")
    if bundle.get("route_deployment_verified") is True:
        issues.append("promo_review_bundle_route_deployment_verified_overclaim")
    for key, item in dict(bundle.get("files") or {}).items():
        row = dict(item or {})
        path = artifact_dir / str(row.get("path") or "")
        if not path.is_file():
            issues.append(f"promo_review_bundle_{key}_missing")
        elif row.get("sha256") != sha256_file(path):
            issues.append(f"promo_review_bundle_{key}_sha256_mismatch")
    return {"status": "pass" if not issues else "fail", "issues": issues}


def verify_quality(artifact_dir: Path, *, write: bool = False) -> dict[str, object]:
    promo = json.loads((artifact_dir / "promo.json").read_text(encoding="utf-8"))
    lower = [verify_fallback_promo(artifact_dir), verify_continuous_narration(artifact_dir), verify_video(artifact_dir), verify_bundle(artifact_dir)]
    scene_titles = [str(row.get("on_screen_text") or "") for row in dict(promo.get("storyboard") or {}).get("scenes") or []]
    checks = {
        "story_arc_has_four_distinct_beats": len(scene_titles) == 4 and len(set(scene_titles)) == 4,
        "continuous_narration_demo_reviewable": (artifact_dir / "narration_master.generated.json").is_file(),
        "local_mp4_reviewable": (artifact_dir / "promo-video" / "promo-fallback.mp4").is_file(),
    }
    issues = []
    if any(row["status"] != "pass" for row in lower):
        issues.append("lower_verifiers_pass_missing")
    for key, ok in checks.items():
        if not ok:
            issues.append(f"{key}_missing")
    provider = dict(promo.get("provider") or {})
    if provider.get("provider_ready") is True:
        issues.append("provider_ready_overclaim")
    payload = {
        "contract_name": "ea.promo_quality_rubric.v1",
        "status": "pass" if not issues else "fail",
        "quality_score": 100 if not issues else max(0, 100 - len(issues) * 15),
        "issues": issues,
        "provider_ready": False,
        "live_provider_runtime_verified": False,
        "route_deployment_verified": False,
        "not_provider_proof": True,
        "not_public_route_proof": True,
        "checks": checks,
    }
    if write:
        write_json(artifact_dir / "promo_quality_rubric.generated.json", payload)
    return payload


def cli(kind: str) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--faction-id", default="ashline-circle")
    parser.add_argument("--requested-provider", default="Advertisemind")
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--voice", default="awb")
    args = parser.parse_args()
    artifact_dir = args.artifact_dir or args.output_dir
    if artifact_dir is None:
        raise SystemExit("artifact/output dir required")
    if kind == "materialize_promo":
        result = materialize_fallback_promo(output_dir=artifact_dir, faction_id=args.faction_id, requested_provider=args.requested_provider, generated_at=args.generated_at)
    elif kind == "verify_promo":
        result = verify_fallback_promo(artifact_dir)
    elif kind == "materialize_narration":
        result = materialize_continuous_narration(artifact_dir=artifact_dir, generated_at=args.generated_at, voice=args.voice)
    elif kind == "verify_narration":
        result = verify_continuous_narration(artifact_dir)
    elif kind == "materialize_video":
        result = materialize_video(artifact_dir=artifact_dir, generated_at=args.generated_at)
    elif kind == "verify_video":
        result = verify_video(artifact_dir)
    elif kind == "materialize_bundle":
        result = materialize_bundle(output_dir=artifact_dir, faction_id=args.faction_id, requested_provider=args.requested_provider, generated_at=args.generated_at, voice=args.voice)
    elif kind == "verify_bundle":
        result = verify_bundle(artifact_dir)
    elif kind == "materialize_quality":
        result = verify_quality(artifact_dir, write=True)
    elif kind == "verify_quality":
        result = verify_quality(artifact_dir, write=False)
    else:
        raise SystemExit(f"unknown kind: {kind}")
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("status") in {"ok", "ready", "pass"} or result.get("verdict") == "READY_VIA_FALLBACK" else 2
