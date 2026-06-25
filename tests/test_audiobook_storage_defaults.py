from __future__ import annotations

import errno
import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_audiobook_defaults_use_configurable_durable_storage() -> None:
    rendered = "\n".join(
        [
            _source("ea/app/services/audiobook_epub_pipeline.py"),
            _source("ea/scripts/materialize_telegram_audiobook_live_readiness.py"),
            _source("ea/scripts/materialize_whatsapp_audiobook_local_intake_proof.py"),
            _source("ea/scripts/materialize_whatsapp_audiobook_live_voice_selection_shadow.py"),
            _source(".env.example"),
            _source(".env.local.example"),
            _source("docker-compose.yml"),
            _source("docker-compose.whatsapp-web-session.yml"),
        ]
    )

    assert "EA_AUDIOBOOK_DURABLE_STORAGE_ROOT" in rendered
    assert "EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE" in rendered
    assert "DEFAULT_DURABLE_AUDIOBOOK_ROOT" in rendered
    assert "audiobook_jobs_root_must_be_on_durable_storage" in rendered
    assert "audiobookshelf_import_root_must_be_on_durable_storage" in rendered
    assert "data/audiobooks" in rendered
    assert 'Path("/mnt") / "' + "pcloud" + '"' not in rendered
    assert "jobs_root_durable" in rendered
    assert "audiobookshelf_import_root_durable" in rendered
    assert "_require_audiobook_storage_root" in rendered
    assert "_require_" + "pcloud_root" not in rendered
    assert "writable_" + "pcloud" not in rendered
    assert "jobs_root_" + "pcloud" not in rendered
    assert "audiobookshelf_import_root_" + "pcloud" not in rendered
    assert "EA_AUDIOBOOK_ALLOW_NON_" + "PCLOUD_STORAGE" not in rendered


def test_env_templates_do_not_default_to_old_host_storage_roots() -> None:
    rendered = "\n".join(
        [
            _source(".env.example"),
            _source(".env.local.example"),
            _source("docker-compose.yml"),
            _source("docker-compose.whatsapp-web-session.yml"),
        ]
    )

    assert "/mnt/" + "pcloud" not in rendered
    assert "/docker/" + "fleet" not in rendered
    assert "/docker/" + "property" not in rendered
    assert "/docker/" + "chummercomplete" not in rendered


