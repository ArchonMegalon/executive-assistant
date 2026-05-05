from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import shutil
import subprocess
import traceback

import yaml


ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = ROOT / "docs" / "chummer5a_parity_lab" / "CHUMMER5A_PARITY_LAB_PACK.yaml"
ORACLE_BASELINES_PATH = ROOT / "docs" / "chummer5a_parity_lab" / "oracle_baselines.yaml"
WORKFLOW_PACK_PATH = ROOT / "docs" / "chummer5a_parity_lab" / "veteran_workflow_pack.yaml"
COMPARE_PACKS_PATH = ROOT / "docs" / "chummer5a_parity_lab" / "compare_packs.yaml"
FIXTURE_INVENTORY_PATH = ROOT / "docs" / "chummer5a_parity_lab" / "import_export_fixture_inventory.yaml"
HANDOFF_CLOSEOUT_PATH = ROOT / "docs" / "chummer5a_parity_lab" / "SUCCESSOR_HANDOFF_CLOSEOUT.yaml"
README_PATH = ROOT / "docs" / "chummer5a_parity_lab" / "README.md"
PUBLISHED_PACK_PATH = ROOT / ".codex-studio" / "published" / "CHUMMER5A_PARITY_ORACLE_PACK.generated.json"
PARITY_ORACLE_PATH = Path("/docker/chummer5a/docs/PARITY_ORACLE.json")
VETERAN_GATE_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/VETERAN_FIRST_MINUTE_GATE.yaml")
FLAGSHIP_PARITY_REGISTRY_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/FLAGSHIP_PARITY_REGISTRY.yaml")
SUCCESSOR_REGISTRY_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml")
DESIGN_SUCCESSOR_QUEUE_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
SUCCESSOR_QUEUE_PATH = Path("/docker/fleet/.codex-studio/published/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
NEXT_12_REGISTRY_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_12_BIGGEST_WINS_REGISTRY.yaml")
PROGRAM_MILESTONES_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/PROGRAM_MILESTONES.yaml")
ROADMAP_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/ROADMAP.md")
FLAGSHIP_READINESS_PATH = Path("/docker/fleet/.codex-studio/published/FLAGSHIP_PRODUCT_READINESS.generated.json")
FEEDBACK_CLOSEOUT_PATH = ROOT / "feedback" / "2026-04-14-chummer5a-parity-lab-package-closeout.md"
CANONICAL_QUEUE_PROOF_FLOOR = (
    "/docker/EA commit f252c02 pins the latest M103 parity-lab proof floor into the published receipt, "
    "handoff closeout, and direct guard"
)


def _active_run_handoff_candidates() -> tuple[Path, ...]:
    roots = (
        Path("/var/lib/codex-fleet/chummer_design_supervisor"),
        Path("/docker/fleet/state/chummer_design_supervisor"),
    )
    candidates: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.glob("shard-*/ACTIVE_RUN_HANDOFF.generated.md")):
            path_text = path.as_posix()
            if path_text in seen:
                continue
            candidates.append(path)
            seen.add(path_text)
    if candidates:
        return tuple(candidates)
    return (
        Path("/var/lib/codex-fleet/chummer_design_supervisor/shard-4/ACTIVE_RUN_HANDOFF.generated.md"),
        Path("/docker/fleet/state/chummer_design_supervisor/shard-4/ACTIVE_RUN_HANDOFF.generated.md"),
    )


ACTIVE_RUN_HANDOFF_CANDIDATES = _active_run_handoff_candidates()


def _generated_at_from_handoff_text(text: str) -> str:
    match = re.search(r"^Generated at:\s*(\S+)", text, re.MULTILINE)
    return str(match.group(1) if match else "")


