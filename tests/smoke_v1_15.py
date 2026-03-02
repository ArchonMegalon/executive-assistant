from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "ea/schema/20260303_v1_15_rag.sql"
CTRL = ROOT / "ea/app/retrieval/control_plane.py"
TB = ROOT / "ea/app/llm_gateway/trust_boundary.py"

schema = SCHEMA.read_text(encoding="utf-8")
for table in (
    "source_objects",
    "source_permissions",
    "extraction_runs",
    "extracted_documents",
    "retrieval_chunks",
    "retrieval_acl_rules",
    "connector_cursors",
    "retrieval_audit_events",
    "extraction_cache_jobs",
):
    assert f"CREATE TABLE IF NOT EXISTS {table}" in schema
print("[SMOKE][HOST][PASS] v1.15 schema tables present")

for path in (CTRL, TB):
    ast.parse(path.read_text(encoding="utf-8"))
print("[SMOKE][HOST][PASS] v1.15 modules parse")
