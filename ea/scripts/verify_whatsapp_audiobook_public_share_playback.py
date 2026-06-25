from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Callable
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
EA_ROOT = ROOT / "ea"
DEFAULT_OUTPUT = ROOT / ".codex-studio" / "published" / "whatsapp_audiobook_public_share_playback.generated.json"
CONTRACT_NAME = "ea.whatsapp_audiobook_public_share_playback_e2e.v1"

if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_text(value: object) -> str:
    text = str(value or "").strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""


def _as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _load_job(path: Path) -> dict[str, object]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _write_job(path: Path, job: dict[str, object]) -> None:
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(job, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _public_share(job: dict[str, object]) -> dict[str, object]:
    return _as_dict(_as_dict(job.get("audiobookshelf_import")).get("public_share"))


def _whatsapp_delivery_sent(job: dict[str, object]) -> bool:
    whatsapp = _as_dict(job.get("whatsapp"))
    share = _public_share(job)
    delivery = _as_dict(share.get("whatsapp_delivery")) or _as_dict(whatsapp.get("public_share_delivery"))
    return str(delivery.get("status") or "").strip() == "sent"


def _is_whatsapp_share_candidate(job: dict[str, object]) -> bool:
    whatsapp = _as_dict(job.get("whatsapp"))
    share = _public_share(job)
    return (
        str(share.get("status") or "").strip() == "public_share_ready"
        and bool(str(share.get("absolute_url") or "").strip())
        and (
            bool(str(whatsapp.get("sender_ref") or "").strip())
            or bool(str(whatsapp.get("session_ref") or "").strip())
            or _whatsapp_delivery_sent(job)
        )
    )


def _job_created_sort_key(path: Path, job: dict[str, object]) -> float:
    created_at = str(job.get("created_at") or "").strip()
    if created_at:
        try:
            return datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return path.stat().st_mtime if path.exists() else 0.0


def _candidate_paths(*, limit: int, job_id: str = "") -> list[Path]:
    from app.services import audiobook_epub_pipeline

    root = audiobook_epub_pipeline.audiobook_jobs_root()
    if not root.is_dir():
        return []
    candidates: list[tuple[float, Path]] = []
    for path in root.glob("*/job.json"):
        job = _load_job(path)
        if not job:
            continue
        if job_id and str(job.get("job_id") or path.parent.name) != job_id:
            continue
        if _is_whatsapp_share_candidate(job):
            candidates.append((_job_created_sort_key(path, job), path))
    candidates.sort(key=lambda row: row[0], reverse=True)
    return [path for _, path in candidates[: max(1, int(limit or 1))]]


def _playback_pass(result: dict[str, object]) -> bool:
    status = str(result.get("status") or "").strip().lower()
    response_status = int(result.get("track_response_status") or 0)
    content_type = str(result.get("track_content_type") or "").strip().lower()
    duration = float(result.get("duration_seconds") or 0)
    current_time = float(result.get("current_time_after_play_seconds") or 0)
    media_error = bool(result.get("media_error"))
    return (
        status == "pass"
        and response_status in {200, 206}
        and content_type.startswith("audio/")
        and duration > 0
        and current_time > 0
        and not media_error
    )


def _content_type(value: object) -> str:
    return str(value or "").split(";", 1)[0].strip()


def _select_track_response(
    *,
    responses: list[dict[str, object]],
    media_src: object,
) -> dict[str, object]:
    media_src_text = str(media_src or "").strip()
    audio_responses = [
        row for row in responses if str(row.get("content_type") or "").strip().lower().startswith("audio/")
    ]
    if audio_responses:
        return audio_responses[-1]
    if media_src_text:
        media_src_responses = [row for row in responses if str(row.get("url") or "").strip() == media_src_text]
        if media_src_responses:
            return media_src_responses[-1]
    media_responses = [row for row in responses if str(row.get("resource_type") or "").strip() == "media"]
    return media_responses[-1] if media_responses else {}


def probe_share_with_playwright(*, url: str, wait_seconds: float = 3.0, timeout_seconds: float = 60.0) -> dict[str, object]:
    from playwright.sync_api import sync_playwright

    responses: list[dict[str, object]] = []
    page_response_status = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--autoplay-policy=no-user-gesture-required",
                "--mute-audio",
            ],
        )
        page = browser.new_page()
        page.on(
            "response",
            lambda response: responses.append(
                {
                    "url": response.url,
                    "status": response.status,
                    "content_type": response.headers.get("content-type", ""),
                    "resource_type": response.request.resource_type,
                }
            ),
        )
        try:
            main_response = page.goto(url, wait_until="networkidle", timeout=max(1000, int(timeout_seconds * 1000)))
            page_response_status = int(main_response.status) if main_response else 0
            media = page.evaluate(
                """async ({waitMs}) => {
                  const audio = document.querySelector('audio, video');
                  if (!audio) {
                    return {ok: false, reason: 'media_element_missing'};
                  }
                  audio.muted = true;
                  audio.volume = 0;
                  try {
                    await audio.play();
                  } catch (error) {
                    return {
                      ok: false,
                      reason: 'play_failed',
                      error: String(error),
                      duration: Number.isFinite(audio.duration) ? audio.duration : 0,
                      currentTime: audio.currentTime || 0,
                      paused: audio.paused,
                      readyState: audio.readyState,
                      src: audio.currentSrc || audio.src || '',
                      mediaError: audio.error ? {code: audio.error.code, message: audio.error.message} : null,
                    };
                  }
                  await new Promise((resolve) => setTimeout(resolve, waitMs));
                  return {
                    ok: true,
                    reason: '',
                    duration: Number.isFinite(audio.duration) ? audio.duration : 0,
                    currentTime: audio.currentTime || 0,
                    paused: audio.paused,
                    readyState: audio.readyState,
                    src: audio.currentSrc || audio.src || '',
                    mediaError: audio.error ? {code: audio.error.code, message: audio.error.message} : null,
                  };
                }""",
                {"waitMs": max(500, int(wait_seconds * 1000))},
            )
        finally:
            browser.close()

    media = media if isinstance(media, dict) else {}
    media_src = str(media.get("src") or "").strip()
    selected_response = _select_track_response(responses=responses, media_src=media_src)
    media_error = _as_dict(media.get("mediaError"))
    result = {
        "contract_name": CONTRACT_NAME,
        "checked_at": _now_iso(),
        "status": "pass" if bool(media.get("ok")) and float(media.get("currentTime") or 0) > 0 and not media_error else "failed",
        "browser": "chromium_playwright",
        "reason": str(media.get("reason") or "").strip(),
        "page_response_status": page_response_status,
        "track_response_status": int(selected_response.get("status") or 0),
        "track_content_type": _content_type(selected_response.get("content_type")),
        "track_response_resource_type": str(selected_response.get("resource_type") or "").strip(),
        "duration_seconds": float(media.get("duration") or 0),
        "current_time_after_play_seconds": float(media.get("currentTime") or 0),
        "paused_after_probe": bool(media.get("paused")),
        "ready_state": int(media.get("readyState") or 0),
        "media_error": bool(media_error),
        "media_error_code": int(media_error.get("code") or 0),
        "media_error_message_sha256": _sha256_text(media_error.get("message")),
        "track_url_sha256": _sha256_text(media_src),
        "track_response_url_sha256": _sha256_text(selected_response.get("url")),
        "raw_url_exposed": False,
    }
    if not result["reason"] and result["status"] != "pass":
        result["reason"] = "audio_playback_did_not_advance"
    return result


