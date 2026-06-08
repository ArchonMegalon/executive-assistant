#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import shutil
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE_ROOT = ROOT / "memorial_data" / "public_memorials"
DEFAULT_PROOF_ROOT = Path("/docker/fleet/state/chummer6/avatar_presenter_provider")
ALLOWED_VIDEO_SUFFIXES = {".mp4", ".webm", ".mov"}
ALLOWED_POSTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid_json_object:{path}")
    return dict(payload)


def _safe_relname(label: str) -> str:
    lowered = "".join(ch.lower() if ch.isalnum() else "-" for ch in label.strip())
    compact = "-".join(part for part in lowered.split("-") if part)
    return compact or "asset"


def _validated_proof(path: Path, provider_key: str) -> dict[str, object]:
    payload = _load_json(path)
    if str(payload.get("provider_key") or "").strip().lower() != provider_key.strip().lower():
        raise SystemExit("provider_proof_provider_mismatch")
    if str(payload.get("verdict") or "").strip().upper() != "VERIFIED_PROVIDER":
        raise SystemExit("provider_proof_not_verified")
    if payload.get("provider_ready") is not True:
        raise SystemExit("provider_proof_not_ready")
    return payload


def _validated_bundle(slug: str, bundle_root: Path) -> tuple[Path, dict[str, object]]:
    bundle_dir = bundle_root / slug
    memorial_path = bundle_dir / "memorial.json"
    if not memorial_path.is_file():
        raise SystemExit(f"memorial_bundle_missing:{memorial_path}")
    payload = _load_json(memorial_path)
    if str(payload.get("slug") or "").strip() != slug:
        raise SystemExit("memorial_slug_mismatch")
    return bundle_dir, payload


def _validated_asset(path: Path, *, allowed_suffixes: set[str], error_code: str) -> Path:
    if not path.is_file():
        raise SystemExit(f"{error_code}_missing:{path}")
    suffix = path.suffix.lower()
    if suffix not in allowed_suffixes:
        raise SystemExit(f"{error_code}_unsupported:{suffix}")
    return path


def _copy_asset(source: Path, target: Path) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return _sha256_file(target)


def _receipt_payload(
    *,
    slug: str,
    provider_key: str,
    proof_path: Path,
    proof: dict[str, object],
    asset_relpath: str,
    poster_relpath: str,
    asset_sha256: str,
    poster_sha256: str,
) -> dict[str, object]:
    return {
        "generated_at": _utc_now(),
        "contract_name": "executive_assistant.memorial_video_call_avatar_publish.v1",
        "slug": slug,
        "provider_key": provider_key,
        "provider_proof_verdict": str(proof.get("verdict") or ""),
        "provider_proof_path": proof_path.as_posix(),
        "provider_proof_generated_at": str(proof.get("generated_at") or ""),
        "asset_relpath": asset_relpath,
        "poster_relpath": poster_relpath,
        "asset_sha256": asset_sha256,
        "poster_sha256": poster_sha256,
        "public_ready": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a verified memorial video-call avatar into a public memorial bundle.")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--provider", default="vidboard")
    parser.add_argument("--asset", required=True)
    parser.add_argument("--poster", required=True)
    parser.add_argument("--bundle-root", default=str(DEFAULT_BUNDLE_ROOT))
    parser.add_argument("--proof", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--detail", default="")
    parser.add_argument("--provider-label", default="")
    parser.add_argument("--publish-receipt", default="")
    args = parser.parse_args()

    slug = str(args.slug).strip()
    provider_key = str(args.provider).strip().lower()
    bundle_root = Path(args.bundle_root)
    proof_path = Path(args.proof) if str(args.proof).strip() else (DEFAULT_PROOF_ROOT / f"{provider_key}_AVATAR_PRESENTER_PROVIDER_PROOF.generated.json")
    proof = _validated_proof(proof_path, provider_key)
    bundle_dir, memorial_payload = _validated_bundle(slug, bundle_root)
    asset_source = _validated_asset(Path(args.asset), allowed_suffixes=ALLOWED_VIDEO_SUFFIXES, error_code="avatar_asset")
    poster_source = _validated_asset(Path(args.poster), allowed_suffixes=ALLOWED_POSTER_SUFFIXES, error_code="avatar_poster")

    asset_target_name = f"{_safe_relname(slug)}-{_safe_relname(provider_key)}-avatar{asset_source.suffix.lower()}"
    poster_target_name = f"{_safe_relname(slug)}-{_safe_relname(provider_key)}-avatar-poster{poster_source.suffix.lower()}"
    asset_target = bundle_dir / "video" / asset_target_name
    poster_target = bundle_dir / "video" / poster_target_name
    asset_sha256 = _copy_asset(asset_source, asset_target)
    poster_sha256 = _copy_asset(poster_source, poster_target)
    asset_relpath = asset_target.relative_to(bundle_dir).as_posix()
    poster_relpath = poster_target.relative_to(bundle_dir).as_posix()

    person_name = str(memorial_payload.get("person_name") or slug).strip() or slug
    provider_name = str(proof.get("provider") or provider_key).strip() or provider_key
    memorial_payload["video_call_avatar"] = {
        "provider_key": provider_key,
        "provider_proof_verdict": str(proof.get("verdict") or ""),
        "provider_proof_path": proof_path.as_posix(),
        "provider_proof_generated_at": str(proof.get("generated_at") or ""),
        "public_ready": True,
        "published_at": _utc_now(),
        "asset_relpath": asset_relpath,
        "poster_relpath": poster_relpath,
        "provider_label": str(args.provider_label).strip() or f"{provider_name} Avatar bereit",
        "title": str(args.title).strip() or f"{person_name} als Avatar",
        "detail": str(args.detail).strip() or f"{provider_name}-Clip ist fuer den Video Call eingebunden.",
        "asset_mime_type": mimetypes.guess_type(asset_target.name)[0] or "application/octet-stream",
        "poster_mime_type": mimetypes.guess_type(poster_target.name)[0] or "application/octet-stream",
        "asset_sha256": asset_sha256,
        "poster_sha256": poster_sha256,
    }
    (bundle_dir / "memorial.json").write_text(json.dumps(memorial_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    receipt_path = Path(args.publish_receipt) if str(args.publish_receipt).strip() else (DEFAULT_PROOF_ROOT / f"{slug}_video_call_avatar_publish.generated.json")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(
            _receipt_payload(
                slug=slug,
                provider_key=provider_key,
                proof_path=proof_path,
                proof=proof,
                asset_relpath=asset_relpath,
                poster_relpath=poster_relpath,
                asset_sha256=asset_sha256,
                poster_sha256=poster_sha256,
            ),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "slug": slug,
                "provider_key": provider_key,
                "asset_relpath": asset_relpath,
                "poster_relpath": poster_relpath,
                "receipt_path": receipt_path.as_posix(),
                "verdict": "published",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
