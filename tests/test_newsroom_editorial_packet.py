from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType


def _load_script(path: str, name: str) -> ModuleType:
    script_path = Path(path)
    spec = importlib.util.spec_from_file_location(name, script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_newsroom_editorial_packet_builds_expected_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    module = _load_script(str(root / "scripts" / "newsroom_editorial_packet.py"), "newsroom_editorial_packet_test")

    payload = module.build_payload()

    assert payload["episode"]["episode_id"] == "black-ledger-turn1-bulletin-sample"
    assert payload["episode"]["status"] == "editorial_ready"
    assert payload["anchor"]["anchor_id"] == "mara_voss"
    assert "Photorealistic cyberpunk newsroom broadcast" in payload["anchor"]["host_performance_prompt"]
    assert len(payload["segments"]) == 3
    assert payload["segments"][1]["broll_cues"][0]["scene_type"] == "facility_exterior"
    assert payload["watch_page_contract"]["required_sections"][2] == "source_receipts"


def test_verify_newsroom_editorial_packet_accepts_materialized_output(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    output_path = tmp_path / "NEWSROOM_EDITORIAL_PACKET.generated.json"
    subprocess.run(
        ["python3", str(root / "scripts" / "newsroom_editorial_packet.py"), "--write", str(output_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    repo_output = root / ".codex-studio" / "published" / "NEWSROOM_EDITORIAL_PACKET.generated.json"
    original = repo_output.read_text(encoding="utf-8") if repo_output.exists() else None
    repo_output.parent.mkdir(parents=True, exist_ok=True)
    repo_output.write_text(output_path.read_text(encoding="utf-8"), encoding="utf-8")
    try:
        completed = subprocess.run(
            ["python3", str(root / "scripts" / "verify_newsroom_editorial_packet.py")],
            check=True,
            capture_output=True,
            text=True,
        )
        assert "ok: newsroom editorial packet" in completed.stdout
    finally:
        if original is None:
            repo_output.unlink(missing_ok=True)
        else:
            repo_output.write_text(original, encoding="utf-8")
