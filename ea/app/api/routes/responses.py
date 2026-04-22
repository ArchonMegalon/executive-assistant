from __future__ import annotations

import abc
import json
import os
import queue
import re
import shlex
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.responses import Response

from app.api.dependencies import RequestContext, get_container, get_request_context, is_operator_context
from app.container import AppContainer
from app.domain.models import ToolInvocationRequest
from app.services.brain_router import BrainRouterService
from app.services.tool_execution_common import ToolExecutionError
from app.services.brain_catalog import (
    DEFAULT_PUBLIC_MODEL,
    FAST_PUBLIC_MODEL,
    GROUNDWORK_PUBLIC_MODEL,
    HARD_BATCH_PUBLIC_MODEL,
    HARD_RESCUE_PUBLIC_MODEL,
    MAGICX_PUBLIC_MODEL,
    ONEMIN_PUBLIC_MODEL,
    REPAIR_GEMINI_PUBLIC_MODEL,
    REVIEW_LIGHT_PUBLIC_MODEL,
    SURVIVAL_PUBLIC_MODEL,
    get_brain_profile,
    list_brain_profiles,
)
from app.services.responses_upstream import (
    ResponsesUpstreamError,
    UpstreamResult,
    codex_status_report,
    _provider_health_report,
    _provider_order,
    generate_text,
    list_response_models,
    principal_identity_summary,
    stream_text,
)
from app.services.survival_lane import SurvivalLaneService


router = APIRouter(tags=["responses"])
models_router = APIRouter(prefix="/v1/models", tags=["responses"])
responses_item_router = APIRouter(prefix="/v1/responses", tags=["responses"])
codex_router = APIRouter(prefix="/v1/codex", tags=["responses"])
STREAM_HEARTBEAT_SECONDS = 10.0
_SSE_KEEPALIVE_TEXT = "Trace: waiting on upstream reasoning.\n"
_SUPPORTED_INPUT_PART_TYPES = {"input_text", "text", "output_text"}
_ENV_ASSIGNMENT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
_SHELL_BUILTIN_COMMANDS = frozenset(
    {
        ":",
        ".",
        "alias",
        "bg",
        "builtin",
        "cd",
        "command",
        "echo",
        "eval",
        "exec",
        "exit",
        "export",
        "false",
        "fg",
        "getopts",
        "hash",
        "help",
        "jobs",
        "kill",
        "printf",
        "pwd",
        "read",
        "return",
        "set",
        "shift",
        "source",
        "test",
        "times",
        "trap",
        "true",
        "type",
        "ulimit",
        "umask",
        "unalias",
        "unset",
        "wait",
    }
)
_PROMPT_ROUTE_HARD_PROFILES = frozenset(
    {
        "core",
        "core_authority",
        "core_batch",
        "core_booster",
        "core_rescue",
        "jury",
        "jury_deep",
        "audit_shard",
    }
)
_PROMPT_ROUTE_HARD_MODELS = frozenset(
    filter(
        None,
        {
            str(HARD_BATCH_PUBLIC_MODEL or "").strip().lower(),
            str(HARD_RESCUE_PUBLIC_MODEL or "").strip().lower(),
            str(SURVIVAL_PUBLIC_MODEL or "").strip().lower(),
            "ea-coder-hard",
            "ea-audit-jury",
            "ea-coder-survival",
        },
    )
)
_PROMPT_ROUTE_QUERY_PREFIXES = (
    "how many",
    "how much",
    "what",
    "which",
    "who",
    "where",
    "when",
    "why",
    "is",
    "are",
    "do",
    "does",
    "did",
    "can",
    "could",
    "would",
    "show",
    "list",
    "tell me",
    "check",
    "count",
    "status",
)
_PROMPT_ROUTE_FILLER_PREFIXES = ("so", "ok", "okay", "then", "now", "please")
_DIRECT_FLEET_RUNTIME_TARGET_KEYWORDS = frozenset(
    {
        "fleet",
        "fleet loop",
        "shard",
        "shards",
        "worker",
        "workers",
        "supervisor",
        "runtime",
    }
)
_DIRECT_FLEET_RUNTIME_SIGNAL_KEYWORDS = frozenset(
    {
        "running",
        "active",
        "alive",
        "busy",
        "idle",
        "status",
        "count",
        "currently",
        "right now",
        "now",
    }
)
_DIRECT_FLEET_ETA_TARGET_KEYWORDS = frozenset(
    {
        "fleet",
        "fleet loop",
        "shard",
        "shards",
        "milestone",
        "milestones",
        "product",
        "completion",
        "finish",
    }
)
_DIRECT_FLEET_ETA_SIGNAL_KEYWORDS = frozenset(
    {
        "eta",
        "finish",
        "finished",
        "complete",
        "completion",
        "done",
        "when",
        "long",
        "how long",
    }
)
_PROMPT_ROUTE_SUBJECT_KEYWORDS = frozenset(
    {
        "fleet",
        "fleet loop",
        "codex",
        "codexes",
        "quartermaster",
        "quartiermeister",
        "quatermaster",
        "controller",
        "fleet-controller",
        "fleet controller",
        "trace",
        "route",
        "routed",
        "lane",
        "model",
        "provider",
        "spawn",
        "spawned",
        "running",
        "run",
        "worker",
        "workers",
        "helper",
        "helpers",
        "process",
        "pid",
        "shard",
        "shards",
        "loop",
        "credits",
        "credit",
        "balance",
        "backoff",
        "timeout",
        "timeouts",
        "slow",
        "latency",
        "health",
        "status",
        "session",
        "sessions",
        "account",
        "accounts",
    }
)
_PROMPT_ROUTE_HARD_BLOCKERS = (
    "audit",
    "review",
    "browseract",
    "handoff",
    "resume",
    "continue working",
    "continue from",
    "fix",
    "patch",
    "implement",
    "wire",
    "edit",
    "change",
    "refactor",
    "create",
    "build",
    "write",
    "add ",
    "remove ",
    "rename",
    "move ",
    "debug",
    "investigate",
    "repair",
    "restart",
    "run tests",
    "test ",
    "verify",
    "smoke",
    "commit",
    "push",
    "publish",
    "deploy",
    "workflow",
    "login",
)
_PROMPT_ROUTE_CODE_MARKERS = (
    "```",
    "`",
    "/docker/",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".yaml",
    ".yml",
    ".json",
    ".md",
)


def _responses_upstream_idle_timeout_seconds(*, model: str = "", codex_profile: str = "") -> float:
    raw = str(os.environ.get("EA_RESPONSES_UPSTREAM_IDLE_TIMEOUT_SECONDS") or "300").strip()
    try:
        parsed = float(raw)
    except Exception:
        parsed = 300.0
    normalized_model = str(model or "").strip().lower()
    normalized_profile = str(codex_profile or "").strip().lower()
    hard_timeout_raw = str(
        os.environ.get("EA_RESPONSES_UPSTREAM_IDLE_TIMEOUT_HARD_SECONDS") or max(parsed, 300.0)
    ).strip()
    try:
        hard_parsed = float(hard_timeout_raw)
    except Exception:
        hard_parsed = max(parsed, 300.0)
    hard_profiles = {
        "core",
        "core_authority",
        "core_booster",
        "core_rescue",
        "jury",
        "jury_deep",
        "audit_shard",
    }
    hard_models = {
        str(DEFAULT_PUBLIC_MODEL or "").strip().lower(),
        str(SURVIVAL_PUBLIC_MODEL or "").strip().lower(),
        "ea-coder-hard",
        str(HARD_BATCH_PUBLIC_MODEL or "").strip().lower(),
        str(HARD_RESCUE_PUBLIC_MODEL or "").strip().lower(),
        "ea-audit-jury",
        "ea-coder-survival",
    }
    rescue_timeout_raw = str(
        os.environ.get("EA_RESPONSES_UPSTREAM_IDLE_TIMEOUT_CORE_RESCUE_SECONDS") or max(hard_parsed, 900.0)
    ).strip()
    try:
        rescue_parsed = float(rescue_timeout_raw)
    except Exception:
        rescue_parsed = max(hard_parsed, 900.0)
    if normalized_profile == "core_rescue" or normalized_model == str(HARD_RESCUE_PUBLIC_MODEL or "").strip().lower():
        timeout_seconds = rescue_parsed
    else:
        timeout_seconds = hard_parsed if normalized_profile in hard_profiles or normalized_model in hard_models else parsed
    return max(timeout_seconds, STREAM_HEARTBEAT_SECONDS + 1.0)


def _streaming_codex_profiles() -> set[str]:
    raw = str(os.environ.get("EA_RESPONSES_STREAMING_CODEX_PROFILES") or "easy,repair,groundwork").strip()
    values = {item.strip().lower() for item in raw.split(",") if item.strip()}
    return values or {"easy", "repair", "groundwork"}


def _requested_model_is_explicit(value: str | None) -> bool:
    normalized = str(value or "").strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    if ":" in normalized:
        return True
    return not lowered.startswith("ea-")


def _prefer_nonstream_upstream(*, model: str = "", codex_profile: str = "") -> bool:
    normalized_model = str(model or "").strip().lower()
    normalized_profile = str(codex_profile or "").strip().lower()
    if normalized_profile and normalized_profile in _streaming_codex_profiles():
        return False
    if normalized_profile:
        return True
    if not normalized_model:
        return True
    if normalized_model.startswith("ea-"):
        return True
    return normalized_model == str(HARD_BATCH_PUBLIC_MODEL or "").strip().lower() or normalized_profile == "core_batch"


