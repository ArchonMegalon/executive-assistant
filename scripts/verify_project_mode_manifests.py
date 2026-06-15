#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT_MODES = ROOT / ".codex-design/product/PROJECT_MODES.generated.json"
SHOW_SURFACE = ROOT / ".codex-design/product/SHOW_SURFACE_MANIFEST.generated.json"
GENERATED_RECEIPT_PATHS = {
    ".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json",
    ".codex-design/product/MEMORIAL_OPERATOR_STATUS.generated.json",
    ".codex-design/product/MEMORIAL_PHRASE_BANK.manfred.generated.json",
    ".codex-design/product/PROJECT_MODES.generated.json",
    ".codex-design/product/SHOW_SURFACE_MANIFEST.generated.json",
    ".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json",
    ".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json",
    ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json",
    ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json",
    ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json",
    ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json",
    ".codex-studio/published/memorial_realtime_browser_meaningful_public_origin.generated.json",
    ".codex-studio/published/memorial_room_audio_public_origin.generated.json",
}


def _load(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid_json:{path}")
    return payload


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except Exception:
        return ""


def _recorded_source_head(payload: dict) -> str:
    return str(payload.get("source_git_head") or payload.get("git_head") or "").strip()


def _fresh_enough(recorded_head: str, *, current_head: str) -> bool:
    recorded = str(recorded_head or "").strip()
    if not recorded or not current_head:
        return False
    if recorded == current_head:
        return True
    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "diff", "--name-only", f"{recorded}..{current_head}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return False
    if proc.returncode != 0:
        return False
    changed = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    return bool(changed) and changed <= GENERATED_RECEIPT_PATHS


def main() -> int:
    modes = _load(PROJECT_MODES)
    show = _load(SHOW_SURFACE)
    current_head = _git_head()
    if current_head and not _fresh_enough(_recorded_source_head(modes), current_head=current_head):
        raise SystemExit("project_modes_manifest_stale")
    if current_head and not _fresh_enough(_recorded_source_head(show), current_head=current_head):
        raise SystemExit("show_surface_manifest_stale")
    keys = {str(item.get("key") or "") for item in modes.get("modes", []) if isinstance(item, dict)}
    required = {"EA_CORE", "MEMORIAL", "PROVIDER_LAB", "CHUMMER_RELEASE_CONTROL", "PROPERTY"}
    missing = required - keys
    if missing:
        raise SystemExit(f"missing_project_modes:{','.join(sorted(missing))}")
    by_key = {str(item.get("key")): item for item in modes.get("modes", []) if isinstance(item, dict)}
    if by_key["EA_CORE"].get("status") != "shipping_core":
        raise SystemExit("ea_core_not_shipping_core")
    if by_key["MEMORIAL"].get("status") not in {"separate_risk_zone", "shipping_memorial"}:
        raise SystemExit("memorial_mode_status_invalid")
    if "tests/e2e/test_ea_first_value_journey.py" not in str(by_key["EA_CORE"].get("hard_gate") or ""):
        raise SystemExit("ea_core_first_value_gate_missing")
    memorial_hard_gates = [str(item) for item in list(by_key["MEMORIAL"].get("hard_gates") or []) if str(item)]
    expected_memorial_hard_gates = [
        ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json",
        ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json",
        ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json",
    ]
    if memorial_hard_gates != expected_memorial_hard_gates:
        raise SystemExit("memorial_hard_gates_missing")
    if show.get("demo_mode") != "ea_core":
        raise SystemExit("show_surface_demo_mode_not_ea_core")
    allowed = set(show.get("allowed_surfaces") or [])
    if "/modes" in allowed:
        raise SystemExit("operator_modes_surface_leaked_into_public_demo")
    operator_surfaces = set(show.get("operator_surfaces") or [])
    if "/modes" not in operator_surfaces:
        raise SystemExit("operator_modes_surface_missing")
    runtime_image_without_tests = ROOT == Path("/app") and not (ROOT / "tests").exists()
    ea_gate = ROOT / str(by_key["EA_CORE"].get("hard_gate") or "")
    if not ea_gate.is_file() and not runtime_image_without_tests:
        raise SystemExit("ea_core_hard_gate_path_missing")
    memorial_gate = ROOT / str(by_key["MEMORIAL"].get("local_release_gate") or by_key["MEMORIAL"].get("hard_gate") or "")
    if not memorial_gate.is_file():
        raise SystemExit("memorial_hard_gate_receipt_missing")
    try:
        memorial_receipt = json.loads(memorial_gate.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"memorial_hard_gate_receipt_invalid:{exc}") from exc
    memorial_status = str(memorial_receipt.get("status") or "").strip().lower()
    if current_head and memorial_status == "pass" and not _fresh_enough(str(memorial_receipt.get("git_head") or ""), current_head=current_head):
        raise SystemExit("memorial_hard_gate_receipt_stale")
    if by_key["MEMORIAL"].get("status") == "shipping_memorial" and memorial_status != "pass":
        raise SystemExit("shipping_memorial_gate_not_passing")
    if by_key["MEMORIAL"].get("status") == "separate_risk_zone" and memorial_status == "pass":
        raise SystemExit("memorial_pass_receipt_still_marked_risk_zone")
    public_gold_status = str(by_key["MEMORIAL"].get("public_gold_status") or "")
    if public_gold_status not in {"public_origin_gold_blocked", "public_origin_gold_pass"}:
        raise SystemExit("memorial_public_gold_status_invalid")
    public_gold_gates = [str(item) for item in list(by_key["MEMORIAL"].get("public_gold_gates") or []) if str(item)]
    expected_public_gates = {
        ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json",
        ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json",
        ".codex-studio/published/memorial_room_audio_public_origin.generated.json",
    }
    if set(public_gold_gates) != expected_public_gates:
        raise SystemExit("memorial_public_gold_gates_missing")
    public_gate_payloads = []
    for public_gate in public_gold_gates:
        path = ROOT / public_gate
        if path.is_file():
            try:
                public_gate_payloads.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                public_gate_payloads.append({})
    public_gate_pass_count = sum(1 for payload in public_gate_payloads if str(payload.get("status") or "").strip().lower() == "pass")
    if public_gold_status == "public_origin_gold_pass" and public_gate_pass_count != len(expected_public_gates):
        raise SystemExit("memorial_public_gold_pass_without_all_public_gates")
    if public_gold_status == "public_origin_gold_blocked" and public_gate_pass_count == len(expected_public_gates):
        raise SystemExit("memorial_public_gold_blocked_despite_public_gates")
    forbidden = set(show.get("forbidden_surfaces") or [])
    for expected in {"/memorials/*", "/memorials/files/*", "/results/*", "/tours/*"}:
        if expected not in forbidden:
            raise SystemExit(f"show_surface_missing_forbidden:{expected}")
    forbidden_providers = set(show.get("forbidden_provider_names") or [])
    for provider in {"JoggAI", "MagicFit", "Poppy", "Unmixr", "VoiceWave"}:
        if provider not in forbidden_providers:
            raise SystemExit(f"show_surface_missing_provider:{provider}")
    print(json.dumps({"status": "pass", "message": "project mode manifests are bounded and explicit."}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
