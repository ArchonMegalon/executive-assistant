#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICE_MODULES = (
    "whatsapp_web_session_delivery.py",
    "whatsapp_delivery_router.py",
    "whatsapp_delivery_outbox.py",
    "whatsapp_web_session_readiness.py",
)
API_SERVICE_MODULES = (
    "whatsapp_web_session_delivery.py",
    "whatsapp_delivery_router.py",
)
RUNNER_PATH = "/app/app/runner.py"
CHANNELS_PATH = "/app/app/api/routes/channels.py"
SERVICE_DEST = "/app/app/services"


def _run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _read_container_file(container: str, path: str) -> str:
    proc = _run(["docker", "exec", container, "cat", path])
    if proc.returncode != 0:
        raise RuntimeError(f"container_read_failed:{container}:{path}:{proc.stderr.strip()}")
    return proc.stdout


def _patch_runner_source(source: str) -> str:
    if "from app.services import whatsapp_delivery_outbox" not in source:
        needle = "from app.services import whatsapp_delivery\n"
        if needle not in source:
            raise RuntimeError("runner_whatsapp_delivery_import_not_found")
        source = source.replace(needle, needle + "from app.services import whatsapp_delivery_outbox\n", 1)

    lines = source.splitlines(keepends=True)
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if line.startswith("def _run_scheduler_whatsapp_async_recovery(")
        ),
        -1,
    )
    if start < 0:
        raise RuntimeError("runner_whatsapp_recovery_function_not_found")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("def "):
            end = index
            break

    replacement = [
        "def _run_scheduler_whatsapp_async_recovery(container, log: logging.Logger) -> dict[str, object]:  # type: ignore[no-untyped-def]\n",
        "    try:\n",
        "        return whatsapp_delivery_outbox.drain_whatsapp_delivery_outbox(\n",
        "            container=container,\n",
        "            min_age_seconds=max(_scheduler_whatsapp_async_recovery_min_age_seconds(), 2.0),\n",
        "            max_attempts=_whatsapp_queue_max_attempts(),\n",
        "            retry_backoff_seconds=_whatsapp_queue_retry_backoff_seconds(),\n",
        "        )\n",
        "    except Exception:\n",
        "        log.exception(\"scheduler whatsapp outbox drain failed\")\n",
        "        return {\n",
        "            \"ran\": True,\n",
        "            \"drained\": 0,\n",
        "            \"pending\": 0,\n",
        "            \"skipped\": 0,\n",
        "            \"errors\": 1,\n",
        "            \"dead_lettered\": 0,\n",
        "        }\n",
        "\n",
    ]
    return "".join(lines[:start] + replacement + lines[end:])


def _copy_module(container: str, module_name: str) -> None:
    source = ROOT / "ea" / "app" / "services" / module_name
    if not source.exists():
        raise RuntimeError(f"module_missing:{source}")
    proc = _run(["docker", "cp", str(source), f"{container}:{SERVICE_DEST}/{module_name}"])
    if proc.returncode != 0:
        raise RuntimeError(f"module_copy_failed:{module_name}:{proc.stderr.strip()}")


def _copy_channels(container: str) -> None:
    source = ROOT / "ea" / "app" / "api" / "routes" / "channels.py"
    if not source.exists():
        raise RuntimeError(f"channels_missing:{source}")
    proc = _run(["docker", "cp", str(source), f"{container}:{CHANNELS_PATH}"])
    if proc.returncode != 0:
        raise RuntimeError(f"channels_copy_failed:{proc.stderr.strip()}")


def _copy_runner(container: str, patched_source: str) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(patched_source)
        temp_path = Path(handle.name)
    try:
        os.chmod(temp_path, 0o644)
        proc = _run(["docker", "cp", str(temp_path), f"{container}:{RUNNER_PATH}"])
        if proc.returncode != 0:
            raise RuntimeError(f"runner_copy_failed:{proc.stderr.strip()}")
    finally:
        temp_path.unlink(missing_ok=True)


