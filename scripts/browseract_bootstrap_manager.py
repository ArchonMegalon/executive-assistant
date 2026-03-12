#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


STATE_DIR = Path("/docker/fleet/state/browseract_bootstrap")


def slugify(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value)
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "adapter"


def build_spec(*, workflow_name: str, purpose: str, login_url: str, tool_url: str, output_dir: Path) -> dict[str, object]:
    slug = slugify(workflow_name)
    return {
        "workflow_name": workflow_name,
        "description": purpose,
        "publish": True,
        "mcp_ready": False,
        "nodes": [
            {"id": "open_login", "type": "visit_page", "label": "Open Login", "config": {"url": login_url}},
            {"id": "email", "type": "input_text", "label": "Email", "config": {"selector": "input[type=email]", "value_from_secret": "browseract_username"}},
            {"id": "password", "type": "input_text", "label": "Password", "config": {"selector": "input[type=password]", "value_from_secret": "browseract_password"}},
            {"id": "submit", "type": "click", "label": "Submit", "config": {"selector": "button[type=submit]"}},
            {"id": "wait_dashboard", "type": "wait", "label": "Wait Dashboard", "config": {"selector": "body"}},
            {"id": "open_tool", "type": "visit_page", "label": "Open Tool", "config": {"url": tool_url}},
            {"id": "input_prompt", "type": "input_text", "label": "Input Prompt", "config": {"selector": "textarea", "value_from_input": "prompt"}},
            {"id": "generate", "type": "click", "label": "Generate", "config": {"selector": "button"}},
            {"id": "extract_result", "type": "extract", "label": "Extract Result", "config": {"selector": "main, body"}},
        ],
        "edges": [
            ["open_login", "email"],
            ["email", "password"],
            ["password", "submit"],
            ["submit", "wait_dashboard"],
            ["wait_dashboard", "open_tool"],
            ["open_tool", "input_prompt"],
            ["input_prompt", "generate"],
            ["generate", "extract_result"],
        ],
        "meta": {
            "slug": slug,
            "output_dir": str(output_dir),
            "status": "pending_browseract_seed",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a BrowserAct adapter workflow spec from a prepared brief.")
    parser.add_argument("--workflow-name", required=True)
    parser.add_argument("--purpose", required=True)
    parser.add_argument("--login-url", required=True)
    parser.add_argument("--tool-url", required=True)
    parser.add_argument("--output-dir", default=str(STATE_DIR))
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(args.workflow_name)
    spec = build_spec(
        workflow_name=args.workflow_name,
        purpose=args.purpose,
        login_url=args.login_url,
        tool_url=args.tool_url,
        output_dir=output_dir,
    )
    spec_path = output_dir / f"{slug}.workflow.json"
    spec_path.write_text(json.dumps(spec, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "spec": str(spec_path), "workflow_name": args.workflow_name}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
