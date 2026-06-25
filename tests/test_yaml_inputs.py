from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "ea") not in sys.path:
    sys.path.insert(0, str(ROOT / "ea"))

from app.yaml_inputs import load_yaml_dict


def test_load_yaml_dict_repairs_wrapped_successor_queue_lines(tmp_path) -> None:
    queue_path = tmp_path / "NEXT_90_DAY_QUEUE_STAGING.generated.yaml"
    queue_path.write_text(
        """- title: Prefix row
  package_id: prefix-row
mode: append
items:
- title: Target row
  package_id: target-row
  proof:
    - /tmp/example commit abc tightens src, tests, docs,
    and scripts.
    - /tmp/example commit def fail-closes stale queue
    proof anchors.
""",
        encoding="utf-8",
    )

    payload = load_yaml_dict(queue_path)
    items = [dict(item) for item in (payload.get("items") or [])]

    assert [item["package_id"] for item in items] == ["target-row", "prefix-row"]
    assert items[0]["proof"] == [
        "/tmp/example commit abc tightens src, tests, docs, and scripts.",
        "/tmp/example commit def fail-closes stale queue proof anchors.",
    ]


def test_load_yaml_dict_uses_configured_successor_queue_source_path(
    tmp_path,
    monkeypatch,
) -> None:
    queue_path = tmp_path / "NEXT_90_DAY_QUEUE_STAGING.generated.yaml"
    design_path = tmp_path / "design" / "NEXT_90_DAY_QUEUE_STAGING.generated.yaml"
    queue_path.write_text("mode: append\nitems: []\n", encoding="utf-8")
    monkeypatch.setenv("EA_FLEET_SUCCESSOR_QUEUE_PATH", queue_path.as_posix())
    monkeypatch.setenv("EA_DESIGN_SUCCESSOR_QUEUE_PATH", design_path.as_posix())

    payload = load_yaml_dict(queue_path)

    assert payload["source_design_queue_path"] == design_path.as_posix()
