#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
EA_DIR = ROOT / "ea"
EA_SCRIPTS = EA_DIR / "scripts"
ROOT_SCRIPTS = ROOT / "scripts"
DEFAULT_OUTPUT = ROOT / ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json"
RUNTIME_SOURCE_REVISION_FAILURE_CODE = "runtime_source_revision_unverified"
RUNTIME_SOURCE_REVISION_HEADER = "X-EA-Source-Revision"
RUNTIME_SOURCE_REVISION_MAX_BODY_BYTES = 1024 * 1024
RUNTIME_SOURCE_REVISION_TIMEOUT_SECONDS = 5.0

for import_root in (EA_SCRIPTS, EA_DIR, ROOT_SCRIPTS, ROOT):
    import_root_text = str(import_root)
    if import_root_text in sys.path:
        sys.path.remove(import_root_text)
for import_root in (EA_SCRIPTS, EA_DIR, ROOT_SCRIPTS, ROOT):
    sys.path.insert(0, str(import_root))

try:
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head
    from source_state_head import resolve_source_worktree_fingerprint

try:
    import scripts.validate_memorial_voice_loop as voice_loop  # noqa: E402
except ModuleNotFoundError:  # pragma: no cover - script execution path
    try:
        import validate_memorial_voice_loop as voice_loop  # type: ignore[no-redef]  # noqa: E402
    except ModuleNotFoundError:  # pragma: no cover - missing optional validator module
        def _missing_validate_memorial_voice_loop(**_kwargs: Any) -> Any:
            raise ModuleNotFoundError(
                "validate_memorial_voice_loop module is not present; provide scripts.validate_memorial_voice_loop "
                "or monkeypatch voice_loop.validate_memorial_voice_loop in tests."
            )

        voice_loop = SimpleNamespace(validate_memorial_voice_loop=_missing_validate_memorial_voice_loop)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head() -> str:
    return resolve_source_state_head(ROOT)


