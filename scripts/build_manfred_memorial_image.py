#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


RECEIPT_SCHEMA = "ea.manfred_memorial_image_build.v2"
FORBIDDEN_CONTEXT_PATHS = (
    ".env",
    ".env.local",
    "memorial_data",
    "memorial_archive",
)
FORBIDDEN_IMAGE_PATHS = (
    "/app/memorial_data",
    "/app/memorial_archive",
    "/tmp/src",
    "/app/.env",
    "/app/.env.local",
)


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    stdout: object | None = subprocess.PIPE,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=subprocess.PIPE,
    )


def _text(argv: list[str], *, cwd: Path) -> str:
    return _run(argv, cwd=cwd).stdout.decode("utf-8", errors="strict").strip()


def _commit_for_ref(source_root: Path, ref: str) -> str:
    commit = _text(
        ["git", "rev-parse", "--verify", f"{str(ref or 'HEAD').strip()}^{{commit}}"],
        cwd=source_root,
    ).lower()
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise ValueError("manfred_image_commit_invalid")
    return commit


def _safe_tag(raw: str, *, commit: str) -> str:
    tag = str(raw or "").strip() or f"ea-runtime:manfred-{commit[:12]}"
    lowered = tag.lower()
    if not tag or any(character.isspace() for character in tag):
        raise ValueError("manfred_image_tag_invalid")
    if lowered == "latest" or lowered.endswith(":latest"):
        raise ValueError("manfred_image_mutable_tag_forbidden")
    return tag


def _materialize_tracked_context(*, source_root: Path, commit: str, destination: Path) -> None:
    archive_path = destination.parent / "source.tar"
    with archive_path.open("wb") as handle:
        _run(
            ["git", "archive", "--format=tar", commit],
            cwd=source_root,
            stdout=handle,
        )
    _run(["tar", "-xf", str(archive_path), "-C", str(destination)])
    archive_path.unlink(missing_ok=True)
    for relative in FORBIDDEN_CONTEXT_PATHS:
        path = destination / relative
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    for relative in FORBIDDEN_CONTEXT_PATHS:
        if (destination / relative).exists() or (destination / relative).is_symlink():
            raise RuntimeError("manfred_image_forbidden_context_path_present")


def _image_inspection(tag: str, *, expected_commit: str) -> tuple[str, dict[str, object]]:
    raw = _run(["docker", "image", "inspect", tag]).stdout
    payload = json.loads(raw)
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise RuntimeError("manfred_image_inspection_invalid")
    inspection = dict(payload[0])
    image_id = str(inspection.get("Id") or "").strip()
    labels = dict((inspection.get("Config") or {}).get("Labels") or {})
    if labels.get("org.opencontainers.image.revision") != expected_commit:
        raise RuntimeError("manfred_image_revision_label_mismatch")
    configured_environment = list((inspection.get("Config") or {}).get("Env") or [])
    configured_revisions = [
        str(item).split("=", 1)[1]
        for item in configured_environment
        if str(item).split("=", 1)[0] == "EA_SOURCE_REVISION" and "=" in str(item)
    ]
    if configured_revisions != [expected_commit]:
        raise RuntimeError("manfred_image_source_revision_environment_mismatch")
    forbidden_names = {
        "EA_API_TOKEN",
        "EA_SIGNING_SECRET",
        "DATABASE_URL",
        "UNMIXR_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
    }
    for item in configured_environment:
        name = str(item).split("=", 1)[0]
        if name in forbidden_names:
            raise RuntimeError("manfred_image_runtime_secret_baked_in")
    return image_id, inspection


def _verify_image_filesystem(tag: str) -> None:
    checks = " && ".join(f"test ! -e {path}" for path in FORBIDDEN_IMAGE_PATHS)
    _run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "/bin/sh",
            tag,
            "-ec",
            checks,
        ]
    )


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        Path(temporary).unlink(missing_ok=True)


def build_image(
    *,
    source_root: Path,
    ref: str,
    tag: str,
    receipt_path: Path,
) -> dict[str, object]:
    source_root = source_root.expanduser().resolve()
    if not (source_root / ".git").exists():
        raise ValueError("manfred_image_source_repo_invalid")
    commit = _commit_for_ref(source_root, ref)
    safe_tag = _safe_tag(tag, commit=commit)
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with tempfile.TemporaryDirectory(prefix="ea-manfred-image-") as temporary:
        context = Path(temporary) / "context"
        context.mkdir(mode=0o700)
        _materialize_tracked_context(
            source_root=source_root,
            commit=commit,
            destination=context,
        )
        dockerfile = context / "ea" / "Dockerfile"
        if not dockerfile.is_file():
            raise RuntimeError("manfred_image_dockerfile_missing")
        _run(
            [
                "docker",
                "build",
                "--file",
                str(dockerfile),
                "--tag",
                safe_tag,
                "--build-arg",
                f"EA_SOURCE_REVISION={commit}",
                "--label",
                f"org.opencontainers.image.revision={commit}",
                "--label",
                f"org.opencontainers.image.created={created_at}",
                "--label",
                "org.opencontainers.image.title=EA Manfred Memorial candidate",
                "--label",
                "org.opencontainers.image.source=git:EA",
                str(context),
            ],
            stdout=None,
        )
    image_id, inspection = _image_inspection(safe_tag, expected_commit=commit)
    _verify_image_filesystem(safe_tag)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "status": "pass",
        "commit": commit,
        "image_tag": safe_tag,
        "image_id": image_id,
        "created_at": created_at,
        "revision_label": commit,
        "runtime_source_revision": commit,
        "rootfs_layer_count": len((inspection.get("RootFS") or {}).get("Layers") or []),
        "tracked_archive_context": True,
        "dirty_worktree_context_used": False,
        "runtime_secrets_baked_in": False,
        "memorial_data_baked_in": False,
        "memorial_archive_baked_in": False,
    }
    _atomic_json(receipt_path, receipt)
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an immutable Manfred Memorial image from an exact tracked Git tree."
    )
    parser.add_argument("--source-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--tag", default="")
    parser.add_argument(
        "--receipt",
        default=str(Path("~/.local/share/ea-deploy/manfred-memorial/image-build.json")),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = build_image(
            source_root=Path(args.source_root),
            ref=args.ref,
            tag=args.tag,
            receipt_path=Path(args.receipt),
        )
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {
                    "schema": RECEIPT_SCHEMA,
                    "status": "fail",
                    "error": str(exc)[:200],
                    "runtime_secrets_included": False,
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
