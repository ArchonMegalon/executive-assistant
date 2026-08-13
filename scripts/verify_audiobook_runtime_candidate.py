#!/usr/bin/env python3
"""Read-only verifier for the inert audiobook runtime candidate contract.

This module validates already-rendered Compose JSON.  It never builds, pulls,
starts, stops, recreates, promotes, rolls back, or deploys a service.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
OVERLAY_RELATIVE_PATH = Path(
    "deploy/audiobook-runtime-candidate/docker-compose.candidate.yml"
)
CONTRACT_NAME = "ea.audiobook_runtime_candidate_preflight.v1"
OVERLAY_CONTRACT = "ea.audiobook_runtime_candidate_configuration.v1"
IMAGE_BUILD_RECEIPT_SCHEMA = "ea.audiobook_runtime_image_build.v1"
CANDIDATE_PROJECT = "ea-audiobook-runtime-candidate-configuration"
CANDIDATE_PROFILE = "audiobook-candidate-configuration-only"
COMPOSE_MINIMUM_VERSION = (2, 24, 4)
TARGET_SERVICES = (
    "ea-api",
    "ea-worker",
    "ea-scheduler",
    "ea-whatsapp-web-action-processor",
)
ALL_SERVICES = (
    "ea-api",
    "ea-db",
    "ea-proactive-ooda",
    "ea-redis",
    "ea-responses-proxy",
    "ea-scheduler",
    "ea-teable-relay",
    "ea-telegram-teable-sync",
    "ea-whatsapp-web-action-processor",
    "ea-whatsapp-web-activator",
    "ea-whatsapp-web-session",
    "ea-whatsapp-web-teable-sync",
    "ea-worker",
)
CONTAINER_NAMES = {
    service: "ea-audiobook-candidate-" + service.removeprefix("ea-")
    for service in ALL_SERVICES
}
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_ID_RE = DIGEST_RE
IMAGE_RE = re.compile(r"^[^\s@:/]+(?::[0-9]+)?/[^\s@]+@sha256:[0-9a-f]{64}$")
COMPOSE_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")

SAFE_ENVIRONMENT = {
    "EA_AUDIOBOOK_RUNTIME_CANDIDATE_ONLY": "1",
    "EA_AUDIOBOOK_CANDIDATE_DEPLOYMENT_AUTHORITY": "0",
    "EA_AUDIOBOOK_DURABLE_STORAGE_ROOT": "/data/audiobooks",
    "EA_AUDIOBOOK_JOBS_ROOT": "/data/audiobooks/jobs",
    "EA_AUDIOBOOKSHELF_IMPORT_ROOT": "/data/audiobooks/audiobookshelf",
    "EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED": "1",
    "EA_AUDIOBOOK_UNMIXR_AUTO_RENDER": "1",
    "EA_AUDIOBOOK_UNMIXR_MAX_CHARS_PER_REQUEST": "1800",
    "EA_UNMIXR_SLOT_SELECTOR_ENABLED": "1",
    "EA_AUDIOBOOK_CINEMATIC_SINGLE_PASS": "0",
    "EA_AUDIOBOOK_CINEMATIC_MAX_CHARS_PER_REQUEST": "1800",
    "EA_AUDIOBOOK_PUBLICATION_STT_GATE_REQUIRED": "1",
    "EA_AUDIOBOOK_PUBLICATION_STT_GATE_ENABLED": "1",
    "EA_AUDIOBOOKSHELF_AUTO_IMPORT": "1",
    "EA_AUDIOBOOKSHELF_PUBLIC_SHARE_ENABLED": "1",
    "EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET_FILE": (
        "/run/secrets/whatsapp_audiobook_callback_secret"
    ),
    "PYTHONPATH": "/app",
}
PRESERVED_SERVICE_ENVIRONMENT = {
    "ea-api": {
        "EA_ARTIFACTS_DIR": "/data/artifacts",
        "EA_CODEXEA_AUTHENTICATED_PRINCIPAL_ID": "",
        "EMAILIT_API_KEY": "",
        "EA_EMAILIT_DELIVERY_ENABLED": "0",
        "EA_EMAILIT_OFFICE_DELIVERY_ENABLED": "0",
        "CHUMMER_HUB_EMAILIT_DELIVERY_ENABLED": "0",
        "EA_EMAIL_DEFAULT_FROM": "",
        "EA_EMAIL_DEFAULT_NAME": "",
        "EA_EMAILIT_OFFICE_FROM": "",
        "EA_EMAILIT_OFFICE_NAME": "",
        "EA_GEMINI_VORTEX_CONFIG_DIR": "/run/ea-gemini-cli-config",
        "EA_ONEDRIVE_ATTACHMENT_ROOT": "/data/onedrive_attachments",
        "EA_POCKET_AUDIO_ARCHIVE_ROOT": "/data/pocket-ai-audio",
        "EA_REGISTRATION_EMAIL_FROM": "",
        "EA_REGISTRATION_EMAIL_NAME": "",
        "EA_RESPONSES_PROVIDER_LEDGER_DIR": "/data/provider-ledger",
        "EA_TELEGRAM_SOURCE_VIDEO_EDIT_ROOT": "/data/artifacts/telegram_video_edits",
        "EA_UI_SERVICE_WORKER_OUTPUT_ROOT": "/data/artifacts/browseract_ui_worker_outputs",
    },
    "ea-worker": {
        "EA_ARTIFACTS_DIR": "/data/artifacts",
        "EA_ONEDRIVE_ATTACHMENT_ROOT": "/data/onedrive_attachments",
        "EA_POCKET_AUDIO_ARCHIVE_ROOT": "/data/pocket-ai-audio",
        "EA_RESPONSES_PROVIDER_LEDGER_DIR": "/data/provider-ledger",
    },
    "ea-scheduler": {
        "EA_ARTIFACTS_DIR": "/data/artifacts",
        "EA_ONEDRIVE_ATTACHMENT_ROOT": "/data/onedrive_attachments",
        "EA_POCKET_AUDIO_ARCHIVE_ROOT": "/data/pocket-ai-audio",
        "EA_RESPONSES_PROVIDER_LEDGER_DIR": "/data/provider-ledger",
    },
    "ea-whatsapp-web-action-processor": {
        "EA_RESPONSES_PROVIDER_LEDGER_DIR": "/data/whatsapp-actions",
        "EA_WHATSAPP_WEB_ACTION_STATE_FILE": "/data/whatsapp-actions/processed.json",
    },
}
REQUIRED_NONEMPTY_ENVIRONMENT = (
    "EA_AUDIOBOOKSHELF_API_BASE_URL",
    "EA_AUDIOBOOKSHELF_PUBLIC_BASE_URL",
    "EA_AUDIOBOOKSHELF_API_TOKEN",
    "EA_AUDIOBOOKSHELF_LIBRARY_ID",
    "EA_AUDIOBOOK_PLAYER_ACCESS_BASE_URL",
    "EA_AUDIOBOOK_ACCESS_SIGNING_SECRET",
    "EA_AUDIOBOOK_CANARY_RECEIPT_HMAC_KEY",
    "EA_UNMIXR_PREFERRED_SLOTS",
    "EA_UNMIXR_RESERVE_SLOTS",
)
URL_ENVIRONMENT = (
    "EA_AUDIOBOOKSHELF_API_BASE_URL",
    "EA_AUDIOBOOKSHELF_PUBLIC_BASE_URL",
    "EA_AUDIOBOOK_PLAYER_ACCESS_BASE_URL",
)
SECRET_ENVIRONMENT = (
    "EA_AUDIOBOOKSHELF_API_TOKEN",
    "EA_AUDIOBOOK_ACCESS_SIGNING_SECRET",
    "EA_AUDIOBOOK_CANARY_RECEIPT_HMAC_KEY",
)
COMMON_REQUIRED_BIND_MOUNTS = {
    "/config": {"read_only": True, "kind": "config"},
    "/app/config": {"read_only": True, "kind": "config"},
    "/run/secrets/whatsapp_audiobook_callback_secret": {
        "read_only": True,
        "kind": "secret",
    },
    "/data/audiobooks": {"read_only": False, "kind": "directory"},
    "/data/audiobooks/jobs": {"read_only": False, "kind": "directory"},
    "/data/audiobooks/audiobookshelf": {
        "read_only": False,
        "kind": "directory",
    },
}
SERVICE_REQUIRED_BIND_MOUNTS = {
    "ea-api": {
        **COMMON_REQUIRED_BIND_MOUNTS,
        "/run/ea-gemini-cli-config": {"read_only": True, "kind": "config"},
        "/data/onedrive_attachments": {"read_only": False, "kind": "directory"},
        "/data/pocket-ai-audio": {"read_only": False, "kind": "directory"},
    },
    "ea-worker": {
        **COMMON_REQUIRED_BIND_MOUNTS,
        "/data/onedrive_attachments": {"read_only": False, "kind": "directory"},
        "/data/pocket-ai-audio": {"read_only": False, "kind": "directory"},
    },
    "ea-scheduler": {
        **COMMON_REQUIRED_BIND_MOUNTS,
        "/data/onedrive_attachments": {"read_only": False, "kind": "directory"},
        "/data/pocket-ai-audio": {"read_only": False, "kind": "directory"},
    },
    "ea-whatsapp-web-action-processor": dict(COMMON_REQUIRED_BIND_MOUNTS),
}
SERVICE_REQUIRED_NAMED_VOLUMES = {
    "ea-api": {
        "/data/artifacts": "ea_artifacts",
        "/data/public_property_tours": "ea_public_tours",
        "/data/provider-ledger": "ea_provider_ledger",
        "/data/whatsapp-actions": "ea_whatsapp_web_actions",
    },
    "ea-worker": {
        "/data/artifacts": "ea_artifacts",
        "/data/public_property_tours": "ea_public_tours",
        "/data/provider-ledger": "ea_provider_ledger",
    },
    "ea-scheduler": {
        "/data/artifacts": "ea_artifacts",
        "/data/provider-ledger": "ea_provider_ledger",
    },
    "ea-whatsapp-web-action-processor": {
        "/data/whatsapp-actions": "ea_whatsapp_web_actions",
    },
}
PROCESSOR_SCRIPT = (
    'if [ "$${EA_WHATSAPP_WEB_ACTION_PROCESSOR_ENABLED:-1}" != "1" ]; then\n'
    "  echo '{\"enabled\":false,\"event\":\"whatsapp_web_action_processor_idle\",\"ok\":true}';\n"
    "  while :; do sleep 3600; done;\n"
    "fi\n"
    "if command -v ionice >/dev/null 2>&1; then\n"
    "  lowprio='nice -n 10 ionice -c 3';\n"
    "else\n"
    "  lowprio='nice -n 10';\n"
    "fi\n"
    "while :; do\n"
    "  $${lowprio} python /app/scripts/process_whatsapp_web_session_actions.py || true;\n"
    '  sleep "$${EA_WHATSAPP_WEB_ACTION_POLL_INTERVAL_SECONDS:-30}";\n'
    "done\n"
)
EXPECTED_COMMANDS = {
    "ea-api": ["python", "-m", "app.runner"],
    "ea-worker": ["python", "-m", "app.runner"],
    "ea-scheduler": ["python", "-m", "app.runner"],
    "ea-whatsapp-web-action-processor": ["/bin/sh", "-ec", PROCESSOR_SCRIPT],
}
EXPECTED_DEPENDS_ON = {
    "ea-api": {
        "ea-db": {"condition": "service_healthy", "required": True},
        "ea-redis": {"condition": "service_healthy", "required": True},
        "ea-teable-relay": {"condition": "service_healthy", "required": True},
    },
    "ea-worker": {
        "ea-db": {"condition": "service_healthy", "required": True},
        "ea-teable-relay": {"condition": "service_healthy", "required": True},
    },
    "ea-scheduler": {
        "ea-db": {"condition": "service_healthy", "required": True},
        "ea-teable-relay": {"condition": "service_healthy", "required": True},
    },
    "ea-whatsapp-web-action-processor": {
        "ea-whatsapp-web-session": {
            "condition": "service_started",
            "required": True,
        }
    },
}
EXPECTED_NETWORKS = {
    "ea-api": {"default", "public_ingress"},
    "ea-worker": {"default"},
    "ea-scheduler": {"default"},
    "ea-whatsapp-web-action-processor": {"default"},
}
EXPECTED_EXTRA_HOSTS = ["host.docker.internal=host-gateway"]
EXPECTED_HEALTHCHECK = {
    "test": [
        "CMD-SHELL",
        "python /app/scripts/check_whatsapp_web_action_processor_readiness.py "
        "--probe-sidecar --healthcheck",
    ],
    "timeout": "10s",
    "interval": "2m0s",
    "retries": 5,
}
VOCALLAB_ENVIRONMENT_KEYS = frozenset(
    """
    EA_AUDIOBOOK_TTS_ALLOW_CROSS_PROVIDER_FALLBACK
    EA_AUDIOBOOK_TTS_PROVIDER_ORDER
    EA_AUDIOBOOK_VOCALLAB_ALLOWED_VOICE_CLASSES
    EA_AUDIOBOOK_VOCALLAB_ALLOW_CLONES
    EA_AUDIOBOOK_VOCALLAB_ALLOW_COMMUNITY_VOICES
    EA_AUDIOBOOK_VOCALLAB_ALLOW_TOPUP_POINTS
    EA_AUDIOBOOK_VOCALLAB_AUTO_RENDER
    EA_AUDIOBOOK_VOCALLAB_BASE_URL
    EA_AUDIOBOOK_VOCALLAB_CREDENTIAL_PRODUCTION_ELIGIBLE
    EA_AUDIOBOOK_VOCALLAB_CREDENTIAL_ROTATION_REQUIRED
    EA_AUDIOBOOK_VOCALLAB_DRAFT_MODEL
    EA_AUDIOBOOK_VOCALLAB_ENABLED
    EA_AUDIOBOOK_VOCALLAB_EXPRESSIVE_MODEL
    EA_AUDIOBOOK_VOCALLAB_MAX_AUDIO_BYTES
    EA_AUDIOBOOK_VOCALLAB_MAX_CHARS_PER_REQUEST
    EA_AUDIOBOOK_VOCALLAB_MAX_IN_FLIGHT
    EA_AUDIOBOOK_VOCALLAB_MAX_POINTS_PER_JOB
    EA_AUDIOBOOK_VOCALLAB_MAX_SEGMENTS_PER_RUN
    EA_AUDIOBOOK_VOCALLAB_MIN_REMAINING_POINTS
    EA_AUDIOBOOK_VOCALLAB_MODEL
    EA_AUDIOBOOK_VOCALLAB_OUTPUT_FORMAT
    EA_AUDIOBOOK_VOCALLAB_POLL_INTERVAL_SECONDS
    EA_AUDIOBOOK_VOCALLAB_POLL_TIMEOUT_SECONDS
    EA_AUDIOBOOK_VOCALLAB_REQUESTS_PER_MINUTE
    EA_AUDIOBOOK_VOCALLAB_SAMPLE_RATE
    EA_AUDIOBOOK_VOCALLAB_TIMEOUT_SECONDS
    EA_AUDIOBOOK_VOCALLAB_VOICE_CATALOG_FILE
    VOCALLAB_API_KEY
    VOCALLAB_API_KEY_FILE
    """.split()
)
COMMON_ENVIRONMENT_KEYS = VOCALLAB_ENVIRONMENT_KEYS | frozenset(
    """
    EA_AUDIOBOOKSHELF_API_BASE_URL
    EA_AUDIOBOOKSHELF_API_TOKEN
    EA_AUDIOBOOKSHELF_AUTO_IMPORT
    EA_AUDIOBOOKSHELF_IMPORT_ROOT
    EA_AUDIOBOOKSHELF_LIBRARY_ID
    EA_AUDIOBOOKSHELF_PUBLIC_BASE_URL
    EA_AUDIOBOOKSHELF_PUBLIC_SHARE_DOWNLOADABLE
    EA_AUDIOBOOKSHELF_PUBLIC_SHARE_ENABLED
    EA_AUDIOBOOKSHELF_PUBLIC_SHARE_EXPIRES_DAYS
    EA_AUDIOBOOK_ACCESS_EXPIRES_DAYS
    EA_AUDIOBOOK_ACCESS_SIGNING_SECRET
    EA_AUDIOBOOK_CANARY_RECEIPT_HMAC_KEY
    EA_AUDIOBOOK_CANDIDATE_DEPLOYMENT_AUTHORITY
    EA_AUDIOBOOK_CINEMATIC_MAX_CHARS_PER_REQUEST
    EA_AUDIOBOOK_CINEMATIC_NARRATION
    EA_AUDIOBOOK_CINEMATIC_SINGLE_PASS
    EA_AUDIOBOOK_DURABLE_STORAGE_ROOT
    EA_AUDIOBOOK_EBOOK_CONVERT_BIN
    EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED
    EA_AUDIOBOOK_JOBS_ROOT
    EA_AUDIOBOOK_KINDLE_CONVERT_TIMEOUT_SECONDS
    EA_AUDIOBOOK_PARAGRAPH_PAUSES_ENABLED
    EA_AUDIOBOOK_PARAGRAPH_PAUSE_SECONDS
    EA_AUDIOBOOK_PLAYER_ACCESS_BASE_URL
    EA_AUDIOBOOK_PUBLICATION_STT_COMMAND
    EA_AUDIOBOOK_PUBLICATION_STT_GATE_ENABLED
    EA_AUDIOBOOK_PUBLICATION_STT_GATE_REQUIRED
    EA_AUDIOBOOK_PUBLICATION_STT_MIN_BOOK_TOKEN_OVERLAP
    EA_AUDIOBOOK_PUBLICATION_STT_SAMPLE_COUNT
    EA_AUDIOBOOK_PUBLICATION_STT_SAMPLE_SECONDS
    EA_AUDIOBOOK_RUNTIME_CANDIDATE_IMAGE_DIGEST
    EA_AUDIOBOOK_RUNTIME_CANDIDATE_ONLY
    EA_AUDIOBOOK_RUNTIME_CANDIDATE_REVISION
    EA_AUDIOBOOK_UNMIXR_AUTO_RENDER
    EA_AUDIOBOOK_UNMIXR_MAX_CHARS_PER_REQUEST
    EA_DEPLOY_COMMIT_SHA
    EA_RELEASE_LABEL
    EA_RESPONSES_PROVIDER_LEDGER_DIR
    EA_SOURCE_REVISION
    EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET_FILE
    EA_UNMIXR_PREFERRED_SLOTS
    EA_UNMIXR_RESERVE_SLOTS
    EA_UNMIXR_SLOT_SELECTOR_ENABLED
    PYTHONPATH
    TZ
    """.split()
)
SERVICE_ENVIRONMENT_EXTRAS = {
    "ea-api": frozenset(
        """
        EA_ALLOW_LOOPBACK_NO_AUTH
        EA_ANSWERLY_AUTO_IMPORT_GMAIL_PDFS
        EA_API_TOKEN
        EA_ARTIFACTS_DIR
        EA_ASSISTANT_OWNER_LABEL
        EA_AUDIOBOOK_DEFAULT_VOICE_LABEL
        EA_AUDIOBOOK_DEFAULT_VOICE_LANGUAGE
        EA_AUDIOBOOK_DEFAULT_VOICE_TAGS
        EA_AUDIOBOOKSHELF_IMPORT_HOST_ROOT
        EA_AUDIOBOOKSHELF_TRUST_LIBRARY_FOLDER_PATHS
        EA_AUDIOBOOK_FFMPEG_M4B_FALLBACK
        EA_AUDIOBOOK_M4B_AUTO_MERGE
        EA_AUDIOBOOK_VOICE_AUDITION_MIN_CANDIDATES
        EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED
        EA_AUDIOBOOK_VOICE_DISCOVERY_TARGET_COUNT
        EA_CODEXEA_AUTHENTICATED_PRINCIPAL_ID
        EMAILIT_API_KEY
        EA_EMAILIT_DELIVERY_ENABLED
        EA_EMAILIT_OFFICE_DELIVERY_ENABLED
        CHUMMER_HUB_EMAILIT_DELIVERY_ENABLED
        EA_EMAIL_DEFAULT_FROM
        EA_EMAIL_DEFAULT_NAME
        EA_EMAILIT_OFFICE_FROM
        EA_EMAILIT_OFFICE_NAME
        EA_EMAILIT_MAX_429_RETRY_ATTEMPTS
        EA_ENABLE_LEGACY_RUNTIME_SURFACES
        EA_GEMINI_VORTEX_CONFIG_DIR
        EA_GEMINI_VORTEX_HOME_ROOT
        EA_ONEDRIVE_ATTACHMENT_ROOT
        EA_OUTBOUND_EMAIL_GUARD_STATE_PATH
        EA_POCKET_AUDIO_ARCHIVE_ROOT
        EA_PORT
        EA_REGISTRATION_EMAIL_FROM
        EA_REGISTRATION_EMAIL_NAME
        EA_ROLE
        EA_SCHEDULER_ASYNC_IDLE_LOG_INTERVAL_SECONDS
        EA_SCHEDULER_TELEGRAM_ASYNC_IDLE_INTERVAL_SECONDS
        EA_SCHEDULER_WHATSAPP_ASYNC_IDLE_INTERVAL_SECONDS
        EA_TELEGRAM_AUDIOBOOK_EPUB_ENABLED
        EA_TELEGRAM_SOURCE_VIDEO_EDIT_ROOT
        EA_TRUST_API_TOKEN_PRINCIPAL_HEADER
        EA_UI_SERVICE_SHARED_TEMP_ROOT
        EA_UI_SERVICE_WORKER_OUTPUT_ROOT
        HOME
        TEABLE_BASE_URL
        TEABLE_TABLE_SYNC_CONFIG_JSON
        VOICEWAVE_RUNTIME_TMP_ROOT
        """.split()
    ),
    "ea-worker": frozenset(
        """
        EA_ANSWERLY_AUTO_IMPORT_GMAIL_PDFS
        EA_ARTIFACTS_DIR
        EA_AUDIOBOOK_DEFAULT_VOICE_LABEL
        EA_AUDIOBOOK_DEFAULT_VOICE_LANGUAGE
        EA_AUDIOBOOK_DEFAULT_VOICE_TAGS
        EA_AUDIOBOOKSHELF_IMPORT_HOST_ROOT
        EA_AUDIOBOOKSHELF_TRUST_LIBRARY_FOLDER_PATHS
        EA_AUDIOBOOK_FFMPEG_M4B_FALLBACK
        EA_AUDIOBOOK_M4B_AUTO_MERGE
        EA_AUDIOBOOK_VOICE_AUDITION_MIN_CANDIDATES
        EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED
        EA_AUDIOBOOK_VOICE_DISCOVERY_TARGET_COUNT
        EA_EMAILIT_MAX_429_RETRY_ATTEMPTS
        EA_ONEDRIVE_ATTACHMENT_ROOT
        EA_OUTBOUND_EMAIL_GUARD_STATE_PATH
        EA_POCKET_AUDIO_ARCHIVE_ROOT
        EA_ROLE
        EA_TELEGRAM_AUDIOBOOK_EPUB_ENABLED
        HOME
        TEABLE_BASE_URL
        TEABLE_TABLE_SYNC_CONFIG_JSON
        """.split()
    ),
    "ea-scheduler": frozenset(
        """
        EA_ANSWERLY_AUTO_IMPORT_GMAIL_PDFS
        EA_ARTIFACTS_DIR
        EA_AUDIOBOOK_DEFAULT_VOICE_LABEL
        EA_AUDIOBOOK_DEFAULT_VOICE_LANGUAGE
        EA_AUDIOBOOK_DEFAULT_VOICE_TAGS
        EA_AUDIOBOOKSHELF_IMPORT_HOST_ROOT
        EA_AUDIOBOOKSHELF_TRUST_LIBRARY_FOLDER_PATHS
        EA_AUDIOBOOK_FFMPEG_M4B_FALLBACK
        EA_AUDIOBOOK_M4B_AUTO_MERGE
        EA_AUDIOBOOK_RESUME_ATTEMPT_COOLDOWN_SECONDS
        EA_AUDIOBOOK_RESUME_DUE_LIMIT
        EA_AUDIOBOOK_VOICE_AUDITION_MIN_CANDIDATES
        EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED
        EA_AUDIOBOOK_VOICE_DISCOVERY_TARGET_COUNT
        EA_EMAILIT_MAX_429_RETRY_ATTEMPTS
        EA_ONEDRIVE_ATTACHMENT_ROOT
        EA_OUTBOUND_EMAIL_GUARD_STATE_PATH
        EA_POCKET_AUDIO_ARCHIVE_ROOT
        EA_ROLE
        EA_SCHEDULER_ASYNC_IDLE_LOG_INTERVAL_SECONDS
        EA_SCHEDULER_AUDIOBOOK_RESUME_ENABLED
        EA_SCHEDULER_AUDIOBOOK_RESUME_INTERVAL_SECONDS
        EA_SCHEDULER_TELEGRAM_ASYNC_IDLE_INTERVAL_SECONDS
        EA_SCHEDULER_WHATSAPP_ASYNC_IDLE_INTERVAL_SECONDS
        EA_TELEGRAM_AUDIOBOOK_EPUB_ENABLED
        HOME
        TEABLE_BASE_URL
        TEABLE_TABLE_SYNC_CONFIG_JSON
        """.split()
    ),
    "ea-whatsapp-web-action-processor": frozenset(
        """
        EA_WHATSAPP_AUDIOBOOK_FOLLOWUP_ENABLED
        EA_WHATSAPP_AUDIOBOOK_FOLLOWUP_LIMIT
        EA_WHATSAPP_AUDIOBOOK_RESUME_DUE
        EA_WHATSAPP_AUDIOBOOK_RESUME_DUE_LIMIT
        EA_WHATSAPP_WEB_ACTION_CONVERSATION_FALLBACK_NOOP_COOLDOWN_SECONDS
        EA_WHATSAPP_WEB_ACTION_CONVERSATION_FALLBACK_NOOP_MAX_COOLDOWN_SECONDS
        EA_WHATSAPP_WEB_ACTION_MESSAGE_TAKE
        EA_WHATSAPP_WEB_ACTION_POLL_INTERVAL_SECONDS
        EA_WHATSAPP_WEB_ACTION_PROCESSOR_ENABLED
        EA_WHATSAPP_WEB_ACTION_REPLY_HEYY_AI_KEY
        EA_WHATSAPP_WEB_ACTION_REPLY_HEYY_AI_NAME
        EA_WHATSAPP_WEB_ACTION_REPLY_PRE_REPLY_DELAY_MAX_SECONDS
        EA_WHATSAPP_WEB_ACTION_REPLY_PRE_REPLY_DELAY_MIN_SECONDS
        EA_WHATSAPP_WEB_ACTION_REPLY_QUIET_HOURS_END_HOUR
        EA_WHATSAPP_WEB_ACTION_REPLY_QUIET_HOURS_START_HOUR
        EA_WHATSAPP_WEB_ACTION_REPLY_TYPING_DELAY_MS
        EA_WHATSAPP_WEB_ACTION_REPLY_TYPING_DELAY_MS_PER_CHARACTER
        EA_WHATSAPP_WEB_ACTION_REPLY_TYPING_STATUS_ENABLED
        EA_WHATSAPP_WEB_ACTION_REPLY_USE_SIDECAR_ROUTE_PACING
        EA_WHATSAPP_WEB_ACTION_RETRY_ZERO_SAMPLE_AUDIOBOOK
        EA_WHATSAPP_WEB_ACTION_STATE_FILE
        EA_WHATSAPP_WEB_ACTION_STATE_STALE_SECONDS
        EA_WHATSAPP_WEB_ACTION_ZERO_SAMPLE_RETRY_LIMIT
        EA_WHATSAPP_WEB_DEFAULT_PRINCIPAL_ID
        EA_WHATSAPP_WEB_DEFAULT_SESSION_REF
        EA_WHATSAPP_WEB_SESSION_API_BASE_URL
        EA_WHATSAPP_WEB_SESSION_API_TOKEN
        EA_WHATSAPP_WEB_TG_SUMMARY_BOT_TOKEN
        EA_WHATSAPP_WEB_TG_SUMMARY_CHAT_ID
        EA_WHATSAPP_WEB_TG_SUMMARY_ENABLED
        EA_WHATSAPP_WEB_TG_SUMMARY_EVERY
        EA_WHATSAPP_WEB_TG_SUMMARY_HEYY_AI_KEYS
        EA_WHATSAPP_WEB_TG_SUMMARY_SCOPE_LABEL
        EA_WHATSAPP_WEB_TG_SUMMARY_TIMEOUT_SECONDS
        """.split()
    ),
}
EXPECTED_ENVIRONMENT_KEYS = {
    service: COMMON_ENVIRONMENT_KEYS | SERVICE_ENVIRONMENT_EXTRAS[service]
    for service in TARGET_SERVICES
}
COMMON_TARGET_SERVICE_FIELDS = frozenset(
    """
    cap_drop command container_name cpu_shares cpus depends_on deploy entrypoint
    environment extra_hosts image labels networks profiles pull_policy read_only
    restart security_opt tmpfs user volumes working_dir
    """.split()
)
EXPECTED_TARGET_SERVICE_FIELDS = {
    "ea-api": COMMON_TARGET_SERVICE_FIELDS
    | {"mem_limit", "mem_reservation", "pids_limit"},
    "ea-worker": COMMON_TARGET_SERVICE_FIELDS | {"pids_limit"},
    "ea-scheduler": COMMON_TARGET_SERVICE_FIELDS | {"pids_limit"},
    "ea-whatsapp-web-action-processor": COMMON_TARGET_SERVICE_FIELDS
    | {"healthcheck"},
}
EXPECTED_RESOURCE_LIMITS = {
    "ea-api": {
        "cpu_shares": 512,
        "cpus": 2,
        "mem_limit": "4294967296",
        "mem_reservation": "1073741824",
        "pids_limit": 512,
    },
    "ea-worker": {"cpu_shares": 128, "cpus": 0.75, "pids_limit": 512},
    "ea-scheduler": {"cpu_shares": 128, "cpus": 0.75, "pids_limit": 512},
    "ea-whatsapp-web-action-processor": {"cpu_shares": 32, "cpus": 0.5},
}
EXPECTED_TOP_LEVEL_KEYS = frozenset(
    {
        "name",
        "services",
        "volumes",
        "networks",
        "x-audiobook-candidate-service",
        "x-audiobook-inert-service",
        "x-audiobook-runtime-environment",
        "x-audiobook-runtime-labels",
    }
)
EXPECTED_TOP_VOLUMES = {
    "ea_artifacts": {"name": f"{CANDIDATE_PROJECT}_ea_artifacts"},
    "ea_pgdata": {"name": f"{CANDIDATE_PROJECT}_ea_pgdata"},
    "ea_provider_ledger": {"name": f"{CANDIDATE_PROJECT}_ea_provider_ledger"},
    "ea_public_tours": {
        "external": True,
        "name": "ea_myexternalbrain_public_tours",
    },
    "ea_telegram_teable_sync": {
        "name": f"{CANDIDATE_PROJECT}_ea_telegram_teable_sync"
    },
    "ea_whatsapp_web_actions": {"name": "ea_whatsapp_web_actions"},
    "ea_whatsapp_web_session": {"name": "ea_whatsapp_web_session"},
    "ea_whatsapp_web_teable_sync": {"name": "ea_whatsapp_web_teable_sync"},
}
EXPECTED_TOP_NETWORKS = {
    "default": {"ipam": {}, "name": f"{CANDIDATE_PROJECT}_default"},
    "public_ingress": {
        "ipam": {
            "config": [
                {"gateway": "172.31.254.1", "subnet": "172.31.254.0/29"}
            ]
        },
        "name": "ea_public_ingress",
    },
}
EXPECTED_INERT_EXTENSION = {
    "deploy": {"replicas": 0},
    "profiles": [CANDIDATE_PROFILE],
    "restart": "no",
}
EXPECTED_CANDIDATE_EXTENSION = {
    "cap_drop": ["ALL"],
    "deploy": {"replicas": 0},
    "entrypoint": ["/usr/local/bin/docker-entrypoint.sh"],
    "privileged": False,
    "profiles": [CANDIDATE_PROFILE],
    "read_only": True,
    "restart": "no",
    "security_opt": ["no-new-privileges:true"],
    "tmpfs": ["/tmp", "/run"],
    "user": "10001:10001",
    "working_dir": "/app",
}
REVISION_ENVIRONMENT_KEYS = frozenset(
    {
        "EA_SOURCE_REVISION",
        "EA_DEPLOY_COMMIT_SHA",
        "EA_AUDIOBOOK_RUNTIME_CANDIDATE_REVISION",
        "EA_AUDIOBOOK_RUNTIME_CANDIDATE_IMAGE_DIGEST",
        "EA_RELEASE_LABEL",
    }
)
EXPECTED_SHARED_ENVIRONMENT_KEYS = (
    frozenset(SAFE_ENVIRONMENT)
    | frozenset(REQUIRED_NONEMPTY_ENVIRONMENT)
    | REVISION_ENVIRONMENT_KEYS
)
EXECUTABLE_PATHS = {
    "ea-api": ("/usr/local/bin/docker-entrypoint.sh", "/app/app"),
    "ea-worker": ("/usr/local/bin/docker-entrypoint.sh", "/app/app"),
    "ea-scheduler": ("/usr/local/bin/docker-entrypoint.sh", "/app/app"),
    "ea-whatsapp-web-action-processor": (
        "/usr/local/bin/docker-entrypoint.sh",
        "/bin/sh",
        "/app/scripts/process_whatsapp_web_session_actions.py",
        "/app/scripts/check_whatsapp_web_action_processor_readiness.py",
    ),
}
PROHIBITED_ISOLATION_FIELDS = (
    "pid",
    "ipc",
    "network_mode",
    "uts",
    "userns_mode",
    "cgroup",
    "cgroup_parent",
    "credential_spec",
    "isolation",
    "sysctls",
    "use_api_socket",
)
PROHIBITED_COLLECTION_FIELDS = (
    "configs",
    "secrets",
    "devices",
    "device_cgroup_rules",
    "gpus",
    "group_add",
    "volumes_from",
)
UNRESOLVED_MANDATORY_GATES = (
    "ea_api_live_owner_handoff_or_approved_multi_mode_contract",
    "signed_immutable_candidate_authority",
    "isolated_candidate_execution_and_runtime_proof",
    "credentialed_deployment_and_promotion_authorization",
    "rollback_capture_and_rehearsal",
    "live_health_continuity_and_postdeploy_proof",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _issue(issues: list[str], service: str, subject: str, code: str) -> None:
    issues.append(f"{service}:{subject}:{code}")


def _compose_mapping(
    value: Any,
    *,
    service: str,
    field: str,
    issues: list[str],
) -> dict[str, str]:
    if isinstance(value, dict):
        return {
            str(key): "" if item is None else str(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        result: dict[str, str] = {}
        for item in value:
            if not isinstance(item, str) or "=" not in item:
                _issue(issues, service, field, "invalid_entry")
                continue
            key, item_value = item.split("=", 1)
            if not key or key in result:
                _issue(issues, service, field, "duplicate_or_empty_key")
                continue
            result[key] = item_value
        return result
    _issue(issues, service, field, "not_mapping_or_list")
    return {}


def _string_list(value: Any) -> list[str] | None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return None
    return list(value)


def _is_resolved(value: str) -> bool:
    stripped = str(value or "").strip()
    return bool(stripped) and "${" not in stripped and "\x00" not in stripped


def _is_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and not parsed.username
        and not parsed.password
    )


def _check_directory(path: Path, *, writable: bool) -> str | None:
    if not path.is_absolute():
        return "source_not_absolute"
    try:
        metadata = path.lstat()
    except OSError:
        return "source_missing"
    if stat.S_ISLNK(metadata.st_mode):
        return "source_is_symlink"
    if not stat.S_ISDIR(metadata.st_mode):
        return "source_not_directory"
    if not os.access(path, os.R_OK | os.X_OK):
        return "source_not_readable"
    if writable:
        if not metadata.st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
            return "source_has_no_write_mode"
        if not os.access(path, os.W_OK | os.X_OK):
            return "source_not_writable"
    return None


def _check_secret(path: Path) -> str | None:
    if not path.is_absolute():
        return "source_not_absolute"
    try:
        metadata = path.lstat()
    except OSError:
        return "source_missing"
    if stat.S_ISLNK(metadata.st_mode):
        return "source_is_symlink"
    if not stat.S_ISREG(metadata.st_mode):
        return "source_not_regular_file"
    if metadata.st_nlink != 1:
        return "source_has_multiple_links"
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        return "source_permissions_not_private"
    if metadata.st_size < 1 or metadata.st_size > 16_384:
        return "source_size_out_of_bounds"
    if not os.access(path, os.R_OK):
        return "source_not_readable"
    return None


def _volume_map(
    service_payload: dict[str, Any],
    *,
    service: str,
    issues: list[str],
) -> dict[str, dict[str, Any]]:
    raw_volumes = service_payload.get("volumes")
    if not isinstance(raw_volumes, list):
        _issue(issues, service, "volumes", "not_list")
        return {}
    result: dict[str, dict[str, Any]] = {}
    for entry in raw_volumes:
        if not isinstance(entry, dict):
            _issue(issues, service, "volumes", "not_rendered_long_syntax")
            continue
        target = str(entry.get("target") or "").strip()
        if not target or target in result:
            _issue(issues, service, "volumes", "missing_or_duplicate_target")
            continue
        result[target] = entry
    return result


def _mount_covers_path(target: str, executable_path: str) -> bool:
    normalized = target.rstrip("/") or "/"
    if normalized == "/":
        return executable_path.startswith("/")
    return executable_path == normalized or executable_path.startswith(normalized + "/")


def _check_mounts(
    service_payload: dict[str, Any],
    *,
    service: str,
    issues: list[str],
) -> list[dict[str, Any]]:
    mounts = _volume_map(service_payload, service=service, issues=issues)
    required_binds = SERVICE_REQUIRED_BIND_MOUNTS[service]
    required_volumes = SERVICE_REQUIRED_NAMED_VOLUMES[service]
    expected_targets = set(required_binds) | set(required_volumes)
    actual_targets = set(mounts)
    for target in sorted(actual_targets - expected_targets):
        _issue(issues, service, "volumes", "mount_target_not_allowlisted")
    for target in sorted(actual_targets):
        for executable_path in EXECUTABLE_PATHS[service]:
            if _mount_covers_path(target, executable_path):
                subject = target if target in expected_targets else "volumes"
                _issue(issues, service, subject, "mount_covers_executable_path")
    for target in sorted(expected_targets - actual_targets):
        _issue(issues, service, target, "required_mount_missing")

    sanitized: list[dict[str, Any]] = []
    sources: dict[str, Path] = {}
    for target in sorted(expected_targets & actual_targets):
        entry = mounts[target]
        entry_type = str(entry.get("type") or "")
        read_only = bool(entry.get("read_only", False))
        allowed_keys = {
            "type",
            "source",
            "target",
            "read_only",
            "bind",
            "volume",
            "consistency",
        }
        if set(entry) - allowed_keys:
            _issue(issues, service, target, "mount_option_not_allowlisted")
        if target in required_binds:
            requirement = required_binds[target]
            if entry_type != "bind":
                _issue(issues, service, target, "mount_type_mismatch")
            expected_read_only = bool(requirement["read_only"])
            if read_only != expected_read_only:
                _issue(issues, service, target, "read_only_posture_mismatch")
            bind_options = entry.get("bind")
            if bind_options != {"create_host_path": False}:
                _issue(issues, service, target, "bind_options_mismatch")
            if entry.get("volume") not in (None, {}):
                _issue(issues, service, target, "volume_options_forbidden_for_bind")
            if entry.get("consistency") not in (None, ""):
                _issue(issues, service, target, "consistency_option_forbidden")
            source = Path(str(entry.get("source") or ""))
            sources[target] = source
            source_issue = (
                _check_secret(source)
                if requirement["kind"] == "secret"
                else _check_directory(source, writable=not expected_read_only)
            )
            if source_issue:
                _issue(issues, service, target, source_issue)
            sanitized.append(
                {
                    "target": target,
                    "type": "bind",
                    "read_only": read_only,
                    "host_path_checked": source_issue is None,
                }
            )
        else:
            expected_source = required_volumes[target]
            if entry_type != "volume":
                _issue(issues, service, target, "mount_type_mismatch")
            if str(entry.get("source") or "") != expected_source:
                _issue(issues, service, target, "named_volume_source_mismatch")
            if read_only:
                _issue(issues, service, target, "named_volume_must_be_writable")
            if entry.get("bind") not in (None, {}):
                _issue(issues, service, target, "bind_options_forbidden_for_volume")
            if entry.get("volume") not in (None, {}):
                _issue(issues, service, target, "named_volume_options_mismatch")
            if entry.get("consistency") not in (None, ""):
                _issue(issues, service, target, "consistency_option_forbidden")
            sanitized.append(
                {
                    "target": target,
                    "type": "volume",
                    "source": expected_source,
                    "read_only": read_only,
                }
            )

    config_source = sources.get("/config")
    app_config_source = sources.get("/app/config")
    if config_source is not None and app_config_source is not None:
        try:
            if config_source.resolve(strict=True) != app_config_source.resolve(strict=True):
                _issue(issues, service, "config", "config_mount_sources_disagree")
        except OSError:
            pass
    durable_source = sources.get("/data/audiobooks")
    for target in ("/data/audiobooks/jobs", "/data/audiobooks/audiobookshelf"):
        nested_source = sources.get(target)
        if durable_source is None or nested_source is None:
            continue
        try:
            nested_source.resolve(strict=True).relative_to(durable_source.resolve(strict=True))
        except (OSError, ValueError):
            _issue(issues, service, target, "source_not_within_durable_root")
    return sanitized


def _check_inert_service(
    payload: dict[str, Any], *, service: str, issues: list[str]
) -> dict[str, Any]:
    profiles = _string_list(payload.get("profiles"))
    if profiles != [CANDIDATE_PROFILE]:
        _issue(issues, service, "profiles", "candidate_profile_mismatch")
    deploy = payload.get("deploy")
    replicas = deploy.get("replicas") if isinstance(deploy, dict) else None
    if replicas != 0:
        _issue(issues, service, "deploy.replicas", "must_be_zero")
    if isinstance(deploy, dict):
        for key, value in deploy.items():
            if key == "replicas":
                continue
            if value not in (None, {}, []):
                _issue(issues, service, "deploy", "nonempty_option_forbidden")
    else:
        _issue(issues, service, "deploy", "not_mapping")
    if str(payload.get("restart") or "no") != "no":
        _issue(issues, service, "restart", "must_be_no")
    if payload.get("scale") not in (None, 0):
        _issue(issues, service, "scale", "must_be_zero_or_absent")
    expected_container_name = CONTAINER_NAMES[service]
    if str(payload.get("container_name") or "") != expected_container_name:
        _issue(issues, service, "container_name", "candidate_name_mismatch")
    profiles_match = profiles == [CANDIDATE_PROFILE]
    replicas_match = replicas == 0
    restart_matches = str(payload.get("restart") or "no") == "no"
    return {
        "profile": CANDIDATE_PROFILE if profiles_match else "mismatch",
        "replicas": 0 if replicas_match else "mismatch",
        "restart": "no" if restart_matches else "mismatch",
        "container_name": (
            expected_container_name
            if str(payload.get("container_name") or "") == expected_container_name
            else "mismatch"
        ),
    }


def _check_target_security(
    payload: dict[str, Any], *, service: str, issues: list[str]
) -> dict[str, Any]:
    expected_entrypoint = ["/usr/local/bin/docker-entrypoint.sh"]
    entrypoint = _string_list(payload.get("entrypoint"))
    command = _string_list(payload.get("command"))
    if entrypoint != expected_entrypoint:
        _issue(issues, service, "entrypoint", "exact_value_mismatch")
    if command != EXPECTED_COMMANDS[service]:
        _issue(issues, service, "command", "exact_value_mismatch")
    if str(payload.get("working_dir") or "") != "/app":
        _issue(issues, service, "working_dir", "exact_value_mismatch")
    if str(payload.get("user") or "") != "10001:10001":
        _issue(issues, service, "user", "exact_value_mismatch")
    if bool(payload.get("privileged", False)):
        _issue(issues, service, "privileged", "must_be_false")
    cap_add = _string_list(payload.get("cap_add", []))
    cap_drop = _string_list(payload.get("cap_drop"))
    if cap_add != []:
        _issue(issues, service, "cap_add", "must_be_empty")
    if cap_drop != ["ALL"]:
        _issue(issues, service, "cap_drop", "must_drop_all")
    if payload.get("read_only") is not True:
        _issue(issues, service, "read_only", "must_be_true")
    security_opt = _string_list(payload.get("security_opt"))
    if security_opt != ["no-new-privileges:true"]:
        _issue(issues, service, "security_opt", "exact_value_mismatch")
    tmpfs = _string_list(payload.get("tmpfs"))
    if tmpfs != ["/tmp", "/run"]:
        _issue(issues, service, "tmpfs", "exact_value_mismatch")
    for field in PROHIBITED_ISOLATION_FIELDS:
        if payload.get(field) not in (None, "", False, {}, []):
            _issue(issues, service, field, "forbidden_isolation_override")
    for field in PROHIBITED_COLLECTION_FIELDS:
        if payload.get(field) not in (None, {}, []):
            _issue(issues, service, field, "must_be_empty")
    ports = payload.get("ports", [])
    if ports not in (None, []):
        _issue(issues, service, "ports", "must_be_empty")
    networks_value = payload.get("networks")
    if isinstance(networks_value, dict):
        networks = set(str(key) for key in networks_value)
    elif isinstance(networks_value, list):
        networks = set(str(item) for item in networks_value)
    else:
        networks = set()
        _issue(issues, service, "networks", "not_mapping_or_list")
    if networks != EXPECTED_NETWORKS[service]:
        _issue(issues, service, "networks", "exact_allowlist_mismatch")
    extra_hosts = _string_list(payload.get("extra_hosts"))
    if extra_hosts != EXPECTED_EXTRA_HOSTS:
        _issue(issues, service, "extra_hosts", "exact_allowlist_mismatch")
    if payload.get("depends_on") != EXPECTED_DEPENDS_ON[service]:
        _issue(issues, service, "depends_on", "exact_value_mismatch")
    healthcheck = payload.get("healthcheck")
    if service == "ea-whatsapp-web-action-processor":
        if healthcheck != EXPECTED_HEALTHCHECK:
            _issue(issues, service, "healthcheck", "exact_value_mismatch")
    elif healthcheck not in (None, {}):
        _issue(issues, service, "healthcheck", "must_be_absent")
    expected_healthcheck = (
        EXPECTED_HEALTHCHECK
        if service == "ea-whatsapp-web-action-processor"
        else None
    )
    return {
        "entrypoint_matches": entrypoint == expected_entrypoint,
        "command_matches": command == EXPECTED_COMMANDS[service],
        "working_dir_matches": str(payload.get("working_dir") or "") == "/app",
        "user_matches": str(payload.get("user") or "") == "10001:10001",
        "privileged_false": not bool(payload.get("privileged", False)),
        "cap_add_empty": cap_add == [],
        "cap_drop_all": cap_drop == ["ALL"],
        "root_filesystem_read_only": payload.get("read_only") is True,
        "no_new_privileges": security_opt == ["no-new-privileges:true"],
        "tmpfs_matches": tmpfs == ["/tmp", "/run"],
        "namespace_overrides_absent": all(
            payload.get(field) in (None, "", False, {}, [])
            for field in PROHIBITED_ISOLATION_FIELDS
        ),
        "runtime_attachments_absent": all(
            payload.get(field) in (None, {}, [])
            for field in PROHIBITED_COLLECTION_FIELDS
        ),
        "networks_match": networks == EXPECTED_NETWORKS[service],
        "extra_hosts_match": extra_hosts == EXPECTED_EXTRA_HOSTS,
        "ports_absent": ports in (None, []),
        "depends_on_matches": payload.get("depends_on") == EXPECTED_DEPENDS_ON[service],
        "healthcheck_matches": healthcheck == expected_healthcheck,
    }


def _parse_compose_version(value: str) -> tuple[int, int, int] | None:
    match = COMPOSE_VERSION_RE.fullmatch(str(value or "").strip())
    if not match:
        return None
    return tuple(int(item) for item in match.groups())


def _validate_image_inspection(
    inspection: dict[str, Any] | None,
    *,
    expected_image: str,
    expected_revision: str,
) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    if not isinstance(inspection, dict):
        return {
            "performed": False,
            "validated": False,
            "image_id": "",
            "exact_repo_digest_present": False,
            "oci_revision_matches": False,
            "source_revision_environment_matches": False,
        }, ["evidence:local_image_inspection:missing"]
    image_id = str(inspection.get("Id") or "")
    repo_digests = inspection.get("RepoDigests")
    config = inspection.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    environment = config.get("Env") if isinstance(config, dict) else None
    if not IMAGE_ID_RE.fullmatch(image_id):
        issues.append("evidence:local_image_inspection:image_id_invalid")
    exact_digest = isinstance(repo_digests, list) and expected_image in repo_digests
    if not exact_digest:
        issues.append("evidence:local_image_inspection:repo_digest_mismatch")
    revision_matches = (
        isinstance(labels, dict)
        and str(labels.get("org.opencontainers.image.revision") or "")
        == expected_revision
    )
    if not revision_matches:
        issues.append("evidence:local_image_inspection:oci_revision_mismatch")
    source_revisions: list[str] = []
    if isinstance(environment, list):
        for entry in environment:
            if isinstance(entry, str) and entry.startswith("EA_SOURCE_REVISION="):
                source_revisions.append(entry.split("=", 1)[1])
    source_matches = source_revisions == [expected_revision]
    if not source_matches:
        issues.append("evidence:local_image_inspection:source_revision_mismatch")
    return {
        "performed": True,
        "validated": not issues,
        "image_id": image_id if IMAGE_ID_RE.fullmatch(image_id) else "",
        "exact_repo_digest_present": exact_digest,
        "oci_revision_matches": revision_matches,
        "source_revision_environment_matches": source_matches,
    }, issues


def _validate_supporting_provenance(
    provenance: dict[str, Any] | None,
    *,
    provenance_sha256: str,
    expected_revision: str,
    expected_image_id: str,
) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(provenance, dict):
        return {
            "provided": False,
            "validated": False,
            "authority_eligible": False,
            "sha256": "",
            "schema": "",
        }, ["evidence:supporting_build_provenance:missing"]
    issues: list[str] = []
    schema = str(provenance.get("schema") or "")
    if schema != IMAGE_BUILD_RECEIPT_SCHEMA:
        issues.append("evidence:supporting_build_provenance:schema_mismatch")
    if provenance.get("status") != "pass":
        issues.append("evidence:supporting_build_provenance:status_not_pass")
    for field in ("commit", "revision_label", "runtime_source_revision"):
        if str(provenance.get(field) or "") != expected_revision:
            issues.append(f"evidence:supporting_build_provenance:{field}_mismatch")
    if not expected_image_id or str(provenance.get("image_id") or "") != expected_image_id:
        issues.append("evidence:supporting_build_provenance:image_id_mismatch")
    required_false = (
        "dirty_worktree_context_used",
        "runtime_secrets_baked_in",
        "customer_data_baked_in",
        "private_archive_baked_in",
        "global_build_cache_pruned",
        "live_or_rollback_images_pruned",
    )
    for field in required_false:
        if provenance.get(field) is not False:
            issues.append(f"evidence:supporting_build_provenance:{field}_not_false")
    if not DIGEST_RE.fullmatch(provenance_sha256):
        issues.append("evidence:supporting_build_provenance:digest_invalid")
    return {
        "provided": True,
        "validated": not issues,
        # The build receipt is private and atomic but is neither a generic
        # audiobook candidate authority nor a signed immutable release statement.
        "authority_eligible": False,
        "sha256": provenance_sha256 if DIGEST_RE.fullmatch(provenance_sha256) else "",
        "schema": schema if schema == IMAGE_BUILD_RECEIPT_SCHEMA else "unrecognized",
    }, issues


def _canonical_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _sanitized_render_projection(compose_payload: dict[str, Any]) -> dict[str, Any]:
    """Build a full-render digest preimage without machine-local mount paths.

    Environment values stay in this in-memory preimage so the final digest binds
    every rendered value, including secrets. The projection itself is never
    returned or written.
    """

    projected = dict(compose_payload)
    services_value = compose_payload.get("services")
    projected_services: dict[str, Any] = {}
    if isinstance(services_value, dict):
        for service, raw_payload in services_value.items():
            if not isinstance(raw_payload, dict):
                projected_services[str(service)] = raw_payload
                continue
            service_payload = dict(raw_payload)
            raw_volumes = raw_payload.get("volumes")
            if isinstance(raw_volumes, list):
                projected_volumes: list[Any] = []
                for raw_mount in raw_volumes:
                    if not isinstance(raw_mount, dict):
                        projected_volumes.append(raw_mount)
                        continue
                    mount = dict(raw_mount)
                    if str(mount.get("type") or "") == "bind":
                        source = str(mount.get("source") or "")
                        mount["source"] = (
                            "sha256:" + hashlib.sha256(source.encode("utf-8")).hexdigest()
                        )
                    projected_volumes.append(mount)
                service_payload["volumes"] = projected_volumes
            raw_build = raw_payload.get("build")
            if isinstance(raw_build, dict):
                build = dict(raw_build)
                if "context" in build:
                    context = str(build.get("context") or "")
                    build["context"] = (
                        "sha256:" + hashlib.sha256(context.encode("utf-8")).hexdigest()
                    )
                service_payload["build"] = build
            elif isinstance(raw_build, str):
                service_payload["build"] = (
                    "sha256:" + hashlib.sha256(raw_build.encode("utf-8")).hexdigest()
                )
            projected_services[str(service)] = service_payload
    projected["services"] = projected_services
    return projected


def _check_top_level_contract(
    compose_payload: dict[str, Any],
    *,
    expected_revision: str,
    image_digest: str,
    issues: list[str],
) -> tuple[dict[str, Any], dict[str, str]]:
    top_keyset_matches = set(compose_payload) == EXPECTED_TOP_LEVEL_KEYS
    if not top_keyset_matches:
        issues.append("compose:top_level:exact_keyset_mismatch")
    volumes_match = compose_payload.get("volumes") == EXPECTED_TOP_VOLUMES
    if not volumes_match:
        issues.append("compose:volumes:exact_definition_mismatch")
    networks_match = compose_payload.get("networks") == EXPECTED_TOP_NETWORKS
    if not networks_match:
        issues.append("compose:networks:exact_definition_mismatch")
    inert_extension_matches = (
        compose_payload.get("x-audiobook-inert-service")
        == EXPECTED_INERT_EXTENSION
    )
    if not inert_extension_matches:
        issues.append("compose:x_inert_service:exact_definition_mismatch")
    candidate_extension_matches = (
        compose_payload.get("x-audiobook-candidate-service")
        == EXPECTED_CANDIDATE_EXTENSION
    )
    if not candidate_extension_matches:
        issues.append("compose:x_candidate_service:exact_definition_mismatch")

    extension_environment = _compose_mapping(
        compose_payload.get("x-audiobook-runtime-environment"),
        service="compose",
        field="x_runtime_environment",
        issues=issues,
    )
    environment_keyset_matches = (
        set(extension_environment) == EXPECTED_SHARED_ENVIRONMENT_KEYS
    )
    if not environment_keyset_matches:
        issues.append("compose:x_runtime_environment:exact_keyset_mismatch")
    revision_environment = {
        "EA_SOURCE_REVISION": expected_revision,
        "EA_DEPLOY_COMMIT_SHA": expected_revision,
        "EA_AUDIOBOOK_RUNTIME_CANDIDATE_REVISION": expected_revision,
        "EA_AUDIOBOOK_RUNTIME_CANDIDATE_IMAGE_DIGEST": image_digest,
        "EA_RELEASE_LABEL": f"audiobook-candidate-{expected_revision}",
    }
    fixed_shared_environment = {**SAFE_ENVIRONMENT, **revision_environment}
    fixed_environment_matches = True
    for key, expected_value in fixed_shared_environment.items():
        if extension_environment.get(key) != expected_value:
            fixed_environment_matches = False
            _issue(issues, "compose", "x_runtime_environment", "fixed_value_mismatch")
    required_environment_valid = True
    for key in REQUIRED_NONEMPTY_ENVIRONMENT:
        if not _is_resolved(extension_environment.get(key, "")):
            required_environment_valid = False
            _issue(issues, "compose", "x_runtime_environment", "required_value_invalid")
    for key in URL_ENVIRONMENT:
        value = extension_environment.get(key, "")
        if _is_resolved(value) and not _is_http_url(value):
            required_environment_valid = False
            _issue(issues, "compose", "x_runtime_environment", "url_value_invalid")
    for key in SECRET_ENVIRONMENT:
        value = extension_environment.get(key, "")
        if _is_resolved(value) and len(value.encode("utf-8")) < 16:
            required_environment_valid = False
            _issue(issues, "compose", "x_runtime_environment", "secret_value_invalid")

    expected_common_labels = {
        "org.opencontainers.image.revision": expected_revision,
        "com.archonmegalon.ea.audiobook-runtime.contract": OVERLAY_CONTRACT,
        "com.archonmegalon.ea.audiobook-runtime.source-revision": expected_revision,
        "com.archonmegalon.ea.audiobook-runtime.image-digest": image_digest,
        "com.archonmegalon.ea.audiobook-runtime.deployment-authority": "denied",
    }
    extension_labels = _compose_mapping(
        compose_payload.get("x-audiobook-runtime-labels"),
        service="compose",
        field="x_runtime_labels",
        issues=issues,
    )
    labels_match = extension_labels == expected_common_labels
    if not labels_match:
        issues.append("compose:x_runtime_labels:exact_definition_mismatch")
    return {
        "top_level_keyset_exact": top_keyset_matches,
        "volume_definitions_exact": volumes_match,
        "network_definitions_exact": networks_match,
        "inert_extension_exact": inert_extension_matches,
        "candidate_extension_exact": candidate_extension_matches,
        "runtime_environment_keyset_exact": environment_keyset_matches,
        "runtime_environment_fixed_values_exact": fixed_environment_matches,
        "runtime_environment_required_values_valid": required_environment_valid,
        "runtime_labels_exact": labels_match,
    }, extension_environment


def _check_target_exact_shape(
    payload: dict[str, Any], *, service: str, issues: list[str]
) -> dict[str, bool]:
    field_set_matches = set(payload) == EXPECTED_TARGET_SERVICE_FIELDS[service]
    if not field_set_matches:
        _issue(issues, service, "fields", "exact_allowlist_mismatch")
    resource_limits_match = all(
        payload.get(field) == expected
        for field, expected in EXPECTED_RESOURCE_LIMITS[service].items()
    )
    if not resource_limits_match:
        _issue(issues, service, "resource_limits", "exact_value_mismatch")
    return {
        "service_field_allowlist_exact": field_set_matches,
        "resource_limits_exact": resource_limits_match,
    }


def verify_audiobook_runtime_candidate(
    compose_payload: dict[str, Any],
    *,
    expected_revision: str,
    expected_image: str,
    source_overlay_commit: str,
    overlay_sha256: str,
    compose_version: str,
    mode: str = "configuration",
    image_inspection: dict[str, Any] | None = None,
    supporting_provenance: dict[str, Any] | None = None,
    supporting_provenance_sha256: str = "",
) -> dict[str, Any]:
    """Validate a rendered candidate contract without exposing secrets or host paths."""

    issues: list[str] = []
    evidence_issues: list[str] = []
    revision = str(expected_revision or "").strip()
    image = str(expected_image or "").strip()
    overlay_commit = str(source_overlay_commit or "").strip()
    overlay_digest = str(overlay_sha256 or "").strip()
    requested_mode = str(mode or "").strip()
    mode_valid = requested_mode in {"configuration", "release"}
    selected_mode = requested_mode if mode_valid else "invalid"
    if not mode_valid:
        issues.append("candidate:verification_mode:invalid")
    revision_valid = bool(REVISION_RE.fullmatch(revision))
    if not revision_valid:
        issues.append("candidate:revision:invalid")
    image_valid = bool(IMAGE_RE.fullmatch(image)) and image.count("@") == 1
    if not image_valid:
        issues.append("candidate:image:not_immutable_digest_reference")
    image_digest = image.rsplit("@", 1)[-1] if "@" in image else ""
    if not DIGEST_RE.fullmatch(image_digest):
        issues.append("candidate:image:digest_invalid")
    if not REVISION_RE.fullmatch(overlay_commit):
        issues.append("candidate:source_overlay_commit:invalid")
    elif revision_valid and overlay_commit != revision:
        issues.append("candidate:source_overlay_commit:revision_mismatch")
    if not DIGEST_HEX_RE.fullmatch(overlay_digest):
        issues.append("candidate:overlay_sha256:invalid")
    parsed_compose_version = _parse_compose_version(compose_version)
    if parsed_compose_version is None:
        issues.append("candidate:compose_version:invalid_or_unavailable")
    elif parsed_compose_version < COMPOSE_MINIMUM_VERSION:
        issues.append("candidate:compose_version:too_old_for_override_contract")

    if not isinstance(compose_payload, dict):
        services: dict[str, Any] = {}
        top_level_receipt: dict[str, Any] = {}
        extension_environment: dict[str, str] = {}
        issues.append("compose:root:not_mapping")
    else:
        services_value = compose_payload.get("services")
        services = services_value if isinstance(services_value, dict) else {}
        if not isinstance(services_value, dict):
            issues.append("compose:services:not_mapping")
        if str(compose_payload.get("name") or "") != CANDIDATE_PROJECT:
            issues.append("compose:name:candidate_project_mismatch")
        top_level_receipt, extension_environment = _check_top_level_contract(
            compose_payload,
            expected_revision=revision,
            image_digest=image_digest,
            issues=issues,
        )
    actual_service_names = set(str(key) for key in services)
    if actual_service_names != set(ALL_SERVICES):
        issues.append("compose:services:exact_set_mismatch")

    inert_receipts: dict[str, Any] = {}
    target_receipts: dict[str, Any] = {}
    target_environments: dict[str, dict[str, str]] = {}
    for service in ALL_SERVICES:
        payload = services.get(service)
        if not isinstance(payload, dict):
            _issue(issues, service, "service", "missing_or_invalid")
            continue
        inert_receipts[service] = _check_inert_service(
            payload, service=service, issues=issues
        )
        if service not in TARGET_SERVICES:
            continue

        exact_shape_receipt = _check_target_exact_shape(
            payload, service=service, issues=issues
        )

        service_image = str(payload.get("image") or "").strip()
        if service_image != image:
            _issue(issues, service, "image", "does_not_match_candidate_image")
        if payload.get("build") is not None:
            _issue(issues, service, "build", "must_be_absent")
        if str(payload.get("pull_policy") or "") != "never":
            _issue(issues, service, "pull_policy", "must_be_never")

        environment = _compose_mapping(
            payload.get("environment"),
            service=service,
            field="environment",
            issues=issues,
        )
        target_environments[service] = environment
        environment_keyset_matches = (
            set(environment) == EXPECTED_ENVIRONMENT_KEYS[service]
        )
        if not environment_keyset_matches:
            _issue(issues, service, "environment", "exact_keyset_mismatch")
        revision_environment = {
            "EA_SOURCE_REVISION": revision,
            "EA_DEPLOY_COMMIT_SHA": revision,
            "EA_AUDIOBOOK_RUNTIME_CANDIDATE_REVISION": revision,
            "EA_AUDIOBOOK_RUNTIME_CANDIDATE_IMAGE_DIGEST": image_digest,
            "EA_RELEASE_LABEL": f"audiobook-candidate-{revision}",
        }
        expected_safe_environment = {
            **SAFE_ENVIRONMENT,
            **PRESERVED_SERVICE_ENVIRONMENT[service],
            **revision_environment,
        }
        for key, expected_value in expected_safe_environment.items():
            if environment.get(key) != expected_value:
                _issue(issues, service, key, "unsafe_or_mismatched_value")
        for key in REQUIRED_NONEMPTY_ENVIRONMENT:
            if not _is_resolved(environment.get(key, "")):
                _issue(issues, service, key, "missing_or_unresolved")
        for key in URL_ENVIRONMENT:
            value = environment.get(key, "")
            if _is_resolved(value) and not _is_http_url(value):
                _issue(issues, service, key, "invalid_http_url")
        for key in SECRET_ENVIRONMENT:
            value = environment.get(key, "")
            if _is_resolved(value) and len(value.encode("utf-8")) < 16:
                _issue(issues, service, key, "secret_too_short")

        labels = _compose_mapping(
            payload.get("labels"), service=service, field="labels", issues=issues
        )
        expected_labels = {
            "org.opencontainers.image.revision": revision,
            "com.archonmegalon.ea.audiobook-runtime.contract": OVERLAY_CONTRACT,
            "com.archonmegalon.ea.audiobook-runtime.source-revision": revision,
            "com.archonmegalon.ea.audiobook-runtime.image-digest": image_digest,
            "com.archonmegalon.ea.audiobook-runtime.deployment-authority": "denied",
        }
        if service == "ea-api":
            expected_labels[
                "com.archonmegalon.ea.audiobook-runtime.live-owner-handoff"
            ] = "required"
        labels_keyset_matches = set(labels) == set(expected_labels)
        if not labels_keyset_matches:
            _issue(issues, service, "labels", "exact_keyset_mismatch")
        for key, expected_value in expected_labels.items():
            if labels.get(key) != expected_value:
                _issue(issues, service, key, "label_mismatch")

        mount_receipts = _check_mounts(payload, service=service, issues=issues)
        security_receipt = _check_target_security(
            payload, service=service, issues=issues
        )
        safe_environment_values = {
            key: (
                expected_safe_environment[key]
                if environment.get(key) == expected_safe_environment[key]
                else "mismatch"
            )
            for key in sorted(expected_safe_environment)
        }
        safe_label_values = {
            key: expected_labels[key] if labels.get(key) == expected_labels[key] else "mismatch"
            for key in sorted(expected_labels)
        }
        target_receipts[service] = {
            **exact_shape_receipt,
            "candidate_image_matches": service_image == image,
            "pull_policy_never": str(payload.get("pull_policy") or "") == "never",
            "build_absent": payload.get("build") is None,
            "safe_environment": safe_environment_values,
            "environment_keyset_exact": environment_keyset_matches,
            "environment_values_bound_in_digest": True,
            "required_sensitive_environment": {
                key: {
                    "present": _is_resolved(environment.get(key, "")),
                    "kind": "secret" if key in SECRET_ENVIRONMENT else "configuration",
                }
                for key in REQUIRED_NONEMPTY_ENVIRONMENT
            },
            "labels": safe_label_values,
            "labels_keyset_exact": labels_keyset_matches,
            "mounts": mount_receipts,
            "execution_and_security": security_receipt,
            "live_owner_handoff": "required" if service == "ea-api" else "not_applicable",
        }

    shared_environment_applied = True
    for service in TARGET_SERVICES:
        environment = target_environments.get(service, {})
        if any(
            environment.get(key) != extension_environment.get(key)
            for key in EXPECTED_SHARED_ENVIRONMENT_KEYS
        ):
            shared_environment_applied = False
            _issue(issues, service, "environment", "shared_extension_value_mismatch")
    if top_level_receipt:
        top_level_receipt["shared_environment_applied_to_targets"] = (
            shared_environment_applied
        )

    image_summary, image_issues = _validate_image_inspection(
        image_inspection,
        expected_image=image,
        expected_revision=revision,
    )
    provenance_summary, provenance_issues = _validate_supporting_provenance(
        supporting_provenance,
        provenance_sha256=supporting_provenance_sha256,
        expected_revision=revision,
        expected_image_id=str(image_summary.get("image_id") or ""),
    )
    if selected_mode == "release":
        evidence_issues.extend(image_issues)
        evidence_issues.extend(provenance_issues)
        evidence_issues.append("evidence:signed_immutable_candidate_authority:unavailable")
    else:
        if image_inspection is not None:
            evidence_issues.extend(image_issues)
        if supporting_provenance is not None:
            evidence_issues.extend(provenance_issues)

    configuration_valid = not issues
    compose_version_text = (
        ".".join(str(part) for part in parsed_compose_version)
        if parsed_compose_version is not None
        else ""
    )
    rendered_contract_sha256 = (
        _canonical_digest(
            {
                "contract_name": CONTRACT_NAME,
                "overlay_contract": OVERLAY_CONTRACT,
                "source_overlay_commit": overlay_commit,
                "overlay_sha256": overlay_digest,
                "compose_version": compose_version_text,
                "rendered_compose": _sanitized_render_projection(compose_payload),
            }
        )
        if configuration_valid
        else ""
    )
    all_issues = sorted(set(issues + evidence_issues))
    if issues or evidence_issues:
        status = "blocked"
    elif selected_mode == "configuration":
        status = "configuration_only"
    else:
        # Release mode always has the signed-authority issue above.  Keep this
        # defensive branch fail-closed if the evidence policy is later changed.
        status = "blocked"
        all_issues.append("evidence:release_authority_policy:not_satisfied")

    configuration_projection = {
        "contract_name": OVERLAY_CONTRACT,
        "status": "pass" if configuration_valid else "blocked",
        "configuration_only": True,
        "configuration_valid": configuration_valid,
        "configuration_authority": False,
        "deploy_ready": False,
        "deployment_authority": False,
        "promotion_authority": False,
        "live_mutation_authority": False,
        "runtime_execution_authority": False,
        "queue_mutation_authority": False,
        "provider_work_authority": False,
        "outbound_send_authority": False,
        "build_authority": False,
        "pull_authority": False,
        "target_services": list(TARGET_SERVICES),
        "source_revision": revision if revision_valid else "",
        "candidate_image_reference": image if image_valid else "",
        "overlay_sha256": (
            overlay_digest if DIGEST_HEX_RE.fullmatch(overlay_digest) else ""
        ),
        "rendered_contract_sha256": (
            rendered_contract_sha256.removeprefix("sha256:")
            if rendered_contract_sha256
            else ""
        ),
        "execution_scope": "isolated_candidate_configuration",
        "live_api_owner": "ea_core",
        "owner_handoff_required": True,
        "cross_product_runtime_compatible": False,
        "group_deploy_eligible": False,
        "silent_takeover_allowed": False,
    }

    return {
        "contract_name": CONTRACT_NAME,
        "status": status,
        "verification_mode": selected_mode,
        "verified_at": _utc_now(),
        "candidate_project": CANDIDATE_PROJECT,
        "target_services": list(TARGET_SERVICES),
        "expected_revision": revision if revision_valid else "",
        "expected_image": image if image_valid else "",
        "source_revision": revision if revision_valid else "",
        "candidate_image_reference": image if image_valid else "",
        "image_digest": image_digest if DIGEST_RE.fullmatch(image_digest) else "",
        "source_overlay_commit": (
            overlay_commit if REVISION_RE.fullmatch(overlay_commit) else ""
        ),
        "overlay_sha256": (
            overlay_digest if DIGEST_HEX_RE.fullmatch(overlay_digest) else ""
        ),
        "compose_version": compose_version_text,
        "rendered_contract_sha256": rendered_contract_sha256,
        "rendered_contract_digest_valid": configuration_valid,
        "rendered_contract_digest_scope": (
            "full_render_with_opaque_environment_and_machine_path_commitments"
        ),
        "deploy_ready": False,
        "configuration_authority": False,
        "deployment_authority": False,
        "promotion_authority": False,
        "live_mutation_authority": False,
        "runtime_execution_authority": False,
        "queue_mutation_authority": False,
        "provider_work_authority": False,
        "outbound_send_authority": False,
        "build_authority": False,
        "pull_authority": False,
        "mutations_performed": 0,
        "live_owner": {
            "ea-api": "ea_core",
            "candidate_posture": "owner_handoff_required",
            "silent_takeover_allowed": False,
        },
        "issues": sorted(set(all_issues)),
        "unresolved_mandatory_gates": list(UNRESOLVED_MANDATORY_GATES),
        "evidence": {
            "local_image_inspection": image_summary,
            "supporting_build_provenance": provenance_summary,
            "signed_immutable_candidate_authority": {
                "available": False,
                "validated": False,
            },
        },
        "inert_services": inert_receipts,
        "top_level_contract": top_level_receipt,
        "services": target_receipts,
        "configuration_projection": configuration_projection,
        "next_action": (
            "obtain_owner_handoff_and_missing_authorities_before_any_runtime_action"
            if status == "configuration_only"
            else "repair_blocking_configuration_or_evidence_without_deploying"
        ),
    }


def _load_compose(path_text: str) -> dict[str, Any]:
    if path_text == "-":
        payload = json.load(sys.stdin)
    else:
        with Path(path_text).open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("rendered Compose JSON root must be an object")
    return payload


def _load_private_json(path: Path) -> tuple[dict[str, Any], str]:
    if not path.is_absolute():
        raise ValueError("evidence path must be absolute")
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("evidence must be a regular non-symlink file")
        if before.st_uid != os.getuid():
            raise ValueError("evidence must be owned by the current user")
        if before.st_nlink != 1:
            raise ValueError("evidence must have one hard link")
        if stat.S_IMODE(before.st_mode) != 0o600:
            raise ValueError("evidence permissions must be private")
        if before.st_size < 2 or before.st_size > 1_048_576:
            raise ValueError("evidence size is outside the accepted bounds")
        chunks: list[bytes] = []
        remaining = int(before.st_size)
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                raise ValueError("evidence changed while it was read")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        current = path.lstat()
        identity_fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_gid",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if any(
            getattr(before, field) != getattr(after, field)
            or getattr(before, field) != getattr(current, field)
            for field in identity_fields
        ):
            raise ValueError("evidence changed while it was read")
        raw = b"".join(chunks)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("evidence root must be an object")
    return payload, "sha256:" + hashlib.sha256(raw).hexdigest()


def _run_read_only(command: list[str], *, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _read_compose_version() -> str:
    completed = _run_read_only(["docker", "compose", "version", "--short"])
    if completed.returncode != 0:
        return ""
    value = completed.stdout.strip()
    return value if _parse_compose_version(value) is not None else ""


def _inspect_local_image(image: str) -> dict[str, Any] | None:
    completed = _run_read_only(["docker", "image", "inspect", "--", image])
    if completed.returncode != 0:
        return None
    payload = json.loads(completed.stdout)
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        return None
    return payload[0]


def _discover_overlay_commit() -> str:
    diff = _run_read_only(
        ["git", "-C", str(ROOT), "diff", "--quiet", "HEAD", "--", str(OVERLAY_RELATIVE_PATH)]
    )
    if diff.returncode != 0:
        return ""
    completed = _run_read_only(["git", "-C", str(ROOT), "rev-parse", "HEAD"])
    if completed.returncode != 0:
        return ""
    value = completed.stdout.strip()
    return value if REVISION_RE.fullmatch(value) else ""


def _read_overlay_sha256() -> str:
    path = ROOT / OVERLAY_RELATIVE_PATH
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid not in {0, os.getuid()}
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) & 0o022
            or before.st_size < 1
            or before.st_size > 1_048_576
        ):
            return ""
        digest = hashlib.sha256()
        remaining = int(before.st_size)
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                return ""
            digest.update(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            return ""
        return digest.hexdigest()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _write_receipt(path: Path, payload: dict[str, Any], *, pretty: bool) -> None:
    if not path.is_absolute():
        raise ValueError("receipt path must be absolute")
    if not path.parent.is_dir():
        raise ValueError("receipt parent must already exist")
    serialized = json.dumps(payload, indent=2 if pretty else None, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify an already-rendered, inert audiobook candidate configuration. "
            "This command performs only read-only version, Git, and optional local-image inspection."
        )
    )
    parser.add_argument("--compose-json", required=True, help="Rendered Compose JSON path, or -")
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--expected-image", required=True)
    parser.add_argument(
        "--mode", choices=("configuration", "release"), default="configuration"
    )
    parser.add_argument(
        "--supporting-build-provenance",
        default="",
        help="Optional absolute path to a private image-build receipt",
    )
    parser.add_argument("--receipt", default="", help="Optional absolute receipt path")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    try:
        compose_payload = _load_compose(str(args.compose_json))
        compose_version = _read_compose_version()
        overlay_commit = _discover_overlay_commit()
        overlay_sha256 = _read_overlay_sha256()
        requested_image = str(args.expected_image).strip()
        image_inspection = (
            _inspect_local_image(requested_image)
            if args.mode == "release"
            and IMAGE_RE.fullmatch(requested_image)
            and requested_image.count("@") == 1
            else None
        )
        provenance: dict[str, Any] | None = None
        provenance_digest = ""
        if args.supporting_build_provenance:
            provenance, provenance_digest = _load_private_json(
                Path(args.supporting_build_provenance)
            )
        result = verify_audiobook_runtime_candidate(
            compose_payload,
            expected_revision=str(args.expected_revision),
            expected_image=str(args.expected_image),
            source_overlay_commit=overlay_commit,
            overlay_sha256=overlay_sha256,
            compose_version=compose_version,
            mode=str(args.mode),
            image_inspection=image_inspection,
            supporting_provenance=provenance,
            supporting_provenance_sha256=provenance_digest,
        )
        if args.receipt:
            _write_receipt(Path(args.receipt), result, pretty=bool(args.pretty))
    except Exception as exc:
        result = {
            "contract_name": CONTRACT_NAME,
            "status": "blocked",
            "verification_mode": str(args.mode),
            "verified_at": _utc_now(),
            "configuration_authority": False,
            "deploy_ready": False,
            "deployment_authority": False,
            "promotion_authority": False,
            "live_mutation_authority": False,
            "runtime_execution_authority": False,
            "queue_mutation_authority": False,
            "provider_work_authority": False,
            "outbound_send_authority": False,
            "build_authority": False,
            "pull_authority": False,
            "rendered_contract_sha256": "",
            "rendered_contract_digest_valid": False,
            "mutations_performed": 0,
            "issues": [f"preflight_input:{type(exc).__name__}"],
            "unresolved_mandatory_gates": list(UNRESOLVED_MANDATORY_GATES),
            "next_action": "repair_preflight_input_without_deploying",
        }

    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if result.get("status") == "configuration_only" else 1


if __name__ == "__main__":
    raise SystemExit(main())
