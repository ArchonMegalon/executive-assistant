#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Callable, Iterator


ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))

from app.services import audiobook_epub_pipeline as pipeline  # noqa: E402


CONTRACT_NAME = "ea.inkfluence_audiobook_export_import.v1"
PACKET_CONTRACT_NAME = "chummer.origin_edition.inkfluence_audiobook_operator_bridge_packet.v1"
ACCEPTED_AUDIO_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg", ".aiff", ".m4a"}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"json_load_failed:{path}:{exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"json_object_required:{path}")
    return payload


def _as_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _fail_receipt(reason: str, *, issues: list[str] | None = None) -> dict[str, Any]:
    return {
        "contractName": CONTRACT_NAME,
        "status": "blocked",
        "reason": reason,
        "issues": issues or [reason],
        "goldEligible": False,
        "shareCreated": False,
        "rawCredentialExposed": False,
        "rawProviderTokenExposed": False,
        "createdAtUtc": _now_iso(),
    }


def _artifact_from_packet(packet: dict[str, Any], key: str) -> tuple[Path, str]:
    artifacts = _as_dict(packet.get("inputArtifacts"))
    artifact = _as_dict(artifacts.get(key))
    path = Path(str(artifact.get("path") or "").strip())
    sha = str(artifact.get("sha256") or "").strip()
    if not path.is_file():
        raise RuntimeError(f"packet_artifact_missing:{key}")
    actual = _sha256_file(path)
    if sha and actual != sha:
        raise RuntimeError(f"packet_artifact_hash_mismatch:{key}")
    return path, actual


def _manifest_path(manifest: dict[str, Any], key: str, fallback: Path | None = None) -> Path:
    raw = str(manifest.get(key) or "").strip()
    return Path(raw) if raw else (fallback or Path())


def _provider_allowed(packet: dict[str, Any], provider: str) -> bool:
    accepted = {
        str(item).strip().lower()
        for item in _as_list(_as_dict(packet.get("outputRequirements")).get("acceptedAudioProviders"))
        if str(item).strip()
    }
    return provider.strip().lower() in accepted