def _git_dirty() -> bool:
    import subprocess

    try:
        proc = subprocess.run(
            ["git", "status", "--short"],
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
    except Exception:
        return True
    return bool(proc.stdout.strip()) if proc.returncode == 0 else True


def _source_tree_fingerprint() -> str:
    import subprocess

    generated_prefixes = (
        ".codex-design/product/",
        ".codex-studio/published/",
    )
    try:
        proc = subprocess.run(
            ["git", "ls-files"],
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
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


def _is_local_base_url(base_url: str) -> bool:
    lowered = str(base_url or "").strip().lower()
    return any(
        marker in lowered
        for marker in (
            "://127.0.0.1",
            "://localhost",
            "://0.0.0.0",
            "://[::1]",
        )
    )


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


def build_receipt(
    *,
    slug: str,
    base_url: str,
    output_dir: Path,
    direct_text: str,
    conversation_question: str,
    present_world_question: str,
    require_stt: bool,
    gold_mode: bool = False,
    require_public_origin: bool = False,
    direct_min_f1: float = 0.92,
    conversation_min_f1: float = 0.90,
    max_conversation_turn_ms: float = 4500.0,
    max_speech_transcribe_ms: float = 2500.0,
    critical_tokens: tuple[str, ...] = (),
) -> dict[str, Any]:
    report = voice_loop.validate_memorial_voice_loop(
        slug=slug,
        base_url=base_url,
        output_dir=output_dir,
        direct_text=direct_text,
        conversation_question=conversation_question,
        present_world_question=present_world_question,
        require_stt=require_stt,
        gold_mode=gold_mode,
        direct_min_f1=direct_min_f1,
        conversation_min_f1=conversation_min_f1,
        critical_tokens=critical_tokens,
    )
    payload = report.as_dict()
    failed_codes = [
        str(item.get("code") or "")
        for item in payload.get("checks", [])
        if isinstance(item, dict) and str(item.get("status") or "").lower() == "fail"
    ]
    warned_codes = [
        str(item.get("code") or "")
        for item in payload.get("checks", [])
        if isinstance(item, dict) and str(item.get("status") or "").lower() == "warn"
    ]
    if require_public_origin and _is_local_base_url(base_url):
        failed_codes.append("public_origin_required")
        payload.setdefault("checks", []).append(
            {
                "status": "fail",
                "code": "public_origin_required",
                "message": "Memorial-gold voice proof requires a public or staging origin, not localhost.",
                "detail": {"base_url": base_url.rstrip("/")},
            }
        )
        payload["status"] = "fail"
    runtime_source_revision: str | None = None
    runtime_source_revision_required = bool(gold_mode or require_public_origin)
    if runtime_source_revision_required:
        probed_revision, probe_reason = _probe_runtime_source_revision(base_url=base_url, slug=slug)
        runtime_source_revision = _validated_source_revision(probed_revision)
        if runtime_source_revision is None:
            failed_codes.append(RUNTIME_SOURCE_REVISION_FAILURE_CODE)
            payload.setdefault("checks", []).append(
                {
                    "status": "fail",
                    "code": RUNTIME_SOURCE_REVISION_FAILURE_CODE,
                    "message": "The public memorial runtime did not expose a valid source revision.",
                    "detail": {"reason": probe_reason or "header_missing_or_invalid"},
                }
            )
            payload["status"] = "fail"
        else:
            payload.setdefault("checks", []).append(
                {
                    "status": "pass",
                    "code": "runtime_source_revision_verified",
                    "message": "The public memorial runtime exposed a valid source revision.",
                    "detail": {},
                }
            )
    metrics = dict(payload.get("metrics") or {})
    try:
        conversation_turn_total_ms = float(metrics.get("conversation_turn_total_ms") or 0.0)
    except Exception:
        conversation_turn_total_ms = 0.0
    try:
        speech_transcribe_ms = float(metrics.get("speech_transcribe_ms") or 0.0)
    except Exception:
        speech_transcribe_ms = 0.0
    if gold_mode and conversation_turn_total_ms > float(max_conversation_turn_ms):
        failed_codes.append("conversation_turn_total_ms_above_gold_threshold")
        payload.setdefault("checks", []).append(
            {
                "status": "fail",
                "code": "conversation_turn_total_ms_above_gold_threshold",
                "message": "Memorial-gold voice proof exceeded the conversation-turn latency threshold.",
                "detail": {
                    "conversation_turn_total_ms": conversation_turn_total_ms,
                    "max_allowed_ms": float(max_conversation_turn_ms),
                },
            }
        )
        payload["status"] = "fail"
    if gold_mode and speech_transcribe_ms > float(max_speech_transcribe_ms):
        failed_codes.append("speech_transcribe_ms_above_gold_threshold")
        payload.setdefault("checks", []).append(
            {
                "status": "fail",
                "code": "speech_transcribe_ms_above_gold_threshold",
                "message": "Memorial-gold voice proof exceeded the speech-transcribe latency threshold.",
                "detail": {
                    "speech_transcribe_ms": speech_transcribe_ms,
                    "max_allowed_ms": float(max_speech_transcribe_ms),
                },
            }
        )
        payload["status"] = "fail"
    dirty_worktree = _git_dirty()
    if gold_mode and dirty_worktree:
        failed_codes.append("dirty_worktree")
        payload.setdefault("checks", []).append(
            {
                "status": "fail",
                "code": "dirty_worktree",
                "message": "Memorial-gold voice proof requires a clean worktree.",
                "detail": {},
            }
        )
        payload["status"] = "fail"
    source_git_head = _git_head()
    receipt = {
        "contract_name": "ea.memorial_voice_roundtrip_exit_gate",
        "generated_at": _utc_now(),
        "generated_by": "scripts/materialize_memorial_voice_roundtrip_exit_gate.py",
        "source_git_head": source_git_head,
        "head_semantics": "source_state",
        "source_tree_fingerprint": _source_tree_fingerprint(),
        "source_state_fingerprint": resolve_source_worktree_fingerprint(ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
        "dirty_worktree": dirty_worktree,
        "status": payload.get("status"),
        "slug": slug,
        "base_url": base_url.rstrip("/"),
        "require_stt": bool(require_stt),
        "gold_mode": bool(gold_mode),
        "require_public_origin": bool(require_public_origin),
        "runtime_source_revision_required": runtime_source_revision_required,
        "direct_min_f1": float(direct_min_f1),
        "conversation_min_f1": float(conversation_min_f1),
        "max_conversation_turn_ms": float(max_conversation_turn_ms),
        "max_speech_transcribe_ms": float(max_speech_transcribe_ms),
        "critical_tokens": list(critical_tokens),
        "direct_text": direct_text,
        "conversation_question": conversation_question,
        "present_world_question": present_world_question,
        "failed_codes": failed_codes,
        "warned_codes": warned_codes,
        "metrics": payload.get("metrics", {}),
        "artifacts": payload.get("artifacts", {}),
        "checks": payload.get("checks", []),
        "gold_claim_allowed": (
            bool(gold_mode)
            and payload.get("status") == "pass"
            and not dirty_worktree
            and (not runtime_source_revision_required or runtime_source_revision is not None)
        ),
    }
    if runtime_source_revision_required:
        receipt["runtime_source_revision"] = runtime_source_revision
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize the live memorial voice roundtrip exit-gate receipt.")
    parser.add_argument("--slug", default=os.getenv("MEMORIAL_VOICE_EXIT_GATE_SLUG", "manfred"))
    parser.add_argument("--base-url", default=os.getenv("MEMORIAL_VOICE_EXIT_GATE_BASE_URL", "http://127.0.0.1:8090"))
    parser.add_argument("--output-dir", default=os.getenv("MEMORIAL_VOICE_EXIT_GATE_OUTPUT_DIR", "/tmp/memorial_voice_roundtrip_exit_gate"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--direct-text",
        default="Worum geht es?",
    )
    parser.add_argument("--conversation-question", default="Hallo Manfred, kannst du jetzt mit mir sprechen?")
    parser.add_argument("--present-world-question", default="Welches Wetter haben wir heute?")
    parser.add_argument("--allow-missing-stt", action="store_true")
    parser.add_argument("--gold-mode", action="store_true")
    parser.add_argument("--require-public-origin", action="store_true")
    parser.add_argument("--direct-min-f1", type=float, default=0.92)
    parser.add_argument("--conversation-min-f1", type=float, default=0.90)
    parser.add_argument("--max-conversation-turn-ms", type=float, default=float(os.getenv("MEMORIAL_GOLD_MAX_CONVERSATION_TURN_MS", "4500")))
    parser.add_argument("--max-speech-transcribe-ms", type=float, default=float(os.getenv("MEMORIAL_GOLD_MAX_SPEECH_TRANSCRIBE_MS", "2500")))
    parser.add_argument("--critical-token", action="append", default=[])
    args = parser.parse_args(argv)

    receipt = build_receipt(
        slug=args.slug,
        base_url=args.base_url,
        output_dir=Path(args.output_dir),
        direct_text=args.direct_text,
        conversation_question=args.conversation_question,
        present_world_question=args.present_world_question,
        require_stt=not args.allow_missing_stt,
        gold_mode=bool(args.gold_mode),
        require_public_origin=bool(args.require_public_origin),
        direct_min_f1=float(args.direct_min_f1),
        conversation_min_f1=float(args.conversation_min_f1),
        max_conversation_turn_ms=float(args.max_conversation_turn_ms),
        max_speech_transcribe_ms=float(args.max_speech_transcribe_ms),
        critical_tokens=tuple(str(token) for token in args.critical_token),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "output": str(output), "failed_codes": receipt["failed_codes"]}, ensure_ascii=False))
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
