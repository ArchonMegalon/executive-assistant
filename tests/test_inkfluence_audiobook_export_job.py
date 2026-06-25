from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import wave
import math
import struct


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "materialize_inkfluence_audiobook_export_job.py"


def load_module():
    spec = importlib.util.spec_from_file_location("materialize_inkfluence_audiobook_export_job", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_tone_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 8000
    frame_count = int(sample_rate * 0.05)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        frames = bytearray()
        for index in range(frame_count):
            value = int(16000 * math.sin(2 * math.pi * 440 * index / sample_rate))
            frames.extend(struct.pack("<h", value))
        handle.writeframes(bytes(frames))


def _write_packet(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "provider-manuscript-draft.md"
    source.write_text("Rain made the clinic sign stutter.\n\nKestrel kept moving.", encoding="utf-8")
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"not-a-real-cover-but-a-stable-operator-export-fixture")
    packet = {
        "contractName": "chummer.origin_edition.inkfluence_audiobook_operator_bridge_packet.v1",
        "inputArtifacts": {
            "approvedManuscript": {"path": str(source), "sha256": _sha256_file(source)},
            "sharedCover": {"path": str(cover), "sha256": _sha256_file(cover)},
        },
        "outputRequirements": {"acceptedAudioProviders": ["Inkfluence"]},
    }
    packet_path = tmp_path / "operator-packet.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    return packet_path, source, cover


def _write_manifest(tmp_path: Path, *, packet_path: Path, source: Path, cover: Path, audio: Path | None = None, provider: str = "Inkfluence") -> Path:
    manifest = {
        "provider": provider,
        "operatorPacketPath": str(packet_path),
        "title": "Kestrel - Origin Story",
        "author": "Chummer Origin Dossier",
        "language": "en-US",
        "principalId": "player-1",
        "playerId": "player-1",
        "runnerId": "runner-1",
        "sourceTextPath": str(source),
        "sourceTextSha256": _sha256_file(source),
        "coverPath": str(cover),
        "coverSha256": _sha256_file(cover),
        "chapterTitle": "Origin Story",
        "audioExports": [],
    }
    if audio is not None:
        manifest["audioExports"].append({"path": str(audio), "sha256": _sha256_file(audio)})
    manifest_path = tmp_path / "inkfluence-export-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def test_inkfluence_export_import_blocks_missing_audio(monkeypatch, tmp_path: Path) -> None:
    module = load_module()
    packet_path, source, cover = _write_packet(tmp_path)
    manifest_path = _write_manifest(tmp_path, packet_path=packet_path, source=source, cover=cover)
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))

    receipt = module.materialize(manifest_path=manifest_path, packet_path=packet_path)

    assert receipt["status"] == "blocked"
    assert receipt["reason"] == "inkfluence_audio_exports_missing"
    assert receipt["shareCreated"] is False
    assert receipt["rawCredentialExposed"] is False
    assert not (tmp_path / "jobs").exists()


def test_inkfluence_export_import_rejects_wrong_provider(monkeypatch, tmp_path: Path) -> None:
    module = load_module()
    packet_path, source, cover = _write_packet(tmp_path)
    audio = tmp_path / "chapter-1.wav"
    _write_tone_wav(audio)
    manifest_path = _write_manifest(tmp_path, packet_path=packet_path, source=source, cover=cover, audio=audio, provider="Unmixr")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))

    receipt = module.materialize(manifest_path=manifest_path, packet_path=packet_path)

    assert receipt["status"] == "blocked"
    assert receipt["reason"] == "audio_provider_not_accepted"


def test_inkfluence_export_import_rejects_source_hash_mismatch(monkeypatch, tmp_path: Path) -> None:
    module = load_module()
    packet_path, source, cover = _write_packet(tmp_path)
    audio = tmp_path / "chapter-1.wav"
    _write_tone_wav(audio)
    manifest_path = _write_manifest(tmp_path, packet_path=packet_path, source=source, cover=cover, audio=audio)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sourceTextSha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))

    receipt = module.materialize(manifest_path=manifest_path, packet_path=packet_path)

    assert receipt["status"] == "blocked"
    assert receipt["reason"] == "source_text_hash_mismatch"


def test_inkfluence_export_import_copies_audio_and_hands_off_to_pipeline(monkeypatch, tmp_path: Path) -> None:
    module = load_module()
    packet_path, source, cover = _write_packet(tmp_path)
    audio = tmp_path / "inkfluence-chapter-1.wav"
    _write_tone_wav(audio)
    manifest_path = _write_manifest(tmp_path, packet_path=packet_path, source=source, cover=cover, audio=audio)
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    observed: dict[str, object] = {}

    def fake_continue(job_dir: Path) -> dict[str, object]:
        job = module.pipeline._load_job(job_dir)
        audio_dir = Path(job["storage"]["audio_dir"])
        audio_files = sorted(audio_dir.glob("*.wav"))
        observed["audio_files"] = [path.name for path in audio_files]
        observed["cover"] = job["metadata"]["cover_image_path"]
        observed["provider"] = job["provider"]["preferred"]
        return {
            **job,
            "status": "audiobookshelf_imported",
            "merge_result": {"status": "m4b_ready"},
            "audiobookshelf_import": {
                "status": "imported",
                "public_share": {"status": "public_share_ready", "share_url": "https://audiobookshelf.example/share/abc"},
            },
        }

    receipt = module.materialize(manifest_path=manifest_path, packet_path=packet_path, continue_job_func=fake_continue)

    assert receipt["status"] == "audiobookshelf_imported"
    assert receipt["goldEligible"] is True
    assert receipt["copiedAudioExportCount"] == 1
    assert observed["audio_files"] == ["001 - Origin Story.wav"]
    assert Path(str(observed["cover"])).is_file()
    assert observed["provider"] == "inkfluence_manual_export"
