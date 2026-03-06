from __future__ import annotations

import os
import uuid

import pytest
import psycopg

from app.domain.models import Artifact
from app.repositories.artifacts_postgres import PostgresArtifactRepository


def test_postgres_artifact_roundtrip_persists_across_repo_reinit(tmp_path) -> None:
    db_url = (os.environ.get("EA_TEST_DATABASE_URL") or "").strip()
    if not db_url:
        pytest.skip("EA_TEST_DATABASE_URL is not set")
    repo = PostgresArtifactRepository(
        database_url=db_url,
        artifacts_dir=str(tmp_path / "artifact_store"),
        tenant_id="test-tenant",
    )
    artifact = Artifact(
        artifact_id=str(uuid.uuid4()),
        kind="rewrite_note",
        content="postgres durable content",
        execution_session_id=str(uuid.uuid4()),
        principal_id="exec-1",
    )
    repo.save(artifact)

    repo2 = PostgresArtifactRepository(
        database_url=db_url,
        artifacts_dir=str(tmp_path / "artifact_store"),
        tenant_id="test-tenant",
    )
    loaded = repo2.get(artifact.artifact_id)
    assert loaded is not None
    assert loaded.artifact_id == artifact.artifact_id
    assert loaded.content == "postgres durable content"
    assert loaded.principal_id == "exec-1"


def test_postgres_artifact_repo_backfills_principal_from_session_intent(tmp_path) -> None:
    db_url = (os.environ.get("EA_TEST_DATABASE_URL") or "").strip()
    if not db_url:
        pytest.skip("EA_TEST_DATABASE_URL is not set")
    session_id = str(uuid.uuid4())
    artifact_id = str(uuid.uuid4())
    artifacts_dir = tmp_path / "artifact_store"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifacts_dir / f"{artifact_id}.txt"
    artifact_path.write_text("backfilled principal content", encoding="utf-8")

    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO execution_sessions (session_id, intent_json, status, created_at, updated_at)
                VALUES (%s, %s::jsonb, 'completed', now(), now())
                ON CONFLICT (session_id) DO NOTHING
                """,
                (session_id, '{"principal_id":"exec-backfill","task_type":"rewrite_text","deliverable_type":"rewrite_note"}'),
            )
            cur.execute(
                """
                INSERT INTO artifacts
                (artifact_id, tenant_id, session_id, principal_id, artifact_type, mime_type, storage_uri, metadata_json, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, now(), now())
                ON CONFLICT (artifact_id) DO UPDATE
                SET session_id = EXCLUDED.session_id,
                    principal_id = EXCLUDED.principal_id,
                    storage_uri = EXCLUDED.storage_uri,
                    metadata_json = EXCLUDED.metadata_json,
                    updated_at = now()
                """,
                (
                    artifact_id,
                    "test-tenant",
                    session_id,
                    "",
                    "rewrite_note",
                    "text/plain",
                    f"file://{artifact_path}",
                    '{"execution_session_id":"' + session_id + '","artifact_kind":"rewrite_note"}',
                ),
            )

    repo = PostgresArtifactRepository(
        database_url=db_url,
        artifacts_dir=str(artifacts_dir),
        tenant_id="test-tenant",
    )
    loaded = repo.get(artifact_id)
    assert loaded is not None
    assert loaded.principal_id == "exec-backfill"