def _codex_trace_instructions_enabled(*, codex_profile: str | None = None, stream: bool = False) -> bool:
    normalized_profile = str(codex_profile or "").strip().lower()
    if not stream or not normalized_profile:
        return False
    raw = str(os.environ.get("EA_CODEX_TRACE_INSTRUCTIONS") or "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def _codex_trace_instruction(*, codex_profile: str | None = None) -> str:
    lane = str(codex_profile or "easy").strip().lower() or "easy"
    return (
        f"Immediately print one short `Trace:` line with lane={lane} and the work you are starting.\n"
        "Keep emitting short one-line `Trace:` updates before each meaningful work unit and again if you have been quiet for roughly 20-45 seconds.\n"
        "If you need to wait on tools, remote state, or a long-running step, emit a short `Trace:` wait line before continuing.\n"
        "After the first trace line, continue the task normally."
    )


@dataclass(frozen=True)
class _ParsedResponseInput:
    messages: list[dict[str, str]]
    input_items: list[dict[str, object]]
    prompt: str


@dataclass(frozen=True)
class _StoredResponse:
    response: dict[str, object]
    input_items: list[dict[str, object]]
    history_items: list[dict[str, object]]
    principal_id: str
    background_job: dict[str, object] | None = None


@dataclass(frozen=True)
class _PromptRouteDecision:
    applied: bool
    reason: str
    original_profile: str | None
    original_model: str
    effective_profile: str | None
    effective_model: str
    trace_line: str


class _ResponseRecordRepository(abc.ABC):
    @abc.abstractmethod
    def store(
        self,
        *,
        response_id: str,
        response_obj: dict[str, object],
        input_items: list[dict[str, object]],
        history_items: list[dict[str, object]],
        principal_id: str,
        background_job: dict[str, object] | None = None,
    ) -> None:
        """Store a response record for the requested principal."""

    @abc.abstractmethod
    def load(
        self,
        *,
        response_id: str,
        principal_id: str,
    ) -> _StoredResponse:
        """Load a previously stored response record for a principal."""


class _MemoryResponseRecordRepository(_ResponseRecordRepository):
    def __init__(self) -> None:
        self._records: dict[str, _StoredResponse] = {}
        self._lock = threading.Lock()

    def store(
        self,
        *,
        response_id: str,
        response_obj: dict[str, object],
        input_items: list[dict[str, object]],
        history_items: list[dict[str, object]],
        principal_id: str,
        background_job: dict[str, object] | None = None,
    ) -> None:
        with self._lock:
            self._records[response_id] = _StoredResponse(
                response=dict(response_obj),
                input_items=[dict(item) for item in input_items],
                history_items=[dict(item) for item in history_items],
                principal_id=principal_id,
                background_job=dict(background_job) if isinstance(background_job, dict) else None,
            )

    def load(
        self,
        *,
        response_id: str,
        principal_id: str,
    ) -> _StoredResponse:
        with self._lock:
            stored = self._records.get(response_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="response_not_found")
        if stored.principal_id != principal_id:
            raise HTTPException(status_code=403, detail="principal_scope_mismatch")
        return stored


class _PostgresResponseRecordRepository(_ResponseRecordRepository):
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for Postgres response storage")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres response storage") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: object):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS response_records (
                        response_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        response_json JSONB NOT NULL,
                        input_items_json JSONB NOT NULL,
                        history_items_json JSONB NOT NULL,
                        background_job_json JSONB NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    ALTER TABLE response_records
                    ADD COLUMN IF NOT EXISTS background_job_json JSONB NULL
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_response_records_principal_created
                    ON response_records(principal_id, created_at DESC)
                    """
                )

    def store(
        self,
        *,
        response_id: str,
        response_obj: dict[str, object],
        input_items: list[dict[str, object]],
        history_items: list[dict[str, object]],
        principal_id: str,
        background_job: dict[str, object] | None = None,
    ) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO response_records (
                        response_id,
                        principal_id,
                        response_json,
                        input_items_json,
                        history_items_json,
                        background_job_json
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (response_id) DO UPDATE SET
                        principal_id = EXCLUDED.principal_id,
                        response_json = EXCLUDED.response_json,
                        input_items_json = EXCLUDED.input_items_json,
                        history_items_json = EXCLUDED.history_items_json,
                        background_job_json = EXCLUDED.background_job_json,
                        updated_at = NOW()
                    """,
                    (
                        response_id,
                        principal_id,
                        self._json_value(response_obj),
                        self._json_value(input_items),
                        self._json_value(history_items),
                        self._json_value(background_job) if background_job is not None else None,
                    ),
                )

    def load(
        self,
        *,
        response_id: str,
        principal_id: str,
    ) -> _StoredResponse:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT principal_id, response_json, input_items_json, history_items_json, background_job_json
                    FROM response_records
                    WHERE response_id = %s
                    """,
                    (response_id,),
                )
                row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="response_not_found")
        stored_principal_id, response_json, input_items_json, history_items_json, background_job_json = row
        if str(stored_principal_id or "") != principal_id:
            raise HTTPException(status_code=403, detail="principal_scope_mismatch")
        return _StoredResponse(
            response=dict(response_json or {}),
            input_items=[dict(item) for item in list(input_items_json or []) if isinstance(item, dict)],
            history_items=[dict(item) for item in list(history_items_json or []) if isinstance(item, dict)],
            principal_id=str(stored_principal_id or ""),
            background_job=dict(background_job_json or {}) if isinstance(background_job_json, dict) else None,
        )


_RESPONSE_REPOSITORY_LOCK = threading.Lock()
_MEMORY_RESPONSE_REPOSITORY = _MemoryResponseRecordRepository()
_POSTGRES_RESPONSE_REPOSITORIES: dict[str, _PostgresResponseRecordRepository] = {}
_STREAM_RESPONSE_OVERRIDE_LOCK = threading.Lock()
_STREAM_RESPONSE_OVERRIDES: dict[str, tuple[float, str, dict[str, object]]] = {}
_BACKGROUND_RESPONSE_LOCK = threading.Lock()
_BACKGROUND_RESPONSE_WORKERS: dict[str, threading.Thread] = {}
_BACKGROUND_RESPONSE_STARTING: set[str] = set()
_BACKGROUND_RESPONSE_TRANSITION_LOCK = threading.Lock()
_DEFAULT_DESIGN_PRODUCT_ROOT = Path("/docker/chummercomplete/chummer-design/products/chummer")

_CODEx_PROFILES = tuple(
    {
        "profile": profile.profile,
        "lane": profile.lane,
        "model": profile.public_model,
        "provider_hint_order": profile.provider_hint_order,
        "review_required": bool(profile.review_required),
        "needs_review": bool(profile.needs_review),
        "risk_labels": list(profile.risk_labels),
        "merge_policy": str(profile.merge_policy or "auto"),
    }
    for profile in list_brain_profiles()
)


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".codex-design").exists():
            return parent
    return current.parents[4]


def _design_product_root() -> Path:
    raw = str(os.getenv("CHUMMER6_DESIGN_PRODUCT_ROOT") or "").strip()
    if raw:
        return Path(raw)
    local_root = _repo_root() / ".codex-design/product"
    if local_root.exists():
        return local_root
    return _DEFAULT_DESIGN_PRODUCT_ROOT


def _design_product_path(filename: str) -> Path:
    root = _design_product_root()
    candidate = root / filename
    if candidate.exists():
        return candidate
    local_root = (_repo_root() / ".codex-design/product").resolve()
    try:
        resolved_root = root.resolve()
    except Exception:
        resolved_root = root
    if resolved_root == local_root and _DEFAULT_DESIGN_PRODUCT_ROOT.exists():
        fallback = _DEFAULT_DESIGN_PRODUCT_ROOT / filename
        if fallback.exists():
            return fallback
    return candidate


def _load_design_yaml_dict(filename: str) -> dict[str, object]:
    path = _design_product_path(filename)
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _scorecard_entry(scorecard_id: str) -> dict[str, object]:
    payload = _load_design_yaml_dict("PRODUCT_HEALTH_SCORECARD.yaml")
    for row in list(payload.get("scorecards") or []):
        entry = dict(row or {}) if isinstance(row, dict) else {}
        if str(entry.get("id") or "").strip() == scorecard_id:
            return entry
    return {}


def _codex_review_cadence() -> dict[str, str]:
    payload = _load_design_yaml_dict("PRODUCT_HEALTH_SCORECARD.yaml")
    cadence = dict(payload.get("cadence") or {}) if isinstance(payload.get("cadence"), dict) else {}
    return {
        "review": str(cadence.get("review") or "weekly").strip() or "weekly",
        "snapshot_owner": str(cadence.get("snapshot_owner") or "product_governor").strip() or "product_governor",
        "publication": str(cadence.get("publication") or "internal_canon_first").strip() or "internal_canon_first",
    }


def _codex_support_help_boundary() -> dict[str, str]:
    entry = _scorecard_entry("support_and_feedback_closure")
    metrics = [dict(item or {}) for item in list(entry.get("metrics") or []) if isinstance(item, dict)]
    first_metric = metrics[0] if metrics else {}
    question = str(entry.get("question") or "").strip()
    target = str(first_metric.get("target") or "").strip()
    return {
        "summary": "Support and help outputs stay grounded and downstream of Hub case truth; EA prepares governed packets without becoming a second canon.",
        "owner": str(entry.get("owner") or "chummer6-hub").strip() or "chummer6-hub",
        "question": question or "Are user-reported problems being closed honestly?",
        "target": target or "<=72h first grounded or human response",
        "boundary": "Keep help, support, and operator outputs connected back to canonical Hub, Design, and Fleet truth surfaces.",
    }


def _codex_governance_sources() -> list[dict[str, str]]:
    return [
        {
            "label": "CAMPAIGN_OS_GAP_AND_CHANGE_GUIDE.md",
            "path": ".codex-design/product/CAMPAIGN_OS_GAP_AND_CHANGE_GUIDE.md",
            "focus": "EA required changes: formalize review cadence, separate lane expectations, and keep outputs tied to canon.",
        },
        {
            "label": "PRODUCT_HEALTH_SCORECARD.yaml",
            "path": ".codex-design/product/PRODUCT_HEALTH_SCORECARD.yaml",
            "focus": "Formal weekly review cadence and support-closure operating question.",
        },
        {
            "label": "PRODUCT_CONTROL_AND_GOVERNOR_LOOP.md",
            "path": ".codex-design/product/PRODUCT_CONTROL_AND_GOVERNOR_LOOP.md",
            "focus": "EA remains a governed packet/synthesis layer downstream of canon.",
        },
    ]


def _codex_governance_payload() -> dict[str, object]:
    return {
        "summary": "EA should stay a governed synthesis and runtime substrate downstream of canon instead of turning into hidden policy.",
        "review_cadence": _codex_review_cadence(),
        "support_help_boundary": _codex_support_help_boundary(),
        "sources": _codex_governance_sources(),
    }


def _codex_profile_expectation(profile_name: str) -> dict[str, str]:
    normalized = str(profile_name or "").strip().lower()
    expectations = {
        "core": {
            "work_class": "hard_coder",
            "expectation_summary": "Hard coder lane for substantive implementation, debugging, and repo-changing work that can materially affect the product.",
            "review_posture": "Require review before merge or release-facing adoption.",
            "best_for": "Blocking bugs, feature work, refactors, and code paths that need the strongest model lane.",
        },
        "easy": {
            "work_class": "easy",
            "expectation_summary": "Easy lane for cheap status answers, lightweight drafting, and low-impact assist work that should stay fast and inexpensive.",
            "review_posture": "No formal review by default; escalate if the task turns into product truth or meaningful code change.",
            "best_for": "Quick operator questions, low-risk prose, and lightweight synthesis.",
        },
        "repair": {
            "work_class": "repair",
            "expectation_summary": "Repair lane for bounded follow-up patches after a concrete failure, regression, or verifier finding.",
            "review_posture": "Auto only for low-risk bounded fixes; escalate when the patch expands beyond the original failure.",
            "best_for": "Small safe repairs, cleanup diffs, and well-scoped regression fixes.",
        },
        "groundwork": {
            "work_class": "groundwork",
            "expectation_summary": "Groundwork lane for non-urgent analysis, planning, design shaping, and synthesis that should inform action without quietly becoming policy.",
            "review_posture": "Use as preparation and framing; convert to a reviewed implementation or audit lane before high-impact changes.",
            "best_for": "Research briefs, design synthesis, option narrowing, and preparation packets.",
        },
        "review_light": {
            "work_class": "review_light",
            "expectation_summary": "Review-light lane for fast diff checks and posthoc verification when a full jury pass would be too heavy.",
            "review_posture": "Use for light review only; escalate to audit/jury when release, trust, or multi-surface risk is present.",
            "best_for": "Focused patch review, bounded verifier follow-up, and quick quality checks.",
        },
        "audit": {
            "work_class": "audit_jury",
            "expectation_summary": "Audit/jury lane for publish-facing, cross-surface, or high-risk review where the operator needs a more adversarial multi-view check.",
            "review_posture": "Treat findings as review-required and operator-visible before relying on the result for release or policy decisions.",
            "best_for": "Release review, trust-sensitive changes, broad audits, and high-risk multi-file decisions.",
        },
        "survival": {
            "work_class": "survival_fallback",
            "expectation_summary": "Survival lane is the fallback path when preferred routes are blocked, exhausted, or too degraded to trust for normal flow.",
            "review_posture": "Prefer temporary use with explicit follow-up back on the normal lanes once the stack recovers.",
            "best_for": "Business-continuity execution when the primary route is unavailable.",
        },
        "core_batch": {
            "work_class": "hard_coder_batch",
            "expectation_summary": "Core batch lane is the hard-coder batch path for larger repo work that still carries review-required posture.",
            "review_posture": "Require review before merge or release-facing adoption.",
            "best_for": "Longer-running implementation slices that still belong to the hard coder family.",
        },
        "core_rescue": {
            "work_class": "hard_coder_rescue",
            "expectation_summary": "Core rescue lane is the longer-running hard-coder recovery path for slices that outgrow the normal hard lane budget.",
            "review_posture": "Require review before merge or release-facing adoption.",
            "best_for": "Large rescue passes, timeout-prone implementation slices, and hard recovery work that still needs a strong coder lane.",
        },
    }
    return dict(expectations.get(normalized) or {})


def _enrich_codex_profile(profile: dict[str, object]) -> dict[str, object]:
    return {
        **profile,
        **_codex_profile_expectation(str(profile.get("profile") or "")),
        "review_cadence": _codex_review_cadence(),
        "support_help_boundary": _codex_support_help_boundary(),
        "governance_sources": _codex_governance_sources(),
    }


def _repair_ready_provider(
    profile: dict[str, object],
    *,
    provider_health: dict[str, object] | None = None,
) -> str:
    if str(profile.get("profile") or "").strip().lower() != "repair":
        return ""
    providers = dict(((provider_health or {}).get("providers") or {}))
    hints = [
        str(item or "").strip()
        for item in (profile.get("provider_hint_order") or ())
        if str(item or "").strip()
    ]
    for provider_key in hints:
        row = dict(providers.get(provider_key) or {})
        state = str(row.get("state") or "").strip().lower()
        if state == "ready":
            return provider_key
        if state in {"degraded", "missing", "unavailable", "disabled", "error"}:
            continue
        slots = [dict(item) for item in (row.get("slots") or []) if isinstance(item, dict)]
        if any(str(slot.get("state") or "").strip().lower() == "ready" for slot in slots):
            return provider_key
    return ""


def _provider_health_snapshot(*, lightweight: bool) -> dict[str, object]:
    try:
        payload = _provider_health_report(lightweight=lightweight)
    except TypeError:
        payload = _provider_health_report()
    return dict(payload or {}) if isinstance(payload, dict) else {}


def _effective_codex_profile_model(
    profile: dict[str, object],
    *,
    provider_health: dict[str, object] | None = None,
) -> str:
    normalized_profile = str(profile.get("profile") or "").strip().lower()
    backend = str(profile.get("backend") or "").strip().lower()
    health_provider_key = str(profile.get("health_provider_key") or "").strip().lower()
    effective_provider = backend or health_provider_key
    if normalized_profile == "repair":
        if effective_provider == "onemin":
            return ONEMIN_PUBLIC_MODEL
        if effective_provider == "magixai":
            return MAGICX_PUBLIC_MODEL
        if effective_provider in {"gemini_vortex", ""}:
            return REPAIR_GEMINI_PUBLIC_MODEL
    if normalized_profile == "groundwork":
        return GROUNDWORK_PUBLIC_MODEL
    model = str(profile.get("model") or DEFAULT_PUBLIC_MODEL).strip() or DEFAULT_PUBLIC_MODEL
    return model


def _stabilize_codex_profile(
    profile: dict[str, object],
    *,
    provider_health: dict[str, object] | None = None,
) -> dict[str, object]:
    normalized = dict(profile or {})
    preferred_ready_provider = _repair_ready_provider(normalized, provider_health=provider_health)
    if preferred_ready_provider:
        existing_hints = [
            str(item or "").strip()
            for item in (normalized.get("provider_hint_order") or ())
            if str(item or "").strip()
        ]
        normalized["backend"] = preferred_ready_provider
        normalized["health_provider_key"] = preferred_ready_provider
        normalized["provider_hint_order"] = tuple(
            [preferred_ready_provider]
            + [item for item in existing_hints if item != preferred_ready_provider]
        )
    normalized["model"] = _effective_codex_profile_model(normalized, provider_health=provider_health)
    return normalized


def _set_stream_response_override(
    *,
    response_id: str,
    principal_id: str,
    response_obj: dict[str, object],
    ttl_seconds: float = 1.0,
) -> None:
    with _STREAM_RESPONSE_OVERRIDE_LOCK:
        _STREAM_RESPONSE_OVERRIDES[response_id] = (
            time.monotonic() + max(float(ttl_seconds), 0.0),
            principal_id,
            dict(response_obj),
        )


def _stream_response_override(
    *,
    response_id: str,
    principal_id: str,
) -> dict[str, object] | None:
    with _STREAM_RESPONSE_OVERRIDE_LOCK:
        entry = _STREAM_RESPONSE_OVERRIDES.get(response_id)
        if entry is None:
            return None
        expires_at, stored_principal_id, response_obj = entry
        if expires_at <= time.monotonic():
            _STREAM_RESPONSE_OVERRIDES.pop(response_id, None)
            return None
        if stored_principal_id != principal_id:
            return None
        return dict(response_obj)


class _ResponsesCreateRequest(BaseModel):
    model: str | None = None
    input: Any | None = None
    instructions: str | None = None
    text: Any | None = None
    metadata: dict[str, object] | None = None
    client_metadata: dict[str, object] | None = None
    max_output_tokens: int | None = None
    stream: bool = False
    store: bool | None = None
    tools: list[dict[str, object]] | None = None
    tool_choice: Any | None = None
    parallel_tool_calls: bool | None = None
    reasoning: Any | None = None
    include: list[str] | None = None
    service_tier: str | None = None
    prompt_cache_key: str | None = None
    previous_response_id: str | None = None

    model_config = ConfigDict(extra="forbid")


class _ModelObject(BaseModel):
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str

    model_config = ConfigDict(extra="forbid")


class _ModelListObject(BaseModel):
    object: str = "list"
    data: list[_ModelObject]

    model_config = ConfigDict(extra="forbid")


class _ResponseUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int


class _ResponseOutputTextPart(BaseModel):
    type: str = "output_text"
    text: str
    annotations: list[dict[str, object]] = Field(default_factory=list)


class _ResponseOutputMessage(BaseModel):
    id: str
    type: str = "message"
    status: str
    role: str = "assistant"
    content: list[_ResponseOutputTextPart]


class _ResponseOutputFunctionCall(BaseModel):
    id: str
    type: str = "function_call"
    status: str
    call_id: str
    name: str
    arguments: str


class _ResponseObject(BaseModel):
    id: str
    object: str = "response"
    created_at: int
    status: str
    completed_at: int | None = None
    error: dict[str, object] | None = None
    incomplete_details: dict[str, object] | None = None
    instructions: str | None = None
    input: list[dict[str, object]]
    max_output_tokens: int | None = None
    model: str
    output: list[dict[str, object]]
    usage: _ResponseUsage
    metadata: dict[str, object]
    output_text: str = ""
    reasoning: Any | None = None
    truncation: str | None = None

    model_config = ConfigDict(extra="forbid")


class _ResponseInputItemsListObject(BaseModel):
    object: str = "list"
    response_id: str
    data: list[dict[str, object]]

    model_config = ConfigDict(extra="forbid")


_RESPONSES_PUBLIC_REQUEST_FIELDS = (
    "model",
    "input",
    "instructions",
    "text",
    "metadata",
    "max_output_tokens",
    "stream",
    "reasoning",
    "include",
    "service_tier",
    "prompt_cache_key",
)

_RESPONSES_CREATE_REQUEST_SCHEMA = _ResponsesCreateRequest.model_json_schema()
_response_request_properties = _RESPONSES_CREATE_REQUEST_SCHEMA.get("properties")
if isinstance(_response_request_properties, dict):
    _RESPONSES_CREATE_REQUEST_SCHEMA["properties"] = {
        key: value
        for key, value in _response_request_properties.items()
        if key in _RESPONSES_PUBLIC_REQUEST_FIELDS
    }
_response_request_required = _RESPONSES_CREATE_REQUEST_SCHEMA.get("required")
if isinstance(_response_request_required, list):
    _RESPONSES_CREATE_REQUEST_SCHEMA["required"] = [
        str(key) for key in _response_request_required if str(key) in _RESPONSES_PUBLIC_REQUEST_FIELDS
    ]

_RESPONSES_DEBUG_CAPTURE_PRUNE_LOCK = threading.Lock()
_RESPONSES_DEBUG_CAPTURE_LAST_PRUNE = 0.0


def _responses_debug_capture_dir() -> Path | None:
    raw = str(os.environ.get("EA_RESPONSES_DEBUG_CAPTURE_DIR") or "").strip()
    if not raw:
        return None
    try:
        path = Path(raw)
        path.mkdir(parents=True, exist_ok=True)
        return path
    except Exception:
        return None


def _responses_debug_capture_limit(name: str, default: int, *, minimum: int = 0) -> int:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except Exception:
        return default


def _prune_responses_debug_capture(target_dir: Path) -> None:
    global _RESPONSES_DEBUG_CAPTURE_LAST_PRUNE

    interval_seconds = _responses_debug_capture_limit(
        "EA_RESPONSES_DEBUG_CAPTURE_PRUNE_EVERY_SECONDS",
        60,
        minimum=0,
    )
    now = time.time()
    with _RESPONSES_DEBUG_CAPTURE_PRUNE_LOCK:
        if interval_seconds > 0 and now - _RESPONSES_DEBUG_CAPTURE_LAST_PRUNE < interval_seconds:
            return
        _RESPONSES_DEBUG_CAPTURE_LAST_PRUNE = now

    max_files = _responses_debug_capture_limit("EA_RESPONSES_DEBUG_CAPTURE_MAX_FILES", 500, minimum=1)
    max_bytes = _responses_debug_capture_limit(
        "EA_RESPONSES_DEBUG_CAPTURE_MAX_BYTES",
        512 * 1024 * 1024,
        minimum=1024 * 1024,
    )
    max_age_seconds = _responses_debug_capture_limit(
        "EA_RESPONSES_DEBUG_CAPTURE_MAX_AGE_SECONDS",
        24 * 60 * 60,
        minimum=0,
    )
    files: list[tuple[float, int, Path]] = []
    try:
        for path in target_dir.glob("*.json"):
            if path.name.startswith("latest_"):
                continue
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            if max_age_seconds > 0 and now - stat.st_mtime > max_age_seconds:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                except Exception:
                    continue
                continue
            files.append((stat.st_mtime, int(stat.st_size), path))
    except Exception:
        return

    files.sort(key=lambda row: row[0], reverse=True)
    total_bytes = 0
    for index, (_, size, path) in enumerate(files, start=1):
        total_bytes += size
        if index <= max_files and total_bytes <= max_bytes:
            continue
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            continue


def _capture_responses_debug(*, name: str, payload: object) -> None:
    target_dir = _responses_debug_capture_dir()
    if target_dir is None:
        return
    try:
        stamp = int(time.time() * 1000)
        target = target_dir / f"{stamp}_{name}.json"
        target.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        latest = target_dir / f"latest_{name}.json"
        latest.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        _prune_responses_debug_capture(target_dir)
    except Exception:
        return


def _test_reset_responses_runtime_state() -> None:
    with _STREAM_RESPONSE_OVERRIDE_LOCK:
        _STREAM_RESPONSE_OVERRIDES.clear()
    with _BACKGROUND_RESPONSE_LOCK:
        _BACKGROUND_RESPONSE_WORKERS.clear()
        _BACKGROUND_RESPONSE_STARTING.clear()
    if isinstance(_MEMORY_RESPONSE_REPOSITORY, _MemoryResponseRecordRepository):
        with _MEMORY_RESPONSE_REPOSITORY._lock:
            _MEMORY_RESPONSE_REPOSITORY._records.clear()


def _now_unix() -> int:
    return int(time.time())


def _json_dumps(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def _sse_event(*, event: str, sequence: int, data: dict[str, object]) -> str:
    event_data = dict(data)
    event_data["sequence_number"] = sequence
    return f"event: {event}\ndata: {_json_dumps(event_data)}\n\n"


def _sse_done() -> str:
    return "data: [DONE]\n\n"


def _sse_comment(comment: str = "keep-alive") -> str:
    return f": {comment}\n\n"


def _sse_heartbeat(*, sequence: int, response: dict[str, object]) -> str:
    heartbeat_response = dict(response)
    return _sse_event(
        event="response.in_progress",
        sequence=sequence,
        data={
            "type": "response.in_progress",
            "response": heartbeat_response,
            "heartbeat": True,
        },
    )


def _extract_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _extract_textish(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value).strip()
    if isinstance(value, list):
        parts = [_extract_textish(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        preferred_keys = ("text", "content", "output", "result", "message", "answer")
        for key in preferred_keys:
            text = _extract_textish(value.get(key))
            if text:
                return text
    return ""


def _latest_user_prompt(parsed_input: _ParsedResponseInput) -> str:
    for item in reversed(parsed_input.input_items):
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip().lower()
        if item_type in {"input_text", "text"}:
            cleaned = str(item.get("text") or "").strip()
            if cleaned:
                return cleaned
            continue
        if item_type != "message":
            continue
        role = str(item.get("role") or "").strip().lower()
        if role != "user":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in reversed(content):
            if not isinstance(part, dict):
                continue
            cleaned = str(part.get("text") or "").strip()
            if cleaned:
                return cleaned
    for item in reversed(parsed_input.messages):
        if str(item.get("role") or "").strip().lower() != "user":
            continue
        cleaned = str(item.get("content") or "").strip()
        if cleaned:
            return cleaned
    return str(parsed_input.prompt or "").strip()


def _prompt_route_fragments(prompt: str) -> list[str]:
    raw = str(prompt or "").strip()
    if not raw:
        return []
    fragments: list[str] = []
    seen: set[str] = set()
    for chunk in re.split(r"(?:\n\s*\n|\r\n\s*\r\n)", raw):
        for line in str(chunk).splitlines():
            cleaned = line.strip()
            if not cleaned:
                continue
            normalized = re.sub(r"\s+", " ", cleaned).strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                fragments.append(normalized)
    normalized_raw = re.sub(r"\s+", " ", raw).strip()
    if normalized_raw and normalized_raw not in seen:
        fragments.append(normalized_raw)
    return fragments


def _effective_prompt_route_text(parsed_input: _ParsedResponseInput) -> str:
    user_prompts: list[str] = []
    latest_prompt = _latest_user_prompt(parsed_input)
    if latest_prompt:
        user_prompts.append(latest_prompt)
    for item in reversed(parsed_input.messages):
        if str(item.get("role") or "").strip().lower() != "user":
            continue
        cleaned = str(item.get("content") or "").strip()
        if cleaned and cleaned not in user_prompts:
            user_prompts.append(cleaned)
    for prompt in user_prompts:
        fragments = _prompt_route_fragments(prompt)
        for fragment in reversed(fragments):
            lightweight_ops, _ = _looks_like_lightweight_ops_query(fragment)
            if lightweight_ops:
                return fragment
    return latest_prompt


def _normalized_prompt_route_text(prompt: str) -> str:
    return re.sub(r"\s+", " ", str(prompt or "").strip().lower()).strip()


def _trim_prompt_route_fillers(prompt: str) -> str:
    parts = str(prompt or "").split()
    while parts and parts[0] in _PROMPT_ROUTE_FILLER_PREFIXES:
        parts = parts[1:]
    return " ".join(parts)


def _is_hard_prompt_route_context(*, model: str, codex_profile: str | None) -> bool:
    normalized_profile = str(codex_profile or "").strip().lower()
    normalized_model = str(model or "").strip().lower()
    return normalized_profile in _PROMPT_ROUTE_HARD_PROFILES or normalized_model in _PROMPT_ROUTE_HARD_MODELS


def _looks_like_lightweight_ops_query(prompt: str) -> tuple[bool, str]:
    normalized = _trim_prompt_route_fillers(_normalized_prompt_route_text(prompt))
    if not normalized:
        return False, "empty_prompt"
    if len(normalized) > 280 or len(normalized.split()) > 48:
        return False, "prompt_too_long"
    if any(marker in normalized for marker in _PROMPT_ROUTE_CODE_MARKERS):
        return False, "code_or_file_reference"
    for blocker in _PROMPT_ROUTE_HARD_BLOCKERS:
        if blocker in normalized:
            return False, "requires_core"
    query_like = normalized.endswith("?") or any(
        normalized == prefix or normalized.startswith(f"{prefix} ") for prefix in _PROMPT_ROUTE_QUERY_PREFIXES
    )
    if not query_like:
        return False, "not_question_like"
    if not any(keyword in normalized for keyword in _PROMPT_ROUTE_SUBJECT_KEYWORDS):
        return False, "not_ops_status_query"
    return True, "lightweight_ops_query"


def _looks_like_direct_fleet_runtime_query(prompt: str) -> bool:
    normalized = _trim_prompt_route_fillers(_normalized_prompt_route_text(prompt))
    if not normalized:
        return False
    if len(normalized) > 280 or len(normalized.split()) > 48:
        return False
    if any(marker in normalized for marker in _PROMPT_ROUTE_CODE_MARKERS):
        return False
    if "eta" in normalized:
        return False
    query_like = normalized.endswith("?") or any(
        normalized == prefix or normalized.startswith(f"{prefix} ") for prefix in _PROMPT_ROUTE_QUERY_PREFIXES
    )
    if not query_like:
        return False
    return any(keyword in normalized for keyword in _DIRECT_FLEET_RUNTIME_TARGET_KEYWORDS) and any(
        keyword in normalized for keyword in _DIRECT_FLEET_RUNTIME_SIGNAL_KEYWORDS
    )


def _looks_like_direct_fleet_eta_query(prompt: str) -> bool:
    normalized = _trim_prompt_route_fillers(_normalized_prompt_route_text(prompt))
    if not normalized:
        return False
    if len(normalized) > 280 or len(normalized.split()) > 48:
        return False
    if any(marker in normalized for marker in _PROMPT_ROUTE_CODE_MARKERS):
        return False
    query_like = normalized.endswith("?") or any(
        normalized == prefix or normalized.startswith(f"{prefix} ") for prefix in _PROMPT_ROUTE_QUERY_PREFIXES
    )
    if not query_like and "eta" not in normalized:
        return False
    return any(keyword in normalized for keyword in _DIRECT_FLEET_ETA_TARGET_KEYWORDS) and any(
        keyword in normalized for keyword in _DIRECT_FLEET_ETA_SIGNAL_KEYWORDS
    )


def _fleet_runtime_state_path() -> Path:
    raw = str(
        os.environ.get("EA_FLEET_RUNTIME_STATE_PATH")
        or os.environ.get("CHUMMER_DESIGN_SUPERVISOR_STATE_ROOT")
        or "/docker/fleet/state/chummer_design_supervisor/state.json"
    ).strip()
    path = Path(raw)
    if path.name != "state.json":
        path = path / "state.json"
    return path


def _load_direct_fleet_runtime_status_payload() -> dict[str, object] | None:
    try:
        payload = json.loads(_fleet_runtime_state_path().read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _render_direct_fleet_runtime_status(payload: dict[str, object]) -> str:
    shards = list(payload.get("shards") or [])
    active_shards = [item for item in shards if isinstance(item, dict) and str(item.get("active_run_id") or "").strip()]
    active_runs = [item for item in list(payload.get("active_runs") or []) if isinstance(item, dict)]
    active_shard_names = [
        str(item.get("name") or "").strip()
        for item in active_shards
        if str(item.get("name") or "").strip()
    ]
    if not active_shard_names:
        active_shard_names = [
            str(item.get("_shard") or "").strip()
            for item in active_runs
            if str(item.get("_shard") or "").strip()
        ]
    deduped_active_shard_names = list(dict.fromkeys(active_shard_names))
    shard_count = len(shards) or None
    active_count = len(active_shards)
    if active_count == 0:
        if deduped_active_shard_names:
            active_count = len(deduped_active_shard_names)
        else:
            active_count = len(active_runs)
    mode = str(payload.get("mode") or "unknown").strip() or "unknown"
    updated_at = str(payload.get("updated_at") or "").strip()
    open_milestones = list(payload.get("open_milestone_ids") or [])
    active_run = payload.get("active_run") if isinstance(payload.get("active_run"), dict) else {}
    active_run_id = str(active_run.get("run_id") or "").strip()
    active_names = ", ".join(deduped_active_shard_names)
    status_prefix = f"Live fleet status: {active_count} active shards"
    if shard_count is not None:
        status_prefix += f" out of {shard_count} total"
    status_prefix += f", mode {mode}"
    fragments = [status_prefix]
    if active_names:
        fragments.append(f"active shards {active_names}")
    if active_run_id:
        fragments.append(f"aggregate active run {active_run_id}")
    if open_milestones:
        fragments.append(f"{len(open_milestones)} open milestones")
    if updated_at:
        fragments.append(f"updated {updated_at}")
    return "; ".join(fragments) + "."


def _render_direct_fleet_eta(payload: dict[str, object]) -> str:
    eta_payload = payload.get("eta") if isinstance(payload.get("eta"), dict) else {}
    if not eta_payload:
        return "Fleet ETA is unavailable right now; supervisor state does not include an ETA estimate."
    eta_human = str(eta_payload.get("eta_human") or "").strip()
    predicted_completion_at = str(eta_payload.get("predicted_completion_at") or "").strip()
    eta_confidence = str(eta_payload.get("eta_confidence") or "").strip()
    summary = str(eta_payload.get("summary") or "").strip()
    blocking_reason = str(eta_payload.get("blocking_reason") or "").strip()
    status = str(eta_payload.get("status") or "").strip()
    updated_at = str(payload.get("updated_at") or "").strip()
    fragments = ["Fleet ETA"]
    detail_parts: list[str] = []
    if eta_human:
        detail_parts.append(eta_human)
    if eta_confidence:
        detail_parts.append(f"{eta_confidence} confidence")
    if status and status != "estimated":
        detail_parts.append(status)
    if detail_parts:
        fragments[0] += f": {'; '.join(detail_parts)}"
    else:
        fragments[0] += ": estimated"
    if predicted_completion_at:
        fragments.append(f"predicted completion {predicted_completion_at}")
    if summary:
        fragments.append(summary)
    if blocking_reason:
        fragments.append(f"blocking reason {blocking_reason}")
    if updated_at:
        fragments.append(f"updated {updated_at}")
    return "; ".join(fragments) + "."


def _direct_fleet_runtime_text(prompt: str) -> str | None:
    if not _looks_like_direct_fleet_runtime_query(prompt):
        return None
    payload = _load_direct_fleet_runtime_status_payload()
    if not isinstance(payload, dict):
        return "Live fleet runtime status is unavailable right now; mounted supervisor state could not be loaded."
    return _render_direct_fleet_runtime_status(payload)


def _direct_fleet_eta_text(prompt: str) -> str | None:
    if not _looks_like_direct_fleet_eta_query(prompt):
        return None
    payload = _load_direct_fleet_runtime_status_payload()
    if not isinstance(payload, dict):
        return "Fleet ETA is unavailable right now; mounted supervisor state could not be loaded."
    return _render_direct_fleet_eta(payload)


def _looks_like_coding_task(prompt: str) -> tuple[bool, str]:
    normalized = _trim_prompt_route_fillers(_normalized_prompt_route_text(prompt))
    if not normalized:
        return False, "empty_prompt"
    padded = f" {normalized} "
    coding_prefixes = (
        "fix ",
        "implement ",
        "write ",
        "edit ",
        "refactor ",
        "debug ",
        "patch ",
        "review ",
        "audit ",
        "investigate ",
        "trace ",
        "wire ",
        "add ",
        "remove ",
        "change ",
        "update ",
        "create ",
        "build ",
    )
    coding_keywords = (
        " codebase",
        " repository",
        " file ",
        " files ",
        " function",
        " class ",
        " api ",
        " endpoint",
        " test ",
        " tests",
        " bug",
        " diff",
        " patch",
        " traceback",
        " stack trace",
        " browseract",
        " onemin",
        " codex",
        " provider",
        " routing",
        " shim",
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        "/docker/",
        "/v1/",
        " commit",
        " push",
    )
    if any(marker in normalized for marker in _PROMPT_ROUTE_CODE_MARKERS):
        return True, "coding_task_requires_core"
    if any(normalized.startswith(prefix) for prefix in coding_prefixes):
        return True, "coding_task_requires_core"
    if any(keyword in padded or keyword in normalized for keyword in coding_keywords):
        return True, "coding_task_requires_core"
    return False, "not_coding_task"


def _resolve_prompt_route(
    *,
    prompt: str,
    model: str,
    codex_profile: str | None,
) -> _PromptRouteDecision:
    original_profile = str(codex_profile or "").strip() or None
    original_model = str(model or DEFAULT_PUBLIC_MODEL).strip() or DEFAULT_PUBLIC_MODEL
    normalized_original_profile = str(original_profile or "").strip().lower()
    normalized_original_model = str(original_model or "").strip().lower()
    effective_profile = original_profile
    effective_model = original_model
    applied = False
    reason = "session_route"
    if (
        normalized_original_profile == "core_batch"
        or normalized_original_model == str(HARD_BATCH_PUBLIC_MODEL or "").strip().lower()
    ):
        reason = "explicit_core_batch_profile"
    elif _is_hard_prompt_route_context(model=original_model, codex_profile=codex_profile):
        demote, demote_reason = _looks_like_lightweight_ops_query(prompt)
        if demote:
            effective_profile = "easy"
            effective_model = str(FAST_PUBLIC_MODEL or "").strip() or original_model
            applied = effective_profile != original_profile or effective_model != original_model
            reason = demote_reason
        else:
            reason = demote_reason
    else:
        lightweight_ops, lightweight_reason = _looks_like_lightweight_ops_query(prompt)
        if lightweight_ops:
            effective_profile = "easy"
            if normalized_original_profile in {"", "default", "easy", "repair", "groundwork"}:
                effective_model = str(ONEMIN_PUBLIC_MODEL or "").strip() or original_model
            applied = effective_profile != original_profile or effective_model != original_model
            reason = lightweight_reason
        else:
            coding_task, coding_reason = _looks_like_coding_task(prompt)
            if coding_task and (
                not normalized_original_profile
                or normalized_original_profile in {"default", "easy"}
            ):
                effective_profile = "core"
                effective_model = "ea-coder-hard"
                applied = effective_profile != original_profile or effective_model != original_model
                reason = coding_reason
    trace_profile = str(effective_profile or original_profile or "default")
    trace_line = f"Trace: prompt_route={trace_profile} route_model={effective_model} route_reason={reason}"
    if applied:
        trace_line += (
            f" original_profile={original_profile or 'default'}"
            f" original_model={original_model}"
        )
    trace_line += "\n"
    return _PromptRouteDecision(
        applied=applied,
        reason=reason,
        original_profile=original_profile,
        original_model=original_model,
        effective_profile=effective_profile,
        effective_model=effective_model,
        trace_line=trace_line,
    )


def _json_compact(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    except Exception:
        return str(value)


def _extract_resume_fallback_text(value: object) -> str:
    if isinstance(value, (str, int, float, bool)):
        return str(value).strip()
    if isinstance(value, list):
        parts = [_extract_resume_fallback_text(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    if not isinstance(value, dict):
        return ""
    for key in ("text", "content", "output", "summary", "message", "result", "arguments"):
        text = _extract_textish(value.get(key))
        if text:
            return text
    return ""


def _normalize_passthrough_input_item(item: dict[str, object]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for key in (
        "id",
        "type",
        "call_id",
        "name",
        "status",
        "arguments",
        "output",
        "summary",
        "role",
        "content",
    ):
        if key in item:
            normalized[key] = item.get(key)
    if "type" not in normalized:
        normalized["type"] = str(item.get("type") or "").strip().lower()
    return normalized


def _normalize_message_role(role: object) -> str:
    lowered = str(role or "").strip().lower()
    if lowered in {"developer", "system"}:
        return "system"
    if lowered == "assistant":
        return "assistant"
    return "user"


def _append_message(messages: list[dict[str, str]], *, role: object, content: object) -> None:
    cleaned = str(content or "").strip()
    if not cleaned:
        return
    normalized_role = _normalize_message_role(role)
    if messages and messages[-1]["role"] == normalized_role:
        messages[-1]["content"] = f"{messages[-1]['content']}\n\n{cleaned}".strip()
        return
    messages.append({"role": normalized_role, "content": cleaned})


def _parse_input_parts(content: object, *, item_context: str) -> list[dict[str, object]]:
    parts: list[dict[str, object]] = []
    if isinstance(content, str):
        cleaned = content.strip()
        if cleaned:
            parts.append({"type": "input_text", "text": cleaned})
        return parts

    if not isinstance(content, list):
        raise HTTPException(
            status_code=400,
            detail=f"unsupported_input_content:{item_context}",
        )

    for index, entry in enumerate(content):
        if isinstance(entry, str):
            cleaned = entry.strip()
            if cleaned:
                parts.append({"type": "input_text", "text": cleaned})
            continue
        if not isinstance(entry, dict):
            raise HTTPException(
                status_code=400,
                detail=f"unsupported_input_content:{item_context}[{index}]",
            )

        part_type = str(entry.get("type") or "").strip().lower()
        if part_type in {"text", "output_text"}:
            part_type = "input_text"
        if part_type not in _SUPPORTED_INPUT_PART_TYPES:
            fallback_text = _extract_resume_fallback_text(entry)
            if fallback_text:
                parts.append({"type": "input_text", "text": fallback_text})
                continue
            raise HTTPException(
                status_code=400,
                detail=f"unsupported_input_part_type:{item_context}:{part_type}",
            )

        text = _extract_text(entry.get("text"))
        if text.strip():
            parts.append({"type": "input_text", "text": text.strip()})

    return parts


def _parse_input_payload(raw_input: object | None) -> _ParsedResponseInput:
    messages: list[dict[str, str]] = []
    input_items: list[dict[str, object]] = []
    prompt_parts: list[str] = []

    if isinstance(raw_input, str):
        cleaned = raw_input.strip()
        if cleaned:
            _append_message(messages, role="user", content=cleaned)
            input_items.append({"type": "input_text", "text": cleaned})
            prompt_parts.append(cleaned)
        return _ParsedResponseInput(
            messages=messages,
            input_items=input_items,
            prompt="\n\n".join(prompt_parts).strip(),
        )

    if not isinstance(raw_input, list):
        raise HTTPException(status_code=400, detail="input_invalid")

    for index, item in enumerate(raw_input):
        item_key = f"{index}"

        if isinstance(item, str):
            cleaned = item.strip()
            if cleaned:
                _append_message(messages, role="user", content=cleaned)
                input_items.append({"type": "input_text", "text": cleaned})
                prompt_parts.append(cleaned)
            continue

        if not isinstance(item, dict):
            if item is None:
                continue
            if isinstance(item, (int, float, bool)):
                cleaned = str(item).strip()
                if cleaned:
                    _append_message(messages, role="user", content=cleaned)
                    input_items.append({"type": "input_text", "text": cleaned})
                    prompt_parts.append(cleaned)
                continue
            # Some Responses clients include non-dict state entries during
            # resume/replay that are not actionable for this text-only facade.
            continue

        item_type = str(item.get("type") or "").strip().lower()

        if item_type == "function_call_output":
            call_id = str(item.get("call_id") or "").strip()
            output_text = _extract_textish(item.get("output"))
            if not call_id:
                raise HTTPException(status_code=400, detail=f"invalid_function_call_output:{item_key}")
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": output_text,
                }
            )
            continue

        if item_type == "function_call":
            call_id = str(item.get("call_id") or "").strip()
            name = str(item.get("name") or "").strip()
            arguments = item.get("arguments")
            if not call_id or not name:
                raise HTTPException(status_code=400, detail=f"invalid_function_call:{item_key}")
            if isinstance(arguments, str):
                rendered_arguments = arguments
            else:
                rendered_arguments = _json_compact(arguments)
            input_items.append(
                {
                    "type": "function_call",
                    "call_id": call_id,
                    "name": name,
                    "arguments": rendered_arguments,
                }
            )
            continue

        if item_type == "reasoning":
            input_items.append(_normalize_passthrough_input_item(item))
            summary_text = _extract_textish(item.get("summary"))
            if summary_text:
                _append_message(messages, role="assistant", content=summary_text)
                prompt_parts.append(summary_text)
            continue

        if item_type.endswith("_call") or item_type.endswith("_call_output"):
            input_items.append(_normalize_passthrough_input_item(item))
            continue

        if item_type == "message":
            role = _normalize_message_role(item.get("role"))
            parts = _parse_input_parts(item.get("content"), item_context=f"message[{item_key}].content")
            if not parts:
                continue
            text = "\n\n".join(part["text"] for part in parts if str(part.get("text") or "").strip())
            _append_message(messages, role=role, content=text)
            input_items.append({"type": "message", "role": role, "content": parts})
            prompt_parts.append(text)
            continue

        if item_type in {"input_text", "text"}:
            text = _extract_text(item.get("text"))
            cleaned = text.strip()
            if not cleaned:
                continue
            _append_message(messages, role="user", content=cleaned)
            input_items.append({"type": "input_text", "text": cleaned})
            prompt_parts.append(cleaned)
            continue

        if "role" in item or "content" in item:
            role = _normalize_message_role(item.get("role"))
            parts = _parse_input_parts(item.get("content"), item_context=f"item[{item_key}].content")
            if not parts:
                continue
            text = "\n\n".join(part["text"] for part in parts if str(part.get("text") or "").strip())
            _append_message(messages, role=role, content=text)
            input_items.append({"type": "message", "role": role, "content": parts})
            prompt_parts.append(text)
            continue

        fallback_text = _extract_resume_fallback_text(
            item.get("text")
            or item.get("content")
            or item.get("output")
            or item.get("summary")
            or item.get("arguments")
        )
        if fallback_text:
            _append_message(messages, role="user", content=fallback_text)
            input_items.append({"type": "input_text", "text": fallback_text})
            prompt_parts.append(fallback_text)
            continue

        # Some Responses clients send non-text state items during resume that
        # are not actionable for this text-only compatibility layer.
        if item_type:
            raise HTTPException(status_code=400, detail=f"unsupported_input_item:{item_key}")
        continue

    return _ParsedResponseInput(
        messages=messages,
        input_items=input_items,
        prompt="\n\n".join(prompt_parts).strip(),
    )


def _parse_create_request(payload: dict[str, object]) -> tuple[_ResponsesCreateRequest, _ParsedResponseInput]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid_request")

    normalized_payload = dict(payload)
    known_fields = set(_ResponsesCreateRequest.model_fields)
    unknown_fields = [field for field in normalized_payload.keys() if field not in known_fields]
    legacy_compat_fields = {"client_metadata"}
    rejected_fields = [field for field in unknown_fields if field not in legacy_compat_fields]
    if rejected_fields:
        raise HTTPException(status_code=400, detail=f"unsupported_fields:{','.join(rejected_fields)}")
    for field in unknown_fields:
        normalized_payload.pop(field, None)

    try:
        request = _ResponsesCreateRequest.model_validate(normalized_payload)
    except ValidationError as exc:
        extra_fields = [
            ".".join(str(part) for part in error.get("loc", ()))
            for error in exc.errors()
            if error.get("type") == "extra_forbidden"
        ]
        if extra_fields:
            raise HTTPException(status_code=400, detail=f"unsupported_fields:{','.join(extra_fields)}") from exc
        raise HTTPException(status_code=400, detail="invalid_request") from exc

    parsed_input = _parse_input_payload(request.input)

    if not parsed_input.input_items:
        raise HTTPException(status_code=400, detail="input_required")

    return request, parsed_input


def _metadata(payload: _ResponsesCreateRequest) -> dict[str, object]:
    raw = payload.metadata
    if isinstance(raw, dict):
        return {str(k): v for k, v in raw.items()}
    return {}


def _accepted_client_fields(payload: _ResponsesCreateRequest) -> list[str]:
    accepted: list[str] = []
    if payload.text is not None:
        accepted.append("text")
    if payload.reasoning is not None:
        accepted.append("reasoning")
    if payload.include:
        accepted.append("include")
    if payload.service_tier:
        accepted.append("service_tier")
    if payload.prompt_cache_key:
        accepted.append("prompt_cache_key")
    return accepted


def _rejected_client_fields(
    payload: _ResponsesCreateRequest,
    *,
    codex_profile: str | None = None,
) -> list[str]:
    # Normalized provider contract rejects Codex compatibility fields on the
    # generic /v1/responses surface.
    if codex_profile:
        return []
    rejected: list[str] = []
    if payload.store is not None:
        rejected.append("store")
    if payload.tools is not None:
        rejected.append("tools")
    if payload.tool_choice is not None:
        rejected.append("tool_choice")
    if payload.parallel_tool_calls is not None:
        rejected.append("parallel_tool_calls")
    if _requested_previous_response_id(payload):
        rejected.append("previous_response_id")
    return rejected


def _should_store_response(payload: _ResponsesCreateRequest) -> bool:
    return payload.store is not False


def _brain_router(container: object | None = None) -> BrainRouterService | None:
    router = getattr(container, "brain_router", None)
    return router if isinstance(router, BrainRouterService) else None


def _provider_registry_payload(
    *,
    container: object | None = None,
    principal_id: str = "",
    provider_health: dict[str, object] | None = None,
    include_sensitive: bool = False,
) -> dict[str, object]:
    registry = getattr(container, "provider_registry", None)
    if registry is None or not hasattr(registry, "registry_read_model"):
        return {}
    router = _brain_router(container)
    profile_decisions = router.list_profile_decisions(principal_id=principal_id or None) if router is not None else ()
    payload = registry.registry_read_model(
        principal_id=principal_id or None,
        provider_health=provider_health or {},
        profile_decisions=profile_decisions,
    )
    if include_sensitive:
        return payload
    providers = []
    for provider in list(payload.get("providers") or []):
        row = dict(provider or {})
        slot_pool = dict(row.get("slot_pool") or {})
        slot_pool["owners"] = []
        slot_pool["lease_holders"] = []
        slot_pool["last_used_principal_id"] = ""
        slot_pool["last_used_principal_label"] = ""
        slot_pool["last_used_owner_category"] = ""
        slot_pool["last_used_lane_role"] = ""
        slot_pool["last_used_hub_user_id"] = ""
        slot_pool["last_used_hub_group_id"] = ""
        slot_pool["last_used_sponsor_session_id"] = ""
        slot_pool["last_used_at"] = None
        row["slot_pool"] = slot_pool
        row["last_used_principal_id"] = ""
        row["last_used_principal_label"] = ""
        row["last_used_owner_category"] = ""
        row["last_used_lane_role"] = ""
        row["last_used_hub_user_id"] = ""
        row["last_used_hub_group_id"] = ""
        row["last_used_sponsor_session_id"] = ""
        row["last_used_at"] = None
        providers.append(row)
    lanes = []
    for lane in list(payload.get("lanes") or []):
        row = dict(lane or {})
        capacity = dict(row.get("capacity_summary") or {})
        capacity["slot_owners"] = []
        capacity["lease_holders"] = []
        capacity["last_used_principal_id"] = ""
        capacity["last_used_principal_label"] = ""
        capacity["last_used_owner_category"] = ""
        capacity["last_used_lane_role"] = ""
        capacity["last_used_hub_user_id"] = ""
        capacity["last_used_hub_group_id"] = ""
        capacity["last_used_sponsor_session_id"] = ""
        capacity["last_used_at"] = None
        row["capacity_summary"] = capacity
        row["last_used_principal_id"] = ""
        row["last_used_principal_label"] = ""
        row["last_used_owner_category"] = ""
        row["last_used_lane_role"] = ""
        row["last_used_hub_user_id"] = ""
        row["last_used_hub_group_id"] = ""
        row["last_used_sponsor_session_id"] = ""
        row["last_used_at"] = None
        lanes.append(row)
    return {
        **payload,
        "providers": providers,
        "lanes": lanes,
    }


def _codex_profiles(
    *,
    container: object | None = None,
    principal_id: str = "",
    provider_health: dict[str, object] | None = None,
) -> tuple[dict[str, object], ...]:
    router = _brain_router(container)
    if router is None:
        return tuple(
            _stabilize_codex_profile(_enrich_codex_profile(dict(item)), provider_health=provider_health)
            for item in _CODEx_PROFILES
        )
    rows = []
    for profile in router.list_profile_decisions(principal_id=principal_id or None):
        rows.append(
            _stabilize_codex_profile(
                _enrich_codex_profile(
                {
                "profile": profile.profile,
                "lane": profile.lane,
                "model": profile.public_model,
                "provider_hint_order": profile.provider_hint_order,
                "backend": profile.backend_key,
                "health_provider_key": profile.health_provider_key,
                "review_required": bool(profile.review_required),
                "needs_review": bool(profile.needs_review),
                "risk_labels": list(profile.risk_labels),
                "merge_policy": str(profile.merge_policy or "auto"),
                }
                ),
                provider_health=provider_health,
            )
        )
    if rows:
        return tuple(rows)
    return tuple(
        _stabilize_codex_profile(_enrich_codex_profile(dict(item)), provider_health=provider_health)
        for item in _CODEx_PROFILES
    )


def _codex_profile(
    profile: str,
    *,
    container: object | None = None,
    principal_id: str = "",
    provider_health: dict[str, object] | None = None,
) -> dict[str, object]:
    for item in _codex_profiles(container=container, principal_id=principal_id, provider_health=provider_health):
        if item["profile"] == profile:
            return dict(item)
    return _stabilize_codex_profile(_enrich_codex_profile(
        {
        "profile": profile,
        "lane": "default",
        "model": DEFAULT_PUBLIC_MODEL,
        "provider_hint_order": tuple(_provider_order()) if profile else (),
        "backend": "",
        "health_provider_key": "",
        "review_required": False,
        "needs_review": False,
        }
    ), provider_health=provider_health)


def _attach_provider_slot_state(
    profiles: list[dict[str, object]],
    *,
    provider_health: dict[str, object],
    include_sensitive: bool = False,
) -> list[dict[str, object]]:
    gemini = dict(((provider_health or {}).get("providers") or {}).get("gemini_vortex") or {})
    gemini_slots = [
        {
            "slot": item.get("slot"),
            "account_name": item.get("account_name"),
            "state": item.get("state"),
            "slot_owner": item.get("slot_owner") if include_sensitive else "",
            "lease_holder": item.get("lease_holder") if include_sensitive else "",
            "lease_holder_label": item.get("lease_holder_label") if include_sensitive else "",
            "lease_holder_owner_category": item.get("lease_holder_owner_category") if include_sensitive else "",
            "lease_holder_lane_role": item.get("lease_holder_lane_role") if include_sensitive else "",
            "lease_holder_hub_user_id": item.get("lease_holder_hub_user_id") if include_sensitive else "",
            "lease_holder_hub_group_id": item.get("lease_holder_hub_group_id") if include_sensitive else "",
            "lease_holder_sponsor_session_id": item.get("lease_holder_sponsor_session_id") if include_sensitive else "",
            "lease_expires_at": item.get("lease_expires_at"),
            "last_used_principal_id": item.get("last_used_principal_id") if include_sensitive else "",
            "last_used_principal_label": item.get("last_used_principal_label") if include_sensitive else "",
            "last_used_owner_category": item.get("last_used_owner_category") if include_sensitive else "",
            "last_used_lane_role": item.get("last_used_lane_role") if include_sensitive else "",
            "last_used_hub_user_id": item.get("last_used_hub_user_id") if include_sensitive else "",
            "last_used_hub_group_id": item.get("last_used_hub_group_id") if include_sensitive else "",
            "last_used_sponsor_session_id": item.get("last_used_sponsor_session_id") if include_sensitive else "",
            "last_used_at": item.get("last_used_at") if include_sensitive else None,
            "quota_posture": item.get("quota_posture"),
        }
        for item in gemini.get("slots") or []
        if isinstance(item, dict)
    ]
    if not gemini_slots:
        return profiles
    selection_mode = str(gemini.get("selection_mode") or "")
    configured_slots = int(gemini.get("configured_slots") or len(gemini_slots))
    enriched: list[dict[str, object]] = []
    for profile in profiles:
        hints = [str(item or "").strip() for item in profile.get("provider_hint_order") or [] if str(item or "").strip()]
        if "gemini_vortex" not in hints:
            enriched.append(profile)
            continue
        enriched.append(
            {
                **profile,
                "provider_slots": gemini_slots,
                "provider_slot_pool": {
                    "provider_key": "gemini_vortex",
                    "selection_mode": selection_mode,
                    "configured_slots": configured_slots,
                    "active_lease_count": int(gemini.get("active_lease_count") or 0),
                    "last_used_principal_id": gemini.get("last_used_principal_id") if include_sensitive else "",
                    "last_used_principal_label": gemini.get("last_used_principal_label") if include_sensitive else "",
                    "last_used_owner_category": gemini.get("last_used_owner_category") if include_sensitive else "",
                    "last_used_lane_role": gemini.get("last_used_lane_role") if include_sensitive else "",
                    "last_used_hub_user_id": gemini.get("last_used_hub_user_id") if include_sensitive else "",
                    "last_used_hub_group_id": gemini.get("last_used_hub_group_id") if include_sensitive else "",
                    "last_used_sponsor_session_id": gemini.get("last_used_sponsor_session_id") if include_sensitive else "",
                    "last_used_at": gemini.get("last_used_at") if include_sensitive else None,
                },
            }
        )
    return enriched


def _redacted_provider_health(provider_health: dict[str, object], *, include_sensitive: bool) -> dict[str, object]:
    if include_sensitive:
        return provider_health
    payload = dict(provider_health or {})
    providers = {}
    for provider_key, provider in dict(payload.get("providers") or {}).items():
        row = dict(provider or {})
        redacted_slots = []
        for item in list(row.get("slots") or []):
            if not isinstance(item, dict):
                continue
            slot = dict(item)
            slot["account_name"] = ""
            slot["slot_owner"] = ""
            slot["owner_label"] = ""
            slot["owner_name"] = ""
            slot["owner_email"] = ""
            slot["lease_holder"] = ""
            slot["lease_holder_label"] = ""
            slot["lease_holder_owner_category"] = ""
            slot["lease_holder_lane_role"] = ""
            slot["lease_holder_hub_user_id"] = ""
            slot["lease_holder_hub_group_id"] = ""
            slot["lease_holder_sponsor_session_id"] = ""
            slot["last_used_principal_id"] = ""
            slot["last_used_principal_label"] = ""
            slot["last_used_owner_category"] = ""
            slot["last_used_lane_role"] = ""
            slot["last_used_hub_user_id"] = ""
            slot["last_used_hub_group_id"] = ""
            slot["last_used_sponsor_session_id"] = ""
            slot["last_used_at"] = None
            redacted_slots.append(slot)
        row["slots"] = redacted_slots
        row["account_name"] = ""
        row["last_used_principal_id"] = ""
        row["last_used_principal_label"] = ""
        row["last_used_owner_category"] = ""
        row["last_used_lane_role"] = ""
        row["last_used_hub_user_id"] = ""
        row["last_used_hub_group_id"] = ""
        row["last_used_sponsor_session_id"] = ""
        row["last_used_at"] = None
        providers[provider_key] = row
    payload["providers"] = providers
    provider_config = dict(payload.get("provider_config") or {})
    for key in (
        "onemin_accounts",
        "onemin_active_accounts",
        "onemin_reserve_accounts",
        "chatplayground_accounts",
        "gemini_vortex_accounts",
        "magixai_accounts",
    ):
        if key in provider_config:
            provider_config[key] = []
    payload["provider_config"] = provider_config
    return payload


def _normalize_payload_for_profile(
    payload: dict[str, object],
    *,
    profile: str,
    container: object | None = None,
    principal_id: str = "",
) -> dict[str, object]:
    profile_config = _codex_profile(
        profile,
        container=container,
        principal_id=principal_id,
        provider_health=_provider_health_snapshot(lightweight=True),
    )
    normalized = dict(payload)
    normalized["model"] = str(profile_config["model"])
    return normalized


def _requested_model(payload: _ResponsesCreateRequest) -> str:
    model = payload.model
    if isinstance(model, str):
        return model.strip()
    return ""


def _requested_previous_response_id(payload: _ResponsesCreateRequest) -> str | None:
    value = str(getattr(payload, "previous_response_id", "") or "").strip()
    return value or None


def _requested_max_output_tokens(payload: _ResponsesCreateRequest) -> int | None:
    raw = payload.max_output_tokens
    if raw is None:
        return None
    try:
        value = int(raw)
    except Exception:
        raise HTTPException(status_code=400, detail="max_output_tokens_invalid")
    if value <= 0:
        raise HTTPException(status_code=400, detail="max_output_tokens_invalid")
    return value


def _requested_max_output_tokens_from_response(response_obj: dict[str, object]) -> int | None:
    raw = response_obj.get("max_output_tokens")
    if raw is None:
        return None
    try:
        value = int(raw)
    except Exception:
        return None
    return value if value > 0 else None


def _browseract_binding_id(*, container: object | None, principal_id: str) -> str:
    if container is None or not principal_id:
        return ""
    tool_runtime = getattr(container, "tool_runtime", None)
    if tool_runtime is None:
        return ""
    try:
        bindings = tool_runtime.list_connector_bindings(principal_id, limit=100)
    except Exception:
        return ""
    for binding in bindings:
        connector_name = str(getattr(binding, "connector_name", "") or "").strip().lower()
        status = str(getattr(binding, "status", "") or "").strip().lower()
        if connector_name != "browseract":
            continue
        if status and status != "enabled":
            continue
        return str(getattr(binding, "binding_id", "") or "").strip()
    return ""


def _build_chatplayground_audit_callback(
    *,
    container: object | None,
    principal_id: str,
) -> Callable[..., Any] | None:
    if container is None:
        return None
    browseract_binding_id = _browseract_binding_id(container=container, principal_id=principal_id)

    def _chatplayground_audit_callback(**kwargs: Any) -> Any:
        prompt = str(kwargs.get("prompt") or "").strip()
        if not prompt:
            raise RuntimeError("chatplayground_audit_prompt_required")
        tool_execution = getattr(container, "tool_execution", None)
        if tool_execution is None:
            raise RuntimeError("chatplayground_tool_execution_unavailable")
        invocation = ToolInvocationRequest(
            session_id=f"codex-audit:{uuid.uuid4().hex}",
            step_id=f"codex-audit-step:{uuid.uuid4().hex}",
            tool_name="browseract.chatplayground_audit",
            action_kind="chatplayground_audit",
            payload_json={
                **dict(kwargs),
                "binding_id": str(kwargs.get("binding_id") or browseract_binding_id or "").strip(),
            },
            context_json={"principal_id": principal_id},
        )
        try:
            result = tool_execution.execute_invocation(invocation)
        except ToolExecutionError as exc:
            raise RuntimeError(str(exc)) from exc
        return result.output_json

    return _chatplayground_audit_callback


def _response_object(
    *,
    response_id: str,
    model: str,
    created_at: int,
    status: str,
    output: list[dict[str, object]] | None = None,
    output_text: str = "",
    tokens_in: int = 0,
    tokens_out: int = 0,
    max_output_tokens: int | None = None,
    metadata: dict[str, object] | None = None,
    instructions: str | None = None,
    error: dict[str, object] | None = None,
    incomplete_details: dict[str, object] | None = None,
    input_items: list[dict[str, object]] | None = None,
    reasoning: Any | None = None,
) -> dict[str, object]:
    completed_at = created_at if status == "completed" else None
    usage = _ResponseUsage(
        input_tokens=int(tokens_in or 0),
        output_tokens=int(tokens_out or 0),
        total_tokens=int((tokens_in or 0) + (tokens_out or 0)),
    )
    response_obj = _ResponseObject(
        id=response_id,
        created_at=created_at,
        status=status,
        completed_at=completed_at,
        error=error,
        incomplete_details=incomplete_details,
        instructions=instructions,
        input=list(input_items or []),
        max_output_tokens=max_output_tokens,
        model=model or "",
        output=list(output or []),
        usage=usage,
        metadata=dict(metadata or {}),
        output_text=output_text,
        reasoning=reasoning,
        truncation="disabled",
    )
    return response_obj.model_dump(mode="json")


def _message_item(*, item_id: str, text: str, status: str) -> dict[str, object]:
    return _ResponseOutputMessage(
        id=item_id,
        status=status,
        content=[_ResponseOutputTextPart(text=text)],
    ).model_dump(mode="json")


def _completed_text_response(
    *,
    request: _ResponsesCreateRequest,
    response_id: str,
    item_id: str,
    model: str,
    created_at: int,
    text: str,
    metadata: dict[str, object],
    instructions: str | None,
    input_items: list[dict[str, object]],
    history_items: list[dict[str, object]],
    principal_id: str,
    container: object | None,
    reasoning: Any | None,
    max_output_tokens: int | None,
    prompt_route_trace_line: str = "",
) -> Response:
    final_item = _message_item(item_id=item_id, text=text, status="completed")
    response_obj = _response_object(
        response_id=response_id,
        model=model,
        created_at=created_at,
        status="completed",
        output=[final_item],
        output_text=text,
        tokens_in=0,
        tokens_out=0,
        max_output_tokens=max_output_tokens,
        metadata=metadata,
        instructions=instructions,
        input_items=input_items,
        reasoning=reasoning,
    )
    if _should_store_response(request):
        _store_response(
            response_id=response_id,
            response_obj=response_obj,
            input_items=input_items,
            history_items=list(history_items) + [final_item],
            principal_id=principal_id,
            container=container,
        )
    if not request.stream:
        return JSONResponse(response_obj)

    in_progress_obj = _response_object(
        response_id=response_id,
        model=model,
        created_at=created_at,
        status="in_progress",
        output=[],
        output_text="",
        tokens_in=0,
        tokens_out=0,
        max_output_tokens=max_output_tokens,
        metadata=metadata,
        instructions=instructions,
        input_items=input_items,
        reasoning=reasoning,
    )

    def event_stream() -> Iterable[str]:
        sequence = 0

        def _next_sequence() -> int:
            nonlocal sequence
            sequence += 1
            return sequence

        empty_item = _message_item(item_id=item_id, text="", status="in_progress")
        yield _sse_event(
            event="response.created",
            sequence=_next_sequence(),
            data={"type": "response.created", "response": in_progress_obj},
        )
        yield _sse_event(
            event="response.in_progress",
            sequence=_next_sequence(),
            data={"type": "response.in_progress", "response": in_progress_obj},
        )
        yield _sse_event(
            event="response.output_item.added",
            sequence=_next_sequence(),
            data={"type": "response.output_item.added", "output_index": 0, "item": empty_item},
        )
        yield _sse_event(
            event="response.content_part.added",
            sequence=_next_sequence(),
            data={
                "type": "response.content_part.added",
                "output_index": 0,
                "item_id": item_id,
                "content_index": 0,
                "part": {"type": "output_text", "text": "", "annotations": []},
            },
        )
        if prompt_route_trace_line:
            yield _sse_event(
                event="response.output_text.delta",
                sequence=_next_sequence(),
                data={
                    "type": "response.output_text.delta",
                    "output_index": 0,
                    "item_id": item_id,
                    "content_index": 0,
                    "delta": prompt_route_trace_line,
                },
            )
        if text:
            yield _sse_event(
                event="response.output_text.delta",
                sequence=_next_sequence(),
                data={
                    "type": "response.output_text.delta",
                    "output_index": 0,
                    "item_id": item_id,
                    "content_index": 0,
                    "delta": text,
                },
            )
        yield _sse_event(
            event="response.output_text.done",
            sequence=_next_sequence(),
            data={
                "type": "response.output_text.done",
                "output_index": 0,
                "item_id": item_id,
                "content_index": 0,
                "text": text,
            },
        )
        yield _sse_event(
            event="response.content_part.done",
            sequence=_next_sequence(),
            data={
                "type": "response.content_part.done",
                "output_index": 0,
                "item_id": item_id,
                "content_index": 0,
                "part": {"type": "output_text", "text": text, "annotations": []},
            },
        )
        yield _sse_event(
            event="response.output_item.done",
            sequence=_next_sequence(),
            data={"type": "response.output_item.done", "output_index": 0, "item": final_item},
        )
        yield _sse_event(
            event="response.completed",
            sequence=_next_sequence(),
            data={"type": "response.completed", "response": response_obj},
        )
        yield _sse_event(
            event="response.done",
            sequence=_next_sequence(),
            data={"type": "response.done", "response": response_obj},
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _function_call_item(
    *,
    item_id: str,
    call_id: str,
    name: str,
    arguments: str,
    status: str,
) -> dict[str, object]:
    return _ResponseOutputFunctionCall(
        id=item_id,
        call_id=call_id,
        name=name,
        arguments=arguments,
        status=status,
    ).model_dump(mode="json")


def _container_database_url(container: object | None) -> str:
    if container is None:
        return ""
    settings = getattr(container, "settings", None)
    if settings is None:
        return ""
    direct = str(getattr(settings, "database_url", "") or "").strip()
    if direct:
        return direct
    storage = getattr(settings, "storage", None)
    if storage is None:
        return ""
    return str(getattr(storage, "database_url", "") or "").strip()


def _response_record_repository(container: object | None) -> _ResponseRecordRepository:
    backend = "memory"
    database_url = ""
    if container is not None:
        runtime_profile = getattr(container, "runtime_profile", None)
        backend = str(getattr(runtime_profile, "storage_backend", "memory") or "memory").strip().lower() or "memory"
        database_url = _container_database_url(container)
    else:
        backend = str(
            os.environ.get("EA_STORAGE_BACKEND")
            or os.environ.get("EA_LEDGER_BACKEND")
            or "memory"
        ).strip().lower() or "memory"
        database_url = str(os.environ.get("DATABASE_URL") or "").strip()

    if backend == "postgres" and database_url:
        with _RESPONSE_REPOSITORY_LOCK:
            repository = _POSTGRES_RESPONSE_REPOSITORIES.get(database_url)
            if repository is None:
                repository = _PostgresResponseRecordRepository(database_url)
                _POSTGRES_RESPONSE_REPOSITORIES[database_url] = repository
        return repository
    return _MEMORY_RESPONSE_REPOSITORY


def _store_response(
    *,
    response_id: str,
    response_obj: dict[str, object],
    input_items: list[dict[str, object]],
    history_items: list[dict[str, object]],
    principal_id: str,
    container: object | None = None,
    background_job: dict[str, object] | None = None,
) -> None:
    _response_record_repository(container).store(
        response_id=response_id,
        response_obj=response_obj,
        input_items=input_items,
        history_items=history_items,
        principal_id=principal_id,
        background_job=background_job,
    )


def _load_response(
    *,
    response_id: str,
    principal_id: str,
    container: object | None = None,
) -> _StoredResponse:
    return _response_record_repository(container).load(
        response_id=response_id,
        principal_id=principal_id,
    )


def _cleanup_background_response_workers() -> None:
    with _BACKGROUND_RESPONSE_LOCK:
        stale_ids = [response_id for response_id, worker in _BACKGROUND_RESPONSE_WORKERS.items() if not worker.is_alive()]
        for response_id in stale_ids:
            _BACKGROUND_RESPONSE_WORKERS.pop(response_id, None)
            _BACKGROUND_RESPONSE_STARTING.discard(response_id)


def _background_response_has_live_worker(response_id: str) -> bool:
    _cleanup_background_response_workers()
    with _BACKGROUND_RESPONSE_LOCK:
        if response_id in _BACKGROUND_RESPONSE_STARTING:
            return True
        worker = _BACKGROUND_RESPONSE_WORKERS.get(response_id)
        return bool(worker and worker.is_alive())


def _claim_background_response_worker_slot(response_id: str) -> bool:
    _cleanup_background_response_workers()
    with _BACKGROUND_RESPONSE_LOCK:
        if response_id in _BACKGROUND_RESPONSE_STARTING:
            return False
        worker = _BACKGROUND_RESPONSE_WORKERS.get(response_id)
        if worker and worker.is_alive():
            return False
        _BACKGROUND_RESPONSE_STARTING.add(response_id)
        return True


def _register_background_response_worker(response_id: str, worker: threading.Thread) -> None:
    with _BACKGROUND_RESPONSE_LOCK:
        _BACKGROUND_RESPONSE_STARTING.discard(response_id)
        _BACKGROUND_RESPONSE_WORKERS[response_id] = worker


def _release_background_response_worker_slot(response_id: str, *, worker: threading.Thread | None = None) -> None:
    with _BACKGROUND_RESPONSE_LOCK:
        _BACKGROUND_RESPONSE_STARTING.discard(response_id)
        existing = _BACKGROUND_RESPONSE_WORKERS.get(response_id)
        if existing is None:
            return
        if worker is None or existing is worker or not existing.is_alive():
            _BACKGROUND_RESPONSE_WORKERS.pop(response_id, None)


def _background_timeout_seconds_for_response(response_obj: dict[str, object]) -> float:
    metadata = dict(response_obj.get("metadata") or {}) if isinstance(response_obj.get("metadata"), dict) else {}
    raw = metadata.get("background_timeout_seconds")
    try:
        return max(float(raw), 0.0)
    except Exception:
        return 0.0


def _background_response_deadline_unix(response_obj: dict[str, object]) -> float:
    timeout_seconds = _background_timeout_seconds_for_response(response_obj)
    created_at = int(response_obj.get("created_at") or 0)
    if timeout_seconds <= 0 or created_at <= 0:
        return 0.0
    return float(created_at) + timeout_seconds


def _background_response_has_expired(response_obj: dict[str, object], *, now_unix: float | None = None) -> bool:
    deadline_unix = _background_response_deadline_unix(response_obj)
    if deadline_unix <= 0:
        return False
    current = float(now_unix if now_unix is not None else time.time())
    return current >= deadline_unix


def _background_replay_payload(
    *,
    prompt: str,
    messages: list[dict[str, str]],
    supported_tools: list[dict[str, object]],
    effective_codex_profile: str | None,
    chatplayground_audit_callback_enabled: bool,
    chatplayground_audit_callback_only: bool,
    preferred_onemin_labels: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "prompt": str(prompt or ""),
        "messages": [dict(item) for item in messages],
        "supported_tools": [dict(item) for item in supported_tools],
        "effective_codex_profile": str(effective_codex_profile or "").strip(),
        "chatplayground_audit_callback_enabled": bool(chatplayground_audit_callback_enabled),
        "chatplayground_audit_callback_only": bool(chatplayground_audit_callback_only),
        "preferred_onemin_labels": [str(item or "").strip() for item in preferred_onemin_labels if str(item or "").strip()],
    }


def _preferred_onemin_labels_from_request(request: Request) -> tuple[str, ...]:
    labels: list[str] = []
    for header_name in (
        "X-EA-Onemin-Account-Alias",
        "X-EA-Onemin-Account-Env",
        "X-EA-Onemin-Account",
        "X-EA-Onemin-Preferred-Accounts",
    ):
        raw = str(request.headers.get(header_name) or "").strip()
        if not raw:
            continue
        for part in raw.replace(";", ",").split(","):
            label = str(part or "").strip()
            if label and label not in labels:
                labels.append(label)
    return tuple(labels)


def _background_failed_response(
    *,
    stored: _StoredResponse,
    failure_message: str,
) -> dict[str, object]:
    response_obj = dict(stored.response)
    return _build_failed_response(
        response_id=str(response_obj.get("id") or ""),
        created_at=int(response_obj.get("created_at") or _now_unix()),
        model=str(response_obj.get("model") or DEFAULT_PUBLIC_MODEL),
        requested_max_output_tokens=_requested_max_output_tokens_from_response(response_obj),
        metadata=dict(response_obj.get("metadata") or {}) if isinstance(response_obj.get("metadata"), dict) else {},
        instructions=response_obj.get("instructions") if isinstance(response_obj.get("instructions"), str) else None,
        input_items=[dict(item) for item in stored.input_items],
        failure_message=failure_message,
        visible_text=f"Error: {failure_message}",
    )


def _background_timeout_failure_message(response_obj: dict[str, object]) -> str:
    timeout_seconds = int(round(_background_timeout_seconds_for_response(response_obj))) or 0
    return f"background_timeout:{timeout_seconds}s" if timeout_seconds > 0 else "background_timeout"


def _store_background_terminal_response(
    *,
    response_id: str,
    principal_id: str,
    container: object | None,
    response_obj: dict[str, object],
    input_items: list[dict[str, object]],
    history_items: list[dict[str, object]],
    background_job: dict[str, object] | None,
) -> dict[str, object]:
    with _BACKGROUND_RESPONSE_TRANSITION_LOCK:
        stored = _load_response(response_id=response_id, principal_id=principal_id, container=container)
        current_response = dict(stored.response)
        current_status = str(current_response.get("status") or "").strip().lower()
        if current_status != "in_progress":
            return current_response
        if _background_response_has_expired(current_response):
            failed_obj = _background_failed_response(
                stored=stored,
                failure_message=_background_timeout_failure_message(current_response),
            )
            _store_response(
                response_id=response_id,
                response_obj=failed_obj,
                input_items=stored.input_items,
                history_items=stored.history_items,
                principal_id=principal_id,
                container=container,
                background_job=background_job,
            )
            return failed_obj
        _store_response(
            response_id=response_id,
            response_obj=response_obj,
            input_items=input_items,
            history_items=history_items,
            principal_id=principal_id,
            container=container,
            background_job=background_job,
        )
        return response_obj


def _spawn_background_codex_worker(
    *,
    response_id: str,
    created_at: int,
    model: str,
    response_metadata: dict[str, object],
    instructions: str | None,
    input_items: list[dict[str, object]],
    reasoning: Any | None,
    max_output_tokens: int | None,
    history_items: list[dict[str, object]],
    prompt: str,
    messages: list[dict[str, str]],
    supported_tools: list[dict[str, object]],
    chatplayground_audit_callback: Callable[..., Any] | None,
    chatplayground_audit_callback_only: bool,
    chatplayground_audit_principal_id: str,
    preferred_onemin_labels: tuple[str, ...],
    principal_id: str,
    container: object | None,
    background_job: dict[str, object] | None,
) -> bool:
    if not _claim_background_response_worker_slot(response_id):
        return False

    def _worker() -> None:
        request_deadline_monotonic = time.monotonic() + _background_timeout_seconds_for_response(
            {"created_at": created_at, "metadata": response_metadata}
        )
        try:
            tool_decision: _ToolShimDecision | None = None
            if supported_tools:
                decision = _tool_shim_decision(
                    model=model,
                    max_output_tokens=max_output_tokens,
                    instructions=instructions,
                    tools=supported_tools,
                    history_items=history_items,
                    chatplayground_audit_callback=chatplayground_audit_callback,
                    chatplayground_audit_callback_only=chatplayground_audit_callback_only,
                    chatplayground_audit_principal_id=chatplayground_audit_principal_id,
                    request_deadline_monotonic=request_deadline_monotonic,
                )
                if not isinstance(decision, _ToolShimDecision) or not isinstance(decision.upstream_result, UpstreamResult):
                    raise RuntimeError("invalid_upstream_result")
                tool_decision = decision
                result = decision.upstream_result
            else:
                result = _generate_upstream_text(
                    prompt=prompt,
                    messages=messages,
                    requested_model=model,
                    max_output_tokens=max_output_tokens,
                    chatplayground_audit_callback=chatplayground_audit_callback,
                    chatplayground_audit_callback_only=chatplayground_audit_callback_only,
                    chatplayground_audit_principal_id=chatplayground_audit_principal_id,
                    preferred_onemin_labels=preferred_onemin_labels,
                    request_deadline_monotonic=request_deadline_monotonic,
                )
            completed_obj, history_items_to_store = _build_completed_response_from_upstream(
                response_id=response_id,
                created_at=created_at,
                model=model,
                requested_max_output_tokens=max_output_tokens,
                metadata=response_metadata,
                instructions=instructions,
                input_items=input_items,
                reasoning=reasoning,
                base_history_items=history_items,
                result=result,
                tool_decision=tool_decision,
            )
            final_obj = _store_background_terminal_response(
                response_id=response_id,
                response_obj=completed_obj,
                input_items=input_items,
                history_items=history_items_to_store,
                principal_id=principal_id,
                container=container,
                background_job=background_job,
            )
            if str(final_obj.get("status") or "").strip().lower() == "completed":
                _capture_responses_debug(
                    name="response",
                    payload={
                        "principal_id": principal_id,
                        "codex_profile": str(response_metadata.get("codex_effective_profile") or response_metadata.get("codex_profile") or ""),
                        "response": final_obj,
                    },
                )
        except Exception as exc:
            failure_message = str(exc)[:500]
            failed_obj = _build_failed_response(
                response_id=response_id,
                created_at=created_at,
                model=model,
                requested_max_output_tokens=max_output_tokens,
                metadata=response_metadata,
                instructions=instructions,
                input_items=input_items,
                failure_message=failure_message,
                visible_text=f"Error: {failure_message}",
            )
            final_obj = _store_background_terminal_response(
                response_id=response_id,
                response_obj=failed_obj,
                input_items=input_items,
                history_items=history_items,
                principal_id=principal_id,
                container=container,
                background_job=background_job,
            )
            if str(final_obj.get("status") or "").strip().lower() == "failed":
                _capture_responses_debug(
                    name="response_background_failed",
                    payload={
                        "principal_id": principal_id,
                        "codex_profile": str(response_metadata.get("codex_effective_profile") or response_metadata.get("codex_profile") or ""),
                        "response_id": response_id,
                        "failure_message": _response_failure_message(final_obj) or failure_message,
                    },
                )
        finally:
            _release_background_response_worker_slot(response_id)

    worker = threading.Thread(target=_worker, daemon=True)
    try:
        _register_background_response_worker(response_id, worker)
        worker.start()
    except Exception:
        _release_background_response_worker_slot(response_id)
        raise
    return True


def _ensure_background_response_progress(
    *,
    stored: _StoredResponse,
    principal_id: str,
    container: object | None,
) -> _StoredResponse:
    with _BACKGROUND_RESPONSE_TRANSITION_LOCK:
        response_obj = dict(stored.response)
        status = str(response_obj.get("status") or "").strip().lower()
        metadata = dict(response_obj.get("metadata") or {}) if isinstance(response_obj.get("metadata"), dict) else {}
        if status != "in_progress" or not bool(metadata.get("background_response")):
            return stored
        response_id = str(response_obj.get("id") or "")
        if _background_response_has_expired(response_obj):
            failed_obj = _background_failed_response(
                stored=stored,
                failure_message=_background_timeout_failure_message(response_obj),
            )
            _store_response(
                response_id=response_id,
                response_obj=failed_obj,
                input_items=stored.input_items,
                history_items=stored.history_items,
                principal_id=principal_id,
                container=container,
                background_job=stored.background_job,
            )
            return _StoredResponse(
                response=failed_obj,
                input_items=[dict(item) for item in stored.input_items],
                history_items=[dict(item) for item in stored.history_items],
                principal_id=stored.principal_id,
                background_job=dict(stored.background_job) if isinstance(stored.background_job, dict) else None,
            )
        if _background_response_has_live_worker(response_id):
            return stored
        replay = dict(stored.background_job or {}) if isinstance(stored.background_job, dict) else {}
        if not replay:
            failed_obj = _background_failed_response(stored=stored, failure_message="background_response_replay_unavailable")
            _store_response(
                response_id=response_id,
                response_obj=failed_obj,
                input_items=stored.input_items,
                history_items=stored.history_items,
                principal_id=principal_id,
                container=container,
                background_job=stored.background_job,
            )
            return _StoredResponse(
                response=failed_obj,
                input_items=[dict(item) for item in stored.input_items],
                history_items=[dict(item) for item in stored.history_items],
                principal_id=stored.principal_id,
                background_job=dict(stored.background_job) if isinstance(stored.background_job, dict) else None,
            )

        response_metadata = metadata
        response_metadata["background_resume_count"] = int(response_metadata.get("background_resume_count") or 0) + 1
        response_metadata["background_last_resumed_at"] = _now_unix()
        refreshed_in_progress = {
            **response_obj,
            "metadata": response_metadata,
        }
        _store_response(
            response_id=response_id,
            response_obj=refreshed_in_progress,
            input_items=stored.input_items,
            history_items=stored.history_items,
            principal_id=principal_id,
            container=container,
            background_job=replay,
        )
        callback_enabled = bool(replay.get("chatplayground_audit_callback_enabled")) or bool(
            replay.get("chatplayground_audit_callback_only")
        )
        replay_callback = (
            _build_chatplayground_audit_callback(container=container, principal_id=principal_id)
            if callback_enabled
            else None
        )
        _spawn_background_codex_worker(
            response_id=response_id,
            created_at=int(response_obj.get("created_at") or _now_unix()),
            model=str(response_obj.get("model") or DEFAULT_PUBLIC_MODEL),
            response_metadata=response_metadata,
            instructions=response_obj.get("instructions") if isinstance(response_obj.get("instructions"), str) else None,
            input_items=[dict(item) for item in stored.input_items],
            reasoning=response_obj.get("reasoning"),
            max_output_tokens=_requested_max_output_tokens_from_response(response_obj),
            history_items=[dict(item) for item in stored.history_items],
            prompt=str(replay.get("prompt") or ""),
            messages=[dict(item) for item in list(replay.get("messages") or []) if isinstance(item, dict)],
            supported_tools=[dict(item) for item in list(replay.get("supported_tools") or []) if isinstance(item, dict)],
            chatplayground_audit_callback=replay_callback,
            chatplayground_audit_callback_only=bool(replay.get("chatplayground_audit_callback_only")),
            chatplayground_audit_principal_id=principal_id,
            preferred_onemin_labels=tuple(
                str(item or "").strip()
                for item in list(replay.get("preferred_onemin_labels") or [])
                if str(item or "").strip()
            ),
            principal_id=principal_id,
            container=container,
            background_job=replay,
        )
        return _StoredResponse(
            response=refreshed_in_progress,
            input_items=[dict(item) for item in stored.input_items],
            history_items=[dict(item) for item in stored.history_items],
            principal_id=stored.principal_id,
            background_job=replay,
        )


def _load_response_for_runtime(
    *,
    response_id: str,
    principal_id: str,
    container: object | None = None,
) -> _StoredResponse:
    stored = _load_response(response_id=response_id, principal_id=principal_id, container=container)
    return _ensure_background_response_progress(stored=stored, principal_id=principal_id, container=container)


def _generate_upstream_text(
    *,
    prompt: str,
    messages: list[dict[str, str]] | None = None,
    requested_model: str,
    max_output_tokens: int | None = None,
    chatplayground_audit_callback: Callable[..., Any] | None = None,
    chatplayground_audit_callback_only: bool = False,
    chatplayground_audit_principal_id: str = "",
    preferred_onemin_labels: tuple[str, ...] = (),
    request_deadline_monotonic: float | None = None,
) -> UpstreamResult:
    try:
        return generate_text(
            prompt=prompt,
            messages=messages,
            requested_model=requested_model,
            max_output_tokens=max_output_tokens,
            chatplayground_audit_callback=chatplayground_audit_callback,
            chatplayground_audit_callback_only=chatplayground_audit_callback_only,
            chatplayground_audit_principal_id=chatplayground_audit_principal_id,
            preferred_onemin_labels=preferred_onemin_labels,
            request_deadline_monotonic=request_deadline_monotonic,
        )
    except ResponsesUpstreamError as exc:
        raise HTTPException(status_code=502, detail=f"upstream_unavailable:{exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"upstream_unavailable:{exc}") from exc


@dataclass(frozen=True)
class _ToolShimDecision:
    kind: str
    text: str = ""
    tool_name: str = ""
    arguments: dict[str, object] | None = None
    upstream_result: UpstreamResult | None = None


def _response_tools(payload: _ResponsesCreateRequest) -> list[dict[str, object]]:
    raw_tools = getattr(payload, "tools", None)
    if not isinstance(raw_tools, list):
        return []
    tools: list[dict[str, object]] = []
    for entry in raw_tools:
        if isinstance(entry, dict):
            tools.append(dict(entry))
    return tools


def _tool_choice_disables_tools(payload: _ResponsesCreateRequest) -> bool:
    raw_tool_choice = getattr(payload, "tool_choice", None)
    if raw_tool_choice is None:
        return False
    if isinstance(raw_tool_choice, str):
        return raw_tool_choice.strip().lower() == "none"
    if isinstance(raw_tool_choice, dict):
        tool_choice_type = str(raw_tool_choice.get("type") or "").strip().lower()
        return tool_choice_type == "none"
    return False


def _tool_shim_supported_tools(
    raw_tools: list[dict[str, object]],
    *,
    prompt: str | None = None,
) -> list[dict[str, object]]:
    supported: list[dict[str, object]] = []
    for tool in raw_tools:
        tool_type = str(tool.get("type") or "").strip().lower()
        if tool_type != "function":
            continue
        name = str(tool.get("name") or "").strip()
        parameters = tool.get("parameters")
        if not name or not isinstance(parameters, dict):
            continue
        supported.append(
            {
                "name": name,
                "description": str(tool.get("description") or "").strip(),
                "parameters": parameters,
            }
        )
    lightweight_ops, _ = _looks_like_lightweight_ops_query(prompt or "")
    if lightweight_ops:
        preferred_names = (
            "exec_command",
            "write_stdin",
            "read_mcp_resource",
            "list_mcp_resources",
        )
        narrowed = [tool for name in preferred_names for tool in supported if tool["name"] == name]
        if narrowed:
            return narrowed
    return supported


def _history_items_for_request(
    *,
    previous_response_id: str | None = None,
    parsed_input: _ParsedResponseInput,
    principal_id: str,
    container: object | None = None,
) -> list[dict[str, object]]:
    history: list[dict[str, object]] = []
    if previous_response_id:
        stored = _load_response_for_runtime(
            response_id=previous_response_id,
            principal_id=principal_id,
            container=container,
        )
        previous_status = str(stored.response.get("status") or "").strip().lower()
        if previous_status == "in_progress":
            raise HTTPException(status_code=409, detail="previous_response_in_progress")
        if previous_status == "failed":
            failure_message = _response_failure_message(dict(stored.response))
            detail = "previous_response_failed"
            if failure_message:
                detail = f"{detail}:{failure_message}"
            raise HTTPException(status_code=409, detail=detail)
        history.extend(dict(item) for item in stored.history_items)
    history.extend(dict(item) for item in parsed_input.input_items)
    return history


def _tool_shim_transcript_max_chars() -> int:
    raw = str(os.environ.get("EA_TOOL_SHIM_TRANSCRIPT_MAX_CHARS") or "4000").strip() or "4000"
    try:
        return max(800, min(32000, int(raw)))
    except Exception:
        return 4000


def _tool_shim_transcript_part_max_chars() -> int:
    raw = str(os.environ.get("EA_TOOL_SHIM_TRANSCRIPT_PART_MAX_CHARS") or "1200").strip() or "1200"
    try:
        return max(200, min(8000, int(raw)))
    except Exception:
        return 1200


def _tool_shim_planner_model(model: str, *, prompt: str | None = None) -> str:
    normalized = str(model or "").strip().lower()
    if not normalized:
        return "onemin:gpt-4.1"
    if normalized == str(ONEMIN_PUBLIC_MODEL or "").strip().lower() or normalized.startswith("onemin:"):
        return "onemin:gpt-4.1"
    return model


def _tool_shim_planner_max_output_tokens(max_output_tokens: int | None) -> int:
    if max_output_tokens is None:
        return 256
    try:
        value = int(max_output_tokens)
    except Exception:
        return 256
    return max(96, min(256, value))


def _tool_shim_truncate_text(text: str, *, limit: int) -> str:
    value = str(text or "")
    if limit <= 0 or len(value) <= limit:
        return value
    if limit <= 96:
        return value[:limit]
    spacer = "\n\n[... omitted for compact audit transport ...]\n\n"
    remaining = limit - len(spacer)
    if remaining <= 32:
        return value[:limit]
    head = remaining // 2
    tail = remaining - head
    return f"{value[:head]}{spacer}{value[-tail:]}".strip()


def _history_item_to_transcript(item: dict[str, object], *, include_system: bool = True, compact: bool = False) -> str:
    item_type = str(item.get("type") or "").strip().lower()
    if item_type == "message":
        role = _normalize_message_role(item.get("role"))
        if role == "system" and not include_system:
            return ""
        content = item.get("content")
        text = ""
        if isinstance(content, list):
            text = "\n\n".join(
                _extract_textish(part.get("text"))
                for part in content
                if isinstance(part, dict) and _extract_textish(part.get("text"))
            ).strip()
        else:
            text = _extract_textish(content)
        if not text:
            return ""
        if compact:
            text = _tool_shim_truncate_text(text, limit=_tool_shim_transcript_part_max_chars())
        return f"{role.capitalize()}:\n{text}"
    if item_type == "input_text":
        text = _extract_textish(item.get("text"))
        if compact:
            text = _tool_shim_truncate_text(text, limit=_tool_shim_transcript_part_max_chars())
        return f"User:\n{text}" if text else ""
    if item_type == "function_call":
        name = str(item.get("name") or "").strip()
        call_id = str(item.get("call_id") or "").strip()
        arguments = str(item.get("arguments") or "").strip()
        if not name:
            return ""
        if compact:
            arguments = _tool_shim_truncate_text(arguments, limit=_tool_shim_transcript_part_max_chars())
        return (
            f"Assistant tool call ({call_id or 'no-call-id'})\n"
            f"Tool: {name}\n"
            f"Arguments: {arguments}"
        ).strip()
    if item_type == "function_call_output":
        call_id = str(item.get("call_id") or "").strip()
        output_text = _extract_textish(item.get("output"))
        if compact:
            output_text = _tool_shim_truncate_text(output_text, limit=_tool_shim_transcript_part_max_chars())
        return (
            f"Tool output ({call_id or 'no-call-id'}):\n{output_text}"
        ).strip()
    return ""


def _tool_shim_latest_user_text(history_items: list[dict[str, object]]) -> str:
    for item in reversed(history_items):
        item_type = str(item.get("type") or "").strip().lower()
        if item_type == "input_text":
            text = _extract_textish(item.get("text"))
            if text:
                return text
            continue
        if item_type != "message":
            continue
        role = _normalize_message_role(item.get("role"))
        if role != "user":
            continue
        content = item.get("content")
        if isinstance(content, list):
            text = "\n\n".join(
                _extract_textish(part.get("text"))
                for part in content
                if isinstance(part, dict) and _extract_textish(part.get("text"))
            ).strip()
        else:
            text = _extract_textish(content)
        if text:
            return text
    return ""


def _tool_shim_unwrap_tool_output_envelope(output_text: str) -> str:
    stripped = str(output_text or "").strip()
    if not stripped:
        return ""
    output_marker = "\nOutput:\n"
    if output_marker in stripped:
        return stripped.rsplit(output_marker, 1)[1].strip()
    succeeded_match = re.search(r"\nsucceeded in [^\n]*:\n(?P<body>.*)\Z", stripped, flags=re.DOTALL)
    if succeeded_match:
        return str(succeeded_match.group("body") or "").strip()
    return stripped


def _tool_shim_latest_function_output(history_items: list[dict[str, object]]) -> str:
    for item in reversed(history_items):
        item_type = str(item.get("type") or "").strip().lower()
        if item_type != "function_call_output":
            continue
        output_text = _tool_shim_unwrap_tool_output_envelope(_extract_textish(item.get("output")))
        if output_text:
            return output_text
    return ""


def _tool_shim_requires_immediate_tool(
    *,
    latest_user_text: str,
    available_tools: list[dict[str, object]],
) -> bool:
    if not available_tools:
        return False
    prompt = str(latest_user_text or "").strip()
    if not prompt:
        return False
    lightweight_ops, _ = _looks_like_lightweight_ops_query(prompt)
    if lightweight_ops:
        return True
    normalized = " ".join(prompt.lower().split())
    if len(normalized) > 220:
        return False
    if not (
        "?" in normalized
        or normalized.startswith(("how many ", "what ", "which ", "is ", "are ", "eta ", "status "))
    ):
        return False
    local_markers = (
        "right now",
        "currently",
        "current ",
        "in the fleet",
        "in this repo",
        "in the repo",
        "in the workspace",
        "local ",
    )
    return any(marker in normalized for marker in local_markers)


def _tool_shim_local_upstream_result(text: str, *, reason: str) -> UpstreamResult:
    return UpstreamResult(
        text=text,
        provider_key="local",
        model="tool_shim_local",
        provider_key_slot=None,
        provider_backend="local",
        provider_account_name="tool_shim_local",
        tokens_in=0,
        tokens_out=0,
        upstream_model="tool_shim_local",
        latency_ms=0,
        fallback_reason=reason,
    )


def _tool_shim_scalar_text(value: object) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    if value is None:
        return None
    if isinstance(value, list) and len(value) == 1:
        return _tool_shim_scalar_text(value[0])
    if isinstance(value, dict):
        preferred_keys = ("output", "stdout", "text", "result", "value", "content", "message")
        for key in preferred_keys:
            if key in value:
                scalar = _tool_shim_scalar_text(value.get(key))
                if scalar is not None:
                    return scalar
        if len(value) == 1:
            only_value = next(iter(value.values()))
            return _tool_shim_scalar_text(only_value)
    return None


def _tool_shim_direct_final_text(history_items: list[dict[str, object]]) -> str | None:
    latest_user_text = _tool_shim_latest_user_text(history_items)
    lightweight_ops, _ = _looks_like_lightweight_ops_query(latest_user_text)
    if not lightweight_ops:
        return None
    output_text = _tool_shim_latest_function_output(history_items)
    if not output_text:
        return None
    stripped = output_text.strip()
    if not stripped:
        return None
    if len(stripped) <= 40 and "\n" not in stripped:
        return stripped
    parsed_ok = False
    try:
        parsed = json.loads(stripped)
        parsed_ok = True
    except Exception:
        parsed = None
    if parsed_ok:
        scalar = _tool_shim_scalar_text(parsed)
        if scalar is not None:
            return scalar
    compact_lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if len(compact_lines) == 1 and len(compact_lines[0]) <= 120:
        return compact_lines[0]
    return None


def _tool_shim_direct_local_fleet_command(latest_user_text: str) -> str | None:
    normalized = " ".join(str(latest_user_text or "").strip().lower().split())
    if "fleet" not in normalized:
        return None
    state_root = Path("/docker/fleet/state/chummer_design_supervisor")
    supervisor_script = Path("/docker/fleet/scripts/chummer_design_supervisor.py")
    if not supervisor_script.exists() or not state_root.exists():
        return None
    eta_cmd = (
        "python3 /docker/fleet/scripts/chummer_design_supervisor.py "
        "eta --state-root /docker/fleet/state/chummer_design_supervisor --json"
    )
    status_cmd = (
        "python3 /docker/fleet/scripts/chummer_design_supervisor.py "
        "status --state-root /docker/fleet/state/chummer_design_supervisor --json"
    )
    def _json_field(cmd: str, expr: str) -> str:
        return (
            f"{cmd} | "
            "python3 -c "
            + shlex.quote(
                "import json,sys; payload=json.load(sys.stdin); " + expr
            )
        )
    if "how many" in normalized and "milestone" in normalized and "not started" in normalized:
        return _json_field(eta_cmd, "print((payload or {}).get('remaining_not_started_milestones', ''))")
    if "how many" in normalized and "milestone" in normalized and "in progress" in normalized:
        return _json_field(eta_cmd, "print((payload or {}).get('remaining_in_progress_milestones', ''))")
    if "how many" in normalized and "milestone" in normalized and "open" in normalized:
        return _json_field(eta_cmd, "print((payload or {}).get('remaining_open_milestones', ''))")
    if "how many" in normalized and "shard" in normalized and any(token in normalized for token in ("running", "active")):
        return _json_field(status_cmd, "print((payload or {}).get('active_runs_count', ''))")
    if normalized.startswith("eta") or "eta of the fleet" in normalized or "fleet eta" in normalized:
        return _json_field(
            eta_cmd,
            "print((payload or {}).get('summary') or (payload or {}).get('eta_human') or json.dumps(payload,separators=(',',':')))"
        )
    if "fleet" in normalized and any(token in normalized for token in ("status", "running", "milestone", "shard")):
        return (
            f"{status_cmd} | "
            "python3 -c "
            + shlex.quote(
                "import json,sys; payload=json.load(sys.stdin) or {}; eta=payload.get('eta') or {}; "
                "out={'active_runs_count':payload.get('active_runs_count'),"
                "'remaining_open_milestones':eta.get('remaining_open_milestones'),"
                "'remaining_not_started_milestones':eta.get('remaining_not_started_milestones'),"
                "'remaining_in_progress_milestones':eta.get('remaining_in_progress_milestones'),"
                "'eta_human':eta.get('eta_human'),'summary':eta.get('summary')}; "
                "print(json.dumps(out,separators=(',',':')))"
            )
        )
    return None


def _tool_shim_text_rejection_reason(*, text: str, requires_tool: bool) -> str | None:
    if not requires_tool:
        return None
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return (
            "You returned an empty answer. Return JSON only and choose one focused function_call "
            "or provide the concrete answer if it is already known from prior tool output."
        )
    intent_markers = (
        "i'll ",
        "i will ",
        "let me ",
        "i need to ",
        "please let me ",
        "i'm going to ",
        "i am going to ",
        "starting repo inspection",
        "scan the repo",
        "inspect the repo",
        "inspect the fleet",
        "need to inspect",
    )
    if any(marker in normalized for marker in intent_markers):
        return (
            "Do not narrate future inspection. Return JSON only. For this factual local-state question, "
            "choose one focused function_call immediately or provide the concrete answer if prior tool "
            "output already contains it."
        )
    if normalized.startswith("trace:") and "waiting" in normalized:
        return (
            "Do not return trace-only or waiting text as the answer. Return JSON only with the single next "
            "action or the final answer."
        )
    return None


def _tool_shim_messages(
    *,
    instructions: str | None,
    tools: list[dict[str, object]],
    history_items: list[dict[str, object]],
    compact_for_audit: bool = False,
) -> list[dict[str, str]]:
    tool_names = {str(tool.get("name") or "").strip() for tool in tools}
    has_apply_patch = "apply_patch" in tool_names
    has_exec_command = "exec_command" in tool_names
    latest_user_text = _tool_shim_latest_user_text(history_items)
    lightweight_ops, _ = _looks_like_lightweight_ops_query(latest_user_text)
    tool_catalog = []
    for tool in tools:
        tool_catalog.append(
            {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"],
            }
        )
    transcript_parts = [
        part
        for part in (
            _history_item_to_transcript(
                item,
                include_system=not compact_for_audit,
                compact=compact_for_audit,
            )
            for item in history_items
        )
        if part
    ]
    transcript = "\n\n".join(transcript_parts).strip()
    if compact_for_audit:
        transcript = _tool_shim_truncate_text(transcript, limit=_tool_shim_transcript_max_chars())
    system_parts = [
        "You are the planning/model layer behind an OpenAI Responses tool-calling shim used by Codex CLI.",
        "Decide the single next assistant action and return JSON only.",
        "Valid JSON responses:",
        '{"decision":"final","text":"..."}',
        '{"decision":"function_call","name":"TOOL_NAME","arguments":{...}}',
        "Rules:",
        "- Use at most one tool call.",
        "- Prefer a real tool call over describing future intent when inspection or execution is needed.",
        "- For coding or backlog tasks, inspect files and run commands before claiming conclusions.",
        "- Prefer the smallest single-purpose command that advances the work.",
        "- For shell-like tools, do not prepend exploratory boilerplate such as pwd or ls unless it is required to answer the request.",
        "- Keep search/read commands tightly scoped and bound noisy output with a limiter such as | head -n 200 when matches could be large.",
        "- Do not emit multiline shell scripts, here-docs, or long quoted bash programs when a simple command sequence would do.",
        "- Prefer commands like pwd, ls, rg, sed -n, cat, git status, pytest <target>, or a small focused shell command.",
        "- If a command session is already running, prefer write_stdin with the existing session_id.",
        "- Do not repeat a tool call whose output is already present in the conversation; build on that output instead.",
        "- If a prior tool output already answers the question, return a final answer instead of rereading the same context.",
        "- Keep trace-style progress concise and textual; do not dump raw scripts into user-facing text.",
        "- Do not invent tool names or arguments outside the provided schemas.",
        "- Do not wrap the JSON in markdown fences.",
        "- If the work is complete, return a final answer.",
        "Available function tools:",
        _json_compact(tool_catalog),
    ]
    if lightweight_ops:
        system_parts.extend(
            [
                "Lightweight ops question rules:",
                "- For short factual questions about the current repo/workspace/fleet state, do not narrate inspection or ask for permission to inspect.",
                "- Use one focused function_call immediately if you need fresh local state.",
                "- Prefer a direct status read or narrow command over broad repo scanning.",
            ]
        )
        normalized_user_text = " ".join(latest_user_text.lower().split())
        if (
            "fleet" in normalized_user_text
            and any(token in normalized_user_text for token in ("milestone", "shard", "eta", "status", "running"))
            and (
                Path("/docker/fleet/state/chummer_design_supervisor/state.json").exists()
                or any(Path("/docker/fleet/state/chummer_design_supervisor").glob("shard-*/state.json"))
            )
        ):
            system_parts.extend(
                [
                    "Fleet status hint for this repo:",
                    "- Prefer reading structured state under /docker/fleet/state/chummer_design_supervisor/ directly for fleet milestone/shard/eta/status questions.",
                    "- Prefer a direct structured read over rg/grep against repo text when those state files can answer the question.",
                ]
            )
    if has_exec_command and not has_apply_patch:
        system_parts.extend(
            [
                "Session constraint:",
                "- The apply_patch tool is not available in this session.",
                "- If a file edit is required, use exec_command with a short focused edit command.",
                "- Prefer one-line edits with sed -i, perl -0pi, or python3 -c for targeted replacements.",
                "- Use a short python heredoc only when no simpler edit command is practical.",
            ]
        )
    if instructions and not compact_for_audit:
        normalized_instructions = str(instructions or "").strip()
        if normalized_instructions:
            if len(normalized_instructions) <= 1200:
                system_parts.extend(
                    [
                        "Original Codex instructions:",
                        normalized_instructions,
                    ]
                )
            else:
                system_parts.extend(
                    [
                        "Original Codex instructions are enforced outside this shim.",
                        "- Omit the full instruction body here to keep the tool-planning prompt small and fast.",
                        "- Follow the visible conversation and available tool schemas to choose the next action.",
                    ]
                )
    elif compact_for_audit:
        system_parts.extend(
            [
                "Compact audit transport is enabled.",
                "- Hidden system/developer instructions are enforced outside this prompt.",
                "- Focus on the visible conversation and tool outputs below.",
            ]
        )
    user_prompt = transcript or "No prior conversation context."
    return [
        {"role": "system", "content": "\n".join(system_parts).strip()},
        {"role": "user", "content": f"Conversation so far:\n\n{user_prompt}\n\nReturn the next action as JSON only."},
    ]


def _completed_tool_call_signatures(history_items: list[dict[str, object]]) -> set[tuple[str, str]]:
    calls_by_id: dict[str, tuple[str, str]] = {}
    completed: set[tuple[str, str]] = set()
    for item in history_items:
        item_type = str(item.get("type") or "").strip().lower()
        if item_type == "function_call":
            call_id = str(item.get("call_id") or "").strip()
            name = str(item.get("name") or "").strip()
            arguments = str(item.get("arguments") or "").strip()
            if call_id and name:
                calls_by_id[call_id] = (name, arguments)
            continue
        if item_type == "function_call_output":
            call_id = str(item.get("call_id") or "").strip()
            if call_id and call_id in calls_by_id:
                completed.add(calls_by_id[call_id])
    return completed


def _extract_json_object(text: str) -> dict[str, object] | None:
    stripped = str(text or "").strip()
    if not stripped:
        return None
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            stripped = "\n".join(lines[1:-1]).strip()
    candidates: list[str] = []
    candidates.append(stripped)
    first = stripped.find("{")
    last = stripped.rfind("}")
    if first != -1 and last != -1 and last > first:
        candidates.append(stripped[first : last + 1])
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _normalize_tool_shim_payload(
    payload: dict[str, object],
    *,
    available_tools: list[dict[str, object]],
) -> dict[str, object]:
    available_names = {str(tool.get("name") or "").strip() for tool in available_tools}
    command_tool_name = None
    if "exec_command" in available_names:
        command_tool_name = "exec_command"
    elif "shell" in available_names:
        command_tool_name = "shell"

    def _command_tool_arguments(source_payload: dict[str, object]) -> dict[str, object] | None:
        if not command_tool_name:
            return None
        raw_arguments = source_payload.get("arguments")
        if isinstance(raw_arguments, dict):
            arguments = dict(raw_arguments)
        else:
            arguments = {
                key: value
                for key, value in source_payload.items()
                if key not in {"decision", "name", "arguments"}
            }
        cmd_value = arguments.get("cmd")
        command_value = arguments.get("command")
        if command_tool_name == "exec_command":
            if isinstance(cmd_value, str) and cmd_value.strip():
                return arguments
            if isinstance(command_value, str) and command_value.strip():
                normalized = dict(arguments)
                normalized["cmd"] = str(normalized.pop("command"))
                return normalized
            return None
        if isinstance(command_value, str) and command_value.strip():
            return arguments
        if isinstance(cmd_value, str) and cmd_value.strip():
            normalized = dict(arguments)
            normalized["command"] = str(normalized.pop("cmd"))
            return normalized
        return None

    decision = str(payload.get("decision") or "").strip()
    if decision == "function_call":
        name = str(payload.get("name") or "").strip()
        if name not in available_names:
            arguments = _command_tool_arguments(payload)
            if arguments is not None and command_tool_name:
                return {
                    "decision": "function_call",
                    "name": command_tool_name,
                    "arguments": arguments,
                }
        return payload
    if decision in available_names:
        arguments = payload.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {
                key: value
                for key, value in payload.items()
                if key not in {"decision", "name", "arguments"}
            }
        return {
            "decision": "function_call",
            "name": decision,
            "arguments": arguments,
        }
    name = str(payload.get("name") or "").strip()
    if not decision and name in available_names:
        arguments = payload.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {
                key: value
                for key, value in payload.items()
                if key not in {"decision", "name", "arguments"}
            }
        return {
            "decision": "function_call",
            "name": name,
            "arguments": arguments,
        }
    if command_tool_name:
        arguments = _command_tool_arguments(payload)
        if arguments is not None:
            return {
                "decision": "function_call",
                "name": command_tool_name,
                "arguments": arguments,
            }
    return payload


def _tool_invocation_command_name(cmd: str) -> str | None:
    try:
        tokens = shlex.split(str(cmd or ""), posix=True)
    except Exception:
        return None
    index = 0
    while index < len(tokens) and _ENV_ASSIGNMENT_PATTERN.match(tokens[index]):
        index += 1
    if index >= len(tokens):
        return None
    return str(tokens[index] or "").strip() or None


def _tool_call_rejection_reason(
    *,
    tool_name: str,
    arguments: dict[str, object],
    history_items: list[dict[str, object]],
    available_tools: list[dict[str, object]],
) -> str | None:
    signature = (tool_name, _json_compact(arguments))
    if signature in _completed_tool_call_signatures(history_items):
        return (
            "That exact tool call already ran and its output is already present. "
            "Use the existing output and choose a different next action or return a final answer."
        )
    if tool_name in {"exec_command", "shell"}:
        raw_cmd = arguments.get("cmd")
        if raw_cmd is None:
            raw_cmd = arguments.get("command")
        if isinstance(raw_cmd, str):
            cmd = raw_cmd.strip()
            latest_user_text = _tool_shim_latest_user_text(history_items)
            requires_structured_status = _tool_shim_requires_immediate_tool(
                latest_user_text=latest_user_text,
                available_tools=available_tools,
            )
            tool_names = {str(tool.get("name") or "").strip() for tool in available_tools}
            has_apply_patch = "apply_patch" in tool_names
            edit_markers = (
                "sed -i",
                "perl -0pi",
                "python3 -c",
                "python -c",
                "python3 - <<'PY'",
                "python - <<'PY'",
            )
            is_edit_command = any(marker in cmd for marker in edit_markers)
            if tool_name == "exec_command" and not has_apply_patch and is_edit_command:
                if len(cmd) > 1400 or cmd.count("\n") > 24:
                    return (
                        "The edit command is too large. Use a shorter focused edit command "
                        "that changes only the needed lines."
                    )
                return None
            lowered_cmd = cmd.lower()
            if (
                ("pwd" in lowered_cmd or "ls -la" in lowered_cmd)
                and any(marker in lowered_cmd for marker in ("rg ", "grep ", "find ", "sed -n", "cat "))
            ):
                return (
                    "The command includes exploratory boilerplate before the real inspection. "
                    "Use the focused read/search command directly."
                )
            if "rg " in lowered_cmd and (" -s ." in lowered_cmd or lowered_cmd.endswith(" .") or " . |" in lowered_cmd):
                if "| head" not in lowered_cmd and "| sed -n" not in lowered_cmd:
                    return (
                        "The rg search is too broad and its output is unbounded. "
                        "Narrow the target path or add a small output cap such as | head -n 200."
                    )
            if (
                requires_structured_status
                and "fleet" in latest_user_text.lower()
                and (
                    Path("/docker/fleet/state/chummer_design_supervisor/state.json").exists()
                    or any(Path("/docker/fleet/state/chummer_design_supervisor").glob("shard-*/state.json"))
                )
                and ("rg " in lowered_cmd or "grep " in lowered_cmd or "find " in lowered_cmd)
                and "/docker/fleet/state/chummer_design_supervisor/" not in cmd
            ):
                return (
                    "For fleet status questions in this repo, read the structured state under "
                    "/docker/fleet/state/chummer_design_supervisor/ directly instead of grepping repo text."
                )
            if requires_structured_status and ("rg " in lowered_cmd or "grep " in lowered_cmd) and "wc -l" in lowered_cmd:
                return (
                    "The command heuristically counts text matches instead of reading a structured local status source. "
                    "Use a direct file/data read or a precise structured command for this count/status question."
                )
            command_name = _tool_invocation_command_name(cmd)
            if (
                command_name
                and "/" not in command_name
                and command_name not in _SHELL_BUILTIN_COMMANDS
                and shutil.which(command_name) is None
            ):
                return (
                    f"The command starts with `{command_name}`, which is not installed on this host. "
                    "Choose a real available command such as rg, sed -n, cat, python3, or another installed tool."
                )
            if "\n" in cmd or len(cmd) > 280:
                return (
                    "The exec_command payload is too large. Use a shorter, single-purpose command "
                    "instead of a multiline or oversized shell script."
                )
    return None


def _tool_shim_retry_payload(
    *,
    model: str,
    max_output_tokens: int | None,
    shim_messages: list[dict[str, str]],
    prior_payload: dict[str, object],
    retry_reason: str,
    chatplayground_audit_callback: Callable[..., Any] | None = None,
    chatplayground_audit_callback_only: bool = False,
    chatplayground_audit_principal_id: str = "",
    request_deadline_monotonic: float | None = None,
) -> tuple[dict[str, object] | None, UpstreamResult]:
    latest_user_text = _tool_shim_latest_user_text(
        [
            {"type": "input_text", "text": shim_messages[-1]["content"]},
        ]
    )
    planner_model = _tool_shim_planner_model(model, prompt=latest_user_text)
    planner_max_output_tokens = _tool_shim_planner_max_output_tokens(max_output_tokens)
    retry_messages = list(shim_messages)
    retry_messages.append({"role": "assistant", "content": _json_compact(prior_payload)})
    retry_messages.append(
        {
            "role": "user",
            "content": f"{retry_reason}\nReturn a corrected next action as JSON only.",
        }
    )
    retry_result = _generate_upstream_text(
        prompt=retry_messages[-1]["content"],
        messages=retry_messages,
        requested_model=planner_model,
        max_output_tokens=planner_max_output_tokens,
        chatplayground_audit_callback=chatplayground_audit_callback,
        chatplayground_audit_callback_only=chatplayground_audit_callback_only,
        chatplayground_audit_principal_id=chatplayground_audit_principal_id,
        request_deadline_monotonic=request_deadline_monotonic,
    )
    return _extract_json_object(retry_result.text), retry_result


def _tool_shim_decision(
    *,
    model: str,
    max_output_tokens: int | None,
    instructions: str | None,
    tools: list[dict[str, object]],
    history_items: list[dict[str, object]],
    chatplayground_audit_callback: Callable[..., Any] | None = None,
    chatplayground_audit_callback_only: bool = False,
    chatplayground_audit_principal_id: str = "",
    request_deadline_monotonic: float | None = None,
) -> _ToolShimDecision:
    latest_user_text = _tool_shim_latest_user_text(history_items)
    direct_final_text = _tool_shim_direct_final_text(history_items)
    if direct_final_text is not None:
        return _ToolShimDecision(
            kind="final",
            text=direct_final_text,
            upstream_result=_tool_shim_local_upstream_result(
                direct_final_text,
                reason="tool_output_finalizer",
            ),
        )
    tool_names = {str(tool.get("name") or "").strip() for tool in tools}
    local_fleet_cmd = None
    if "exec_command" in tool_names:
        local_fleet_cmd = _tool_shim_direct_local_fleet_command(latest_user_text)
    if local_fleet_cmd:
        return _ToolShimDecision(
            kind="function_call",
            tool_name="exec_command",
            arguments={"cmd": local_fleet_cmd, "max_output_tokens": 200},
            upstream_result=_tool_shim_local_upstream_result(
                local_fleet_cmd,
                reason="fleet_local_telemetry_tool",
            ),
        )
    planner_model = _tool_shim_planner_model(model, prompt=latest_user_text)
    planner_max_output_tokens = _tool_shim_planner_max_output_tokens(max_output_tokens)
    requires_immediate_tool = _tool_shim_requires_immediate_tool(
        latest_user_text=latest_user_text,
        available_tools=tools,
    )
    shim_messages = _tool_shim_messages(
        instructions=instructions,
        tools=tools,
        history_items=history_items,
        compact_for_audit=chatplayground_audit_callback_only,
    )
    shim_prompt = shim_messages[-1]["content"]
    result = _generate_upstream_text(
        prompt=shim_prompt,
        messages=shim_messages,
        requested_model=planner_model,
        max_output_tokens=planner_max_output_tokens,
        chatplayground_audit_callback=chatplayground_audit_callback,
        chatplayground_audit_callback_only=chatplayground_audit_callback_only,
        chatplayground_audit_principal_id=chatplayground_audit_principal_id,
        request_deadline_monotonic=request_deadline_monotonic,
    )
    payload = _extract_json_object(result.text)
    if not isinstance(payload, dict):
        retry_reason = _tool_shim_text_rejection_reason(
            text=result.text,
            requires_tool=requires_immediate_tool,
        )
        if retry_reason:
            retry_payload, retry_result = _tool_shim_retry_payload(
                model=model,
                max_output_tokens=max_output_tokens,
                shim_messages=shim_messages,
                prior_payload={"decision": "final", "text": result.text},
                retry_reason=retry_reason,
                chatplayground_audit_callback=chatplayground_audit_callback,
                chatplayground_audit_callback_only=chatplayground_audit_callback_only,
                chatplayground_audit_principal_id=chatplayground_audit_principal_id,
                request_deadline_monotonic=request_deadline_monotonic,
            )
            if isinstance(retry_payload, dict):
                payload = retry_payload
                result = retry_result
            else:
                return _ToolShimDecision(kind="final", text=retry_result.text, upstream_result=retry_result)
        else:
            return _ToolShimDecision(kind="final", text=result.text, upstream_result=result)
    if not isinstance(payload, dict):
        return _ToolShimDecision(kind="final", text=result.text, upstream_result=result)
    payload = _normalize_tool_shim_payload(payload, available_tools=tools)
    decision = str(payload.get("decision") or "").strip().lower()
    if decision == "final":
        retry_reason = _tool_shim_text_rejection_reason(
            text=str(payload.get("text") or ""),
            requires_tool=requires_immediate_tool,
        )
        if retry_reason:
            retry_payload, retry_result = _tool_shim_retry_payload(
                model=model,
                max_output_tokens=max_output_tokens,
                shim_messages=shim_messages,
                prior_payload=payload,
                retry_reason=retry_reason,
                chatplayground_audit_callback=chatplayground_audit_callback,
                chatplayground_audit_callback_only=chatplayground_audit_callback_only,
                chatplayground_audit_principal_id=chatplayground_audit_principal_id,
                request_deadline_monotonic=request_deadline_monotonic,
            )
            if isinstance(retry_payload, dict):
                payload = _normalize_tool_shim_payload(retry_payload, available_tools=tools)
                result = retry_result
                decision = str(payload.get("decision") or "").strip().lower()
    if decision == "function_call":
        tool_name = str(payload.get("name") or "").strip()
        arguments = payload.get("arguments")
        if tool_name and isinstance(arguments, dict):
            retry_reason = _tool_call_rejection_reason(
                tool_name=tool_name,
                arguments=arguments,
                history_items=history_items,
                available_tools=tools,
            )
            if retry_reason:
                retry_payload, retry_result = _tool_shim_retry_payload(
                    model=model,
                    max_output_tokens=max_output_tokens,
                    shim_messages=shim_messages,
                    prior_payload=payload,
                    retry_reason=retry_reason,
                    chatplayground_audit_callback=chatplayground_audit_callback,
                    chatplayground_audit_callback_only=chatplayground_audit_callback_only,
                    chatplayground_audit_principal_id=chatplayground_audit_principal_id,
                    request_deadline_monotonic=request_deadline_monotonic,
                )
                if isinstance(retry_payload, dict):
                    payload = _normalize_tool_shim_payload(retry_payload, available_tools=tools)
                    result = retry_result
                    decision = str(payload.get("decision") or "").strip().lower()
    if decision == "function_call":
        tool_name = str(payload.get("name") or "").strip()
        arguments = payload.get("arguments")
        if tool_name and isinstance(arguments, dict) and any(tool["name"] == tool_name for tool in tools):
            return _ToolShimDecision(
                kind="function_call",
                tool_name=tool_name,
                arguments=arguments,
                upstream_result=result,
            )
    final_text = _extract_textish(payload.get("text")) or result.text
    return _ToolShimDecision(kind="final", text=final_text, upstream_result=result)


def _build_failed_response(
    *,
    response_id: str,
    created_at: int,
    model: str,
    requested_max_output_tokens: int | None,
    metadata: dict[str, object],
    instructions: str | None,
    input_items: list[dict[str, object]],
    failure_message: str,
    item_id: str | None = None,
    visible_text: str = "",
) -> dict[str, object]:
    output: list[dict[str, object]] = []
    output_text = str(visible_text or "").strip()
    if item_id and output_text:
        output = [_message_item(item_id=item_id, text=output_text, status="completed")]
    return _response_object(
        response_id=response_id,
        model=model,
        created_at=created_at,
        status="failed",
        output=output,
        output_text=output_text,
        tokens_in=0,
        tokens_out=0,
        max_output_tokens=requested_max_output_tokens,
        metadata=metadata,
        instructions=instructions,
        input_items=input_items,
        error={"code": "upstream_unavailable", "message": failure_message},
        incomplete_details={"type": "error", "reason": failure_message},
    )


def _error_event_payload(message: str) -> dict[str, object]:
    return {
        "error": {
            "code": "upstream_unavailable",
            "message": message,
            "param": None,
        },
    }


def _failed_stream_events(
    *,
    sequence_fn: Callable[[], int],
    failed_obj: dict[str, object],
    failure_message: str,
    item_id: str | None = None,
) -> list[str]:
    events: list[str] = []
    visible_text = f"Error: {failure_message}"
    if item_id:
        empty_item = _message_item(item_id=item_id, text="", status="in_progress")
        final_item = _message_item(item_id=item_id, text=visible_text, status="completed")
        events.extend(
            [
                _sse_event(
                    event="response.output_item.added",
                    sequence=sequence_fn(),
                    data={
                        "type": "response.output_item.added",
                        "output_index": 0,
                        "item": empty_item,
                    },
                ),
                _sse_event(
                    event="response.content_part.added",
                    sequence=sequence_fn(),
                    data={
                        "type": "response.content_part.added",
                        "output_index": 0,
                        "item_id": item_id,
                        "content_index": 0,
                        "part": {"type": "output_text", "text": "", "annotations": []},
                    },
                ),
                _sse_event(
                    event="response.output_text.delta",
                    sequence=sequence_fn(),
                    data={
                        "type": "response.output_text.delta",
                        "output_index": 0,
                        "item_id": item_id,
                        "content_index": 0,
                        "delta": visible_text,
                    },
                ),
                _sse_event(
                    event="response.output_text.done",
                    sequence=sequence_fn(),
                    data={
                        "type": "response.output_text.done",
                        "output_index": 0,
                        "item_id": item_id,
                        "content_index": 0,
                        "text": visible_text,
                    },
                ),
                _sse_event(
                    event="response.content_part.done",
                    sequence=sequence_fn(),
                    data={
                        "type": "response.content_part.done",
                        "output_index": 0,
                        "item_id": item_id,
                        "content_index": 0,
                        "part": {"type": "output_text", "text": visible_text, "annotations": []},
                    },
                ),
                _sse_event(
                    event="response.output_item.done",
                    sequence=sequence_fn(),
                    data={
                        "type": "response.output_item.done",
                        "output_index": 0,
                        "item": final_item,
                    },
                ),
            ]
        )
    events.extend([
        _sse_event(
            event="response.failed",
            sequence=sequence_fn(),
            data={
                "type": "response.failed",
                "response": failed_obj,
            },
        ),
        _sse_event(
            event="error",
            sequence=sequence_fn(),
            data=_error_event_payload(failure_message),
        ),
        _sse_event(
            event="response.completed",
            sequence=sequence_fn(),
            data={
                "type": "response.completed",
                "response": failed_obj,
            },
        ),
        _sse_event(
            event="response.done",
            sequence=sequence_fn(),
            data={
                "type": "response.done",
                "response": failed_obj,
            },
        ),
        _sse_done(),
    ])
    return events


def _is_background_codex_profile(*, model: str = "", codex_profile: str | None = None) -> bool:
    normalized_model = str(model or "").strip().lower()
    normalized_profile = str(codex_profile or "").strip().lower()
    return normalized_profile in {"core_batch", "core_rescue"} or normalized_model in {
        str(HARD_BATCH_PUBLIC_MODEL or "").strip().lower(),
        str(HARD_RESCUE_PUBLIC_MODEL or "").strip().lower(),
    }


def _responses_background_timeout_seconds(*, model: str = "", codex_profile: str | None = None) -> float:
    base_timeout = _responses_upstream_idle_timeout_seconds(model=model, codex_profile=str(codex_profile or ""))
    raw = str(os.environ.get("EA_RESPONSES_BACKGROUND_TIMEOUT_SECONDS") or "7200").strip()
    try:
        parsed = float(raw)
    except Exception:
        parsed = 7200.0
    hard_batch_raw = str(
        os.environ.get("EA_RESPONSES_BACKGROUND_TIMEOUT_HARD_BATCH_SECONDS") or max(parsed, 21600.0)
    ).strip()
    try:
        hard_batch_parsed = float(hard_batch_raw)
    except Exception:
        hard_batch_parsed = max(parsed, 21600.0)
    rescue_raw = str(
        os.environ.get("EA_RESPONSES_BACKGROUND_TIMEOUT_CORE_RESCUE_SECONDS") or max(hard_batch_parsed, 21600.0)
    ).strip()
    try:
        rescue_parsed = float(rescue_raw)
    except Exception:
        rescue_parsed = max(hard_batch_parsed, 21600.0)
    normalized_model = str(model or "").strip().lower()
    normalized_profile = str(codex_profile or "").strip().lower()
    if normalized_profile == "core_rescue" or normalized_model == str(HARD_RESCUE_PUBLIC_MODEL or "").strip().lower():
        timeout_seconds = rescue_parsed
    elif _is_background_codex_profile(model=model, codex_profile=codex_profile):
        timeout_seconds = hard_batch_parsed
    else:
        timeout_seconds = parsed
    return max(timeout_seconds, base_timeout)


def _primary_output_item(response_obj: dict[str, object]) -> dict[str, object]:
    output = response_obj.get("output")
    if isinstance(output, list):
        for item in output:
            if isinstance(item, dict):
                return dict(item)
    return {}


def _response_output_text_value(response_obj: dict[str, object]) -> str:
    direct = str(response_obj.get("output_text") or "").strip()
    if direct:
        return direct
    primary_item = _primary_output_item(response_obj)
    content = primary_item.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            text = str(part.get("text") or "").strip()
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    return ""


def _response_failure_message(response_obj: dict[str, object]) -> str:
    error = response_obj.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "").strip()
        if message:
            return message
    incomplete_details = response_obj.get("incomplete_details")
    if isinstance(incomplete_details, dict):
        reason = str(incomplete_details.get("reason") or "").strip()
        if reason:
            return reason
    output_text = _response_output_text_value(response_obj)
    if output_text.startswith("Error: "):
        return output_text[len("Error: ") :].strip()
    return output_text


def _build_completed_response_from_upstream(
    *,
    response_id: str,
    created_at: int,
    model: str,
    requested_max_output_tokens: int | None,
    metadata: dict[str, object],
    instructions: str | None,
    input_items: list[dict[str, object]],
    reasoning: Any | None,
    base_history_items: list[dict[str, object]],
    result: UpstreamResult,
    tool_decision: _ToolShimDecision | None = None,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    final_metadata = {
        **metadata,
        "upstream_provider": result.provider_key,
        "upstream_model": result.model,
        "provider_backend": result.provider_backend,
        "provider_account_name": result.provider_account_name,
        "provider_key_slot": result.provider_key_slot,
        "upstream_fallback_reason": result.fallback_reason,
    }
    history_items_to_store = list(base_history_items)
    if tool_decision and tool_decision.kind == "function_call":
        call_id = "call_" + uuid.uuid4().hex[:24]
        arguments_json = _json_compact(tool_decision.arguments or {})
        final_item = _function_call_item(
            item_id="fc_" + uuid.uuid4().hex[:24],
            call_id=call_id,
            name=tool_decision.tool_name,
            arguments=arguments_json,
            status="completed",
        )
        history_items_to_store.append(final_item)
        return (
            _response_object(
                response_id=response_id,
                model=model,
                created_at=created_at,
                status="completed",
                output=[final_item],
                output_text="",
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                max_output_tokens=requested_max_output_tokens,
                metadata=final_metadata,
                instructions=instructions,
                input_items=input_items,
                reasoning=reasoning,
            ),
            history_items_to_store,
        )

    text = tool_decision.text if tool_decision else result.text
    final_item = _message_item(
        item_id="msg_" + uuid.uuid4().hex[:24],
        text=text,
        status="completed",
    )
    history_items_to_store.append(final_item)
    return (
        _response_object(
            response_id=response_id,
            model=model,
            created_at=created_at,
            status="completed",
            output=[final_item],
            output_text=text,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            max_output_tokens=requested_max_output_tokens,
            metadata=final_metadata,
            instructions=instructions,
            input_items=input_items,
            reasoning=reasoning,
        ),
        history_items_to_store,
    )


def _run_background_codex_response(
    request: _ResponsesCreateRequest,
    *,
    parsed_input: _ParsedResponseInput,
    context: RequestContext,
    container: object | None,
    response_id: str,
    created_at: int,
    model: str,
    metadata: dict[str, object],
    instructions: str | None,
    input_items: list[dict[str, object]],
    reasoning: Any | None,
    max_output_tokens: int | None,
    history_items: list[dict[str, object]],
    messages: list[dict[str, str]],
    supported_tools: list[dict[str, object]],
    chatplayground_audit_callback: Callable[..., Any] | None,
    chatplayground_audit_callback_only: bool,
    chatplayground_audit_principal_id: str,
    prompt_route_trace_line: str,
    effective_codex_profile: str | None,
) -> Response:
    store_forced = request.store is False
    background_timeout_seconds = _responses_background_timeout_seconds(
        model=model,
        codex_profile=effective_codex_profile,
    )
    background_job = _background_replay_payload(
        prompt=parsed_input.prompt,
        messages=messages,
        supported_tools=supported_tools,
        effective_codex_profile=effective_codex_profile,
        chatplayground_audit_callback_enabled=chatplayground_audit_callback is not None,
        chatplayground_audit_callback_only=chatplayground_audit_callback_only,
        preferred_onemin_labels=tuple(
            str(item or "").strip()
            for item in list(metadata.get("preferred_onemin_labels") or [])
            if str(item or "").strip()
        ),
    )
    response_metadata = {
        **metadata,
        "background_response": True,
        "background_poll_url": f"/v1/responses/{response_id}",
        "background_timeout_seconds": background_timeout_seconds,
    }
    if store_forced:
        response_metadata["background_requested_store"] = False
        response_metadata["background_store_forced"] = True

    in_progress_obj = _response_object(
        response_id=response_id,
        model=model,
        created_at=created_at,
        status="in_progress",
        output=[],
        output_text="",
        tokens_in=0,
        tokens_out=0,
        max_output_tokens=max_output_tokens,
        metadata=response_metadata,
        instructions=instructions,
        input_items=input_items,
        reasoning=reasoning,
    )
    _store_response(
        response_id=response_id,
        response_obj=in_progress_obj,
        input_items=input_items,
        history_items=history_items,
        principal_id=context.principal_id,
        container=container,
        background_job=background_job,
    )
    _spawn_background_codex_worker(
        response_id=response_id,
        created_at=created_at,
        model=model,
        response_metadata=response_metadata,
        instructions=instructions,
        input_items=input_items,
        reasoning=reasoning,
        max_output_tokens=max_output_tokens,
        history_items=history_items,
        prompt=parsed_input.prompt,
        messages=messages,
        supported_tools=supported_tools,
        chatplayground_audit_callback=chatplayground_audit_callback,
        chatplayground_audit_callback_only=chatplayground_audit_callback_only,
        chatplayground_audit_principal_id=chatplayground_audit_principal_id,
        preferred_onemin_labels=tuple(
            str(item or "").strip()
            for item in list(metadata.get("preferred_onemin_labels") or [])
            if str(item or "").strip()
        ),
        principal_id=context.principal_id,
        container=container,
        background_job=background_job,
    )

    if not request.stream:
        return JSONResponse(in_progress_obj, status_code=202)

    def _iter_background_stream() -> Iterable[str]:
        sequence = 0
        item_id = "msg_" + uuid.uuid4().hex[:24]
        message_stream_open = False
        prompt_route_trace_pending = bool(prompt_route_trace_line)

        def _next_sequence() -> int:
            nonlocal sequence
            sequence += 1
            return sequence

        def _open_message_stream() -> Iterable[str]:
            empty_item = _message_item(item_id=item_id, text="", status="in_progress")
            yield _sse_event(
                event="response.output_item.added",
                sequence=_next_sequence(),
                data={"type": "response.output_item.added", "output_index": 0, "item": empty_item},
            )
            yield _sse_event(
                event="response.content_part.added",
                sequence=_next_sequence(),
                data={
                    "type": "response.content_part.added",
                    "output_index": 0,
                    "item_id": item_id,
                    "content_index": 0,
                    "part": {"type": "output_text", "text": "", "annotations": []},
                },
            )

        yield _sse_event(
            event="response.created",
            sequence=_next_sequence(),
            data={"type": "response.created", "response": in_progress_obj},
        )
        yield _sse_event(
            event="response.in_progress",
            sequence=_next_sequence(),
            data={"type": "response.in_progress", "response": in_progress_obj},
        )

        while True:
            stored = _load_response_for_runtime(
                response_id=response_id,
                principal_id=context.principal_id,
                container=container,
            )
            current_response = dict(stored.response)
            status = str(current_response.get("status") or "").strip().lower()
            if status == "in_progress":
                yield _sse_heartbeat(sequence=_next_sequence(), response=in_progress_obj)
                time.sleep(STREAM_HEARTBEAT_SECONDS)
                continue

            if status == "failed":
                failure_message = _response_failure_message(current_response) or "background_response_failed"
                visible_text = f"Error: {failure_message}"
                failed_obj = {
                    **current_response,
                    "output": [_message_item(item_id=item_id, text=visible_text, status="completed")],
                    "output_text": visible_text,
                }
                for event in _failed_stream_events(
                    sequence_fn=_next_sequence,
                    failed_obj=failed_obj,
                    failure_message=failure_message,
                    item_id=item_id,
                ):
                    yield event
                return

            primary_item = _primary_output_item(current_response)
            primary_type = str(primary_item.get("type") or "").strip().lower()
            if primary_type == "function_call":
                function_item_id = "fc_" + uuid.uuid4().hex[:24]
                call_id = str(primary_item.get("call_id") or "call_" + uuid.uuid4().hex[:24]).strip()
                name = str(primary_item.get("name") or "").strip()
                arguments_json = str(primary_item.get("arguments") or "").strip()
                in_progress_item = _function_call_item(
                    item_id=function_item_id,
                    call_id=call_id,
                    name=name,
                    arguments="",
                    status="in_progress",
                )
                yield _sse_event(
                    event="response.output_item.added",
                    sequence=_next_sequence(),
                    data={"type": "response.output_item.added", "output_index": 0, "item": in_progress_item},
                )
                yield _sse_event(
                    event="response.function_call_arguments.delta",
                    sequence=_next_sequence(),
                    data={
                        "type": "response.function_call_arguments.delta",
                        "output_index": 0,
                        "item_id": function_item_id,
                        "delta": arguments_json,
                    },
                )
                yield _sse_event(
                    event="response.function_call_arguments.done",
                    sequence=_next_sequence(),
                    data={
                        "type": "response.function_call_arguments.done",
                        "output_index": 0,
                        "item_id": function_item_id,
                        "arguments": arguments_json,
                    },
                )
                final_item = _function_call_item(
                    item_id=function_item_id,
                    call_id=call_id,
                    name=name,
                    arguments=arguments_json,
                    status="completed",
                )
                yield _sse_event(
                    event="response.output_item.done",
                    sequence=_next_sequence(),
                    data={"type": "response.output_item.done", "output_index": 0, "item": final_item},
                )
                completed_obj = {
                    **current_response,
                    "output": [final_item],
                    "output_text": "",
                }
            else:
                text = _response_output_text_value(current_response)
                if not message_stream_open:
                    for event in _open_message_stream():
                        yield event
                    message_stream_open = True
                if prompt_route_trace_pending and text:
                    prompt_route_trace_pending = False
                    yield _sse_event(
                        event="response.output_text.delta",
                        sequence=_next_sequence(),
                        data={
                            "type": "response.output_text.delta",
                            "output_index": 0,
                            "item_id": item_id,
                            "content_index": 0,
                            "delta": prompt_route_trace_line,
                        },
                    )
                if text:
                    yield _sse_event(
                        event="response.output_text.delta",
                        sequence=_next_sequence(),
                        data={
                            "type": "response.output_text.delta",
                            "output_index": 0,
                            "item_id": item_id,
                            "content_index": 0,
                            "delta": text,
                        },
                    )
                yield _sse_event(
                    event="response.output_text.done",
                    sequence=_next_sequence(),
                    data={
                        "type": "response.output_text.done",
                        "output_index": 0,
                        "item_id": item_id,
                        "content_index": 0,
                        "text": text,
                    },
                )
                yield _sse_event(
                    event="response.content_part.done",
                    sequence=_next_sequence(),
                    data={
                        "type": "response.content_part.done",
                        "output_index": 0,
                        "item_id": item_id,
                        "content_index": 0,
                        "part": {"type": "output_text", "text": text, "annotations": []},
                    },
                )
                final_item = _message_item(item_id=item_id, text=text, status="completed")
                yield _sse_event(
                    event="response.output_item.done",
                    sequence=_next_sequence(),
                    data={"type": "response.output_item.done", "output_index": 0, "item": final_item},
                )
                completed_obj = {
                    **current_response,
                    "output": [final_item],
                    "output_text": text,
                }

            yield _sse_event(
                event="response.completed",
                sequence=_next_sequence(),
                data={"type": "response.completed", "response": completed_obj},
            )
            yield _sse_event(
                event="response.done",
                sequence=_next_sequence(),
                data={"type": "response.done", "response": completed_obj},
            )
            yield _sse_done()
            return

    return StreamingResponse(
        _iter_background_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


def _survival_max_output_tokens() -> int:
    raw = str(os.environ.get("EA_SURVIVAL_MAX_OUTPUT_TOKENS") or "768").strip() or "768"
    try:
        value = int(raw)
    except Exception:
        value = 768
    return max(32, min(4096, value))


def _survival_rejected_fields(payload: _ResponsesCreateRequest) -> list[str]:
    # Codex clients send tool-shim fields by default on exec sessions. The
    # survival lane does not execute client tools, but it should ignore these
    # compatibility fields instead of rejecting the whole fallback attempt.
    return []


def _run_survival_response(
    request: _ResponsesCreateRequest,
    *,
    parsed_input: _ParsedResponseInput,
    context: RequestContext,
    container: object | None,
    codex_profile: str | None,
    profile_config: dict[str, object] | None,
    model: str,
    metadata: dict[str, object],
    history_items: list[dict[str, object]],
    previous_response_id: str | None = None,
) -> Response:
    if str(os.environ.get("EA_SURVIVAL_ENABLED") or "1").strip().lower() in {"0", "false", "no", "off"}:
        raise HTTPException(status_code=503, detail="survival_lane_disabled")
    rejected_fields = _survival_rejected_fields(request)
    if rejected_fields:
        raise HTTPException(status_code=400, detail=f"survival_unsupported_fields:{','.join(rejected_fields)}")
    created_at = _now_unix()
    response_id = "resp_" + uuid.uuid4().hex[:24]
    requested_max_output_tokens = _requested_max_output_tokens(request)
    max_output_tokens = min(requested_max_output_tokens or _survival_max_output_tokens(), _survival_max_output_tokens())
    response_metadata = {
        **metadata,
        "principal_id": context.principal_id,
        "survival_lane": True,
        "survival_background": True,
        "survival_route_order": str(os.environ.get("EA_SURVIVAL_ROUTE_ORDER") or "onemin,gemini_vortex,gemini_web,chatplayground"),
    }
    if codex_profile:
        response_metadata.update(
            {
                "codex_profile": codex_profile,
                "codex_lane": profile_config.get("lane") if profile_config else None,
                "codex_review_required": bool(profile_config.get("review_required")) if isinstance(profile_config, dict) else None,
                "codex_needs_review": bool(profile_config.get("needs_review")) if isinstance(profile_config, dict) else None,
                "codex_risk_labels": list(profile_config.get("risk_labels", [])) if isinstance(profile_config, dict) else None,
                "codex_merge_policy": profile_config.get("merge_policy") if isinstance(profile_config, dict) else None,
                "codex_provider_hint_order": list(profile_config.get("provider_hint_order", []))
                if isinstance(profile_config, dict)
                else None,
                "codex_work_class": profile_config.get("work_class") if isinstance(profile_config, dict) else None,
                "codex_expectation_summary": profile_config.get("expectation_summary") if isinstance(profile_config, dict) else None,
                "codex_review_posture": profile_config.get("review_posture") if isinstance(profile_config, dict) else None,
                "codex_best_for": profile_config.get("best_for") if isinstance(profile_config, dict) else None,
                "codex_review_cadence": dict(profile_config.get("review_cadence") or {})
                if isinstance(profile_config, dict)
                else {},
                "codex_support_help_boundary": dict(profile_config.get("support_help_boundary") or {})
                if isinstance(profile_config, dict)
                else {},
            }
        )

    in_progress_obj = _response_object(
        response_id=response_id,
        model=model,
        created_at=created_at,
        status="in_progress",
        output=[],
        output_text="",
        tokens_in=0,
        tokens_out=0,
        max_output_tokens=max_output_tokens,
        metadata=response_metadata,
        instructions=request.instructions.strip() if isinstance(request.instructions, str) else None,
        input_items=parsed_input.input_items,
        reasoning=request.reasoning,
    )
    _store_response(
        response_id=response_id,
        response_obj=in_progress_obj,
        input_items=parsed_input.input_items,
        history_items=history_items,
        principal_id=context.principal_id,
        container=container,
    )

    def _build_survival_completed_response(result: Any) -> dict[str, object]:
        upstream_result = result.to_upstream_result()
        message_item = _message_item(
            item_id="msg_" + uuid.uuid4().hex[:24],
            text=result.text,
            status="completed",
        )
        completed_metadata = {
            **response_metadata,
            "survival_provider": result.provider_key,
            "survival_backend": result.provider_backend,
            "survival_cache_hit": result.cache_hit,
            "survival_attempts": [
                {
                    "backend": item.backend,
                    "started_at": item.started_at,
                    "completed_at": item.completed_at,
                    "status": item.status,
                    "detail": item.detail,
                }
                for item in result.attempts
            ],
            "upstream_provider": upstream_result.provider_key,
            "upstream_model": upstream_result.model,
            "provider_backend": upstream_result.provider_backend,
        }
        return _response_object(
            response_id=response_id,
            model=model,
            created_at=created_at,
            status="completed",
            output=[message_item],
            output_text=result.text,
            tokens_in=0,
            tokens_out=0,
            max_output_tokens=max_output_tokens,
            metadata=completed_metadata,
            instructions=request.instructions.strip() if isinstance(request.instructions, str) else None,
            input_items=parsed_input.input_items,
            reasoning=request.reasoning,
        )

    if request.stream:
        def _iter_survival_stream() -> Iterable[str]:
            sequence = 0

            def _next_sequence() -> int:
                nonlocal sequence
                sequence += 1
                return sequence

            yield _sse_event(
                event="response.created",
                sequence=_next_sequence(),
                data={"type": "response.created", "response": in_progress_obj},
            )
            yield _sse_event(
                event="response.in_progress",
                sequence=_next_sequence(),
                data={"type": "response.in_progress", "response": in_progress_obj},
            )

            result_queue: queue.Queue[tuple[str, object]] = queue.Queue()
            item_id = "msg_" + uuid.uuid4().hex[:24]
            message_stream_open = False
            streamed_text_parts: list[str] = []
            survival_idle_timeout_seconds = _responses_upstream_idle_timeout_seconds(
                model=model,
                codex_profile=codex_profile,
            )
            last_activity = time.monotonic()

            def _open_message_stream() -> Iterable[str]:
                empty_item = _message_item(item_id=item_id, text="", status="in_progress")
                yield _sse_event(
                    event="response.output_item.added",
                    sequence=_next_sequence(),
                    data={
                        "type": "response.output_item.added",
                        "output_index": 0,
                        "item": empty_item,
                    },
                )
                yield _sse_event(
                    event="response.content_part.added",
                    sequence=_next_sequence(),
                    data={
                        "type": "response.content_part.added",
                        "output_index": 0,
                        "item_id": item_id,
                        "content_index": 0,
                        "part": {"type": "output_text", "text": "", "annotations": []},
                    },
                )

            def _worker_stream() -> None:
                service = SurvivalLaneService(
                    tool_execution=getattr(container, "tool_execution", None),
                    tool_runtime=getattr(container, "tool_runtime", None),
                    principal_id=context.principal_id,
                )
                try:
                    result = service.execute(
                        instructions=request.instructions.strip() if isinstance(request.instructions, str) else None,
                        history_items=history_items,
                        current_input=parsed_input.prompt,
                        desired_format="plain_text",
                        prompt_cache_key=request.prompt_cache_key,
                    )
                    result_queue.put(("result", result))
                except Exception as exc:
                    result_queue.put(("error", exc))

            threading.Thread(target=_worker_stream, daemon=True).start()

            state: tuple[str, object] | None = None
            while state is None:
                try:
                    next_state = result_queue.get(timeout=STREAM_HEARTBEAT_SECONDS)
                except queue.Empty:
                    if (time.monotonic() - last_activity) >= survival_idle_timeout_seconds:
                        failure_message = f"survival_timeout:{int(survival_idle_timeout_seconds)}s"
                        failed_obj = _build_failed_response(
                            response_id=response_id,
                            created_at=created_at,
                            model=model,
                            requested_max_output_tokens=max_output_tokens,
                            metadata=response_metadata,
                            instructions=request.instructions.strip() if isinstance(request.instructions, str) else None,
                            input_items=parsed_input.input_items,
                            failure_message=failure_message,
                            item_id=item_id,
                            visible_text=f"Error: {failure_message}",
                        )
                        _store_response(
                            response_id=response_id,
                            response_obj=failed_obj,
                            input_items=parsed_input.input_items,
                            history_items=history_items,
                            principal_id=context.principal_id,
                            container=container,
                        )
                        for event in _failed_stream_events(
                            sequence_fn=_next_sequence,
                            failed_obj=failed_obj,
                            failure_message=failure_message,
                            item_id=item_id,
                        ):
                            yield event
                        return
                    if not message_stream_open:
                        for event in _open_message_stream():
                            yield event
                        message_stream_open = True
                    streamed_text_parts.append(_SSE_KEEPALIVE_TEXT)
                    yield _sse_event(
                        event="response.output_text.delta",
                        sequence=_next_sequence(),
                        data={
                            "type": "response.output_text.delta",
                            "output_index": 0,
                            "item_id": item_id,
                            "content_index": 0,
                            "delta": _SSE_KEEPALIVE_TEXT,
                        },
                    )
                    yield _sse_heartbeat(sequence=_next_sequence(), response=in_progress_obj)
                    continue
                if not isinstance(next_state, tuple) or not next_state:
                    continue
                last_activity = time.monotonic()
                state = next_state

            status, result_payload = state
            if status == "error":
                failure = result_payload if isinstance(result_payload, Exception) else RuntimeError(str(result_payload))
                failure_message = str(failure)[:500]
                failed_obj = _build_failed_response(
                    response_id=response_id,
                    created_at=created_at,
                    model=model,
                    requested_max_output_tokens=max_output_tokens,
                    metadata=response_metadata,
                    instructions=request.instructions.strip() if isinstance(request.instructions, str) else None,
                    input_items=parsed_input.input_items,
                    failure_message=failure_message,
                    item_id=item_id,
                    visible_text=f"Error: {failure_message}",
                )
                _store_response(
                    response_id=response_id,
                    response_obj=failed_obj,
                    input_items=parsed_input.input_items,
                    history_items=history_items,
                    principal_id=context.principal_id,
                    container=container,
                )
                for event in _failed_stream_events(
                    sequence_fn=_next_sequence,
                    failed_obj=failed_obj,
                    failure_message=failure_message,
                    item_id=item_id,
                ):
                    yield event
                return

            completed_obj = _build_survival_completed_response(result_payload)
            text = "".join(streamed_text_parts).replace(_SSE_KEEPALIVE_TEXT, "") or str(completed_obj.get("output_text") or "")
            if not message_stream_open:
                for event in _open_message_stream():
                    yield event
                message_stream_open = True
            if text:
                yield _sse_event(
                    event="response.output_text.delta",
                    sequence=_next_sequence(),
                    data={
                        "type": "response.output_text.delta",
                        "output_index": 0,
                        "item_id": item_id,
                        "content_index": 0,
                        "delta": text,
                    },
                )
            yield _sse_event(
                event="response.output_text.done",
                sequence=_next_sequence(),
                data={
                    "type": "response.output_text.done",
                    "output_index": 0,
                    "item_id": item_id,
                    "content_index": 0,
                    "text": text,
                },
            )
            yield _sse_event(
                event="response.content_part.done",
                sequence=_next_sequence(),
                data={
                    "type": "response.content_part.done",
                    "output_index": 0,
                    "item_id": item_id,
                    "content_index": 0,
                    "part": {"type": "output_text", "text": text, "annotations": []},
                },
            )
            final_item = _message_item(item_id=item_id, text=text, status="completed")
            yield _sse_event(
                event="response.output_item.done",
                sequence=_next_sequence(),
                data={
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": final_item,
                },
            )
            completed_obj["output"] = [final_item]
            completed_obj["output_text"] = text
            _store_response(
                response_id=response_id,
                response_obj=completed_obj,
                input_items=parsed_input.input_items,
                history_items=[*history_items, final_item],
                principal_id=context.principal_id,
                container=container,
            )
            yield _sse_event(
                event="response.completed",
                sequence=_next_sequence(),
                data={"type": "response.completed", "response": completed_obj},
            )
            yield _sse_event(
                event="response.done",
                sequence=_next_sequence(),
                data={"type": "response.done", "response": completed_obj},
            )
            yield _sse_done()

        return StreamingResponse(
            _iter_survival_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    def _worker() -> None:
        service = SurvivalLaneService(
            tool_execution=getattr(container, "tool_execution", None),
            tool_runtime=getattr(container, "tool_runtime", None),
            principal_id=context.principal_id,
        )
        try:
            result = service.execute(
                instructions=request.instructions.strip() if isinstance(request.instructions, str) else None,
                history_items=history_items,
                current_input=parsed_input.prompt,
                desired_format="plain_text",
                prompt_cache_key=request.prompt_cache_key,
            )
            completed_obj = _build_survival_completed_response(result)
            _store_response(
                response_id=response_id,
                response_obj=completed_obj,
                input_items=parsed_input.input_items,
                history_items=[*history_items, *list(completed_obj.get("output") or [])],
                principal_id=context.principal_id,
                container=container,
            )
        except Exception as exc:
            failed_obj = _response_object(
                response_id=response_id,
                model=model,
                created_at=created_at,
                status="failed",
                output=[],
                output_text="",
                tokens_in=0,
                tokens_out=0,
                max_output_tokens=max_output_tokens,
                metadata=response_metadata,
                instructions=request.instructions.strip() if isinstance(request.instructions, str) else None,
                input_items=parsed_input.input_items,
                reasoning=request.reasoning,
                error={"code": "survival_failed", "message": str(exc)[:500]},
                incomplete_details={"type": "error", "reason": str(exc)[:500]},
            )
            _store_response(
                response_id=response_id,
                response_obj=failed_obj,
                input_items=parsed_input.input_items,
                history_items=history_items,
                principal_id=context.principal_id,
                container=container,
            )

    threading.Thread(target=_worker, daemon=True).start()
    return JSONResponse(in_progress_obj, status_code=202)


def _run_response(
    request_payload: dict[str, object],
    *,
    context: RequestContext,
    container: object | None = None,
    codex_profile: str | None = None,
    preferred_onemin_labels: tuple[str, ...] = (),
) -> Response:
    _capture_responses_debug(
        name="request",
        payload={
            "principal_id": context.principal_id,
            "codex_profile": codex_profile,
            "payload": request_payload,
        },
    )
    request, parsed_input = _parse_create_request(request_payload)
    model = _requested_model(request) or DEFAULT_PUBLIC_MODEL
    profile_config: dict[str, object] | None = None
    if codex_profile:
        profile_config = _codex_profile(
            codex_profile,
            container=container,
            principal_id=context.principal_id,
            provider_health=_provider_health_snapshot(lightweight=True),
        )
        codex_model = profile_config.get("model")
        if isinstance(codex_model, str) and codex_model and not _requested_model_is_explicit(_requested_model(request)):
            model = codex_model
    else:
        router = _brain_router(container)
        if router is not None and get_brain_profile(model) is not None:
            resolved = router.resolve_profile(model, principal_id=context.principal_id)
            if resolved.public_model:
                model = resolved.public_model

    requested_model = _requested_model(request)
    latest_prompt = _latest_user_prompt(parsed_input)
    effective_prompt = _effective_prompt_route_text(parsed_input)
    prompt_route = _resolve_prompt_route(
        prompt=effective_prompt,
        model=model,
        codex_profile=codex_profile,
    )
    effective_codex_profile = prompt_route.effective_profile
    model = prompt_route.effective_model

    is_survival_profile = effective_codex_profile == "survival"
    is_survival_model = requested_model == SURVIVAL_PUBLIC_MODEL or model == SURVIVAL_PUBLIC_MODEL

    is_audit_profile = effective_codex_profile == "audit"
    is_audit_model = requested_model in {"ea-audit", "ea-audit-jury"}
    is_review_light_profile = effective_codex_profile == "review_light"
    is_review_light_model = requested_model == REVIEW_LIGHT_PUBLIC_MODEL or model == REVIEW_LIGHT_PUBLIC_MODEL
    audit_profile_or_model = is_audit_profile or is_audit_model
    chatplayground_profile_or_model = audit_profile_or_model or is_review_light_profile or is_review_light_model
    chatplayground_audit_callback = None
    if chatplayground_profile_or_model:
        chatplayground_audit_callback = _build_chatplayground_audit_callback(
            container=container,
            principal_id=context.principal_id,
        )

    max_output_tokens = _requested_max_output_tokens(request)
    metadata = _metadata(request)
    stream = bool(request.stream)
    instructions = request.instructions.strip() if isinstance(request.instructions, str) else None
    accepted_client_fields = _accepted_client_fields(request)
    rejected_client_fields = _rejected_client_fields(request, codex_profile=codex_profile)
    if rejected_client_fields:
        raise HTTPException(status_code=400, detail=f"unsupported_fields:{','.join(rejected_client_fields)}")
    previous_response_id = _requested_previous_response_id(request)
    raw_tools = _response_tools(request)
    supported_tools = _tool_shim_supported_tools(raw_tools, prompt=latest_prompt)
    if _tool_choice_disables_tools(request):
        supported_tools = []
    history_items = _history_items_for_request(
        previous_response_id=previous_response_id,
        parsed_input=parsed_input,
        principal_id=context.principal_id,
        container=container,
    )

    messages: list[dict[str, str]] = []
    if instructions:
        _append_message(messages, role="system", content=instructions)
    if _codex_trace_instructions_enabled(
        codex_profile=effective_codex_profile or codex_profile,
        stream=stream,
    ):
        _append_message(
            messages,
            role="system",
            content=_codex_trace_instruction(codex_profile=effective_codex_profile or codex_profile),
        )
    for item in parsed_input.messages:
        _append_message(messages, role=item.get("role"), content=item.get("content"))

    created_at = _now_unix()
    response_id = "resp_" + uuid.uuid4().hex[:24]
    item_id = "msg_" + uuid.uuid4().hex[:24]

    response_metadata = {
        **metadata,
        "principal_id": context.principal_id,
    }
    if preferred_onemin_labels:
        response_metadata["preferred_onemin_labels"] = list(preferred_onemin_labels)
    if accepted_client_fields:
        response_metadata["accepted_client_fields"] = accepted_client_fields
    if supported_tools:
        response_metadata["tool_shim"] = True
        response_metadata["tool_shim_tools"] = [tool["name"] for tool in supported_tools]
    if codex_profile:
        response_metadata.update(
            {
                "codex_profile": codex_profile,
                "codex_lane": profile_config.get("lane") if profile_config else None,
                "codex_review_required": bool(profile_config.get("review_required")) if isinstance(profile_config, dict) else None,
                "codex_needs_review": bool(profile_config.get("needs_review")) if isinstance(profile_config, dict) else None,
                "codex_risk_labels": list(profile_config.get("risk_labels", [])) if isinstance(profile_config, dict) else None,
                "codex_merge_policy": profile_config.get("merge_policy") if isinstance(profile_config, dict) else None,
                "codex_provider_hint_order": list(profile_config.get("provider_hint_order", []))
                if isinstance(profile_config, dict)
                else None,
                "codex_work_class": profile_config.get("work_class") if isinstance(profile_config, dict) else None,
                "codex_expectation_summary": profile_config.get("expectation_summary") if isinstance(profile_config, dict) else None,
                "codex_review_posture": profile_config.get("review_posture") if isinstance(profile_config, dict) else None,
                "codex_best_for": profile_config.get("best_for") if isinstance(profile_config, dict) else None,
                "codex_review_cadence": dict(profile_config.get("review_cadence") or {})
                if isinstance(profile_config, dict)
                else {},
                "codex_support_help_boundary": dict(profile_config.get("support_help_boundary") or {})
                if isinstance(profile_config, dict)
                else {},
            }
        )
    response_metadata.update(
        {
            "codex_effective_profile": effective_codex_profile,
            "codex_effective_model": model,
            "codex_prompt_route_applied": prompt_route.applied,
            "codex_prompt_route_reason": prompt_route.reason,
            "codex_prompt_route_from_profile": prompt_route.original_profile,
            "codex_prompt_route_to_profile": effective_codex_profile,
            "codex_prompt_route_from_model": prompt_route.original_model,
            "codex_prompt_route_to_model": model,
            "codex_prompt_route_trace": prompt_route.trace_line.strip(),
        }
    )

    if is_survival_profile or is_survival_model:
        return _run_survival_response(
            request,
            parsed_input=parsed_input,
            context=context,
            container=container,
            codex_profile=codex_profile,
            profile_config=profile_config,
            model=SURVIVAL_PUBLIC_MODEL,
            metadata=response_metadata,
            history_items=history_items,
        )

    if _is_background_codex_profile(model=model, codex_profile=effective_codex_profile):
        return _run_background_codex_response(
            request,
            parsed_input=parsed_input,
            context=context,
            container=container,
            response_id=response_id,
            created_at=created_at,
            model=model,
            metadata=response_metadata,
            instructions=instructions,
            input_items=parsed_input.input_items,
            reasoning=request.reasoning,
            max_output_tokens=max_output_tokens,
            history_items=history_items,
            messages=messages,
            supported_tools=supported_tools,
            chatplayground_audit_callback=chatplayground_audit_callback,
            chatplayground_audit_callback_only=audit_profile_or_model,
            chatplayground_audit_principal_id=context.principal_id,
            prompt_route_trace_line=prompt_route.trace_line,
            effective_codex_profile=effective_codex_profile,
        )

    if not stream:
        result_queue: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)
        upstream_idle_timeout_seconds = _responses_upstream_idle_timeout_seconds(
            model=model,
            codex_profile=effective_codex_profile,
        )
        request_deadline_monotonic = time.monotonic() + upstream_idle_timeout_seconds

        def _run_non_stream() -> None:
            try:
                if supported_tools:
                    decision = _tool_shim_decision(
                        model=model,
                        max_output_tokens=max_output_tokens,
                        instructions=instructions,
                        tools=supported_tools,
                        history_items=history_items,
                        chatplayground_audit_callback=chatplayground_audit_callback,
                        chatplayground_audit_callback_only=audit_profile_or_model,
                        chatplayground_audit_principal_id=context.principal_id,
                        request_deadline_monotonic=request_deadline_monotonic,
                    )
                    result_queue.put(("decision", decision))
                    return
                result = _generate_upstream_text(
                    prompt=parsed_input.prompt,
                    messages=messages,
                    requested_model=model,
                    max_output_tokens=max_output_tokens,
                    chatplayground_audit_callback=chatplayground_audit_callback,
                    chatplayground_audit_callback_only=audit_profile_or_model,
                    chatplayground_audit_principal_id=context.principal_id,
                    preferred_onemin_labels=preferred_onemin_labels,
                    request_deadline_monotonic=request_deadline_monotonic,
                )
                result_queue.put(("result", result))
            except Exception as exc:
                result_queue.put(("error", exc))

        worker = threading.Thread(target=_run_non_stream, daemon=True)
        worker.start()
        try:
            status, result_payload = result_queue.get(timeout=upstream_idle_timeout_seconds)
        except queue.Empty:
            failure_message = f"upstream_timeout:{int(upstream_idle_timeout_seconds)}s"
            failed_obj = _build_failed_response(
                response_id=response_id,
                created_at=created_at,
                model=model,
                requested_max_output_tokens=max_output_tokens,
                metadata=response_metadata,
                instructions=instructions,
                input_items=parsed_input.input_items,
                failure_message=failure_message,
            )
            if _should_store_response(request):
                _store_response(
                    response_id=response_id,
                    response_obj=failed_obj,
                    input_items=parsed_input.input_items,
                    history_items=history_items,
                    principal_id=context.principal_id,
                    container=container,
                )
            _capture_responses_debug(
                name="response_timeout",
                payload={
                    "principal_id": context.principal_id,
                    "codex_profile": codex_profile,
                    "response_id": response_id,
                    "model": model,
                    "failure_message": failure_message,
                },
            )
            return JSONResponse(failed_obj, status_code=504)
        if status == "error":
            failure = result_payload if isinstance(result_payload, Exception) else RuntimeError(str(result_payload))
            raise failure
        tool_decision: _ToolShimDecision | None = None
        if status == "decision":
            if not isinstance(result_payload, _ToolShimDecision) or not isinstance(result_payload.upstream_result, UpstreamResult):
                raise HTTPException(status_code=502, detail="upstream_unavailable:invalid_upstream_result")
            tool_decision = result_payload
            result = result_payload.upstream_result
        else:
            result = result_payload
        if not isinstance(result, UpstreamResult):
            raise HTTPException(status_code=502, detail="upstream_unavailable:invalid_upstream_result")
        final_metadata = {
            **response_metadata,
            "upstream_provider": result.provider_key,
            "upstream_model": result.model,
            "provider_backend": result.provider_backend,
            "provider_account_name": result.provider_account_name,
            "provider_key_slot": result.provider_key_slot,
            "upstream_fallback_reason": result.fallback_reason,
        }
        output_items: list[dict[str, object]]
        output_text = ""
        history_items_to_store = list(history_items)
        if tool_decision and tool_decision.kind == "function_call":
            call_id = "call_" + uuid.uuid4().hex[:24]
            arguments_json = _json_compact(tool_decision.arguments or {})
            function_item = _function_call_item(
                item_id="fc_" + uuid.uuid4().hex[:24],
                call_id=call_id,
                name=tool_decision.tool_name,
                arguments=arguments_json,
                status="completed",
            )
            output_items = [function_item]
            history_items_to_store.append(function_item)
        else:
            output_text = tool_decision.text if tool_decision else result.text
            message = _message_item(item_id=item_id, text=output_text, status="completed")
            output_items = [message]
            history_items_to_store.append(message)
        response_obj = _response_object(
            response_id=response_id,
            model=model,
            created_at=created_at,
            status="completed",
            output=output_items,
            output_text=output_text,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            max_output_tokens=max_output_tokens,
            metadata=final_metadata,
            instructions=instructions,
            input_items=parsed_input.input_items,
            reasoning=request.reasoning,
        )
        if _should_store_response(request):
            _store_response(
                response_id=response_id,
                response_obj=response_obj,
                input_items=parsed_input.input_items,
                history_items=history_items_to_store,
                principal_id=context.principal_id,
                container=container,
            )
        _capture_responses_debug(
            name="response",
            payload={
                "principal_id": context.principal_id,
                "codex_profile": codex_profile,
                "response": response_obj,
            },
        )
        return JSONResponse(response_obj)

    def _iter_stream() -> Iterable[str]:
        sequence = 0

        def _next_sequence() -> int:
            nonlocal sequence
            sequence += 1
            return sequence

        in_progress_obj = _response_object(
            response_id=response_id,
            model=model,
            created_at=created_at,
            status="in_progress",
            output=[],
            output_text="",
            tokens_in=0,
            tokens_out=0,
            max_output_tokens=max_output_tokens,
            metadata=response_metadata,
            instructions=instructions,
            input_items=parsed_input.input_items,
            reasoning=request.reasoning,
        )
        if _should_store_response(request):
            _store_response(
                response_id=response_id,
                response_obj=in_progress_obj,
                input_items=parsed_input.input_items,
                history_items=history_items,
                principal_id=context.principal_id,
                container=container,
            )
        yield _sse_event(
            event="response.created",
            sequence=_next_sequence(),
            data={"type": "response.created", "response": in_progress_obj},
        )
        yield _sse_event(
            event="response.in_progress",
            sequence=_next_sequence(),
            data={"type": "response.in_progress", "response": in_progress_obj},
        )

        result_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        streamed_text_parts: list[str] = []
        message_stream_open = False
        prompt_route_trace_pending = bool(prompt_route.trace_line)
        upstream_idle_timeout_seconds = _responses_upstream_idle_timeout_seconds(
            model=model,
            codex_profile=effective_codex_profile,
        )
        request_deadline_monotonic = time.monotonic() + upstream_idle_timeout_seconds

        def _open_message_stream() -> Iterable[str]:
            empty_item = _message_item(item_id=item_id, text="", status="in_progress")
            yield _sse_event(
                event="response.output_item.added",
                sequence=_next_sequence(),
                data={
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": empty_item,
                },
            )
            yield _sse_event(
                event="response.content_part.added",
                sequence=_next_sequence(),
                data={
                    "type": "response.content_part.added",
                    "output_index": 0,
                    "item_id": item_id,
                    "content_index": 0,
                    "part": {"type": "output_text", "text": "", "annotations": []},
                },
            )

        def _run_upstream() -> None:
            try:
                if supported_tools:
                    decision = _tool_shim_decision(
                        model=model,
                        max_output_tokens=max_output_tokens,
                        instructions=instructions,
                        tools=supported_tools,
                        history_items=history_items,
                        chatplayground_audit_callback=chatplayground_audit_callback,
                        chatplayground_audit_callback_only=audit_profile_or_model,
                        chatplayground_audit_principal_id=context.principal_id,
                        request_deadline_monotonic=request_deadline_monotonic,
                    )
                    result_queue.put(("decision", decision))
                    return
                if _prefer_nonstream_upstream(model=model, codex_profile=effective_codex_profile):
                    result = _generate_upstream_text(
                        prompt=parsed_input.prompt,
                        messages=messages,
                        requested_model=model,
                        max_output_tokens=max_output_tokens,
                        chatplayground_audit_callback=chatplayground_audit_callback,
                        chatplayground_audit_callback_only=audit_profile_or_model,
                        chatplayground_audit_principal_id=context.principal_id,
                        preferred_onemin_labels=preferred_onemin_labels,
                        request_deadline_monotonic=request_deadline_monotonic,
                    )
                else:
                    result = stream_text(
                        prompt=parsed_input.prompt,
                        messages=messages,
                        requested_model=model,
                        max_output_tokens=max_output_tokens,
                        chatplayground_audit_callback=chatplayground_audit_callback,
                        chatplayground_audit_callback_only=audit_profile_or_model,
                        chatplayground_audit_principal_id=context.principal_id,
                        preferred_onemin_labels=preferred_onemin_labels,
                        request_deadline_monotonic=request_deadline_monotonic,
                        on_delta=lambda delta: result_queue.put(("delta", delta)),
                    )
                result_queue.put(("result", result))
            except Exception as exc:
                result_queue.put(("error", exc))

        worker = threading.Thread(target=_run_upstream, daemon=True)
        worker.start()

        state: tuple[str, object] | None = None
        last_upstream_activity = time.monotonic()
        while state is None:
            try:
                next_state = result_queue.get(timeout=STREAM_HEARTBEAT_SECONDS)
            except queue.Empty:
                if (time.monotonic() - last_upstream_activity) >= upstream_idle_timeout_seconds:
                    failure_message = f"upstream_timeout:{int(upstream_idle_timeout_seconds)}s"
                    failed_obj = _build_failed_response(
                        response_id=response_id,
                        created_at=created_at,
                        model=model,
                        requested_max_output_tokens=max_output_tokens,
                        metadata=response_metadata,
                        instructions=instructions,
                        input_items=parsed_input.input_items,
                        failure_message=failure_message,
                        item_id=item_id,
                        visible_text=f"Error: {failure_message}",
                    )
                    if _should_store_response(request):
                        _store_response(
                            response_id=response_id,
                            response_obj=failed_obj,
                            input_items=parsed_input.input_items,
                            history_items=history_items,
                            principal_id=context.principal_id,
                            container=container,
                        )
                    _capture_responses_debug(
                        name="response_timeout",
                        payload={
                            "principal_id": context.principal_id,
                            "codex_profile": codex_profile,
                            "response_id": response_id,
                            "model": model,
                            "failure_message": failure_message,
                        },
                    )
                    for event in _failed_stream_events(
                        sequence_fn=_next_sequence,
                        failed_obj=failed_obj,
                        failure_message=failure_message,
                        item_id=item_id,
                    ):
                        yield event
                    return
                if not message_stream_open:
                    for event in _open_message_stream():
                        yield event
                    message_stream_open = True
                keepalive_text = prompt_route.trace_line if prompt_route_trace_pending else _SSE_KEEPALIVE_TEXT
                prompt_route_trace_pending = False
                if keepalive_text == _SSE_KEEPALIVE_TEXT:
                    streamed_text_parts.append(keepalive_text)
                yield _sse_event(
                    event="response.output_text.delta",
                    sequence=_next_sequence(),
                    data={
                        "type": "response.output_text.delta",
                        "output_index": 0,
                        "item_id": item_id,
                        "content_index": 0,
                        "delta": keepalive_text,
                    },
                )
                yield _sse_heartbeat(sequence=_next_sequence(), response=in_progress_obj)
                continue
            if not isinstance(next_state, tuple) or not next_state:
                continue
            if next_state[0] == "delta":
                delta = str(next_state[1] or "")
                if not delta:
                    continue
                if not message_stream_open:
                    for event in _open_message_stream():
                        yield event
                    message_stream_open = True
                if prompt_route_trace_pending:
                    prompt_route_trace_pending = False
                    yield _sse_event(
                        event="response.output_text.delta",
                        sequence=_next_sequence(),
                        data={
                            "type": "response.output_text.delta",
                            "output_index": 0,
                            "item_id": item_id,
                            "content_index": 0,
                            "delta": prompt_route.trace_line,
                        },
                    )
                streamed_text_parts.append(delta)
                yield _sse_event(
                    event="response.output_text.delta",
                    sequence=_next_sequence(),
                    data={
                        "type": "response.output_text.delta",
                        "output_index": 0,
                        "item_id": item_id,
                        "content_index": 0,
                        "delta": delta,
                    },
                )
                last_upstream_activity = time.monotonic()
                continue
            last_upstream_activity = time.monotonic()
            state = next_state

        status, result_payload = state
        if status == "error":
            failure = result_payload if isinstance(result_payload, Exception) else RuntimeError(str(result_payload))
            failure_message = str(failure)[:500]
            failed_obj = _build_failed_response(
                response_id=response_id,
                created_at=created_at,
                model=model,
                requested_max_output_tokens=max_output_tokens,
                metadata=response_metadata,
                instructions=instructions,
                input_items=parsed_input.input_items,
                failure_message=failure_message,
                item_id=item_id,
                visible_text=f"Error: {failure_message}",
            )
            if _should_store_response(request):
                _store_response(
                    response_id=response_id,
                    response_obj=failed_obj,
                    input_items=parsed_input.input_items,
                    history_items=history_items,
                    principal_id=context.principal_id,
                    container=container,
                )
            for event in _failed_stream_events(
                sequence_fn=_next_sequence,
                failed_obj=failed_obj,
                failure_message=failure_message,
                item_id=item_id,
            ):
                yield event
            return

        tool_decision: _ToolShimDecision | None = None
        if status == "decision":
            if not isinstance(result_payload, _ToolShimDecision) or not isinstance(result_payload.upstream_result, UpstreamResult):
                failure_message = "invalid_upstream_result"
                failed_obj = _build_failed_response(
                    response_id=response_id,
                    created_at=created_at,
                    model=model,
                    requested_max_output_tokens=max_output_tokens,
                    metadata=response_metadata,
                    instructions=instructions,
                    input_items=parsed_input.input_items,
                    failure_message=failure_message,
                    item_id=item_id,
                    visible_text=f"Error: {failure_message}",
                )
                if _should_store_response(request):
                    _store_response(
                        response_id=response_id,
                        response_obj=failed_obj,
                        input_items=parsed_input.input_items,
                        history_items=history_items,
                        principal_id=context.principal_id,
                        container=container,
                    )
                for event in _failed_stream_events(
                    sequence_fn=_next_sequence,
                    failed_obj=failed_obj,
                    failure_message=failure_message,
                    item_id=item_id,
                ):
                    yield event
                return
            tool_decision = result_payload
            result = result_payload.upstream_result
        elif not isinstance(result_payload, UpstreamResult):
            failure_message = "invalid_upstream_result"
            failed_obj = _build_failed_response(
                response_id=response_id,
                created_at=created_at,
                model=model,
                requested_max_output_tokens=max_output_tokens,
                metadata=response_metadata,
                instructions=instructions,
                input_items=parsed_input.input_items,
                failure_message=failure_message,
                item_id=item_id,
                visible_text=f"Error: {failure_message}",
            )
            if _should_store_response(request):
                _store_response(
                    response_id=response_id,
                    response_obj=failed_obj,
                    input_items=parsed_input.input_items,
                    history_items=history_items,
                    principal_id=context.principal_id,
                    container=container,
                )
            for event in _failed_stream_events(
                sequence_fn=_next_sequence,
                failed_obj=failed_obj,
                failure_message=failure_message,
                item_id=item_id,
            ):
                yield event
            return

        else:
            result = result_payload
        stream_metadata = {
            **response_metadata,
            "upstream_provider": result.provider_key,
            "upstream_model": result.model,
            "provider_backend": result.provider_backend,
            "provider_account_name": result.provider_account_name,
            "provider_key_slot": result.provider_key_slot,
            "upstream_fallback_reason": result.fallback_reason,
        }
        history_items_to_store = list(history_items)
        if tool_decision and tool_decision.kind == "function_call":
            call_id = "call_" + uuid.uuid4().hex[:24]
            function_item_id = "fc_" + uuid.uuid4().hex[:24]
            arguments_json = _json_compact(tool_decision.arguments or {})
            in_progress_item = _function_call_item(
                item_id=function_item_id,
                call_id=call_id,
                name=tool_decision.tool_name,
                arguments="",
                status="in_progress",
            )
            yield _sse_event(
                event="response.output_item.added",
                sequence=_next_sequence(),
                data={
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": in_progress_item,
                },
            )
            yield _sse_event(
                event="response.function_call_arguments.delta",
                sequence=_next_sequence(),
                data={
                    "type": "response.function_call_arguments.delta",
                    "output_index": 0,
                    "item_id": function_item_id,
                    "delta": arguments_json,
                },
            )
            yield _sse_event(
                event="response.function_call_arguments.done",
                sequence=_next_sequence(),
                data={
                    "type": "response.function_call_arguments.done",
                    "output_index": 0,
                    "item_id": function_item_id,
                    "arguments": arguments_json,
                },
            )
            final_item = _function_call_item(
                item_id=function_item_id,
                call_id=call_id,
                name=tool_decision.tool_name,
                arguments=arguments_json,
                status="completed",
            )
            yield _sse_event(
                event="response.output_item.done",
                sequence=_next_sequence(),
                data={
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": final_item,
                },
            )
            history_items_to_store.append(final_item)
            completed_obj = _response_object(
                response_id=response_id,
                model=model,
                created_at=created_at,
                status="completed",
                output=[final_item],
                output_text="",
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                max_output_tokens=max_output_tokens,
                metadata=stream_metadata,
                instructions=instructions,
                input_items=parsed_input.input_items,
                reasoning=request.reasoning,
            )
        else:
            streamed_text = "".join(streamed_text_parts).replace(_SSE_KEEPALIVE_TEXT, "")
            text = streamed_text or (tool_decision.text if tool_decision else result.text)
            if not message_stream_open:
                for event in _open_message_stream():
                    yield event
                message_stream_open = True
            if prompt_route_trace_pending and text:
                prompt_route_trace_pending = False
                yield _sse_event(
                    event="response.output_text.delta",
                    sequence=_next_sequence(),
                    data={
                        "type": "response.output_text.delta",
                        "output_index": 0,
                        "item_id": item_id,
                        "content_index": 0,
                        "delta": prompt_route.trace_line,
                    },
                )
            if not streamed_text and text:
                yield _sse_event(
                    event="response.output_text.delta",
                    sequence=_next_sequence(),
                    data={
                        "type": "response.output_text.delta",
                        "output_index": 0,
                        "item_id": item_id,
                        "content_index": 0,
                        "delta": text,
                    },
                )

            yield _sse_event(
                event="response.output_text.done",
                sequence=_next_sequence(),
                data={
                    "type": "response.output_text.done",
                    "output_index": 0,
                    "item_id": item_id,
                    "content_index": 0,
                    "text": text,
                },
            )
            yield _sse_event(
                event="response.content_part.done",
                sequence=_next_sequence(),
                data={
                    "type": "response.content_part.done",
                    "output_index": 0,
                    "item_id": item_id,
                    "content_index": 0,
                    "part": {"type": "output_text", "text": text, "annotations": []},
                },
            )

            final_item = _message_item(item_id=item_id, text=text, status="completed")
            yield _sse_event(
                event="response.output_item.done",
                sequence=_next_sequence(),
                data={
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": final_item,
                },
            )
            history_items_to_store.append(final_item)
            completed_obj = _response_object(
                response_id=response_id,
                model=model,
                created_at=created_at,
                status="completed",
                output=[final_item],
                output_text=text,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                max_output_tokens=max_output_tokens,
                metadata=stream_metadata,
                instructions=instructions,
                input_items=parsed_input.input_items,
                reasoning=request.reasoning,
            )
        _set_stream_response_override(
            response_id=response_id,
            principal_id=context.principal_id,
            response_obj=in_progress_obj,
        )
        if _should_store_response(request):
            _store_response(
                response_id=response_id,
                response_obj=completed_obj,
                input_items=parsed_input.input_items,
                history_items=history_items_to_store,
                principal_id=context.principal_id,
                container=container,
            )
        _capture_responses_debug(
            name="response",
            payload={
                "principal_id": context.principal_id,
                "codex_profile": codex_profile,
                "response": completed_obj,
            },
        )

        yield _sse_event(
            event="response.completed",
            sequence=_next_sequence(),
            data={
                "type": "response.completed",
                "response": completed_obj,
            },
        )
        yield _sse_event(
            event="response.done",
            sequence=_next_sequence(),
            data={
                "type": "response.done",
                "response": completed_obj,
            },
        )
        yield _sse_done()

    return StreamingResponse(
        _iter_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@models_router.get("", response_model=_ModelListObject)
def list_models(request: Request) -> Response:
    return JSONResponse(
        {
            "object": "list",
            "data": list_response_models(),
        }
    )


@responses_item_router.get("/_provider_health", response_model=None)
def get_provider_health(
    *,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
    lightweight: bool = Query(default=False),
) -> Response:
    include_sensitive = is_operator_context(context)
    provider_health = _provider_health_snapshot(lightweight=lightweight)
    safe_provider_health = _redacted_provider_health(provider_health, include_sensitive=include_sensitive)
    return JSONResponse(
        {
            **safe_provider_health,
            "principal": principal_identity_summary(context.principal_id),
            "provider_registry": _provider_registry_payload(
                container=container,
                principal_id=context.principal_id,
                provider_health=safe_provider_health,
                include_sensitive=include_sensitive,
            ),
        }
    )


@responses_item_router.get("/{response_id}", response_model=_ResponseObject)
def get_response(
    response_id: str,
    *,
    context: RequestContext = Depends(get_request_context),
    container: object = Depends(get_container),
) -> Response:
    override = _stream_response_override(
        response_id=response_id,
        principal_id=context.principal_id,
    )
    if override is not None:
        return JSONResponse(override)
    stored = _load_response_for_runtime(
        response_id=response_id,
        principal_id=context.principal_id,
        container=container,
    )
    return JSONResponse(stored.response)


@responses_item_router.get("/{response_id}/input_items", response_model=_ResponseInputItemsListObject)
def get_response_input_items(
    response_id: str,
    *,
    context: RequestContext = Depends(get_request_context),
    container: object = Depends(get_container),
) -> Response:
    stored = _load_response(
        response_id=response_id,
        principal_id=context.principal_id,
        container=container,
    )
    return JSONResponse(
        {
            "object": "list",
            "response_id": response_id,
            "data": [dict(item) for item in stored.input_items],
        }
    )


@responses_item_router.post(
    "",
    response_model=_ResponseObject,
    responses={
        200: {
            "description": "Returns JSON when stream=false, SSE when stream=true.",
            "content": {
                "text/event-stream": {
                    "schema": {
                        "type": "string",
                        "example": "event: response.created\\ndata: {\"type\":\"response.created\"}\\n\\ndata: [DONE]\\n\\n",
                    }
                }
            },
        }
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": _RESPONSES_CREATE_REQUEST_SCHEMA,
                }
            },
        }
    },
)
def create_response(
    payload: dict[str, object],
    *,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    container: object = Depends(get_container),
) -> Response:
    header_profile = str(request.headers.get("X-EA-Codex-Profile") or request.headers.get("X-CodexEA-Profile") or "").strip().lower()
    preferred_onemin_labels = _preferred_onemin_labels_from_request(request)
    if header_profile == "jury":
        header_profile = "audit"
    if header_profile == "review-light":
        header_profile = "review_light"
    if header_profile not in {"core", "core_batch", "core_rescue", "easy", "repair", "groundwork", "review_light", "survival", "audit"}:
        header_profile = ""
    return _run_response(
        payload,
        context=context,
        container=container,
        codex_profile=header_profile or None,
        preferred_onemin_labels=preferred_onemin_labels,
    )


@codex_router.post(
    "/core",
    response_model=_ResponseObject,
    responses={
        200: {
            "description": "Returns JSON when stream=false, SSE when stream=true.",
            "content": {
                "text/event-stream": {
                    "schema": {
                        "type": "string",
                        "example": "event: response.created\\ndata: {\"type\":\"response.created\"}\\n\\ndata: [DONE]\\n\\n",
                    }
                }
            },
        }
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": _RESPONSES_CREATE_REQUEST_SCHEMA,
                }
            },
        }
    },
)
def create_codex_core(
    payload: dict[str, object],
    *,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    container: object = Depends(get_container),
) -> Response:
    normalized = _normalize_payload_for_profile(
        payload,
        profile="core",
        container=container,
        principal_id=context.principal_id,
    )
    return _run_response(
        normalized,
        context=context,
        container=container,
        codex_profile="core",
        preferred_onemin_labels=_preferred_onemin_labels_from_request(request),
    )


@codex_router.post(
    "/core-batch",
    response_model=_ResponseObject,
    responses={
        202: {
            "description": "Returns an in-progress response object for background core batch execution.",
        }
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": _RESPONSES_CREATE_REQUEST_SCHEMA,
                }
            },
        }
    },
)
def create_codex_core_batch(
    payload: dict[str, object],
    *,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    container: object = Depends(get_container),
) -> Response:
    normalized = _normalize_payload_for_profile(
        payload,
        profile="core_batch",
        container=container,
        principal_id=context.principal_id,
    )
    return _run_response(
        normalized,
        context=context,
        container=container,
        codex_profile="core_batch",
        preferred_onemin_labels=_preferred_onemin_labels_from_request(request),
    )


@codex_router.post(
    "/core-rescue",
    response_model=_ResponseObject,
    responses={
        200: {
            "description": "Returns JSON when stream=false, SSE when stream=true.",
            "content": {
                "text/event-stream": {
                    "schema": {
                        "type": "string",
                        "example": "event: response.created\\ndata: {\"type\":\"response.created\"}\\n\\ndata: [DONE]\\n\\n",
                    }
                }
            },
        }
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": _RESPONSES_CREATE_REQUEST_SCHEMA,
                }
            },
        }
    },
)
def create_codex_core_rescue(
    payload: dict[str, object],
    *,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    container: object = Depends(get_container),
) -> Response:
    normalized = _normalize_payload_for_profile(
        payload,
        profile="core_rescue",
        container=container,
        principal_id=context.principal_id,
    )
    return _run_response(
        normalized,
        context=context,
        container=container,
        codex_profile="core_rescue",
        preferred_onemin_labels=_preferred_onemin_labels_from_request(request),
    )


@codex_router.post(
    "/easy",
    response_model=_ResponseObject,
    responses={
        200: {
            "description": "Returns JSON when stream=false, SSE when stream=true.",
            "content": {
                "text/event-stream": {
                    "schema": {
                        "type": "string",
                        "example": "event: response.created\\ndata: {\"type\":\"response.created\"}\\n\\ndata: [DONE]\\n\\n",
                    }
                }
            },
        }
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": _RESPONSES_CREATE_REQUEST_SCHEMA,
                }
            },
        }
    },
)
def create_codex_easy(
    payload: dict[str, object],
    *,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    container: object = Depends(get_container),
) -> Response:
    normalized = _normalize_payload_for_profile(
        payload,
        profile="easy",
        container=container,
        principal_id=context.principal_id,
    )
    return _run_response(
        normalized,
        context=context,
        container=container,
        codex_profile="easy",
        preferred_onemin_labels=_preferred_onemin_labels_from_request(request),
    )


@codex_router.post(
    "/repair",
    response_model=_ResponseObject,
    responses={
        200: {
            "description": "Returns JSON when stream=false, SSE when stream=true.",
            "content": {
                "text/event-stream": {
                    "schema": {
                        "type": "string",
                        "example": "event: response.created\\ndata: {\"type\":\"response.created\"}\\n\\ndata: [DONE]\\n\\n",
                    }
                }
            },
        }
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": _RESPONSES_CREATE_REQUEST_SCHEMA,
                }
            },
        }
    },
)
def create_codex_repair(
    payload: dict[str, object],
    *,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    container: object = Depends(get_container),
) -> Response:
    normalized = _normalize_payload_for_profile(
        payload,
        profile="repair",
        container=container,
        principal_id=context.principal_id,
    )
    return _run_response(
        normalized,
        context=context,
        container=container,
        codex_profile="repair",
        preferred_onemin_labels=_preferred_onemin_labels_from_request(request),
    )


@codex_router.post(
    "/groundwork",
    response_model=_ResponseObject,
    responses={
        200: {
            "description": "Returns JSON when stream=false, SSE when stream=true.",
            "content": {
                "text/event-stream": {
                    "schema": {
                        "type": "string",
                        "example": "event: response.created\\ndata: {\"type\":\"response.created\"}\\n\\ndata: [DONE]\\n\\n",
                    }
                }
            },
        }
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": _RESPONSES_CREATE_REQUEST_SCHEMA,
                }
            },
        }
    },
)
def create_codex_groundwork(
    payload: dict[str, object],
    *,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    container: object = Depends(get_container),
) -> Response:
    normalized = _normalize_payload_for_profile(
        payload,
        profile="groundwork",
        container=container,
        principal_id=context.principal_id,
    )
    return _run_response(
        normalized,
        context=context,
        container=container,
        codex_profile="groundwork",
        preferred_onemin_labels=_preferred_onemin_labels_from_request(request),
    )


@codex_router.post(
    "/review-light",
    response_model=_ResponseObject,
    responses={
        200: {
            "description": "Returns JSON when stream=false, SSE when stream=true.",
            "content": {
                "text/event-stream": {
                    "schema": {
                        "type": "string",
                        "example": "event: response.created\\ndata: {\"type\":\"response.created\"}\\n\\ndata: [DONE]\\n\\n",
                    }
                }
            },
        }
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": _RESPONSES_CREATE_REQUEST_SCHEMA,
                }
            },
        }
    },
)
def create_codex_review_light(
    payload: dict[str, object],
    *,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    container: object = Depends(get_container),
) -> Response:
    normalized = _normalize_payload_for_profile(
        payload,
        profile="review_light",
        container=container,
        principal_id=context.principal_id,
    )
    return _run_response(
        normalized,
        context=context,
        container=container,
        codex_profile="review_light",
        preferred_onemin_labels=_preferred_onemin_labels_from_request(request),
    )


@codex_router.post(
    "/survival",
    response_model=_ResponseObject,
    responses={
        202: {
            "description": "Returns an in-progress response object for background survival execution.",
        }
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": _RESPONSES_CREATE_REQUEST_SCHEMA,
                }
            },
        }
    },
)
def create_codex_survival(
    payload: dict[str, object],
    *,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    container: object = Depends(get_container),
) -> Response:
    normalized = _normalize_payload_for_profile(
        payload,
        profile="survival",
        container=container,
        principal_id=context.principal_id,
    )
    return _run_response(
        normalized,
        context=context,
        container=container,
        codex_profile="survival",
        preferred_onemin_labels=_preferred_onemin_labels_from_request(request),
    )


@codex_router.post(
    "/audit",
    response_model=_ResponseObject,
    responses={
        200: {
            "description": "Returns JSON when stream=false, SSE when stream=true.",
            "content": {
                "text/event-stream": {
                    "schema": {
                        "type": "string",
                        "example": "event: response.created\\ndata: {\"type\":\"response.created\"}\\n\\ndata: [DONE]\\n\\n",
                    }
                }
            },
        }
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": _RESPONSES_CREATE_REQUEST_SCHEMA,
                }
            },
        }
    },
)
def create_codex_audit(
    payload: dict[str, object],
    *,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    container: AppContainer = Depends(get_container),
) -> Response:
    normalized = _normalize_payload_for_profile(
        payload,
        profile="audit",
        container=container,
        principal_id=context.principal_id,
    )
    return _run_response(
        normalized,
        context=context,
        container=container,
        codex_profile="audit",
        preferred_onemin_labels=_preferred_onemin_labels_from_request(request),
    )


@codex_router.get("/profiles")
def list_codex_profiles(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> Response:
    include_sensitive = is_operator_context(context)
    provider_health = _provider_health_snapshot(lightweight=(not include_sensitive))
    safe_provider_health = _redacted_provider_health(provider_health, include_sensitive=include_sensitive)
    profiles = [
        {**profile, "provider_hint_order": list(profile["provider_hint_order"])}
        for profile in _codex_profiles(
            container=container,
            principal_id=context.principal_id,
            provider_health=provider_health,
        )
    ]
    return JSONResponse(
        {
            "principal": principal_identity_summary(context.principal_id),
            "governance": _codex_governance_payload(),
            "profiles": _attach_provider_slot_state(
                profiles,
                provider_health=safe_provider_health,
                include_sensitive=include_sensitive,
            ),
            "provider_health": safe_provider_health,
            "provider_registry": _provider_registry_payload(
                container=container,
                principal_id=context.principal_id,
                provider_health=safe_provider_health,
                include_sensitive=include_sensitive,
            ),
        }
    )


@codex_router.get("/status")
def get_codex_status(
    window: str = "1h",
    refresh: bool = False,
    compact: bool = False,
    context: RequestContext = Depends(get_request_context),
) -> Response:
    _ = refresh
    profile_health = _provider_health_snapshot(lightweight=(not is_operator_context(context)))
    if is_operator_context(context):
        report = codex_status_report(window=window, provider_health=profile_health, compact=compact)
    else:
        report = dict(
            codex_status_report(
                window=window,
                principal_id=context.principal_id,
                provider_health=profile_health,
                compact=compact,
            )
        )
        report["fleet_burn"] = {}
    report["governance"] = _codex_governance_payload()
    return JSONResponse(report)


router.include_router(models_router)
router.include_router(responses_item_router)
router.include_router(codex_router)
