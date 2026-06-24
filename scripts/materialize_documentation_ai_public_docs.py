#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACKAGE_DIR = ROOT / "docs-public" / "executive-assistant"
DEFAULT_SOURCE_OPENAPI = ROOT / "artifacts" / "openapi_latest.json"
DEFAULT_PUBLIC_OPENAPI = DEFAULT_PACKAGE_DIR / "api-reference" / "openapi.public.json"
DEFAULT_MANIFEST = DEFAULT_PACKAGE_DIR / "PUBLICATION_MANIFEST.json"
PUBLIC_API_BASE_URL = "https://api.executive-assistant.example"

PUBLIC_ENDPOINTS: dict[str, dict[str, dict[str, str]]] = {
    "/v1/register/start": {
        "post": {
            "summary": "Start registration",
            "description": "Create the first short-lived registration challenge for a new Executive Assistant user.",
            "operationId": "startRegistration",
            "tag": "Registration",
        }
    },
    "/v1/register/verify": {
        "post": {
            "summary": "Verify registration",
            "description": "Complete the registration challenge and return the next onboarding step.",
            "operationId": "verifyRegistration",
            "tag": "Registration",
        }
    },
    "/v1/onboarding/start": {
        "post": {
            "summary": "Start onboarding",
            "description": "Create an onboarding session for an authenticated user.",
            "operationId": "startOnboarding",
            "tag": "Onboarding",
        }
    },
    "/v1/onboarding/status": {
        "get": {
            "summary": "Get onboarding status",
            "description": "Read the current onboarding checklist without exposing provider credentials.",
            "operationId": "getOnboardingStatus",
            "tag": "Onboarding",
        }
    },
    "/v1/onboarding/google/start": {
        "post": {
            "summary": "Start Google OAuth",
            "description": "Begin the Gmail and Calendar connection flow through a provider-hosted OAuth redirect.",
            "operationId": "startGoogleOAuth",
            "tag": "Provider Connections",
        }
    },
    "/v1/onboarding/telegram/start": {
        "post": {
            "summary": "Start Telegram setup",
            "description": "Begin Telegram channel setup and return the next safe linking instruction.",
            "operationId": "startTelegramSetup",
            "tag": "Delivery Channels",
        }
    },
    "/v1/onboarding/telegram/link-bot": {
        "post": {
            "summary": "Link Telegram bot",
            "description": "Attach a Telegram bot conversation to the onboarding session after user confirmation.",
            "operationId": "linkTelegramBot",
            "tag": "Delivery Channels",
        }
    },
    "/v1/onboarding/whatsapp/start-business": {
        "post": {
            "summary": "Start WhatsApp Business setup",
            "description": "Create a WhatsApp Business setup step for approved notification delivery.",
            "operationId": "startWhatsAppBusinessSetup",
            "tag": "Delivery Channels",
        }
    },
    "/v1/onboarding/finalize": {
        "post": {
            "summary": "Finalize onboarding",
            "description": "Finish the onboarding checklist once identity, provider, and approval requirements are complete.",
            "operationId": "finalizeOnboarding",
            "tag": "Onboarding",
        }
    },
}


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_source_openapi(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return data


def _assert_allowed_endpoints_exist(source_openapi: dict[str, Any] | None, *, source_path: Path) -> None:
    if source_openapi is None:
        return
    source_paths = source_openapi.get("paths")
    if not isinstance(source_paths, dict):
        raise ValueError(f"{source_path} has no OpenAPI paths object")
    missing: list[str] = []
    for path, methods in PUBLIC_ENDPOINTS.items():
        source_methods = source_paths.get(path)
        if not isinstance(source_methods, dict):
            missing.extend(f"{method.upper()} {path}" for method in methods)
            continue
        for method in methods:
            if method not in source_methods:
                missing.append(f"{method.upper()} {path}")
    if missing:
        joined = ", ".join(sorted(missing))
        raise ValueError(f"public endpoint allowlist is stale; missing from {source_path}: {joined}")


def _operation(method: str, path: str, spec: dict[str, str]) -> dict[str, Any]:
    success_description = "Accepted" if method == "post" else "Current state"
    operation: dict[str, Any] = {
        "tags": [spec["tag"]],
        "summary": spec["summary"],
        "description": spec["description"],
        "operationId": spec["operationId"],
        "responses": {
            "200": {
                "description": success_description,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/PublicResult"}
                    }
                },
            },
            "202": {
                "description": "Queued or waiting for user action",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/PublicResult"}
                    }
                },
            },
            "400": {"description": "Invalid request"},
            "401": {"description": "Authentication required"},
            "429": {"description": "Rate limit exceeded"},
        },
    }
    if method == "post":
        operation["requestBody"] = {
            "required": False,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/PublicRequest"},
                    "examples": {
                        "minimal": {
                            "summary": "Minimal request",
                            "value": {
                                "client_ref": "public-docs-example",
                                "idempotency_key": "replace-with-your-key",
                            },
                        }
                    },
                }
            },
        }
    return operation


