#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


EA_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = EA_ROOT / ".env"
API_BASE = "https://api.browseract.com/v2/workflow"


def load_local_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_FILE.exists():
        return values
    for raw in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


LOCAL_ENV = load_local_env()


def env_value(name: str) -> str:
    return str(os.environ.get(name) or LOCAL_ENV.get(name) or "").strip()


def browseract_key() -> str:
    for key_name in (
        "BROWSERACT_API_KEY",
        "BROWSERACT_API_KEY_FALLBACK_1",
        "BROWSERACT_API_KEY_FALLBACK_2",
        "BROWSERACT_API_KEY_FALLBACK_3",
    ):
        value = env_value(key_name)
        if value:
            return value
    return ""


def api_request(method: str, path: str, *, payload: dict[str, object] | None = None, query: dict[str, str] | None = None) -> dict[str, object]:
    key = browseract_key()
    if not key:
        raise RuntimeError("browseract:not_configured")
    url = API_BASE.rstrip("/") + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    headers = {
        "Authorization": f"Bearer {key}",
        "User-Agent": "EA-BrowserAct-Architect/1.0",
    }
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, method=method.upper(), headers=headers, data=data)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"browseract:http_{exc.code}:{detail[:240]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"browseract:urlerror:{exc.reason}") from exc
    try:
        loaded = json.loads(body)
    except Exception as exc:
        raise RuntimeError(f"browseract:non_json:{body[:240]}") from exc
    return loaded if isinstance(loaded, dict) else {"data": loaded}


def load_spec(path: Path) -> dict[str, object]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise RuntimeError("invalid_spec")
    return loaded


def normalize_spec(raw: dict[str, object]) -> dict[str, object]:
    nodes = raw.get("nodes")
    edges = raw.get("edges")
    if not isinstance(nodes, list) or not nodes:
        raise RuntimeError("invalid_spec:nodes")
    if not isinstance(edges, list):
        raise RuntimeError("invalid_spec:edges")
    normalized_nodes: list[dict[str, object]] = []
    for index, entry in enumerate(nodes, start=1):
        if not isinstance(entry, dict):
            raise RuntimeError("invalid_spec:node_entry")
        label = str(entry.get("label") or f"Step {index}").strip()
        node_type = str(entry.get("type") or "").strip().lower()
        config = entry.get("config") if isinstance(entry.get("config"), dict) else {}
        if not node_type:
            raise RuntimeError("invalid_spec:node_type")
        normalized_nodes.append(
            {
                "id": str(entry.get("id") or f"node_{index:02d}"),
                "label": label,
                "type": node_type,
                "config": config,
            }
        )
    normalized_edges: list[dict[str, str]] = []
    for index, entry in enumerate(edges, start=1):
        if isinstance(entry, dict):
            source = str(entry.get("source") or "").strip()
            target = str(entry.get("target") or "").strip()
        elif isinstance(entry, list) and len(entry) == 2:
            source = str(entry[0] or "").strip()
            target = str(entry[1] or "").strip()
        else:
            raise RuntimeError("invalid_spec:edge_entry")
        if not source or not target:
            raise RuntimeError("invalid_spec:edge_values")
        normalized_edges.append({"id": f"edge_{index:02d}", "source": source, "target": target})
    normalized_inputs: list[dict[str, object]] = []
    seen_inputs: set[str] = set()

    def add_input(name: object, *, description: object = "", default_value: object = "") -> None:
        normalized_name = str(name or "").strip()
        if not normalized_name:
            return
        key = normalized_name.lower()
        if key in seen_inputs:
            return
        seen_inputs.add(key)
        normalized_inputs.append(
            {
                "name": normalized_name,
                "description": str(description or "").strip(),
                "default_value": str(default_value or "").strip(),
            }
        )

    raw_inputs = raw.get("inputs")
    if not isinstance(raw_inputs, list):
        raw_inputs = raw.get("input_parameters")
    if isinstance(raw_inputs, list):
        for entry in raw_inputs:
            if isinstance(entry, dict):
                add_input(
                    entry.get("name") or entry.get("key") or entry.get("id"),
                    description=entry.get("description") or entry.get("label"),
                    default_value=entry.get("default_value") or entry.get("default") or entry.get("value"),
                )
            elif isinstance(entry, str):
                add_input(entry)
    for node in normalized_nodes:
        config = dict(node.get("config") or {})
        inferred_name = str(config.get("value_from_input") or "").strip()
        if not inferred_name:
            inferred_name = str(config.get("value_from_secret") or "").strip()
        if not inferred_name:
            continue
        inferred_description = str(config.get("description") or f"Runtime input for {node['label']}.").strip()
        add_input(inferred_name, description=inferred_description)
    return {
        "workflow_name": str(raw.get("workflow_name") or "browseract_architect").strip() or "browseract_architect",
        "description": str(raw.get("description") or "").strip(),
        "publish": bool(raw.get("publish", False)),
        "mcp_ready": bool(raw.get("mcp_ready", False)),
        "inputs": normalized_inputs,
        "nodes": normalized_nodes,
        "edges": normalized_edges,
    }


def builder_packet(spec: dict[str, object]) -> dict[str, object]:
    nodes = list(spec.get("nodes") or [])
    edges = list(spec.get("edges") or [])
    inputs = list(spec.get("inputs") or [])
    instructions = [
        "Open BrowserAct dashboard and start a new workflow.",
        "Set workflow name and description from the packet metadata, then declare the runtime input parameters on the Start node.",
        "Add nodes in listed order, then configure each node from its config payload.",
        "Wire edges exactly as listed.",
        "Save draft, publish workflow, then enable MCP later only if explicitly requested.",
    ]
    return {
        "workflow_name": spec.get("workflow_name"),
        "description": spec.get("description"),
        "publish": bool(spec.get("publish")),
        "mcp_ready": bool(spec.get("mcp_ready")),
        "instructions": instructions,
        "inputs": inputs,
        "nodes": nodes,
        "edges": edges,
    }


def cmd_emit(spec_path: Path, output_path: Path) -> int:
    spec = normalize_spec(load_spec(spec_path))
    packet = builder_packet(spec)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(packet, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "output": str(output_path), "workflow_name": packet["workflow_name"]}, ensure_ascii=True))
    return 0


def cmd_check() -> int:
    workflow_id = env_value("BROWSERACT_ARCHITECT_WORKFLOW_ID")
    query = env_value("BROWSERACT_ARCHITECT_WORKFLOW_QUERY")
    if workflow_id:
        print(json.dumps({"status": "ready", "workflow_id": workflow_id, "source": "explicit"}, ensure_ascii=True))
        return 0
    print(json.dumps({"status": "pending_seed", "workflow_query": query or "browseract architect"}, ensure_ascii=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="BrowserAct architect helper.")
    sub = parser.add_subparsers(dest="command", required=True)
    emit = sub.add_parser("emit")
    emit.add_argument("--spec", required=True)
    emit.add_argument("--output", required=True)
    sub.add_parser("check")
    args = parser.parse_args()
    if args.command == "emit":
        return cmd_emit(Path(args.spec), Path(args.output))
    if args.command == "check":
        return cmd_check()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
