from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_audiobook_m4b_structure_probe(artifact_dir: Path) -> dict[str, object]:
    receipt_path = artifact_dir / "audiobook_m4b_structure_probe.generated.json"
    issues: list[str] = []
    if not receipt_path.is_file():
        return {"contract_name": "ea.audiobook_m4b_structure_probe.verify.v1", "status": "fail", "issues": ["m4b_structure_probe_receipt_missing"], "chapter_count": 0, "cover_attached_pic": False}
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    m4b = dict(receipt.get("m4b") or {})
    m4b_path = artifact_dir / str(m4b.get("path") or "")
    if not m4b_path.is_file():
        issues.append("m4b_structure_probe_m4b_missing")
    elif str(m4b.get("sha256") or "") != _sha256(m4b_path):
        issues.append("m4b_structure_probe_m4b_sha256_mismatch")
    probe_payload: dict[str, object] = {}
    if m4b_path.is_file():
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type:stream_disposition=attached_pic:chapters",
                "-of",
                "json",
                str(m4b_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if completed.returncode == 0:
            probe_payload = json.loads(completed.stdout or "{}")
        else:
            issues.append("m4b_structure_probe_ffprobe_failed")
    chapters = probe_payload.get("chapters") if isinstance(probe_payload.get("chapters"), list) else []
    streams = probe_payload.get("streams") if isinstance(probe_payload.get("streams"), list) else []
    cover_attached = any(
        isinstance(stream, dict)
        and stream.get("codec_type") == "video"
        and int(dict(stream.get("disposition") or {}).get("attached_pic") or 0) == 1
        for stream in streams
    )
    if len(chapters) != int(dict(receipt.get("expected") or {}).get("chapter_count") or 0):
        issues.append("m4b_structure_probe_chapter_count_mismatch")
    if not cover_attached:
        issues.append("m4b_structure_probe_cover_attached_pic_missing")
    return {
        "contract_name": "ea.audiobook_m4b_structure_probe.verify.v1",
        "status": "fail" if issues else "pass",
        "issues": issues,
        "chapter_count": len(chapters),
        "cover_attached_pic": cover_attached,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args()
    result = verify_audiobook_m4b_structure_probe(args.artifact_dir)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

