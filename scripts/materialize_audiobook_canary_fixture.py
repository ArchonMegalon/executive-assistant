#!/usr/bin/env python3
"""Materialize a deterministic, rights-safe EPUB for the live audiobook canary.

This command only writes fixture bytes and a portable manifest.  It never calls a
provider, uploads a document, or sends a channel message.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from typing import Final
from xml.sax.saxutils import escape
import zipfile


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_NAME: Final = "ea.audiobook_live_canary_fixture.v1"
FIXED_ZIP_TIMESTAMP: Final = (2026, 7, 19, 0, 0, 0)
MIMETYPE: Final = b"application/epub+zip"
RIGHTS_TEXT: Final = (
    "CC0-1.0; original synthetic canary text created for this repository; "
    "no third-party book text included."
)
FILE_MODE: Final = 0o600


@dataclass(frozen=True)
class CanaryChapter:
    title: str
    paragraphs: tuple[str, ...]
    expected_dialogue_turn_count: int

    @property
    def canonical_text(self) -> str:
        return "\n\n".join((self.title, *self.paragraphs))


@dataclass(frozen=True)
class CanaryFixture:
    language: str
    language_tag: str
    identifier: str
    title: str
    chapters: tuple[CanaryChapter, ...]


FIXTURES: Final[dict[str, CanaryFixture]] = {
    "en": CanaryFixture(
        language="en",
        language_tag="en-US",
        identifier="urn:ea:audiobook-live-canary:en:v1",
        title="The Lantern Test",
        chapters=(
            CanaryChapter(
                title="The Lantern",
                paragraphs=(
                    "Rain tapped the windows while the quiet room waited.",
                    "Anna said, “The lantern is ready.” “Then we can begin,” Ben replied.",
                ),
                expected_dialogue_turn_count=2,
            ),
            CanaryChapter(
                title="The First Page",
                paragraphs=(
                    "A calm pause joined one chapter to the next.",
                    "Ben asked, “Shall I open the book?” Anna replied, “Please do.”",
                ),
                expected_dialogue_turn_count=2,
            ),
        ),
    ),
    "de": CanaryFixture(
        language="de",
        language_tag="de-AT",
        identifier="urn:ea:audiobook-live-canary:de:v1",
        title="Der Laternentest",
        chapters=(
            CanaryChapter(
                title="Die Laterne",
                paragraphs=(
                    "Regen klopfte an die Fenster, während der ruhige Raum wartete.",
                    "„Die Laterne ist bereit“, sagte Anna. Ben antwortete: «Dann können wir beginnen.»",
                ),
                expected_dialogue_turn_count=2,
            ),
            CanaryChapter(
                title="Die erste Seite",
                paragraphs=(
                    "Eine ruhige Pause verband ein Kapitel mit dem nächsten.",
                    "„Soll ich das Buch öffnen?“, fragte Ben. Anna antwortete: «Bitte.»",
                ),
                expected_dialogue_turn_count=2,
            ),
        ),
    ),
}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _generator_source_revision() -> str:
    try:
        completed = subprocess.run(  # nosec B603,B607 - fixed git command
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    value = completed.stdout.strip().lower() if completed.returncode == 0 else ""
    if len(value) == 40 and all(character in "0123456789abcdef" for character in value):
        return value
    return ""


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(filename=name, date_time=FIXED_ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.flag_bits = 0
    info.extra = b""
    info.comment = b""
    return info


def _container_xml() -> bytes:
    return (
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
        "<container version=\"1.0\" "
        "xmlns=\"urn:oasis:names:tc:opendocument:xmlns:container\">\n"
        "  <rootfiles>\n"
        "    <rootfile full-path=\"OEBPS/content.opf\" "
        "media-type=\"application/oebps-package+xml\"/>\n"
        "  </rootfiles>\n"
        "</container>\n"
    ).encode("utf-8")


def _opf(fixture: CanaryFixture) -> bytes:
    manifest_rows = [
        '    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
    ]
    spine_rows: list[str] = []
    for index, _chapter in enumerate(fixture.chapters, start=1):
        manifest_rows.append(
            f'    <item id="chapter-{index}" href="chapters/chapter-{index}.xhtml" '
            'media-type="application/xhtml+xml"/>'
        )
        spine_rows.append(f'    <itemref idref="chapter-{index}"/>')
    payload = (
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
        "<package xmlns=\"http://www.idpf.org/2007/opf\" version=\"3.0\" "
        "unique-identifier=\"book-id\">\n"
        "  <metadata xmlns:dc=\"http://purl.org/dc/elements/1.1/\">\n"
        f"    <dc:identifier id=\"book-id\">{escape(fixture.identifier)}</dc:identifier>\n"
        f"    <dc:title>{escape(fixture.title)}</dc:title>\n"
        "    <dc:creator>EA Rights-Safe Canary Fixture</dc:creator>\n"
        f"    <dc:language>{escape(fixture.language_tag)}</dc:language>\n"
        f"    <dc:rights>{escape(RIGHTS_TEXT)}</dc:rights>\n"
        "    <meta property=\"dcterms:modified\">2026-07-19T00:00:00Z</meta>\n"
        "  </metadata>\n"
        "  <manifest>\n"
        + "\n".join(manifest_rows)
        + "\n  </manifest>\n"
        "  <spine>\n"
        + "\n".join(spine_rows)
        + "\n  </spine>\n"
        "</package>\n"
    )
    return payload.encode("utf-8")


def _nav(fixture: CanaryFixture) -> bytes:
    links = "\n".join(
        f'        <li><a href="chapters/chapter-{index}.xhtml">{escape(chapter.title)}</a></li>'
        for index, chapter in enumerate(fixture.chapters, start=1)
    )
    return (
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
        "<html xmlns=\"http://www.w3.org/1999/xhtml\" "
        "xmlns:epub=\"http://www.idpf.org/2007/ops\" "
        f"xml:lang=\"{escape(fixture.language_tag)}\">\n"
        "  <head><title>Contents</title></head>\n"
        "  <body>\n"
        "    <nav epub:type=\"toc\" id=\"toc\"><ol>\n"
        f"{links}\n"
        "    </ol></nav>\n"
        "  </body>\n"
        "</html>\n"
    ).encode("utf-8")


def _chapter_xhtml(fixture: CanaryFixture, chapter: CanaryChapter) -> bytes:
    paragraphs = "\n".join(
        f"    <p>{escape(paragraph)}</p>" for paragraph in chapter.paragraphs
    )
    return (
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
        "<html xmlns=\"http://www.w3.org/1999/xhtml\" "
        f"xml:lang=\"{escape(fixture.language_tag)}\">\n"
        f"  <head><title>{escape(chapter.title)}</title></head>\n"
        "  <body>\n"
        f"{paragraphs}\n"
        "  </body>\n"
        "</html>\n"
    ).encode("utf-8")


def build_epub_bytes(fixture: CanaryFixture) -> tuple[bytes, tuple[str, ...]]:
    entries: list[tuple[str, bytes]] = [
        ("mimetype", MIMETYPE),
        ("META-INF/container.xml", _container_xml()),
        ("OEBPS/content.opf", _opf(fixture)),
        ("OEBPS/nav.xhtml", _nav(fixture)),
    ]
    entries.extend(
        (
            f"OEBPS/chapters/chapter-{index}.xhtml",
            _chapter_xhtml(fixture, chapter),
        )
        for index, chapter in enumerate(fixture.chapters, start=1)
    )
    from io import BytesIO

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.comment = b""
        for name, payload in entries:
            archive.writestr(_zip_info(name), payload)
    return buffer.getvalue(), tuple(name for name, _payload in entries)


def build_manifest(
    *,
    fixture: CanaryFixture,
    epub_filename: str,
    epub_bytes: bytes,
    zip_entry_order: tuple[str, ...],
) -> dict[str, object]:
    script_path = Path(__file__).resolve()
    try:
        script_sha256 = _sha256_bytes(script_path.read_bytes())
    except OSError:
        script_sha256 = ""
    chapters = [
        {
            "index": index,
            "title": chapter.title,
            "source_href": f"OEBPS/chapters/chapter-{index}.xhtml",
            "canonical_expected_text": chapter.canonical_text,
            "canonical_expected_text_sha256": _sha256_bytes(
                chapter.canonical_text.encode("utf-8")
            ),
            "expected_dialogue_turn_count": chapter.expected_dialogue_turn_count,
            "expected_speaker_labels": ["Anna", "Ben"],
        }
        for index, chapter in enumerate(fixture.chapters, start=1)
    ]
    payload: dict[str, object] = {
        "contract_name": CONTRACT_NAME,
        "fixture_version": 1,
        "language": fixture.language,
        "language_tag": fixture.language_tag,
        "identifier": fixture.identifier,
        "title": fixture.title,
        "author": "EA Rights-Safe Canary Fixture",
        "rights": {
            "dc_rights": RIGHTS_TEXT,
            "spdx_license_expression": "CC0-1.0",
            "basis": "original_synthetic_repository_canary_text",
            "third_party_book_text_included": False,
        },
        "epub": {
            "filename": Path(epub_filename).name,
            "sha256": _sha256_bytes(epub_bytes),
            "size_bytes": len(epub_bytes),
            "mimetype_first": True,
            "mimetype_stored": True,
            "all_entries_stored": True,
            "fixed_zip_timestamp": list(FIXED_ZIP_TIMESTAMP),
            "zip_entry_order": list(zip_entry_order),
        },
        "chapter_count": len(chapters),
        "chapters": chapters,
        "canonical_expected_text_sha256": _sha256_bytes(
            "\n\n\n".join(chapter.canonical_text for chapter in fixture.chapters).encode(
                "utf-8"
            )
        ),
        "expected_dialogue_turn_count": sum(
            chapter.expected_dialogue_turn_count for chapter in fixture.chapters
        ),
        "expected_recurring_speaker_labels": ["Anna", "Ben"],
        "generator": {
            "path": "scripts/materialize_audiobook_canary_fixture.py",
            "source_revision": _generator_source_revision(),
            "source_revision_semantics": "git_head_if_available",
            "source_file_sha256": script_sha256,
        },
        "side_effects": {
            "provider_called": False,
            "uploaded": False,
            "channel_message_sent": False,
        },
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    payload["manifest_sha256"] = _sha256_bytes(canonical)
    return payload


def _assert_safe_target(path: Path, *, replace: bool) -> None:
    target = Path(path)
    for parent in (target.parent, *target.parent.parents):
        if parent.is_symlink():
            raise RuntimeError(f"output_parent_symlink_not_allowed:{target.name}")
    if target.is_symlink():
        raise RuntimeError(f"output_symlink_not_allowed:{target.name}")
    if target.exists():
        if not target.is_file():
            raise RuntimeError(f"output_not_regular_file:{target.name}")
        if not replace:
            raise FileExistsError(f"output_exists_use_replace:{target.name}")


def _stage_bytes(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temp_path = Path(raw_temp_path)
    try:
        os.fchmod(descriptor, FILE_MODE)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temp_path.unlink(missing_ok=True)
        raise
    return temp_path


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _commit_staged_file(
    *,
    staged_path: Path,
    output_path: Path,
    replace: bool,
) -> None:
    if replace:
        _assert_safe_target(output_path, replace=True)
        os.replace(staged_path, output_path)
    else:
        try:
            # The hard-link commit is atomic and fails if a target appears after
            # preflight.  Unlike os.replace, it can never silently overwrite.
            os.link(staged_path, output_path, follow_symlinks=False)
        except FileExistsError as exc:
            raise FileExistsError(
                f"output_exists_use_replace:{output_path.name}"
            ) from exc
        staged_path.unlink()
    os.chmod(output_path, FILE_MODE, follow_symlinks=False)
    _fsync_directory(output_path.parent)


def materialize_fixture(
    *,
    language: str,
    epub_path: Path,
    manifest_path: Path | None = None,
    replace: bool = False,
) -> dict[str, object]:
    normalized_language = str(language or "").strip().lower()
    try:
        fixture = FIXTURES[normalized_language]
    except KeyError as exc:
        raise ValueError("language_must_be_en_or_de") from exc
    output_epub = Path(epub_path)
    output_manifest = Path(manifest_path) if manifest_path else output_epub.with_suffix(
        output_epub.suffix + ".manifest.json"
    )
    if output_epub.absolute() == output_manifest.absolute():
        raise ValueError("epub_and_manifest_paths_must_differ")
    _assert_safe_target(output_epub, replace=replace)
    _assert_safe_target(output_manifest, replace=replace)

    epub_bytes, entry_order = build_epub_bytes(fixture)
    manifest = build_manifest(
        fixture=fixture,
        epub_filename=output_epub.name,
        epub_bytes=epub_bytes,
        zip_entry_order=entry_order,
    )
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    staged_manifest: Path | None = None
    staged_epub: Path | None = None
    manifest_committed = False
    epub_committed = False
    try:
        staged_manifest = _stage_bytes(output_manifest, manifest_bytes)
        staged_epub = _stage_bytes(output_epub, epub_bytes)
        _commit_staged_file(
            staged_path=staged_manifest,
            output_path=output_manifest,
            replace=replace,
        )
        staged_manifest = None
        manifest_committed = True
        _commit_staged_file(
            staged_path=staged_epub,
            output_path=output_epub,
            replace=replace,
        )
        staged_epub = None
        epub_committed = True
    finally:
        if staged_manifest is not None:
            staged_manifest.unlink(missing_ok=True)
        if staged_epub is not None:
            staged_epub.unlink(missing_ok=True)
        if manifest_committed and not epub_committed and not replace:
            output_manifest.unlink(missing_ok=True)
            _fsync_directory(output_manifest.parent)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Materialize a deterministic rights-safe audiobook canary EPUB."
    )
    parser.add_argument("--language", choices=tuple(sorted(FIXTURES)), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Explicitly replace existing regular output files; symlinks remain forbidden.",
    )
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    manifest = materialize_fixture(
        language=args.language,
        epub_path=args.output,
        manifest_path=args.manifest,
        replace=args.replace,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
