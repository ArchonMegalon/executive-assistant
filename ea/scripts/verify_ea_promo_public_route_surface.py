from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "ea_promo_public_route_surface.generated.json"


def verify_ea_promo_public_route_surface(receipt_path: str | Path) -> dict[str, Any]:
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    issues: list[str] = []
    if receipt.get("route_deployment_verified") is not True:
        issues.append("promo_public_route_verification_not_true")
    if receipt.get("published_fallback_route_claim_allowed") is not True:
        issues.append("promo_public_route_fallback_claim_not_allowed")
    checks = dict(receipt.get("checks") or {})
    for key in ("watch_http_200", "json_http_200", "watch_marks_in_app_fallback_route", "watch_does_not_mark_route_pending"):
        if checks.get(key) is not True:
            issues.append(f"promo_public_route_check_failed:{key}")
    if receipt.get("public_internet_deployment_verified") is True:
        issues.append("promo_public_route_internet_overclaim")
    return {"contract_name": "ea.promo_public_route_surface.verify.v1", "status": "pass" if not issues else "fail", "issues": issues}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify EA promo public route surface proof.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    args = parser.parse_args(argv)
    result = verify_ea_promo_public_route_surface(args.receipt)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
