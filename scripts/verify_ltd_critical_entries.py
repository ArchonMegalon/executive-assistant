#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _contains(text: str, *needles: str) -> bool:
    return all(str(needle or "") in text for needle in needles)


def build_receipt(*, markdown_text: str, env: dict[str, str]) -> dict[str, object]:
    checks = {
        "prompt_architects_inventory": _contains(
            markdown_text,
            "| `Prompt Architects` | `Tier 4` |",
            "PROMPTING_SYSTEMS_API_KEY",
            "Prompt Foundry",
        ),
        "onemin_inventory": _contains(
            markdown_text,
            "| `1min.AI` | `Advanced Business Plan` |",
            "scripts/resolve_onemin_ai_key.sh",
            "remaining credits",
        ),
        "browseract_discovery": _contains(
            markdown_text,
            "| `BrowserAct` | ops@example.com | `complete` | `browseract_live` |",
        ),
        "teable_discovery": _contains(
            markdown_text,
            "| `Teable` | ops@teable.example | `complete` | `browseract_live` |",
        ),
        "prompt_architects_env": bool(str(env.get("PROMPTING_SYSTEMS_API_KEY") or "").strip()),
        "onemin_env": bool(str(env.get("ONEMIN_AI_API_KEY") or "").strip()),
    }
    failures = [name for name, ok in checks.items() if not ok]
    return {
        "contract_name": "ea.verify_ltd_critical_entries",
        "status": "pass" if not failures else "fail",
        "checks": checks,
        "failures": failures,
    }


def main() -> int:
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        print(
            "Usage:\n"
            "  python3 scripts/verify_ltd_critical_entries.py\n\n"
            "Fail closed when the runtime-critical LTD rows or local env drift away\n"
            "from the required 1min.AI, Prompt Architects, BrowserAct, and Teable facts."
        )
        return 0
    root = Path(__file__).resolve().parents[1]
    markdown_path = root / "LTDs.md"
    markdown_text = markdown_path.read_text(encoding="utf-8")
    env = _load_dotenv(root / ".env")
    env.update({key: value for key, value in os.environ.items() if value})
    receipt = build_receipt(markdown_text=markdown_text, env=env)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
