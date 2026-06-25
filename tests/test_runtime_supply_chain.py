from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    path = ROOT / "scripts" / "verify_runtime_supply_chain.py"
    spec = importlib.util.spec_from_file_location("verify_runtime_supply_chain", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_supply_chain_verifier_passes_for_current_tree() -> None:
    module = _load_module()

    result = module.verify()

    assert result["contract_name"] == "ea.runtime_supply_chain.v1"
    assert result["status"] == "pass"
    assert result["issues"] == []
    assert result["checked"]["compose_services"] == [
        "docker-compose.yml:ea-db",
        "docker-compose.yml:ea-redis",
        "docker-compose.host-tools.yml:ea-docker-socket-proxy",
        "docker-compose.fastestvpn.yml:ea-docker-socket-proxy",
        "docker-compose.cloudflared.yml:ea-cloudflared",
    ]
    assert result["checked"]["compose_images"] == {
        "docker-compose.yml:ea-db": "postgres:16-alpine@sha256:16bc17c64a573ef34162af9298258d1aec548232985b33ed7b1eac33ba35c229",
        "docker-compose.yml:ea-redis": "redis:7-alpine@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99",
        "docker-compose.host-tools.yml:ea-docker-socket-proxy": "tecnativa/docker-socket-proxy:0.3.0@sha256:9e4b9e7517a6b660f2cc903a19b257b1852d5b3344794e3ea334ff00ae677ac2",
        "docker-compose.fastestvpn.yml:ea-docker-socket-proxy": "tecnativa/docker-socket-proxy:0.3.0@sha256:9e4b9e7517a6b660f2cc903a19b257b1852d5b3344794e3ea334ff00ae677ac2",
        "docker-compose.cloudflared.yml:ea-cloudflared": "cloudflare/cloudflared:latest@sha256:6d91c121b803126f7a5344005d17a9324788fc09d305b6e2560ec6040a7ae283",
    }


def test_runtime_supply_chain_cli_returns_pass_json() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/verify_runtime_supply_chain.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    body = json.loads(completed.stdout)
    assert body["status"] == "pass"
    assert body["issues"] == []
    assert body["checked"]["compose_services"] == [
        "docker-compose.yml:ea-db",
        "docker-compose.yml:ea-redis",
        "docker-compose.host-tools.yml:ea-docker-socket-proxy",
        "docker-compose.fastestvpn.yml:ea-docker-socket-proxy",
        "docker-compose.cloudflared.yml:ea-cloudflared",
    ]
    assert body["checked"]["compose_images"] == {
        "docker-compose.yml:ea-db": "postgres:16-alpine@sha256:16bc17c64a573ef34162af9298258d1aec548232985b33ed7b1eac33ba35c229",
        "docker-compose.yml:ea-redis": "redis:7-alpine@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99",
        "docker-compose.host-tools.yml:ea-docker-socket-proxy": "tecnativa/docker-socket-proxy:0.3.0@sha256:9e4b9e7517a6b660f2cc903a19b257b1852d5b3344794e3ea334ff00ae677ac2",
        "docker-compose.fastestvpn.yml:ea-docker-socket-proxy": "tecnativa/docker-socket-proxy:0.3.0@sha256:9e4b9e7517a6b660f2cc903a19b257b1852d5b3344794e3ea334ff00ae677ac2",
        "docker-compose.cloudflared.yml:ea-cloudflared": "cloudflare/cloudflared:latest@sha256:6d91c121b803126f7a5344005d17a9324788fc09d305b6e2560ec6040a7ae283",
    }


def test_release_assets_script_requires_runtime_supply_chain_contract() -> None:
    script = (ROOT / "scripts" / "verify_release_assets.sh").read_text(encoding="utf-8")

    assert "Refreshes then validates the EA release bundle" in script
    assert "deploy-context, release-authority," in script
    assert "authoritative live runtime release posture" in script
    assert "runtime supply-chain" in script
    assert "verification still pass" in script
    assert "scripts/verify_runtime_supply_chain.py" in script
    assert "scripts/materialize_runtime_dependency_evidence.py" in script
    assert "scripts/verify_runtime_dependency_evidence.py" in script
    assert '"${PYTHON_BIN}" scripts/verify_runtime_supply_chain.py >/tmp/ea_runtime_supply_chain_verify.out 2>/tmp/ea_runtime_supply_chain_verify.err' in script
    assert "ok: runtime supply-chain gate" in script
    assert "missing: runtime supply-chain gate" in script
