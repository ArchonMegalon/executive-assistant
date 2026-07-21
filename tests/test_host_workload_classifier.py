from __future__ import annotations

import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLASSIFIER = ROOT / ".codex-hardening" / "host-workload-classifier"


def test_codex_fleet_profile_is_responsive_but_bounded() -> None:
    namespace = runpy.run_path(str(CLASSIFIER))
    profile = namespace["CGROUP_PROFILES"]["fleet"]

    assert profile["name"] == "host-codex-fleet-lowprio"
    assert profile["cpu_weight"] == 100
    assert profile["cpu_quota_us"] == 300_000
    assert profile["cpu_period_us"] == 100_000
    assert profile["io_weight"] == 100
    assert profile["write_bps"] == 32 * namespace["MIB"]


def test_codex_processes_are_not_forced_to_idle_priority() -> None:
    text = CLASSIFIER.read_text(encoding="utf-8")
    codex_block = text.split('"codex-fleet-tree"', 1)[1].split('"test-workers"', 1)[0]

    assert "\n            5,\n            2,\n            4,\n            \"fleet\"," in codex_block
    assert "\n            19,\n            3,\n            None,\n            \"fleet\"," not in codex_block
