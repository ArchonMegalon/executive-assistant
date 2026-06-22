#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.materialize_memorial_stt_fixture_candidate import (
        _default_bundle_root,
        _sha256_text,
        build_fixture_candidate,
    )
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from materialize_memorial_stt_fixture_candidate import (  # type: ignore
        _default_bundle_root,
        _sha256_text,
        build_fixture_candidate,
    )


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_MANIFEST = ROOT / "tests" / "fixtures" / "memorial" / "stt_fixture_manifest.json"
DEFAULT_OUTPUT = ROOT / ".codex-studio" / "published" / "memorial_stt_capture_discovery.generated.json"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _fixture_targets(samples: set[str] | None = None) -> list[dict[str, Any]]:
    manifest = _load_json(FIXTURE_MANIFEST)
    targets: list[dict[str, Any]] = []
    for item in list(manifest.get("fixtures") or []):
        if not isinstance(item, dict):
            continue
        sample = str(item.get("sample") or "").strip()
        if not sample or sample == "technical_retry":
            continue
        if samples and sample not in samples:
            continue
        expected_text = str(item.get("expected_text") or "").strip()
        required_tokens = [str(token).strip() for token in list(item.get("required_tokens") or []) if str(token).strip()]
        if not expected_text or not required_tokens:
            continue
        targets.append(
            {
                "sample": sample,
                "expected_text": expected_text,
                "required_tokens": required_tokens,
                "fixture_file": f"{sample}_real_captured.wav",
            }
        )
    return targets


def _metadata_text_fields(metadata: dict[str, Any]) -> dict[str, str]:
    fields: dict[str, str] = {}

    def add(prefix: str, value: object) -> None:
        if isinstance(value, str) and value.strip():
            fields[prefix] = " ".join(value.split()).strip()

    answer = metadata.get("answer") if isinstance(metadata.get("answer"), dict) else {}
    transcription = metadata.get("transcription") if isinstance(metadata.get("transcription"), dict) else {}
    add("answer.question", answer.get("question"))
    add("transcription.transcript_effective_text", transcription.get("transcript_effective_text"))
    add("transcription.transcript_original_text", transcription.get("transcript_original_text"))
    add("transcription.transcript_text", transcription.get("transcript_text"))
    return fields


def _matching_fields(fields: dict[str, str], expected_text: str) -> list[str]:
    expected_hash = _sha256_text(" ".join(expected_text.split()).strip())
    return [name for name, value in fields.items() if _sha256_text(value) == expected_hash]


def discover_bundle_dirs(bundle_root: Path) -> list[Path]:
    root = bundle_root.expanduser()
    if not root.exists():
        return []
    bundle_dirs: set[Path] = set()
    for metadata_path in root.rglob("error.json"):
        bundle_dir = metadata_path.parent
        if (bundle_dir / "input.wav").is_file():
            bundle_dirs.add(bundle_dir)
    return sorted(bundle_dirs, key=lambda path: path.as_posix())


