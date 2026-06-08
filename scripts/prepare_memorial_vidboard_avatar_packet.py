#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE_ROOT = ROOT / "memorial_data" / "public_memorials"
DEFAULT_PACKET_ROOT = Path("/docker/fleet/state/chummer6/avatar_presenter_provider")
_STOPWORDS = {
    "aber",
    "alle",
    "also",
    "dann",
    "darf",
    "dass",
    "diese",
    "echte",
    "einen",
    "einer",
    "eines",
    "fuer",
    "gegen",
    "gibt",
    "halt",
    "hier",
    "heute",
    "kein",
    "keine",
    "mehr",
    "muss",
    "nicht",
    "noch",
    "oder",
    "schon",
    "seite",
    "sich",
    "soll",
    "sollt",
    "sollte",
    "sollten",
    "ueber",
    "vater",
    "vorsichtig",
    "worte",
}


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid_json_object:{path}")
    return dict(payload)


def _safe_name(label: str) -> str:
    lowered = "".join(ch.lower() if ch.isalnum() else "-" for ch in label.strip())
    compact = "-".join(part for part in lowered.split("-") if part)
    return compact or "asset"


def _bundle_paths(slug: str, bundle_root: Path) -> tuple[Path, dict[str, object]]:
    bundle_dir = bundle_root / slug
    memorial_path = bundle_dir / "memorial.json"
    if not memorial_path.is_file():
        raise SystemExit(f"memorial_bundle_missing:{memorial_path}")
    payload = _load_json(memorial_path)
    if str(payload.get("slug") or "").strip() != slug:
        raise SystemExit("memorial_slug_mismatch")
    return bundle_dir, payload


def _first_audio_clip(memorial: dict[str, object]) -> dict[str, object]:
    clips = memorial.get("audio_clips")
    if not isinstance(clips, list):
        raise SystemExit("memorial_audio_clips_missing")
    for item in clips:
        if isinstance(item, dict) and str(item.get("asset_relpath") or "").strip():
            return dict(item)
    raise SystemExit("memorial_audio_clip_missing")


def _portrait_source(bundle_dir: Path, memorial: dict[str, object]) -> Path:
    icons = memorial.get("pwa_icon")
    if not isinstance(icons, dict):
        branding = memorial.get("branding")
        if isinstance(branding, dict):
            icons = branding.get("icons")
    if not isinstance(icons, dict):
        raise SystemExit("memorial_portrait_icon_missing")
    rel = ""
    for key in ("src_512", "src_192", "src_180"):
        candidate = str(icons.get(key) or "").strip()
        if candidate:
            rel = candidate
            break
    if not rel:
        raise SystemExit("memorial_portrait_icon_missing")
    source = bundle_dir / rel
    if not source.is_file():
        raise SystemExit(f"memorial_portrait_icon_not_found:{source}")
    return source


def _audio_source(bundle_dir: Path, clip: dict[str, object]) -> Path:
    rel = str(clip.get("asset_relpath") or "").strip()
    if not rel:
        raise SystemExit("memorial_audio_asset_relpath_missing")
    source = bundle_dir / rel
    if not source.is_file():
        raise SystemExit(f"memorial_audio_asset_not_found:{source}")
    return source


def _extract_audio_segment(source: Path, target: Path, *, start_seconds: float, duration_seconds: float) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-ss",
            str(start_seconds),
            "-t",
            str(duration_seconds),
            "-ar",
            "44100",
            "-ac",
            "1",
            str(target),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not target.is_file():
        raise SystemExit("audio_segment_extract_failed")
    return target


def _normalized_tokens(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-zA-Z0-9äöüÄÖÜß]+", (text or "").lower()) if len(token) >= 4]


def _keyword_hints(memorial: dict[str, object]) -> list[str]:
    memory_cards = memorial.get("memory_cards")
    tokens: list[str] = []
    if isinstance(memory_cards, list):
        for item in memory_cards[:8]:
            if not isinstance(item, dict):
                continue
            for field in ("title", "body"):
                tokens.extend(_normalized_tokens(str(item.get(field) or "")))
    preferred = []
    for token in tokens:
        if token in _STOPWORDS:
            continue
        if token not in preferred:
            preferred.append(token)
    return preferred[:24]


