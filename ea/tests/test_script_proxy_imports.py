from __future__ import annotations

import importlib


def test_local_script_proxies_resolve_from_ea_repo_root() -> None:
    expected = {
        "scripts.source_state_head": "resolve_source_state_head",
        "scripts.run_proactive_ooda": "main",
        "scripts.materialize_proactive_ooda_operator_status": "build_proactive_ooda_operator_status",
        "scripts.materialize_proactive_ooda_gold_acceptance": "materialize_proactive_ooda_gold_acceptance",
        "scripts.verify_proactive_ooda": "main",
        "scripts.verify_proactive_ooda_live_receipt": "verify_receipt",
        "scripts.verify_proactive_ooda_operator_status": "main",
        "scripts.verify_proactive_ooda_gold_acceptance": "verify",
    }
    for module_name, symbol_name in expected.items():
        module = importlib.import_module(module_name)
        symbol = getattr(module, symbol_name, None)
        assert callable(symbol), f"{module_name}:{symbol_name}"


def test_local_scripts_that_depend_on_source_state_head_import_cleanly() -> None:
    expected = {
        "scripts.materialize_office_loop_goal_receipt": "_source_state_fields",
        "scripts.verify_office_loop_goal_receipt": "verify_office_loop_goal_receipt",
    }
    for module_name, symbol_name in expected.items():
        module = importlib.import_module(module_name)
        symbol = getattr(module, symbol_name, None)
        assert callable(symbol), f"{module_name}:{symbol_name}"