def discover_bundle(
    *,
    bundle_dir: Path,
    targets: list[dict[str, Any]],
    speaker_consent: str,
    bundle_root: Path | None = None,
) -> list[dict[str, Any]]:
    metadata = _load_json(bundle_dir / "error.json")
    fields = _metadata_text_fields(metadata)
    rows: list[dict[str, Any]] = []
    for target in targets:
        expected_text = str(target["expected_text"])
        matched_fields = _matching_fields(fields, expected_text)
        if not matched_fields:
            continue
        candidate = build_fixture_candidate(
            bundle_dir=bundle_dir,
            sample=str(target["sample"]),
            expected_text=expected_text,
            required_tokens=[str(token) for token in list(target["required_tokens"])],
            speaker_consent=speaker_consent,
            origin="Captured Manfred memorial STT bundle matched by logged transcript hash.",
            allowed_purpose="memorial_stt_regression_and_provider_bakeoff",
            retention="private_captured_regression_candidate",
            accent="Austrian German",
            fixture_file=str(target["fixture_file"]),
            text_mode="redacted",
            allow_external_root=False,
            bundle_root=bundle_root,
        )
        candidate_entry = dict(candidate.get("candidate_manifest_entry") or {})
        rows.append(
            {
                "status": str(candidate.get("status") or "blocked"),
                "failed_codes": list(candidate.get("failed_codes") or []),
                "bundle_id": bundle_dir.name,
                "reason": str(metadata.get("reason") or ""),
                "route": str(metadata.get("route") or ""),
                "content_type": str(metadata.get("content_type") or ""),
                "stored_wav": bool(metadata.get("stored_wav")),
                "matched_metadata_fields": matched_fields,
                "sample": str(target["sample"]),
                "expected_text_chars": int(dict(candidate_entry.get("expected_text") or {}).get("text_chars") or 0),
                "expected_text_sha256": str(dict(candidate_entry.get("expected_text") or {}).get("text_sha256") or ""),
                "required_token_count": len(list(candidate_entry.get("required_tokens") or [])),
                "required_token_sha256": [
                    str(dict(token).get("text_sha256") or "")
                    for token in list(candidate_entry.get("required_tokens") or [])
                    if isinstance(token, dict)
                ],
                "audio": dict(candidate.get("audio") or {}),
                "fixture_file": str(candidate_entry.get("file") or ""),
                "raw_text_fields": bool(candidate.get("raw_text_fields")),
            }
        )
    return rows


def build_discovery(
    *,
    bundle_dirs: list[Path],
    samples: set[str] | None = None,
    speaker_consent: str = "operator_attested_for_private_stt_regression",
    bundle_root: Path | None = None,
    bundle_discovery_mode: str = "explicit_bundle_dirs",
) -> dict[str, Any]:
    targets = _fixture_targets(samples)
    resolved_bundle_root = bundle_root or _default_bundle_root()
    rows: list[dict[str, Any]] = []
    for bundle_dir in bundle_dirs:
        rows.extend(
            discover_bundle(
                bundle_dir=bundle_dir,
                targets=targets,
                speaker_consent=speaker_consent,
                bundle_root=resolved_bundle_root,
            )
        )
    promotable = [row for row in rows if row.get("status") == "pass"]
    blockers = sorted({str(code) for row in rows for code in list(row.get("failed_codes") or []) if str(code)})
    return {
        "contract_name": "ea.memorial_stt_capture_discovery",
        "status": "pass" if promotable else "blocked",
        "target_samples": [str(target["sample"]) for target in targets],
        "bundle_count": len(bundle_dirs),
        "bundle_discovery_mode": bundle_discovery_mode,
        "bundle_root": str(resolved_bundle_root),
        "matched_count": len(rows),
        "promotable_count": len(promotable),
        "failed_codes": blockers,
        "text_mode": "redacted",
        "raw_text_fields": False,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover redacted captured STT fixture candidates from selected private bundles.")
    parser.add_argument("--bundle-dir", action="append", type=Path, default=[])
    parser.add_argument("--sample", action="append", default=[])
    parser.add_argument("--speaker-consent", default="operator_attested_for_private_stt_regression")
    parser.add_argument("--bundle-root", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    samples = {str(item).strip() for item in list(args.sample or []) if str(item).strip()} or None
    bundle_root = args.bundle_root or _default_bundle_root()
    bundle_dirs = [path.expanduser() for path in list(args.bundle_dir or [])]
    bundle_discovery_mode = "explicit_bundle_dirs"
    if not bundle_dirs:
        bundle_dirs = discover_bundle_dirs(bundle_root)
        bundle_discovery_mode = "auto_bundle_root_scan"
    payload = build_discovery(
        bundle_dirs=bundle_dirs,
        samples=samples,
        speaker_consent=str(args.speaker_consent),
        bundle_root=bundle_root,
        bundle_discovery_mode=bundle_discovery_mode,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
