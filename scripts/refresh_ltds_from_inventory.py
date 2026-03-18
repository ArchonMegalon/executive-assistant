#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


EA_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EA_ROOT / "ea"))

from app.services.ltd_inventory_markdown import refresh_inventory_markdown


def _load_json(path: str) -> dict[str, object]:
    if path == "-":
        payload = sys.stdin.read()
    else:
        payload = Path(path).read_text(encoding="utf-8")
    data = json.loads(payload or "{}")
    if not isinstance(data, dict):
        raise ValueError("inventory_json_must_be_object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh the LTDs.md discovery-tracking table from a BrowserAct inventory artifact/output JSON payload.",
    )
    parser.add_argument(
        "--input",
        default="-",
        help="Inventory JSON file path, or '-' to read JSON from stdin.",
    )
    parser.add_argument(
        "--markdown",
        default=str(EA_ROOT / "LTDs.md"),
        help="Path to the LTD markdown file to update.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the refreshed markdown back to --markdown instead of printing to stdout.",
    )
    args = parser.parse_args()

    inventory_output_json = _load_json(args.input)
    markdown_path = Path(args.markdown)
    existing = markdown_path.read_text(encoding="utf-8")
    updated = refresh_inventory_markdown(existing, inventory_output_json)
    if args.write:
        markdown_path.write_text(updated, encoding="utf-8")
        return 0
    sys.stdout.write(updated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
