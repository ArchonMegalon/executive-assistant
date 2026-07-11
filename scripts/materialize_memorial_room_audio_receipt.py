#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head
    from source_state_head import resolve_source_worktree_fingerprint


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".codex-studio/published/memorial_room_audio_public_origin.generated.json"
RUNTIME_SOURCE_REVISION_FAILURE_CODE = "runtime_source_revision_unverified"
RUNTIME_SOURCE_REVISION_HEADER = "X-EA-Source-Revision"
RUNTIME_SOURCE_REVISION_MAX_BODY_BYTES = 1024 * 1024
RUNTIME_SOURCE_REVISION_TIMEOUT_SECONDS = 5.0
ROOM_AUDIO_CHECK_REQUIREMENTS = {
    "actual_device_checked": "The tester used the actual public-origin device/browser path, not a simulated CI playback.",
    "actual_speaker_checked": "The tester heard the response through the intended output speaker/headphones.",
    "first_syllable_not_clipped": "The first audible syllable was present and not clipped by playback startup.",
    "intelligibility_confirmed": "The spoken answer was understandable in the room without reading the fallback text.",
    "answer_text_fallback_visible": "Fallback transcript text remained visible for accessibility and recovery.",
    "no_internet_search_confirmed": "The memorial answer did not use internet search as Manfred.",
    "normal_spoken_turn_confirmed": "A normal spoken question completed as microphone capture, STT, answer, TTS, and playback.",
    "interruption_behavior_confirmed": "Intentional interruption or barge-in behavior was observed and was not harsh or confusing.",
    "retry_path_confirmed": "The tester observed a clear retry/recovery path after an acoustic or turn-taking problem.",
}


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head() -> str:
    return resolve_source_state_head(ROOT)


def _git_dirty() -> bool:
    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "status", "--short"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return True
    return bool(proc.stdout.strip()) if proc.returncode == 0 else True


