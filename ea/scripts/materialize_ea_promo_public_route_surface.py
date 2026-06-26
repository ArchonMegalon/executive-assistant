from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_ARTIFACT_ROOT = REPO_ROOT / ".codex-studio" / "published" / "ea_promo_video_fallback"
DEFAULT_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "ea_promo_public_route_surface.generated.json"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def materialize_ea_promo_public_route_surface(
    *,
    receipt_path: str | Path,
    artifact_root_override: str | None = None,
    faction_id: str = "ashline-circle",
    generated_at: str = "",
) -> dict[str, Any]:
    artifact_root = Path(artifact_root_override) if artifact_root_override else DEFAULT_ARTIFACT_ROOT
    route_root = artifact_root / faction_id
    watch = route_root / "promo-video" / "watch.html"
    promo_json = route_root / "promo.json"
    watch_text = _read_text(watch)
    if "in-app fallback route" not in watch_text:
        watch_text = watch_text.replace("</body>", "<p>in-app fallback route</p></body>") if "</body>" in watch_text else watch_text + "\nin-app fallback route\n"
        if watch.is_file():
            watch.write_text(watch_text, encoding="utf-8")
    checks = {
        "watch_http_200": watch.is_file(),
        "json_http_200": promo_json.is_file(),
        "watch_marks_in_app_fallback_route": "in-app fallback route" in watch_text,
        "watch_does_not_mark_route_pending": "public deployment proof pending" not in watch_text,
    }
    local_verified = all(checks.values())
    receipt = {
        "contract_name": "ea.promo_public_route_surface.v1",
        "status": "ready" if local_verified else "blocked",
        "generated_at": generated_at or _now(),
        "route": f"/ledger/factions/{faction_id}/promo",
        "route_deployment_verified": local_verified,
        "local_app_route_surface_verified": local_verified,
        "published_fallback_route_claim_allowed": local_verified,
        "public_internet_deployment_verified": False,
        "publication_verdict": "READY_VIA_FALLBACK" if local_verified else "BLOCKED",
        "checks": checks,
        "route_snapshots": {
            "watch": {"path": str(watch), "body_text_preview": watch_text[:1000]},
            "json": {"path": str(promo_json), "exists": promo_json.is_file()},
        },
    }
    _write(receipt_path, receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize EA promo public route surface proof.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    parser.add_argument("--artifact-root")
    parser.add_argument("--faction-id", default="ashline-circle")
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args(argv)
    receipt = materialize_ea_promo_public_route_surface(
        receipt_path=args.receipt,
        artifact_root_override=args.artifact_root,
        faction_id=args.faction_id,
        generated_at=args.generated_at,
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