def record_playback_e2e(
    *,
    job_path: Path,
    probe: Callable[..., dict[str, object]] = probe_share_with_playwright,
    wait_seconds: float = 3.0,
    timeout_seconds: float = 60.0,
) -> dict[str, object]:
    job = _load_job(job_path)
    if not job:
        return {"status": "failed", "reason": "job_manifest_unreadable", "job_path_sha256": _sha256_text(job_path)}
    share = _public_share(job)
    url = str(share.get("absolute_url") or "").strip()
    if not url:
        return {
            "status": "skipped",
            "reason": "public_share_url_missing",
            "job_id_sha256": _sha256_text(job.get("job_id") or job_path.parent.name),
        }
    result = dict(probe(url=url, wait_seconds=wait_seconds, timeout_seconds=timeout_seconds))
    result.setdefault("contract_name", CONTRACT_NAME)
    result.setdefault("checked_at", _now_iso())
    result.setdefault("raw_url_exposed", False)

    import_result = _as_dict(job.get("audiobookshelf_import"))
    share = _as_dict(import_result.get("public_share"))
    share["playback_e2e"] = result
    import_result["public_share"] = share
    job["audiobookshelf_import"] = import_result
    job["updated_at"] = _now_iso()
    _write_job(job_path, job)

    try:
        from app.services import audiobook_epub_pipeline

        audiobook_epub_pipeline.build_audiobook_job_receipt(job_dir=job_path.parent)
    except Exception:
        pass

    parsed = urlparse(url)
    return {
        "status": str(result.get("status") or "").strip(),
        "passed": _playback_pass(result),
        "reason": str(result.get("reason") or "").strip(),
        "job_id_sha256": _sha256_text(job.get("job_id") or job_path.parent.name),
        "public_share_host": parsed.hostname or "",
        "public_share_url_sha256": _sha256_text(url),
        "page_response_status": int(result.get("page_response_status") or 0),
        "track_response_status": int(result.get("track_response_status") or 0),
        "track_content_type": str(result.get("track_content_type") or ""),
        "track_response_resource_type": str(result.get("track_response_resource_type") or ""),
        "duration_seconds": float(result.get("duration_seconds") or 0),
        "current_time_after_play_seconds": float(result.get("current_time_after_play_seconds") or 0),
        "media_error": bool(result.get("media_error")),
        "media_error_code": int(result.get("media_error_code") or 0),
        "raw_url_exposed": False,
    }


