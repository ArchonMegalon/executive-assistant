from __future__ import annotations

import logging
from types import SimpleNamespace

from scripts import run_proactive_ooda


def test_build_postgres_container_for_script_suppresses_memory_fallback_warning(
    monkeypatch: object,
    caplog,
) -> None:
    root_module = getattr(run_proactive_ooda, "_module", run_proactive_ooda)

    def _fake_build_container():  # type: ignore[no-untyped-def]
        logging.getLogger("ea.container").warning(
            "postgres runtime profile unavailable, switching whole container to memory: fake"
        )
        return SimpleNamespace(runtime_profile=SimpleNamespace(storage_backend="memory"))

    import app.container as app_container

    monkeypatch.setattr(app_container, "build_container", _fake_build_container)
    caplog.set_level(logging.WARNING, logger="ea.container")

    assert root_module._build_postgres_container_for_script() is None  # noqa: SLF001
    assert not [
        record
        for record in caplog.records
        if "postgres runtime profile unavailable, switching whole container to memory" in record.getMessage()
    ]


def test_delivery_status_uses_lightweight_fallback_when_postgres_container_unavailable(monkeypatch: object) -> None:
    root_module = getattr(run_proactive_ooda, "_module", run_proactive_ooda)
    sentinel = {"selected_channel": "telegram", "mode": "lightweight"}
    observed: dict[str, object] = {}

    monkeypatch.setattr(root_module, "_build_postgres_container_for_script", lambda: None)

    def _fake_resolve(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return sentinel

    monkeypatch.setattr(root_module, "resolve_proactive_ooda_delivery_status", _fake_resolve)

    result = root_module._delivery_status("principal-1", digest="digest-1")  # noqa: SLF001

    assert result == sentinel
    assert observed == {"principal_id": "principal-1", "digest": "digest-1"}
