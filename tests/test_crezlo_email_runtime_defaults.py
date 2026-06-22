from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_script(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_crezlo_batch_principal_defaults_to_runtime_principal(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EA_DEFAULT_PRINCIPAL_ID", "workspace-owner")
    module = _load_script(ROOT / "scripts" / "run_crezlo_property_tour_batch.py", "run_crezlo_property_tour_batch_defaults")

    args = module.parse_args(
        [
            "--packets",
            str(tmp_path / "packets.json"),
            "--binding-id",
            "crezlo-binding",
        ]
    )

    assert args.principal_id == "workspace-owner"


def test_emailit_scripts_default_to_generic_sender() -> None:
    tour_email = _load_script(
        ROOT / "scripts" / "send_crezlo_property_tour_results_email.py",
        "send_crezlo_property_tour_results_email_defaults",
    )
    outbox = _load_script(ROOT / "scripts" / "process_emailit_delivery_outbox.py", "process_emailit_delivery_outbox_defaults")

    assert tour_email.DEFAULT_SENDER_EMAIL == "no-reply@example.test"
    assert tour_email.DEFAULT_SENDER_NAME == "Executive Assistant"
    assert outbox.DEFAULT_SENDER_EMAIL == "no-reply@example.test"
    assert outbox.DEFAULT_SENDER_NAME == "Executive Assistant"
