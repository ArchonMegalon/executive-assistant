#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/docker/EA}"

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
else
  DC=(docker-compose)
fi

python3 -m py_compile \
  "$ROOT/ea/app/retrieval/control_plane.py" \
  "$ROOT/ea/app/llm_gateway/trust_boundary.py" \
  "$ROOT/tests/smoke_v1_15.py"
python3 "$ROOT/tests/smoke_v1_15.py"

"${DC[@]}" exec -T ea-worker python - <<'PY'
from app.retrieval.control_plane import RetrievalControlPlane

cp = RetrievalControlPlane()
so = cp.ingest_pointer_first(
    tenant_key="rag_tenant",
    connector_id="paperless",
    source_uri="paperless://doc/42",
    external_object_id="42",
    file_class="pdf",
    normalized_text="Patient update stable. Follow-up needed in 3 days.",
    metadata={"etag": "v1", "title": "Doc42"},
    principal_id="p1",
)
assert so > 0
rows = cp.retrieve_for_principal(tenant_key="rag_tenant", principal_id="p1", query="follow-up", limit=3)
assert rows and len(rows) >= 1
print("[SMOKE][v1.15][PASS] pointer-first ingest + ACL retrieval")
PY
