from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_unmixr_account_slots.py"


def load_module():
    spec = importlib.util.spec_from_file_location("audit_unmixr_account_slots", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_audit_maps_any_number_of_unmixr_accounts_to_fallback_slots() -> None:
    module = load_module()
    markdown = """
| Service | Account | Discovery | Source | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `Unmixr AI` | `shared@example.test` | `manual_seeded` | `local_env` | 2026-06-22 | seeded in `UNMIXR_API_KEY` |
| `Unmixr AI` | `primary@example.test` | `manual_seeded` | `local_env` | 2026-06-22 | seeded in `UNMIXR_API_KEY_FALLBACK_1` |
| `Unmixr AI` | `narration@example.test` | `manual_seeded` | `local_env` | 2026-06-22 | seeded in `UNMIXR_API_KEY_FALLBACK_2` |
| `Unmixr AI` | `office@example.test` | `manual_seeded` | `local_env` | 2026-06-22 | future slot |
| `Unmixr AI` | `media@example.test` | `manual_seeded` | `local_env` | 2026-06-22 | future slot |
| `Unmixr AI` | `sixth@example.test` | `manual_seeded` | `local_env` | 2026-06-22 | future slot |
"""
    env = """
UNMIXR_API_KEY=secret
UNMIXR_API_KEY_FALLBACK_1=secret
UNMIXR_API_KEY_FALLBACK_2=secret
UNMIXR_API_KEY_FALLBACK_5=secret
"""

    audit = module.build_audit(markdown_text=markdown, env_text=env, runtime_slots=["UNMIXR_API_KEY"])

    assert audit["inventoryAccountCount"] == 6
    assert audit["configuredInventoryAccountCount"] == 4
    assert [row["expectedEnvKey"] for row in audit["missingRuntimeKeys"]] == [
        "UNMIXR_API_KEY_FALLBACK_3",
        "UNMIXR_API_KEY_FALLBACK_4",
    ]
    assert audit["genericSupport"]["futureAccountsRequireCodeChange"] is False
    assert audit["secretsExposed"] is False
    assert audit["extraEnvSlots"] == []


def test_parse_env_slots_supports_list_key_without_exposing_values() -> None:
    module = load_module()

    slots = module.parse_env_slots("UNMIXR_API_KEYS=a,b,c\nUNMIXR_API_KEY_FALLBACK_12=value\n")

    assert slots["UNMIXR_API_KEYS"]["hasValue"] is True
    assert slots["UNMIXR_API_KEYS"]["kind"] == "list"
    assert slots["UNMIXR_API_KEY_FALLBACK_12"]["hasValue"] is True


def test_duplicate_account_aliases_with_distinct_slots_are_counted_separately() -> None:
    module = load_module()
    markdown = """
| Service | Account | Discovery | Source | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `Unmixr AI` | `voice@example.test` | `manual_seeded` | `local_env` | 2026-06-25 | seeded in `UNMIXR_API_KEY_FALLBACK_6` |
| `Unmixr AI` | `voice@example.test` | `manual_seeded` | `local_env` | 2026-06-25 | seeded in `UNMIXR_API_KEY_FALLBACK_7` |
"""
    env = """
UNMIXR_API_KEY_FALLBACK_6=secret
UNMIXR_API_KEY_FALLBACK_7=secret
"""

    audit = module.build_audit(markdown_text=markdown, env_text=env)

    assert audit["inventoryAccountCount"] == 2
    assert audit["configuredInventoryAccountCount"] == 2
    assert [row["expectedEnvKey"] for row in audit["accounts"]] == [
        "UNMIXR_API_KEY_FALLBACK_6",
        "UNMIXR_API_KEY_FALLBACK_7",
    ]
    assert audit["secretsExposed"] is False
