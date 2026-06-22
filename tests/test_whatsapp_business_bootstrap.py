from __future__ import annotations

import importlib.util
import sys
from argparse import Namespace
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "bootstrap_whatsapp_business_account.py"


def _module():
    spec = importlib.util.spec_from_file_location("bootstrap_whatsapp_business_account", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _args(**overrides):
    values = {
        "tenant_id": "tenant-default",
        "tenant_name": "Default Tenant",
        "tenant_slug": "default",
        "principal_id": "principal-default",
        "display_name": "Executive Assistant Operator",
        "email": "operator@example.test",
        "business_phone_number": "+15555550100",
        "business_name": "Executive Assistant WhatsApp Business",
        "binding_id": "ea-whatsapp-business",
        "access_token": "",
        "phone_number_id": "",
    }
    values.update(overrides)
    return Namespace(**values)


def test_build_seed_stores_generic_whatsapp_business_number_without_secret() -> None:
    module = _module()

    seed = module.build_seed(_args())

    assert seed.tenant_id == "tenant-default"
    assert seed.principal_id == "principal-default"
    assert seed.email == "operator@example.test"
    assert seed.business_phone_number == "+15555550100"
    assert seed.business_phone_number_digits == "15555550100"
    assert seed.binding_id == "ea-whatsapp-business"
    assert seed.credential_status == "meta_credentials_missing"
    assert seed.scope_json()["scopes"] == ["whatsapp.send"]
    assert seed.auth_metadata_json()["business_phone_number"] == "+15555550100"
    assert "access_token" not in seed.auth_metadata_json()
    assert seed.sanitized_summary()["access_token_present"] is False


def test_build_seed_accepts_meta_credentials_only_as_complete_pair() -> None:
    module = _module()

    seed = module.build_seed(_args(access_token="token", phone_number_id="123456"))

    assert seed.credential_status == "meta_configured"
    assert seed.auth_metadata_json()["access_token"] == "token"
    assert seed.auth_metadata_json()["phone_number_id"] == "123456"
    assert seed.sanitized_summary()["access_token_present"] is True
    assert seed.sanitized_summary()["phone_number_id_present"] is True


def test_build_seed_rejects_access_token_without_meta_phone_number_id() -> None:
    module = _module()

    with pytest.raises(ValueError, match="meta_phone_number_id_required"):
        module.build_seed(_args(access_token="token", phone_number_id=""))
