"""Governed, fail-closed VocalLab HTTP adapter for authorized segments."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import stat
import threading
import time
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

import requests

from app.services.audiobook_tts.authorities import (
    AuthorityError,
    VocalLabAuthorityStore,
    VOCALLAB_PROVIDER_CONTRACT_VERSION,
)
from app.services.audiobook_tts.budget_ledger import (
    AccountBalance,
    BudgetLedgerError,
    BudgetReservation,
    VocalLabBudgetLedger,
)
from app.services.audiobook_tts.contracts import (
    ProviderName,
    SpeechSynthesisRequest,
    SpeechSynthesisResult,
    synthesis_fingerprint,
)
from app.services.audiobook_tts.errors import AudiobookProviderError, ProviderFailure
from app.services.audiobook_tts.output_validation import (
    AudioOutputValidationError,
    ValidatedAudio,
    decode_inline_audio,
)
from app.services.audiobook_tts.providers.base import BaseAudiobookTtsProvider
from app.services.audiobook_tts.providers.vocallab_schema import (
    GenerationObservation,
    VOCALLAB_GENERATION_FAILED,
    VOCALLAB_GENERATION_PENDING,
    VOCALLAB_GENERATION_SUCCESS,
    VOCALLAB_MODEL_KEYS,
    VocalLabSchemaError,
    parse_account,
    parse_generation,
    parse_models,
    parse_ping,
    parse_voices,
)
from app.services.audiobook_tts.voice_catalog import (
    VocalLabVoiceCatalog,
    VoiceCatalogError,
)


VOCALLAB_DEFAULT_BASE_URL = "https://api.vocallab.ai"
VOCALLAB_MODELS = frozenset(VOCALLAB_MODEL_KEYS)
_API_KEY_RE = re.compile(r"^vl_live_[A-Za-z0-9_-]{16,160}$")
_MAX_JSON_BYTES = 2 * 1024 * 1024
_DEFAULT_KEY_FILE = "config/vocallab_api_key"
_DEFAULT_ACCOUNT_STATE_ROOT = "/data/provider-ledger/vocallab"
_ABSOLUTE_KEY_ROOTS = (
    Path("/run/secrets"),
    Path("/var/run/secrets"),
    Path("/etc/ea/secrets"),
)

PERFORMANCE_DIRECTION_MAP: Mapping[str, str] = {
    "neutral": "",
    "warm": "[speak warmly at a natural pace]",
    "calm": "[speak calmly and reassuringly]",
    "tense": "[speak with restrained tension and deliberate pacing]",
    "whisper": "[whisper quietly with clear articulation]",
    "angry_restrained": (
        "[speak as if holding back anger with precise articulation]"
    ),
}


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("nonfinite_json_number")


def _approved_key_path(value: str) -> Path:
    candidate = Path(value)
    if any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError("vocallab_key_file_path_invalid")
    if candidate.is_absolute():
        resolved = candidate.absolute()
        if not any(
            resolved == root or resolved.is_relative_to(root)
            for root in _ABSOLUTE_KEY_ROOTS
        ):
            raise ValueError("vocallab_key_file_path_invalid")
        return resolved
    if candidate.parts != ("config", "vocallab_api_key"):
        raise ValueError("vocallab_key_file_path_invalid")
    root = (Path.cwd() / "config").absolute()
    resolved_parent = (Path.cwd() / candidate).absolute().parent
    if resolved_parent != root:
        raise ValueError("vocallab_key_file_path_invalid")
    return resolved_parent / candidate.name


def _read_private_key_file(path: Path) -> str:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:-1]:
        current /= part
        try:
            component = current.lstat()
        except OSError:
            raise ValueError("vocallab_key_file_unavailable") from None
        if stat.S_ISLNK(component.st_mode) or not stat.S_ISDIR(component.st_mode):
            raise ValueError("vocallab_key_file_unsafe")
    try:
        parent_before = absolute.parent.lstat()
        if (
            stat.S_ISLNK(parent_before.st_mode)
            or not stat.S_ISDIR(parent_before.st_mode)
            or parent_before.st_uid != os.geteuid()
            or stat.S_IMODE(parent_before.st_mode) & 0o022
        ):
            raise ValueError("vocallab_key_file_unsafe")
    except ValueError:
        raise
    except OSError:
        raise ValueError("vocallab_key_file_unavailable") from None
    parent_fd = -1
    descriptor = -1
    try:
        parent_fd = os.open(
            absolute.parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        parent_opened = os.fstat(parent_fd)
        if (parent_opened.st_dev, parent_opened.st_ino) != (
            parent_before.st_dev,
            parent_before.st_ino,
        ):
            raise ValueError("vocallab_key_file_identity_changed")
        before = os.stat(
            absolute.name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
            or before.st_size <= 0
            or before.st_size > 4096
        ):
            raise ValueError("vocallab_key_file_unsafe")
        descriptor = os.open(
            absolute.name,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_fd,
        )
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.geteuid()
            or stat.S_IMODE(opened.st_mode) != 0o600
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            or opened.st_size != before.st_size
        ):
            raise ValueError("vocallab_key_file_unsafe")
        chunks: list[bytes] = []
        received = 0
        while True:
            chunk = os.read(descriptor, min(4097 - received, 4096))
            if not chunk:
                break
            chunks.append(chunk)
            received += len(chunk)
            if received > 4096:
                raise ValueError("vocallab_key_file_unsafe")
        raw = b"".join(chunks)
        after = os.stat(
            absolute.name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        parent_after = absolute.parent.lstat()
        identity = (
            "st_dev",
            "st_ino",
            "st_size",
            "st_mode",
            "st_uid",
            "st_nlink",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if (
            any(getattr(after, name) != getattr(before, name) for name in identity)
            or (
                parent_after.st_dev,
                parent_after.st_ino,
                parent_after.st_mode,
                parent_after.st_uid,
                parent_after.st_nlink,
            )
            != (
                parent_before.st_dev,
                parent_before.st_ino,
                parent_before.st_mode,
                parent_before.st_uid,
                parent_before.st_nlink,
            )
        ):
            raise ValueError("vocallab_key_file_identity_changed")
    except ValueError:
        raise
    except OSError:
        raise ValueError("vocallab_key_file_unavailable") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if parent_fd >= 0:
            os.close(parent_fd)
    try:
        value = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        raise ValueError("vocallab_key_file_invalid") from None
    if not value or "\n" in value or "\r" in value:
        raise ValueError("vocallab_key_file_invalid")
    return value


class VocalLabProviderVerification:
    """Legacy direct construction is deliberately non-authoritative."""

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("authenticated_verification_loader_required")


@dataclass(frozen=True, slots=True)
class VocalLabConfig:
    enabled: bool = False
    auto_render_enabled: bool = False
    credential_rotation_required: bool = True
    credential_production_eligible: bool = False
    allow_cross_provider_fallback: bool = False
    allow_clones: bool = False
    allow_community_voices: bool = False
    allow_persona: bool = False
    allow_lite_publication: bool = False
    base_url: str = VOCALLAB_DEFAULT_BASE_URL
    api_key: str = field(default="", repr=False)
    account_state_root: str = _DEFAULT_ACCOUNT_STATE_ROOT
    model: str = "v-pro"
    expressive_model: str = "v-studio"
    draft_model: str = "v-lite"
    max_chars_per_request: int = 1800
    requests_per_minute: int = 30
    max_in_flight: int = 1
    timeout_seconds: int = 120
    poll_interval_seconds: float = 2.0
    poll_timeout_seconds: int = 180
    output_format: str = "wav"
    sample_rate: int = 44100
    max_audio_bytes: int = 32 * 1024 * 1024
    verification_max_age_hours: int = 24
    allowed_download_hosts: tuple[str, ...] = ()
    allowed_voice_classes: tuple[str, ...] = (
        "professional",
        "consented_clone",
    )

    @classmethod
    def from_environment(cls) -> "VocalLabConfig":
        def flag(name: str, default: str = "0") -> bool:
            raw = os.getenv(name, default).strip()
            if raw not in {"0", "1"}:
                raise ValueError("vocallab_configuration_invalid")
            return raw == "1"

        def integer(name: str, default: int) -> int:
            try:
                return int(os.getenv(name, str(default)).strip())
            except ValueError:
                raise ValueError("vocallab_configuration_invalid") from None

        try:
            poll_interval = float(
                os.getenv("EA_AUDIOBOOK_VOCALLAB_POLL_INTERVAL_SECONDS", "2")
            )
        except ValueError:
            raise ValueError("vocallab_configuration_invalid") from None
        enabled = flag("EA_AUDIOBOOK_VOCALLAB_ENABLED")
        credential_rotation_required = flag(
            "EA_AUDIOBOOK_VOCALLAB_CREDENTIAL_ROTATION_REQUIRED",
            "1",
        )
        credential_production_eligible = flag(
            "EA_AUDIOBOOK_VOCALLAB_CREDENTIAL_PRODUCTION_ELIGIBLE",
            "0",
        )
        environment_key = os.getenv("VOCALLAB_API_KEY", "").strip()
        key_file_value = os.getenv("VOCALLAB_API_KEY_FILE", "").strip()
        file_key = ""
        if key_file_value and (enabled or environment_key):
            path = _approved_key_path(key_file_value)
            if path.exists() or path.is_symlink():
                file_key = _read_private_key_file(path)
            elif key_file_value != _DEFAULT_KEY_FILE:
                raise ValueError("vocallab_key_file_unavailable")
        if environment_key and file_key and environment_key != file_key:
            raise ValueError("vocallab_key_sources_disagree")
        classes = tuple(
            value.strip().lower()
            for value in os.getenv(
                "EA_AUDIOBOOK_VOCALLAB_ALLOWED_VOICE_CLASSES",
                "professional,consented_clone",
            ).split(",")
            if value.strip()
        )
        return cls(
            enabled=enabled,
            auto_render_enabled=flag("EA_AUDIOBOOK_VOCALLAB_AUTO_RENDER"),
            credential_rotation_required=credential_rotation_required,
            credential_production_eligible=credential_production_eligible,
            allow_cross_provider_fallback=flag(
                "EA_AUDIOBOOK_TTS_ALLOW_CROSS_PROVIDER_FALLBACK"
            ),
            allow_clones=flag("EA_AUDIOBOOK_VOCALLAB_ALLOW_CLONES"),
            allow_community_voices=flag(
                "EA_AUDIOBOOK_VOCALLAB_ALLOW_COMMUNITY_VOICES"
            ),
            allow_persona=flag("EA_AUDIOBOOK_VOCALLAB_ALLOW_PERSONA"),
            allow_lite_publication=flag(
                "EA_AUDIOBOOK_VOCALLAB_ALLOW_LITE_PUBLICATION"
            ),
            base_url=os.getenv(
                "EA_AUDIOBOOK_VOCALLAB_BASE_URL", VOCALLAB_DEFAULT_BASE_URL
            ).strip(),
            api_key=environment_key or file_key,
            account_state_root=os.getenv(
                "EA_AUDIOBOOK_VOCALLAB_ACCOUNT_STATE_ROOT",
                _DEFAULT_ACCOUNT_STATE_ROOT,
            ).strip(),
            model=os.getenv("EA_AUDIOBOOK_VOCALLAB_MODEL", "v-pro").strip(),
            expressive_model=os.getenv(
                "EA_AUDIOBOOK_VOCALLAB_EXPRESSIVE_MODEL", "v-studio"
            ).strip(),
            draft_model=os.getenv(
                "EA_AUDIOBOOK_VOCALLAB_DRAFT_MODEL", "v-lite"
            ).strip(),
            max_chars_per_request=integer(
                "EA_AUDIOBOOK_VOCALLAB_MAX_CHARS_PER_REQUEST", 1800
            ),
            requests_per_minute=integer(
                "EA_AUDIOBOOK_VOCALLAB_REQUESTS_PER_MINUTE", 30
            ),
            max_in_flight=integer("EA_AUDIOBOOK_VOCALLAB_MAX_IN_FLIGHT", 1),
            timeout_seconds=integer(
                "EA_AUDIOBOOK_VOCALLAB_TIMEOUT_SECONDS", 120
            ),
            poll_interval_seconds=poll_interval,
            poll_timeout_seconds=integer(
                "EA_AUDIOBOOK_VOCALLAB_POLL_TIMEOUT_SECONDS", 180
            ),
            output_format=os.getenv(
                "EA_AUDIOBOOK_VOCALLAB_OUTPUT_FORMAT", "WAV"
            ).strip().lower(),
            sample_rate=integer("EA_AUDIOBOOK_VOCALLAB_SAMPLE_RATE", 44100),
            max_audio_bytes=integer(
                "EA_AUDIOBOOK_VOCALLAB_MAX_AUDIO_BYTES", 32 * 1024 * 1024
            ),
            verification_max_age_hours=integer(
                "EA_AUDIOBOOK_VOCALLAB_VERIFICATION_MAX_AGE_HOURS", 24
            ),
            allowed_download_hosts=tuple(
                host.strip().lower()
                for host in os.getenv(
                    "EA_AUDIOBOOK_VOCALLAB_ALLOWED_AUDIO_HOSTS", ""
                ).split(",")
                if host.strip()
            ),
            allowed_voice_classes=classes,
        )


class VocalLabProvider(BaseAudiobookTtsProvider):
    name: ProviderName = "vocallab"

    def __init__(
        self,
        *,
        config: VocalLabConfig | None = None,
        voice_catalog: VocalLabVoiceCatalog | None = None,
        budget_ledger: VocalLabBudgetLedger | None = None,
        authority_store: VocalLabAuthorityStore | None = None,
        verification: object | None = None,
        session: requests.Session | Any | None = None,
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if verification is not None:
            raise ValueError("authenticated_verification_loader_required")
        self.config = config or VocalLabConfig.from_environment()
        self._validate_configuration()
        self._voice_catalog = voice_catalog
        self._budget = budget_ledger
        self._authorities = authority_store
        self._session = session or requests.Session()
        if hasattr(self._session, "trust_env"):
            self._session.trust_env = False
        self._now = now or (lambda: datetime.now(UTC))
        self._monotonic = monotonic
        self._sleep = sleeper
        self._post_lock = threading.Lock()

    def _validate_configuration(self) -> None:
        try:
            parsed = urlsplit(self.config.base_url)
            port = parsed.port
        except ValueError:
            raise ValueError("vocallab_configuration_invalid") from None
        numeric_ints = (
            self.config.max_chars_per_request,
            self.config.requests_per_minute,
            self.config.max_in_flight,
            self.config.timeout_seconds,
            self.config.poll_timeout_seconds,
            self.config.sample_rate,
            self.config.max_audio_bytes,
            self.config.verification_max_age_hours,
        )
        boolean_flags = (
            self.config.enabled,
            self.config.auto_render_enabled,
            self.config.credential_rotation_required,
            self.config.credential_production_eligible,
            self.config.allow_cross_provider_fallback,
            self.config.allow_clones,
            self.config.allow_community_voices,
            self.config.allow_persona,
            self.config.allow_lite_publication,
        )
        state_root = Path(self.config.account_state_root)
        if (
            parsed.scheme.lower() != "https"
            or str(parsed.hostname or "").lower() != "api.vocallab.ai"
            or parsed.username is not None
            or parsed.password is not None
            or port not in {None, 443}
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or any(type(value) is not int for value in numeric_ints)
            or any(type(value) is not bool for value in boolean_flags)
            or self.config.credential_rotation_required
            == self.config.credential_production_eligible
            or (
                self.config.enabled
                and (
                    self.config.credential_rotation_required
                    or not self.config.credential_production_eligible
                )
            )
            or self.config.model != "v-pro"
            or self.config.expressive_model != "v-studio"
            or self.config.draft_model != "v-lite"
            or not 1 <= self.config.max_chars_per_request <= 1800
            or not 1 <= self.config.requests_per_minute <= 30
            or self.config.max_in_flight != 1
            or self.config.timeout_seconds < 1
            or type(self.config.poll_interval_seconds) not in {int, float}
            or isinstance(self.config.poll_interval_seconds, bool)
            or not math.isfinite(float(self.config.poll_interval_seconds))
            or self.config.poll_interval_seconds <= 0
            or self.config.poll_timeout_seconds < 1
            or self.config.output_format != "wav"
            or self.config.sample_rate != 44100
            or not 1024 <= self.config.max_audio_bytes <= 32 * 1024 * 1024
            or self.config.verification_max_age_hours != 24
            or self.config.allowed_download_hosts != ()
            or self.config.allow_clones
            or self.config.allowed_voice_classes
            != ("professional", "consented_clone")
            or not state_root.is_absolute()
            or any(part in {"", ".", ".."} for part in state_root.parts)
        ):
            raise ValueError("vocallab_configuration_invalid")

    def _credential_binding_sha256(self) -> str:
        return hashlib.sha256(self.config.api_key.encode("utf-8")).hexdigest()

    @staticmethod
    def _failure(
        code: str,
        *,
        retryable: bool = False,
        charge_state: str = "not_charged",
        retry_after_seconds: int = 0,
    ) -> AudiobookProviderError:
        return AudiobookProviderError(
            ProviderFailure(
                provider="vocallab",
                code=code,
                retryable=retryable,
                charge_state=charge_state,  # type: ignore[arg-type]
                retry_after_seconds=retry_after_seconds,
                public_reason=code,
            )
        )

    def _record_upstream_failure(self) -> None:
        if self._budget is None:
            raise self._failure("budget_ledger_missing")
        try:
            self._budget.record_upstream_failure()
        except BudgetLedgerError as exc:
            raise self._failure(exc.code) from None

    def _record_provider_success(self) -> None:
        if self._budget is None:
            raise self._failure("budget_ledger_missing")
        try:
            self._budget.record_provider_success()
        except BudgetLedgerError as exc:
            raise self._failure(exc.code) from None

    def _require_enabled(self) -> None:
        if not self.config.enabled:
            raise self._failure("provider_disabled")
        if not _API_KEY_RE.fullmatch(self.config.api_key):
            raise self._failure("authentication_configuration_invalid")

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, object] | None = None,
        spending_post: bool = False,
    ) -> dict[str, Any]:
        self._pace_http_request()
        response: Any | None = None
        charge_state = "unknown" if spending_post else "not_charged"
        try:
            response = self._session.request(
                method,
                f"{self.config.base_url.rstrip('/')}/api/v1/{path.lstrip('/')}",
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json=dict(payload) if payload is not None else None,
                timeout=self.config.timeout_seconds,
                allow_redirects=False,
                stream=True,
            )
            status = getattr(response, "status_code", None)
            if type(status) is not int:
                raise self._failure(
                    "invalid_provider_response", charge_state=charge_state
                )
            if 300 <= status < 400:
                raise self._failure(
                    "invalid_provider_response", charge_state=charge_state
                )
            if status < 200 or status >= 300:
                retry_after = 0
                header = str(
                    getattr(response, "headers", {}).get("Retry-After") or ""
                )
                if header.isdigit():
                    retry_after = min(int(header), 3600)
                mapping = {
                    401: ("authentication_failed", False),
                    402: ("balance_exhausted", False),
                    403: ("plan_or_api_access_denied", False),
                    413: ("input_too_long", False),
                    429: ("rate_limited", True),
                }
                code, retryable = mapping.get(
                    status,
                    (
                        "upstream_unavailable"
                        if status >= 500
                        else "invalid_request",
                        status >= 500,
                    ),
                )
                error_charge = charge_state
                if spending_post:
                    retryable = False
                raise self._failure(
                    code,
                    retryable=retryable,
                    charge_state=error_charge,
                    retry_after_seconds=retry_after,
                )
            headers = getattr(response, "headers", {})
            content_type = str(headers.get("Content-Type") or "")
            if content_type.split(";", 1)[0].strip().lower() != "application/json":
                raise self._failure(
                    "invalid_provider_response", charge_state=charge_state
                )
            declared = str(headers.get("Content-Length") or "")
            if declared:
                if not declared.isdigit() or int(declared) > _MAX_JSON_BYTES:
                    raise self._failure(
                        "invalid_provider_response", charge_state=charge_state
                    )
            iterator = getattr(response, "iter_content", None)
            if not callable(iterator):
                raise self._failure(
                    "invalid_provider_response", charge_state=charge_state
                )
            chunks: list[bytes] = []
            received = 0
            for chunk in iterator(chunk_size=65536):
                if not isinstance(chunk, bytes):
                    raise self._failure(
                        "invalid_provider_response", charge_state=charge_state
                    )
                if not chunk:
                    continue
                received += len(chunk)
                if received > _MAX_JSON_BYTES:
                    raise self._failure(
                        "invalid_provider_response", charge_state=charge_state
                    )
                chunks.append(chunk)
            try:
                parsed = json.loads(
                    b"".join(chunks).decode("utf-8"),
                    object_pairs_hook=_strict_json_object,
                    parse_constant=_reject_json_constant,
                )
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                raise self._failure(
                    "invalid_provider_response", charge_state=charge_state
                ) from None
            if not isinstance(parsed, dict):
                raise self._failure(
                    "invalid_provider_response", charge_state=charge_state
                )
            return parsed
        except AudiobookProviderError as exc:
            if exc.failure.code == "upstream_unavailable":
                self._record_upstream_failure()
            raise
        except Exception:
            self._record_upstream_failure()
            raise self._failure(
                "upstream_unavailable",
                retryable=not spending_post,
                charge_state=charge_state,
            ) from None
        finally:
            if response is not None:
                close = getattr(response, "close", None)
                if callable(close):
                    close()

    @staticmethod
    def _parse_balance(payload: Mapping[str, Any]) -> AccountBalance:
        try:
            observation = parse_account(payload)
        except VocalLabSchemaError:
            raise VocalLabProvider._failure("invalid_provider_response")
        return AccountBalance(monthly_points=observation.points, topup_points=0)

    @staticmethod
    def _parse_models(payload: Mapping[str, Any]) -> tuple[str, ...]:
        try:
            return tuple(model.key for model in parse_models(payload))
        except VocalLabSchemaError:
            raise VocalLabProvider._failure("invalid_provider_response")

    @staticmethod
    def _parse_voices(payload: Mapping[str, Any]) -> tuple[dict[str, object], ...]:
        try:
            observations = parse_voices(payload)
        except VocalLabSchemaError:
            raise VocalLabProvider._failure("invalid_provider_response")
        return tuple(
            {
                "provider_voice_id_private": observation.provider_voice_id,
                "voice_id_sha256": hashlib.sha256(
                    observation.provider_voice_id.encode("utf-8")
                ).hexdigest(),
                "safe_label": observation.name,
                "languages": observation.languages,
                "provider_type": observation.provider_type,
            }
            for observation in observations
        )

    def verify_capability(self) -> dict[str, object]:
        """Return GET-only observations; never install runtime authority."""

        self._require_enabled()
        try:
            parse_ping(self._request_json("GET", "ping"))
        except VocalLabSchemaError:
            raise self._failure("provider_ping_failed")
        self._record_provider_success()
        balance = self._parse_balance(self._request_json("GET", "me"))
        self._record_provider_success()
        models = self._parse_models(self._request_json("GET", "models"))
        self._record_provider_success()
        voices = self._parse_voices(self._request_json("GET", "voices"))
        self._record_provider_success()
        return {
            "provider": self.name,
            "status": "observed_not_authorized",
            "provider_contract_version": VOCALLAB_PROVIDER_CONTRACT_VERSION,
            "ping_observed": True,
            "account_access_observed": True,
            "balance_present": balance.monthly_points >= 0,
            "exact_balance_exposed": False,
            "models": list(models),
            "voice_count": len(voices),
            "raw_voice_ids_exposed": False,
            "runtime_authority_installed": False,
        }

    def list_voices(self) -> tuple[dict[str, object], ...]:
        self._require_enabled()
        voices = self._parse_voices(self._request_json("GET", "voices"))
        self._record_provider_success()
        return voices

    @staticmethod
    def _valid_step(value: object, *, minimum: str, maximum: str) -> bool:
        if type(value) not in {int, float} or not math.isfinite(float(value)):
            return False
        try:
            number = Decimal(str(value))
            lower = Decimal(minimum)
            upper = Decimal(maximum)
        except InvalidOperation:
            return False
        return lower <= number <= upper and number * 20 == (number * 20).to_integral()

    def _provider_text(self, request: SpeechSynthesisRequest) -> str:
        direction_name = request.performance_direction or "neutral"
        if direction_name not in PERFORMANCE_DIRECTION_MAP:
            raise self._failure("performance_direction_not_allowed")
        direction = PERFORMANCE_DIRECTION_MAP[direction_name]
        if direction and request.model != "v-studio":
            raise self._failure("performance_direction_model_mismatch")
        if request.model == "v-studio" and (
            "[" in request.source_text or "]" in request.source_text
        ):
            raise self._failure("studio_source_control_tokens_blocked")
        provider_text = (
            f"{direction}\n{request.source_text}" if direction else request.source_text
        )
        if not provider_text or len(provider_text) > self.config.max_chars_per_request:
            raise self._failure("input_too_long")
        return provider_text

    def _catalog_use(self, request: SpeechSynthesisRequest) -> str:
        if request.workload == "voice_audition":
            return "voice_audition"
        return "audiobook_narration" if request.speaker_role == "narrator" else "dialogue"

    def validate_route(self, request: SpeechSynthesisRequest) -> None:
        self._require_enabled()
        if request.voice.provider != self.name:
            raise self._failure("voice_provider_mismatch")
        if request.provider_selection == "automatic" and not self.config.auto_render_enabled:
            raise self._failure("provider_auto_render_disabled")
        if request.provider_selection == "fallback":
            raise self._failure("cross_provider_fallback_disabled")
        if request.workload == "sensitive_persona" and not self.config.allow_persona:
            raise self._failure("sensitive_persona_provider_use_blocked")
        if request.model not in VOCALLAB_MODELS:
            raise self._failure("model_not_allowed")
        if (
            request.model == "v-lite"
            and request.publication_intent
            and not self.config.allow_lite_publication
        ):
            raise self._failure("draft_model_publication_blocked")
        if request.provider_contract_version != VOCALLAB_PROVIDER_CONTRACT_VERSION:
            raise self._failure("provider_contract_version_missing")
        if (
            len(request.external_processing_authorization_sha256) != 64
            or any(
                value not in "0123456789abcdef"
                for value in request.external_processing_authorization_sha256
            )
        ):
            raise self._failure("external_authorization_digest_invalid")
        required_route_hash = (
            request.audition_authorization_sha256
            if request.workload == "voice_audition"
            else request.cast_snapshot_sha256
        )
        if len(required_route_hash) != 64 or any(
            value not in "0123456789abcdef" for value in required_route_hash
        ):
            raise self._failure("route_authority_digest_invalid")
        if self._voice_catalog is None or not self._voice_catalog.entries:
            raise self._failure("voice_catalog_missing")
        if len(self._voice_catalog.source_sha256) != 64:
            raise self._failure("voice_catalog_digest_invalid")
        if self._authorities is None:
            raise self._failure("provider_authority_store_missing")
        if self._budget is None:
            raise self._failure("budget_ledger_missing")
        credential_binding_sha256 = self._credential_binding_sha256()
        try:
            self._budget.assert_scope(
                credential_binding_sha256=credential_binding_sha256,
                canonical_account_state_root=self.config.account_state_root,
            )
        except BudgetLedgerError as exc:
            raise self._failure(exc.code) from None
        current = self._now()
        if current.tzinfo is None:
            raise self._failure("provider_clock_invalid")
        try:
            verification = self._authorities.authorize(
                request,
                catalog_sha256=self._voice_catalog.source_sha256,
                credential_binding_sha256=credential_binding_sha256,
                now=current,
            )
        except AuthorityError as exc:
            raise self._failure(exc.code) from None
        if request.model not in verification.models:
            raise self._failure("model_not_verified")
        active_catalog_hashes = tuple(
            sorted(
                entry.voice_id_sha256
                for entry in self._voice_catalog.entries
                if entry.active
            )
        )
        if active_catalog_hashes != verification.discovered_voice_hashes:
            raise self._failure("verification_catalog_inventory_mismatch")
        if request.voice.voice_id_sha256 not in verification.discovered_voice_hashes:
            raise self._failure("voice_not_verified")
        try:
            catalog_entry = self._voice_catalog.authorize(
                request.voice,
                language=request.language,
                use=self._catalog_use(request),
                allow_clones=self.config.allow_clones,
                allow_community=self.config.allow_community_voices,
                allowed_rights_classes=self.config.allowed_voice_classes,
                now=current,
            )
        except VoiceCatalogError as exc:
            raise self._failure(exc.code) from None
        if not hmac.compare_digest(catalog_entry.safe_label, request.voice.safe_label):
            raise self._failure("voice_safe_label_mismatch")
        if hashlib.sha256(request.source_text.encode("utf-8")).hexdigest() != request.source_text_sha256:
            raise self._failure("source_text_hash_mismatch")
        if not request.idempotency_key:
            raise self._failure("idempotency_key_missing")
        if not self._valid_step(request.speed, minimum="0.5", maximum="1.5"):
            raise self._failure("speed_invalid")
        if not self._valid_step(request.temperature, minimum="0.7", maximum="1.5"):
            raise self._failure("temperature_invalid")
        if request.output_format != "wav":
            raise self._failure("format_invalid")
        if request.sample_rate != 44100:
            raise self._failure("sample_rate_invalid")
        self._provider_text(request)

    def estimate_points(self, request: SpeechSynthesisRequest) -> int:
        provider_text = self._provider_text(request)
        divisor = 30 if request.model == "v-lite" else 15
        return (len(provider_text) + divisor - 1) // divisor

    def _post_payload(
        self, request: SpeechSynthesisRequest, provider_text: str
    ) -> dict[str, object]:
        return {
            "text": provider_text,
            "voice": request.voice.provider_voice_id,
            "model": request.model,
            "speed": request.speed,
            "temperature": request.temperature,
            "format": "WAV",
            "sample_rate": 44100,
        }

    def _generation_observation(
        self,
        payload: Mapping[str, Any],
        request: SpeechSynthesisRequest,
        *,
        expected_generation_id: str = "",
    ) -> GenerationObservation:
        try:
            observation = parse_generation(
                payload,
                expected_model=request.model,
            )
        except VocalLabSchemaError:
            raise self._failure(
                "invalid_provider_response", charge_state="unknown"
            ) from None
        if (
            expected_generation_id
            and observation.generation_id != expected_generation_id
        ):
            raise self._failure(
                "provider_generation_id_changed", charge_state="unknown"
            )
        return observation

    def _poll_generation(
        self, generation_id: str, request: SpeechSynthesisRequest
    ) -> GenerationObservation:
        started = self._monotonic()
        while self._monotonic() - started <= self.config.poll_timeout_seconds:
            payload = self._request_json("GET", f"tts/{generation_id}")
            observation = self._generation_observation(
                payload,
                request,
                expected_generation_id=generation_id,
            )
            self._record_provider_success()
            if observation.status in VOCALLAB_GENERATION_SUCCESS:
                return observation
            if observation.status in VOCALLAB_GENERATION_FAILED:
                raise self._failure("generation_failed", charge_state="unknown")
            self._sleep(self.config.poll_interval_seconds)
        raise self._failure(
            "generation_poll_timeout",
            retryable=True,
            charge_state="unknown",
        )

    def _materialize_audio(
        self, observation: GenerationObservation, request: SpeechSynthesisRequest
    ) -> ValidatedAudio:
        inline = observation.audio_base64
        if not inline:
            if observation.audio_url:
                raise self._failure(
                    "audio_url_fallback_disabled", charge_state="charged"
                )
            raise self._failure("invalid_provider_audio", charge_state="charged")
        try:
            return decode_inline_audio(
                inline,
                expected_format="wav",
                expected_sample_rate=44100,
                max_audio_bytes=self.config.max_audio_bytes,
            )
        except AudioOutputValidationError:
            raise self._failure(
                "invalid_provider_audio", charge_state="charged"
            ) from None

    def _start_post(self, reservation_id: str) -> None:
        assert self._budget is not None
        try:
            self._budget.mark_post_started(
                reservation_id,
                started_at=self._now(),
            )
        except BudgetLedgerError as exc:
            raise self._failure(
                exc.code,
                retryable=exc.code == "provider_local_rate_limited",
                retry_after_seconds=exc.retry_after_seconds,
            ) from None

    def _pace_http_request(self) -> None:
        if self._budget is None:
            raise self._failure("budget_ledger_missing")
        for attempt in range(2):
            try:
                self._budget.record_request_started(
                    started_at=self._now(),
                    requests_per_minute=self.config.requests_per_minute,
                )
                return
            except BudgetLedgerError as exc:
                if exc.code != "provider_local_rate_limited" or attempt:
                    raise self._failure(
                        exc.code,
                        retryable=exc.code == "provider_local_rate_limited",
                        retry_after_seconds=exc.retry_after_seconds,
                    ) from None
                self._sleep(float(exc.retry_after_seconds))
        raise self._failure("provider_local_rate_limited", retryable=True)

    def _ready_generation(
        self,
        generation_id: str,
        request: SpeechSynthesisRequest,
        observation: GenerationObservation,
    ) -> GenerationObservation:
        if observation.generation_id != generation_id:
            raise self._failure(
                "provider_generation_id_changed", charge_state="unknown"
            )
        if observation.status in VOCALLAB_GENERATION_PENDING:
            if observation.audio_base64 and observation.points_used is not None:
                return observation
            return self._poll_generation(generation_id, request)
        if observation.status in VOCALLAB_GENERATION_FAILED:
            raise self._failure("generation_failed", charge_state="unknown")
        return observation

    def _require_spending_balance_partition(self) -> AccountBalance:
        """No live contract currently proves monthly/top-up point partitioning."""

        raise self._failure("provider_balance_partition_unverified")

    def synthesize(self, request: SpeechSynthesisRequest) -> SpeechSynthesisResult:
        self.validate_route(request)
        if self._budget is None:
            raise self._failure("budget_ledger_missing")
        provider_text = self._provider_text(request)
        points_estimated = self.estimate_points(request)
        request_fingerprint = synthesis_fingerprint(request)
        with self._post_lock, self._budget.provider_account_lock():
            try:
                reservation = self._budget.find_existing(
                    job_id=request.job_id,
                    idempotency_key=request.idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
                if reservation is None or reservation.status == "reserved":
                    balance = self._require_spending_balance_partition()
                    reservation = self._budget.reserve(
                        job_id=request.job_id,
                        idempotency_key=request.idempotency_key,
                        request_fingerprint=request_fingerprint,
                        points_estimated=points_estimated,
                        balance=balance,
                        observed_at=self._now(),
                    )
            except BudgetLedgerError as exc:
                raise self._failure(
                    exc.code,
                    charge_state=exc.charge_state,
                    retry_after_seconds=exc.retry_after_seconds,
                ) from None

            generation_id = reservation.generation_id_private
            generation: GenerationObservation
            if reservation.status == "reserved":
                self._start_post(reservation.reservation_id)
                try:
                    payload = self._request_json(
                        "POST",
                        "tts",
                        payload=self._post_payload(request, provider_text),
                        spending_post=True,
                    )
                    generation = self._generation_observation(payload, request)
                    generation_id = generation.generation_id
                    reservation = self._budget.record_generation(
                        reservation.reservation_id,
                        generation_id,
                    )
                    self._record_provider_success()
                except AudiobookProviderError:
                    try:
                        self._budget.mark_unknown(reservation.reservation_id)
                    except BudgetLedgerError:
                        pass
                    raise
                except BudgetLedgerError as exc:
                    try:
                        self._budget.mark_unknown(reservation.reservation_id)
                    except BudgetLedgerError:
                        pass
                    raise self._failure(
                        exc.code, charge_state="unknown"
                    ) from None
            else:
                try:
                    generation = self._poll_generation(generation_id, request)
                except AudiobookProviderError as exc:
                    if reservation.status == "charged_pending_materialization":
                        raise self._failure(
                            exc.failure.code,
                            retryable=exc.failure.retryable,
                            charge_state="charged",
                            retry_after_seconds=exc.failure.retry_after_seconds,
                        ) from None
                    raise self._failure(
                        exc.failure.code,
                        retryable=exc.failure.retryable,
                        charge_state="unknown",
                        retry_after_seconds=exc.failure.retry_after_seconds,
                    ) from None

            try:
                generation = self._ready_generation(
                    generation_id,
                    request,
                    generation,
                )
            except AudiobookProviderError as exc:
                raise self._failure(
                    exc.failure.code,
                    retryable=exc.failure.retryable,
                    charge_state=(
                        "charged"
                        if reservation.status
                        == "charged_pending_materialization"
                        else "unknown"
                    ),
                    retry_after_seconds=exc.failure.retry_after_seconds,
                ) from None

            if generation.points_used is None:
                raise self._failure(
                    "invalid_provider_response", charge_state="unknown"
                )
            points_used = generation.points_used
            if reservation.status == "charged_pending_materialization":
                if points_used != reservation.points_used:
                    raise self._failure(
                        "provider_points_changed_after_charge",
                        charge_state="charged",
                    )
                charged = reservation
            else:
                try:
                    charged = self._budget.reconcile_charge(
                        reservation.reservation_id,
                        points_used=points_used,
                    )
                except BudgetLedgerError as exc:
                    raise self._failure(
                        exc.code, charge_state=exc.charge_state
                    ) from None
            validated = self._materialize_audio(generation, request)
            output_sha256 = hashlib.sha256(validated.audio_bytes).hexdigest()
            try:
                complete = self._budget.commit_materialized(
                    reservation.reservation_id,
                    output_sha256=output_sha256,
                )
            except BudgetLedgerError as exc:
                raise self._failure(
                    exc.code, charge_state=exc.charge_state
                ) from None
            return SpeechSynthesisResult(
                provider=self.name,
                model=request.model,
                content_type=validated.content_type,
                audio_bytes=validated.audio_bytes,
                audio_sha256=complete.output_sha256,
                provider_generation_id_private=generation_id,
                provider_generation_id_sha256=charged.generation_id_sha256,
                points_estimated=points_estimated,
                points_used=points_used,
                retry_count=0,
                provider_contract_version=VOCALLAB_PROVIDER_CONTRACT_VERSION,
            )
