from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_workers_use_shared_cleanup_helper() -> None:
    for path in (
        "scripts/booka_book_worker.py",
        "scripts/avomap_flyover_worker.py",
        "scripts/browseract_template_service_worker.py",
    ):
        source = _source(path)
        assert "cleanup_ui_service_run_dir" in source
        assert "ui_service_worker_cleanup_enabled" in source
        assert '"cleanup"' in source


def test_worker_defaults_cover_generic_ui_cleanup_toggle() -> None:
    rendered = "\n".join(
        _source(path)
        for path in (
            "scripts/ui_service_worker_cleanup.py",
            "scripts/booka_book_worker.py",
            "scripts/avomap_flyover_worker.py",
            "scripts/browseract_template_service_worker.py",
            ".env.example",
        )
    )

    assert "EA_UI_SERVICE_WORKER_CLEANUP_ENABLED" in rendered