def build_public_openapi(*, server_url: str = PUBLIC_API_BASE_URL) -> dict[str, Any]:
    paths: dict[str, Any] = {}
    tags: dict[str, dict[str, str]] = {}
    for path, methods in PUBLIC_ENDPOINTS.items():
        path_item: dict[str, Any] = {}
        for method, spec in methods.items():
            path_item[method] = _operation(method, path, spec)
            tags.setdefault(spec["tag"], {"name": spec["tag"]})
        paths[path] = path_item
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Executive Assistant Public API",
            "version": "public-preview",
            "description": (
                "A deliberately small public API surface for onboarding and channel setup. "
                "Internal action queues, provider repair tools, CodexEA routes, memory, and operator endpoints are not published."
            ),
        },
        "servers": [{"url": server_url.rstrip("/")}],
        "tags": list(tags.values()),
        "paths": paths,
        "components": {
            "securitySchemes": {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT",
                }
            },
            "schemas": {
                "PublicRequest": {
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {
                        "client_ref": {
                            "type": "string",
                            "description": "Caller-owned reference for logs and retries.",
                        },
                        "idempotency_key": {
                            "type": "string",
                            "description": "Unique key used to make retries safe.",
                        },
                    },
                },
                "PublicResult": {
                    "type": "object",
                    "required": ["status"],
                    "additionalProperties": False,
                    "properties": {
                        "status": {
                            "type": "string",
                            "description": "Human-readable result state.",
                        },
                        "next_step": {
                            "type": "string",
                            "description": "Next user action, if the flow needs one.",
                        },
                        "request_id": {
                            "type": "string",
                            "description": "Support reference for this request.",
                        },
                    },
                },
            },
        },
        "security": [{"BearerAuth": []}],
    }


def materialize_public_docs(
    *,
    package_dir: Path = DEFAULT_PACKAGE_DIR,
    source_openapi_path: Path = DEFAULT_SOURCE_OPENAPI,
    server_url: str = PUBLIC_API_BASE_URL,
    require_source: bool = False,
) -> dict[str, Any]:
    source_openapi = _load_source_openapi(source_openapi_path)
    if require_source and source_openapi is None:
        raise FileNotFoundError(f"source OpenAPI snapshot not found: {source_openapi_path}")
    _assert_allowed_endpoints_exist(source_openapi, source_path=source_openapi_path)

    public_openapi_path = package_dir / "api-reference" / "openapi.public.json"
    public_openapi_path.parent.mkdir(parents=True, exist_ok=True)
    public_openapi = build_public_openapi(server_url=server_url)
    public_openapi_path.write_text(json.dumps(public_openapi, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = {
        "contract": "ea.documentation_ai_public_docs.v1",
        "generated_at": _utc_timestamp(),
        "package_dir": str(package_dir.relative_to(ROOT) if package_dir.is_relative_to(ROOT) else package_dir),
        "source_openapi": str(
            source_openapi_path.relative_to(ROOT) if source_openapi_path.is_relative_to(ROOT) else source_openapi_path
        ),
        "source_openapi_present": source_openapi is not None,
        "public_openapi": str(
            public_openapi_path.relative_to(ROOT) if public_openapi_path.is_relative_to(ROOT) else public_openapi_path
        ),
        "published_endpoint_count": sum(len(methods) for methods in PUBLIC_ENDPOINTS.values()),
        "published_paths": sorted(PUBLIC_ENDPOINTS),
        "documentation_ai": {
            "organization": "Executive Assistant",
            "site": "docs.<executive-assistant-domain>",
            "repository_policy": "dedicated public docs repo plus optional sanitized public schema repo only",
            "provider_writeback_allowed": False,
            "private_runtime_context_allowed": False,
        },
    }
    (package_dir / "PUBLICATION_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Materialize the EA Documentation.AI public OpenAPI package.")
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE_DIR)
    parser.add_argument("--source-openapi", type=Path, default=DEFAULT_SOURCE_OPENAPI)
    parser.add_argument("--server-url", default=os.environ.get("EA_PUBLIC_API_BASE_URL", PUBLIC_API_BASE_URL))
    parser.add_argument("--require-source", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    manifest = materialize_public_docs(
        package_dir=args.package_dir,
        source_openapi_path=args.source_openapi,
        server_url=args.server_url,
        require_source=args.require_source,
    )
    print(f"materialized {manifest['public_openapi']}")
    print(f"published endpoints: {manifest['published_endpoint_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
