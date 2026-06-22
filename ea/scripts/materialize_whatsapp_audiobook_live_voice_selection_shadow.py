from __future__ import annotations

import argparse
import importlib.util
from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
EA_ROOT = ROOT / "ea"
DEFAULT_OUTPUT = ROOT / ".codex-studio" / "published" / "whatsapp_audiobook_live_voice_selection_shadow.generated.json"
CONTRACT_NAME = "ea.whatsapp_audiobook_live_voice_selection_shadow.v1"
SHADOW_CALLBACK_SECRET = "ea-whatsapp-audiobook-shadow-proof-secret"
SHADOW_SENDER_REF = "4360000000000"
SHADOW_CHAT_REF = "shadow-whatsapp-chat"
SHADOW_SESSION_REF = "shadow-whatsapp-session"
FUTURE_EXPIRY = 4102444800


if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))


from app.services import audiobook_epub_pipeline, whatsapp_inbound_actions  # noqa: E402


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_text(value: object) -> str:
    text = str(value or "").strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def _as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


@contextmanager
def _temporary_env(values: dict[str, str]):
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, old_value in previous.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def _load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_processor_module():
    path = ROOT / "scripts" / "process_whatsapp_web_session_actions.py"
    spec = importlib.util.spec_from_file_location("process_whatsapp_web_session_actions_for_shadow_proof", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("processor_module_load_failed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _voice_selection(job: dict[str, object]) -> dict[str, object]:
    return _as_dict(_as_dict(job.get("provider")).get("voice_selection"))


def _whatsapp(job: dict[str, object]) -> dict[str, object]:
    return _as_dict(job.get("whatsapp"))


def _waiting_whatsapp_voice_job(job: dict[str, object]) -> bool:
    selection = _voice_selection(job)
    whatsapp = _whatsapp(job)
    return (
        str(job.get("status") or "").strip() == "waiting_voice_selection"
        and str(selection.get("status") or "").strip() == "waiting_user_choice"
        and bool(_as_list(selection.get("pending_batch")))
        and bool(str(whatsapp.get("sender_ref") or "").strip())
    )


def _candidate_job_dirs(root: Path) -> list[Path]:
    rows: list[tuple[float, str, Path]] = []
    if not root.is_dir():
        return []
    for manifest_path in sorted(root.glob("*/job.json")):
        job = _load_json(manifest_path)
        if not _waiting_whatsapp_voice_job(job):
            continue
        try:
            mtime = manifest_path.stat().st_mtime
        except OSError:
            mtime = 0.0
        rows.append((mtime, manifest_path.parent.name, manifest_path.parent))
    rows.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [row[2] for row in rows]


def _select_job_dir(job_dir: Path | None) -> Path | None:
    if job_dir is not None:
        return job_dir if (job_dir / "job.json").is_file() else None
    candidates = _candidate_job_dirs(audiobook_epub_pipeline.audiobook_jobs_root())
    return candidates[0] if candidates else None


def _candidate_summary(job: dict[str, object], job_dir: Path) -> dict[str, object]:
    metadata = _as_dict(job.get("metadata"))
    selection = _voice_selection(job)
    pending = [row for row in _as_list(selection.get("pending_batch")) if isinstance(row, dict)]
    whatsapp = _whatsapp(job)
    delivery = _as_dict(whatsapp.get("voice_sample_delivery"))
    return {
        "job_dir_name": job_dir.name,
        "job_id_sha256": _sha256_text(job.get("job_id") or job_dir.name),
        "manifest_sha256": _sha256_file(job_dir / "job.json"),
        "title_present": bool(str(metadata.get("title") or "").strip()),
        "title_sha256": _sha256_text(metadata.get("title")),
        "language": str(metadata.get("language") or "").strip(),
        "status": str(job.get("status") or "").strip(),
        "next_action": str(job.get("next_action") or "").strip(),
        "voice_selection_status": str(selection.get("status") or "").strip(),
        "voice_selection_reason": str(selection.get("reason") or "").strip(),
        "pending_voice_count": len(pending),
        "voice_sample_delivery_status": str(delivery.get("status") or "").strip(),
        "voice_sample_delivery_sent_count": int(delivery.get("sent_count") or 0),
        "whatsapp_sender_bound": bool(str(whatsapp.get("sender_ref") or "").strip()),
        "whatsapp_chat_ref_bound": bool(str(whatsapp.get("chat_ref") or "").strip()),
        "raw_sender_ref_exposed": False,
        "raw_callback_token_exposed": False,
        "raw_voice_id_exposed": False,
        "private_job_path_exposed": False,
    }


def _prepare_shadow_copy(*, source_job_dir: Path, jobs_root: Path) -> Path:
    shadow_job_dir = jobs_root / source_job_dir.name
    shutil.copytree(source_job_dir, shadow_job_dir)
    job_path = shadow_job_dir / "job.json"
    job = _load_json(job_path)
    storage = _as_dict(job.get("storage"))
    storage["job_dir"] = str(shadow_job_dir)
    job["storage"] = storage
    whatsapp = _whatsapp(job)
    whatsapp.update(
        {
            "sender_ref": SHADOW_SENDER_REF,
            "chat_ref": SHADOW_CHAT_REF,
            "session_ref": SHADOW_SESSION_REF,
        }
    )
    job["whatsapp"] = whatsapp
    _write_json(job_path, job)
    return shadow_job_dir


def _run_shadow_callback(shadow_job_dir: Path) -> dict[str, object]:
    job_path = shadow_job_dir / "job.json"
    job = _load_json(job_path)
    selection = _voice_selection(job)
    pending = [row for row in _as_list(selection.get("pending_batch")) if isinstance(row, dict)]
    chosen = pending[0] if pending else {}
    token = str(chosen.get("callback_token") or "").strip()
    if not token:
        return {"status": "failed", "reason": "pending_callback_token_missing"}
    callback_data = whatsapp_inbound_actions.encode_whatsapp_audiobook_voice_callback(
        action="u",
        token=token,
        sender_ref=SHADOW_SENDER_REF,
        expires_at=FUTURE_EXPIRY,
    )
    if not callback_data:
        return {"status": "failed", "reason": "callback_encoding_failed"}
    result = dict(
        whatsapp_inbound_actions.handle_whatsapp_inbound_callback(
            callback_data=callback_data,
            sender_ref=SHADOW_SENDER_REF,
            message_id="wamid.shadow.voice-selection",
        )
    )
    updated = _load_json(job_path)
    updated_selection = _voice_selection(updated)
    selected = _as_dict(updated_selection.get("selected"))
    pending_after = [row for row in _as_list(updated_selection.get("pending_batch")) if isinstance(row, dict)]
    return {
        "status": "pass"
        if (
            str(result.get("status") or "").strip() == "applied"
            and str(result.get("kind") or "").strip() == "audiobook_voice"
            and str(result.get("action") or "").strip() == "use"
            and str(updated.get("status") or "").strip() == "voice_selected"
            and str(updated.get("next_action") or "").strip() == "render_chapter_audio"
            and bool(str(updated_selection.get("selected_candidate_key") or "").strip())
            and not pending_after
            and updated_selection.get("raw_voice_ids_exposed") is False
        )
        else "failed",
        "callback_status": str(result.get("status") or "").strip(),
        "callback_kind": str(result.get("kind") or "").strip(),
        "callback_action": str(result.get("action") or "").strip(),
        "candidate_token_sha256": _sha256_text(token),
        "selected_label_sha256": _sha256_text(selected.get("label")),
        "selected_label_present": bool(str(selected.get("label") or "").strip()),
        "selected_candidate_key_sha256": _sha256_text(updated_selection.get("selected_candidate_key")),
        "selected_candidate_key_present": bool(str(updated_selection.get("selected_candidate_key") or "").strip()),
        "shadow_status": str(updated.get("status") or "").strip(),
        "shadow_next_action": str(updated.get("next_action") or "").strip(),
        "pending_voice_count_after": len(pending_after),
        "raw_voice_ids_exposed": bool(updated_selection.get("raw_voice_ids_exposed")),
        "raw_callback_token_exposed": False,
        "raw_sender_ref_exposed": False,
        "raw_message_id_exposed": False,
        "reason": "" if str(result.get("status") or "").strip() == "applied" else str(result.get("reason") or "").strip(),
    }


def _run_shadow_text_fallback_proof(shadow_job_dir: Path) -> dict[str, object]:
    processor = _load_processor_module()
    job = _load_json(shadow_job_dir / "job.json")
    selection = _voice_selection(job)
    pending = [row for row in _as_list(selection.get("pending_batch")) if isinstance(row, dict)]
    chosen = pending[0] if pending else {}
    label = str(chosen.get("label") or "").strip()
    if not label:
        return {"status": "failed", "reason": "pending_label_missing"}
    use_text = f"use {label}"
    dismiss_text = f"dismiss {label}"
    use_action = str(processor._whatsapp_voice_text_action(use_text) or "").strip()  # type: ignore[attr-defined]
    dismiss_action = str(processor._whatsapp_voice_text_action(dismiss_text) or "").strip()  # type: ignore[attr-defined]
    dismiss_all_action = str(processor._whatsapp_voice_text_action("dismiss all") or "").strip()  # type: ignore[attr-defined]
    bare_choice = str(
        processor._pending_whatsapp_voice_label_choice(  # type: ignore[attr-defined]
            label,
            sender_digits=SHADOW_SENDER_REF,
            chat_ref=SHADOW_CHAT_REF,
        )
        or ""
    ).strip()
    source = (ROOT / "scripts" / "process_whatsapp_web_session_actions.py").read_text(encoding="utf-8")
    prompt_mentions_fallback = (
        "If the buttons do not work, reply 'use " in source and "'dismiss all'" in source
    )
    status = (
        "pass"
        if use_action == "use_named"
        and dismiss_action == "dismiss_named"
        and dismiss_all_action == "dismiss_all"
        and bare_choice == label
        and prompt_mentions_fallback
        else "failed"
    )
    return {
        "status": status,
        "use_named_action": use_action,
        "dismiss_named_action": dismiss_action,
        "dismiss_all_action": dismiss_all_action,
        "bare_voice_choice_resolved": bare_choice == label,
        "fallback_prompt_mentions_text_commands": prompt_mentions_fallback,
        "raw_label_exposed": False,
        "reason": "" if status == "pass" else "whatsapp_text_fallback_proof_failed",
    }


def build_receipt(
    *,
    output_path: Path = DEFAULT_OUTPUT,
    job_dir: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, object]:
    observed_at = generated_at or _now_iso()
    selected_job_dir = _select_job_dir(job_dir)
    if selected_job_dir is None:
        receipt = {
            "contract_name": CONTRACT_NAME,
            "generated_at": observed_at,
            "status": "waiting",
            "reason": "waiting_whatsapp_voice_selection_job_not_found",
            "candidate": {},
            "shadow": {},
            "checks": {
                "waiting_voice_selection_job_found": False,
                "shadow_callback_applied": False,
                "shadow_text_fallback_ready": False,
                "shadow_reached_render_action": False,
                "live_job_unchanged": False,
            },
        }
        _write_json(output_path, receipt)
        return receipt

    before_hash = _sha256_file(selected_job_dir / "job.json")
    source_job = _load_json(selected_job_dir / "job.json")
    shadow_result: dict[str, object] = {}
    text_fallback_result: dict[str, object] = {}
    live_unchanged = False
    with tempfile.TemporaryDirectory(prefix="ea-wa-audiobook-shadow-") as tmp:
        tmp_root = Path(tmp)
        with _temporary_env(
            {
                "EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE": "1",
                "EA_AUDIOBOOK_UNMIXR_AUTO_RENDER": "0",
                "EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED": "1",
                "EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET": SHADOW_CALLBACK_SECRET,
            }
        ):
            text_jobs_root = tmp_root / "text-jobs"
            text_jobs_root.mkdir(parents=True, exist_ok=True)
            with _temporary_env({"EA_AUDIOBOOK_JOBS_ROOT": str(text_jobs_root)}):
                text_shadow_job_dir = _prepare_shadow_copy(source_job_dir=selected_job_dir, jobs_root=text_jobs_root)
                text_fallback_result = _run_shadow_text_fallback_proof(text_shadow_job_dir)
            callback_jobs_root = tmp_root / "callback-jobs"
            callback_jobs_root.mkdir(parents=True, exist_ok=True)
            with _temporary_env({"EA_AUDIOBOOK_JOBS_ROOT": str(callback_jobs_root)}):
                callback_shadow_job_dir = _prepare_shadow_copy(source_job_dir=selected_job_dir, jobs_root=callback_jobs_root)
                shadow_result = _run_shadow_callback(callback_shadow_job_dir)
        after_hash = _sha256_file(selected_job_dir / "job.json")
        live_unchanged = bool(before_hash and before_hash == after_hash)

    checks = {
        "waiting_voice_selection_job_found": True,
        "voice_sample_delivery_sent": str(
            _as_dict(_whatsapp(source_job).get("voice_sample_delivery")).get("status") or ""
        ).strip()
        == "sent",
        "shadow_callback_applied": str(shadow_result.get("callback_status") or "").strip() == "applied",
        "shadow_text_fallback_ready": str(text_fallback_result.get("status") or "").strip() == "pass",
        "shadow_reached_render_action": (
            str(shadow_result.get("shadow_status") or "").strip() == "voice_selected"
            and str(shadow_result.get("shadow_next_action") or "").strip() == "render_chapter_audio"
        ),
        "shadow_pending_batch_cleared": int(shadow_result.get("pending_voice_count_after", -1)) == 0,
        "shadow_raw_voice_ids_not_exposed": shadow_result.get("raw_voice_ids_exposed") is False,
        "live_job_unchanged": live_unchanged,
    }
    status = "pass" if all(checks.values()) and str(shadow_result.get("status") or "") == "pass" else "failed"
    receipt = {
        "contract_name": CONTRACT_NAME,
        "generated_at": observed_at,
        "status": status,
        "reason": "" if status == "pass" else "shadow_voice_selection_proof_failed",
        "candidate": _candidate_summary(source_job, selected_job_dir),
        "shadow": shadow_result,
        "text_fallback": text_fallback_result,
        "checks": checks,
        "privacy": {
            "raw_sender_ref_exposed": False,
            "raw_callback_token_exposed": False,
            "raw_voice_id_exposed": False,
            "raw_message_id_exposed": False,
            "private_job_path_exposed": False,
        },
        "live_mutation": {
            "manifest_sha256_before": before_hash,
            "manifest_sha256_after": _sha256_file(selected_job_dir / "job.json"),
            "unchanged": live_unchanged,
        },
    }
    _write_json(output_path, receipt)
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Materialize a shadow proof for live WhatsApp audiobook voice selection.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--job-dir", type=Path)
    parser.add_argument("--require-pass", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = build_receipt(output_path=args.output, job_dir=args.job_dir)
    print(json.dumps(receipt, indent=2 if args.pretty else None, sort_keys=True))
    if args.require_pass and str(receipt.get("status") or "") != "pass":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
