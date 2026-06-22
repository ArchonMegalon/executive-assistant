from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import UTC, datetime
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
import wave
import zipfile


ROOT = Path(__file__).resolve().parents[2]
EA_ROOT = ROOT / "ea"
PROCESSOR_SCRIPT = ROOT / "scripts" / "process_whatsapp_web_session_actions.py"
DEFAULT_OUTPUT = ROOT / ".codex-studio" / "published" / "whatsapp_audiobook_local_intake_proof.generated.json"
CONTRACT_NAME = "ea.whatsapp_audiobook_local_epub_intake_proof.v1"


if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _load_processor_module():
    spec = importlib.util.spec_from_file_location("process_whatsapp_web_session_actions_for_local_proof", PROCESSOR_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("whatsapp_action_processor_script_missing")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_live_receipt_module():
    path = Path(__file__).with_name("materialize_whatsapp_audiobook_live_delivery_receipt.py")
    spec = importlib.util.spec_from_file_location("materialize_whatsapp_audiobook_live_delivery_receipt_for_local_proof", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("whatsapp_live_receipt_script_missing")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_minimal_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as book:
        book.writestr("mimetype", "application/epub+zip")
        book.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        book.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>WhatsApp Proof Book</dc:title>
    <dc:creator>A. Writer</dc:creator>
    <dc:language>en-US</dc:language>
  </metadata>
  <manifest>
    <item id="chap1" href="chapters/chapter-1.xhtml" media-type="application/xhtml+xml"/>
    <item id="chap2" href="chapters/chapter-2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chap1"/>
    <itemref idref="chap2"/>
  </spine>
</package>
""",
        )
        book.writestr(
            "OEBPS/chapters/chapter-1.xhtml",
            "<html><body><h1>Opening</h1><p>Hello from a real WhatsApp EPUB intake proof.</p></body></html>",
        )
        book.writestr(
            "OEBPS/chapters/chapter-2.xhtml",
            "<html><body><h1>Next</h1><p>The generated job should keep WhatsApp delivery metadata.</p></body></html>",
        )


def _tone_wav_bytes(*, seconds: float = 0.12, sample_rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    samples = [
        0.12 * math.sin(2 * math.pi * 220 * index / sample_rate)
        for index in range(max(int(sample_rate * seconds), 1))
    ]
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"".join(struct.pack("<h", int(value * 32767)) for value in samples))
    return buffer.getvalue()


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


def _build_args(*, tmp_root: Path):
    from argparse import Namespace

    return Namespace(
        auth_header_name="Authorization",
        auth_header_prefix="Bearer ",
        dry_run=False,
        principal_id="local-proof-principal",
        audiobook_resume_due=False,
        audiobook_resume_due_limit=1,
        audiobook_followup_enabled=False,
        audiobook_followup_limit=3,
        reply_typing_delay_ms=0,
        reply_typing_status_enabled=False,
        session_api_base_url="https://wa-local-proof.invalid",
        session_api_token="local-proof-token",
        session_ref="local-proof-session",
        state_file=str(tmp_root / "wa-actions.json"),
        take=100,
        timeout_seconds=30.0,
    )


def _first_use_callback(requests: list[dict[str, object]]) -> str:
    for request in requests:
        body = request.get("body")
        if not isinstance(body, dict):
            continue
        for group in list(body.get("buttons") or []):
            if not isinstance(group, list):
                continue
            for button in group:
                if not isinstance(button, (list, tuple)) or len(button) < 2:
                    continue
                if str(button[0] or "").strip().lower().startswith("use "):
                    return str(button[1] or "").strip()
    return ""


def _player_token_from_reference(reference: dict[str, object]) -> str:
    relative = str(reference.get("relative_url") or "").strip()
    marker = "/internal/audiobooks/player/"
    if marker in relative:
        return relative.rsplit(marker, 1)[1].strip()
    absolute = str(reference.get("absolute_url") or "").strip()
    if marker in absolute:
        return absolute.rsplit(marker, 1)[1].strip()
    return ""


def _probe_resolved_player_audio(processor, *, token: str) -> dict[str, object]:
    if not token:
        return {"status": "failed", "reason": "player_token_missing"}
    try:
        resolved_path, resolved_metadata = processor.audiobook_epub_pipeline.resolve_player_scoped_audiobook_file(token)
    except Exception as exc:
        return {"status": "failed", "reason": type(exc).__name__}
    probe = processor.audiobook_epub_pipeline._probe_audio_publication_file(resolved_path)
    streams = probe.get("streams") if isinstance(probe.get("streams"), list) else []
    audio_streams = [row for row in streams if isinstance(row, dict) and row.get("codec_type") == "audio"]
    chapters = probe.get("chapters") if isinstance(probe.get("chapters"), list) else []
    try:
        duration_seconds = float(dict(probe.get("format") or {}).get("duration") or 0.0)
    except Exception:
        duration_seconds = 0.0
    passed = (
        str(dict(resolved_metadata).get("status") or "") == "ready"
        and resolved_path.is_file()
        and len(audio_streams) >= 1
        and duration_seconds > 0
    )
    return {
        "status": "pass" if passed else "failed",
        "metadata_status": str(dict(resolved_metadata).get("status") or ""),
        "content_type": str(dict(resolved_metadata).get("content_type") or ""),
        "file_ready": resolved_path.is_file(),
        "file_sha256": processor.audiobook_epub_pipeline._sha256_file(resolved_path)
        if resolved_path.is_file()
        else "",
        "audio_streams": len(audio_streams),
        "chapter_count": len(chapters),
        "duration_seconds": round(duration_seconds, 3),
        "raw_path_exposed": False,
        "raw_token_exposed": False,
        "reason": "" if passed else str(probe.get("probe_error") or "player_audio_probe_failed"),
    }


def _probe_http_player_route(*, token: str) -> dict[str, object]:
    if not token:
        return {"status": "failed", "reason": "player_token_missing"}
    try:
        from app.api.app import create_app
        from fastapi.testclient import TestClient

        client = TestClient(create_app())
        metadata_response = client.get(f"/internal/audiobooks/player/{token}")
        metadata_payload = metadata_response.json() if metadata_response.status_code == 200 else {}
        download_url = str(dict(metadata_payload).get("download_url") or "").strip()
        download_response = client.get(download_url) if download_url else None
    except Exception as exc:
        return {"status": "failed", "reason": type(exc).__name__}

    download_status_code = int(download_response.status_code) if download_response is not None else 0
    download_content_type = (
        str(download_response.headers.get("content-type") or "").strip() if download_response is not None else ""
    )
    download_cache_control = (
        str(download_response.headers.get("cache-control") or "").strip() if download_response is not None else ""
    )
    download_bytes = len(download_response.content or b"") if download_response is not None else 0
    metadata = dict(metadata_payload) if isinstance(metadata_payload, dict) else {}
    passed = (
        metadata_response.status_code == 200
        and str(metadata.get("status") or "") == "ready"
        and str(metadata_response.headers.get("cache-control") or "").strip() == "no-store"
        and bool(download_url)
        and download_status_code == 200
        and download_content_type.startswith("audio/mp4")
        and download_cache_control == "no-store"
        and download_bytes > 0
        and metadata.get("vendor_token_exposed") is False
        and metadata.get("raw_library_path_exposed") is False
    )
    return {
        "status": "pass" if passed else "failed",
        "metadata_status_code": int(metadata_response.status_code),
        "metadata_status": str(metadata.get("status") or ""),
        "metadata_cache_control": str(metadata_response.headers.get("cache-control") or "").strip(),
        "metadata_download_url_present": bool(download_url),
        "metadata_vendor_token_exposed": bool(metadata.get("vendor_token_exposed")),
        "metadata_raw_library_path_exposed": bool(metadata.get("raw_library_path_exposed")),
        "download_status_code": download_status_code,
        "download_content_type": download_content_type,
        "download_cache_control": download_cache_control,
        "download_bytes": download_bytes,
        "raw_path_exposed": False,
        "raw_token_exposed": False,
        "reason": "" if passed else "player_http_route_probe_failed",
    }


def materialize_whatsapp_audiobook_local_intake_proof(*, output_path: Path = DEFAULT_OUTPUT) -> dict[str, object]:
    generated_at = _now_iso()
    processor = _load_processor_module()

    with tempfile.TemporaryDirectory(prefix="ea-wa-audiobook-proof-") as tmp:
        tmp_root = Path(tmp)
        jobs_root = tmp_root / "jobs"
        import_root = tmp_root / "audiobookshelf"
        source_epub = tmp_root / "whatsapp-proof.epub"
        _write_minimal_epub(source_epub)
        requests: list[dict[str, object]] = []
        inbound_messages: list[dict[str, object]] = [
            {
                "direction": "inbound",
                "from_me": False,
                "id": "wamid.local-proof.epub.1",
                "media_filename": "whatsapp-proof.epub",
                "media_mime_type": "application/epub+zip",
                "media_present": True,
                "sender_digits": "4368120864006",
            }
        ]

        def request_json(**kwargs: object) -> dict[str, object]:
            requests.append(dict(kwargs))
            if kwargs.get("method") == "GET":
                return {
                    "ok": True,
                    "messages": list(inbound_messages),
                }
            return {"ok": True, "message_id": f"wamid.local-proof.out.{len(requests)}"}

        env = {
            "EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET": "local-proof-callback-secret",
            "EA_AUDIOBOOK_INSTANT_PHONE_WHITELIST": "4368120864006",
            "EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE": "1",
            "EA_AUDIOBOOK_JOBS_ROOT": str(jobs_root),
            "EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED": "1",
            "EA_AUDIOBOOK_UNMIXR_AUTO_RENDER": "1",
            "EA_AUDIOBOOK_UNMIXR_RETRY_COUNT": "1",
            "EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED": "0",
            "EA_AUDIOBOOKSHELF_AUTO_IMPORT": "1",
            "EA_AUDIOBOOKSHELF_IMPORT_ROOT": str(import_root),
            "EA_AUDIOBOOKSHELF_PUBLIC_SHARE_ENABLED": "1",
            "EA_AUDIOBOOK_ACCESS_SIGNING_SECRET": "local-proof-access-secret",
            "EA_AUDIOBOOK_PLAYER_ACCESS_BASE_URL": "https://ea-local-proof.invalid",
            "EA_AUDIOBOOK_M4B_AUTO_MERGE": "1",
            "EA_AUDIOBOOK_FFMPEG_M4B_FALLBACK": "1",
            "EA_M4B_TOOL_BIN": "definitely-missing-m4b-tool",
            "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON": json.dumps(
                [
                    {
                        "voice_id": "voice-clear",
                        "label": "Clear narrator",
                        "language": "en-US",
                        "tags": ["audiobook", "narration", "clear", "nonfiction"],
                    },
                    {
                        "voice_id": "voice-warm",
                        "label": "Warm narrator",
                        "language": "en-US",
                        "tags": ["audiobook", "narration", "warm", "memoir"],
                    },
                    {
                        "voice_id": "voice-story",
                        "label": "Story narrator",
                        "language": "en-US",
                        "tags": ["audiobook", "narration", "fiction", "dialogue"],
                    },
                ]
            ),
        }

        original_synthesize = processor.audiobook_epub_pipeline.unmixr_synthesize_request
        original_normalize = processor.audiobook_epub_pipeline._normalize_rendered_audio_file
        original_gate = processor.audiobook_epub_pipeline._build_audiobook_publication_gate
        original_share = processor.audiobook_epub_pipeline._create_or_reuse_audiobookshelf_public_share
        player_probe: dict[str, object] = {"status": "not_run"}
        player_http_probe: dict[str, object] = {"status": "not_run"}

        def _local_publication_gate(*, job: dict[str, object], target_path: Path) -> dict[str, object]:
            return {
                "contract_name": "ea.audiobook_publication_audio_gate.v1",
                "checked_at": _now_iso(),
                "status": "pass",
                "issues": [],
                "target_file_sha256": processor.audiobook_epub_pipeline._sha256_file(target_path)
                if target_path.is_file()
                else "",
                "target_file_size": int(target_path.stat().st_size) if target_path.is_file() else 0,
                "audio_streams": 1,
                "cover_streams": 0,
                "chapters": int(dict(job.get("totals") or {}).get("chapter_count") or 0),
                "raw_paths_exposed": False,
                "local_proof_gate": True,
            }

        def _local_public_share(**_: object) -> dict[str, object]:
            return {
                "status": "public_share_ready",
                "source": "local_whatsapp_audiobook_proof",
                "slug_sha256": processor.audiobook_epub_pipeline._sha256_bytes(b"local-whatsapp-proof-share"),
                "absolute_url": "https://abs-local-proof.invalid/share/whatsapp-proof-book",
                "expires_at": "",
                "is_downloadable": False,
                "token_exposed": False,
                "raw_library_path_exposed": False,
            }

        try:
            processor.audiobook_epub_pipeline.unmixr_synthesize_request = lambda **_: (_tone_wav_bytes(), "audio/wav")
            processor.audiobook_epub_pipeline._normalize_rendered_audio_file = lambda path: path
            processor.audiobook_epub_pipeline._build_audiobook_publication_gate = _local_publication_gate
            processor.audiobook_epub_pipeline._create_or_reuse_audiobookshelf_public_share = _local_public_share
            with _temporary_env(env):
                intake_report = processor.build_report(
                    _build_args(tmp_root=tmp_root),
                    request_json=request_json,
                    request_bytes=lambda **_: source_epub.read_bytes(),
                )
                manifests = [path for path in jobs_root.glob("*/job.json") if path.parent.name != "_incoming_whatsapp"]
                intake_job = json.loads(manifests[0].read_text(encoding="utf-8")) if manifests else {}
                intake_job_dir = Path(str(intake_job.get("storage", {}).get("job_dir") or "")) if intake_job else Path()
                intake_job_receipt = (
                    processor.audiobook_epub_pipeline.build_audiobook_job_receipt(job_dir=intake_job_dir)
                    if intake_job_dir and intake_job_dir.is_dir()
                    else {}
                )
                live_receipt = _load_live_receipt_module()
                intake_stage_receipt = live_receipt.build_receipt(
                    output_path=tmp_root / "local-intake-stage.generated.json",
                    job_receipts=[intake_job_receipt] if intake_job_receipt else [],
                    generated_at=generated_at,
                    observation_source="local_whatsapp_epub_intake_proof",
                )
                use_callback = _first_use_callback(requests)
                inbound_messages[:] = [
                    {
                        "direction": "inbound",
                        "from_me": False,
                        "id": "wamid.local-proof.voice-choice.1",
                        "media_present": False,
                        "selected_button_id_present": True,
                        "selected_button_kind": "audiobook_voice",
                        "selected_button_id": use_callback,
                        "sender_digits": "4368120864006",
                    }
                ]
                selection_report = processor.build_report(
                    _build_args(tmp_root=tmp_root),
                    request_json=request_json,
                    request_bytes=lambda **_: source_epub.read_bytes(),
                )
                final_job_paths = [path for path in jobs_root.glob("*/job.json") if path.parent.name != "_incoming_whatsapp"]
                final_job = json.loads(final_job_paths[0].read_text(encoding="utf-8")) if final_job_paths else {}
                final_import = dict(final_job.get("audiobookshelf_import") or {})
                player_reference = dict(final_import.get("player_scoped_reference") or {})
                player_probe = _probe_resolved_player_audio(
                    processor,
                    token=_player_token_from_reference(player_reference),
                )
                player_http_probe = _probe_http_player_route(token=_player_token_from_reference(player_reference))
        finally:
            processor.audiobook_epub_pipeline.unmixr_synthesize_request = original_synthesize
            processor.audiobook_epub_pipeline._normalize_rendered_audio_file = original_normalize
            processor.audiobook_epub_pipeline._build_audiobook_publication_gate = original_gate
            processor.audiobook_epub_pipeline._create_or_reuse_audiobookshelf_public_share = original_share

        manifests = [path for path in jobs_root.glob("*/job.json") if path.parent.name != "_incoming_whatsapp"]
        job = json.loads(manifests[0].read_text(encoding="utf-8")) if manifests else {}
        job_dir = Path(str(job.get("storage", {}).get("job_dir") or "")) if job else Path()
        job_receipt = (
            processor.audiobook_epub_pipeline.build_audiobook_job_receipt(job_dir=job_dir)
            if job_dir and job_dir.is_dir()
            else {}
        )

        final_stage_receipt = live_receipt.build_receipt(
            output_path=tmp_root / "local-delivery-stage.generated.json",
            job_receipts=[job_receipt] if job_receipt else [],
            generated_at=generated_at,
            observation_source="local_whatsapp_voice_selection_and_share_proof",
        )
        provider = dict(job.get("provider") or {})
        voice_selection = dict(provider.get("voice_selection") or {})
        whatsapp = dict(job.get("whatsapp") or {})
        import_result = dict(job.get("audiobookshelf_import") or {})
        public_share = dict(import_result.get("public_share") or {})
        receipt_whatsapp = dict(job_receipt.get("whatsapp") or {})
        receipt_metadata = dict(job_receipt.get("metadata") or {})
        receipt_import = dict(job_receipt.get("audiobookshelf_import") or {})
        receipt_assembly = dict(job_receipt.get("assembly") or {})

        checks = {
            "intake_processor_passed": str(intake_report.get("status") or "") == "pass",
            "voice_selection_processor_passed": str(selection_report.get("status") or "") == "pass",
            "epub_processed_once": int(intake_report.get("epub_processed") or 0) == 1,
            "three_voice_samples_sent": int(intake_report.get("voice_sample_sent") or 0) == 3,
            "job_created": len(manifests) == 1,
            "intake_job_waiting_for_voice_choice": str(intake_job.get("status") or "") == "waiting_voice_selection",
            "use_callback_captured": bool(use_callback),
            "voice_choice_callback_processed": int(selection_report.get("processed") or 0) == 1,
            "voice_selected_by_user": str(voice_selection.get("status") or "") == "selected_by_user",
            "chapter_audio_rendered": str(dict(job.get("render_result") or {}).get("status") or "") in {
                "rendered",
                "already_rendered",
            },
            "m4b_ready": str(dict(job.get("merge_result") or {}).get("status") or "") == "m4b_ready",
            "audiobookshelf_imported": str(import_result.get("status") or "") == "imported",
            "player_scoped_reference_ready": str(dict(import_result.get("player_scoped_reference") or {}).get("status") or "")
            == "signed_reference_ready",
            "player_scoped_reference_resolves": str(player_probe.get("metadata_status") or "") == "ready",
            "player_scoped_audio_probe_passed": str(player_probe.get("status") or "") == "pass",
            "player_http_metadata_ready": str(player_http_probe.get("metadata_status") or "") == "ready",
            "player_http_audio_download_works": str(player_http_probe.get("status") or "") == "pass",
            "public_share_ready": str(public_share.get("status") or "") == "public_share_ready",
            "whatsapp_public_share_sent": str(receipt_import.get("public_share_whatsapp_delivery_status") or "") == "sent",
            "chapters_extracted": int(dict(job.get("totals") or {}).get("chapter_count") or 0) == 2,
            "whatsapp_sender_bound": bool(receipt_whatsapp.get("sender_bound")),
            "whatsapp_session_bound": bool(receipt_whatsapp.get("session_bound")),
            "whatsapp_message_hash_present": bool(receipt_whatsapp.get("message_hash_present")),
            "receipt_voice_delivery_sent": str(receipt_whatsapp.get("voice_sample_delivery_status") or "") == "sent",
            "intake_stage_waits_for_voice_choice": str(intake_stage_receipt.get("next_action") or "")
            == "choose_whatsapp_audiobook_voice_sample",
            "local_delivery_tracks_machine_playback_gap": int(
                dict(dict(final_stage_receipt.get("stage_summary") or {}).get("counts") or {}).get(
                    "waiting_machine_playback_verification"
                )
                or 0
            )
            == 1,
        }
        status = "pass" if all(checks.values()) else "fail"
        proof = {
            "contract_name": CONTRACT_NAME,
            "generated_at": generated_at,
            "generated_by": "ea/scripts/materialize_whatsapp_audiobook_local_intake_proof.py",
            "status": status,
            "claim": (
                "A local generated EPUB can pass through the WhatsApp action processor into the audiobook pipeline, "
                "create a WhatsApp-bound job, send three voice samples, accept a WhatsApp Use voice callback, "
                "render/import the audiobook, and send the Audiobookshelf public share link through WhatsApp. "
                "This is not a live WhatsApp delivery claim."
            ),
            "checks": checks,
            "processor_report": {
                "intake": {
                    "status": str(intake_report.get("status") or ""),
                    "message_count": int(intake_report.get("message_count") or 0),
                    "epub_candidate_count": int(intake_report.get("epub_candidate_count") or 0),
                    "epub_processed": int(intake_report.get("epub_processed") or 0),
                    "voice_sample_sent": int(intake_report.get("voice_sample_sent") or 0),
                    "reply_sent": int(intake_report.get("reply_sent") or 0),
                    "errors": int(intake_report.get("errors") or 0),
                },
                "voice_selection": {
                    "status": str(selection_report.get("status") or ""),
                    "candidate_count": int(selection_report.get("candidate_count") or 0),
                    "processed": int(selection_report.get("processed") or 0),
                    "share_link_sent": int(selection_report.get("share_link_sent") or 0),
                    "reply_sent": int(selection_report.get("reply_sent") or 0),
                    "errors": int(selection_report.get("errors") or 0),
                },
            },
            "intake_summary": {
                "status": str(intake_job.get("status") or ""),
                "voice_selection_status": str(
                    dict(dict(intake_job.get("provider") or {}).get("voice_selection") or {}).get("status") or ""
                ),
                "pending_voice_sample_count": len(
                    [
                        row
                        for row in list(
                            dict(dict(intake_job.get("provider") or {}).get("voice_selection") or {}).get("pending_batch")
                            or []
                        )
                        if isinstance(row, dict)
                    ]
                ),
                "stage_next_action": str(intake_stage_receipt.get("next_action") or ""),
            },
            "job_summary": {
                "status": str(job.get("status") or ""),
                "chapter_count": int(dict(job.get("totals") or {}).get("chapter_count") or 0),
                "voice_selection_status": str(voice_selection.get("status") or ""),
                "pending_voice_sample_count": len(
                    [row for row in list(voice_selection.get("pending_batch") or []) if isinstance(row, dict)]
                ),
                "whatsapp_source": str(whatsapp.get("source") or ""),
                "render_status": str(dict(job.get("render_result") or {}).get("status") or ""),
                "m4b_status": str(dict(job.get("merge_result") or {}).get("status") or ""),
                "audiobookshelf_import_status": str(import_result.get("status") or ""),
                "public_share_status": str(public_share.get("status") or ""),
            },
            "sanitized_receipt_summary": {
                "contract_name": str(job_receipt.get("contract_name") or ""),
                "status": str(job_receipt.get("status") or ""),
                "title_sha256": str(receipt_metadata.get("title_sha256") or ""),
                "author_sha256": str(receipt_metadata.get("author_sha256") or ""),
                "m4b_output_ready": bool(receipt_assembly.get("output_file_ready")),
                "chapter_metadata_embedded": bool(receipt_assembly.get("chapter_metadata_embedded")),
                "audiobookshelf_import_status": str(receipt_import.get("status") or ""),
                "player_scoped_reference_status": str(receipt_import.get("player_scoped_reference_status") or ""),
                "public_share_status": str(receipt_import.get("public_share_status") or ""),
                "public_share_whatsapp_delivery_status": str(
                    receipt_import.get("public_share_whatsapp_delivery_status") or ""
                ),
                "public_share_whatsapp_message_id_present": bool(
                    receipt_import.get("public_share_whatsapp_message_id_present")
                ),
                "whatsapp_sender_bound": bool(receipt_whatsapp.get("sender_bound")),
                "whatsapp_session_bound": bool(receipt_whatsapp.get("session_bound")),
                "whatsapp_message_hash_present": bool(receipt_whatsapp.get("message_hash_present")),
                "whatsapp_voice_sample_delivery_status": str(receipt_whatsapp.get("voice_sample_delivery_status") or ""),
                "whatsapp_voice_sample_delivery_sent_count": int(receipt_whatsapp.get("voice_sample_delivery_sent_count") or 0),
            },
            "player_probe_summary": {
                "status": str(player_probe.get("status") or ""),
                "metadata_status": str(player_probe.get("metadata_status") or ""),
                "content_type": str(player_probe.get("content_type") or ""),
                "file_ready": bool(player_probe.get("file_ready")),
                "file_sha256": str(player_probe.get("file_sha256") or ""),
                "audio_streams": int(player_probe.get("audio_streams") or 0),
                "chapter_count": int(player_probe.get("chapter_count") or 0),
                "duration_seconds": float(player_probe.get("duration_seconds") or 0.0),
                "raw_path_exposed": False,
                "raw_token_exposed": False,
            },
            "player_http_probe_summary": {
                "status": str(player_http_probe.get("status") or ""),
                "metadata_status_code": int(player_http_probe.get("metadata_status_code") or 0),
                "metadata_status": str(player_http_probe.get("metadata_status") or ""),
                "metadata_cache_control": str(player_http_probe.get("metadata_cache_control") or ""),
                "metadata_download_url_present": bool(player_http_probe.get("metadata_download_url_present")),
                "metadata_vendor_token_exposed": bool(player_http_probe.get("metadata_vendor_token_exposed")),
                "metadata_raw_library_path_exposed": bool(player_http_probe.get("metadata_raw_library_path_exposed")),
                "download_status_code": int(player_http_probe.get("download_status_code") or 0),
                "download_content_type": str(player_http_probe.get("download_content_type") or ""),
                "download_cache_control": str(player_http_probe.get("download_cache_control") or ""),
                "download_bytes": int(player_http_probe.get("download_bytes") or 0),
                "raw_path_exposed": False,
                "raw_token_exposed": False,
            },
            "local_stage_receipt_summary": {
                "intake": {
                    "status": str(intake_stage_receipt.get("status") or ""),
                    "live_delivery_claim_allowed": bool(intake_stage_receipt.get("live_delivery_claim_allowed")),
                    "next_action": str(intake_stage_receipt.get("next_action") or ""),
                    "stage_counts": dict(dict(intake_stage_receipt.get("stage_summary") or {}).get("counts") or {}),
                },
                "delivery": {
                    "status": str(final_stage_receipt.get("status") or ""),
                    "live_delivery_claim_allowed": bool(final_stage_receipt.get("live_delivery_claim_allowed")),
                    "next_action": str(final_stage_receipt.get("next_action") or ""),
                    "stage_counts": dict(dict(final_stage_receipt.get("stage_summary") or {}).get("counts") or {}),
                },
            },
            "privacy": {
                "live_whatsapp_claim": False,
                "raw_epub_text_persisted": False,
                "raw_sender_ref_exposed": False,
                "raw_message_id_exposed": False,
                "callback_tokens_exposed": False,
                "public_share_token_exposed": False,
                "player_access_token_exposed": False,
                "audiobookshelf_raw_path_exposed": False,
                "provider_voice_ids_exposed": False,
                "provider_secret_exposed": False,
                "local_temp_job_root_removed_after_run": True,
            },
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {**proof, "receipt_path": output_path.as_posix()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args()
    result = materialize_whatsapp_audiobook_local_intake_proof(output_path=args.output)
    print(json.dumps(result, sort_keys=True))
    if args.require_pass and result["status"] != "pass":
        return 2
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
