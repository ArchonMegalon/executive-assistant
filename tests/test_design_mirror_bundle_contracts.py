from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_design_mirror_bundle.py"
REPAIR_SCRIPT = ROOT / "scripts" / "repair_design_mirror_bundle.sh"


def test_design_mirror_bundle_bindings_cover_the_audited_queue_slice() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    keys = {row["key"] for row in payload}
    assert keys == {
        "next_90_day_queue_staging",
        "published_queue_overlay",
    }
    queue_row = next(row for row in payload if row["key"] == "next_90_day_queue_staging")
    assert queue_row["local_path"].endswith(".codex-design/product/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
    assert queue_row["source_path"] == "/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_QUEUE_STAGING.generated.yaml"
    overlay_row = next(row for row in payload if row["key"] == "published_queue_overlay")
    assert overlay_row["local_path"].endswith(".codex-studio/published/QUEUE.generated.yaml")
    assert overlay_row["source_items"] == [
        "/docker/EA/.codex-design/product/NEXT_90_DAY_QUEUE_STAGING.generated.yaml",
    ]


def test_repair_design_mirror_bundle_help_mentions_bounded_bundle() -> None:
    completed = subprocess.run(
        ["bash", str(REPAIR_SCRIPT), "--help"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "bounded EA design-mirror bundle" in completed.stdout


def test_release_assets_guard_wires_design_mirror_bundle_verifier() -> None:
    script = (ROOT / "scripts" / "verify_release_assets.sh").read_text(encoding="utf-8")
    assert "scripts/verify_design_mirror_bundle.py" in script
    assert "scripts/repair_design_mirror_bundle.sh" in script
    assert "ok: bounded design mirror bundle parity" in script


def test_repair_design_mirror_bundle_restores_drifted_queue_staging(tmp_path) -> None:
    local_queue = ROOT / ".codex-design" / "product" / "NEXT_90_DAY_QUEUE_STAGING.generated.yaml"
    source_queue = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
    backup_queue = tmp_path / "NEXT_90_DAY_QUEUE_STAGING.generated.yaml.backup"

    shutil.copy2(local_queue, backup_queue)
    try:
        local_queue.write_text("mode: append\nitems: []\n", encoding="utf-8")

        failed = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert failed.returncode == 1
        assert "drift: next_90_day_queue_staging" in failed.stdout

        repaired = subprocess.run(
            ["bash", str(REPAIR_SCRIPT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "ok: next_90_day_queue_staging" in repaired.stdout
        assert local_queue.read_text(encoding="utf-8") == source_queue.read_text(encoding="utf-8")
    finally:
        shutil.copy2(backup_queue, local_queue)


def test_repair_design_mirror_bundle_restores_drifted_queue_overlay_source_items(tmp_path) -> None:
    queue_overlay = ROOT / ".codex-studio" / "published" / "QUEUE.generated.yaml"
    backup_overlay = tmp_path / "QUEUE.generated.yaml.backup"

    shutil.copy2(queue_overlay, backup_overlay)
    try:
        payload = yaml.safe_load(queue_overlay.read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        items = payload.get("items") or []
        assert isinstance(items, list) and items
        items[0]["source_items"] = ["/docker/EA/.codex-design/product/NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml"]
        queue_overlay.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

        failed = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert failed.returncode == 1
        assert "queue_drift: published_queue_overlay" in failed.stdout

        repaired = subprocess.run(
            ["bash", str(REPAIR_SCRIPT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "ok: published_queue_overlay" in repaired.stdout
        repaired_payload = yaml.safe_load(queue_overlay.read_text(encoding="utf-8"))
        repaired_items = repaired_payload.get("items") or []
        assert repaired_items[0]["source_items"] == [
            "/docker/EA/.codex-design/product/NEXT_90_DAY_QUEUE_STAGING.generated.yaml",
        ]
    finally:
        shutil.copy2(backup_overlay, queue_overlay)