def run(
    *,
    output_path: Path = DEFAULT_OUTPUT,
    job_id: str = "",
    limit: int = 1,
    wait_seconds: float = 3.0,
    timeout_seconds: float = 60.0,
    probe: Callable[..., dict[str, object]] = probe_share_with_playwright,
) -> dict[str, object]:
    rows = []
    for job_path in _candidate_paths(limit=limit, job_id=job_id):
        rows.append(
            record_playback_e2e(
                job_path=job_path,
                probe=probe,
                wait_seconds=wait_seconds,
                timeout_seconds=timeout_seconds,
            )
        )
    passed = sum(1 for row in rows if bool(row.get("passed")))
    receipt = {
        "contract_name": CONTRACT_NAME,
        "generated_at": _now_iso(),
        "generated_by": "ea/scripts/verify_whatsapp_audiobook_public_share_playback.py",
        "status": "pass" if rows and passed == len(rows) else ("waiting" if not rows else "failed"),
        "attempted": len(rows),
        "passed": passed,
        "failed": len(rows) - passed,
        "results": rows,
        "privacy": {
            "raw_public_share_url_exposed": False,
            "raw_track_url_exposed": False,
            "job_ids_hashed": True,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    if any(flag in sys.argv[1:] for flag in ("--help", "-h")):
        print(
            "Usage:\n"
            "  python ea/scripts/verify_whatsapp_audiobook_public_share_playback.py [options]\n\n"
            "Verify WhatsApp audiobook public-share playback in Chromium."
        )
        return 0
    parser = argparse.ArgumentParser(description="Verify WhatsApp audiobook public-share playback in Chromium.")
    parser.add_argument("--output", "--out", dest="output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--job-id", default="")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--wait-seconds", type=float, default=3.0)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args()
    receipt = run(
        output_path=args.output,
        job_id=args.job_id,
        limit=args.limit,
        wait_seconds=args.wait_seconds,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(receipt, sort_keys=True))
    return 1 if args.require_pass and receipt["status"] != "pass" else 0


if __name__ == "__main__":
    raise SystemExit(main())
