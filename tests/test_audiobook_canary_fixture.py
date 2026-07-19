from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "materialize_audiobook_canary_fixture.py"


def _module():
    spec = importlib.util.spec_from_file_location(
        "materialize_audiobook_canary_fixture",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("language,language_tag", (("en", "en-US"), ("de", "de-AT")))
def test_canary_fixture_epub_bytes_are_reproducible_and_portably_bound(
    tmp_path: Path,
    language: str,
    language_tag: str,
) -> None:
    materializer = _module()
    first_epub = tmp_path / "first" / "canary.epub"
    second_epub = tmp_path / "second" / "canary.epub"

    first = materializer.materialize_fixture(language=language, epub_path=first_epub)
    second = materializer.materialize_fixture(language=language, epub_path=second_epub)

    first_bytes = first_epub.read_bytes()
    assert first_bytes == second_epub.read_bytes()
    assert first == second
    assert first["contract_name"] == "ea.audiobook_live_canary_fixture.v1"
    assert first["language_tag"] == language_tag
    assert first["chapter_count"] == 2
    assert first["expected_dialogue_turn_count"] >= 2
    assert first["expected_recurring_speaker_labels"] == ["Anna", "Ben"]
    assert first["rights"] == {
        "dc_rights": materializer.RIGHTS_TEXT,
        "spdx_license_expression": "CC0-1.0",
        "basis": "original_synthetic_repository_canary_text",
        "third_party_book_text_included": False,
    }
    assert first["epub"]["sha256"] == hashlib.sha256(first_bytes).hexdigest()
    assert first["epub"]["size_bytes"] == len(first_bytes)
    manifest_without_digest = dict(first)
    manifest_sha256 = manifest_without_digest.pop("manifest_sha256")
    assert manifest_sha256 == hashlib.sha256(
        json.dumps(
            manifest_without_digest,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    assert "/tmp/" not in json.dumps(first, sort_keys=True)
    assert first["side_effects"] == {
        "provider_called": False,
        "uploaded": False,
        "channel_message_sent": False,
    }

    with zipfile.ZipFile(first_epub) as archive:
        infos = archive.infolist()
        assert [row.filename for row in infos] == first["epub"]["zip_entry_order"]
        assert infos[0].filename == "mimetype"
        assert archive.read("mimetype") == b"application/epub+zip"
        assert all(row.compress_type == zipfile.ZIP_STORED for row in infos)
        assert all(row.date_time == materializer.FIXED_ZIP_TIMESTAMP for row in infos)
        opf = archive.read("OEBPS/content.opf").decode("utf-8")
        assert f"<dc:rights>{materializer.RIGHTS_TEXT}</dc:rights>" in opf

    assert stat.S_IMODE(first_epub.stat().st_mode) == 0o600
    assert stat.S_IMODE(first_epub.with_suffix(".epub.manifest.json").stat().st_mode) == 0o600


@pytest.mark.parametrize("language", ("en", "de"))
def test_canary_fixture_extracts_and_v5_planner_reconstructs_exact_source(
    tmp_path: Path,
    language: str,
) -> None:
    materializer = _module()
    epub_path = tmp_path / f"canary-{language}.epub"
    manifest = materializer.materialize_fixture(language=language, epub_path=epub_path)

    from app.services.audiobook_epub_pipeline import extract_epub_chapters
    from app.services.audiobook_narration_planner import (
        PLANNER_CONTRACT_NAME,
        PlannerChapter,
        plan_narration,
    )

    chapter_dir = tmp_path / "extracted" / language
    metadata, chapters = extract_epub_chapters(
        epub_path=epub_path,
        chapter_dir=chapter_dir,
        source_filename=epub_path.name,
    )
    assert metadata.language == manifest["language_tag"]
    assert metadata.source_sha256 == manifest["epub"]["sha256"]
    assert len(chapters) == manifest["chapter_count"] == 2

    expected_rows = manifest["chapters"]
    planner_chapters = []
    for chapter, expected in zip(chapters, expected_rows, strict=True):
        extracted_text = (chapter_dir / chapter.text_path).read_text(encoding="utf-8").rstrip("\n")
        assert chapter.source_href == expected["source_href"]
        assert extracted_text == expected["canonical_expected_text"]
        assert chapter.sha256 == expected["canonical_expected_text_sha256"]
        planner_chapters.append(
            PlannerChapter(
                index=chapter.index,
                source_href=chapter.source_href,
                text=extracted_text,
                expected_sha256=chapter.sha256,
            )
        )

    plan = plan_narration(
        tuple(planner_chapters),
        language=metadata.language,
        max_chars=1800,
    )
    assert plan["contract_name"] == PLANNER_CONTRACT_NAME
    assert plan["version"] == 5
    assert plan["status"] == "ready"
    assert plan["source_coverage"] == "complete"
    assert plan["coverage_complete"] is True
    assert plan["source_integrity_verified"] is True
    assert plan["source_integrity_issues"] == []
    assert plan["dialogue_span_count"] == manifest["expected_dialogue_turn_count"]
    assert plan["attributed_dialogue_span_count"] == manifest["expected_dialogue_turn_count"]
    assert plan["uncertain_dialogue_span_count"] == 0

    for chapter, expected in zip(chapters, expected_rows, strict=True):
        reconstructed = "".join(
            str(span["source_text"])
            for span in plan["spans"]
            if span["source_chapter_index"] == chapter.index
        )
        assert reconstructed == expected["canonical_expected_text"]

    dialogue = [span for span in plan["spans"] if span["kind"] == "dialogue"]
    assert {str(span["speaker_label"]) for span in dialogue} == {"Anna", "Ben"}
    for label in ("Anna", "Ben"):
        rows = [span for span in dialogue if span["speaker_label"] == label]
        assert {int(span["source_chapter_index"]) for span in rows} == {1, 2}
        assert len({str(span["speaker_id"]) for span in rows}) == 1


def test_canary_fixture_refuses_existing_or_symlink_outputs_without_side_effects(
    tmp_path: Path,
) -> None:
    materializer = _module()
    existing = tmp_path / "existing.epub"
    existing.write_bytes(b"keep-me")
    manifest = existing.with_suffix(".epub.manifest.json")

    with pytest.raises(FileExistsError, match="output_exists_use_replace"):
        materializer.materialize_fixture(language="en", epub_path=existing)
    assert existing.read_bytes() == b"keep-me"
    assert not manifest.exists()

    target = tmp_path / "real.epub"
    target.write_bytes(b"real")
    symlink = tmp_path / "symlink.epub"
    os.symlink(target, symlink)
    with pytest.raises(RuntimeError, match="output_symlink_not_allowed"):
        materializer.materialize_fixture(language="de", epub_path=symlink)
    assert target.read_bytes() == b"real"
    assert not symlink.with_suffix(".epub.manifest.json").exists()

    manifest_target = tmp_path / "real-manifest.json"
    manifest_target.write_text("keep-manifest", encoding="utf-8")
    manifest_symlink = tmp_path / "manifest-link.json"
    os.symlink(manifest_target, manifest_symlink)
    fresh_epub = tmp_path / "fresh.epub"
    with pytest.raises(RuntimeError, match="output_symlink_not_allowed"):
        materializer.materialize_fixture(
            language="en",
            epub_path=fresh_epub,
            manifest_path=manifest_symlink,
        )
    assert not fresh_epub.exists()
    assert manifest_target.read_text(encoding="utf-8") == "keep-manifest"

    replacement = materializer.materialize_fixture(
        language="en",
        epub_path=existing,
        replace=True,
    )
    assert existing.read_bytes() != b"keep-me"
    assert replacement["epub"]["sha256"] == hashlib.sha256(existing.read_bytes()).hexdigest()