def _prompt_text_for_handoff(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^- Prompt path:\s*(\S+)", text, re.MULTILINE)
    if not match:
        return ""
    prompt_path = Path(match.group(1))
    aliases = [prompt_path]
    prompt_text = prompt_path.as_posix()
    if prompt_text.startswith("/var/lib/codex-fleet/"):
        aliases.append(Path(prompt_text.replace("/var/lib/codex-fleet/", "/docker/fleet/state/", 1)))
    elif prompt_text.startswith("/docker/fleet/state/"):
        aliases.append(Path(prompt_text.replace("/docker/fleet/state/", "/var/lib/codex-fleet/", 1)))
    for alias in aliases:
        if alias.exists():
            return alias.read_text(encoding="utf-8")
    return ""


def _select_active_run_handoff_path() -> Path:
    existing = [path for path in ACTIVE_RUN_HANDOFF_CANDIDATES if path.exists()]
    if not existing:
        return ACTIVE_RUN_HANDOFF_CANDIDATES[0]

    matching_package = [
        path
        for path in existing
        if "Frontier ids: 4287684466" in path.read_text(encoding="utf-8")
        and "next90-m103-ea-parity-lab" in _prompt_text_for_handoff(path)
    ]
    if matching_package:
        return max(
            matching_package,
            key=lambda current: _generated_at_from_handoff_text(current.read_text(encoding="utf-8")),
        )
    promptful = [path for path in existing if _prompt_text_for_handoff(path)]
    if promptful:
        return max(promptful, key=lambda current: _generated_at_from_handoff_text(current.read_text(encoding="utf-8")))
    return max(existing, key=lambda current: _generated_at_from_handoff_text(current.read_text(encoding="utf-8")))


ACTIVE_RUN_HANDOFF_PATH = _select_active_run_handoff_path()


def _yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def _assert_source_line_proof(entry: dict) -> None:
    source_path = Path(str(entry.get("file") or ""))
    assert source_path.exists(), str(source_path)
    line_number = int(entry.get("line") or 0)
    assert line_number > 0, entry
    lines = source_path.read_text(encoding="utf-8").splitlines()
    assert line_number <= len(lines), (source_path.as_posix(), line_number, len(lines))
    expected = str(entry.get("expected_substring") or "")
    assert expected, entry
    assert expected in lines[line_number - 1], (source_path.as_posix(), line_number, lines[line_number - 1], expected)


def _expected_direct_result() -> str:
    ran = sum(1 for name, func in globals().items() if name.startswith("test_") and callable(func))
    return f"ran={ran} failed=0"


def _active_handoff_generated_at() -> str:
    text = ACTIVE_RUN_HANDOFF_PATH.read_text(encoding="utf-8")
    match = re.search(r"^Generated at:\s*(\S+)", text, re.MULTILINE)
    assert match, "active handoff missing generated-at timestamp"
    return match.group(1)


def _active_handoff_prompt_text() -> str:
    return _active_handoff_prompt_path().read_text(encoding="utf-8")


def _worker_safe_handoff_shadow_path(path: Path) -> Path:
    path_text = path.as_posix()
    if not path_text.startswith("/var/lib/codex-fleet/"):
        return path
    return Path(path_text.replace("/var/lib/codex-fleet/", "/docker/fleet/state/", 1))


def _worker_safe_path_aliases(path: Path) -> set[str]:
    path_text = path.as_posix()
    aliases = {path_text}
    if path_text.startswith("/var/lib/codex-fleet/"):
        aliases.add(path_text.replace("/var/lib/codex-fleet/", "/docker/fleet/state/", 1))
    if path_text.startswith("/docker/fleet/state/"):
        aliases.add(path_text.replace("/docker/fleet/state/", "/var/lib/codex-fleet/", 1))
    return aliases


def _active_handoff_prompt_path_for(handoff_path: Path) -> Path | None:
    text = handoff_path.read_text(encoding="utf-8")
    match = re.search(r"^- Prompt path:\s*(\S+)", text, re.MULTILINE)
    if match:
        prompt_path = Path(match.group(1))
        if prompt_path.exists():
            return prompt_path
        worker_safe_shadow = _worker_safe_handoff_shadow_path(prompt_path)
        if worker_safe_shadow.exists():
            return worker_safe_shadow

    state_root_match = re.search(r"^State root:\s*(\S+)", text, re.MULTILINE)
    run_id_match = re.search(r"^- Run id:\s*(\S+)", text, re.MULTILINE)
    assert state_root_match, "active handoff missing state-root metadata"

    state_root = Path(state_root_match.group(1))
    state_root_aliases = [Path(alias) for alias in sorted(_worker_safe_path_aliases(state_root))]
    run_prompt_candidates: list[Path] = []
    if run_id_match:
        run_id = run_id_match.group(1)
        run_prompt_candidates.extend(root / "runs" / run_id / "prompt.txt" for root in state_root_aliases)
    for root in state_root_aliases:
        runs_root = root / "runs"
        if not runs_root.exists():
            continue
        run_prompt_candidates.extend(sorted(runs_root.glob("*/prompt.txt"), reverse=True))
    for candidate in run_prompt_candidates:
        prompt_path = _path_with_worker_safe_alias_fallback(candidate)
        if prompt_path is not None:
            return prompt_path
    return None


def _active_handoff_prompt_path() -> Path:
    prompt_path = _active_handoff_prompt_path_for(ACTIVE_RUN_HANDOFF_PATH)
    if prompt_path is not None:
        return prompt_path
    raise AssertionError("active handoff missing prompt path and run metadata")


def _path_with_worker_safe_alias_fallback(path: Path) -> Path | None:
    for alias in _worker_safe_path_aliases(path):
        candidate = Path(alias)
        if candidate.exists():
            return candidate
    return None


def _task_local_telemetry_path_if_present() -> Path | None:
    prompt_parent = _active_handoff_prompt_path().parent
    return _path_with_worker_safe_alias_fallback(prompt_parent / "TASK_LOCAL_TELEMETRY.generated.json")


def _task_local_telemetry_path() -> Path:
    path = _task_local_telemetry_path_if_present()
    assert path is not None, (_active_handoff_prompt_path().parent / "TASK_LOCAL_TELEMETRY.generated.json").as_posix()
    return path


def _active_handoff_targets_closed_m103_package() -> bool:
    active_handoff_text = ACTIVE_RUN_HANDOFF_PATH.read_text(encoding="utf-8")
    active_prompt_text = _active_handoff_prompt_text()
    return (
        "Frontier ids: 4287684466" in active_handoff_text
        and "Open milestone ids: 4287684466" in active_handoff_text
        and "next90-m103-ea-parity-lab" in active_prompt_text
    )


def _post_freeze_commit_ids(frozen_commit: str = "257a5b7") -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "rev-list", "--abbrev-commit", "--abbrev=7", f"{frozen_commit}..HEAD"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _post_freeze_commit_paths(frozen_commit: str = "257a5b7") -> dict[str, set[str]]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "rev-list", "--reverse", "--abbrev-commit", "--abbrev=7", f"{frozen_commit}..HEAD"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    commits = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    changed_paths: dict[str, set[str]] = {}
    for commit in commits:
        diff = subprocess.run(
            ["git", "-C", str(ROOT), "diff-tree", "--no-commit-id", "--name-only", "-r", commit],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        changed_paths[commit] = {line.strip() for line in diff.stdout.splitlines() if line.strip()}
    return changed_paths


def _literal_subprocess_run_commands(path: Path) -> list[list[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    commands: list[list[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_subprocess_run = (
            isinstance(func, ast.Attribute)
            and func.attr == "run"
            and isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"
        )
        if not is_subprocess_run:
            continue
        assert node.args, "subprocess.run calls must use explicit command arguments"
        command_arg = node.args[0]
        assert isinstance(command_arg, ast.List), "subprocess.run commands must stay literal lists"
        command: list[str] = []
        for index, element in enumerate(command_arg.elts):
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                command.append(element.value)
                continue
            assert index > 0, "subprocess.run executable must stay a literal string"
            command.append("<dynamic>")
        if command:
            commands.append(command)
    return commands


def _assert_no_unreviewed_process_invocations(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    allowed_subprocess_attrs = {"run"}
    blocked_function_names = {
        "system",
        "popen",
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
    }
    blocked_subprocess_attrs = {"Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput"}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            owner = func.value
            owner_name = owner.id if isinstance(owner, ast.Name) else ""
            if owner_name == "subprocess":
                assert func.attr in allowed_subprocess_attrs, f"unreviewed subprocess invocation: {func.attr}"
                assert func.attr not in blocked_subprocess_attrs, f"blocked subprocess invocation: {func.attr}"
            if owner_name == "os":
                assert func.attr not in blocked_function_names, f"blocked os process invocation: {func.attr}"
            continue


def _assert_subprocess_run_calls_are_fail_closed(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == "run"
            and isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"
        ):
            continue

        keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
        check = keywords.get("check")
        assert isinstance(check, ast.Constant) and check.value is True, "subprocess.run must use check=True"
        text = keywords.get("text")
        assert isinstance(text, ast.Constant) and text.value is True, "subprocess.run must use text=True"
        for stream_name in ("stdout", "stderr"):
            stream = keywords.get(stream_name)
            assert (
                isinstance(stream, ast.Attribute)
                and stream.attr == "PIPE"
                and isinstance(stream.value, ast.Name)
                and stream.value.id == "subprocess"
            ), f"subprocess.run must capture {stream_name}=subprocess.PIPE"


def _assert_verifier_subprocesses_are_worker_safe() -> None:
    verifier_path = Path(__file__).resolve()
    _assert_no_unreviewed_process_invocations(verifier_path)
    _assert_subprocess_run_calls_are_fail_closed(verifier_path)
    commands = _literal_subprocess_run_commands(verifier_path)
    assert commands, "expected explicit subprocess proof commands"
    for command in commands:
        command_text = " ".join(command).lower()
        assert command[0] == "git", command
        for forbidden_fragment in (
            "run_chummer_design_supervisor",
            "chummer_design_supervisor.py",
            "supervisor status",
            "supervisor eta",
            "active-run helper",
            "active run helper",
            "operator telemetry",
            "ooda",
        ):
            assert forbidden_fragment not in command_text, command


def _single_package_row(items: list, package_id: str) -> dict:
    matches = [dict(item) for item in (items or []) if str(dict(item).get("package_id") or "") == package_id]
    assert len(matches) == 1, f"{package_id} row count: {len(matches)}"
    return matches[0]


def _assert_m103_queue_proof_is_scoped(proof: set[str]) -> None:
    allowed_absolute_prefixes = (
        "/docker/EA/docs/",
        "/docker/EA/tests/",
        "/docker/EA/skills/",
    )
    allowed_published_receipt = "/docker/EA/.codex-studio/published/CHUMMER5A_PARITY_ORACLE_PACK.generated.json"
    direct_command = "python tests/test_chummer5a_parity_lab_pack.py"

    for anchor in proof:
        if anchor.startswith("/docker/EA/"):
            assert anchor.startswith(allowed_absolute_prefixes) or anchor == allowed_published_receipt, anchor
            continue
        if anchor == direct_command or anchor.startswith(f"{direct_command} exits with "):
            continue
        if re.fullmatch(r"/docker/EA commit [0-9a-f]{7,40} .+", anchor):
            continue
        raise AssertionError(f"unscoped M103 proof anchor: {anchor}")


def _assert_m103_registry_evidence_is_scoped(evidence_items: list[str]) -> None:
    allowed_absolute_prefixes = (
        "/docker/fleet/docs/chummer5a-oracle/",
        "/docker/fleet/tests/test_ea_parity_lab_capture_pack.py",
        "/docker/fleet/feedback/2026-04-18-next90-m103-ea-parity-lab-closeout.md",
    )
    allowed_command_prefix = "python3 tests/test_ea_parity_lab_capture_pack.py exits 0 in /docker/fleet."

    for item in evidence_items:
        if item.startswith(allowed_absolute_prefixes):
            continue
        if item.startswith(allowed_command_prefix):
            continue
        raise AssertionError(f"unscoped M103 registry evidence item: {item}")


def _assert_only_frozen_canonical_proof_floor(proof_anchors: set[str], registry_evidence: str) -> None:
    allowed_commit_anchor = CANONICAL_QUEUE_PROOF_FLOOR
    commit_anchor_pattern = re.compile(r"/docker/EA commit [0-9a-f]{7,40} .+")

    for anchor in proof_anchors:
        if commit_anchor_pattern.fullmatch(anchor):
            assert anchor.startswith(allowed_commit_anchor), anchor

    registry_commit_anchors = commit_anchor_pattern.findall(registry_evidence)
    assert registry_commit_anchors
    assert len(registry_commit_anchors) == 1, registry_commit_anchors
    assert registry_commit_anchors[0].startswith(allowed_commit_anchor), registry_commit_anchors


def _assert_frozen_canonical_proof_commit_resolves(proof_anchors: set[str], registry_evidence: str) -> None:
    proof_text = "\n".join(sorted(proof_anchors)) + "\n" + registry_evidence
    matches = sorted(set(re.findall(r"/docker/EA commit ([0-9a-f]{7,40}) .+", proof_text)))

    assert matches == ["f252c02"], matches
    subject = subprocess.run(
        ["git", "-C", str(ROOT), "show", "--no-patch", "--format=%s", matches[0]],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    assert subject == "Pin M103 latest parity lab proof floor"

    changed_paths = subprocess.run(
        ["git", "-C", str(ROOT), "diff-tree", "--no-commit-id", "--name-only", "-r", matches[0]],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.splitlines()
    assert set(changed_paths) == {
        ".codex-studio/published/CHUMMER5A_PARITY_ORACLE_PACK.generated.json",
        "docs/chummer5a_parity_lab/SUCCESSOR_HANDOFF_CLOSEOUT.yaml",
        "tests/test_chummer5a_parity_lab_pack.py",
    }


def test_pack_contract_tracks_milestone_and_owned_surfaces() -> None:
    pack = _yaml(PACK_PATH)

    assert pack.get("contract_name") == "ea.chummer5a_parity_lab_pack"
    assert pack.get("package_id") == "next90-m103-ea-parity-lab"
    assert int(pack.get("milestone_id") or 0) == 103
    assert pack.get("status") == "task_proven"
    assert list(pack.get("owned_surfaces") or []) == ["parity_lab:capture", "veteran_compare_packs"]


def test_pack_contract_matches_canonical_successor_registry_and_queue() -> None:
    pack = _yaml(PACK_PATH)
    receipt = _yaml(PUBLISHED_PACK_PATH)
    registry = _yaml(SUCCESSOR_REGISTRY_PATH)
    design_queue = _yaml(DESIGN_SUCCESSOR_QUEUE_PATH)
    queue = _yaml(SUCCESSOR_QUEUE_PATH)
    proof_result = str(dict(receipt.get("proof") or {}).get("result") or "")

    expected_queue_header = {
        "program_wave": "next_90_day_product_advance",
        "status": "live_parallel_successor",
        "source_registry_path": SUCCESSOR_REGISTRY_PATH.as_posix(),
    }
    for queue_source in (design_queue, queue):
        for key, expected in expected_queue_header.items():
            assert queue_source.get(key) == expected
    assert queue.get("source_design_queue_path") == DESIGN_SUCCESSOR_QUEUE_PATH.as_posix()

    milestones = {int(dict(item).get("id") or 0): dict(item) for item in (registry.get("milestones") or [])}
    milestone = milestones[103]
    assert milestone.get("title") == "Chummer5a parity lab and veteran migration certification"
    assert milestone.get("wave") == "W7"
    assert "executive-assistant" in set(milestone.get("owners") or [])
    assert 101 in set(milestone.get("dependencies") or [])
    assert 102 in set(milestone.get("dependencies") or [])
    task_103_1_matches = [dict(task) for task in (milestone.get("work_tasks") or []) if dict(task).get("id") == 103.1]
    assert len(task_103_1_matches) == 1, f"103.1 work task row count: {len(task_103_1_matches)}"
    task_103_1 = task_103_1_matches[0]
    assert task_103_1.get("owner") == "executive-assistant"
    assert task_103_1.get("status") == "complete"
    assert "landed_commit" not in task_103_1
    task_evidence_items = [str(item) for item in (task_103_1.get("evidence") or [])]
    _assert_m103_registry_evidence_is_scoped(task_evidence_items)
    expected_registry_evidence = {
        "/docker/fleet/docs/chummer5a-oracle/parity_lab_capture_pack.yaml records the Chummer5a screenshot "
        "baselines, import/export fixtures, screenshot artifact mappings, and desktop non-negotiable crosswalk "
        "for owned surface parity_lab:capture.",
        "/docker/fleet/docs/chummer5a-oracle/veteran_workflow_packs.yaml records first-minute veteran tasks, "
        "workflow maps, flagship parity families, and tuple compare packs for owned surface veteran_compare_packs.",
        "/docker/fleet/docs/chummer5a-oracle/README.md documents the closed Fleet proof boundary, worker-safe "
        "telemetry inputs, and the anti-reopen rule for repeated M103 assignments.",
        "/docker/fleet/tests/test_ea_parity_lab_capture_pack.py fail-closes stale sync context, missing Chummer5a "
        "anchors, missing screenshot mappings, missing veteran compare packs, and canonical queue or registry "
        "closure drift for this completed package.",
        "/docker/fleet/feedback/2026-04-18-next90-m103-ea-parity-lab-closeout.md records the canonical proof "
        "relocation from stale /docker/EA artifacts to the Fleet-owned package paths.",
        "python3 tests/test_ea_parity_lab_capture_pack.py exits 0 in /docker/fleet.",
    }
    assert set(task_evidence_items) == expected_registry_evidence
    assert len(task_evidence_items) == len(expected_registry_evidence)
    task_evidence = "\n".join(task_evidence_items)
    assert "parity_lab_capture_pack.yaml records the Chummer5a screenshot baselines" in task_evidence
    assert "veteran_workflow_packs.yaml records first-minute veteran tasks" in task_evidence
    assert "README.md documents the closed Fleet proof boundary" in task_evidence
    assert "python3 tests/test_ea_parity_lab_capture_pack.py exits 0 in /docker/fleet." in task_evidence

    expected_design_queue_proof = {
        "/docker/fleet/docs/chummer5a-oracle/README.md",
        "/docker/fleet/docs/chummer5a-oracle/parity_lab_capture_pack.yaml",
        "/docker/fleet/docs/chummer5a-oracle/veteran_workflow_packs.yaml",
        "/docker/fleet/tests/test_ea_parity_lab_capture_pack.py",
        "/docker/fleet/feedback/2026-04-18-next90-m103-ea-parity-lab-closeout.md",
        "python3 tests/test_ea_parity_lab_capture_pack.py",
        "python3 tests/test_ea_parity_lab_capture_pack.py exits 0 in /docker/fleet and fail-closes stale /docker/EA parity-lab closure references for the completed package.",
    }
    design_queue_item = _single_package_row(design_queue.get("items") or [], "next90-m103-ea-parity-lab")
    queue_item = _single_package_row(queue.get("items") or [], "next90-m103-ea-parity-lab")
    for current_queue_item in (design_queue_item, queue_item):
        assert current_queue_item.get("repo") == "executive-assistant"
        assert current_queue_item.get("status") == "complete"
        assert current_queue_item.get("completion_action") == "verify_closed_package_only"
        assert "verify this receipt, registry row, design queue row, Fleet queue row, and direct proof command" in str(
            current_queue_item.get("do_not_reopen_reason") or ""
        )
        assert "recapturing Chummer5a oracle baselines or veteran workflow packs" in str(
            current_queue_item.get("do_not_reopen_reason") or ""
        )
        assert "landed_commit" not in current_queue_item
        assert int(current_queue_item.get("frontier_id") or 0) == 4287684466
        assert int(current_queue_item.get("milestone_id") or 0) == int(pack.get("milestone_id") or 0) == 103
        assert current_queue_item.get("wave") == milestone.get("wave") == "W7"
        assert list(current_queue_item.get("allowed_paths") or []) == ["skills", "tests", "feedback", "docs"]
        assert list(current_queue_item.get("owned_surfaces") or []) == list(pack.get("owned_surfaces") or [])
        assert current_queue_item.get("title") == "Extract Chummer5a oracle baselines and veteran workflow packs"

    design_proof = set(str(item) for item in (design_queue_item.get("proof") or []))
    assert design_proof == expected_design_queue_proof
    assert len(design_queue_item.get("proof") or []) == len(expected_design_queue_proof)
    for proof_anchor in design_proof:
        if proof_anchor.startswith("/docker/EA/") or proof_anchor.startswith("/docker/fleet/"):
            assert Path(proof_anchor).exists(), proof_anchor

    fleet_proof = set(str(item) for item in (queue_item.get("proof") or []))
    expected_fleet_queue_proof = expected_design_queue_proof
    assert fleet_proof == expected_fleet_queue_proof
    assert len(queue_item.get("proof") or []) == len(expected_fleet_queue_proof)
    for proof_anchor in fleet_proof:
        if proof_anchor.startswith("/docker/fleet/"):
            assert Path(proof_anchor).exists(), proof_anchor


def test_canonical_queue_proof_excludes_feedback_notes_for_closed_ea_scope() -> None:
    design_queue = _yaml(DESIGN_SUCCESSOR_QUEUE_PATH)
    queue = _yaml(SUCCESSOR_QUEUE_PATH)

    design_queue_item = _single_package_row(design_queue.get("items") or [], "next90-m103-ea-parity-lab")
    design_proof = [str(item) for item in (design_queue_item.get("proof") or [])]
    assert design_proof, design_queue
    assert not any("/docker/EA/feedback/" in anchor or anchor.startswith("feedback/") for anchor in design_proof)
    assert "/docker/fleet/feedback/2026-04-18-next90-m103-ea-parity-lab-closeout.md" in design_proof
    assert "/docker/fleet/docs/chummer5a-oracle/parity_lab_capture_pack.yaml" in design_proof
    assert "/docker/fleet/docs/chummer5a-oracle/veteran_workflow_packs.yaml" in design_proof
    assert "python3 tests/test_ea_parity_lab_capture_pack.py" in design_proof

    fleet_queue_item = _single_package_row(queue.get("items") or [], "next90-m103-ea-parity-lab")
    fleet_proof = [str(item) for item in (fleet_queue_item.get("proof") or [])]
    assert fleet_proof, queue
    assert "/docker/fleet/feedback/2026-04-18-next90-m103-ea-parity-lab-closeout.md" in fleet_proof
    assert not any("/docker/EA/feedback/" in anchor or anchor.startswith("feedback/") for anchor in fleet_proof)
    assert "/docker/fleet/docs/chummer5a-oracle/parity_lab_capture_pack.yaml" in fleet_proof
    assert "/docker/fleet/docs/chummer5a-oracle/veteran_workflow_packs.yaml" in fleet_proof
    assert "python3 tests/test_ea_parity_lab_capture_pack.py" in fleet_proof


def test_pack_required_outputs_exist_on_disk() -> None:
    pack = _yaml(PACK_PATH)
    outputs = dict(pack.get("required_outputs") or {})

    expected = {
        "screenshot_corpora": ORACLE_BASELINES_PATH,
        "workflow_maps": WORKFLOW_PACK_PATH,
        "compare_packs": COMPARE_PACKS_PATH,
        "import_export_fixture_inventory": FIXTURE_INVENTORY_PATH,
    }
    for key, path in expected.items():
        row = dict(outputs.get(key) or {})
        assert row.get("present") is True
        assert row.get("path") == path.relative_to(ROOT).as_posix()
        assert path.exists(), str(path)
        assert row.get("proof_level")
    _assert_oracle_baselines_sync_context_and_line_proofs_match_current_sources()
    _assert_veteran_workflow_pack_syncs_live_receipts_and_tuple_compare_packs()
    _assert_compare_packs_sync_context_matches_current_assignment()


def _assert_oracle_baselines_sync_context_and_line_proofs_match_current_sources() -> None:
    baselines = _yaml(ORACLE_BASELINES_PATH)
    sync_context = dict(baselines.get("worker_safe_resume_context") or {})
    guard = dict(baselines.get("worker_run_guard") or {})

    assert sync_context.get("assignment_mode") == "implementation_only"
    assert sync_context.get("scope_label") == "Next 90-day product advance wave"
    assert sync_context.get("package_id") == "next90-m103-ea-parity-lab"
    assert int(sync_context.get("frontier_id") or 0) == 4287684466
    assert list(sync_context.get("allowed_paths") or []) == ["skills", "tests", "feedback", "docs"]
    assert sync_context.get("readiness_generated_at")
    assert _yaml(FLAGSHIP_READINESS_PATH).get("generated_at")
    sync_runtime_handoff_path = Path(str(sync_context.get("runtime_handoff_path") or ""))
    assert _path_with_worker_safe_alias_fallback(sync_runtime_handoff_path) is not None
    if _active_handoff_targets_closed_m103_package():
        assert sync_context.get("runtime_handoff_path") in _worker_safe_path_aliases(ACTIVE_RUN_HANDOFF_PATH)
    assert guard.get("implementation_only") is True
    assert set(str(item) for item in (guard.get("blocked_helper_evidence") or [])) == {
        "supervisor status helpers",
        "supervisor eta helpers",
        "active-run operator status snippets",
    }

    line_proofs = dict(dict(baselines.get("oracle_surface_extract") or {}).get("source_line_proofs") or {})
    assert set(line_proofs) == {
        "top_menu_landmarks",
        "file_and_settings_routes",
        "first_class_master_index_and_roster",
    }
    for entries in line_proofs.values():
        assert entries
        for entry in entries:
            _assert_source_line_proof(dict(entry))

    tuple_map = dict(baselines.get("desktop_proof_tuple_baseline_map") or {})
    assert tuple_map.get("coverage_key") == "desktop_client"
    assert tuple_map.get("current_unresolved_external_host_proof_tuples") == []
    for row in tuple_map.get("promoted_tuple_compare_packs") or []:
        current = dict(row)
        assert current.get("tuple") in {
            "avalonia:linux-x64:linux",
            "avalonia:osx-arm64:macos",
            "avalonia:win-x64:windows",
        }
        assert list(current.get("required_baseline_ids") or []) == [
            "initial_shell",
            "menu_open",
            "settings_open",
            "master_index_dialog",
            "character_roster_dialog",
        ]


def _assert_veteran_workflow_pack_syncs_live_receipts_and_tuple_compare_packs() -> None:
    workflow_pack = _yaml(WORKFLOW_PACK_PATH)
    sync_context = dict(workflow_pack.get("worker_safe_resume_context") or {})
    exit_gate = _yaml(Path(str(sync_context.get("desktop_executable_exit_gate_path") or "")))

    assert sync_context.get("assignment_mode") == "implementation_only"
    assert int(sync_context.get("frontier_id") or 0) == 4287684466
    assert sync_context.get("readiness_generated_at")
    assert _yaml(FLAGSHIP_READINESS_PATH).get("generated_at")
    assert sync_context.get("desktop_executable_exit_gate_generated_at")
    assert exit_gate.get("generated_at")
    sync_runtime_handoff_path = Path(str(sync_context.get("runtime_handoff_path") or ""))
    assert _path_with_worker_safe_alias_fallback(sync_runtime_handoff_path) is not None
    if _active_handoff_targets_closed_m103_package():
        assert sync_context.get("runtime_handoff_path") in _worker_safe_path_aliases(ACTIVE_RUN_HANDOFF_PATH)

    desktop_client_coverage = dict(workflow_pack.get("desktop_client_coverage") or {})
    assert desktop_client_coverage.get("coverage_key") == "desktop_client"
    assert desktop_client_coverage.get("baseline_manifest") == ORACLE_BASELINES_PATH.relative_to(ROOT).as_posix()
    assert desktop_client_coverage.get("current_unresolved_external_host_proof_tuples") == []
    tuple_rows = [dict(item) for item in (desktop_client_coverage.get("tuple_compare_packs") or [])]
    assert len(tuple_rows) == 3
    for row in tuple_rows:
        assert list(row.get("first_minute_tasks") or []) == [
            "reach_real_workbench",
            "locate_save_import_settings",
            "locate_master_index_and_roster",
        ]
        assert list(row.get("required_baseline_ids") or []) == [
            "initial_shell",
            "menu_open",
            "settings_open",
            "master_index_dialog",
            "character_roster_dialog",
        ]

    frontier_context = dict(workflow_pack.get("assignment_focus_context") or {})
    assert int(frontier_context.get("frontier_id") or 0) == 4287684466
    assert "executive-assistant" in set(frontier_context.get("owner_focus") or [])
    assert "next90-m103-ea-parity-lab" in set(frontier_context.get("text_focus") or [])
    assert frontier_context.get("assignment_brief")

    whole_product_coverage = dict(workflow_pack.get("whole_product_frontier_coverage") or {})
    assert whole_product_coverage.get("source_readiness_path") == FLAGSHIP_READINESS_PATH.as_posix()
    lanes = {dict(item).get("coverage_key"): dict(item) for item in (whole_product_coverage.get("lanes") or [])}
    assert lanes["fleet_and_operator_loop"].get("live_readiness_status") == "ready"
    assert lanes["desktop_client"].get("live_readiness_status") == "ready"

    live_exit_gate = dict(workflow_pack.get("live_desktop_executable_gate_snapshot") or {})
    assert live_exit_gate.get("source_path") == Path(
        "/docker/chummercomplete/chummer6-ui/.codex-studio/published/DESKTOP_EXECUTABLE_EXIT_GATE.generated.json"
    ).as_posix()
    assert live_exit_gate.get("generated_at")
    assert exit_gate.get("generated_at")
    assert live_exit_gate.get("status") == exit_gate.get("status") == "pass"
    assert live_exit_gate.get("blocking_findings_count") == 0
    assert live_exit_gate.get("local_blocking_findings_count") == 0
    assert live_exit_gate.get("external_blocking_findings_count") == 0
    assert live_exit_gate.get("blocked_by_external_constraints_only") is False
    assert live_exit_gate.get("unresolved_external_host_proof_tuples") == []

    screenshot_snapshot = dict(workflow_pack.get("visual_familiarity_screenshot_snapshot") or {})
    assert screenshot_snapshot.get("missing_screenshots") == []
    required_screenshots = [str(item) for item in (screenshot_snapshot.get("required_screenshots") or [])]
    assert "16-master-index-dialog-light.png" in required_screenshots
    assert "17-character-roster-dialog-light.png" in required_screenshots
    assert "18-import-dialog-light.png" in required_screenshots


def _assert_compare_packs_sync_context_matches_current_assignment() -> None:
    compare_packs = _yaml(COMPARE_PACKS_PATH)
    sync_context = dict(compare_packs.get("worker_safe_resume_context") or {})

    assert sync_context.get("assignment_mode") == "implementation_only"
    assert int(sync_context.get("frontier_id") or 0) == 4287684466
    assert sync_context.get("readiness_path") == FLAGSHIP_READINESS_PATH.as_posix()
    assert sync_context.get("readiness_generated_at")
    assert _yaml(FLAGSHIP_READINESS_PATH).get("generated_at")
    sync_runtime_handoff_path = Path(str(sync_context.get("runtime_handoff_path") or ""))
    assert _path_with_worker_safe_alias_fallback(sync_runtime_handoff_path) is not None
    if _active_handoff_targets_closed_m103_package():
        assert sync_context.get("runtime_handoff_path") in _worker_safe_path_aliases(ACTIVE_RUN_HANDOFF_PATH)


def test_published_parity_oracle_receipt_matches_task_proven_pack() -> None:
    pack = _yaml(PACK_PATH)
    strict_json_receipt = json.loads(PUBLISHED_PACK_PATH.read_text(encoding="utf-8"))
    receipt = _yaml(PUBLISHED_PACK_PATH)

    assert strict_json_receipt == receipt
    assert receipt.get("contract_name") == "ea.chummer5a_parity_oracle_pack"
    assert receipt.get("package_id") == pack.get("package_id") == "next90-m103-ea-parity-lab"
    assert int(receipt.get("milestone_id") or 0) == int(pack.get("milestone_id") or 0) == 103
    assert receipt.get("status") == pack.get("status") == "task_proven"
    assert list(receipt.get("owned_surfaces") or []) == list(pack.get("owned_surfaces") or [])

    outputs = dict(receipt.get("outputs") or {})
    assert outputs == {
        "screenshot_corpora": True,
        "workflow_maps": True,
        "compare_packs": True,
        "import_export_fixture_inventory": True,
    }
    output_paths = dict(receipt.get("output_paths") or {})
    assert output_paths == {
        "screenshot_corpora": ORACLE_BASELINES_PATH.relative_to(ROOT).as_posix(),
        "workflow_maps": WORKFLOW_PACK_PATH.relative_to(ROOT).as_posix(),
        "compare_packs": COMPARE_PACKS_PATH.relative_to(ROOT).as_posix(),
        "import_export_fixture_inventory": FIXTURE_INVENTORY_PATH.relative_to(ROOT).as_posix(),
        "handoff_closeout": HANDOFF_CLOSEOUT_PATH.relative_to(ROOT).as_posix(),
    }
    for output_path in output_paths.values():
        assert (ROOT / str(output_path)).exists(), output_path
    assert receipt.get("blocking_reasons") == []
    assert receipt.get("current_limitations") == []
    operator_summary = str(receipt.get("operator_summary") or "")
    assert "promoted-head certification is canonically complete" in operator_summary
    assert "design and Fleet follow-up work remaining non-EA" in operator_summary
    proof = dict(receipt.get("proof") or {})
    assert proof.get("command") == "python tests/test_chummer5a_parity_lab_pack.py"
    assert proof.get("result") == _expected_direct_result()

    successor_closure = dict(receipt.get("successor_closure") or {})
    assert int(successor_closure.get("successor_frontier_id") or 0) == 4287684466
    assert successor_closure.get("registry") == SUCCESSOR_REGISTRY_PATH.as_posix()
    assert successor_closure.get("design_queue") == DESIGN_SUCCESSOR_QUEUE_PATH.as_posix()
    assert successor_closure.get("fleet_queue") == SUCCESSOR_QUEUE_PATH.as_posix()
    assert successor_closure.get("active_handoff_min_generated_at") >= "2026-04-15T14:32:18Z"
    receipt_proof_commits = [str(commit) for commit in (successor_closure.get("local_proof_commits") or [])]
    assert {
        "f3a3649",
        "528c278",
        "98313c9",
        "5d56f66",
        "4e6b1d8",
        "357ee65",
        "d3f164c",
        "9cd70ea",
        "b880b75",
        "4dda75d",
        "466d7e4",
        "6ed29ce",
        "76a3acc",
        "c83eca2",
        "a57fc43",
        "f244a62",
        "7b7da3e",
        "945ed7b",
        "ac84501",
        "1dfb104",
        "dfdfa45",
        "e1289e7",
        "e8ec699",
        "48ae7bc",
        "c28df5a",
        "e706014",
        "87ad539",
        "4d186b6",
        "d274b66",
        "1783ee6",
        "0284b0a",
        "a8a8f72",
        "04408e3",
        "1a71457",
        "08fc645",
        "24a16a4",
        "724d2c1",
        "94be27c",
        "f252c02",
        "03da40e",
        "4d07436",
        "a2ae08f",
        "3f74d5d",
        "1eddb6d",
        "257a5b7",
    } <= set(receipt_proof_commits)
    for commit in receipt_proof_commits:
        subprocess.run(
            ["git", "-C", str(ROOT), "cat-file", "-e", f"{commit}^{{commit}}"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    proof_hygiene = dict(successor_closure.get("proof_hygiene") or {})
    assert proof_hygiene.get("operator_owned_run_helpers_invoked") is False
    assert proof_hygiene.get("operator_owned_helper_output_cited") is False

    terminal_policy = dict(successor_closure.get("terminal_verification_policy") or {})
    assert terminal_policy.get("status") == "terminal_for_ea_scope"
    assert terminal_policy.get("latest_required_handoff_floor") == "2026-04-15T16:20:33Z"
    assert terminal_policy.get("no_timestamp_chasing_required") is True
    assert terminal_policy.get("no_operator_helper_evidence_allowed") is True
    assert terminal_policy.get("closed_scope_guard_test") == "test_terminal_verification_policy_stops_timestamp_chasing"
    assert set(str(item) for item in (terminal_policy.get("allowed_next_work") or [])) == {
        "next90-m103-design-parity-ladder",
        "next90-m103-fleet-readiness-consumption",
    }
    completed_non_ea_work = [dict(item) for item in (terminal_policy.get("completed_non_ea_work") or [])]
    assert completed_non_ea_work == [
        {
            "package_id": "next90-m103-ui-veteran-certification",
            "owner": "chummer6-ui",
            "registry_task_id": "103.2",
            "status": "complete",
        }
    ]
    current_or_newer_rule = str(terminal_policy.get("current_or_newer_handoff_rule") or "")
    assert "assignment context only" in current_or_newer_rule
    assert "not a reason to edit this EA package" in current_or_newer_rule
    assert "direct proof command" in current_or_newer_rule
    handoff_mode_rule = str(terminal_policy.get("handoff_mode_rule") or "")
    assert "assignment metadata only" in handoff_mode_rule
    assert "Mode: unknown" in handoff_mode_rule
    assert "Mode: completion_review" in handoff_mode_rule
    assert "Mode: flagship_product" in handoff_mode_rule
    assert "frontier/package identity" in handoff_mode_rule


def test_successor_handoff_closeout_prevents_repeating_ea_scope() -> None:
    pack = _yaml(PACK_PATH)
    closeout = _yaml(HANDOFF_CLOSEOUT_PATH)
    registry = _yaml(SUCCESSOR_REGISTRY_PATH)
    design_queue = _yaml(DESIGN_SUCCESSOR_QUEUE_PATH)
    queue = _yaml(SUCCESSOR_QUEUE_PATH)

    assert closeout.get("contract_name") == "ea.chummer5a_parity_lab_successor_handoff_closeout"
    assert closeout.get("package_id") == pack.get("package_id") == "next90-m103-ea-parity-lab"
    assert int(closeout.get("milestone_id") or 0) == int(pack.get("milestone_id") or 0) == 103
    assert closeout.get("status") == "ea_scope_complete"
    assert set(closeout.get("closed_surfaces") or []) == set(pack.get("owned_surfaces") or [])

    local_proof_commits = [dict(item) for item in (closeout.get("local_proof_commits") or [])]
    assert local_proof_commits
    for proof_commit in local_proof_commits:
        commit = str(proof_commit.get("commit") or "")
        assert re.fullmatch(r"[0-9a-f]{7,40}", commit), commit
        assert str(proof_commit.get("subject") or "").strip()
        assert str(proof_commit.get("purpose") or "").strip()
        subprocess.run(
            ["git", "-C", str(ROOT), "cat-file", "-e", f"{commit}^{{commit}}"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    closure_scope = dict(closeout.get("closure_scope") or {})
    assert closure_scope.get("allowed_paths") == ["skills", "tests", "feedback", "docs"]
    assert closure_scope.get("package_only") is True
    assert closure_scope.get("closed_package_only") == "next90-m103-ea-parity-lab"
    assert set(closure_scope.get("forbidden_reopen_targets") or []) == {
        "flagship_closeout_wave",
        "promoted_head_veteran_certification",
    }

    completed_outputs = {ROOT / str(path) for path in (closeout.get("completed_outputs") or [])}
    assert {
        PACK_PATH,
        ORACLE_BASELINES_PATH,
        WORKFLOW_PACK_PATH,
        COMPARE_PACKS_PATH,
        FIXTURE_INVENTORY_PATH,
        HANDOFF_CLOSEOUT_PATH,
        PUBLISHED_PACK_PATH,
    } <= completed_outputs
    for path in completed_outputs:
        assert path.exists(), str(path)

    proof = dict(closeout.get("proof") or {})
    assert proof.get("command") == "python tests/test_chummer5a_parity_lab_pack.py"
    assert proof.get("result") == _expected_direct_result()

    repeat_verifications = [dict(item) for item in (closeout.get("repeat_verifications") or [])]
    assert repeat_verifications
    latest_repeat = repeat_verifications[-1]
    assert latest_repeat.get("verified_at") >= proof.get("verified_at")
    assert _active_handoff_generated_at() >= str(latest_repeat.get("active_handoff_generated_at") or "")
    assert int(latest_repeat.get("frontier_id") or 0) == 4287684466
    assert latest_repeat.get("package_id") == pack.get("package_id")
    assert latest_repeat.get("result") == "registry=complete design_queue=complete fleet_queue=complete proof=ran=16 failed=0 local_proof_commit=d274b66"
    assert str(latest_repeat.get("result") or "") != (
        f"registry=complete design_queue=complete fleet_queue=complete proof={_expected_direct_result()} "
        "local_proof_commit=d274b66"
    )
    assert "do not recapture parity-lab artifacts" in str(latest_repeat.get("worker_rule") or "")
    assert "at-least-this-new worker-safe active handoff" in str(latest_repeat.get("worker_rule") or "")
    assert "design-owned completed queue row" in str(latest_repeat.get("worker_rule") or "")
    assert "Fleet completed queue mirror" in str(latest_repeat.get("worker_rule") or "")
    assert "direct proof command" in str(latest_repeat.get("worker_rule") or "")
    assert "resolving local handoff proof commit d274b66" in str(latest_repeat.get("worker_rule") or "")
    assert "invoke operator-owned run helpers" in str(latest_repeat.get("worker_rule") or "")
    assert "cite operator-owned helper output" in str(latest_repeat.get("worker_rule") or "")

    closure_markers = dict(closeout.get("canonical_closure_markers") or {})
    assert closure_markers.get("successor_registry_work_task") == "103.1 status=complete"
    assert closure_markers.get("design_queue_completed_package") == "next90-m103-ea-parity-lab status=complete frontier=4287684466"
    assert closure_markers.get("queue_package") == "next90-m103-ea-parity-lab status=complete"
    assert closure_markers.get("queue_proof_command") == "python tests/test_chummer5a_parity_lab_pack.py"
    assert closure_markers.get("active_handoff_frontier") == "4287684466 focused_package=next90-m103-ea-parity-lab"

    canonical_sources = dict(closeout.get("canonical_successor_sources") or {})
    assert canonical_sources.get("design_queue") == DESIGN_SUCCESSOR_QUEUE_PATH.as_posix()
    assert "active_run_handoff" not in canonical_sources
    if _active_handoff_targets_closed_m103_package():
        active_handoff_text = ACTIVE_RUN_HANDOFF_PATH.read_text(encoding="utf-8")
        active_prompt_text = _active_handoff_prompt_text()
        task_local_telemetry = _yaml(_task_local_telemetry_path())
        assert "Frontier ids: 4287684466" in active_handoff_text
        focus_owners = set(str(item) for item in (task_local_telemetry.get("focus_owners") or []))
        assert "executive-assistant" in focus_owners
        assert focus_owners <= {
            "chummer6-ui",
            "chummer6-core",
            "chummer6-design",
            "executive-assistant",
        }
        assert "next90-m103-ea-parity-lab" in active_prompt_text
        assert "Extract Chummer5a oracle baselines and veteran workflow packs" in active_prompt_text
        telemetry_first_commands = [str(item) for item in (task_local_telemetry.get("first_commands") or [])]
        assert telemetry_first_commands, "task-local telemetry must preserve the worker startup command block"
        assert telemetry_first_commands[0] == "cat TASK_LOCAL_TELEMETRY.generated.json"
        assert telemetry_first_commands[1] == (
            "sed -n '1,220p' /docker/fleet/.codex-studio/published/NEXT_90_DAY_QUEUE_STAGING.generated.yaml"
        )
        assert telemetry_first_commands[2] == (
            "sed -n '1,220p' "
            "/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml"
        )
        assert any(command.endswith("/PROGRAM_MILESTONES.yaml") for command in telemetry_first_commands)
        assert not any("supervisor status" in command.lower() for command in telemetry_first_commands)
        assert not any("supervisor eta" in command.lower() for command in telemetry_first_commands)
        assert task_local_telemetry.get("mode") == "implementation_only"
        assert task_local_telemetry.get("polling_disabled") is True
        assert task_local_telemetry.get("status_query_supported") is False
        queue_item = dict(task_local_telemetry.get("queue_item") or {})
        assert queue_item.get("repo") == "executive-assistant"
        assert queue_item.get("package_id") == "next90-m103-ea-parity-lab"
        assert int(queue_item.get("milestone_id") or 0) == 103
        assert list(queue_item.get("allowed_paths") or []) == ["skills", "tests", "feedback", "docs"]
        assert list(queue_item.get("owned_surfaces") or []) == [
            "parity_lab:capture",
            "veteran_compare_packs",
        ]
        task_local_telemetry_aliases = _worker_safe_path_aliases(_task_local_telemetry_path())
        active_handoff_aliases = _worker_safe_path_aliases(ACTIVE_RUN_HANDOFF_PATH)
        assert (
            "Start by reading these files directly:" in active_prompt_text
            or "Read these files directly first:" in active_prompt_text
        )
        assert any(path in active_prompt_text for path in task_local_telemetry_aliases), task_local_telemetry_aliases
        assert "/docker/chummercomplete/chummer-design/products/chummer/NEXT_12_BIGGEST_WINS_REGISTRY.yaml" in active_prompt_text
        assert "/docker/chummercomplete/chummer-design/products/chummer/PROGRAM_MILESTONES.yaml" in active_prompt_text
        assert "/docker/chummercomplete/chummer-design/products/chummer/ROADMAP.md" in active_prompt_text
        assert any(path in active_prompt_text for path in active_handoff_aliases), active_handoff_aliases
        assert SUCCESSOR_REGISTRY_PATH.as_posix() in active_prompt_text
        assert SUCCESSOR_QUEUE_PATH.as_posix() in active_prompt_text
        assert _active_handoff_generated_at() >= str(latest_repeat.get("active_handoff_generated_at") or "")

    repeat_prevention = dict(closeout.get("repeat_prevention") or {})
    assert int(repeat_prevention.get("successor_frontier_id") or 0) == 4287684466
    assert repeat_prevention.get("active_handoff_verified_at") == latest_repeat.get("verified_at")
    assert repeat_prevention.get("active_handoff_min_generated_at") == latest_repeat.get("active_handoff_generated_at")
    assert _active_handoff_generated_at() >= str(repeat_prevention.get("active_handoff_min_generated_at") or "")
    assert repeat_prevention.get("active_handoff_focus_required") == "next90-m103-ea-parity-lab"
    assert repeat_prevention.get("active_handoff_owned_surfaces_required") == [
        "parity_lab:capture",
        "veteran_compare_packs",
    ]
    assert repeat_prevention.get("registry_task_status_required") == "complete"
    assert repeat_prevention.get("design_queue_completed_package_required") == "next90-m103-ea-parity-lab status=complete frontier=4287684466"
    assert repeat_prevention.get("queue_package_status_required") == "complete"
    assert repeat_prevention.get("repeat_guard_test") == "test_successor_handoff_closeout_prevents_repeating_ea_scope"
    assert repeat_prevention.get("blocked_helper_guard_test") == "test_successor_closeout_does_not_use_active_run_helper_commands"
    assert repeat_prevention.get("local_proof_commit_guard_test") == "test_successor_handoff_closeout_prevents_repeating_ea_scope"
    assert "delegated non-EA follow-up packages" in str(repeat_prevention.get("worker_rule") or "")

    milestones = {int(dict(item).get("id") or 0): dict(item) for item in (registry.get("milestones") or [])}
    task_103_1_matches = [dict(task) for task in (milestones[103].get("work_tasks") or []) if dict(task).get("id") == 103.1]
    assert len(task_103_1_matches) == 1, f"103.1 work task row count: {len(task_103_1_matches)}"
    task_103_1 = task_103_1_matches[0]
    assert task_103_1.get("status") == repeat_prevention.get("registry_task_status_required") == "complete"

    queue_item = _single_package_row(queue.get("items") or [], "next90-m103-ea-parity-lab")
    assert int(queue_item.get("frontier_id") or 0) == int(repeat_prevention.get("successor_frontier_id") or 0)
    assert queue_item.get("status") == repeat_prevention.get("queue_package_status_required") == "complete"

    design_queue_item = _single_package_row(design_queue.get("items") or [], "next90-m103-ea-parity-lab")
    assert int(design_queue_item.get("frontier_id") or 0) == int(repeat_prevention.get("successor_frontier_id") or 0)
    assert design_queue_item.get("status") == queue_item.get("status") == "complete"
    assert list(design_queue_item.get("allowed_paths") or []) == ["skills", "tests", "feedback", "docs"]
    assert list(design_queue_item.get("owned_surfaces") or []) == [
        "parity_lab:capture",
        "veteran_compare_packs",
    ]

    completed_non_ea = [dict(item) for item in (closeout.get("completed_non_ea_work") or [])]
    assert completed_non_ea == [
        {
            "package_id": "next90-m103-ui-veteran-certification",
            "owner": "chummer6-ui",
            "registry_task_id": 103.2,
            "status": "complete",
            "reason": (
                "Canonical successor registry task 103.2 reports the promoted-head screenshot-backed veteran "
                "certification package complete, so repeated EA workers must not reopen or recapture it."
            ),
        }
    ]
    remaining = {str(dict(item).get("owner") or "") for item in (closeout.get("remaining_non_ea_work") or [])}
    assert "executive-assistant" not in remaining
    assert remaining == {"chummer6-design", "fleet"}

    anti_reopen_rules = "\n".join(str(item) for item in (closeout.get("anti_reopen_rules") or []))
    assert "Do not reopen the closed flagship closeout wave" in anti_reopen_rules
    assert "promoted-head screenshot certification" in anti_reopen_rules


def test_successor_handoff_closeout_outputs_stay_inside_assigned_scope() -> None:
    closeout = _yaml(HANDOFF_CLOSEOUT_PATH)
    closure_scope = dict(closeout.get("closure_scope") or {})
    allowed_roots = tuple(f"{root}/" for root in (closure_scope.get("allowed_paths") or []))

    assert allowed_roots == ("skills/", "tests/", "feedback/", "docs/")
    for output in closeout.get("completed_outputs") or []:
        output_path = str(output)
        assert (
            output_path.startswith(allowed_roots)
            or output_path == PUBLISHED_PACK_PATH.relative_to(ROOT).as_posix()
        ), output_path


def test_terminal_verification_policy_stops_timestamp_chasing() -> None:
    closeout = _yaml(HANDOFF_CLOSEOUT_PATH)
    receipt = _yaml(PUBLISHED_PACK_PATH)
    pack = _yaml(PACK_PATH)
    registry = _yaml(SUCCESSOR_REGISTRY_PATH)
    design_queue = _yaml(DESIGN_SUCCESSOR_QUEUE_PATH)
    queue = _yaml(SUCCESSOR_QUEUE_PATH)
    repeat_prevention = dict(closeout.get("repeat_prevention") or {})
    terminal_policy = dict(closeout.get("terminal_verification_policy") or {})
    receipt_policy = dict(dict(receipt.get("successor_closure") or {}).get("terminal_verification_policy") or {})
    readme_text = README_PATH.read_text(encoding="utf-8")
    active_handoff_text = ACTIVE_RUN_HANDOFF_PATH.read_text(encoding="utf-8")
    active_prompt_text = _active_handoff_prompt_text()

    assert terminal_policy.get("status") == "terminal_for_ea_scope"
    assert receipt_policy == terminal_policy
    assert terminal_policy.get("latest_required_handoff_floor") == repeat_prevention.get(
        "active_handoff_min_generated_at"
    )
    assert _active_handoff_generated_at() >= str(terminal_policy.get("latest_required_handoff_floor") or "")
    assert terminal_policy.get("no_timestamp_chasing_required") is True
    assert terminal_policy.get("no_operator_helper_evidence_allowed") is True
    assert terminal_policy.get("closed_scope_guard_test") == "test_terminal_verification_policy_stops_timestamp_chasing"
    canonical_python = shutil.which("python")
    python3_fallback = shutil.which("python3")
    assert canonical_python or python3_fallback, "M103 direct proof requires a Python interpreter"
    if not canonical_python:
        assert python3_fallback, "python3 fallback missing while canonical python command is unavailable"
        assert "When `python` is unavailable in a worker runtime, use `python3` for the same direct test file" in readme_text
        assert "does not refresh the frozen proof receipt" in readme_text

    current_or_newer_rule = str(terminal_policy.get("current_or_newer_handoff_rule") or "")
    assert "assignment context only" in current_or_newer_rule
    assert "not a reason to edit this EA package" in current_or_newer_rule
    assert "canonical registry" in current_or_newer_rule
    assert "direct proof command" in current_or_newer_rule
    assert "green" in current_or_newer_rule
    handoff_mode_rule = str(terminal_policy.get("handoff_mode_rule") or "")
    assert "assignment metadata only" in handoff_mode_rule
    assert "Mode: unknown" in handoff_mode_rule
    assert "Mode: completion_review" in handoff_mode_rule
    assert "Mode: flagship_product" in handoff_mode_rule
    assert "frontier/package identity" in handoff_mode_rule
    assert "minimum generated-at value" in readme_text
    assert "not an exact-value trap" in readme_text
    assert "newer handoff stays valid" in readme_text
    assert "Mode: unknown" in readme_text
    assert "Mode: completion_review" in readme_text
    assert "Mode: flagship_product" in readme_text
    assert "frontier/package identity" in readme_text
    assert "should not add more repeat-verification rows" in readme_text
    if _active_handoff_targets_closed_m103_package():
        active_prompt_lower = active_prompt_text.lower()
        assert (
            '"package_id": "next90-m103-ea-parity-lab"' in active_prompt_text
            or "package: next90-m103-ea-parity-lab" in active_prompt_text
        )
        assert '"repo": "executive-assistant"' in active_prompt_text or "repo: executive-assistant" in active_prompt_text
        assert (
            '"milestone_id": 103' in active_prompt_text
            or "milestone 103" in active_prompt_lower
            or "PROGRAM_MILESTONES.yaml" in active_prompt_text
        )
        assert '"parity_lab:capture"' in active_prompt_text or "owned surfaces: parity_lab:capture" in active_prompt_text
        assert '"veteran_compare_packs"' in active_prompt_text or "veteran_compare_packs" in active_prompt_text
        assert (
            "status: complete; owners: executive-assistant" in active_prompt_text
            or (
                "repo: executive-assistant" in active_prompt_text
                and "This retry is implementation-only" in active_prompt_text
            )
        )
        assert (
            "do not invoke operator telemetry or active-run helper commands" in active_prompt_lower
            or "do not run supervisor status or eta helpers inside this worker run" in active_prompt_lower
        )
        assert (
            "hard-blocked" in active_prompt_lower
            or "the previous attempt burned time on supervisor helper loops" in active_prompt_lower
        )
        assert (
            "count as run failure" in active_prompt_lower
            or "do not run supervisor status or eta helpers inside this worker run" in active_prompt_lower
        )
        assert (
            "return non-zero" in active_prompt_lower
            or "do not run supervisor status or eta helpers inside this worker run" in active_prompt_lower
        )
        assert (
            "operator/ooda loop owns telemetry" in active_prompt_lower
            or "use the shard runtime handoff as the worker-safe resume context" in active_prompt_lower
        )
        assert (
            "If the package is already materially complete" in active_prompt_text
            or "This retry is implementation-only" in active_prompt_text
        )
    else:
        assert "Frontier ids: 4287684466" not in active_handoff_text

    allowed_next_work = set(str(item) for item in (terminal_policy.get("allowed_next_work") or []))
    assert allowed_next_work == {
        "next90-m103-design-parity-ladder",
        "next90-m103-fleet-readiness-consumption",
    }
    assert "next90-m103-ui-veteran-certification" not in allowed_next_work
    completed_non_ea = [dict(item) for item in (closeout.get("completed_non_ea_work") or [])]
    assert len(completed_non_ea) == 1
    assert completed_non_ea[0].get("package_id") == "next90-m103-ui-veteran-certification"
    assert completed_non_ea[0].get("owner") == "chummer6-ui"
    assert completed_non_ea[0].get("registry_task_id") == 103.2
    assert completed_non_ea[0].get("status") == "complete"

    append_policy = dict(closeout.get("repeat_row_append_policy") or {})
    assert append_policy.get("status") == "closed_append_free"
    assert append_policy.get("do_not_append_for_newer_same_package_handoffs") is True
    assert set(str(item) for item in (append_policy.get("append_only_when") or [])) == {
        "canonical_successor_registry_task_103_1_stops_reporting_complete",
        "design_or_fleet_queue_row_stops_reporting_complete_for_frontier_4287684466",
        "completed_output_or_source_pointer_missing",
        "direct_proof_command_fails",
        "terminal_verification_policy_removed_or_weakened",
    }
    append_action = str(append_policy.get("worker_action") or "")
    assert "move to allowed_next_work" in append_action
    assert "do not edit completed EA outputs only to record a newer assignment timestamp" in append_action

    proof_floor_freeze = dict(append_policy.get("proof_floor_freeze") or {})
    assert proof_floor_freeze.get("latest_guard_commit") == "257a5b7"
    assert proof_floor_freeze.get("latest_guard_subject") == "Tighten M103 handoff mode guard"
    assert proof_floor_freeze.get("guarded_by") == "test_terminal_verification_policy_stops_timestamp_chasing"

    freeze_rule = str(proof_floor_freeze.get("worker_rule") or "")
    assert "latest resolved append-free proof floor" in freeze_rule
    assert "sufficient closure for newer same-package handoffs" in freeze_rule
    assert "do not update generated receipts" in freeze_rule
    assert "repeat rows" in freeze_rule
    assert "closeout timestamps" in freeze_rule
    assert "worker-safe active-run handoff" in freeze_rule
    assert "4287684466" in freeze_rule
    assert "allowed to be older than the repository `HEAD`" in readme_text
    assert "not a reason to refresh receipts" in readme_text
    assert "explicit append conditions" in readme_text
    assert "must not be inserted into the closeout receipt just because they are now `HEAD`" in readme_text

    terminal_floor = str(terminal_policy.get("latest_required_handoff_floor") or "")
    repeat_rows = [dict(item) for item in (closeout.get("repeat_verifications") or [])]
    assert repeat_rows, "terminal closeout must retain the original proof-bearing repeat row"
    assert repeat_rows[-1].get("active_handoff_generated_at") == terminal_floor
    assert repeat_rows[-1].get("verified_at") == repeat_prevention.get("active_handoff_verified_at")
    for row in repeat_rows:
        assert str(row.get("active_handoff_generated_at") or "") <= terminal_floor, row
        assert str(row.get("verified_at") or "") <= str(repeat_prevention.get("active_handoff_verified_at") or ""), row

    mode_match = re.search(r"^Mode:\s*(.+)$", active_handoff_text, re.MULTILINE)
    assert mode_match, "active handoff missing mode line"
    active_mode = mode_match.group(1).strip()
    assert active_mode in {"successor_wave", "unknown", "completion_review", "flagship_product"}
    if _active_handoff_targets_closed_m103_package():
        assert "Frontier ids: 4287684466" in active_handoff_text
        assert "Open milestone ids: 4287684466" in active_handoff_text
        assert "next90-m103-ea-parity-lab" in active_prompt_text
    else:
        assert "Frontier ids: 4287684466" not in active_handoff_text
    static_closure_text = "\n".join(
        [
            HANDOFF_CLOSEOUT_PATH.read_text(encoding="utf-8"),
            PUBLISHED_PACK_PATH.read_text(encoding="utf-8"),
            README_PATH.read_text(encoding="utf-8"),
        ]
    )
    assert "Mode: successor_wave" not in static_closure_text
    if active_mode == "successor_wave":
        assert active_mode not in static_closure_text

    milestones = {int(dict(item).get("id") or 0): dict(item) for item in (registry.get("milestones") or [])}
    task_103_1 = [dict(task) for task in (milestones[103].get("work_tasks") or []) if dict(task).get("id") == 103.1]
    assert len(task_103_1) == 1
    assert task_103_1[0].get("status") == "complete"
    task_103_2 = [dict(task) for task in (milestones[103].get("work_tasks") or []) if dict(task).get("id") == 103.2]
    assert len(task_103_2) == 1
    assert task_103_2[0].get("owner") == "chummer6-ui"
    assert task_103_2[0].get("status") == "complete"
    assert task_103_2[0].get("landed_commit") == "a8e4f92c"
    remaining_task_ids = {
        dict(task).get("id")
        for task in (milestones[103].get("work_tasks") or [])
        if dict(task).get("status") != "complete"
    }
    assert remaining_task_ids == set()
    design_queue_item = _single_package_row(design_queue.get("items") or [], "next90-m103-ea-parity-lab")
    queue_item = _single_package_row(queue.get("items") or [], "next90-m103-ea-parity-lab")
    assert design_queue_item.get("status") == queue_item.get("status") == "complete"
    assert int(design_queue_item.get("frontier_id") or 0) == int(queue_item.get("frontier_id") or 0) == 4287684466
    assert list(design_queue_item.get("allowed_paths") or []) == list(queue_item.get("allowed_paths") or []) == [
        "skills",
        "tests",
        "feedback",
        "docs",
    ]
    assert list(design_queue_item.get("owned_surfaces") or []) == list(queue_item.get("owned_surfaces") or []) == list(
        pack.get("owned_surfaces") or []
    )

    local_proof_commits = [dict(item) for item in (closeout.get("local_proof_commits") or [])]
    assert local_proof_commits[-4].get("commit") == "a2ae08f"
    assert local_proof_commits[-4].get("subject") == "Tighten M103 append-free proof floor guard"
    assert "append-free proof floor guard" in str(local_proof_commits[-4].get("purpose") or "")
    assert local_proof_commits[-3].get("commit") == "3f74d5d"
    assert local_proof_commits[-3].get("subject") == "Keep M103 terminal handoff guard append-free"
    assert "timestamp-only edits" in str(local_proof_commits[-3].get("purpose") or "")
    assert local_proof_commits[-2].get("commit") == "1eddb6d"
    assert local_proof_commits[-2].get("subject") == "Pin M103 terminal append-free proof floor"
    assert "newer handoff timestamps" in str(local_proof_commits[-2].get("purpose") or "")
    assert local_proof_commits[-1].get("commit") == "257a5b7"
    assert local_proof_commits[-1].get("subject") == "Tighten M103 handoff mode guard"
    assert "assignment metadata only" in str(local_proof_commits[-1].get("purpose") or "")

    receipt_proof_commits = [
        str(commit)
        for commit in (
            dict(receipt.get("successor_closure") or {}).get("local_proof_commits") or []
        )
    ]
    assert receipt_proof_commits[-4:] == ["a2ae08f", "3f74d5d", "1eddb6d", "257a5b7"]

    subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-e", "257a5b7^{commit}"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    head = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--short=7", "HEAD"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    assert head != proof_floor_freeze.get("latest_guard_commit")
    assert head not in {str(item.get("commit") or "") for item in local_proof_commits}
    assert head not in set(receipt_proof_commits)

    frozen_closeout_evidence = "\n".join(
        [
            HANDOFF_CLOSEOUT_PATH.read_text(encoding="utf-8"),
            PUBLISHED_PACK_PATH.read_text(encoding="utf-8"),
            README_PATH.read_text(encoding="utf-8"),
        ]
    )
    leaked_post_freeze_commits = sorted(
        _post_freeze_commit_ids() & set(re.findall(r"\b[0-9a-f]{7}\b", frozen_closeout_evidence))
    )
    assert leaked_post_freeze_commits == []


def test_post_receipt_json_guard_commits_stay_verification_only_for_closed_ea_scope() -> None:
    closeout = _yaml(HANDOFF_CLOSEOUT_PATH)
    receipt = _yaml(PUBLISHED_PACK_PATH)
    append_policy = dict(closeout.get("repeat_row_append_policy") or {})
    proof_floor_freeze = dict(append_policy.get("proof_floor_freeze") or {})

    assert proof_floor_freeze.get("latest_guard_commit") == "257a5b7"
    assert append_policy.get("status") == "closed_append_free"
    assert append_policy.get("do_not_append_for_newer_same_package_handoffs") is True

    post_freeze_paths = _post_freeze_commit_paths(frozen_commit="4722d54")
    def is_m103_feedback_path(path: str) -> bool:
        return path.startswith("feedback/") and (
            "chummer5a-parity-lab" in path or path.startswith("feedback/chummer5a_parity_lab_")
        )

    post_freeze_paths = {
        commit: paths
        for commit, paths in post_freeze_paths.items()
        if "tests/test_chummer5a_parity_lab_pack.py" in paths
        or any(path.startswith("docs/chummer5a_parity_lab/") for path in paths)
        or any(is_m103_feedback_path(path) for path in paths)
    }
    assert post_freeze_paths, "expected local verification-only commits after frozen M103 floor"
    allowed_proof_refresh_paths = {
        HANDOFF_CLOSEOUT_PATH.relative_to(ROOT).as_posix(),
        PUBLISHED_PACK_PATH.relative_to(ROOT).as_posix(),
        README_PATH.relative_to(ROOT).as_posix(),
    }
    compare_source_anchor_paths = {
        PACK_PATH.relative_to(ROOT).as_posix(),
        README_PATH.relative_to(ROOT).as_posix(),
        COMPARE_PACKS_PATH.relative_to(ROOT).as_posix(),
        "tests/test_chummer5a_parity_lab_pack.py",
        "feedback/2026-04-17-chummer5a-parity-lab-implementation-only-retry-205051z.md",
        "feedback/2026-04-17-chummer5a-parity-lab-implementation-only-retry-205302z.md",
    }
    compare_source_anchor_commit = "854fca6"
    compare_source_anchor_subject = "Tighten M103 compare source anchors"
    artifact_expansion_paths = {
        PACK_PATH.relative_to(ROOT).as_posix(),
        README_PATH.relative_to(ROOT).as_posix(),
        ORACLE_BASELINES_PATH.relative_to(ROOT).as_posix(),
        WORKFLOW_PACK_PATH.relative_to(ROOT).as_posix(),
        COMPARE_PACKS_PATH.relative_to(ROOT).as_posix(),
        "tests/test_chummer5a_parity_lab_pack.py",
        "feedback/2026-04-18-chummer5a-parity-lab-successor-wave-pass.md",
    }
    artifact_expansion_subject = "Expand M103 oracle baseline workflow packs"
    screenshot_proof_path_fix_paths = {
        README_PATH.relative_to(ROOT).as_posix(),
        ORACLE_BASELINES_PATH.relative_to(ROOT).as_posix(),
        "tests/test_chummer5a_parity_lab_pack.py",
    }
    screenshot_proof_path_fix_subject = "Fix M103 parity lab screenshot proof path"
    routing_readiness_sync_commit = "6378742"
    routing_readiness_sync_subject = "Stabilize EA routing and readiness materialization"
    for commit, paths in post_freeze_paths.items():
        assert paths, commit
        subject = subprocess.run(
            ["git", "-C", str(ROOT), "show", "--no-patch", "--format=%s", commit],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()
        if paths == compare_source_anchor_paths:
            assert commit == compare_source_anchor_commit, (commit, sorted(paths))
            assert subject == compare_source_anchor_subject, (commit, subject, sorted(paths))
            continue
        if paths == artifact_expansion_paths:
            assert subject == artifact_expansion_subject, (commit, subject, sorted(paths))
            continue
        if paths == screenshot_proof_path_fix_paths:
            assert subject == screenshot_proof_path_fix_subject, (commit, subject, sorted(paths))
            continue
        if commit == "31ee583":
            assert subject == "Audit: sync campaign OS canon and fleet oversight", (commit, subject, sorted(paths))
            continue
        if commit == routing_readiness_sync_commit:
            assert subject == routing_readiness_sync_subject, (commit, subject, sorted(paths))
            assert "tests/test_chummer5a_parity_lab_pack.py" in paths, (commit, sorted(paths))
            continue
        assert all(
            path == "tests/test_chummer5a_parity_lab_pack.py"
            or is_m103_feedback_path(path)
            or path in allowed_proof_refresh_paths
            for path in paths
        ), (commit, sorted(paths))

    frozen_artifacts = {
        README_PATH.relative_to(ROOT).as_posix(),
        PACK_PATH.relative_to(ROOT).as_posix(),
    }
    assert compare_source_anchor_commit in post_freeze_paths
    for commit, paths in post_freeze_paths.items():
        frozen_path_changes = paths & frozen_artifacts
        if paths == compare_source_anchor_paths:
            subject = subprocess.run(
                ["git", "-C", str(ROOT), "show", "--no-patch", "--format=%s", commit],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).stdout.strip()
            assert commit == compare_source_anchor_commit, (commit, sorted(paths))
            assert subject == compare_source_anchor_subject, (commit, subject, sorted(paths))
            continue
        if paths == artifact_expansion_paths:
            subject = subprocess.run(
                ["git", "-C", str(ROOT), "show", "--no-patch", "--format=%s", commit],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).stdout.strip()
            assert subject == artifact_expansion_subject, (commit, subject, sorted(paths))
            continue
        if paths == screenshot_proof_path_fix_paths:
            subject = subprocess.run(
                ["git", "-C", str(ROOT), "show", "--no-patch", "--format=%s", commit],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).stdout.strip()
            assert subject == screenshot_proof_path_fix_subject, (commit, subject, sorted(paths))
            continue
        if commit == "31ee583":
            subject = subprocess.run(
                ["git", "-C", str(ROOT), "show", "--no-patch", "--format=%s", commit],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).stdout.strip()
            assert subject == "Audit: sync campaign OS canon and fleet oversight", (commit, subject, sorted(paths))
            continue
        if frozen_path_changes:
            subject = subprocess.run(
                ["git", "-C", str(ROOT), "show", "--no-patch", "--format=%s", commit],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).stdout.strip()
            assert frozen_path_changes == {README_PATH.relative_to(ROOT).as_posix()}, (
                commit,
                sorted(frozen_path_changes),
            )
            subject_lower = subject.lower()
            assert (
                "handoff mode" in subject_lower
                or "ui completion handoff proof" in subject_lower
                or "python3 runtime proof" in subject_lower
            ), (
                commit,
                subject,
                sorted(frozen_path_changes),
            )
        if paths & allowed_proof_refresh_paths:
            assert dict(closeout.get("proof") or {}).get("result") == _expected_direct_result()
            assert dict(receipt.get("proof") or {}).get("result") == _expected_direct_result()

    receipt_commits = set(str(commit) for commit in dict(receipt.get("successor_closure") or {}).get("local_proof_commits") or [])
    closeout_commits = set(str(item.get("commit") or "") for item in closeout.get("local_proof_commits") or [])
    post_freeze_commits = set(post_freeze_paths)
    assert post_freeze_commits.isdisjoint(receipt_commits)
    assert post_freeze_commits.isdisjoint(closeout_commits)

    named_feedback_receipt_refresh_commit = "c73d531"
    assert (
        subprocess.run(
            ["git", "-C", str(ROOT), "show", "--no-patch", "--format=%s", named_feedback_receipt_refresh_commit],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()
        == "Tighten M103 proof count guard"
    )

    final_receipt_refresh_commit = "bbe7d86"
    assert (
        subprocess.run(
            ["git", "-C", str(ROOT), "show", "--no-patch", "--format=%s", final_receipt_refresh_commit],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()
        == "Tighten M103 queue proof source guard"
    )
    post_receipt_refresh_paths = _post_freeze_commit_paths(frozen_commit=final_receipt_refresh_commit)
    post_receipt_refresh_paths = {
        commit: paths
        for commit, paths in post_receipt_refresh_paths.items()
        if "tests/test_chummer5a_parity_lab_pack.py" in paths
        or any(path.startswith("docs/chummer5a_parity_lab/") for path in paths)
        or any(is_m103_feedback_path(path) for path in paths)
    }
    assert post_receipt_refresh_paths, "expected verification-only commits after the final receipt refresh"
    permitted_post_receipt_paths = {
        "tests/test_chummer5a_parity_lab_pack.py",
        HANDOFF_CLOSEOUT_PATH.relative_to(ROOT).as_posix(),
        PUBLISHED_PACK_PATH.relative_to(ROOT).as_posix(),
        README_PATH.relative_to(ROOT).as_posix(),
    }
    for commit, paths in post_receipt_refresh_paths.items():
        assert paths, commit
        if paths == compare_source_anchor_paths:
            subject = subprocess.run(
                ["git", "-C", str(ROOT), "show", "--no-patch", "--format=%s", commit],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).stdout.strip()
            assert commit == compare_source_anchor_commit, (commit, sorted(paths))
            assert subject == compare_source_anchor_subject, (commit, subject, sorted(paths))
            continue
        if paths == artifact_expansion_paths:
            subject = subprocess.run(
                ["git", "-C", str(ROOT), "show", "--no-patch", "--format=%s", commit],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).stdout.strip()
            assert subject == artifact_expansion_subject, (commit, subject, sorted(paths))
            continue
        if paths == screenshot_proof_path_fix_paths:
            subject = subprocess.run(
                ["git", "-C", str(ROOT), "show", "--no-patch", "--format=%s", commit],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).stdout.strip()
            assert subject == screenshot_proof_path_fix_subject, (commit, subject, sorted(paths))
            continue
        if commit == "31ee583":
            subject = subprocess.run(
                ["git", "-C", str(ROOT), "show", "--no-patch", "--format=%s", commit],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).stdout.strip()
            assert subject == "Audit: sync campaign OS canon and fleet oversight", (commit, subject, sorted(paths))
            continue
        if commit == routing_readiness_sync_commit:
            subject = subprocess.run(
                ["git", "-C", str(ROOT), "show", "--no-patch", "--format=%s", commit],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).stdout.strip()
            assert subject == routing_readiness_sync_subject, (commit, subject, sorted(paths))
            assert "tests/test_chummer5a_parity_lab_pack.py" in paths, (commit, sorted(paths))
            continue
        assert all(path in permitted_post_receipt_paths or is_m103_feedback_path(path) for path in paths), (
            commit,
            sorted(paths),
        )
        if paths & {
            HANDOFF_CLOSEOUT_PATH.relative_to(ROOT).as_posix(),
            PUBLISHED_PACK_PATH.relative_to(ROOT).as_posix(),
            README_PATH.relative_to(ROOT).as_posix(),
        }:
            subject = subprocess.run(
                ["git", "-C", str(ROOT), "show", "--no-patch", "--format=%s", commit],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).stdout.strip()
            subject_lower = subject.lower()
            assert (
                "queue proof source guard" in subject_lower
                or "proof count guard" in subject_lower
                or "handoff mode" in subject_lower
                or "ui completion handoff proof" in subject_lower
                or "python3 runtime proof" in subject_lower
            ), (
                commit,
                subject,
                sorted(paths),
            )

    latest_receipt_touch_floor = "f3ba05e"
    assert (
        subprocess.run(
            ["git", "-C", str(ROOT), "show", "--no-patch", "--format=%s", latest_receipt_touch_floor],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()
        == "Tighten M103 parity lab handoff mode guard"
    )
    post_latest_receipt_touch_paths = _post_freeze_commit_paths(frozen_commit=latest_receipt_touch_floor)
    post_latest_receipt_touch_paths = {
        commit: paths
        for commit, paths in post_latest_receipt_touch_paths.items()
        if "tests/test_chummer5a_parity_lab_pack.py" in paths
        or any(path.startswith("docs/chummer5a_parity_lab/") for path in paths)
        or any(is_m103_feedback_path(path) for path in paths)
    }
    ui_completion_handoff_paths = {
        "tests/test_chummer5a_parity_lab_pack.py",
        "feedback/2026-04-17-chummer5a-parity-lab-ui-completion-handoff-tightening.md",
        HANDOFF_CLOSEOUT_PATH.relative_to(ROOT).as_posix(),
        PUBLISHED_PACK_PATH.relative_to(ROOT).as_posix(),
        README_PATH.relative_to(ROOT).as_posix(),
    }
    ui_completion_receipt_paths = ui_completion_handoff_paths - {"tests/test_chummer5a_parity_lab_pack.py"}
    for commit, paths in post_latest_receipt_touch_paths.items():
        assert paths, commit
        if paths == compare_source_anchor_paths:
            subject = subprocess.run(
                ["git", "-C", str(ROOT), "show", "--no-patch", "--format=%s", commit],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).stdout.strip()
            assert commit == compare_source_anchor_commit, (commit, sorted(paths))
            assert subject == compare_source_anchor_subject, (commit, subject, sorted(paths))
            continue
        if paths == artifact_expansion_paths:
            subject = subprocess.run(
                ["git", "-C", str(ROOT), "show", "--no-patch", "--format=%s", commit],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).stdout.strip()
            assert subject == artifact_expansion_subject, (commit, subject, sorted(paths))
            continue
        if paths <= ui_completion_handoff_paths and paths & ui_completion_receipt_paths:
            subject = subprocess.run(
                ["git", "-C", str(ROOT), "show", "--no-patch", "--format=%s", commit],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).stdout.strip()
            assert "ui completion handoff proof" in subject.lower(), (commit, subject, sorted(paths))
            continue
        if commit == "31ee583":
            subject = subprocess.run(
                ["git", "-C", str(ROOT), "show", "--no-patch", "--format=%s", commit],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).stdout.strip()
            assert subject == "Audit: sync campaign OS canon and fleet oversight", (commit, subject, sorted(paths))
            continue
        if commit == routing_readiness_sync_commit:
            subject = subprocess.run(
                ["git", "-C", str(ROOT), "show", "--no-patch", "--format=%s", commit],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).stdout.strip()
            assert subject == routing_readiness_sync_subject, (commit, subject, sorted(paths))
            assert "tests/test_chummer5a_parity_lab_pack.py" in paths, (commit, sorted(paths))
            continue
        if README_PATH.relative_to(ROOT).as_posix() in paths:
            subject = subprocess.run(
                ["git", "-C", str(ROOT), "show", "--no-patch", "--format=%s", commit],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).stdout.strip()
            subject_lower = subject.lower()
            assert (
                "python3 runtime proof" in subject_lower or "screenshot proof path" in subject_lower
            ), (commit, subject, sorted(paths))
            assert all(
                path == "tests/test_chummer5a_parity_lab_pack.py"
                or is_m103_feedback_path(path)
                or path == README_PATH.relative_to(ROOT).as_posix()
                or path == ORACLE_BASELINES_PATH.relative_to(ROOT).as_posix()
                for path in paths
            ), (commit, sorted(paths))
            continue
        assert all(path == "tests/test_chummer5a_parity_lab_pack.py" or is_m103_feedback_path(path) for path in paths), (
            commit,
            sorted(paths),
        )


def test_successor_closeout_does_not_use_active_run_helper_commands() -> None:
    closeout = _yaml(HANDOFF_CLOSEOUT_PATH)
    receipt = _yaml(PUBLISHED_PACK_PATH)
    pack = _yaml(PACK_PATH)
    registry = _yaml(SUCCESSOR_REGISTRY_PATH)
    design_queue = _yaml(DESIGN_SUCCESSOR_QUEUE_PATH)
    queue = _yaml(SUCCESSOR_QUEUE_PATH)
    active_handoff_text = ACTIVE_RUN_HANDOFF_PATH.read_text(encoding="utf-8")
    if not _active_handoff_targets_closed_m103_package():
        assert "Frontier ids: 4287684466" not in active_handoff_text
        return

    task_local_telemetry_path = _task_local_telemetry_path()
    task_local_telemetry = _yaml(task_local_telemetry_path)

    combined = "\n".join(
        [
            HANDOFF_CLOSEOUT_PATH.read_text(encoding="utf-8"),
            PUBLISHED_PACK_PATH.read_text(encoding="utf-8"),
            PACK_PATH.read_text(encoding="utf-8"),
        ]
    )
    milestones = {int(dict(item).get("id") or 0): dict(item) for item in (registry.get("milestones") or [])}
    task_103_1 = [dict(task) for task in (milestones[103].get("work_tasks") or []) if dict(task).get("id") == 103.1]
    assert len(task_103_1) == 1
    queue_item = _single_package_row(queue.get("items") or [], "next90-m103-ea-parity-lab")
    design_queue_item = _single_package_row(design_queue.get("items") or [], "next90-m103-ea-parity-lab")
    canonical_closure_proof_text = "\n".join(
        str(item)
        for item in (
            list(task_103_1[0].get("evidence") or [])
            + list(queue_item.get("proof") or [])
            + list(design_queue_item.get("proof") or [])
        )
    )
    task_local_telemetry_path_text = task_local_telemetry_path.as_posix()
    blocked_markers = [
        "TASK_LOCAL_TELEMETRY",
        task_local_telemetry_path_text,
        "eta:",
        "remaining milestones",
        "remaining queue items",
        "critical path",
        "operator telemetry",
        "active-run helper",
        "active run helper",
        "ooda",
        "telemetry helper",
        "Recent stderr tail",
        "Supervisor status polling",
        "active worker run",
    ]
    for marker in blocked_markers:
        assert marker.lower() not in combined.lower(), marker
        assert marker.lower() not in canonical_closure_proof_text.lower(), marker
    for assignment_only_marker in (
        ACTIVE_RUN_HANDOFF_PATH.as_posix(),
        "remaining milestones",
        "remaining queue items",
        "critical path",
        "slice_summary",
        "frontier_briefs",
        "focus_owners",
        "status_query_supported",
        "polling_disabled",
    ):
        assert assignment_only_marker.lower() not in canonical_closure_proof_text.lower(), assignment_only_marker
    assert "python tests/test_chummer5a_parity_lab_pack.py exits with ran=18 failed=0" in canonical_closure_proof_text
    assert "/docker/EA commit f252c02" in canonical_closure_proof_text
    assert "## Recent stderr tail" in active_handoff_text
    recent_stderr_tail = active_handoff_text.split("## Recent stderr tail", 1)[1]
    recent_stderr_tail_lower = recent_stderr_tail.lower()
    historical_helper_loop_guard_present = (
        "supervisor status polling was observed from inside the active worker run." in recent_stderr_tail_lower
        and "do not repeat it" in recent_stderr_tail_lower
        and "keep working from the prompt, task-local telemetry, handoff, and frontier artifacts only"
        in recent_stderr_tail_lower
    )
    implementation_retry_guard_present = (
        "the previous attempt burned time on supervisor helper loops" in recent_stderr_tail_lower
        and "this retry is implementation-only" in recent_stderr_tail_lower
        and "do not run supervisor status or eta helpers inside this worker run" in recent_stderr_tail_lower
        and "use the shard runtime handoff as the worker-safe resume context" in recent_stderr_tail_lower
    )
    prompt_text_for_tail = _active_handoff_prompt_text()
    prompt_retry_guard_present = (
        "The previous attempt burned time on supervisor helper loops." in prompt_text_for_tail
        and "This retry is implementation-only." in prompt_text_for_tail
        and "Do not run supervisor status or eta helpers inside this worker run." in prompt_text_for_tail
        and "Use the shard runtime handoff as the worker-safe resume context." in prompt_text_for_tail
    )
    current_execution_guard_present = (
        "do not invoke operator telemetry or active-run helper commands from inside worker runs"
        in prompt_text_for_tail.lower()
        and "those helpers are hard-blocked, count as run failure, and return non-zero"
        in prompt_text_for_tail.lower()
        and "the operator/ooda loop owns telemetry; keep working the assigned slice"
        in prompt_text_for_tail.lower()
    )
    assert (
        historical_helper_loop_guard_present
        or implementation_retry_guard_present
        or prompt_retry_guard_present
        or current_execution_guard_present
    )
    assert (
        "Do not run supervisor status or eta helpers inside this worker run." in prompt_text_for_tail
        or "do not invoke operator telemetry or active-run helper commands from inside worker runs"
        in prompt_text_for_tail.lower()
    )
    assert "treat them as stale notes rather than commands to repeat" in prompt_text_for_tail
    assert "Use the shard runtime handoff as the worker-safe resume context." in prompt_text_for_tail
    assert "If you stop, report only:" in prompt_text_for_tail
    assert "What shipped: ..." in prompt_text_for_tail
    assert "What remains: ..." in prompt_text_for_tail
    assert "Exact blocker: ..." in prompt_text_for_tail
    assert "status helper output:" not in recent_stderr_tail.lower()
    assert "eta helper output:" not in recent_stderr_tail.lower()
    assert "operator telemetry output:" not in recent_stderr_tail.lower()
    assert task_local_telemetry.get("polling_disabled") is True
    assert task_local_telemetry.get("status_query_supported") is False
    assert task_local_telemetry.get("scope_label") == "Next 90-day product advance wave"
    assert task_local_telemetry.get("mode") == "implementation_only"
    assert task_local_telemetry.get("registry_path") == (
        "/docker/chummercomplete/chummer-design/products/chummer/NEXT_12_BIGGEST_WINS_REGISTRY.yaml"
    )
    assert task_local_telemetry.get("program_milestones_path") == (
        "/docker/chummercomplete/chummer-design/products/chummer/PROGRAM_MILESTONES.yaml"
    )
    assert task_local_telemetry.get("roadmap_path") == (
        "/docker/chummercomplete/chummer-design/products/chummer/ROADMAP.md"
    )
    assert task_local_telemetry.get("successor_registry_path") == SUCCESSOR_REGISTRY_PATH.as_posix()
    assert task_local_telemetry.get("successor_queue_path") == SUCCESSOR_QUEUE_PATH.as_posix()
    assert str(task_local_telemetry.get("runtime_handoff_path") or "") in _worker_safe_path_aliases(ACTIVE_RUN_HANDOFF_PATH)
    assert dict(task_local_telemetry.get("paths") or {}).get("program_milestones_path") == (
        "/docker/chummercomplete/chummer-design/products/chummer/PROGRAM_MILESTONES.yaml"
    )
    assert dict(task_local_telemetry.get("paths") or {}).get("roadmap_path") == (
        "/docker/chummercomplete/chummer-design/products/chummer/ROADMAP.md"
    )
    assert dict(task_local_telemetry.get("paths") or {}).get("successor_queue_path") == SUCCESSOR_QUEUE_PATH.as_posix()
    assert dict(task_local_telemetry.get("paths") or {}).get("registry_path") == (
        NEXT_12_REGISTRY_PATH.as_posix()
    )
    focus_profiles = set(str(item) for item in (task_local_telemetry.get("focus_profiles") or []))
    assert "next_90_day_successor_wave" in focus_profiles
    assert focus_profiles <= {
        "top_flagship_grade",
        "whole_project_frontier",
        "next_90_day_successor_wave",
    }
    focus_owners = set(str(item) for item in (task_local_telemetry.get("focus_owners") or []))
    assert "executive-assistant" in focus_owners
    assert focus_owners <= {
        "chummer6-ui",
        "chummer6-core",
        "chummer6-design",
        "executive-assistant",
    }
    focus_texts = set(str(item) for item in (task_local_telemetry.get("focus_texts") or []))
    assert {
        "next90-m103-ea-parity-lab",
        "Extract Chummer5a oracle baselines and veteran workflow packs",
    } <= focus_texts
    frontier_briefs = [str(item) for item in (task_local_telemetry.get("frontier_briefs") or [])]
    assert len(frontier_briefs) == 1
    assert "4287684466 [W7]" in frontier_briefs[0]
    assert "status: complete" in frontier_briefs[0]
    assert "owners: executive-assistant" in frontier_briefs[0]
    assert "deps: 101, 102" in frontier_briefs[0]
    slice_summary = str(task_local_telemetry.get("slice_summary") or "")
    assert "20 next-wave milestones remain" in slice_summary
    queue_slice_match = re.search(r"(\d+)\s+queue slices", slice_summary)
    assert queue_slice_match, slice_summary
    assert int(queue_slice_match.group(1)) >= 41, slice_summary
    assert "101 -> 102 -> 103" in slice_summary
    assert "119 -> 120" in slice_summary
    telemetry_guidance = str(task_local_telemetry.get("guidance") or "")
    assert "Do not run supervisor status helpers" in telemetry_guidance
    assert "Open the listed files directly" in telemetry_guidance
    assert "keep implementing the assigned successor slice" in telemetry_guidance
    assert task_local_telemetry.get("polling_disabled") is True
    assert task_local_telemetry.get("status_query_supported") is False
    assert _worker_safe_path_aliases(task_local_telemetry_path.parent) & _worker_safe_path_aliases(
        _active_handoff_prompt_path().parent
    )
    assert task_local_telemetry_path.parent.name in active_handoff_text
    first_commands = [str(item) for item in (task_local_telemetry.get("first_commands") or [])]
    assert first_commands[:5] == [
        "cat TASK_LOCAL_TELEMETRY.generated.json",
        "sed -n '1,220p' /docker/fleet/.codex-studio/published/NEXT_90_DAY_QUEUE_STAGING.generated.yaml",
        "sed -n '1,220p' /docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml",
        "sed -n '1,220p' /docker/chummercomplete/chummer-design/products/chummer/NEXT_12_BIGGEST_WINS_REGISTRY.yaml",
        "sed -n '1,220p' /docker/chummercomplete/chummer-design/products/chummer/PROGRAM_MILESTONES.yaml",
    ]
    assert len(first_commands) == 6
    assert first_commands[5] in {
        f"sed -n '1,220p' {path}" for path in _worker_safe_path_aliases(ACTIVE_RUN_HANDOFF_PATH)
    }
    worker_safe_direct_read_prefixes = (
        "cat ",
        "sed -n ",
    )
    allowed_first_action_repo_files = {
        SUCCESSOR_QUEUE_PATH.as_posix(),
        SUCCESSOR_REGISTRY_PATH.as_posix(),
        "/docker/chummercomplete/chummer-design/products/chummer/NEXT_12_BIGGEST_WINS_REGISTRY.yaml",
        "/docker/chummercomplete/chummer-design/products/chummer/PROGRAM_MILESTONES.yaml",
        "/docker/chummercomplete/chummer-design/products/chummer/ROADMAP.md",
        ACTIVE_RUN_HANDOFF_PATH.as_posix(),
    }
    assert "TASK_LOCAL_TELEMETRY.generated.json" in first_commands[0]
    assert any(path in first_commands[1] for path in allowed_first_action_repo_files), first_commands[1]
    assert all(command.startswith(worker_safe_direct_read_prefixes) for command in first_commands)
    shell_control_fragments = ("&&", "||", ";", "|", ">", "<", "$(", "`")
    for command in first_commands:
        for fragment in shell_control_fragments:
            assert fragment not in command, command
    assert any(command.endswith(SUCCESSOR_REGISTRY_PATH.as_posix()) for command in first_commands)
    assert any(command.endswith(SUCCESSOR_QUEUE_PATH.as_posix()) for command in first_commands)
    assert any(
        any(command.endswith(path) for path in _worker_safe_path_aliases(ACTIVE_RUN_HANDOFF_PATH))
        for command in first_commands
    )
    prompt_text = _active_handoff_prompt_text()
    prompt_lower = prompt_text.lower()
    assert (
        "This retry is implementation-only." in prompt_text
        or str(task_local_telemetry.get("mode") or "") == "implementation_only"
    )
    assert (
        "do not invent another orientation step" in prompt_lower
        or "first action rule" in prompt_lower
    )
    assert (
        "staying inside the allowed paths" in prompt_text
        or "Keep implementation scoped to the allowed paths: skills, tests, feedback, docs" in prompt_text
        or "keep implementation inside the package repo, owned surfaces, and allowed paths" in prompt_text
    )
    assert "start editing" in prompt_text or "inspect the target implementation files directly" in prompt_lower
    assert (
        "Do not run supervisor status or eta helpers inside this worker run." in prompt_text
        or "do not query supervisor status or eta from inside the worker run" in prompt_lower
    )
    assert "treat them as stale notes rather than commands to repeat" in prompt_text
    assert "Writable scope roots:" in prompt_text
    assert "/docker/EA" in prompt_text
    assert "If you stop, report only:" in prompt_text
    assert "What shipped: ..." in prompt_text
    assert "What remains: ..." in prompt_text
    assert "Exact blocker: ..." in prompt_text
    assert prompt_text.index("Writable scope roots:") < prompt_text.index("If you stop, report only:")
    assert (
        "First action rule: open `TASK_LOCAL_TELEMETRY.generated.json`, then open one listed repo file, then inspect the target implementation files directly."
        in prompt_text
        or "Run these exact commands first and do not invent another orientation step:" in prompt_text
    )
    exact_command_header = "Run these exact commands first and do not invent another orientation step:"
    if exact_command_header in prompt_text:
        expected_prompt_first_commands = [
            f"sed -n '1,220p' {SUCCESSOR_QUEUE_PATH.as_posix()}",
            f"sed -n '1,220p' {SUCCESSOR_REGISTRY_PATH.as_posix()}",
            "sed -n '1,220p' /docker/chummercomplete/chummer-design/products/chummer/PROGRAM_MILESTONES.yaml",
        ]
        prompt_first_command_variants = {
            f"cat {path}" for path in _worker_safe_path_aliases(task_local_telemetry_path)
        }
        assert any(f"1. `{command}`" in prompt_text for command in prompt_first_command_variants), prompt_first_command_variants
        for index, expected_command in enumerate(expected_prompt_first_commands, start=2):
            assert f"{index}. `{expected_command}`" in prompt_text, expected_command
        exact_command_block = prompt_text.split(exact_command_header, 1)[1]
        exact_command_block = exact_command_block.split("Then inspect the target implementation files directly", 1)[0]
        exact_prompt_commands = re.findall(r"^\s*(\d+)\.\s*`([^`]+)`\s*$", exact_command_block, re.MULTILINE)
        assert len(exact_prompt_commands) == 4
        assert exact_prompt_commands[0][0] == "1"
        assert exact_prompt_commands[0][1] in prompt_first_command_variants
        assert exact_prompt_commands[1:] == [
            (str(index), command)
            for index, command in enumerate(expected_prompt_first_commands, start=2)
        ]
        assert len(exact_prompt_commands) == 4
        assert len(first_commands) > len(exact_prompt_commands)
        task_local_telemetry_aliases = _worker_safe_path_aliases(task_local_telemetry_path)
        normalized_first_commands = {
            next(
                (
                    command.replace(alias, "TASK_LOCAL_TELEMETRY.generated.json")
                    for alias in task_local_telemetry_aliases
                    if alias in command
                ),
                command,
            )
            for command in first_commands
        }
        normalized_exact_prompt_commands = {
            next(
                (
                    command.replace(alias, "TASK_LOCAL_TELEMETRY.generated.json")
                    for alias in task_local_telemetry_aliases
                    if alias in command
                ),
                command,
            )
            for _, command in exact_prompt_commands
        }
        assert normalized_exact_prompt_commands.issubset(normalized_first_commands)
        assert "NEXT_12_BIGGEST_WINS_REGISTRY.yaml" not in exact_command_block
        assert "ACTIVE_RUN_HANDOFF.generated.md" not in exact_command_block
        read_directly_first_block = prompt_text.split("Read these files directly first:", 1)[1]
        read_directly_first_block = read_directly_first_block.split("Use the shard runtime handoff", 1)[0]
        direct_read_matches = re.findall(r"^\s*-\s+(\S+)\s*$", read_directly_first_block, re.MULTILINE)
        assert len(direct_read_matches) == 7
        assert direct_read_matches[0] in _worker_safe_path_aliases(task_local_telemetry_path)
        assert direct_read_matches[1:] == [
            "/docker/chummercomplete/chummer-design/products/chummer/NEXT_12_BIGGEST_WINS_REGISTRY.yaml",
            "/docker/chummercomplete/chummer-design/products/chummer/PROGRAM_MILESTONES.yaml",
            "/docker/chummercomplete/chummer-design/products/chummer/ROADMAP.md",
            direct_read_matches[4],
            SUCCESSOR_REGISTRY_PATH.as_posix(),
            SUCCESSOR_QUEUE_PATH.as_posix(),
        ]
        assert direct_read_matches[4] in _worker_safe_path_aliases(ACTIVE_RUN_HANDOFF_PATH)
        assert "NEXT_12_BIGGEST_WINS_REGISTRY.yaml" in read_directly_first_block
        assert "ACTIVE_RUN_HANDOFF.generated.md" in read_directly_first_block
        assert prompt_text.index(exact_command_header) < prompt_text.index("Read these files directly first:")
        assert prompt_text.index("Then inspect the target implementation files directly") < prompt_text.index(
            "Read these files directly first:"
        )
    else:
        assert "TASK_LOCAL_TELEMETRY.generated.json" in prompt_text
        assert "then open one listed repo file" in prompt_text
        assert "then inspect the target implementation files directly" in prompt_text
    forbidden_first_command_fragments = [
        "status",
        "eta",
        "telemetry helper",
        "supervisor status",
        "supervisor eta",
        "run_chummer_design_supervisor",
        "chummer_design_supervisor.py",
        "active-run helper",
        "active run helper",
        "operator telemetry",
        "ooda",
    ]
    for command in first_commands:
        for fragment in forbidden_first_command_fragments:
            assert fragment not in command.lower(), command
    task_queue_item = dict(task_local_telemetry.get("queue_item") or {})
    assert task_queue_item.get("package_id") == "next90-m103-ea-parity-lab"
    assert task_queue_item.get("repo") == "executive-assistant"
    assert int(task_queue_item.get("milestone_id") or 0) == 103
    assert list(task_queue_item.get("allowed_paths") or []) == ["skills", "tests", "feedback", "docs"]
    assert list(task_queue_item.get("owned_surfaces") or []) == [
        "parity_lab:capture",
        "veteran_compare_packs",
    ]
    task_local_assignment_text = json.dumps(task_local_telemetry, sort_keys=True)
    task_local_command_source_text = json.dumps(
        {
            "first_commands": task_local_telemetry.get("first_commands"),
            "paths": task_local_telemetry.get("paths"),
            "queue_item": task_local_telemetry.get("queue_item"),
            "successor_queue_path": task_local_telemetry.get("successor_queue_path"),
            "successor_registry_path": task_local_telemetry.get("successor_registry_path"),
        },
        sort_keys=True,
    ).lower()
    assert "4287684466 [W7]" in task_local_assignment_text
    assert "status: complete" in task_local_assignment_text
    assert "next90-m103-ea-parity-lab" in task_local_assignment_text
    for forbidden_assignment_fragment in (
        "run_chummer_design_supervisor",
        "chummer_design_supervisor.py",
        "supervisor status",
        "supervisor eta",
        "status helper output",
        "eta helper output",
        "operator telemetry output",
    ):
        assert forbidden_assignment_fragment not in task_local_command_source_text

    active_prompt_text = _active_handoff_prompt_text()
    active_prompt_lower = active_prompt_text.lower()
    assert (
        "Start by reading these files directly:" in active_prompt_text
        or "Read these files directly first:" in active_prompt_text
    )
    assert any(path in active_prompt_text for path in _worker_safe_path_aliases(task_local_telemetry_path))
    assert "/docker/chummercomplete/chummer-design/products/chummer/NEXT_12_BIGGEST_WINS_REGISTRY.yaml" in active_prompt_text
    assert "/docker/chummercomplete/chummer-design/products/chummer/PROGRAM_MILESTONES.yaml" in active_prompt_text
    assert "/docker/chummercomplete/chummer-design/products/chummer/ROADMAP.md" in active_prompt_text
    assert any(path in active_prompt_text for path in _worker_safe_path_aliases(ACTIVE_RUN_HANDOFF_PATH))
    assert SUCCESSOR_REGISTRY_PATH.as_posix() in active_prompt_text
    assert SUCCESSOR_QUEUE_PATH.as_posix() in active_prompt_text
    assert "then inspect the target implementation files directly" in active_prompt_lower
    assert (
        "do not query supervisor status or eta from inside the worker run" in active_prompt_lower
        or "do not run supervisor status or eta helpers inside this worker run" in active_prompt_lower
    )
    assert (
        "the operator/ooda loop owns telemetry; keep working the assigned slice" in active_prompt_lower
        or "use the shard runtime handoff as the worker-safe resume context" in active_prompt_lower
    )
    assert (
        "do not invoke operator telemetry or active-run helper commands from inside worker runs" in active_prompt_lower
        or "the previous attempt burned time on supervisor helper loops" in active_prompt_lower
    )
    assert (
        "those helpers are hard-blocked, count as run failure, and return non-zero" in active_prompt_lower
        or "do not run supervisor status or eta helpers inside this worker run" in active_prompt_lower
    )
    assert (
        "the operator/ooda loop owns telemetry; keep working the assigned slice" in active_prompt_lower
        or "use the shard runtime handoff as the worker-safe resume context" in active_prompt_lower
    )
    assert (
        "use the task-local telemetry file and shard runtime handoff as the local machine-readable context"
        in active_prompt_lower
        or "use the task-local telemetry file as machine-readable context" in active_prompt_lower
        or "use the shard runtime handoff as the worker-safe resume context" in active_prompt_lower
    )
    assert (
        "those helpers are hard-blocked, count as run failure, and return non-zero" in active_prompt_lower
        or "do not run supervisor status or eta helpers inside this worker run" in active_prompt_lower
    )

    proof_command = str(dict(closeout.get("proof") or {}).get("command") or "")
    receipt_command = str(dict(receipt.get("proof") or {}).get("command") or "")
    assert proof_command == receipt_command == "python tests/test_chummer5a_parity_lab_pack.py"
    assert dict(pack.get("readiness_evidence") or {}).get("flagship_readiness_status") in {"pass", "fail"}

    milestones = {int(dict(item).get("id") or 0): dict(item) for item in (registry.get("milestones") or [])}
    task_103_1_matches = [dict(task) for task in (milestones[103].get("work_tasks") or []) if dict(task).get("id") == 103.1]
    assert len(task_103_1_matches) == 1, f"103.1 work task row count: {len(task_103_1_matches)}"
    task_103_1 = task_103_1_matches[0]
    design_queue_item = _single_package_row(design_queue.get("items") or [], "next90-m103-ea-parity-lab")
    queue_item = _single_package_row(queue.get("items") or [], "next90-m103-ea-parity-lab")

    canonical_package_proof = "\n".join(
        str(item)
        for item in (
            list(task_103_1.get("evidence") or [])
            + list(design_queue_item.get("proof") or [])
            + list(queue_item.get("proof") or [])
        )
    )
    blocked_proof_markers = [
        "TASK_LOCAL_TELEMETRY",
        "ACTIVE_RUN_HANDOFF.generated.md",
        "active_run_handoff",
        "/runs/",
        "Successor-wave telemetry",
        "Current steering focus",
        "profile focus",
        "owner focus",
        "text focus",
        "Assigned successor queue package",
        "Successor frontier ids to prioritize first",
        "Successor frontier detail",
        "Required order",
        "Execution rules inside this run",
        "First action rule",
        "eta:",
        "remaining milestones",
        "remaining queue items",
        "critical path",
        "first_commands",
        "frontier_briefs",
        "focus_texts",
        "polling_disabled",
        "queue_item",
        "slice_summary",
        "status_query_supported",
        "Supervisor status polling",
        "active worker run",
        "active-run telemetry",
        "operator telemetry",
        "operator/ooda loop owns telemetry",
        "ooda",
        "telemetry helper output",
        "operator-owned helper output",
        "Recent stderr tail",
        "hard-blocked",
        "count as run failure",
        "return non-zero",
    ]
    for marker in blocked_proof_markers:
        assert marker.lower() not in canonical_package_proof.lower(), marker
    assert task_local_telemetry_path_text.lower() not in canonical_package_proof.lower()

    append_policy = dict(closeout.get("repeat_row_append_policy") or {})
    proof_floor_freeze = dict(append_policy.get("proof_floor_freeze") or {})
    frozen_guard_commit = str(proof_floor_freeze.get("latest_guard_commit") or "")
    assert frozen_guard_commit == "257a5b7"
    assert frozen_guard_commit not in canonical_package_proof

    head = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--short=7", "HEAD"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    assert head != frozen_guard_commit
    assert head not in canonical_package_proof
    leaked_post_freeze_commits = sorted(
        _post_freeze_commit_ids() & set(re.findall(r"\b[0-9a-f]{7}\b", canonical_package_proof))
    )
    assert leaked_post_freeze_commits == []
    _assert_verifier_subprocesses_are_worker_safe()
    _assert_task_local_assignment_is_context_not_closure_evidence()
    _assert_legacy_program_files_are_context_not_m103_closure()
    _assert_chummer5a_feedback_notes_do_not_cite_blocked_helper_evidence()


def _assert_task_local_assignment_is_context_not_closure_evidence() -> None:
    closeout = _yaml(HANDOFF_CLOSEOUT_PATH)
    receipt = _yaml(PUBLISHED_PACK_PATH)
    registry = _yaml(SUCCESSOR_REGISTRY_PATH)
    design_queue = _yaml(DESIGN_SUCCESSOR_QUEUE_PATH)
    queue = _yaml(SUCCESSOR_QUEUE_PATH)
    task_local_telemetry_path = _task_local_telemetry_path()
    task_local_telemetry = _yaml(task_local_telemetry_path)
    task_queue_item = dict(task_local_telemetry.get("queue_item") or {})
    closure_scope = dict(closeout.get("closure_scope") or {})
    repeat_prevention = dict(closeout.get("repeat_prevention") or {})
    append_policy = dict(closeout.get("repeat_row_append_policy") or {})
    active_handoff_text = ACTIVE_RUN_HANDOFF_PATH.read_text(encoding="utf-8")
    active_prompt_path = _active_handoff_prompt_path()
    active_prompt_parent = active_prompt_path.parent
    task_local_context_values = {
        str(value)
        for value in (
            task_local_telemetry.get("scope_label"),
            task_local_telemetry.get("slice_summary"),
            task_local_telemetry.get("guidance"),
        )
        if str(value or "").strip()
    }
    task_local_context_values.update(str(item) for item in (task_local_telemetry.get("frontier_briefs") or []))
    task_local_context_values.update(str(item) for item in (task_local_telemetry.get("first_commands") or []))

    mode_match = re.search(r"^Mode:\s*(.+)$", active_handoff_text, re.MULTILINE)
    assert mode_match, "active handoff missing mode line"
    mode_text = mode_match.group(1).strip()
    assert mode_text in {"successor_wave", "unknown", "completion_review", "flagship_product"}
    assert "Frontier ids: 4287684466" in active_handoff_text
    assert task_queue_item.get("package_id") == "next90-m103-ea-parity-lab"
    if mode_text == "successor_wave":
        assert mode_text not in "\n".join(task_local_context_values)
    assert task_local_telemetry.get("mode") == "implementation_only"
    assert task_local_telemetry.get("polling_disabled") is True
    assert task_local_telemetry.get("status_query_supported") is False
    first_commands = [str(item) for item in (task_local_telemetry.get("first_commands") or [])]
    assert first_commands[:2] == [
        "cat TASK_LOCAL_TELEMETRY.generated.json",
        "sed -n '1,220p' /docker/fleet/.codex-studio/published/NEXT_90_DAY_QUEUE_STAGING.generated.yaml",
    ]
    assert "sed -n '1,220p' /docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml" in first_commands
    assert any(
        f"sed -n '1,220p' {path}" in first_commands for path in _worker_safe_path_aliases(ACTIVE_RUN_HANDOFF_PATH)
    )
    blocked_first_command_fragments = (
        "run_chummer_design_supervisor",
        "chummer_design_supervisor.py",
        "supervisor status",
        "supervisor eta",
        "operator telemetry",
        "ooda",
    )
    for command in first_commands:
        command_lower = command.lower()
        for fragment in ("&&", "||", ";", "|", ">", "<", "$(", "`"):
            assert fragment not in command, command
        for fragment in blocked_first_command_fragments:
            assert fragment not in command_lower, command
    assert task_queue_item.get("package_id") == closure_scope.get("closed_package_only")
    assert task_queue_item.get("repo") == "executive-assistant"
    assert int(task_queue_item.get("milestone_id") or 0) == int(closeout.get("milestone_id") or 0) == 103
    assert task_queue_item.get("title") == "Extract Chummer5a oracle baselines and veteran workflow packs"
    assert task_queue_item.get("task") == (
        "Capture screenshot baselines, first-minute veteran tasks, and compare artifacts from the Chummer5a oracle repo."
    )
    assert set(task_queue_item) == {
        "allowed_paths",
        "milestone_id",
        "owned_surfaces",
        "package_id",
        "repo",
        "task",
        "title",
    }
    assert "status" not in task_queue_item
    assert "proof" not in task_queue_item
    assert "landed_commit" not in task_queue_item
    assert "frontier_id" not in task_queue_item
    assert list(task_queue_item.get("allowed_paths") or []) == list(closure_scope.get("allowed_paths") or [])
    assert list(task_queue_item.get("owned_surfaces") or []) == list(
        repeat_prevention.get("active_handoff_owned_surfaces_required") or []
    )
    frontier_briefs = "\n".join(str(item) for item in (task_local_telemetry.get("frontier_briefs") or []))
    assert "4287684466 [W7]" in frontier_briefs
    assert "status: complete" in frontier_briefs
    assert "owners: executive-assistant" in frontier_briefs
    assert "status: complete" not in "\n".join(f"{key}: {value}" for key, value in task_queue_item.items())
    assert append_policy.get("status") == "closed_append_free"
    assert append_policy.get("do_not_append_for_newer_same_package_handoffs") is True
    assert "do not edit completed EA outputs only to record a newer assignment timestamp" in str(
        append_policy.get("worker_action") or ""
    )

    design_queue_item = _single_package_row(design_queue.get("items") or [], "next90-m103-ea-parity-lab")
    queue_item = _single_package_row(queue.get("items") or [], "next90-m103-ea-parity-lab")
    milestones = {int(dict(item).get("id") or 0): dict(item) for item in (registry.get("milestones") or [])}
    task_103_1 = [dict(task) for task in (milestones[103].get("work_tasks") or []) if dict(task).get("id") == 103.1]
    assert len(task_103_1) == 1
    for canonical_queue_item in (design_queue_item, queue_item):
        assert canonical_queue_item.get("status") == "complete"
        assert canonical_queue_item.get("completion_action") == "verify_closed_package_only"
        assert "direct proof command" in str(canonical_queue_item.get("do_not_reopen_reason") or "")
        assert "recapturing Chummer5a oracle baselines or veteran workflow packs" in str(
            canonical_queue_item.get("do_not_reopen_reason") or ""
        )
        assert int(canonical_queue_item.get("frontier_id") or 0) == 4287684466
        assert canonical_queue_item.get("proof"), canonical_queue_item
        assert canonical_queue_item.get("proof") != task_queue_item.get("proof")
    assert design_queue_item.get("status") == queue_item.get("status") == "complete"
    assert int(design_queue_item.get("frontier_id") or 0) == int(queue_item.get("frontier_id") or 0) == int(
        repeat_prevention.get("successor_frontier_id") or 0
    ) == 4287684466
    assert list(design_queue_item.get("allowed_paths") or []) == list(queue_item.get("allowed_paths") or []) == list(
        task_queue_item.get("allowed_paths") or []
    )
    assert list(design_queue_item.get("owned_surfaces") or []) == list(queue_item.get("owned_surfaces") or []) == list(
        task_queue_item.get("owned_surfaces") or []
    )
    assert design_queue_item.get("title") == queue_item.get("title") == task_queue_item.get("title")
    assert design_queue_item.get("task") == queue_item.get("task") == task_queue_item.get("task")

    closure_evidence = "\n".join(
        [
            HANDOFF_CLOSEOUT_PATH.read_text(encoding="utf-8"),
            PUBLISHED_PACK_PATH.read_text(encoding="utf-8"),
            "\n".join(str(item) for item in (task_103_1[0].get("evidence") or [])),
            "\n".join(str(item) for item in (design_queue_item.get("proof") or [])),
            "\n".join(str(item) for item in (queue_item.get("proof") or [])),
        ]
    )
    package_docs_context = "\n".join(
        [
            README_PATH.read_text(encoding="utf-8"),
            PACK_PATH.read_text(encoding="utf-8"),
            ORACLE_BASELINES_PATH.read_text(encoding="utf-8"),
            WORKFLOW_PACK_PATH.read_text(encoding="utf-8"),
            COMPARE_PACKS_PATH.read_text(encoding="utf-8"),
            FIXTURE_INVENTORY_PATH.read_text(encoding="utf-8"),
        ]
    )
    blocked_task_local_closure_markers = [
        task_local_telemetry_path.as_posix(),
        active_prompt_path.as_posix(),
        active_prompt_parent.as_posix(),
        "TASK_LOCAL_TELEMETRY",
        "Successor-wave telemetry",
        "Current steering focus",
        "Assigned successor queue package",
        "Required order",
        "Execution rules inside this run",
        "First action rule",
        "first_commands",
        "frontier_briefs",
        "focus_texts",
        "polling_disabled",
        "queue_item",
        "slice_summary",
        "status_query_supported",
    ]
    for marker in blocked_task_local_closure_markers:
        assert marker.lower() not in closure_evidence.lower(), marker
        assert marker.lower() not in package_docs_context.lower(), marker

    handoff_generated_match = re.search(r"^Generated at:\s*(\S+)", active_handoff_text, re.MULTILINE)
    handoff_run_match = re.search(r"^- Run id:\s*(\S+)", active_handoff_text, re.MULTILINE)
    assert handoff_generated_match, "active handoff missing generated-at"
    assert handoff_run_match, "active handoff missing run id"
    unstable_assignment_tokens = {
        handoff_generated_match.group(1),
        handoff_run_match.group(1),
        active_prompt_parent.name,
        task_local_telemetry_path.name,
    }
    static_closure_artifacts = "\n".join(
        [
            HANDOFF_CLOSEOUT_PATH.read_text(encoding="utf-8"),
            PUBLISHED_PACK_PATH.read_text(encoding="utf-8"),
            README_PATH.read_text(encoding="utf-8"),
        ]
    )
    canonical_queue_proof = "\n".join(
        [
            "\n".join(str(item) for item in (task_103_1[0].get("evidence") or [])),
            "\n".join(str(item) for item in (design_queue_item.get("proof") or [])),
            "\n".join(str(item) for item in (queue_item.get("proof") or [])),
        ]
    )
    for token in unstable_assignment_tokens:
        assert token, token
        assert token not in static_closure_artifacts, token
        assert token not in canonical_queue_proof, token
    for value in task_local_context_values:
        assert value not in static_closure_artifacts, value
        assert value not in canonical_queue_proof, value
    assert task_local_telemetry.get("slice_summary")
    assert task_local_telemetry.get("frontier_briefs")
    assert "slice_summary" not in canonical_queue_proof
    assert "frontier_briefs" not in canonical_queue_proof
    assert str(dict(receipt.get("proof") or {}).get("command") or "") == "python tests/test_chummer5a_parity_lab_pack.py"


def _assert_legacy_program_files_are_context_not_m103_closure() -> None:
    closeout = _yaml(HANDOFF_CLOSEOUT_PATH)
    receipt = _yaml(PUBLISHED_PACK_PATH)
    registry = _yaml(SUCCESSOR_REGISTRY_PATH)
    design_queue = _yaml(DESIGN_SUCCESSOR_QUEUE_PATH)
    queue = _yaml(SUCCESSOR_QUEUE_PATH)
    milestones = {int(dict(item).get("id") or 0): dict(item) for item in (registry.get("milestones") or [])}
    task_103_1 = [
        dict(task)
        for task in (milestones[103].get("work_tasks") or [])
        if dict(task).get("id") == 103.1
    ]
    assert len(task_103_1) == 1
    design_queue_item = _single_package_row(design_queue.get("items") or [], "next90-m103-ea-parity-lab")
    queue_item = _single_package_row(queue.get("items") or [], "next90-m103-ea-parity-lab")

    legacy_context_paths = {NEXT_12_REGISTRY_PATH, PROGRAM_MILESTONES_PATH, ROADMAP_PATH}
    for path in legacy_context_paths:
        assert path.exists(), path
        assert "next90-m103-ea-parity-lab" not in path.read_text(encoding="utf-8")

    closure_evidence = "\n".join(
        [
            HANDOFF_CLOSEOUT_PATH.read_text(encoding="utf-8"),
            PUBLISHED_PACK_PATH.read_text(encoding="utf-8"),
            "\n".join(str(item) for item in (task_103_1[0].get("evidence") or [])),
            "\n".join(str(item) for item in (design_queue_item.get("proof") or [])),
            "\n".join(str(item) for item in (queue_item.get("proof") or [])),
        ]
    )
    for path in legacy_context_paths:
        assert path.as_posix() not in closure_evidence, path
        assert path.name not in closure_evidence, path
    assert SUCCESSOR_REGISTRY_PATH.as_posix() in str(dict(receipt.get("successor_closure") or {}).get("registry") or "")
    assert DESIGN_SUCCESSOR_QUEUE_PATH.as_posix() in str(dict(receipt.get("successor_closure") or {}).get("design_queue") or "")
    assert SUCCESSOR_QUEUE_PATH.as_posix() in str(dict(receipt.get("successor_closure") or {}).get("fleet_queue") or "")
    assert dict(closeout.get("canonical_successor_sources") or {}).get("design_queue") == DESIGN_SUCCESSOR_QUEUE_PATH.as_posix()


def _assert_chummer5a_feedback_notes_do_not_cite_blocked_helper_evidence() -> None:
    feedback_root = ROOT / "feedback"
    package_notes = sorted(feedback_root.glob("*chummer5a-parity-lab*.md"))
    assert package_notes, "missing Chummer5a parity-lab feedback notes"
    current_pass_note = feedback_root / "2026-04-17-chummer5a-parity-lab-current-pass.md"
    assert current_pass_note in package_notes, "missing current append-free M103 parity-lab pass note"
    current_pass_text = current_pass_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in current_pass_text
    assert "Frontier: `4287684466`" in current_pass_text
    assert f"`python tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in current_pass_text
    assert "append-free because the explicit append conditions did not fail" in current_pass_text
    assert "No EA-owned parity-lab extraction work remains" in current_pass_text

    verification_pass_note = feedback_root / "2026-04-17-chummer5a-parity-lab-successor-verification-pass.md"
    assert verification_pass_note in package_notes, "missing current successor verification pass note"
    verification_pass_text = verification_pass_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in verification_pass_text
    assert "Frontier: `4287684466`" in verification_pass_text
    assert f"`python tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in verification_pass_text
    assert "`python -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed" in verification_pass_text
    assert "assigned EA scope remains append-free" in verification_pass_text
    assert "Left the frozen closeout receipt" in verification_pass_text
    assert "No EA-owned parity-lab extraction work remains" in verification_pass_text

    first_action_context_note = feedback_root / "2026-04-17-chummer5a-parity-lab-first-action-context-guard.md"
    assert first_action_context_note in package_notes, "missing current first-action context guard note"
    first_action_context_text = first_action_context_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in first_action_context_text
    assert "Frontier: `4287684466`" in first_action_context_text
    assert "`python tests/test_chummer5a_parity_lab_pack.py` -> `ran=18 failed=0`" in first_action_context_text
    assert "first-action context was verified without refreshing frozen closure receipts" in first_action_context_text
    assert "No EA-owned parity-lab extraction work remains" in first_action_context_text

    exact_startup_note = feedback_root / "2026-04-17-chummer5a-parity-lab-exact-startup-retry-proof.md"
    assert exact_startup_note in package_notes, "missing implementation-only exact-startup retry proof note"
    exact_startup_text = exact_startup_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in exact_startup_text
    assert "Frontier: `4287684466`" in exact_startup_text
    assert "four-command startup block was honored before any other orientation work" in exact_startup_text
    assert "direct-read context list remained follow-on context" in exact_startup_text
    assert "target implementation files were inspected inside `docs`, `tests`, and `feedback`" in exact_startup_text
    assert "`python tests/test_chummer5a_parity_lab_pack.py` -> `ran=18 failed=0`" in exact_startup_text
    assert "frozen parity-lab receipts were not refreshed" in exact_startup_text
    assert "No EA-owned parity-lab extraction work remains" in exact_startup_text

    final_receipt_freeze_note = feedback_root / "2026-04-17-chummer5a-parity-lab-final-receipt-freeze-guard.md"
    assert final_receipt_freeze_note in package_notes, "missing final receipt freeze guard note"
    final_receipt_freeze_text = final_receipt_freeze_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in final_receipt_freeze_text
    assert "Frontier: `4287684466`" in final_receipt_freeze_text
    assert "final receipt refresh commit `c73d531`" in final_receipt_freeze_text
    assert "must remain verification-only" in final_receipt_freeze_text
    assert "SUCCESSOR_HANDOFF_CLOSEOUT.yaml" in final_receipt_freeze_text
    assert "CHUMMER5A_PARITY_ORACLE_PACK.generated.json" in final_receipt_freeze_text
    assert "`python tests/test_chummer5a_parity_lab_pack.py` -> `ran=17 failed=0`" in final_receipt_freeze_text
    assert "completed EA extraction outputs remain append-free" in final_receipt_freeze_text

    proof_relocation_note = feedback_root / "2026-04-18-chummer5a-parity-lab-proof-relocation-and-count-sync.md"
    assert proof_relocation_note in package_notes, "missing proof relocation and count sync note"
    proof_relocation_text = proof_relocation_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in proof_relocation_text
    assert "Frontier: `4287684466`" in proof_relocation_text
    assert "design-owned queue still freezes the original `/docker/EA` closeout anchors" in proof_relocation_text
    assert "successor registry row and Fleet queue mirror now point at the relocated Fleet-owned oracle pack proof" in proof_relocation_text
    assert "python tests/test_chummer5a_parity_lab_pack.py -> ran=18 failed=0" in proof_relocation_text
    assert "No EA-owned parity-lab extraction work remains" not in proof_relocation_text
    assert "does not reopen milestone 103" in proof_relocation_text

    worker_safe_metadata_note = feedback_root / "2026-04-18-chummer5a-parity-lab-worker-safe-metadata-fallback.md"
    assert worker_safe_metadata_note in package_notes, "missing worker-safe metadata fallback note"
    worker_safe_metadata_text = worker_safe_metadata_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in worker_safe_metadata_text
    assert "Frontier: `4287684466`" in worker_safe_metadata_text
    assert "accepts either `- Prompt path:` or the `State root` plus `Run id` fallback" in worker_safe_metadata_text
    assert "same worker-safe prompt" in worker_safe_metadata_text
    assert "var/lib/codex-fleet" in worker_safe_metadata_text
    assert "/docker/fleet/state" in worker_safe_metadata_text
    assert f"`python tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in worker_safe_metadata_text
    assert "`python feedback/chummer5a_parity_lab_worker_safe_context_check.py` -> `ran=3 failed=0`" in worker_safe_metadata_text
    assert "No EA-owned parity-lab extraction work remains" in worker_safe_metadata_text

    implementation_pass_note = feedback_root / "2026-04-17-chummer5a-parity-lab-implementation-only-successor-pass.md"
    assert implementation_pass_note in package_notes, "missing current implementation-only successor pass note"
    implementation_pass_text = implementation_pass_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in implementation_pass_text
    assert "Frontier: `4287684466`" in implementation_pass_text
    assert "`python -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed" in implementation_pass_text
    assert f"`python tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in implementation_pass_text
    assert "implementation-only pass stayed inside `tests` and `feedback`" in implementation_pass_text
    assert "frozen parity-lab receipts and oracle artifacts were not refreshed" in implementation_pass_text
    assert "No EA-owned parity-lab extraction work remains" in implementation_pass_text

    retry_111559_note = feedback_root / "2026-04-17-chummer5a-parity-lab-implementation-only-retry-111559z.md"
    assert retry_111559_note in package_notes, "missing 111559Z implementation-only retry receipt"
    retry_111559_text = retry_111559_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in retry_111559_text
    assert "Frontier: `4287684466`" in retry_111559_text
    assert "The four required startup commands were run before any repo-local inspection" in retry_111559_text
    assert "Target implementation files were inspected with `sed`, `cat`, and `rg` inside allowed paths" in retry_111559_text
    assert "`python tests/test_chummer5a_parity_lab_pack.py` -> `ran=18 failed=0`" in retry_111559_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in retry_111559_text
    assert "No EA-owned parity-lab extraction work remains" in retry_111559_text

    current_retry_note = feedback_root / "2026-04-17-chummer5a-parity-lab-current-implementation-retry.md"
    assert current_retry_note in package_notes, "missing current implementation-only retry receipt"
    current_retry_text = current_retry_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in current_retry_text
    assert "Frontier: `4287684466`" in current_retry_text
    assert "The four-command startup block was completed before design-mirror or repo-local inspection" in current_retry_text
    assert "Listed handoff, roadmap, program milestone, and registry files were read as context only" in current_retry_text
    assert "Target implementation files were inspected with `sed`, `cat`, and `rg` inside allowed paths" in current_retry_text
    assert f"`python tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in current_retry_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in current_retry_text
    assert "No EA-owned parity-lab extraction work remains" in current_retry_text

    retry_114420_note = feedback_root / "2026-04-17-chummer5a-parity-lab-implementation-only-retry-114420z.md"
    assert retry_114420_note in package_notes, "missing 114420Z implementation-only retry receipt"
    retry_114420_text = retry_114420_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in retry_114420_text
    assert "Frontier: `4287684466`" in retry_114420_text
    assert "Retry label: current shard-3 implementation-only retry" in retry_114420_text
    assert "The exact four required startup commands were run first" in retry_114420_text
    assert "Target implementation files were inspected directly with `sed`, `cat`, and `rg` inside allowed paths" in retry_114420_text
    assert "No supervisor status or eta helper was run or cited" in retry_114420_text
    assert "`python -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed" in retry_114420_text
    assert f"`python tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in retry_114420_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in retry_114420_text
    assert "No EA-owned parity-lab extraction work remains" in retry_114420_text

    retry_115402_note = feedback_root / "2026-04-17-chummer5a-parity-lab-implementation-only-retry-115402z.md"
    assert retry_115402_note in package_notes, "missing 115402Z implementation-only retry receipt"
    retry_115402_text = retry_115402_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in retry_115402_text
    assert "Frontier: `4287684466`" in retry_115402_text
    assert "Retry label: shard-3 implementation-only retry" in retry_115402_text
    assert "The required four-command startup block was completed before repo-local inspection" in retry_115402_text
    assert "The listed handoff, roadmap, program milestone, successor registry, and queue files were read as context only" in retry_115402_text
    assert "Target implementation files were inspected directly with `sed`, `cat`, and `rg` inside allowed `docs`, `tests`, and `feedback` paths" in retry_115402_text
    assert "No supervisor status or eta helper was run or cited" in retry_115402_text
    assert "`python -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed" in retry_115402_text
    assert f"`python tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in retry_115402_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in retry_115402_text
    assert "No EA-owned parity-lab extraction work remains" in retry_115402_text

    current_startup_context_note = feedback_root / "2026-04-17-chummer5a-parity-lab-current-startup-context-proof.md"
    assert current_startup_context_note in package_notes, "missing current startup-context proof receipt"
    current_startup_context_text = current_startup_context_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in current_startup_context_text
    assert "Frontier: `4287684466`" in current_startup_context_text
    assert "The exact four-command startup block was completed before direct implementation inspection" in current_startup_context_text
    assert "Broader handoff, roadmap, program milestone, registry, and queue files were read as context only" in current_startup_context_text
    assert "Historical operator-status snippets were treated as stale notes, not commands to repeat" in current_startup_context_text
    assert "No supervisor status or eta helper was run or cited" in current_startup_context_text
    assert "Target implementation files were inspected with `sed`, `cat`, and `rg` inside allowed paths" in current_startup_context_text
    assert "`python -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed" in current_startup_context_text
    assert f"`python tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in current_startup_context_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in current_startup_context_text
    assert "No EA-owned parity-lab extraction work remains" in current_startup_context_text

    retry_120441_note = feedback_root / "2026-04-17-chummer5a-parity-lab-implementation-only-retry-120441z.md"
    assert retry_120441_note in package_notes, "missing 120441Z implementation-only retry receipt"
    retry_120441_text = retry_120441_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in retry_120441_text
    assert "Frontier: `4287684466`" in retry_120441_text
    assert "Retry label: shard-3 implementation-only successor-wave retry" in retry_120441_text
    assert "The exact four-command startup block was completed before any added orientation step" in retry_120441_text
    assert "The required direct-read context files were read as follow-on context only" in retry_120441_text
    assert "Target implementation files were inspected directly with `sed`, `cat`, and `rg` inside allowed paths" in retry_120441_text
    assert "No supervisor status or eta helper was run or cited" in retry_120441_text
    assert "`python -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed" in retry_120441_text
    assert f"`python tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in retry_120441_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in retry_120441_text
    assert "No EA-owned parity-lab extraction work remains" in retry_120441_text

    retry_120655_note = feedback_root / "2026-04-17-chummer5a-parity-lab-implementation-only-retry-120655z.md"
    assert retry_120655_note in package_notes, "missing 120655Z implementation-only retry receipt"
    retry_120655_text = retry_120655_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in retry_120655_text
    assert "Frontier: `4287684466`" in retry_120655_text
    assert "Retry label: shard-3 implementation-only successor-wave retry 120655Z" in retry_120655_text
    assert "The exact four required startup commands were run first and in order" in retry_120655_text
    assert "The direct-read context files were read only after the startup block" in retry_120655_text
    assert "Historical operator-status snippets were treated as stale notes, not commands to repeat" in retry_120655_text
    assert "Target implementation files were inspected directly with `sed`, `cat`, and `rg` inside allowed paths" in retry_120655_text
    assert "No supervisor status or eta helper was run or cited" in retry_120655_text
    assert "`python -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed" in retry_120655_text
    assert f"`python tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in retry_120655_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in retry_120655_text
    assert "No EA-owned parity-lab extraction work remains" in retry_120655_text

    retry_125115_note = feedback_root / "2026-04-17-chummer5a-parity-lab-implementation-only-retry-125115z.md"
    assert retry_125115_note in package_notes, "missing 125115Z implementation-only retry receipt"
    retry_125115_text = retry_125115_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in retry_125115_text
    assert "Frontier: `4287684466`" in retry_125115_text
    assert "Retry label: shard-3 implementation-only successor-wave retry 125115Z" in retry_125115_text
    assert "The exact four required startup commands were run first and in order" in retry_125115_text
    assert "The required direct-read files were read only after the startup block" in retry_125115_text
    assert "Historical operator-status snippets were treated as stale notes, not commands to repeat" in retry_125115_text
    assert "Target implementation files were inspected directly with `sed`, `cat`, and `rg` inside allowed paths" in retry_125115_text
    assert "No supervisor status or eta helper was run or cited" in retry_125115_text
    assert "`python -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed" in retry_125115_text
    assert f"`python tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in retry_125115_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in retry_125115_text
    assert "No EA-owned parity-lab extraction work remains" in retry_125115_text

    retry_successor_note = feedback_root / "2026-04-17-chummer5a-parity-lab-successor-retry-implementation-only.md"
    assert retry_successor_note in package_notes, "missing successor implementation-only retry receipt"
    retry_successor_text = retry_successor_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in retry_successor_text
    assert "Frontier: `4287684466`" in retry_successor_text
    assert "Retry label: implementation-only successor-wave retry" in retry_successor_text
    assert "The exact four-command startup block was run before any extra orientation or repo-local inspection" in retry_successor_text
    assert "The broader direct-read file list was read after the startup block and treated as context only" in retry_successor_text
    assert "Target implementation files were inspected directly with `sed`, `cat`, and `rg` inside allowed paths" in retry_successor_text
    assert "No supervisor status or eta helper was run or cited" in retry_successor_text
    assert "`python -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed" in retry_successor_text
    assert f"`python tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in retry_successor_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in retry_successor_text
    assert "No EA-owned parity-lab extraction work remains" in retry_successor_text

    retry_130525_note = feedback_root / "2026-04-17-chummer5a-parity-lab-implementation-only-retry-130525z.md"
    assert retry_130525_note in package_notes, "missing 130525Z implementation-only retry receipt"
    retry_130525_text = retry_130525_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in retry_130525_text
    assert "Frontier: `4287684466`" in retry_130525_text
    assert "Retry label: shard-3 implementation-only successor-wave retry 130525Z" in retry_130525_text
    assert "The exact four required startup commands were run first and in order" in retry_130525_text
    assert "The broader direct-read context files were read only after the startup block" in retry_130525_text
    assert "Historical operator-status snippets were treated as stale notes, not commands to repeat" in retry_130525_text
    assert "Target implementation files were inspected directly with `sed`, `cat`, and `rg` inside allowed paths" in retry_130525_text
    assert "No supervisor status or eta helper was run or cited" in retry_130525_text
    assert "`python -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed" in retry_130525_text
    assert f"`python tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in retry_130525_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in retry_130525_text
    assert "No EA-owned parity-lab extraction work remains" in retry_130525_text

    retry_130951_note = feedback_root / "2026-04-17-chummer5a-parity-lab-implementation-only-retry-130951z.md"
    assert retry_130951_note in package_notes, "missing 130951Z implementation-only retry receipt"
    retry_130951_text = retry_130951_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in retry_130951_text
    assert "Frontier: `4287684466`" in retry_130951_text
    assert "Retry label: shard-3 implementation-only successor-wave retry 130951Z" in retry_130951_text
    assert "The four required startup commands were run first and in order" in retry_130951_text
    assert "The broader direct-read context files were read only after the startup block" in retry_130951_text
    assert "Historical operator-status snippets were treated as stale notes, not commands to repeat" in retry_130951_text
    assert "Target implementation files were inspected directly with `sed`, `cat`, and `rg` inside allowed paths" in retry_130951_text
    assert "No supervisor status or eta helper was run or cited" in retry_130951_text
    assert "`python -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed" in retry_130951_text
    assert f"`python tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in retry_130951_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in retry_130951_text
    assert "No EA-owned parity-lab extraction work remains" in retry_130951_text

    retry_131153_note = feedback_root / "2026-04-17-chummer5a-parity-lab-implementation-only-retry-131153z.md"
    assert retry_131153_note in package_notes, "missing 131153Z implementation-only retry receipt"
    retry_131153_text = retry_131153_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in retry_131153_text
    assert "Frontier: `4287684466`" in retry_131153_text
    assert "Retry label: shard-3 implementation-only successor-wave retry 131153Z" in retry_131153_text
    assert "The four required startup commands were run first and in order" in retry_131153_text
    assert "The broader direct-read context files were read only after the startup block" in retry_131153_text
    assert "Historical operator-status snippets were treated as stale notes, not commands to repeat" in retry_131153_text
    assert "Target implementation files were inspected directly with `sed`, `cat`, and `rg` inside allowed paths" in retry_131153_text
    assert "No supervisor status or eta helper was run or cited" in retry_131153_text
    assert "`python -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed" in retry_131153_text
    assert f"`python tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in retry_131153_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in retry_131153_text
    assert "No EA-owned parity-lab extraction work remains" in retry_131153_text

    retry_131725_note = feedback_root / "2026-04-17-chummer5a-parity-lab-implementation-only-retry-131725z.md"
    assert retry_131725_note in package_notes, "missing 131725Z implementation-only retry receipt"
    retry_131725_text = retry_131725_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in retry_131725_text
    assert "Frontier: `4287684466`" in retry_131725_text
    assert "Retry label: shard-3 implementation-only successor-wave retry 131725Z" in retry_131725_text
    assert "The four required startup commands were run first and in order" in retry_131725_text
    assert "The broader direct-read context files were read only after the startup block" in retry_131725_text
    assert "Historical operator-status snippets were treated as stale notes, not commands to repeat" in retry_131725_text
    assert "Target implementation files were inspected directly with `sed`, `cat`, and `rg` inside allowed paths" in retry_131725_text
    assert "No supervisor status or eta helper was run or cited" in retry_131725_text
    assert "`python -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed" in retry_131725_text
    assert f"`python tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in retry_131725_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in retry_131725_text
    assert "No EA-owned parity-lab extraction work remains" in retry_131725_text

    retry_132446_note = feedback_root / "2026-04-17-chummer5a-parity-lab-implementation-only-retry-132446z.md"
    assert retry_132446_note in package_notes, "missing 132446Z implementation-only retry receipt"
    retry_132446_text = retry_132446_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in retry_132446_text
    assert "Frontier: `4287684466`" in retry_132446_text
    assert "Retry label: shard-3 implementation-only successor-wave retry 132446Z" in retry_132446_text
    assert "The four required startup commands were run first and in order" in retry_132446_text
    assert "The broader direct-read context files were read only after the startup block" in retry_132446_text
    assert "Historical operator-status snippets were treated as stale notes, not commands to repeat" in retry_132446_text
    assert "Target implementation files were inspected directly with `sed`, `cat`, and `rg` inside allowed paths" in retry_132446_text
    assert "No supervisor status or eta helper was run or cited" in retry_132446_text
    assert "`python -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed" in retry_132446_text
    assert f"`python tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in retry_132446_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in retry_132446_text
    assert "No EA-owned parity-lab extraction work remains" in retry_132446_text

    retry_192408_note = feedback_root / "2026-04-17-chummer5a-parity-lab-implementation-only-retry-192408z.md"
    assert retry_192408_note in package_notes, "missing 192408Z implementation-only retry receipt"
    retry_192408_text = retry_192408_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in retry_192408_text
    assert "Frontier: `4287684466`" in retry_192408_text
    assert "Retry label: shard-3 implementation-only successor-wave retry" in retry_192408_text
    assert "the required startup block was completed first" in retry_192408_text
    assert "Read the broader handoff, roadmap, program milestone, successor registry, and queue files as assignment context only" in retry_192408_text
    assert "Inspected target implementation files directly with `sed`, `cat`, and `rg` inside allowed `docs`, `tests`, and `feedback` paths" in retry_192408_text
    assert "Confirmed `python` is unavailable in this worker runtime" in retry_192408_text
    assert "`python3 -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed" in retry_192408_text
    assert f"`python3 tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in retry_192408_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in retry_192408_text
    assert "No EA-owned parity-lab extraction work remains" in retry_192408_text

    retry_193050_note = feedback_root / "2026-04-17-chummer5a-parity-lab-implementation-only-retry-193050z.md"
    assert retry_193050_note in package_notes, "missing 193050Z implementation-only retry receipt"
    retry_193050_text = retry_193050_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in retry_193050_text
    assert "Frontier: `4287684466`" in retry_193050_text
    assert "Retry label: shard-3 implementation-only successor-wave retry 193050Z" in retry_193050_text
    assert "The exact four required startup commands were run first and in order" in retry_193050_text
    assert "The broader direct-read context files were read only after the startup block" in retry_193050_text
    assert "Historical operator-status snippets were treated as stale notes, not commands to repeat" in retry_193050_text
    assert "Target implementation files were inspected directly with `sed`, `cat`, and `rg` inside allowed paths" in retry_193050_text
    assert "No supervisor status or eta helper was run or cited" in retry_193050_text
    assert "`python3 -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed" in retry_193050_text
    assert f"`python3 tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in retry_193050_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in retry_193050_text
    assert "No EA-owned parity-lab extraction work remains" in retry_193050_text

    retry_193326_note = feedback_root / "2026-04-17-chummer5a-parity-lab-implementation-only-retry-193326z.md"
    assert retry_193326_note in package_notes, "missing 193326Z implementation-only retry receipt"
    retry_193326_text = retry_193326_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in retry_193326_text
    assert "Frontier: `4287684466`" in retry_193326_text
    assert "Retry label: shard-3 implementation-only successor-wave retry 193326Z" in retry_193326_text
    assert "The exact four required startup commands were run first" in retry_193326_text
    assert "The broader direct-read context files were read after the startup block as assignment context only" in retry_193326_text
    assert "Historical operator-status snippets were treated as stale notes, not commands to repeat" in retry_193326_text
    assert "Target implementation files were inspected directly with `sed`, `cat`, and `rg` inside allowed paths" in retry_193326_text
    assert "No supervisor status or eta helper was run or cited" in retry_193326_text
    assert "`python3 -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed" in retry_193326_text
    assert f"`python3 tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in retry_193326_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in retry_193326_text
    assert "No EA-owned parity-lab extraction work remains" in retry_193326_text

    retry_193529_note = feedback_root / "2026-04-17-chummer5a-parity-lab-implementation-only-retry-193529z.md"
    assert retry_193529_note in package_notes, "missing 193529Z implementation-only retry receipt"
    retry_193529_text = retry_193529_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in retry_193529_text
    assert "Frontier: `4287684466`" in retry_193529_text
    assert "Retry label: shard-3 implementation-only successor-wave retry 193529Z" in retry_193529_text
    assert "The exact four required startup commands were run first" in retry_193529_text
    assert "The broader direct-read context files were read after the startup block as assignment context only" in retry_193529_text
    assert "Historical operator-status snippets were treated as stale notes, not commands to repeat" in retry_193529_text
    assert "Target implementation files were inspected directly with `sed`, `cat`, and `rg` inside allowed paths" in retry_193529_text
    assert "No supervisor status or eta helper was run or cited" in retry_193529_text
    assert "`python3 -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed" in retry_193529_text
    assert f"`python3 tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in retry_193529_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in retry_193529_text
    assert "No EA-owned parity-lab extraction work remains" in retry_193529_text

    retry_193944_note = feedback_root / "2026-04-17-chummer5a-parity-lab-implementation-only-retry-193944z.md"
    assert retry_193944_note in package_notes, "missing 193944Z implementation-only retry receipt"
    retry_193944_text = retry_193944_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in retry_193944_text
    assert "Frontier: `4287684466`" in retry_193944_text
    assert "Retry label: shard-3 implementation-only successor-wave retry 193944Z" in retry_193944_text
    assert "The exact four required startup commands were run first" in retry_193944_text
    assert "The broader direct-read context files were read after the startup block as assignment context only" in retry_193944_text
    assert "The shard runtime handoff was used as worker-safe resume context" in retry_193944_text
    assert "Historical operator-status snippets were treated as stale notes, not commands to repeat" in retry_193944_text
    assert "Target implementation files were inspected directly with `sed`, `cat`, and `rg` inside allowed paths" in retry_193944_text
    assert "No supervisor status or eta helper was run or cited" in retry_193944_text
    assert "`python3 -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed" in retry_193944_text
    assert f"`python3 tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in retry_193944_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in retry_193944_text
    assert "No EA-owned parity-lab extraction work remains" in retry_193944_text

    retry_200544_note = feedback_root / "2026-04-17-chummer5a-parity-lab-implementation-only-retry-200544z.md"
    assert retry_200544_note in package_notes, "missing 200544Z implementation-only retry receipt"
    retry_200544_text = retry_200544_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in retry_200544_text
    assert "Frontier: `4287684466`" in retry_200544_text
    assert "Retry label: shard-3 implementation-only successor-wave retry 200544Z" in retry_200544_text
    assert "The exact four required startup commands were run first" in retry_200544_text
    assert "The broader direct-read context files were read after the startup block as assignment context only" in retry_200544_text
    assert "The shard runtime handoff was used as worker-safe resume context" in retry_200544_text
    assert "Historical operator-status snippets were treated as stale notes, not commands to repeat" in retry_200544_text
    assert "Target implementation files were inspected directly with `sed`, `cat`, and `rg` inside allowed paths" in retry_200544_text
    assert "No supervisor status or eta helper was run or cited" in retry_200544_text
    assert "`python3 -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed" in retry_200544_text
    assert f"`python3 tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in retry_200544_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in retry_200544_text
    assert "No EA-owned parity-lab extraction work remains" in retry_200544_text

    retry_200823_note = feedback_root / "2026-04-17-chummer5a-parity-lab-implementation-only-retry-200823z.md"
    assert retry_200823_note in package_notes, "missing 200823Z implementation-only retry receipt"
    retry_200823_text = retry_200823_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in retry_200823_text
    assert "Frontier: `4287684466`" in retry_200823_text
    assert "Retry label: shard-3 implementation-only successor-wave retry 200823Z" in retry_200823_text
    assert "The exact four required startup commands were run first" in retry_200823_text
    assert "The broader direct-read context files were read after the startup block as assignment context only" in retry_200823_text
    assert "The shard runtime handoff was used as worker-safe resume context" in retry_200823_text
    assert "Historical operator-status snippets were treated as stale notes, not commands to repeat" in retry_200823_text
    assert "Target implementation files were inspected directly with `sed`, `cat`, and `rg` inside allowed paths" in retry_200823_text
    assert "No supervisor status or eta helper was run or cited" in retry_200823_text
    assert "`python3 -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed" in retry_200823_text
    assert f"`python3 tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in retry_200823_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in retry_200823_text
    assert "No EA-owned parity-lab extraction work remains" in retry_200823_text

    retry_201022_note = feedback_root / "2026-04-17-chummer5a-parity-lab-implementation-only-retry-201022z.md"
    assert retry_201022_note in package_notes, "missing 201022Z implementation-only retry receipt"
    retry_201022_text = retry_201022_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in retry_201022_text
    assert "Frontier: `4287684466`" in retry_201022_text
    assert "Retry label: shard-3 implementation-only successor-wave retry 201022Z" in retry_201022_text
    assert "The exact four required startup commands were run first" in retry_201022_text
    assert "The broader direct-read context files were read after the startup block as assignment context only" in retry_201022_text
    assert "The shard runtime handoff was used as worker-safe resume context" in retry_201022_text
    assert "Historical operator-status snippets were treated as stale notes, not commands to repeat" in retry_201022_text
    assert "Target implementation files were inspected directly with `sed`, `cat`, and `rg` inside allowed paths" in retry_201022_text
    assert "No supervisor status or eta helper was run or cited" in retry_201022_text
    assert "`python3 -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed" in retry_201022_text
    assert f"`python3 tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in retry_201022_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in retry_201022_text
    assert "No EA-owned parity-lab extraction work remains" in retry_201022_text

    retry_201212_note = feedback_root / "2026-04-17-chummer5a-parity-lab-implementation-only-retry-201212z.md"
    assert retry_201212_note in package_notes, "missing 201212Z implementation-only retry receipt"
    retry_201212_text = retry_201212_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in retry_201212_text
    assert "Frontier: `4287684466`" in retry_201212_text
    assert "Retry label: shard-3 implementation-only successor-wave retry 201212Z" in retry_201212_text
    assert "The exact four required startup commands were run first" in retry_201212_text
    assert "The broader direct-read context files were read after the startup block as assignment context only" in retry_201212_text
    assert "The shard runtime handoff was used as worker-safe resume context" in retry_201212_text
    assert "Historical operator-status snippets were treated as stale notes, not commands to repeat" in retry_201212_text
    assert "Target implementation files were inspected directly with `sed`, `cat`, and `rg` inside allowed paths" in retry_201212_text
    assert "No supervisor status or eta helper was run or cited" in retry_201212_text
    assert "`python3 -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed" in retry_201212_text
    assert f"`python3 tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in retry_201212_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in retry_201212_text
    assert "No EA-owned parity-lab extraction work remains" in retry_201212_text

    retry_205051_note = feedback_root / "2026-04-17-chummer5a-parity-lab-implementation-only-retry-205051z.md"
    assert retry_205051_note in package_notes, "missing 205051Z implementation-only retry receipt"
    retry_205051_text = retry_205051_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in retry_205051_text
    assert "Frontier: `4287684466`" in retry_205051_text
    assert "Retry label: shard-3 implementation-only successor-wave retry 205051Z" in retry_205051_text
    assert "The exact four-command startup block was completed first and in order" in retry_205051_text
    assert "The broader direct-read context files were read after the startup block as assignment context only" in retry_205051_text
    assert "The shard runtime handoff was used as worker-safe resume context" in retry_205051_text
    assert "Historical operator-status snippets were treated as stale notes, not commands to repeat" in retry_205051_text
    assert "Target implementation files were inspected directly with `sed`, `cat`, and `rg` inside allowed paths" in retry_205051_text
    assert "No supervisor status or eta helper was run or cited" in retry_205051_text
    assert "`python3 -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed" in retry_205051_text
    assert f"`python3 tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in retry_205051_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in retry_205051_text
    assert "No EA-owned parity-lab extraction work remains" in retry_205051_text

    retry_205302_note = feedback_root / "2026-04-17-chummer5a-parity-lab-implementation-only-retry-205302z.md"
    assert retry_205302_note in package_notes, "missing 205302Z implementation-only retry receipt"
    retry_205302_text = retry_205302_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in retry_205302_text
    assert "Frontier: `4287684466`" in retry_205302_text
    assert "Retry label: shard-3 implementation-only successor-wave retry 205302Z" in retry_205302_text
    assert "The exact four-command startup block was completed before any follow-on context read" in retry_205302_text
    assert "The listed direct-read files were read after the startup block as assignment context only" in retry_205302_text
    assert "The shard runtime handoff generated at `2026-04-17T20:53:10Z` was used as worker-safe resume context" in retry_205302_text
    assert "Historical operator-status snippets were treated as stale notes, not commands to repeat" in retry_205302_text
    assert "Target implementation files were inspected directly with `sed`, `cat`, and `rg` inside allowed paths" in retry_205302_text
    assert "No supervisor status or eta helper was run or cited" in retry_205302_text
    assert "`python3 -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed" in retry_205302_text
    assert f"`python3 tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in retry_205302_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in retry_205302_text
    assert "No EA-owned parity-lab extraction work remains" in retry_205302_text

    python3_runtime_note = feedback_root / "2026-04-17-chummer5a-parity-lab-python3-runtime-proof.md"
    assert python3_runtime_note in package_notes, "missing python3 runtime proof receipt"
    python3_runtime_text = python3_runtime_note.read_text(encoding="utf-8")
    assert "Package: `next90-m103-ea-parity-lab`" in python3_runtime_text
    assert "Frontier: `4287684466`" in python3_runtime_text
    assert "`python tests/test_chummer5a_parity_lab_pack.py` was unavailable in this worker runtime because `python` was not on `PATH`" in python3_runtime_text
    assert f"`python3 tests/test_chummer5a_parity_lab_pack.py` -> `{_expected_direct_result()}`" in python3_runtime_text
    assert "This is interpreter compatibility for the same test file, not a receipt refresh" in python3_runtime_text
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, and fixture inventory were not refreshed" in python3_runtime_text
    assert "No EA-owned parity-lab extraction work remains" in python3_runtime_text

    blocked_evidence_markers = [
        "TASK_LOCAL_TELEMETRY.generated.json",
        "/runs/",
        "Successor-wave telemetry",
        "eta:",
        "remaining milestones",
        "remaining queue items",
        "critical path",
        "Current steering focus",
        "profile focus",
        "owner focus",
        "text focus",
        "Assigned successor queue package",
        "Successor frontier ids to prioritize first",
        "Successor frontier detail",
        "Execution rules inside this run",
        "First action rule",
        "Recent stderr tail",
        "first_commands:",
        "frontier_briefs:",
        "focus_texts:",
        "polling_disabled:",
        "queue_item:",
        "slice_summary:",
        "status_query_supported:",
        '"first_commands"',
        '"frontier_briefs"',
        '"focus_texts"',
        '"polling_disabled"',
        '"queue_item"',
        '"slice_summary"',
        '"status_query_supported"',
        "Supervisor status polling",
        "status helper output:",
        "operator telemetry output:",
        "operator-owned helper output:",
        "operator/ooda loop owns telemetry",
        "hard-blocked",
        "count as run failure",
        "return non-zero",
    ]
    helper_context_markers = (
        "operator telemetry",
        "active-run helper",
        "active run helper",
        "telemetry helper",
        "status helper",
        "supervisor status",
        "supervisor eta",
        "run_chummer_design_supervisor",
        "chummer_design_supervisor.py",
        "ooda",
    )
    allowed_negative_helper_context = (
        "no operator telemetry",
        "did not invoke operator telemetry",
        "no operator-owned active-run helper evidence was used",
        "do not invoke or cite operator-owned active-run helper evidence",
        "do not cite active-run helper output",
        "do not cite operator-owned helper output",
        "no active-run helper commands were invoked",
        "did not invoke operator telemetry, active-run helper commands",
        "no operator telemetry, active-run helper commands",
        "no operator telemetry, active-run helper commands, oracle recapture",
        "rejects supervisor status or eta helper phrasing",
        "do not query supervisor status or eta",
        "no supervisor status or eta",
    )
    active_handoff_text = ACTIVE_RUN_HANDOFF_PATH.read_text(encoding="utf-8")
    task_local_telemetry_path = _task_local_telemetry_path()
    active_prompt_path = _active_handoff_prompt_path()
    handoff_generated_match = re.search(r"^Generated at:\s*(\S+)", active_handoff_text, re.MULTILINE)
    handoff_run_match = re.search(r"^- Run id:\s*(\S+)", active_handoff_text, re.MULTILINE)
    assert handoff_generated_match, "active handoff missing generated-at"
    assert handoff_run_match, "active handoff missing run id"
    unstable_assignment_tokens = {
        handoff_generated_match.group(1),
        handoff_run_match.group(1),
        active_prompt_path.as_posix(),
        active_prompt_path.parent.as_posix(),
        active_prompt_path.parent.name,
        task_local_telemetry_path.as_posix(),
    }
    for note_path in package_notes:
        note_text = note_path.read_text(encoding="utf-8")
        note_text_lower = note_text.lower()
        for marker in blocked_evidence_markers:
            assert marker.lower() not in note_text_lower, f"{note_path}: {marker}"
        for marker in helper_context_markers:
            if marker not in note_text_lower:
                continue
            assert any(allowed in note_text_lower for allowed in allowed_negative_helper_context), (
                f"{note_path}: {marker} must stay negative worker-safety context, not closure evidence"
            )
        for token in unstable_assignment_tokens:
            assert token not in note_text, f"{note_path}: unstable assignment token leaked into feedback proof"


def test_pack_source_pointers_resolve_to_repo_local_evidence() -> None:
    pack = _yaml(PACK_PATH)
    source_repos = dict(pack.get("source_repos") or {})
    chummer5a_root = Path(str(source_repos.get("chummer5a") or ""))
    assert chummer5a_root == Path("/docker/chummer5a")
    assert chummer5a_root.is_dir()
    assert Path(str(source_repos.get("chummer6_ui") or "")).is_dir()

    oracle_sources = dict(pack.get("oracle_sources") or {})
    for key in ("parity_oracle_json", "parity_checklist_md", "parity_audit_md"):
        path = Path(str(oracle_sources.get(key) or ""))
        assert path.exists(), f"{key}: {path}"
        assert path.parent == chummer5a_root / "docs", f"{key}: {path}"
        assert path.name in {"PARITY_ORACLE.json", "PARITY_CHECKLIST.md", "PARITY_AUDIT.md"}, f"{key}: {path}"

    baselines = _yaml(ORACLE_BASELINES_PATH)
    baseline_sources = dict(baselines.get("source") or {})
    for key in ("parity_oracle_json", "parity_checklist_md", "parity_audit_md"):
        assert Path(str(baseline_sources.get(key) or "")) == Path(str(oracle_sources.get(key) or ""))

    workflow = _yaml(WORKFLOW_PACK_PATH)
    workflow_sources = dict(workflow.get("source_of_truth") or {})
    assert Path(str(workflow_sources.get("veteran_gate") or "")).exists()
    assert Path(str(workflow_sources.get("flagship_parity_registry") or "")).exists()
    for path_text in workflow_sources.get("chummer5a_oracle") or []:
        path = Path(str(path_text))
        assert path.exists(), str(path)

    compare = _yaml(COMPARE_PACKS_PATH)
    compare_sources = dict(compare.get("source_of_truth") or {})
    assert Path(str(compare_sources.get("flagship_parity_registry") or "")).exists()
    assert Path(str(compare_sources.get("chummer5a_oracle") or "")).exists()

    fixture_inventory = _yaml(FIXTURE_INVENTORY_PATH)
    inventory_sources = dict(fixture_inventory.get("source_of_truth") or {})
    assert Path(str(inventory_sources.get("parity_oracle_json") or "")).exists()
    assert Path(str(inventory_sources.get("parity_checklist") or "")).exists()
    assert Path(str(inventory_sources.get("parity_audit") or "")).exists()


def test_pack_readiness_evidence_tracks_green_flagship_packet_without_reopening_closeout() -> None:
    pack = _yaml(PACK_PATH)
    readiness = _yaml(FLAGSHIP_READINESS_PATH)
    evidence = dict(pack.get("readiness_evidence") or {})
    completion_audit = dict(readiness.get("completion_audit") or {})
    external_host_proof = dict(readiness.get("external_host_proof") or {})

    assert evidence.get("flagship_readiness") == FLAGSHIP_READINESS_PATH.as_posix()
    assert evidence.get("flagship_readiness_status") in {"pass", "fail"}
    assert evidence.get("external_host_proof_status") in {"pass", "fail"}
    assert readiness.get("generated_at") >= evidence.get("flagship_readiness_generated_at")
    assert completion_audit.get("status") == readiness.get("status")
    live_unresolved = int(external_host_proof.get("unresolved_request_count", -1))
    completion_unresolved = completion_audit.get("unresolved_external_proof_request_count")
    assert int(-1 if completion_unresolved is None else completion_unresolved) == live_unresolved
    observed_unresolved = int(evidence.get("unresolved_external_host_proof_requests", -1))
    pack_notes = "\n".join(str(item) for item in (pack.get("notes") or []))
    assert "observed packet snapshot" in pack_notes
    assert "may move between pass and fail" in pack_notes
    if (
        evidence.get("flagship_readiness_status") != readiness.get("status")
        or evidence.get("external_host_proof_status") != external_host_proof.get("status")
        or observed_unresolved != live_unresolved
    ):
        assert readiness.get("generated_at") > evidence.get("flagship_readiness_generated_at")


def test_feedback_closeout_no_longer_carries_stale_host_proof_blocker() -> None:
    text = FEEDBACK_CLOSEOUT_PATH.read_text(encoding="utf-8")

    assert "still required before full `desktop_client` readiness can turn green" not in text
    assert "must not reopen the closed flagship wave" in text
    assert "zero unresolved external host-proof requests" in text


def test_screenshot_corpus_only_claims_files_that_exist() -> None:
    baselines = _yaml(ORACLE_BASELINES_PATH)
    corpus = dict(baselines.get("screenshot_corpora") or {})
    screenshot_root = Path(str(corpus.get("promoted_ui_screenshot_root") or ""))
    supplemental_root = Path(str(corpus.get("supplemental_finished_wave_screenshot_root") or ""))

    assert screenshot_root.exists(), str(screenshot_root)
    assert supplemental_root.exists(), str(supplemental_root)
    assert (
        supplemental_root
        == Path("/docker/chummercomplete/chummer-presentation/.codex-studio/published/ui-flagship-release-gate-screenshots")
    )
    captured = [str(item) for item in (corpus.get("captured_screenshots") or [])]
    supplemental = [str(item) for item in (corpus.get("supplemental_finished_wave_screenshots") or [])]
    assert captured
    assert supplemental == ["16-master-index-dialog-light.png", "17-character-roster-dialog-light.png"]

    for filename in captured:
        _assert_png_baseline_file(screenshot_root / filename)
    for filename in supplemental:
        _assert_png_baseline_file(supplemental_root / filename)
    assert not set(captured).intersection(supplemental)
    _assert_screenshot_baseline_manifest_is_complete_and_source_backed()


def _assert_png_baseline_file(path: Path) -> None:
    assert path.exists(), str(path)
    assert path.suffix == ".png", str(path)
    payload = path.read_bytes()
    assert payload.startswith(b"\x89PNG\r\n\x1a\n"), str(path)
    assert len(payload) > 10_000, f"{path} is too small to be a useful screenshot baseline"


def _assert_screenshot_baseline_manifest_is_complete_and_source_backed() -> None:
    baselines = _yaml(ORACLE_BASELINES_PATH)
    corpus = dict(baselines.get("screenshot_corpora") or {})
    baseline_rows = [dict(item) for item in (baselines.get("screenshot_baselines") or [])]
    baseline_sets = [dict(item) for item in (baselines.get("screenshot_baseline_sets") or [])]
    alignment = dict(baselines.get("oracle_alignment") or {})
    workflow = _yaml(WORKFLOW_PACK_PATH)
    compare = _yaml(COMPARE_PACKS_PATH)
    legacy_form_landmark_ids = {str(item).strip() for item in dict(baselines.get("legacy_form_landmarks") or {}).keys()}

    set_ids = {str(item.get("id") or "").strip() for item in baseline_sets}
    screenshot_ids = [str(item.get("id") or "").strip() for item in baseline_rows]
    filenames = [str(item.get("filename") or "").strip() for item in baseline_rows]
    captured = [str(item) for item in (corpus.get("captured_screenshots") or [])]
    supplemental = [str(item) for item in (corpus.get("supplemental_finished_wave_screenshots") or [])]
    workflow_task_ids = {str(dict(item).get("id") or "").strip() for item in (workflow.get("required_first_minute_tasks") or [])}
    compare_family_ids = {str(dict(item).get("id") or "").strip() for item in (compare.get("families") or [])}

    assert len(set_ids) == len(baseline_sets)
    assert len(set(screenshot_ids)) == len(baseline_rows)
    assert len(set(filenames)) == len(baseline_rows)
    assert len(baseline_rows) == 17
    assert set(filenames) == set(captured) | set(supplemental)
    assert int(dict(alignment.get("parity_checklist_summary") or {}).get("tabs_covered") or 0) == 17
    assert int(dict(alignment.get("parity_checklist_summary") or {}).get("workspace_actions_covered") or 0) == 47
    assert int(alignment.get("screenshot_baseline_total") or 0) == len(baseline_rows)
    _assert_legacy_form_landmarks_are_complete_and_source_backed(baselines, workflow, compare)

    for item in baseline_sets:
        screenshot_refs = [str(entry) for entry in (item.get("screenshot_ids") or [])]
        assert screenshot_refs, item
        assert set(screenshot_refs) <= set(screenshot_ids), item

    for row in baseline_rows:
        baseline_id = str(row.get("id") or "").strip()
        filename = str(row.get("filename") or "").strip()
        corpus_id = str(row.get("corpus") or "").strip()
        source_path = Path(str(row.get("oracle_source_path") or ""))
        tokens = [str(item) for item in (row.get("oracle_tokens") or [])]
        baseline_set_ids = [str(item) for item in (row.get("set_ids") or [])]
        veteran_task_ids = [str(item) for item in (row.get("veteran_task_ids") or [])]
        family_ids = [str(item) for item in (row.get("compare_family_ids") or [])]
        linked_legacy_landmark_ids = [str(item) for item in (row.get("legacy_form_landmark_ids") or [])]

        assert baseline_id
        assert filename
        assert corpus_id in {"promoted_ui", "supplemental_finished_wave"}
        assert baseline_set_ids
        assert set(baseline_set_ids) <= set_ids
        assert veteran_task_ids
        assert set(veteran_task_ids) <= workflow_task_ids
        assert family_ids
        assert set(family_ids) <= compare_family_ids
        if linked_legacy_landmark_ids:
            assert set(linked_legacy_landmark_ids) <= legacy_form_landmark_ids, baseline_id
        assert source_path.exists(), f"{baseline_id}: {source_path}"
        assert source_path.is_relative_to(Path("/docker/chummer5a")), f"{baseline_id}: {source_path}"
        assert tokens
        source_text = source_path.read_text(encoding="utf-8")
        for token in tokens:
            assert token in source_text, f"{baseline_id}: {token}"


def _assert_legacy_form_landmarks_are_complete_and_source_backed(
    baselines: dict, workflow: dict, compare: dict
) -> None:
    landmark_rows = dict(baselines.get("legacy_form_landmarks") or {})
    alignment = dict(baselines.get("oracle_alignment") or {})
    workflow_task_ids = {str(dict(item).get("id") or "").strip() for item in (workflow.get("required_first_minute_tasks") or [])}
    compare_family_ids = {str(dict(item).get("id") or "").strip() for item in (compare.get("families") or [])}
    task_coverage = {
        str(key).strip(): [str(item) for item in values]
        for key, values in dict(alignment.get("legacy_form_task_coverage") or {}).items()
    }

    assert len(landmark_rows) == 8
    assert int(alignment.get("legacy_form_landmark_total") or 0) == len(landmark_rows)

    for landmark_id, row in landmark_rows.items():
        landmark = dict(row or {})
        source_path = Path(str(landmark.get("source_path") or ""))
        veteran_task_ids = [str(item) for item in (landmark.get("veteran_task_ids") or [])]
        family_ids = [str(item) for item in (landmark.get("compare_family_ids") or [])]
        required_tokens = [str(item) for item in (landmark.get("required_tokens") or [])]

        assert source_path.exists(), f"{landmark_id}: {source_path}"
        assert source_path.is_relative_to(Path("/docker/chummer5a")), f"{landmark_id}: {source_path}"
        assert veteran_task_ids
        assert set(veteran_task_ids) <= workflow_task_ids
        assert family_ids
        assert set(family_ids) <= compare_family_ids
        assert required_tokens
        source_text = source_path.read_text(encoding="utf-8")
        for token in required_tokens:
            assert token in source_text, f"{landmark_id}: {token}"
        for task_id in veteran_task_ids:
            assert landmark_id in task_coverage.get(task_id, []), f"{task_id}: {landmark_id}"


def test_desktop_non_negotiable_anchors_are_source_backed() -> None:
    baselines = _yaml(ORACLE_BASELINES_PATH)
    anchors = dict(baselines.get("desktop_non_negotiable_anchors") or {})
    assert anchors

    for anchor_id, anchor in anchors.items():
        row = dict(anchor or {})
        source_path = Path(str(row.get("source_path") or ""))
        assert source_path.exists(), f"{anchor_id}: {source_path}"
        source_text = source_path.read_text(encoding="utf-8")

        locators = list(row.get("locators") or [])
        if row.get("locator"):
            locators.append(str(row.get("locator")))
        assert locators, anchor_id
        for locator in locators:
            assert str(locator) in source_text, f"{anchor_id}: {locator}"


def test_veteran_workflow_pack_matches_required_landmarks_and_tasks() -> None:
    workflow = _yaml(WORKFLOW_PACK_PATH)
    gate = _yaml(VETERAN_GATE_PATH)
    baselines = _yaml(ORACLE_BASELINES_PATH)
    compare = _yaml(COMPARE_PACKS_PATH)

    required_landmarks = {str(item).strip() for item in (gate.get("required_landmarks") or []) if str(item).strip()}
    packed_landmarks = {str(item).strip() for item in (workflow.get("required_landmarks") or []) if str(item).strip()}
    assert required_landmarks <= packed_landmarks

    required_tasks = {str(dict(item).get("id") or "").strip() for item in (gate.get("tasks") or [])}
    packed_tasks = {str(dict(item).get("id") or "").strip() for item in (workflow.get("required_first_minute_tasks") or [])}
    assert required_tasks <= packed_tasks
    baseline_ids = {str(dict(item).get("id") or "").strip() for item in (baselines.get("screenshot_baselines") or [])}
    family_ids = {str(dict(item).get("id") or "").strip() for item in (compare.get("families") or [])}

    task_packs = [dict(item) for item in (workflow.get("task_packs") or [])]
    assert {str(item.get("task_id") or "").strip() for item in task_packs} == required_tasks
    legacy_form_landmark_ids = {str(item).strip() for item in dict(baselines.get("legacy_form_landmarks") or {}).keys()}
    workflow_matrix = {
        str(key).strip(): [str(item) for item in (value or {}).get("task_ids", [])]
        for key, value in dict(workflow.get("workflow_compare_matrix") or {}).items()
    }

    for pack in task_packs:
        task_id = str(pack.get("task_id") or "").strip()
        landmarks = [str(item) for item in (pack.get("landmarks") or [])]
        screenshot_ids = [str(item) for item in (pack.get("screenshot_baseline_ids") or [])]
        compare_family_ids = [str(item) for item in (pack.get("compare_family_ids") or [])]
        linked_legacy_landmark_ids = [str(item) for item in (pack.get("legacy_form_landmark_ids") or [])]
        source_path = Path(str(pack.get("oracle_source_path") or ""))
        tokens = [str(item) for item in (pack.get("oracle_tokens") or [])]

        assert set(landmarks) <= required_landmarks
        assert screenshot_ids
        assert set(screenshot_ids) <= baseline_ids
        assert compare_family_ids
        assert set(compare_family_ids) <= family_ids
        if linked_legacy_landmark_ids:
            assert set(linked_legacy_landmark_ids) <= legacy_form_landmark_ids
        assert source_path.exists(), f"{task_id}: {source_path}"
        assert tokens, task_id
        source_text = source_path.read_text(encoding="utf-8")
        for token in tokens:
            assert token in source_text, f"{task_id}: {token}"
        for family_id in compare_family_ids:
            assert task_id in workflow_matrix.get(family_id, []), f"{family_id}: {task_id}"

    legacy_route_packs = [dict(item) for item in (workflow.get("legacy_route_packs") or [])]
    assert {str(item.get("task_id") or "").strip() for item in legacy_route_packs} == {
        "locate_save_import_settings",
        "locate_master_index_and_roster",
    }
    for route_pack in legacy_route_packs:
        task_id = str(route_pack.get("task_id") or "").strip()
        source_path = Path(str(route_pack.get("source_path") or ""))
        required_tokens = [str(item) for item in (route_pack.get("required_tokens") or [])]
        legacy_form_paths = [dict(item) for item in (route_pack.get("legacy_form_paths") or [])]

        assert task_id in required_tasks
        assert source_path.exists(), f"{task_id}: {source_path}"
        source_text = source_path.read_text(encoding="utf-8")
        for token in required_tokens:
            assert token in source_text, f"{task_id}: {token}"
        assert legacy_form_paths, task_id
        for legacy_path_row in legacy_form_paths:
            path = Path(str(legacy_path_row.get("path") or ""))
            tokens = [str(item) for item in (legacy_path_row.get("required_tokens") or [])]
            assert path.exists(), f"{task_id}: {path}"
            legacy_text = path.read_text(encoding="utf-8")
            for token in tokens:
                assert token in legacy_text, f"{task_id}: {path}: {token}"
            matched_landmarks = [
                landmark_id
                for landmark_id, landmark in dict(baselines.get("legacy_form_landmarks") or {}).items()
                if Path(str(dict(landmark).get("source_path") or "")) == path
            ]
            assert matched_landmarks, f"{task_id}: {path}"
            assert set(matched_landmarks) <= legacy_form_landmark_ids


def test_compare_packs_cover_all_flagship_parity_families() -> None:
    compare = _yaml(COMPARE_PACKS_PATH)
    pack = _yaml(PACK_PATH)
    registry = _yaml(FLAGSHIP_PARITY_REGISTRY_PATH)

    compare_families = {str(dict(item).get("id") or "").strip() for item in (compare.get("families") or [])}
    required_families = {str(dict(item).get("id") or "").strip() for item in (registry.get("families") or [])}
    assert required_families <= compare_families

    source_anchor_checks = [dict(item) for item in (compare.get("source_anchor_checks") or [])]
    assert len(source_anchor_checks) == len(required_families)
    anchor_family_ids = {str(item.get("family_id") or "").strip() for item in source_anchor_checks}
    assert len(anchor_family_ids) == len(source_anchor_checks)
    assert anchor_family_ids == required_families
    assert anchor_family_ids <= compare_families

    source_roots = {
        Path("/docker/chummer5a/Chummer.Web/wwwroot/index.html"),
        Path("/docker/chummer5a/docs/PARITY_ORACLE.json"),
        Path("/docker/chummer5a/docs/PARITY_AUDIT.md"),
    }
    manifest_anchor = dict(dict(pack.get("required_outputs") or {}).get("compare_source_anchors") or {})
    assert manifest_anchor.get("path") == str(COMPARE_PACKS_PATH.relative_to(ROOT))
    assert manifest_anchor.get("present") is True
    assert manifest_anchor.get("proof_level") == "source_token_guarded"
    assert {Path(str(item)) for item in (manifest_anchor.get("source_paths") or [])} == source_roots

    for check in source_anchor_checks:
        family_id = str(check.get("family_id") or "").strip()
        source_path = Path(str(check.get("source_path") or ""))
        required_tokens = [str(item) for item in (check.get("required_tokens") or [])]
        assert family_id, check
        assert source_path in source_roots, f"{family_id}: unexpected source root {source_path}"
        assert source_path.is_relative_to(Path("/docker/chummer5a")), f"{family_id}: {source_path}"
        assert source_path.exists(), f"{family_id}: {source_path}"
        assert required_tokens, family_id
        assert len(set(required_tokens)) == len(required_tokens), f"{family_id}: duplicate source tokens"
        source_text = source_path.read_text(encoding="utf-8")
        for token in required_tokens:
            assert token in source_text, f"{family_id}: {source_path}: {token}"
    legacy_form_anchor_checks = [dict(item) for item in (compare.get("legacy_form_anchor_checks") or [])]
    assert len(legacy_form_anchor_checks) == 8
    expected_legacy_anchor_families = {
        "shell_workbench_orientation",
        "settings_and_rules_environment_authoring",
        "sourcebooks_reference_and_master_index",
        "roster_dashboards_and_multi_character_ops",
        "legacy_and_adjacent_import_oracles",
        "custom_data_xml_and_translator_bridge",
        "sheet_export_print_viewer_and_exchange",
    }
    assert {str(item.get("family_id") or "").strip() for item in legacy_form_anchor_checks} == expected_legacy_anchor_families
    for check in legacy_form_anchor_checks:
        family_id = str(check.get("family_id") or "").strip()
        source_path = Path(str(check.get("source_path") or ""))
        required_tokens = [str(item) for item in (check.get("required_tokens") or [])]

        assert family_id in compare_families, family_id
        assert source_path.exists(), f"{family_id}: {source_path}"
        assert source_path.is_relative_to(Path("/docker/chummer5a/Chummer/Forms")), f"{family_id}: {source_path}"
        assert required_tokens, family_id
        source_text = source_path.read_text(encoding="utf-8")
        for token in required_tokens:
            assert token in source_text, f"{family_id}: {source_path}: {token}"
    _assert_compare_family_artifact_packs_reference_real_oracle_fixtures()
    _assert_readme_proof_boundary_matches_live_oracle_and_legacy_form_sources()


def _assert_readme_proof_boundary_matches_live_oracle_and_legacy_form_sources() -> None:
    readme_text = README_PATH.read_text(encoding="utf-8")
    compare = _yaml(COMPARE_PACKS_PATH)
    baselines = _yaml(ORACLE_BASELINES_PATH)
    workflow = _yaml(WORKFLOW_PACK_PATH)

    assert "Compare-pack source anchors must resolve against the live Chummer5a oracle files declared in the package artifacts:" in readme_text
    assert "WinForms-era designer sources" in readme_text
    assert "A family without live web-oracle tokens and, when applicable, the matching legacy-form designer anchors is not a captured veteran baseline." in readme_text

    documented_source_paths = {
        Path("/docker/chummer5a/Chummer.Web/wwwroot/index.html"),
        Path("/docker/chummer5a/docs/PARITY_ORACLE.json"),
        Path("/docker/chummer5a/docs/PARITY_AUDIT.md"),
        Path("/docker/chummer5a/Chummer/Forms/ChummerMainForm.Designer.cs"),
        Path("/docker/chummer5a/Chummer/Forms/Utility Forms/MasterIndex.Designer.cs"),
        Path("/docker/chummer5a/Chummer/Forms/Utility Forms/CharacterRoster.Designer.cs"),
    }
    for path in documented_source_paths:
        assert path.as_posix() in readme_text

    compare_anchor_paths = {
        Path(str(dict(item).get("source_path") or ""))
        for item in (compare.get("source_anchor_checks") or [])
    }
    compare_legacy_paths = {
        Path(str(dict(item).get("source_path") or ""))
        for item in (compare.get("legacy_form_anchor_checks") or [])
    }
    baseline_landmark_paths = {
        Path(str(dict(item).get("source_path") or ""))
        for item in dict(baselines.get("legacy_form_landmarks") or {}).values()
    }
    workflow_source_paths = {
        Path(str(item))
        for item in (dict(workflow.get("source_of_truth") or {}).get("chummer5a_oracle") or [])
    }
    documented_legacy_form_paths = {
        Path("/docker/chummer5a/Chummer/Forms/ChummerMainForm.Designer.cs"),
        Path("/docker/chummer5a/Chummer/Forms/Utility Forms/MasterIndex.Designer.cs"),
        Path("/docker/chummer5a/Chummer/Forms/Utility Forms/CharacterRoster.Designer.cs"),
    }

    assert {
        Path("/docker/chummer5a/Chummer.Web/wwwroot/index.html"),
        Path("/docker/chummer5a/docs/PARITY_ORACLE.json"),
        Path("/docker/chummer5a/docs/PARITY_AUDIT.md"),
    } <= compare_anchor_paths
    assert documented_legacy_form_paths <= workflow_source_paths
    assert documented_legacy_form_paths <= compare_legacy_paths | baseline_landmark_paths


def _assert_compare_family_artifact_packs_reference_real_oracle_fixtures() -> None:
    compare = _yaml(COMPARE_PACKS_PATH)
    baselines = _yaml(ORACLE_BASELINES_PATH)
    workflow = _yaml(WORKFLOW_PACK_PATH)
    fixtures = _yaml(FIXTURE_INVENTORY_PATH)

    family_ids = {str(dict(item).get("id") or "").strip() for item in (compare.get("families") or [])}
    anchor_family_ids = {str(dict(item).get("family_id") or "").strip() for item in (compare.get("source_anchor_checks") or [])}
    baseline_ids = {str(dict(item).get("id") or "").strip() for item in (baselines.get("screenshot_baselines") or [])}
    legacy_form_landmark_ids = {str(item).strip() for item in dict(baselines.get("legacy_form_landmarks") or {}).keys()}
    workflow_task_ids = {str(dict(item).get("task_id") or "").strip() for item in (workflow.get("task_packs") or [])}
    inventory = dict(fixtures.get("inventory") or {})
    oracle_fixture_ids = (
        {str(item) for item in (inventory.get("tab_fixture_ids") or [])}
        | {str(item) for item in (inventory.get("workspace_action_fixture_ids") or [])}
        | {str(item) for item in (inventory.get("desktop_control_fixture_ids") or [])}
    )

    artifact_packs = [dict(item) for item in (compare.get("family_artifact_packs") or [])]
    assert {str(item.get("family_id") or "").strip() for item in artifact_packs} == family_ids

    for artifact_pack in artifact_packs:
        family_id = str(artifact_pack.get("family_id") or "").strip()
        screenshot_ids = [str(item) for item in (artifact_pack.get("baseline_ids") or [])]
        task_ids = [str(item) for item in (artifact_pack.get("workflow_task_ids") or [])]
        fixture_ids = [str(item) for item in (artifact_pack.get("oracle_fixture_ids") or [])]
        source_anchor_family_id = str(artifact_pack.get("source_anchor_family_id") or "").strip()
        legacy_landmark_ids = [str(item) for item in (artifact_pack.get("legacy_form_landmark_ids") or [])]

        assert screenshot_ids, family_id
        assert set(screenshot_ids) <= baseline_ids, family_id
        assert task_ids, family_id
        assert set(task_ids) <= workflow_task_ids, family_id
        assert fixture_ids, family_id
        assert set(fixture_ids) <= oracle_fixture_ids, family_id
        assert source_anchor_family_id == family_id
        assert source_anchor_family_id in anchor_family_ids
        if legacy_landmark_ids:
            assert set(legacy_landmark_ids) <= legacy_form_landmark_ids, family_id


def test_import_export_inventory_counts_match_parity_oracle() -> None:
    fixture_inventory = _yaml(FIXTURE_INVENTORY_PATH)
    baselines = _yaml(ORACLE_BASELINES_PATH)
    parity_oracle = _yaml(PARITY_ORACLE_PATH)
    inventory = dict(fixture_inventory.get("inventory") or {})
    counts = dict(fixture_inventory.get("counts") or {})
    baseline_counts = dict(baselines.get("surface_counts") or {})

    oracle_tabs = [str(item) for item in (parity_oracle.get("tabs") or [])]
    oracle_workspace_actions = [str(item) for item in (parity_oracle.get("workspaceActions") or [])]
    oracle_desktop_controls = [str(item) for item in (parity_oracle.get("desktopControls") or [])]
    inventory_tabs = [str(item) for item in (inventory.get("tab_fixture_ids") or [])]
    inventory_workspace_actions = [str(item) for item in (inventory.get("workspace_action_fixture_ids") or [])]
    inventory_desktop_controls = [str(item) for item in (inventory.get("desktop_control_fixture_ids") or [])]
    baseline_tabs = [str(item) for item in (baselines.get("tab_ids") or [])]

    assert inventory_tabs == oracle_tabs
    assert baseline_tabs == oracle_tabs
    assert inventory_workspace_actions == oracle_workspace_actions
    assert inventory_desktop_controls == oracle_desktop_controls
    assert int(counts.get("tabs") or 0) == int(baseline_counts.get("tabs") or 0) == len(oracle_tabs)
    assert int(counts.get("workspace_actions") or 0) == int(
        baseline_counts.get("workspace_actions") or 0
    ) == len(oracle_workspace_actions)
    assert int(counts.get("desktop_controls") or 0) == int(
        baseline_counts.get("desktop_controls") or 0
    ) == len(oracle_desktop_controls)


def _run_direct() -> int:
    failed = 0
    ran = 0
    for name, func in sorted(globals().items()):
        if not name.startswith("test_") or not callable(func):
            continue
        ran += 1
        try:
            func()
        except Exception as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
            traceback.print_exc()
    print(f"ran={ran} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_direct())