def _verify_api_container(container: str) -> None:
    code = "\n".join(
        [
            "import py_compile",
            "for path in (",
            "    '/app/app/services/whatsapp_web_session_delivery.py',",
            "    '/app/app/services/whatsapp_delivery_router.py',",
            "    '/app/app/api/routes/channels.py',",
            "):",
            "    py_compile.compile(path, doraise=True)",
            "from pathlib import Path",
            "text = Path('/app/app/api/routes/channels.py').read_text(encoding='utf-8')",
            "assert 'def _whatsapp_send_audiobook_voice_samples(' in text",
            "assert 'whatsapp_delivery_router.send_whatsapp_delivery_text(' in text",
            "assert 'EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET' in text",
            "print('whatsapp_web_api_channels_patch_verified')",
        ]
    )
    proc = _run(["docker", "exec", container, "python", "-c", code])
    if proc.returncode != 0:
        raise RuntimeError(f"api_container_verify_failed:{proc.stderr.strip() or proc.stdout.strip()}")


def _verify_container(container: str) -> None:
    code = "\n".join(
        [
            "import py_compile",
            "for path in (",
            "    '/app/app/services/whatsapp_web_session_delivery.py',",
            "    '/app/app/services/whatsapp_delivery_router.py',",
            "    '/app/app/services/whatsapp_delivery_outbox.py',",
            "    '/app/app/services/whatsapp_web_session_readiness.py',",
            "    '/app/app/runner.py',",
            "):",
            "    py_compile.compile(path, doraise=True)",
            "from app import runner",
            "from app.services import whatsapp_delivery_outbox",
            "print('whatsapp_web_runtime_patch_verified')",
        ]
    )
    proc = _run(["docker", "exec", container, "python", "-c", code])
    if proc.returncode != 0:
        raise RuntimeError(f"container_verify_failed:{proc.stderr.strip() or proc.stdout.strip()}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install the EA WhatsApp Web outbox router into a running EA container.")
    parser.add_argument("--container", default="ea-scheduler")
    parser.add_argument("--api-container", default="ea-api")
    parser.add_argument("--apply", action="store_true", help="Actually copy modules and patch the container runner.")
    parser.add_argument("--patch-api-channels", action="store_true", help="Copy WhatsApp Web delivery modules and channels.py into the API container.")
    parser.add_argument("--restart", action="store_true", help="Restart the patched container after applying.")
    parser.add_argument("--restart-api", action="store_true", help="Restart the API container after applying --patch-api-channels.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    original = _read_container_file(args.container, RUNNER_PATH)
    patched = _patch_runner_source(original)
    changed = patched != original
    print(f"container={args.container}")
    print(f"runner_patch_needed={changed}")
    print(f"modules={','.join(SERVICE_MODULES)}")
    if args.patch_api_channels:
        print(f"api_container={args.api_container}")
        print(f"api_modules={','.join(API_SERVICE_MODULES)}")
        print("api_channels_patch_needed=true")
    if not args.apply:
        print("dry_run=true")
        return 0

    for module in SERVICE_MODULES:
        _copy_module(args.container, module)
    if changed:
        _copy_runner(args.container, patched)
    _verify_container(args.container)
    if args.restart:
        proc = _run(["docker", "restart", args.container])
        if proc.returncode != 0:
            raise RuntimeError(f"container_restart_failed:{proc.stderr.strip()}")
        print(f"restarted={args.container}")
    if args.patch_api_channels:
        for module in API_SERVICE_MODULES:
            _copy_module(args.api_container, module)
        _copy_channels(args.api_container)
        _verify_api_container(args.api_container)
        if args.restart_api:
            proc = _run(["docker", "restart", args.api_container])
            if proc.returncode != 0:
                raise RuntimeError(f"api_container_restart_failed:{proc.stderr.strip()}")
            print(f"restarted={args.api_container}")
    print("dry_run=false")
    print("runtime_patch=installed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
