from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sync_onemin_owner_ledger.py"


def test_sync_onemin_owner_ledger_assigns_slots_and_current_hashes(tmp_path: Path) -> None:
    dotenv_path = tmp_path / ".env"
    ledger_path = tmp_path / "onemin_slot_owners.json"
    dotenv_path.write_text(
        "\n".join(
            [
                "ONEMIN_AI_API_KEY=primary-secret",
                "ONEMIN_AI_API_KEY_FALLBACK_2=fallback-secret",
                "",
            ]
        ),
        encoding="utf-8",
    )
    ledger_path.write_text(
        json.dumps(
            {
                "slots": [
                    {"owner_email": "primary@example.com"},
                    {"owner_email": "fallback@example.com"},
                ]
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--dotenv",
            str(dotenv_path),
            "--ledger",
            str(ledger_path),
            "--write",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert payload["hash_algorithm"] == "sha256"
    assert payload["slots"][0]["slot"] == "primary"
    assert payload["slots"][0]["account_name"] == "ONEMIN_AI_API_KEY"
    assert payload["slots"][0]["owner_email"] == "primary@example.com"
    assert payload["slots"][0]["secret_sha256"] == hashlib.sha256(b"primary-secret").hexdigest()
    assert payload["slots"][1]["slot"] == "fallback_2"
    assert payload["slots"][1]["account_name"] == "ONEMIN_AI_API_KEY_FALLBACK_2"
    assert payload["slots"][1]["owner_email"] == "fallback@example.com"
    assert payload["slots"][1]["secret_sha256"] == hashlib.sha256(b"fallback-secret").hexdigest()


def test_sync_onemin_owner_ledger_merges_json_manifest_slots(tmp_path: Path) -> None:
    dotenv_path = tmp_path / ".env"
    ledger_path = tmp_path / "onemin_slot_owners.json"
    manifest_path = tmp_path / "onemin_api_keys.local.json"
    manifest_path.write_text(
        json.dumps(
            [
                {
                    "slot": "fallback_55",
                    "account_name": "ONEMIN_AI_API_KEY_FALLBACK_55",
                    "key": "json-secret-55",
                    "owner_email": "owner55@example.com",
                    "owner_name": "Owner 55",
                },
                {
                    "slot": "fallback_56",
                    "account_name": "ONEMIN_AI_API_KEY_FALLBACK_56",
                    "key": "json-secret-56",
                    "owner_email": "owner56@example.com",
                },
            ]
        ),
        encoding="utf-8",
    )
    dotenv_path.write_text(
        "\n".join(
            [
                "ONEMIN_AI_API_KEY=primary-secret",
                f"ONEMIN_DIRECT_API_KEYS_JSON_FILE={manifest_path}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    ledger_path.write_text(json.dumps({"slots": [{"owner_email": "primary@example.com"}]}), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--dotenv",
            str(dotenv_path),
            "--ledger",
            str(ledger_path),
            "--write",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert [slot["slot"] for slot in payload["slots"]] == ["primary", "fallback_55", "fallback_56"]
    assert payload["slots"][1]["account_name"] == "ONEMIN_AI_API_KEY_FALLBACK_55"
    assert payload["slots"][1]["owner_email"] == "owner55@example.com"
    assert payload["slots"][1]["owner_name"] == "Owner 55"
    assert payload["slots"][1]["secret_sha256"] == hashlib.sha256(b"json-secret-55").hexdigest()
    assert payload["slots"][2]["account_name"] == "ONEMIN_AI_API_KEY_FALLBACK_56"
    assert payload["slots"][2]["owner_email"] == "owner56@example.com"