def _source_tree_fingerprint() -> str:
    generated_prefixes = (
        ".codex-design/product/",
        ".codex-studio/published/",
    )
    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    digest = hashlib.sha256()
    for relpath in sorted(line.strip() for line in proc.stdout.splitlines() if line.strip()):
        if relpath.startswith(generated_prefixes):
            continue
        path = ROOT / relpath
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            return ""
        digest.update(relpath.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).hexdigest().encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _is_local_base_url(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    return any(marker in lowered for marker in ("://127.0.0.1", "://localhost", "://0.0.0.0", "://[::1]"))


def _normalized_label(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _is_generic_room_value(value: object, generic_values: set[str]) -> bool:
    normalized = _normalized_label(value)
    return bool(normalized and normalized in generic_values)


def _looks_like_utc_timestamp(value: object) -> bool:
    text = str(value or "").strip()
    if not text.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _validated_source_revision(value: object) -> str | None:
    text = str(value or "")
    if len(text) != 40 or any(character not in "0123456789abcdef" for character in text):
        return None
    return text


def _url_origin(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(str(value or ""))
        port = parsed.port
    except ValueError:
        return None
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    if scheme not in {"http", "https"} or not hostname or parsed.username or parsed.password:
        return None
    if port is None:
        port = 443 if scheme == "https" else 80
    return scheme, hostname, port


class _SameOriginRedirectHandler(HTTPRedirectHandler):
    def __init__(self, expected_origin: tuple[str, str, int]) -> None:
        super().__init__()
        self._expected_origin = expected_origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        redirect_url = urljoin(req.full_url, str(newurl or ""))
        if _url_origin(redirect_url) != self._expected_origin:
            raise URLError("runtime_source_revision_cross_origin_redirect")
        return super().redirect_request(req, fp, code, msg, headers, redirect_url)


def _probe_runtime_source_revision(*, base_url: str, slug: str) -> tuple[str | None, str | None]:
    slug_text = str(slug or "").strip()
    if not slug_text or len(slug_text) > 128:
        return None, "request_invalid"
    base_text = str(base_url or "").rstrip("/")
    try:
        base_parts = urlsplit(base_text)
        endpoint = f"{base_text}/memorials/{quote(slug_text, safe='')}.json"
    except (UnicodeError, ValueError):
        return None, "request_invalid"
    expected_origin = _url_origin(endpoint)
    if expected_origin is None or base_parts.query or base_parts.fragment:
        return None, "request_invalid"
    try:
        request = Request(endpoint, headers={"Accept": "application/json"}, method="GET")
        opener = build_opener(_SameOriginRedirectHandler(expected_origin))
        with opener.open(request, timeout=RUNTIME_SOURCE_REVISION_TIMEOUT_SECONDS) as response:
            if _url_origin(str(response.geturl() or "")) != expected_origin:
                return None, "cross_origin_final_url"
            status = int(response.getcode() or 0)
            if status != 200:
                return None, "unexpected_status"
            body = response.read(RUNTIME_SOURCE_REVISION_MAX_BODY_BYTES + 1)
            if len(body) > RUNTIME_SOURCE_REVISION_MAX_BODY_BYTES:
                return None, "response_too_large"
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                return None, "response_invalid"
            if not isinstance(payload, dict):
                return None, "response_invalid"
            revision = _validated_source_revision(response.headers.get(RUNTIME_SOURCE_REVISION_HEADER))
            if revision is None:
                return None, "header_missing_or_invalid"
            return revision, None
    except (AttributeError, HTTPError, TypeError, URLError, OSError, TimeoutError, ValueError):
        return None, "request_failed"


def build_receipt(args: argparse.Namespace) -> dict[str, object]:
    source_git_head = _git_head()
    checks = {
        key: bool(getattr(args, key, False))
        for key in ROOM_AUDIO_CHECK_REQUIREMENTS
    }
    failed_codes = [f"{key}_missing" for key, value in checks.items() if value is not True]
    reviewer = str(args.reviewer or "").strip()
    device_label = str(args.device_label or "").strip()
    speaker_label = str(args.speaker_label or "").strip()
    room_label = str(args.room_label or "").strip()
    notes = str(args.notes or "").strip()
    if not reviewer:
        failed_codes.append("reviewer_missing")
    elif _is_generic_room_value(reviewer, {"qa-room-reviewer", "qa room reviewer", "reviewer", "test reviewer"}):
        failed_codes.append("reviewer_generic")
    if not device_label:
        failed_codes.append("device_label_missing")
    elif _is_generic_room_value(device_label, {"laptop speaker test", "presentation laptop", "laptop", "test device"}):
        failed_codes.append("device_label_generic")
    if not speaker_label:
        failed_codes.append("speaker_label_missing")
    elif _is_generic_room_value(speaker_label, {"room speaker", "speaker", "laptop speaker", "test speaker"}):
        failed_codes.append("speaker_label_generic")
    if not room_label:
        failed_codes.append("room_label_missing")
    elif _is_generic_room_value(room_label, {"office", "room", "test room"}):
        failed_codes.append("room_label_generic")
    if not notes:
        failed_codes.append("notes_missing")
    attestation_id = str(getattr(args, "manual_attestation_id", "") or "").strip()
    attestation_signed_at = str(getattr(args, "manual_attestation_signed_at", "") or "").strip()
    if not attestation_id:
        failed_codes.append("manual_attestation_id_missing")
    if not attestation_signed_at:
        failed_codes.append("manual_attestation_signed_at_missing")
    elif not _looks_like_utc_timestamp(attestation_signed_at):
        failed_codes.append("manual_attestation_signed_at_invalid")
    if bool(args.require_public_origin) and _is_local_base_url(str(args.base_url or "")):
        failed_codes.append("public_origin_required")
    probed_revision, _probe_reason = _probe_runtime_source_revision(
        base_url=str(args.base_url or ""),
        slug=str(args.slug or "manfred"),
    )
    runtime_source_revision = _validated_source_revision(probed_revision)
    if runtime_source_revision is None:
        failed_codes.append(RUNTIME_SOURCE_REVISION_FAILURE_CODE)
    dirty_worktree = _git_dirty()
    if dirty_worktree:
        failed_codes.append("dirty_worktree")
    status = "pass" if not failed_codes else "fail"
    return {
        "contract_name": "ea.memorial_room_audio_public_origin",
        "generated_at": _utc_now(),
        "generated_by": "scripts/materialize_memorial_room_audio_receipt.py",
        "proof_type": "manual_room_attestation",
        "source_git_head": source_git_head,
        "head_semantics": "source_state",
        "source_tree_fingerprint": _source_tree_fingerprint(),
        "source_state_fingerprint": resolve_source_worktree_fingerprint(ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
        "dirty_worktree": dirty_worktree,
        "status": status,
        "base_url": str(args.base_url or "").rstrip("/"),
        "slug": str(args.slug or "manfred"),
        "require_public_origin": bool(args.require_public_origin),
        "runtime_source_revision_required": True,
        "runtime_source_revision": runtime_source_revision,
        "reviewer": reviewer,
        "device_label": device_label,
        "speaker_label": speaker_label,
        "room_label": room_label,
        "checks": checks,
        "check_requirements": ROOM_AUDIO_CHECK_REQUIREMENTS,
        "manual_attestation": {
            "attestation_id": attestation_id,
            "signed_at": attestation_signed_at,
            "source": str(getattr(args, "manual_attestation_source", "") or "operator_room_review").strip()
            or "operator_room_review",
            "ci_must_not_auto_assert": True,
        },
        "notes": notes,
        "failed_codes": failed_codes,
        "gold_claim_allowed": status == "pass",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize the manual room/device playback receipt for memorial public-origin gold.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--slug", default="manfred")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--device-label", default="")
    parser.add_argument("--speaker-label", default="")
    parser.add_argument("--room-label", default="")
    parser.add_argument("--notes", default="")
    parser.add_argument("--manual-attestation-id", default="")
    parser.add_argument("--manual-attestation-signed-at", default="")
    parser.add_argument("--manual-attestation-source", default="operator_room_review")
    parser.add_argument("--require-public-origin", action="store_true")
    parser.add_argument("--actual-device-checked", action="store_true")
    parser.add_argument("--actual-speaker-checked", action="store_true")
    parser.add_argument("--first-syllable-not-clipped", action="store_true")
    parser.add_argument("--intelligibility-confirmed", action="store_true")
    parser.add_argument("--answer-text-fallback-visible", action="store_true")
    parser.add_argument("--no-internet-search-confirmed", action="store_true")
    parser.add_argument("--normal-spoken-turn-confirmed", action="store_true")
    parser.add_argument("--interruption-behavior-confirmed", action="store_true")
    parser.add_argument("--retry-path-confirmed", action="store_true")
    args = parser.parse_args()

    receipt = build_receipt(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "output": str(output), "failed_codes": receipt["failed_codes"]}, ensure_ascii=False))
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
