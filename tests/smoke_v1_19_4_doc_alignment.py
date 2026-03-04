from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
EA_DIR = ROOT / "ea"
for path in (str(ROOT), str(EA_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


def _pass(name: str) -> None:
    print(f"[SMOKE][HOST][PASS] {name}")


def test_readme_runtime_positioning_contract() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "EA OS (Assistant Runtime)" in readme
    assert "capability + skill registries" in readme
    assert "Patched Deployment Bundle" not in readme.splitlines()[0]
    _pass("v1.19.4 readme runtime-positioning contract")


def test_change_guide_claims_have_backing_files() -> None:
    guide = (ROOT / "docs/EA_OS_Change_Guide_for_Dev_v1_19_Future_Intelligence_Care_OS.md").read_text(
        encoding="utf-8"
    )
    required_paths = [
        "ea/app/intelligence/human_compose.py",
        "ea/app/intelligence/source_acquisition.py",
        "ea/app/skills/capability_registry.py",
        "ea/app/skills/registry.py",
        "ea/app/skills/router.py",
        "ea/app/skills/generic.py",
    ]
    for rel in required_paths:
        assert rel in guide
        assert (ROOT / rel).exists(), f"missing file for guide claim: {rel}"
    _pass("v1.19.4 change-guide claim/file alignment")


if __name__ == "__main__":
    test_readme_runtime_positioning_contract()
    test_change_guide_claims_have_backing_files()