def _transcribe_audio(base_url: str, slug: str, audio_path: Path) -> dict[str, object]:
    if not base_url.strip():
        return {}
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/memorials/{slug}/speech-transcribe",
        data=audio_path.read_bytes(),
        headers={"Content-Type": "audio/wav"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        return {"status": "failed", "detail": detail[:400]}
    except Exception as exc:
        return {"status": "failed", "detail": str(exc)[:400]}
    if not isinstance(payload, dict):
        return {"status": "failed", "detail": "invalid_transcription_payload"}
    result = dict(payload)
    result["status"] = "ok"
    return result


def _candidate_starts(start_seconds: float) -> list[float]:
    if start_seconds > 0:
        return [start_seconds]
    return [0.0, 120.0, 300.0, 600.0, 900.0, 1200.0, 1800.0]


def _score_transcript(text: str, keywords: list[str]) -> int:
    normalized = _normalized_tokens(text)
    tokens = set(normalized)
    if not tokens:
        return -1
    keyword_hits = sum(1 for keyword in keywords if keyword in tokens)
    preferred_hits = sum(1 for preferred in ("familie", "schach", "krankenhaus", "behandlung", "mobbing", "diskriminierung") if preferred in tokens)
    score = keyword_hits * 10 + preferred_hits * 8 + min(len(text.strip()), 160) // 40
    for keyword in keywords:
        if keyword in {"familie", "schach", "krankenhaus", "behandlung"} and keyword in tokens:
            score += 4
    repeated_penalties = ("also", "halt", "naja", "quasi", "eigentlich")
    for filler in repeated_penalties:
        filler_count = normalized.count(filler)
        if filler_count >= 2:
            score -= filler_count * 2
    if "kartoffeln" in tokens or "waschen" in tokens or "bett" in tokens:
        score -= 10
    if keyword_hits == 0 and preferred_hits == 0:
        score -= 6
    return score


def _curate_segment(
    *,
    audio_source: Path,
    packet_dir: Path,
    slug: str,
    base_url: str,
    duration_seconds: float,
    start_seconds: float,
    memorial: dict[str, object],
) -> tuple[Path, dict[str, object], str, list[dict[str, object]], dict[str, object]]:
    keywords = _keyword_hints(memorial)
    candidates: list[dict[str, object]] = []
    selected_path: Path | None = None
    selected_transcript: dict[str, object] = {}
    selected_text = ""
    best_score = -10**9
    for index, candidate_start in enumerate(_candidate_starts(start_seconds)):
        candidate_path = packet_dir / f"{_safe_name(slug)}-public-audio-segment-{index:02d}.wav"
        _extract_audio_segment(
            audio_source,
            candidate_path,
            start_seconds=candidate_start,
            duration_seconds=duration_seconds,
        )
        transcript = _transcribe_audio(base_url, slug, candidate_path)
        transcript_text = str(transcript.get("transcript_text") or "").strip()
        score = _score_transcript(transcript_text, keywords)
        candidate_payload = {
            "path": candidate_path.as_posix(),
            "sha256": _sha256_file(candidate_path),
            "start_seconds": round(candidate_start, 3),
            "duration_seconds": round(duration_seconds, 3),
            "transcript_text": transcript_text,
            "transcription": transcript,
            "score": score,
        }
        candidates.append(candidate_payload)
        if score > best_score:
            best_score = score
            selected_path = candidate_path
            selected_transcript = transcript
            selected_text = transcript_text
    if selected_path is None:
        raise SystemExit("audio_segment_selection_failed")
    canonical = packet_dir / f"{_safe_name(slug)}-public-audio-segment.wav"
    canonical.write_bytes(selected_path.read_bytes())
    selected_candidate = next(
        (item for item in candidates if str(item.get("path") or "").strip() == selected_path.as_posix()),
        {},
    )
    return canonical, selected_transcript, selected_text, candidates, selected_candidate


def _write_markdown(path: Path, *, payload: dict[str, object]) -> None:
    lines = [
        f"# {payload['title']}",
        "",
        "## Purpose",
        "",
        "Prepare a real VidBoard talking-photo render from the public memorial bundle without inventing new Manfred copy.",
        "",
        "## Assets",
        "",
        f"- Portrait: `{payload['portrait']['path']}`",
        f"- Audio segment: `{payload['audio_segment']['path']}`",
        f"- Source clip: `{payload['source_audio']['path']}`",
        "",
        "## Provider instruction",
        "",
        payload["provider_instruction"],
        "",
        "## Transcript",
        "",
        payload["transcript_text"] or "_No transcript captured yet._",
        "",
        "## Selected segment",
        "",
        f"- Start: `{payload['audio_segment']['start_seconds']}s`",
        f"- Duration: `{payload['audio_segment']['duration_seconds']}s`",
        f"- Score: `{payload['audio_segment'].get('score', '')}`",
        f"- Review status: `{payload['audio_segment'].get('selection_status', '')}`",
        "",
        "## Public-safety note",
        "",
        payload["safety_note"],
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize a VidBoard avatar render packet from a public memorial bundle.")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--bundle-root", default=str(DEFAULT_BUNDLE_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_PACKET_ROOT))
    parser.add_argument("--start-seconds", type=float, default=0.0)
    parser.add_argument("--duration-seconds", type=float, default=14.0)
    parser.add_argument("--base-url", default="")
    args = parser.parse_args()

    slug = str(args.slug).strip()
    if not slug:
        raise SystemExit("slug_missing")
    duration_seconds = float(args.duration_seconds)
    if duration_seconds <= 0:
        raise SystemExit("duration_seconds_invalid")
    start_seconds = max(0.0, float(args.start_seconds))

    bundle_dir, memorial = _bundle_paths(slug, Path(args.bundle_root))
    clip = _first_audio_clip(memorial)
    portrait_source = _portrait_source(bundle_dir, memorial)
    audio_source = _audio_source(bundle_dir, clip)
    person_name = str(memorial.get("person_name") or slug).strip() or slug

    packet_dir = Path(args.output_root) / f"{slug}_vidboard_avatar_packet"
    packet_dir.mkdir(parents=True, exist_ok=True)
    portrait_target = packet_dir / f"{_safe_name(slug)}-portrait{portrait_source.suffix.lower()}"
    portrait_target.write_bytes(portrait_source.read_bytes())
    audio_target, transcript, transcript_text, candidates, selected_candidate = _curate_segment(
        audio_source=audio_source,
        packet_dir=packet_dir,
        slug=slug,
        base_url=str(args.base_url),
        duration_seconds=duration_seconds,
        start_seconds=start_seconds,
        memorial=memorial,
    )
    selection_status = "auto_candidate_ready" if int(selected_candidate.get("score") or -1) > 0 else "manual_review_required"

    payload = {
        "generated_at": _utc_now(),
        "contract_name": "executive_assistant.memorial_vidboard_avatar_packet.v1",
        "slug": slug,
        "title": f"{person_name} VidBoard Avatar Packet",
        "person_name": person_name,
        "provider": "VidBoard",
        "provider_key": "vidboard",
        "source_audio": {
            "title": str(clip.get("title") or ""),
            "description": str(clip.get("description") or ""),
            "path": audio_source.as_posix(),
            "sha256": _sha256_file(audio_source),
        },
        "portrait": {
            "path": portrait_target.as_posix(),
            "sha256": _sha256_file(portrait_target),
        },
        "audio_segment": {
            "path": audio_target.as_posix(),
            "sha256": _sha256_file(audio_target),
            "start_seconds": round(float(selected_candidate.get("start_seconds") or start_seconds), 3),
            "duration_seconds": round(duration_seconds, 3),
            "score": int(selected_candidate.get("score") or 0),
            "selection_status": selection_status,
        },
        "transcription": transcript,
        "transcript_text": transcript_text,
        "candidate_segments": candidates,
        "selection_keywords": _keyword_hints(memorial),
        "provider_instruction": (
            "Render a talking-photo clip from the supplied portrait plus the supplied original archive audio segment. "
            "Do not rewrite, paraphrase, or synthesize new Manfred copy. Keep the output to the supplied audio only."
        ),
        "safety_note": (
            "This packet is based on a public memorial portrait and a public original archive recording. "
            "The intended render is an animated presentation of existing source audio, not a newly scripted impersonation."
        ),
        "publish_next_step": (
            "After exporting a real VidBoard clip, run "
            "`python3 scripts/publish_memorial_video_call_avatar.py --slug "
            f"{slug} --provider vidboard --asset /path/to/export.mp4`."
        ),
    }
    payload_path = packet_dir / "packet.generated.json"
    payload_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_markdown(packet_dir / "README.md", payload=payload)
    print(payload_path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
