#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "config/provider_evidence/AIWRITEBOOK_ACCOUNT_REVIEW.source.json"
DEFAULT_OUTPUT = ROOT / "ea/_completion/aiwritebook/AIWRITEBOOK_ACCOUNT_REVIEW.generated.json"


def load_sanitized_source(path: Path = DEFAULT_SOURCE) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("aiwritebook_account_review_source_must_be_an_object")
    rendered = json.dumps(payload, sort_keys=True)
    account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
    if (
        payload.get("contract") != "ea.aiwritebook.account_review"
        or payload.get("contract_version") != 2
        or payload.get("secret_material_in_receipt") is not False
        or account.get("safe_ref") != "gmail.com"
        or "@" in rendered
        or "password" in rendered.lower()
    ):
        raise ValueError("aiwritebook_account_review_source_is_not_sanitized")
    return payload


def materialize(
    *,
    source: Path = DEFAULT_SOURCE,
    output: Path = DEFAULT_OUTPUT,
) -> Path:
    payload = load_sanitized_source(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize the sanitized AIWriteBook account-review receipt.")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    output = materialize(source=Path(args.source), output=Path(args.output))
    print(json.dumps({"status": "pass", "output": str(output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