def test_audiobook_paths_can_fall_back_to_host_roots_from_dotenv(monkeypatch) -> None:
    module_path = ROOT / "ea" / "app" / "services" / "audiobook_epub_pipeline.py"
    spec = importlib.util.spec_from_file_location("audiobook_epub_pipeline_storage_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    monkeypatch.delenv("EA_AUDIOBOOK_JOBS_ROOT", raising=False)
    monkeypatch.delenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", raising=False)
    monkeypatch.delenv("EA_AUDIOBOOK_JOBS_HOST_ROOT", raising=False)
    monkeypatch.delenv("EA_AUDIOBOOKSHELF_IMPORT_HOST_ROOT", raising=False)
    monkeypatch.setattr(
        module,
        "_dotenv_values",
        lambda env_files=module.DEFAULT_ENV_FILES: {
            "EA_AUDIOBOOK_JOBS_HOST_ROOT": "/host/audiobook-jobs",
            "EA_AUDIOBOOKSHELF_IMPORT_HOST_ROOT": "/host/audiobookshelf-import",
        },
    )
    monkeypatch.setattr(
        module,
        "_storage_path_accessible",
        lambda path: str(path) in {"/host/audiobook-jobs", "/host/audiobookshelf-import"},
    )

    assert module.audiobook_jobs_root() == Path("/host/audiobook-jobs")
    assert module.audiobookshelf_import_root() == Path("/host/audiobookshelf-import")


def test_audiobook_job_discovery_roots_include_configured_host_root(monkeypatch) -> None:
    module_path = ROOT / "ea" / "app" / "services" / "audiobook_epub_pipeline.py"
    spec = importlib.util.spec_from_file_location("audiobook_epub_pipeline_discovery_roots_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", "/durable/audiobooks/jobs")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_HOST_ROOT", "/host/audiobook-jobs")
    monkeypatch.setenv("EA_AUDIOBOOK_JOB_DISCOVERY_ROOTS", "/alt/audiobook-jobs")
    monkeypatch.setattr(
        module,
        "_storage_path_accessible",
        lambda path: str(path) in {"/durable/audiobooks/jobs", "/host/audiobook-jobs", "/alt/audiobook-jobs"},
    )

    assert module.audiobook_job_discovery_roots() == (
        Path("/alt/audiobook-jobs"),
        Path("/durable/audiobooks/jobs"),
        Path("/host/audiobook-jobs"),
    )


def test_audiobook_jobs_root_falls_back_to_default_when_configured_path_is_inaccessible(monkeypatch) -> None:
    module_path = ROOT / "ea" / "app" / "services" / "audiobook_epub_pipeline.py"
    spec = importlib.util.spec_from_file_location("audiobook_epub_pipeline_storage_fallback_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    inaccessible = Path("/mnt/pcloud/EA/audiobook_jobs")
    durable = Path("/durable/audiobooks/jobs")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(inaccessible))
    monkeypatch.delenv("EA_AUDIOBOOK_JOBS_HOST_ROOT", raising=False)
    monkeypatch.setattr(module, "DEFAULT_JOB_ROOT", durable)
    monkeypatch.setattr(
        module,
        "_storage_path_accessible",
        lambda path: False if Path(path) == inaccessible else True,
    )

    assert module.audiobook_jobs_root() == durable


def test_audiobook_jobs_root_falls_back_to_default_when_configured_path_is_missing(monkeypatch) -> None:
    module_path = ROOT / "ea" / "app" / "services" / "audiobook_epub_pipeline.py"
    spec = importlib.util.spec_from_file_location("audiobook_epub_pipeline_storage_missing_path_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    missing = Path("/mnt/pcloud/EA/audiobook_jobs")
    durable = Path("/durable/audiobooks/jobs")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(missing))
    monkeypatch.delenv("EA_AUDIOBOOK_JOBS_HOST_ROOT", raising=False)
    monkeypatch.setattr(module, "DEFAULT_JOB_ROOT", durable)
    monkeypatch.setattr(module, "_storage_path_accessible", lambda path: False if Path(path) == missing else True)

    assert module.audiobook_jobs_root() == durable


def test_resume_due_audiobook_jobs_returns_job_root_missing_for_disconnected_mount(monkeypatch) -> None:
    module_path = ROOT / "ea" / "app" / "services" / "audiobook_epub_pipeline.py"
    spec = importlib.util.spec_from_file_location("audiobook_epub_pipeline_resume_missing_root_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    broken_root = Path("/mnt/pcloud/EA/audiobook_jobs")
    monkeypatch.setattr(module, "audiobook_jobs_root", lambda: broken_root)
    monkeypatch.setattr(
        module,
        "_storage_path_probe",
        lambda path: {
            "path": str(path),
            "accessible": False if Path(path) == broken_root else True,
            "status": "disconnected_mount" if Path(path) == broken_root else "present",
            "error": "OSError" if Path(path) == broken_root else None,
            "errno": errno.ENOTCONN if Path(path) == broken_root else None,
        },
    )

    summary = module.resume_due_audiobook_jobs(notify_telegram=False)

    assert summary["ran"] is True
    assert summary["attempted"] == 0
    assert summary["errors"] == 0
    assert summary["reason"] == "job_root_missing"
    assert summary["job_root"] == {
        "path": str(broken_root),
        "accessible": False,
        "status": "disconnected_mount",
        "error": "OSError",
        "errno": errno.ENOTCONN,
    }


def test_cleanup_finished_audiobook_jobs_reports_disconnected_job_root(monkeypatch) -> None:
    module_path = ROOT / "ea" / "app" / "services" / "audiobook_epub_pipeline.py"
    spec = importlib.util.spec_from_file_location("audiobook_epub_pipeline_cleanup_missing_root_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    broken_root = Path("/mnt/pcloud/EA/audiobook_jobs")
    monkeypatch.setattr(module, "audiobook_jobs_root", lambda: broken_root)
    monkeypatch.setattr(module, "audiobook_job_discovery_roots", lambda: ())
    monkeypatch.setattr(
        module,
        "_storage_path_probe",
        lambda path: {
            "path": str(path),
            "accessible": False,
            "status": "disconnected_mount",
            "error": "OSError",
            "errno": errno.ENOTCONN,
        },
    )

    summary = module.cleanup_finished_audiobook_jobs()

    assert summary["status"] == "missing"
    assert summary["job_root"] == {
        "path": str(broken_root),
        "accessible": False,
        "status": "disconnected_mount",
        "error": "OSError",
        "errno": errno.ENOTCONN,
    }
