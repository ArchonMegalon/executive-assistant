from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
from types import ModuleType

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_full_design_mirror_parity.py"


def _load_verifier() -> ModuleType:
    spec = importlib.util.spec_from_file_location("full_design_mirror_parity", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFIER = _load_verifier()


def _write_manifest(
    path: Path,
    *,
    source: Path,
    local_path: str = "mirror/copied.txt",
) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "bindings": [
                    {
                        "key": "fixture",
                        "kind": "file",
                        "local_path": local_path,
                        "source_path": source.as_posix(),
                        "required": True,
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _binding(source: Path, **overrides: object) -> dict[str, object]:
    binding: dict[str, object] = {
        "key": "fixture",
        "kind": "file",
        "local_path": "mirror/copied.txt",
        "source_path": source.as_posix(),
        "required": True,
    }
    binding.update(overrides)
    return binding


def _write_payload(path: Path, payload: object) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


@pytest.mark.parametrize(
    ("field", "first", "second"),
    [
        ("key", "fixture", "fixture-shadow"),
        ("kind", "file", "directory"),
        ("local_path", "mirror/copied.txt", "mirror/shadow.txt"),
    ],
)
def test_manifest_loader_rejects_recursive_duplicate_binding_keys(
    tmp_path: Path,
    field: str,
    first: str,
    second: str,
) -> None:
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        "version: 1\n"
        "bindings:\n"
        "  - key: fixture\n"
        "    kind: file\n"
        "    local_path: mirror/copied.txt\n"
        "    source_path: /tmp/source.txt\n"
        f"    {field}: {first}\n"
        f"    {field}: {second}\n",
        encoding="utf-8",
    )

    with pytest.raises(yaml.constructor.ConstructorError, match="duplicate key"):
        VERIFIER.inspect_manifest(tmp_path, manifest)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (None, "root must be a mapping"),
        ("scalar", "root must be a mapping"),
        ({"version": 1, "bindings": {}}, "nonempty list"),
        ({"version": 1, "bindings": []}, "nonempty list"),
        ({"version": 1, "bindings": ["scalar"]}, "must be a mapping"),
        ({"version": True, "bindings": [{}]}, "version must be the integer 1"),
    ],
)
def test_inspector_rejects_vacuous_or_malformed_manifest_shapes(
    tmp_path: Path,
    payload: object,
    expected: str,
) -> None:
    manifest = tmp_path / "manifest.yaml"
    _write_payload(manifest, payload)

    with pytest.raises(ValueError, match=expected):
        VERIFIER.inspect_manifest(tmp_path, manifest)


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("duplicate_key", "duplicated"),
        ("nonfile", "kind must be exactly file"),
        ("nonbool_required", "required must be a boolean"),
        ("absolute_local", "local_path"),
        ("escaping_local", "local_path"),
        ("relative_source", "source_path"),
    ],
)
def test_inspector_rejects_unsafe_binding_schema_and_paths(
    tmp_path: Path,
    case: str,
    expected: str,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    source = tmp_path / "source.txt"
    source.write_text("canonical\n", encoding="utf-8")
    binding = _binding(source)
    bindings = [binding]
    if case == "duplicate_key":
        bindings.append(_binding(source, local_path="mirror/other.txt"))
    elif case == "nonfile":
        binding["kind"] = "directory"
    elif case == "nonbool_required":
        binding["required"] = 1
    elif case == "absolute_local":
        binding["local_path"] = (tmp_path / "outside.txt").as_posix()
    elif case == "escaping_local":
        binding["local_path"] = "../outside.txt"
    elif case == "relative_source":
        binding["source_path"] = "source.txt"
    manifest = tmp_path / "manifest.yaml"
    _write_payload(manifest, {"version": 1, "bindings": bindings})

    with pytest.raises(ValueError, match=expected):
        VERIFIER.inspect_manifest(root, manifest)


@pytest.mark.parametrize("symlink_side", ["local", "source"])
def test_inspector_rejects_symlink_components_and_out_of_root_aliases(
    tmp_path: Path,
    symlink_side: str,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    source = tmp_path / "source.txt"
    source.write_text("canonical\n", encoding="utf-8")
    binding = _binding(source)
    if symlink_side == "local":
        (root / "mirror").symlink_to(outside, target_is_directory=True)
    else:
        source_link = tmp_path / "source-link.txt"
        source_link.symlink_to(source)
        binding["source_path"] = source_link.as_posix()
    manifest = tmp_path / "manifest.yaml"
    _write_payload(manifest, {"version": 1, "bindings": [binding]})

    with pytest.raises(ValueError, match="symlink component"):
        VERIFIER.inspect_manifest(root, manifest)


@pytest.mark.parametrize("oversized_side", ["local", "source"])
def test_inspector_rejects_files_over_the_generic_hash_bound(
    tmp_path: Path,
    oversized_side: str,
) -> None:
    root = tmp_path / "root"
    local = root / "mirror" / "copied.txt"
    local.parent.mkdir(parents=True)
    source = tmp_path / "source.txt"
    local.write_text("canonical\n", encoding="utf-8")
    source.write_text("canonical\n", encoding="utf-8")
    oversized = local if oversized_side == "local" else source
    with oversized.open("wb") as handle:
        handle.truncate(VERIFIER.MAX_MIRROR_FILE_BYTES + 1)
    manifest = tmp_path / "manifest.yaml"
    _write_manifest(manifest, source=source)

    with pytest.raises(ValueError, match="hash bound"):
        VERIFIER.inspect_manifest(root, manifest)


def test_inspector_accepts_a_strict_valid_manifest(tmp_path: Path) -> None:
    root = tmp_path / "root"
    local = root / "mirror" / "copied.txt"
    local.parent.mkdir(parents=True)
    local.write_text("canonical\n", encoding="utf-8")
    source = tmp_path / "source.txt"
    source.write_text("canonical\n", encoding="utf-8")
    manifest = tmp_path / "manifest.yaml"
    _write_manifest(manifest, source=source)

    rows = VERIFIER.inspect_manifest(root, manifest)

    assert rows[0]["status"] == "ok"
    assert rows[0]["local_sha256"] == rows[0]["source_sha256"]


def test_cli_reports_invalid_manifest_as_json_failure(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    manifest = tmp_path / "manifest.yaml"
    _write_payload(manifest, {"version": 1, "bindings": []})

    result = subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--root",
            str(root),
            "--manifest",
            str(manifest),
            "--json",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["items"] == []
    assert payload["issues"]


@pytest.mark.parametrize(
    "local_path",
    [
        "/tmp/outside.txt",
        "../outside.txt",
        "mirror/../outside.txt",
    ],
)
def test_repair_rejects_absolute_escaping_and_nonnormal_local_paths(
    tmp_path: Path,
    local_path: str,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    source = tmp_path / "source.txt"
    source.write_text("canonical\n", encoding="utf-8")
    manifest = tmp_path / "manifest.yaml"
    _write_manifest(manifest, source=source, local_path=local_path)

    with pytest.raises(ValueError, match="local_path"):
        VERIFIER.repair_manifest(root, manifest)

    assert not (tmp_path / "outside.txt").exists()


@pytest.mark.parametrize("parent_kind", ["symlink", "file"])
def test_repair_rejects_symlink_and_nondirectory_parent_components(
    tmp_path: Path,
    parent_kind: str,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    parent = root / "unsafe-parent"
    if parent_kind == "symlink":
        parent.symlink_to(outside, target_is_directory=True)
    else:
        parent.write_text("not a directory\n", encoding="utf-8")
    source = tmp_path / "source.txt"
    source.write_text("canonical\n", encoding="utf-8")
    manifest = tmp_path / "manifest.yaml"
    _write_manifest(
        manifest,
        source=source,
        local_path="unsafe-parent/copied.txt",
    )

    with pytest.raises(ValueError, match="local_path"):
        VERIFIER.repair_manifest(root, manifest)

    assert not (outside / "copied.txt").exists()


def test_repair_atomically_replaces_destination_symlink_without_following_it(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    destination_parent = root / "mirror"
    destination_parent.mkdir(parents=True)
    source = tmp_path / "source.txt"
    source.write_text("canonical\n", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside sentinel\n", encoding="utf-8")
    destination = destination_parent / "copied.txt"
    destination.symlink_to(outside)
    manifest = tmp_path / "manifest.yaml"
    _write_manifest(manifest, source=source)

    rows = VERIFIER.repair_manifest(root, manifest)

    assert rows[0]["action"] == "copied"
    assert not destination.is_symlink()
    assert destination.read_text(encoding="utf-8") == "canonical\n"
    assert outside.read_text(encoding="utf-8") == "outside sentinel\n"


@pytest.mark.parametrize("source_kind", ["symlink", "directory"])
def test_repair_rejects_symlink_and_nonregular_sources(
    tmp_path: Path,
    source_kind: str,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    backing = tmp_path / "backing.txt"
    backing.write_text("canonical\n", encoding="utf-8")
    source = tmp_path / "source"
    if source_kind == "symlink":
        source.symlink_to(backing)
    else:
        source.mkdir()
    manifest = tmp_path / "manifest.yaml"
    _write_manifest(manifest, source=source)

    with pytest.raises(ValueError, match="source"):
        VERIFIER.repair_manifest(root, manifest)


def test_repair_safely_materializes_a_regular_mirror_file(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    source = tmp_path / "source.txt"
    source.write_text("canonical\n", encoding="utf-8")
    manifest = tmp_path / "manifest.yaml"
    _write_manifest(manifest, source=source, local_path="nested/mirror/copied.txt")

    rows = VERIFIER.repair_manifest(root, manifest)

    destination = root / "nested" / "mirror" / "copied.txt"
    assert rows == [
        {
            "key": "fixture",
            "kind": "file",
            "local_path": destination.as_posix(),
            "source_path": source.as_posix(),
            "required": True,
            "status": "ok",
            "local_sha256": rows[0]["source_sha256"],
            "source_sha256": rows[0]["source_sha256"],
            "action": "copied",
        }
    ]
    assert destination.is_file()
    assert not destination.is_symlink()
    assert destination.read_bytes() == source.read_bytes()
    assert not any(".tmp-" in item.name for item in destination.parent.iterdir())
