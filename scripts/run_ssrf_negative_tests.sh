#!/usr/bin/env bash
set -euo pipefail

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
else
  DC=(docker-compose)
fi

"${DC[@]}" exec -T ea-worker python - <<'PY'
from app.net.egress_guard import evaluate_connector_url

cases = [
    ("http://127.0.0.1:8000", False, "localhost blocked"),
    ("http://localhost:8000", False, "localhost name blocked"),
    ("http://169.254.169.254/latest/meta-data", False, "metadata blocked"),
]
for url, expected, label in cases:
    d = evaluate_connector_url(url, network_mode="hosted", allow_private_targets=False)
    assert d.allowed is expected, f"{label}: {url} -> {d}"

ok = evaluate_connector_url("https://example.com/api", network_mode="hosted", allow_private_targets=False)
assert ok.allowed is True, ok
print("[SMOKE][v1.13][PASS] SSRF negatives + safe public URL")
PY