def _chapter_rows(manifest: dict[str, Any], source_text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for index, raw in enumerate(_as_list(manifest.get("textChapters")), start=1):
        item = _as_dict(raw)
        title = str(item.get("title") or f"Chapter {index}").strip() or f"Chapter {index}"
        text = str(item.get("text") or "").strip()
        text_path = Path(str(item.get("textPath") or "").strip())
        if not text and text_path.is_file():
            text = text_path.read_text(encoding="utf-8").strip()
        if text:
            rows.append({"title": title, "text": text})
    if rows:
        return rows
    title = str(manifest.get("chapterTitle") or manifest.get("title") or "Origin Story").strip() or "Origin Story"
    return [{"title": title, "text": source_text.strip()}]


@contextmanager
def _temporary_env(values: dict[str, str]) -> Iterator[None]:
    previous: dict[str, str | None] = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _build_job_without_render(
    *,
    manifest: dict[str, Any],
    packet: dict[str, Any],
    source_text: str,
    source_text_sha: str,
    source_text_path: Path,
    cover_path: Path,
    cover_sha: str,
) -> tuple[Path, dict[str, Any]]:
    root = pipeline.audiobook_jobs_root()
    pipeline._require_audiobook_storage_root(root)
    job_id = f"inkfluence-origin-audiobook-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{os.urandom(4).hex()}"
    job_dir = root / job_id
    chapter_dir = job_dir / "chapters"
    source_dir = job_dir / "source"
    asset_dir = job_dir / "assets"
    chapter_dir.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(parents=True, exist_ok=True)
    asset_dir.mkdir(parents=True, exist_ok=True)

    stored_source = source_dir / pipeline._safe_filename(source_text_path.name or "origin-story.txt", fallback="origin-story", suffix=".txt")
    stored_source.write_text(source_text.rstrip() + "\n", encoding="utf-8")
    cover_target = asset_dir / f"cover{cover_path.suffix.lower() if cover_path.suffix else '.jpg'}"
    shutil.copy2(cover_path, cover_target)
    if _sha256_file(cover_target) != cover_sha:
        raise RuntimeError("cover_copy_hash_mismatch")

    chapters: list[pipeline.EpubChapter] = []
    for index, row in enumerate(_chapter_rows(manifest, source_text), start=1):
        safe_title = pipeline._safe_filename(row["title"], fallback=f"Chapter {index:03d}")
        text_filename = f"{index:03d} - {safe_title}.txt"
        audio_filename = f"{index:03d} - {safe_title}.wav"
        chapter_text = row["text"].strip()
        (chapter_dir / text_filename).write_text(chapter_text + "\n", encoding="utf-8")
        chapters.append(
            pipeline.EpubChapter(
                index=index,
                title=row["title"],
                source_href=f"inkfluence_manual_export:{source_text_sha}:{index}",
                text_path=text_filename,
                audio_filename=audio_filename,
                char_count=len(chapter_text),
                sha256=_sha256_bytes(chapter_text.encode("utf-8")),
            )
        )

    metadata = pipeline.EpubMetadata(
        title=str(manifest.get("title") or "Kestrel - Origin Story").strip() or "Kestrel - Origin Story",
        author=str(manifest.get("author") or "Chummer Origin Dossier").strip() or "Chummer Origin Dossier",
        language=str(manifest.get("language") or "en-US").strip() or "en-US",
        source_filename=stored_source.name,
        source_sha256=source_text_sha,
        cover_image_path=str(cover_target),
        cover_media_type="image/png" if cover_target.suffix.lower() == ".png" else "image/jpeg",
    )
    with _temporary_env({"EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED": "0", "EA_AUDIOBOOK_UNMIXR_AUTO_RENDER": "0"}):
        payload = pipeline._build_job_payload(
            job_id=job_id,
            job_dir=job_dir,
            metadata=metadata,
            chapters=tuple(chapters),
            principal_id=str(manifest.get("principalId") or manifest.get("playerId") or "operator").strip(),
            source={
                "kind": "origin_dossier_story",
                "source_ref": str(manifest.get("dossierId") or manifest.get("runnerId") or "").strip(),
                "source_filename": stored_source.name,
                "source_sha256": source_text_sha,
                "source_text": str(stored_source),
                "source_text_original": str(source_text_path),
                "rights_basis": "player_or_gm_approved_origin_story_inkfluence_export",
                "player_id": str(manifest.get("playerId") or "").strip(),
                "provider_packet_sha256": _sha256_bytes(json.dumps(packet, sort_keys=True).encode("utf-8")),
            },
            telegram={},
            runner_id=str(manifest.get("runnerId") or manifest.get("dossierId") or "").strip(),
        )
    provider_payload = _as_dict(payload.get("provider"))
    provider_payload.update(
        {
            "preferred": "inkfluence_manual_export",
            "manual_export_imported": True,
            "source_provider": "Inkfluence",
            "raw_book_text_leaves_ea": False,
            "direct_provider_publishing_allowed": False,
        }
    )
    payload["provider"] = provider_payload
    payload["inkfluence_export"] = {
        "status": "awaiting_audio_copy",
        "provider": "Inkfluence",
        "cover_sha256": cover_sha,
        "source_text_sha256": source_text_sha,
        "operator_packet_contract": str(packet.get("contractName") or ""),
        "raw_credentials_exposed": False,
        "raw_provider_tokens_exposed": False,
    }
    pipeline._write_job(job_dir, payload)
    return job_dir, payload


def _copy_audio_exports(*, manifest: dict[str, Any], job_dir: Path, job: dict[str, Any]) -> list[dict[str, Any]]:
    exports = _as_list(manifest.get("audioExports"))
    chapters = _as_list(job.get("chapters"))
    if not exports:
        raise RuntimeError("inkfluence_audio_exports_missing")
    if len(exports) != len(chapters):
        raise RuntimeError("inkfluence_audio_export_count_mismatch")
    audio_dir = job_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    copied: list[dict[str, Any]] = []
    for index, raw_export in enumerate(exports):
        export = _as_dict(raw_export)
        source = Path(str(export.get("path") or "").strip())
        if not source.is_file() or source.stat().st_size <= 0:
            raise RuntimeError(f"inkfluence_audio_export_missing:{index + 1}")
        if source.suffix.lower() not in ACCEPTED_AUDIO_SUFFIXES:
            raise RuntimeError(f"inkfluence_audio_export_suffix_rejected:{index + 1}")
        actual_sha = _sha256_file(source)
        expected_sha = str(export.get("sha256") or "").strip()
        if expected_sha and expected_sha != actual_sha:
            raise RuntimeError(f"inkfluence_audio_export_hash_mismatch:{index + 1}")
        chapter = _as_dict(chapters[index])
        expected_stem = (audio_dir / str(chapter.get("audio_filename") or f"{index + 1:03d} - Chapter.wav")).with_suffix("")
        target = expected_stem.with_suffix(source.suffix.lower())
        shutil.copy2(source, target)
        copied.append(
            {
                "chapterIndex": index + 1,
                "chapterTitle": str(chapter.get("title") or ""),
                "targetFilename": target.name,
                "sourceSha256": actual_sha,
                "bytes": target.stat().st_size,
            }
        )
    return copied


def materialize(
    *,
    manifest_path: Path,
    packet_path: Path,
    continue_job_func: Callable[[Path], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    try:
        manifest = _load_json(manifest_path)
        packet = _load_json(packet_path)
        if str(packet.get("contractName") or "") != PACKET_CONTRACT_NAME:
            return _fail_receipt("operator_packet_contract_mismatch")
        provider = str(manifest.get("provider") or "").strip()
        if provider.lower() != "inkfluence" or not _provider_allowed(packet, provider):
            return _fail_receipt("audio_provider_not_accepted")

        packet_source_path, packet_source_sha = _artifact_from_packet(packet, "approvedManuscript")
        packet_cover_path, packet_cover_sha = _artifact_from_packet(packet, "sharedCover")
        source_path = _manifest_path(manifest, "sourceTextPath", packet_source_path)
        cover_path = _manifest_path(manifest, "coverPath", packet_cover_path)
        if source_path.resolve() != packet_source_path.resolve():
            return _fail_receipt("source_text_path_must_match_operator_packet")
        if cover_path.resolve() != packet_cover_path.resolve():
            return _fail_receipt("cover_path_must_match_operator_packet")
        source_sha = _sha256_file(source_path)
        cover_sha = _sha256_file(cover_path)
        if source_sha != packet_source_sha or str(manifest.get("sourceTextSha256") or source_sha).strip() != source_sha:
            return _fail_receipt("source_text_hash_mismatch")
        if cover_sha != packet_cover_sha or str(manifest.get("coverSha256") or cover_sha).strip() != cover_sha:
            return _fail_receipt("cover_hash_mismatch")

        source_text = source_path.read_text(encoding="utf-8").strip()
        if not source_text:
            return _fail_receipt("source_text_empty")
        audio_exports = _as_list(manifest.get("audioExports"))
        if not audio_exports:
            return _fail_receipt("inkfluence_audio_exports_missing")
        text_chapters = _chapter_rows(manifest, source_text)
        if len(audio_exports) != len(text_chapters):
            return _fail_receipt("inkfluence_audio_export_count_mismatch")
        job_dir, job = _build_job_without_render(
            manifest=manifest,
            packet=packet,
            source_text=source_text,
            source_text_sha=source_sha,
            source_text_path=source_path,
            cover_path=cover_path,
            cover_sha=cover_sha,
        )
        copied = _copy_audio_exports(manifest=manifest, job_dir=job_dir, job=job)
        job = pipeline._load_job(job_dir)
        job["inkfluence_export"] = {
            **_as_dict(job.get("inkfluence_export")),
            "status": "audio_copied",
            "copiedAudioExports": copied,
        }
        pipeline._write_job(job_dir, job)
        final_job = (continue_job_func or pipeline.continue_job)(job_dir)
        import_result = _as_dict(final_job.get("audiobookshelf_import"))
        public_share = _as_dict(import_result.get("public_share"))
        return {
            "contractName": CONTRACT_NAME,
            "status": str(final_job.get("status") or ""),
            "goldEligible": str(public_share.get("status") or "") == "public_share_ready",
            "jobId": str(final_job.get("job_id") or ""),
            "jobDir": str(job_dir),
            "provider": "Inkfluence",
            "sourceTextSha256": source_sha,
            "coverSha256": cover_sha,
            "copiedAudioExportCount": len(copied),
            "mergeStatus": str(_as_dict(final_job.get("merge_result")).get("status") or ""),
            "audiobookshelfImportStatus": str(import_result.get("status") or ""),
            "publicShareStatus": str(public_share.get("status") or ""),
            "shareCreated": str(public_share.get("status") or "") == "public_share_ready",
            "rawCredentialExposed": False,
            "rawProviderTokenExposed": False,
            "createdAtUtc": _now_iso(),
        }
    except Exception as exc:
        return _fail_receipt(str(exc))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import a verified Inkfluence audiobook export into the EA audiobook pipeline.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    receipt = materialize(manifest_path=args.manifest, packet_path=args.packet)
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt.get("status") not in {"blocked"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
