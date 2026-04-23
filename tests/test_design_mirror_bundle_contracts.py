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
    assert "product:WEEKLY_PRODUCT_PULSE.generated.json" in keys
    assert "product:NEXT_90_DAY_QUEUE_STAGING.generated.yaml" in keys
    assert "repo:implementation_scope" in keys
    assert "review:review_context" in keys
    assert "product:stale_local_files" in keys
    assert "published_queue_overlay" in keys
    pulse_row = next(row for row in payload if row["key"] == "product:WEEKLY_PRODUCT_PULSE.generated.json")
    assert pulse_row["local_path"].endswith(".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json")
    assert pulse_row["source_path"] == "/docker/chummercomplete/chummer-design/products/chummer/WEEKLY_PRODUCT_PULSE.generated.json"
    queue_row = next(row for row in payload if row["key"] == "product:NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
    assert queue_row["local_path"].endswith(".codex-design/product/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
    assert queue_row["source_path"] == "/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_QUEUE_STAGING.generated.yaml"
    repo_row = next(row for row in payload if row["key"] == "repo:implementation_scope")
    assert repo_row["local_path"].endswith(".codex-design/repo/IMPLEMENTATION_SCOPE.md")
    assert repo_row["source_path"] == "/docker/chummercomplete/chummer-design/products/chummer/projects/executive-assistant.md"
    review_row = next(row for row in payload if row["key"] == "review:review_context")
    assert review_row["local_path"].endswith(".codex-design/review/REVIEW_CONTEXT.md")
    assert review_row["source_path"] == "/docker/chummercomplete/chummer-design/products/chummer/review/executive-assistant.AGENTS.template.md"
    stale_row = next(row for row in payload if row["key"] == "product:stale_local_files")
    assert stale_row["local_path"].endswith(".codex-design/product")
    assert stale_row["status"] == "ok"
    assert stale_row["stale_files"] == []
    overlay_row = next(row for row in payload if row["key"] == "published_queue_overlay")
    assert overlay_row["local_path"].endswith(".codex-studio/published/QUEUE.generated.yaml")
    assert overlay_row["source_items"] == [
        "/docker/EA/.codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json",
        "/docker/EA/.codex-design/product/NEXT_90_DAY_QUEUE_STAGING.generated.yaml",
    ]
    feedback_row = next(row for row in payload if row["key"] == "feedback:applied_log")
    assert feedback_row["local_path"].endswith("feedback/.applied.log")
    assert feedback_row["status"] == "ok"
    assert feedback_row["missing_entries"] == []


def test_repair_design_mirror_bundle_help_mentions_bounded_bundle() -> None:
    completed = subprocess.run(
        ["bash", str(REPAIR_SCRIPT), "--help"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "EA design-mirror files" in completed.stdout


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
        assert "drift: product:NEXT_90_DAY_QUEUE_STAGING.generated.yaml" in failed.stdout

        repaired = subprocess.run(
            ["bash", str(REPAIR_SCRIPT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "ok: product:NEXT_90_DAY_QUEUE_STAGING.generated.yaml" in repaired.stdout
        assert local_queue.read_text(encoding="utf-8") == source_queue.read_text(encoding="utf-8")
    finally:
        shutil.copy2(backup_queue, local_queue)


def test_repair_design_mirror_bundle_restores_drifted_weekly_product_pulse(tmp_path) -> None:
    local_pulse = ROOT / ".codex-design" / "product" / "WEEKLY_PRODUCT_PULSE.generated.json"
    source_pulse = Path("/docker/chummercomplete/chummer-design/products/chummer/WEEKLY_PRODUCT_PULSE.generated.json")
    backup_pulse = tmp_path / "WEEKLY_PRODUCT_PULSE.generated.json.backup"

    shutil.copy2(local_pulse, backup_pulse)
    try:
        local_pulse.write_text('{"contract_name":"ea.weekly_product_pulse","drifted":true}\n', encoding="utf-8")

        failed = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert failed.returncode == 1
        assert "drift: product:WEEKLY_PRODUCT_PULSE.generated.json" in failed.stdout

        repaired = subprocess.run(
            ["bash", str(REPAIR_SCRIPT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "ok: product:WEEKLY_PRODUCT_PULSE.generated.json" in repaired.stdout
        assert local_pulse.read_text(encoding="utf-8") == source_pulse.read_text(encoding="utf-8")
    finally:
        shutil.copy2(backup_pulse, local_pulse)


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
            "/docker/EA/.codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json",
            "/docker/EA/.codex-design/product/NEXT_90_DAY_QUEUE_STAGING.generated.yaml",
        ]
    finally:
        shutil.copy2(backup_overlay, queue_overlay)


def test_repair_design_mirror_bundle_recreates_missing_overlay_item_with_stable_bounded_task_text(tmp_path) -> None:
    queue_overlay = ROOT / ".codex-studio" / "published" / "QUEUE.generated.yaml"
    backup_overlay = tmp_path / "QUEUE.generated.yaml.backup"

    shutil.copy2(queue_overlay, backup_overlay)
    try:
        queue_overlay.write_text("mode: append\nitems: []\n", encoding="utf-8")

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
        assert len(repaired_items) == 1
        repaired_item = repaired_items[0]
        assert repaired_item["package_id"] == "audit-task-4257456"
        assert repaired_item["title"] == (
            "Auto-detect and repair recurring `ea` mirror drift; keep one bounded queue slice for the "
            "affected local design mirror bundle instead of reopening one-off mirror refresh work."
        )
        assert repaired_item["task"] == repaired_item["title"]
        assert "5837 repeated audit observations" not in repaired_item["title"]
        assert repaired_item["source_items"] == [
            "/docker/EA/.codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json",
            "/docker/EA/.codex-design/product/NEXT_90_DAY_QUEUE_STAGING.generated.yaml",
        ]
    finally:
        shutil.copy2(backup_overlay, queue_overlay)


def test_design_mirror_bundle_verifier_flags_dynamic_repeat_count_queue_text(tmp_path) -> None:
    queue_overlay = ROOT / ".codex-studio" / "published" / "QUEUE.generated.yaml"
    backup_overlay = tmp_path / "QUEUE.generated.yaml.backup"

    shutil.copy2(queue_overlay, backup_overlay)
    try:
        payload = yaml.safe_load(queue_overlay.read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        items = payload.get("items") or []
        assert isinstance(items, list) and items
        items[0]["title"] = (
            "Auto-detect and repair recurring `ea` mirror drift after 7860 repeated audit observations; "
            "keep one bounded queue slice for the affected local design mirror bundle instead of reopening one-off mirror refresh work."
        )
        items[0]["task"] = items[0]["title"]
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
        repaired_item = (repaired_payload.get("items") or [])[0]
        assert repaired_item["title"] == (
            "Auto-detect and repair recurring `ea` mirror drift; keep one bounded queue slice for the "
            "affected local design mirror bundle instead of reopening one-off mirror refresh work."
        )
        assert repaired_item["task"] == repaired_item["title"]
    finally:
        shutil.copy2(backup_overlay, queue_overlay)


def test_repair_design_mirror_bundle_deduplicates_same_finding_rows(tmp_path) -> None:
    queue_overlay = ROOT / ".codex-studio" / "published" / "QUEUE.generated.yaml"
    backup_overlay = tmp_path / "QUEUE.generated.yaml.backup"

    shutil.copy2(queue_overlay, backup_overlay)
    try:
        payload = yaml.safe_load(queue_overlay.read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        original_items = payload.get("items") or []
        assert isinstance(original_items, list) and original_items
        duplicate = dict(original_items[0])
        duplicate["title"] = "stale duplicate mirror row"
        duplicate["task"] = duplicate["title"]
        payload["items"] = [original_items[0], duplicate]
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
        mirror_items = [item for item in repaired_items if item.get("audit_finding_key") == "project.design_mirror_missing_or_stale"]
        assert len(mirror_items) == 1
        assert mirror_items[0]["title"] == (
            "Auto-detect and repair recurring `ea` mirror drift; keep one bounded queue slice for the "
            "affected local design mirror bundle instead of reopening one-off mirror refresh work."
        )
    finally:
        shutil.copy2(backup_overlay, queue_overlay)


def test_design_mirror_bundle_verifier_flags_stale_product_files_and_repair_prunes_them(tmp_path) -> None:
    stale_file = ROOT / ".codex-design" / "product" / "SHOULD_NOT_EXIST.tmp"
    stale_file.write_text("stale\n", encoding="utf-8")
    try:
        failed = subprocess.run(
            [sys.executable, str(SCRIPT), "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert failed.returncode == 1
        payload = json.loads(failed.stdout)
        stale_row = next(row for row in payload if row["key"] == "product:stale_local_files")
        assert stale_row["status"] == "stale_local_files"
        assert "SHOULD_NOT_EXIST.tmp" in stale_row["stale_files"]

        repaired = subprocess.run(
            ["bash", str(REPAIR_SCRIPT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "ok: product:stale_local_files" in repaired.stdout
        assert not stale_file.exists()
    finally:
        if stale_file.exists():
            stale_file.unlink()


def test_design_mirror_bundle_verifier_prunes_local_product_receipts(tmp_path) -> None:
    local_receipt = ROOT / ".codex-design" / "product" / "UNAPPROVED_LOCAL_RECEIPT.generated.json"

    local_receipt.write_text('{"status":"stale"}\n', encoding="utf-8")
    assert local_receipt.exists()

    failed = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert failed.returncode == 1
    payload = json.loads(failed.stdout)
    stale_row = next(row for row in payload if row["key"] == "product:stale_local_files")
    assert stale_row["status"] == "stale_local_files"
    assert "UNAPPROVED_LOCAL_RECEIPT.generated.json" in stale_row["stale_files"]

    repaired = subprocess.run(
        ["bash", str(REPAIR_SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "ok: product:stale_local_files" in repaired.stdout
    assert not local_receipt.exists()


def test_design_mirror_bundle_verifier_has_no_local_product_artifact_exceptions() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    stale_row = next(row for row in payload if row["key"] == "product:stale_local_files")
    assert stale_row["status"] == "ok"
    assert stale_row["stale_files"] == []


def test_repair_design_mirror_bundle_appends_missing_feedback_log_entries(tmp_path) -> None:
    applied_log = ROOT / "feedback" / ".applied.log"
    backup_applied_log = tmp_path / ".applied.log.backup"

    shutil.copy2(applied_log, backup_applied_log)
    try:
        original_lines = applied_log.read_text(encoding="utf-8").splitlines()
        target_entry = "2026-04-22-124654-audit-task-4257456.md"
        assert any(Path(line).name == target_entry for line in original_lines)
        trimmed_lines = [line for line in original_lines if Path(line).name != target_entry]
        applied_log.write_text("\n".join(trimmed_lines) + "\n", encoding="utf-8")

        failed = subprocess.run(
            [sys.executable, str(SCRIPT), "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert failed.returncode == 1
        payload = json.loads(failed.stdout)
        feedback_row = next(row for row in payload if row["key"] == "feedback:applied_log")
        assert feedback_row["status"] == "feedback_reopen_risk"
        assert target_entry in feedback_row["missing_entries"]

        repaired = subprocess.run(
            ["bash", str(REPAIR_SCRIPT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "ok: feedback:applied_log" in repaired.stdout
        repaired_lines = applied_log.read_text(encoding="utf-8").splitlines()
        assert any(Path(line).name == target_entry for line in repaired_lines)
    finally:
        shutil.copy2(backup_applied_log, applied_log)


def test_design_mirror_bundle_verifier_flags_duplicate_feedback_log_entries_and_repair_dedupes(tmp_path) -> None:
    applied_log = ROOT / "feedback" / ".applied.log"
    backup_applied_log = tmp_path / ".applied.log.backup"

    shutil.copy2(applied_log, backup_applied_log)
    try:
        original_lines = applied_log.read_text(encoding="utf-8").splitlines()
        duplicate_entry = "feedback/2026-04-22-124343-audit-task-4257456.md"
        assert duplicate_entry in original_lines
        applied_log.write_text("\n".join([duplicate_entry, *original_lines]) + "\n", encoding="utf-8")

        failed = subprocess.run(
            [sys.executable, str(SCRIPT), "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert failed.returncode == 1
        payload = json.loads(failed.stdout)
        feedback_row = next(row for row in payload if row["key"] == "feedback:applied_log")
        assert feedback_row["status"] == "feedback_reopen_risk"
        assert "2026-04-22-124343-audit-task-4257456.md" in feedback_row["duplicate_entries"]

        repaired = subprocess.run(
            ["bash", str(REPAIR_SCRIPT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "ok: feedback:applied_log" in repaired.stdout
        repaired_lines = applied_log.read_text(encoding="utf-8").splitlines()
        assert repaired_lines.count(duplicate_entry) == 1
    finally:
        shutil.copy2(backup_applied_log, applied_log)
