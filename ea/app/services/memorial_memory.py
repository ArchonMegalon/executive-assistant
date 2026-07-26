from __future__ import annotations

import base64
import email
import errno
import fcntl
import hashlib
import hmac
import json
import mailbox
import math
import os
import re
import shutil
import stat
import tempfile
import threading
import urllib.parse
from collections import Counter
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import datetime
from email.message import Message
from email.policy import default as default_email_policy
from pathlib import Path
from typing import Any

from app.domain.models import MemoryItem, now_utc_iso
from app.repositories.memory_items import MemoryItemSnapshotLimitExceeded
from app.services.memory_runtime import MemoryRuntimeService

_ARCHIVE_ROOT = Path('/data/artifacts/memorial_mail_archive')
_MAIL_MANIFEST_SCHEMA = 'ea.memorial_mail_ingest_manifest.v2'
_MAIL_MANIFEST_LOCK = threading.RLock()
_MAIL_MAX_RAW_MESSAGE_BYTES = 32 * 1024 * 1024
_MAIL_MAX_IMPORT_BYTES = 128 * 1024 * 1024
_MAIL_MANIFEST_MAX_BYTES = 8 * 1024 * 1024
_MAIL_MANIFEST_MAX_KEYS = 10_000
_MAIL_MANIFEST_MAX_PRINCIPALS = 1_000
_LOCAL_SNAPSHOT_SCHEMA = 'ea.memorial_local_snapshot.v1'
_LOCAL_SNAPSHOT_MAIL_SCHEMA = 'ea.memorial_local_snapshot_mail.v1'
_LOCAL_SNAPSHOT_RECOVERY_SCHEMA = 'ea.memorial_local_recovery_receipt.v1'
_LOCAL_SNAPSHOT_MAX_MEMORY_ITEMS = 5000
_LOCAL_SNAPSHOT_MAX_MEMORY_BYTES = 16 * 1024 * 1024
_LOCAL_SNAPSHOT_MAX_FILE_BYTES = 192 * 1024 * 1024
_LOCAL_SNAPSHOT_AUTHORITY = {
    'scope': 'ea_local_noncanonical_private_recovery',
    'authenticated': False,
    'integrity_model': 'sha256_accidental_corruption_only',
    'restores_hub_identity': False,
    'restores_registry_state': False,
    'restores_publication_state': False,
}
_PUBLICATION_STATE_KEYS = {
    'public',
    'visibility',
    'public_approved',
    'public_approval_key',
    'publication_id',
    'publication_status',
    'published_at',
    'registry_publication_id',
    'registry_status',
}
_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ0-9_\-]{3,}")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_URL_RE = re.compile(r"https?://\S+")
_STOPWORDS = {
    'und','oder','aber','doch','denn','eine','einer','eines','einem','einen','der','die','das','dem','des','ist','sind','war','waren',
    'mit','ohne','dass','wenn','weil','also','noch','nicht','nur','auch','wie','was','wer','wird','wurde','einerseits','andererseits',
    'fuer','für','von','zum','zur','auf','aus','bei','als','ein','im','in','am','an','zu','es','ich','du','er','sie','wir','ihr'
}


def memorial_memory_principal_id(slug: str, payload: dict[str, object] | None = None) -> str:
    configured = str((payload or {}).get('memory_principal_id') or '').strip()
    if configured:
        return configured
    return f'memorial:{str(slug or "").strip().lower()}'


def _safe_slug(value: str) -> str:
    normalized = ''.join(ch for ch in str(value or '').strip().lower() if ch.isalnum() or ch in {'-','_'})
    return normalized[:80].strip('-_') or 'memorial'


def _normalize_text(value: object) -> str:
    return _SPACE_RE.sub(' ', str(value or '').strip())


def _source_item_is_public(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    visibility = _normalize_text(value.get('visibility')).lower()
    public_flag = value.get('public')
    if visibility:
        return visibility == 'public' and public_flag is not False
    return public_flag is True


def _source_text(value: object) -> str:
    return _normalize_text(value) if isinstance(value, str) else ''


def _safe_public_https_url(value: object) -> str:
    candidate = _source_text(value)
    if not candidate or len(candidate) > 2048 or '\\' in candidate:
        return ''
    if any(ord(character) < 32 or ord(character) == 127 for character in candidate):
        return ''
    try:
        parsed = urllib.parse.urlsplit(candidate)
        port = parsed.port
    except ValueError:
        return ''
    if parsed.scheme.lower() != 'https' or not parsed.hostname:
        return ''
    if parsed.username or parsed.password or port not in {None, 443}:
        return ''
    return parsed.geturl()


def _strip_html(value: str) -> str:
    return _normalize_text(_HTML_TAG_RE.sub(' ', value or ''))


def _tokenize(value: str) -> set[str]:
    return {token.lower() for token in _WORD_RE.findall(value or '') if token.lower() not in _STOPWORDS}


def _query_memory_axes(question: str) -> set[str]:
    lowered = str(question or '').lower()
    axes: set[str] = set()
    if any(token in lowered for token in ('mail', 'email', 'e-mail', 'schreibstil', 'schriftlich', 'formuliert', 'ton', 'klang')):
        axes.add('stylistic')
    if any(token in lowered for token in ('familie', 'schach', 'erinner', 'damals', 'kindheit', 'reise', 'krankenhaus', 'spital')):
        axes.add('episodic')
    if any(token in lowered for token in ('wohnung', 'kauf', 'kaufen', 'grundbuch', 'ruecklage', 'betriebskosten', 'sanierung', 'recht', 'rechtsfrage', 'prinzip', 'pflicht', 'schuld', 'verantwortung')):
        axes.add('legal')
    if not axes:
        axes.add('general')
    return axes


def _infer_memory_axis(*, kind: str, title: str = '', body: str = '', trait: str = '', note: str = '', subject: str = '') -> str:
    lowered = ' '.join([kind, title, body, trait, note, subject]).lower()
    if kind == 'mail_message':
        if any(token in lowered for token in ('grundbuch', 'wohnung', 'rechtlich', 'rechtsfrage', 'pflicht', 'schuld', 'verantwortung')):
            return 'legal'
        return 'stylistic'
    if any(token in lowered for token in ('schach', 'familie', 'reise', 'weitergegeben', 'behalten', 'erinner')):
        return 'episodic'
    if any(token in lowered for token in ('rechtlich', 'rechtsfrage', 'prinzip', 'pflicht', 'schuld', 'verantwortung', 'ordnung', 'anspruch')):
        return 'legal'
    if any(token in lowered for token in ('trocken', 'formal', 'stil', 'schriftlich', 'mail', 'quelle', 'linkbezogen')):
        return 'stylistic'
    if kind in {'memorial_character_note', 'character_note'}:
        return 'stylistic'
    if kind in {'memorial_memory_card', 'family_context_note', 'memorial_family_context'}:
        return 'episodic'
    if kind in {'grounded_profile', 'memorial_grounded_profile'}:
        return 'legal'
    return 'general'


def _memory_kind_retrieval_boost(*, query_tokens: set[str], fact: dict[str, object], row: MemoryItem) -> float:
    kind = str(fact.get('memory_kind') or '').strip().lower()
    axis = str(fact.get('memory_axis') or '').strip().lower()
    summary = str(row.summary or '').lower()
    boost = 0.0
    if kind == 'mail_message':
        boost += 0.35
    elif kind in {'grounded_profile', 'family_context_note'}:
        boost += 0.6
    elif kind == 'character_note':
        boost += 0.5
    elif kind in {'conversation_style', 'conversation_avoid'}:
        boost += 0.85
    elif kind == 'memorial_memory_card':
        boost += 0.75
    elif kind == 'suggested_prompt':
        boost += 0.2
    elif kind == 'external_source':
        boost -= 0.15
    query_axes = _query_memory_axes(' '.join(sorted(query_tokens)))
    if axis == 'stylistic' and 'stylistic' in query_axes:
        boost += 1.0
    elif axis == 'episodic' and 'episodic' in query_axes:
        boost += 0.95
    elif axis == 'legal' and 'legal' in query_axes:
        boost += 0.9
    elif axis and axis != 'general':
        boost += 0.1
    if {'mail', 'email', 'e-mail', 'schreibstil', 'schriftlich'} & query_tokens:
        if kind == 'mail_message':
            boost += 1.3
        if kind in {'character_note', 'grounded_profile', 'conversation_style', 'conversation_avoid'} and any(token in summary for token in ('trocken', 'schrift', 'mail', 'quelle', 'formal', 'stil', 'ton')):
            boost += 0.65
    if {'schach', 'familie'} & query_tokens:
        if kind == 'memorial_memory_card':
            boost += 1.1
        if kind in {'family_context_note', 'grounded_profile'}:
            boost += 0.55
    if {'wohnung', 'kaufen', 'kauf', 'grundbuch', 'ruecklage', 'betriebskosten', 'sanierungen'} & query_tokens:
        if kind in {'mail_message', 'grounded_profile'}:
            boost += 0.45
    return boost


def _extract_text_parts(message: Message) -> tuple[str, str]:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_disposition() == 'attachment':
                continue
            content_type = str(part.get_content_type() or '').lower()
            try:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or 'utf-8'
                text = (payload or b'').decode(charset, errors='ignore') if payload is not None else str(part.get_payload() or '')
            except Exception:
                text = str(part.get_payload() or '')
            if content_type == 'text/plain':
                plain_parts.append(_normalize_text(text))
            elif content_type == 'text/html':
                html_parts.append(_strip_html(text))
    else:
        content_type = str(message.get_content_type() or '').lower()
        try:
            payload = message.get_payload(decode=True)
            charset = message.get_content_charset() or 'utf-8'
            text = (payload or b'').decode(charset, errors='ignore') if payload is not None else str(message.get_payload() or '')
        except Exception:
            text = str(message.get_payload() or '')
        if content_type == 'text/html':
            html_parts.append(_strip_html(text))
        else:
            plain_parts.append(_normalize_text(text))
    plain = _normalize_text(' '.join(part for part in plain_parts if part))
    html = _normalize_text(' '.join(part for part in html_parts if part))
    return plain, html


def _message_body_text(message: Message) -> str:
    plain, html = _extract_text_parts(message)
    return plain or html


def _header_values(message: Message, name: str) -> list[str]:
    values: list[str] = []
    for value in message.get_all(name, []):
        normalized = _normalize_text(value)
        if normalized:
            values.append(normalized)
    return values


def _message_key(message: Message, body_text: str) -> str:
    message_id = _normalize_text(message.get('Message-ID'))
    if message_id:
        return hashlib.sha1(message_id.encode('utf-8')).hexdigest()
    base = ' | '.join([
        _normalize_text(message.get('Date')),
        _normalize_text(message.get('From')),
        _normalize_text(message.get('Subject')),
        body_text[:800],
    ])
    return hashlib.sha1(base.encode('utf-8')).hexdigest()


def _message_summary(message: Message, body_text: str) -> str:
    subject = _normalize_text(message.get('Subject'))
    first_sentence = body_text.split('.', 1)[0].strip()
    sender = _normalize_text(message.get('From'))
    if subject and first_sentence:
        return _normalize_text(f'{subject}: {first_sentence}')[:280]
    if subject:
        return _normalize_text(f'{subject} ({sender})')[:280]
    if first_sentence:
        return first_sentence[:280]
    return _normalize_text(f'Email von {sender}')[:280] or 'Email'


def _mail_memory_excerpt(*, row: MemoryItem, fact: dict[str, object]) -> str:
    excerpt = _normalize_text(fact.get('body_excerpt'))
    if excerpt:
        first_sentence = excerpt.split('.', 1)[0].strip()
        if first_sentence:
            return f'Im Kern ging es darum, dass {first_sentence[:180].rstrip(" .,;:")}.'
    summary = _normalize_text(row.summary)
    summary = re.sub(r'^(?:re|aw|wg|fwd)\s*:\s*', '', summary, flags=re.IGNORECASE).strip()
    if ':' in summary:
        summary = summary.split(':', 1)[0].strip()
    if summary:
        return f'Im Kern ging es um {summary[:180].rstrip(" .,;:")}.'
    subject = _normalize_text(fact.get('subject'))
    subject = re.sub(r'^(?:re|aw|wg|fwd)\s*:\s*', '', subject, flags=re.IGNORECASE).strip()
    if subject:
        return f'Im Kern ging es um {subject[:180].rstrip(" .,;:")}.'
    return 'Im Kern ging es um eine klare Sache mit praktischer Folgerung.'


def _archive_root_for(slug: str) -> Path:
    return _ARCHIVE_ROOT / _safe_slug(slug)


def _snapshot_root_for(slug: str) -> Path:
    return _archive_root_for(slug) / 'snapshots'


def _manifest_path(slug: str) -> Path:
    return _archive_root_for(slug) / 'ingest_manifest.json'


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _reject_symlink_components(path: Path, *, include_leaf: bool = True) -> None:
    absolute = _absolute_path(path)
    candidates = list(reversed(absolute.parents))
    if include_leaf:
        candidates.append(absolute)
    for candidate in candidates:
        try:
            mode = os.lstat(candidate).st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ValueError('memorial_private_storage_path_invalid') from exc
        if stat.S_ISLNK(mode):
            raise ValueError('memorial_private_storage_symlink_forbidden')


def _ensure_private_directory(path: Path) -> Path:
    absolute = _absolute_path(path)
    _reject_symlink_components(absolute)
    try:
        absolute.mkdir(mode=0o700, parents=True, exist_ok=True)
        _reject_symlink_components(absolute)
        if not absolute.is_dir():
            raise ValueError('memorial_private_storage_path_invalid')
        os.chmod(absolute, 0o700, follow_symlinks=False)
    except ValueError:
        raise
    except OSError as exc:
        raise ValueError('memorial_private_storage_path_invalid') from exc
    return absolute


def _ensure_archive_root(slug: str, *children: str) -> Path:
    root = _ensure_private_directory(_ARCHIVE_ROOT)
    memorial_root = _ensure_private_directory(root / _safe_slug(slug))
    current = memorial_root
    for child in children:
        if not child or child in {'.', '..'} or '/' in child or '\\' in child:
            raise ValueError('memorial_private_storage_path_invalid')
        current = _ensure_private_directory(current / child)
    return current


def _require_contained_path(*, root: Path, candidate: Path, allow_root: bool = False) -> Path:
    absolute_root = _absolute_path(root)
    absolute_candidate = _absolute_path(candidate)
    try:
        relative = absolute_candidate.relative_to(absolute_root)
    except ValueError as exc:
        raise ValueError('memorial_private_storage_path_outside_root') from exc
    if (not allow_root and relative == Path('.')) or any(part in {'', '.', '..'} for part in relative.parts):
        raise ValueError('memorial_private_storage_path_outside_root')
    _reject_symlink_components(absolute_candidate)
    return absolute_candidate


class _BoundedFileTooLarge(RuntimeError):
    pass


def _read_regular_file_bounded(path: Path, *, max_bytes: int) -> bytes:
    absolute = _absolute_path(path)
    _reject_symlink_components(absolute)
    nofollow = getattr(os, 'O_NOFOLLOW', 0)
    close_on_exec = getattr(os, 'O_CLOEXEC', 0)
    directory_flag = getattr(os, 'O_DIRECTORY', 0)
    parent_fd = os.open(absolute.parent, os.O_RDONLY | directory_flag | nofollow | close_on_exec)
    try:
        parent_metadata = os.fstat(parent_fd)
        if not stat.S_ISDIR(parent_metadata.st_mode):
            raise OSError(errno.ENOTDIR, 'private directory required')
        if stat.S_IMODE(parent_metadata.st_mode) & 0o077:
            if parent_metadata.st_uid != os.geteuid():
                raise OSError(errno.EACCES, 'private directory ownership required')
            os.fchmod(parent_fd, 0o700)
            os.fsync(parent_fd)
        descriptor = os.open(
            absolute.name,
            os.O_RDONLY | nofollow | close_on_exec,
            dir_fd=parent_fd,
        )
    finally:
        os.close(parent_fd)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError(errno.EINVAL, 'not a regular file')
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            if metadata.st_uid != os.geteuid():
                raise OSError(errno.EACCES, 'private file ownership required')
            os.fchmod(descriptor, 0o600)
            os.fsync(descriptor)
        if metadata.st_size > max_bytes:
            raise _BoundedFileTooLarge
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise _BoundedFileTooLarge
        return b''.join(chunks)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        _absolute_path(path),
        os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write_bytes(path: Path, payload: bytes, *, replace_existing: bool = True) -> None:
    path = _absolute_path(path)
    _ensure_private_directory(path.parent)
    _reject_symlink_components(path)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=str(path.parent))
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if replace_existing:
            os.replace(temporary_path, path)
        else:
            os.link(temporary_path, path, follow_symlinks=False)
            temporary_path.unlink()
        _fsync_directory(path.parent)
    finally:
        temporary_path.unlink(missing_ok=True)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    serialized = (json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    _atomic_write_bytes(path, serialized)


def _validated_manifest_keys(value: object, *, canonical_order_required: bool = True) -> list[str]:
    if not isinstance(value, list) or len(value) > _MAIL_MANIFEST_MAX_KEYS:
        raise ValueError('memorial_mail_ingest_manifest_invalid')
    keys: list[str] = []
    for item in value:
        if not isinstance(item, str) or re.fullmatch(r'[0-9a-f]{40}', item) is None:
            raise ValueError('memorial_mail_ingest_manifest_invalid')
        keys.append(item)
    canonical = sorted(set(keys))
    if canonical_order_required and keys != canonical:
        raise ValueError('memorial_mail_ingest_manifest_invalid')
    return canonical


def _validated_last_sources(value: object) -> dict[str, dict[str, str]]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > _MAIL_MANIFEST_MAX_PRINCIPALS:
        raise ValueError('memorial_mail_ingest_manifest_invalid')
    validated: dict[str, dict[str, str]] = {}
    for raw_principal, raw_source in value.items():
        if not isinstance(raw_principal, str) or raw_principal != raw_principal.strip() or len(raw_principal) > 500:
            raise ValueError('memorial_mail_ingest_manifest_invalid')
        if not isinstance(raw_source, dict) or not set(raw_source).issubset({'source_path', 'mailbox_format'}):
            raise ValueError('memorial_mail_ingest_manifest_invalid')
        source_path = raw_source.get('source_path', '')
        mailbox_format = raw_source.get('mailbox_format', '')
        if (
            not isinstance(source_path, str)
            or len(source_path) > 4096
            or not isinstance(mailbox_format, str)
            or len(mailbox_format) > 100
        ):
            raise ValueError('memorial_mail_ingest_manifest_invalid')
        validated[raw_principal] = {
            'source_path': source_path,
            'mailbox_format': mailbox_format,
        }
    return validated


def _validated_v2_manifest(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or not set(payload).issubset(
        {'schema', 'processed_keys', 'processed_by_principal', 'last_source_by_principal'}
    ):
        raise ValueError('memorial_mail_ingest_manifest_invalid')
    if payload.get('schema') != _MAIL_MANIFEST_SCHEMA:
        raise ValueError('memorial_mail_ingest_manifest_invalid')
    processed_keys = _validated_manifest_keys(payload.get('processed_keys'))
    raw_by_principal = payload.get('processed_by_principal')
    if not isinstance(raw_by_principal, dict) or len(raw_by_principal) > _MAIL_MANIFEST_MAX_PRINCIPALS:
        raise ValueError('memorial_mail_ingest_manifest_invalid')
    processed_by_principal: dict[str, list[str]] = {}
    for raw_principal, raw_keys in raw_by_principal.items():
        if (
            not isinstance(raw_principal, str)
            or not raw_principal
            or raw_principal != raw_principal.strip()
            or len(raw_principal) > 500
        ):
            raise ValueError('memorial_mail_ingest_manifest_invalid')
        processed_by_principal[raw_principal] = _validated_manifest_keys(raw_keys)
    union = sorted({item for values in processed_by_principal.values() for item in values})
    if union != processed_keys:
        raise ValueError('memorial_mail_ingest_manifest_invalid')
    validated: dict[str, Any] = {
        'schema': _MAIL_MANIFEST_SCHEMA,
        'processed_keys': processed_keys,
        'processed_by_principal': processed_by_principal,
    }
    last_sources = _validated_last_sources(payload.get('last_source_by_principal'))
    if last_sources:
        validated['last_source_by_principal'] = last_sources
    return validated


def _load_manifest(slug: str, *, legacy_principal_id: str = '') -> dict[str, Any]:
    path = _manifest_path(slug)
    try:
        raw = _read_regular_file_bounded(path, max_bytes=_MAIL_MANIFEST_MAX_BYTES)
    except FileNotFoundError:
        return {
            'schema': _MAIL_MANIFEST_SCHEMA,
            'processed_keys': [],
            'processed_by_principal': {},
        }
    except _BoundedFileTooLarge as exc:
        raise ValueError('memorial_mail_ingest_manifest_too_large') from exc
    except (OSError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc) == 'memorial_private_storage_symlink_forbidden':
            raise
        raise ValueError('memorial_mail_ingest_manifest_invalid') from exc
    try:
        payload = json.loads(
            raw.decode('utf-8'),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ValueError('memorial_mail_ingest_manifest_invalid') from exc
    if not isinstance(payload, dict):
        raise ValueError('memorial_mail_ingest_manifest_invalid')
    if payload.get('schema') == _MAIL_MANIFEST_SCHEMA or 'processed_by_principal' in payload:
        return _validated_v2_manifest(payload)
    if payload.get('schema') not in {None, 'ea.memorial_mail_ingest_manifest.v1'}:
        raise ValueError('memorial_mail_ingest_manifest_invalid')
    if not set(payload).issubset({'schema', 'processed_keys', 'last_source_by_principal'}):
        raise ValueError('memorial_mail_ingest_manifest_invalid')
    legacy_keys = _validated_manifest_keys(
        payload.get('processed_keys'),
        canonical_order_required=False,
    )
    principal = _normalize_text(legacy_principal_id)
    expected_principal = f'memorial:{_safe_slug(slug)}'
    if legacy_keys and principal != expected_principal:
        raise ValueError('memorial_mail_ingest_manifest_legacy_principal_ambiguous')
    migrated = {
        'schema': _MAIL_MANIFEST_SCHEMA,
        'processed_keys': legacy_keys,
        'processed_by_principal': {principal: legacy_keys} if legacy_keys else {},
    }
    last_sources = _validated_last_sources(payload.get('last_source_by_principal'))
    if last_sources:
        migrated['last_source_by_principal'] = last_sources
    return _validated_v2_manifest(migrated)


def _save_manifest(slug: str, payload: dict[str, Any]) -> None:
    with _MAIL_MANIFEST_LOCK:
        _ensure_archive_root(slug)
        _atomic_write_json(_manifest_path(slug), _validated_v2_manifest(payload))


@contextmanager
def _memorial_storage_lock(slug: str):
    with _MAIL_MANIFEST_LOCK:
        root = _ensure_archive_root(slug)
        lock_path = root / '.storage.lock'
        _reject_symlink_components(lock_path)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_NOFOLLOW', 0)
        descriptor = os.open(lock_path, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError('memorial_private_storage_path_invalid')
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            _fsync_directory(root)
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def _archive_raw_message(*, slug: str, message_key: str, raw_bytes: bytes) -> str:
    if re.fullmatch(r'[0-9a-f]{40}', message_key) is None or len(raw_bytes) > _MAIL_MAX_RAW_MESSAGE_BYTES:
        raise ValueError('memorial_mail_archive_invalid')
    archive_dir = _ensure_archive_root(slug, 'raw')
    filename = f'{message_key}.eml'
    path = archive_dir / filename
    try:
        _atomic_write_bytes(path, raw_bytes, replace_existing=False)
    except FileExistsError:
        try:
            existing_raw = _read_regular_file_bounded(path, max_bytes=_MAIL_MAX_RAW_MESSAGE_BYTES)
        except (_BoundedFileTooLarge, OSError, ValueError) as exc:
            raise ValueError('memorial_mail_archive_digest_mismatch') from exc
        existing_digest = hashlib.sha256(existing_raw).hexdigest()
        incoming_digest = hashlib.sha256(raw_bytes).hexdigest()
        if not hmac.compare_digest(existing_digest, incoming_digest):
            raise ValueError('memorial_mail_archive_digest_mismatch')
    return str(path.relative_to(_archive_root_for(slug)))


def _iter_messages(source_path: Path, mailbox_format: str) -> Iterable[tuple[Message, bytes]]:
    fmt = str(mailbox_format or 'auto').strip().lower()
    if fmt == 'auto':
        if source_path.is_dir() and (source_path / 'cur').exists() and (source_path / 'new').exists():
            fmt = 'maildir'
        elif source_path.suffix.lower() == '.mbox':
            fmt = 'mbox'
        elif source_path.suffix.lower() == '.eml':
            fmt = 'eml'
        else:
            fmt = 'mbox' if source_path.is_file() else 'maildir'
    if fmt == 'mbox':
        box = mailbox.mbox(str(source_path), factory=None, create=False)
        for key in box.iterkeys():
            raw = box.get_bytes(key)
            yield email.message_from_bytes(raw, policy=default_email_policy), raw
        return
    if fmt == 'maildir':
        box = mailbox.Maildir(str(source_path), factory=None, create=False)
        for key, message in box.iteritems():
            raw = bytes(message)
            yield email.message_from_bytes(raw, policy=default_email_policy), raw
        return
    if fmt == 'eml':
        raw = source_path.read_bytes()
        yield email.message_from_bytes(raw, policy=default_email_policy), raw
        return
    raise ValueError('unsupported_mailbox_format')


def _reconciled_mail_keys(
    *,
    memory_runtime: MemoryRuntimeService,
    principal: str,
    slug: str,
) -> set[str]:
    try:
        rows = memory_runtime.export_principal_snapshot(
            principal_id=principal,
            max_items=_LOCAL_SNAPSHOT_MAX_MEMORY_ITEMS,
        )
    except MemoryItemSnapshotLimitExceeded as exc:
        raise ValueError('memorial_mail_reconciliation_incomplete') from exc
    reconciled: set[str] = set()
    for row in rows:
        fact = dict(getattr(row, 'fact_json', {}) or {})
        provenance = dict(getattr(row, 'provenance_json', {}) or {})
        if _normalize_text(fact.get('memory_kind')).lower() != 'mail_message':
            continue
        source_kind = _normalize_text(fact.get('source_kind')).lower()
        source_type = _normalize_text(provenance.get('source_type')).lower()
        raw_relpath = _normalize_text(fact.get('raw_archive_relpath'))
        if source_kind != 'mail_archive' and source_type != 'mail_archive' and not raw_relpath:
            continue
        explicit_slug = _normalize_text(fact.get('memorial_slug'))
        if explicit_slug and explicit_slug != slug:
            raise ValueError('memorial_mail_reconciliation_scope_mismatch')
        message_key = _normalize_text(fact.get('message_key'))
        raw_sha256 = _normalize_text(fact.get('raw_sha256') or provenance.get('raw_sha256'))
        if (
            re.fullmatch(r'[0-9a-f]{40}', message_key) is None
            or raw_relpath != f'raw/{message_key}.eml'
            or (raw_sha256 and re.fullmatch(r'[0-9a-f]{64}', raw_sha256) is None)
        ):
            raise ValueError('memorial_mail_reconciliation_invalid')
        try:
            raw_bytes = _read_regular_file_bounded(
                _archive_root_for(slug) / raw_relpath,
                max_bytes=_MAIL_MAX_RAW_MESSAGE_BYTES,
            )
        except (_BoundedFileTooLarge, OSError, ValueError) as exc:
            raise ValueError('memorial_mail_reconciliation_raw_incomplete') from exc
        if raw_sha256 and not hmac.compare_digest(hashlib.sha256(raw_bytes).hexdigest(), raw_sha256):
            raise ValueError('memorial_mail_reconciliation_raw_mismatch')
        reconciled.add(message_key)
    return reconciled


def ingest_memorial_mail_archive(
    *,
    memory_runtime: MemoryRuntimeService,
    principal_id: str,
    memorial_slug: str,
    source_path: str,
    mailbox_format: str = 'auto',
    reviewer: str = 'memorial-mail-import',
    source_label: str = '',
    sensitivity: str = 'private',
    max_messages: int = 5000,
) -> dict[str, object]:
    path = Path(str(source_path or '').strip()).expanduser()
    if not path.exists():
        raise FileNotFoundError('mail_source_missing')
    slug = _safe_slug(memorial_slug)
    principal = _normalize_text(principal_id)
    if not principal or len(principal) > 500:
        raise ValueError('memorial_mail_principal_missing')
    bounded_max_messages = max(1, min(int(max_messages or 1), 5000))
    with _memorial_storage_lock(slug):
        manifest = _load_manifest(slug, legacy_principal_id=principal)
        processed_by_principal = dict(manifest.get('processed_by_principal') or {})
        processed_keys = {
            str(item)
            for item in list(processed_by_principal.get(principal) or [])
            if str(item).strip()
        }
        existing_mail_keys = _reconciled_mail_keys(
            memory_runtime=memory_runtime,
            principal=principal,
            slug=slug,
        )
        processed_keys.update(existing_mail_keys)
        all_processed_keys = {
            str(item)
            for values in processed_by_principal.values()
            for item in values
            if str(item).strip()
        }
        all_processed_keys.update(existing_mail_keys)
        if len(all_processed_keys) > _MAIL_MANIFEST_MAX_KEYS:
            raise ValueError('memorial_mail_ingest_manifest_too_large')
        if principal not in processed_by_principal and len(processed_by_principal) >= _MAIL_MANIFEST_MAX_PRINCIPALS:
            raise ValueError('memorial_mail_ingest_manifest_too_large')
        imported = 0
        skipped = 0
        imported_bytes = 0
        seen_now: list[str] = []
        for index, (message, raw_bytes) in enumerate(_iter_messages(path, mailbox_format), start=1):
            if index > bounded_max_messages:
                break
            if len(raw_bytes) > _MAIL_MAX_RAW_MESSAGE_BYTES:
                raise ValueError('memorial_mail_message_too_large')
            imported_bytes += len(raw_bytes)
            if imported_bytes > _MAIL_MAX_IMPORT_BYTES:
                raise ValueError('memorial_mail_import_too_large')
            body_text = _message_body_text(message)
            message_key = _message_key(message, body_text)
            if message_key in existing_mail_keys:
                _archive_raw_message(
                    slug=slug,
                    message_key=message_key,
                    raw_bytes=raw_bytes,
                )
                skipped += 1
                continue
            if message_key not in all_processed_keys and len(all_processed_keys) >= _MAIL_MANIFEST_MAX_KEYS:
                raise ValueError('memorial_mail_ingest_manifest_too_large')
            raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
            archive_relpath = _archive_raw_message(slug=slug, message_key=message_key, raw_bytes=raw_bytes)
            subject = _normalize_text(message.get('Subject'))
            from_value = _normalize_text(message.get('From'))
            urls = list(dict.fromkeys(_URL_RE.findall(body_text or '')))
            summary = _message_summary(message, body_text)
            fact_json = {
                'memorial_slug': slug,
                'source_kind': 'mail_archive',
                'source_label': _normalize_text(source_label) or str(path),
                'mailbox_format': mailbox_format,
                'message_key': message_key,
                'message_id': _normalize_text(message.get('Message-ID')),
                'in_reply_to': _normalize_text(message.get('In-Reply-To')),
                'references': _header_values(message, 'References'),
                'subject': subject,
                'from': from_value,
                'to': _header_values(message, 'To'),
                'cc': _header_values(message, 'Cc'),
                'date': _normalize_text(message.get('Date')),
                'body_text': body_text[:12000],
                'body_excerpt': body_text[:1200],
                'urls': urls[:20],
                'raw_archive_relpath': archive_relpath,
                'raw_sha256': raw_sha256,
                'memory_kind': 'mail_message',
                'memory_axis': _infer_memory_axis(
                    kind='mail_message',
                    subject=subject,
                    body=body_text[:1800],
                ),
            }
            provenance_json = {
                'source_type': 'mail_archive',
                'source_path': str(path),
                'mailbox_format': mailbox_format,
                'message_key': message_key,
                'message_id': _normalize_text(message.get('Message-ID')),
                'archive_relpath': archive_relpath,
                'raw_sha256': raw_sha256,
            }
            memory_runtime.create_memory_item(
                principal_id=principal,
                category='memorial_mail_message',
                summary=summary,
                fact_json=fact_json,
                provenance_json=provenance_json,
                confidence=0.86,
                sensitivity=sensitivity,
                sharing_policy='private',
                reviewer=reviewer,
            )
            processed_keys.add(message_key)
            existing_mail_keys.add(message_key)
            all_processed_keys.add(message_key)
            seen_now.append(message_key)
            imported += 1
        processed_by_principal[principal] = sorted(processed_keys)
        manifest['schema'] = _MAIL_MANIFEST_SCHEMA
        manifest['processed_by_principal'] = {
            key: sorted({str(item) for item in value if str(item).strip()})
            for key, value in sorted(processed_by_principal.items())
            if key and isinstance(value, list)
        }
        manifest['processed_keys'] = sorted(
            {
                item
                for values in manifest['processed_by_principal'].values()
                for item in values
            }
        )
        last_sources = dict(manifest.get('last_source_by_principal') or {})
        last_sources[principal] = {
            'source_path': str(path),
            'mailbox_format': mailbox_format,
        }
        manifest['last_source_by_principal'] = last_sources
        _save_manifest(slug, manifest)
    return {
        'memorial_slug': slug,
        'principal_id': principal,
        'source_path': str(path),
        'mailbox_format': mailbox_format,
        'imported': imported,
        'skipped': skipped,
        'processed_total': len(processed_keys),
        'processed_total_all_principals': len(manifest.get('processed_keys') or []),
        'new_message_keys': seen_now[:50],
    }


def ingest_memorial_gmail_messages(
    *,
    container,
    memory_runtime: MemoryRuntimeService,
    principal_id: str,
    memorial_slug: str,
    account_email_filter: str = '',
    gmail_query: str = 'in:sent',
    max_messages: int = 10,
    confirm_private_mail_import: bool = False,
    reviewer: str = 'memorial-gmail-import',
) -> dict[str, object]:
    if confirm_private_mail_import is not True:
        raise ValueError('explicit_private_mail_import_confirmation_required')
    from app.services.google_oauth import export_google_gmail_raw_messages

    bounded_max_messages = max(1, min(int(max_messages or 1), 500))
    rows = tuple(
        export_google_gmail_raw_messages(
            container=container,
            principal_id=_normalize_text(principal_id),
            account_email_filter=_normalize_text(account_email_filter),
            gmail_query=_normalize_text(gmail_query) or 'in:sent',
            max_messages=bounded_max_messages,
        )
    )
    account_email = _normalize_text(getattr(rows[0], 'account_email', '')) if rows else _normalize_text(account_email_filter)
    binding_id = _normalize_text(getattr(getattr(rows[0], 'binding', None), 'binding_id', '')) if rows else ''
    live_root = _ensure_archive_root(memorial_slug, 'gmail_live')
    staging_dir = Path(tempfile.mkdtemp(prefix='import-', dir=str(live_root)))
    try:
        for directory_name in ('cur', 'new', 'tmp'):
            directory = staging_dir / directory_name
            directory.mkdir(parents=True, exist_ok=True)
            os.chmod(directory, 0o700)
        for row in rows:
            raw_bytes = bytes(getattr(row, 'raw_bytes', b'') or b'')
            if not raw_bytes:
                continue
            if len(raw_bytes) > _MAIL_MAX_RAW_MESSAGE_BYTES:
                raise ValueError('memorial_mail_message_too_large')
            message_id = _normalize_text(getattr(row, 'message_id', ''))
            filename_key = hashlib.sha256((message_id.encode('utf-8') + b'\0' + raw_bytes)).hexdigest()
            _atomic_write_bytes(staging_dir / 'new' / f'{filename_key}.eml', raw_bytes)
        if rows:
            result = ingest_memorial_mail_archive(
                memory_runtime=memory_runtime,
                principal_id=principal_id,
                memorial_slug=memorial_slug,
                source_path=str(staging_dir),
                mailbox_format='maildir',
                reviewer=reviewer,
                source_label=f'Gmail live import: {account_email or "selected account"}',
                sensitivity='private',
                max_messages=bounded_max_messages,
            )
        else:
            result = {
                'memorial_slug': _safe_slug(memorial_slug),
                'principal_id': _normalize_text(principal_id),
                'source_path': str(staging_dir),
                'mailbox_format': 'maildir',
                'imported': 0,
                'skipped': 0,
                'processed_total': 0,
                'processed_total_all_principals': 0,
                'new_message_keys': [],
            }
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
    result.update(
        {
            'exported': len(rows),
            'account_email': account_email,
            'binding_id': binding_id,
            'gmail_query': _normalize_text(gmail_query) or 'in:sent',
        }
    )
    return result


def _seed_manifest_path(slug: str) -> Path:
    return _archive_root_for(slug) / 'seed_manifest.json'


def _load_seed_manifest(slug: str) -> dict[str, Any]:
    path = _seed_manifest_path(slug)
    try:
        raw = _read_regular_file_bounded(path, max_bytes=_MAIL_MANIFEST_MAX_BYTES)
    except FileNotFoundError:
        return {'processed_keys': []}
    except (_BoundedFileTooLarge, OSError, ValueError) as exc:
        raise ValueError('memorial_seed_manifest_invalid') from exc
    try:
        payload = json.loads(
            raw.decode('utf-8'),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ValueError('memorial_seed_manifest_invalid') from exc
    if not isinstance(payload, dict):
        raise ValueError('memorial_seed_manifest_invalid')
    processed_keys = payload.get('processed_keys')
    if not isinstance(processed_keys, list) or len(processed_keys) > _MAIL_MANIFEST_MAX_KEYS:
        raise ValueError('memorial_seed_manifest_invalid')
    if any(not isinstance(item, str) or not item or len(item) > 500 for item in processed_keys):
        raise ValueError('memorial_seed_manifest_invalid')
    payload['processed_keys'] = sorted(set(processed_keys))
    return payload


def memorial_seed_manifest_processed_total(slug: str) -> int:
    payload = _load_seed_manifest(slug)
    return len([str(item) for item in (payload.get('processed_keys') or []) if str(item).strip()])


def _save_seed_manifest(slug: str, payload: dict[str, Any]) -> None:
    with _MAIL_MANIFEST_LOCK:
        _ensure_archive_root(slug)
        _atomic_write_json(_seed_manifest_path(slug), payload)


def synthesize_memorial_mail_style_profile(
    *,
    memory_runtime: MemoryRuntimeService,
    principal_id: str,
    memorial_slug: str,
    reviewer: str = 'memorial-mail-style-profile',
) -> dict[str, object]:
    principal = _normalize_text(principal_id)
    slug = _safe_slug(memorial_slug)
    try:
        rows = memory_runtime.export_principal_snapshot(
            principal_id=principal,
            max_items=_LOCAL_SNAPSHOT_MAX_MEMORY_ITEMS,
        )
    except MemoryItemSnapshotLimitExceeded as exc:
        raise ValueError('memorial_mail_style_memory_enumeration_incomplete') from exc
    mail_rows = [
        row
        for row in rows
        if _normalize_text(dict(getattr(row, 'fact_json', {}) or {}).get('memory_kind')).lower() == 'mail_message'
    ]
    source_keys = sorted(
        {
            _normalize_text(dict(getattr(row, 'fact_json', {}) or {}).get('message_key'))
            or _normalize_text(getattr(row, 'item_id', ''))
            for row in mail_rows
            if _normalize_text(dict(getattr(row, 'fact_json', {}) or {}).get('message_key'))
            or _normalize_text(getattr(row, 'item_id', ''))
        }
    )
    if not source_keys:
        return {
            'memorial_slug': slug,
            'principal_id': principal,
            'created': 0,
            'skipped': 0,
            'message_count': 0,
            'source_digest': '',
        }
    source_digest = hashlib.sha256('\n'.join(source_keys).encode('utf-8')).hexdigest()
    for row in rows:
        fact = dict(getattr(row, 'fact_json', {}) or {})
        if (
            _normalize_text(fact.get('memory_kind')).lower() == 'conversation_style'
            and _normalize_text(fact.get('style_key')) == 'gmail_mail_style_profile'
            and _normalize_text(fact.get('source_digest')) == source_digest
        ):
            return {
                'memorial_slug': slug,
                'principal_id': principal,
                'created': 0,
                'skipped': 1,
                'message_count': len(source_keys),
                'source_digest': source_digest,
            }

    body_text = ' '.join(
        _normalize_text(
            dict(getattr(row, 'fact_json', {}) or {}).get('body_text')
            or dict(getattr(row, 'fact_json', {}) or {}).get('body_excerpt')
        )
        for row in mail_rows
    ).lower()
    markers: list[str] = []
    if any(token in body_text for token in ('fakten', 'sachverhalt', 'punkt fuer punkt', 'punkt für punkt')):
        markers.append('Fakten und Sachverhalt zuerst ordnen')
    if any(token in body_text for token in ('rechtlich', 'pflicht', 'verantwortung', 'meines erachtens')):
        markers.append('danach rechtlich oder prinzipiell einordnen')
    if any(token in body_text for token in ('daher', 'bitte', 'folg', 'zunaechst', 'zunächst')):
        markers.append('mit einer knappen praktischen Folgerung schliessen')
    if not markers:
        markers = ['erst den Sachverhalt ordnen', 'dann eine knappe praktische Folgerung nennen']
    note = (
        f'Gmail-Stilprofil aus {len(source_keys)} privaten Mails: '
        + '; '.join(markers[:3])
        + '. Keine Rohmail und kein woertliches Zitat ist in diesem Profil gespeichert.'
    )
    memory_runtime.create_memory_item(
        principal_id=principal,
        category='memorial_mail_style_profile',
        summary=f'Gmail-Stilprofil aus {len(source_keys)} privaten Mails',
        fact_json={
            'memorial_slug': slug,
            'memory_kind': 'conversation_style',
            'memory_axis': 'stylistic',
            'style_key': 'gmail_mail_style_profile',
            'message_count': len(source_keys),
            'source_digest': source_digest,
            'note': note,
        },
        provenance_json={
            'source_type': 'memorial_mail_style_synthesis',
            'memorial_slug': slug,
            'source_digest': source_digest,
            'message_count': len(source_keys),
            'raw_mail_content_embedded': False,
        },
        confidence=0.78,
        sensitivity='private',
        sharing_policy='private',
        reviewer=reviewer,
    )
    return {
        'memorial_slug': slug,
        'principal_id': principal,
        'created': 1,
        'skipped': 0,
        'message_count': len(source_keys),
        'source_digest': source_digest,
    }


def seed_memorial_source_memories(
    *,
    memory_runtime: MemoryRuntimeService,
    principal_id: str,
    memorial_slug: str,
    memorial_payload: dict[str, object],
    private_profile: dict[str, object] | None = None,
    reviewer: str = 'memorial-source-seed',
) -> dict[str, object]:
    with _MAIL_MANIFEST_LOCK:
        return _seed_memorial_source_memories_locked(
            memory_runtime=memory_runtime,
            principal_id=principal_id,
            memorial_slug=memorial_slug,
            memorial_payload=memorial_payload,
            private_profile=private_profile,
            reviewer=reviewer,
        )


def _seed_memorial_source_memories_locked(
    *,
    memory_runtime: MemoryRuntimeService,
    principal_id: str,
    memorial_slug: str,
    memorial_payload: dict[str, object],
    private_profile: dict[str, object] | None,
    reviewer: str,
) -> dict[str, object]:
    slug = _safe_slug(memorial_slug)
    processed = {str(item) for item in (_load_seed_manifest(slug).get('processed_keys') or []) if str(item).strip()}
    try:
        stored_rows = memory_runtime.export_principal_snapshot(
            principal_id=principal_id,
            max_items=_LOCAL_SNAPSHOT_MAX_MEMORY_ITEMS,
        )
    except MemoryItemSnapshotLimitExceeded as exc:
        raise ValueError('memorial_seed_reconciliation_incomplete') from exc
    stored_seed_rows: dict[str, list[object]] = {}
    for item in stored_rows:
        raw_provenance = getattr(item, 'provenance_json', {})
        if not isinstance(raw_provenance, dict):
            continue
        provenance = dict(raw_provenance)
        if (
            _normalize_text(provenance.get('source_type')).lower()
            != 'memorial_seed'
            or _normalize_text(provenance.get('memorial_slug')) != slug
        ):
            continue
        stored_seed_key = _normalize_text(provenance.get('seed_key'))
        if stored_seed_key:
            stored_seed_rows.setdefault(stored_seed_key, []).append(item)
    created_keys: list[str] = []
    current_public_approval_keys: set[str] = set()
    created_count = 0

    def create_seed_item(
        *,
        seed_key: str,
        category: str,
        summary: str,
        fact_json: dict[str, object],
        public_approved: bool = False,
    ) -> None:
        nonlocal created_count
        seed_contract = {
            'category': category,
            'summary': summary,
            'fact_json': dict(fact_json),
            'public_approved': bool(public_approved),
        }
        seed_contract_sha256 = hashlib.sha256(
            json.dumps(
                seed_contract,
                ensure_ascii=False,
                sort_keys=True,
                separators=(',', ':'),
                allow_nan=False,
            ).encode('utf-8')
        ).hexdigest()
        seed_key = f'{seed_key}:v3:{seed_contract_sha256[:24]}'
        public_approval_key = ''
        if public_approved:
            public_approval_key = f'public_v2:{seed_key}'
            current_public_approval_keys.add(public_approval_key)
            seed_key = public_approval_key
        stored_fact = dict(fact_json)
        stored_fact['public_approved'] = bool(public_approved)
        stored_fact['public_approval_key'] = public_approval_key
        stored_provenance = {
            'source_type': 'memorial_seed',
            'memorial_slug': slug,
            'seed_key': seed_key,
            'public_approved': bool(public_approved),
            'public_approval_key': public_approval_key,
        }
        existing_rows = list(stored_seed_rows.get(seed_key) or [])
        if existing_rows:
            if len(existing_rows) != 1:
                raise ValueError('memorial_seed_reconciliation_mismatch')
            existing = existing_rows[0]
            existing_fact = getattr(existing, 'fact_json', {})
            existing_provenance = getattr(existing, 'provenance_json', {})
            if (
                getattr(existing, 'category', '') != category
                or getattr(existing, 'summary', '') != summary
                or not isinstance(existing_fact, dict)
                or dict(existing_fact) != stored_fact
                or not isinstance(existing_provenance, dict)
                or dict(existing_provenance) != stored_provenance
                or getattr(existing, 'sensitivity', '') != 'private'
                or getattr(existing, 'sharing_policy', '') != 'private'
            ):
                raise ValueError('memorial_seed_reconciliation_mismatch')
            processed.add(seed_key)
            return
        created = memory_runtime.create_memory_item(
            principal_id=principal_id,
            category=category,
            summary=summary,
            fact_json=stored_fact,
            provenance_json=stored_provenance,
            confidence=0.82,
            sensitivity='private',
            sharing_policy='private',
            reviewer=reviewer,
        )
        processed.add(seed_key)
        if created is not None:
            stored_seed_rows.setdefault(seed_key, []).append(created)
        created_keys.append(seed_key)
        created_count += 1

    for index, card in enumerate(memorial_payload.get('memory_cards') or []):
        if not isinstance(card, dict):
            continue
        title = _source_text(card.get('title'))
        body = _source_text(card.get('body'))
        source_label = _source_text(card.get('source_label'))
        if not (title or body):
            continue
        create_seed_item(
            seed_key=f'memory_card:{index}:{hashlib.sha1((title + body).encode("utf-8")).hexdigest()[:12]}',
            category='memorial_memory_card',
            summary=_normalize_text(f'{title}: {body}' if title and body else title or body)[:280],
            fact_json={
                'memorial_slug': slug,
                'memory_kind': 'memorial_memory_card',
                'title': title,
                'body': body,
                'source_label': source_label,
                'memory_axis': _infer_memory_axis(kind='memorial_memory_card', title=title, body=body),
            },
            public_approved=_source_item_is_public(card),
        )

    for index, item in enumerate(memorial_payload.get('source_grounded_profile') or []):
        if not isinstance(item, dict):
            continue
        trait = _source_text(item.get('trait'))
        evidence = _source_text(item.get('evidence'))
        confidence = _source_text(item.get('confidence'))
        if not (trait or evidence):
            continue
        create_seed_item(
            seed_key=f'grounded_profile:{index}:{hashlib.sha1((trait + evidence).encode("utf-8")).hexdigest()[:12]}',
            category='memorial_grounded_profile',
            summary=_normalize_text(f'{trait}: {evidence}' if trait and evidence else trait or evidence)[:280],
            fact_json={
                'memorial_slug': slug,
                'memory_kind': 'grounded_profile',
                'trait': trait,
                'evidence': evidence,
                'confidence_label': confidence,
                'memory_axis': _infer_memory_axis(kind='grounded_profile', trait=trait, body=evidence),
            },
            public_approved=_source_item_is_public(item),
        )

    for index, note in enumerate(memorial_payload.get('character_notes') or []):
        normalized = _source_text(note.get('note')) if isinstance(note, dict) else _source_text(note)
        if not normalized:
            continue
        create_seed_item(
            seed_key=f'character_note:{index}:{hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]}',
            category='memorial_character_note',
            summary=normalized[:280],
            fact_json={
                'memorial_slug': slug,
                'memory_kind': 'character_note',
                'note': normalized,
                'memory_axis': _infer_memory_axis(kind='character_note', note=normalized),
            },
            public_approved=_source_item_is_public(note),
        )

    conversation_style = memorial_payload.get('conversation_style')
    if isinstance(conversation_style, dict):
        conversation_style_public = _source_item_is_public(conversation_style)
        for style_key in ('reasoning_frame', 'conflict_style', 'social_tone'):
            normalized = _source_text(conversation_style.get(style_key))
            if not normalized:
                continue
            create_seed_item(
                seed_key=f'conversation_style:{style_key}:{hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]}',
                category='memorial_conversation_style',
                summary=_normalize_text(f'{style_key}: {normalized}')[:280],
                fact_json={
                    'memorial_slug': slug,
                    'memory_kind': 'conversation_style',
                    'style_key': style_key,
                    'note': normalized,
                    'memory_axis': 'stylistic',
                },
                public_approved=conversation_style_public,
            )
        for index, avoid_item in enumerate(conversation_style.get('should_avoid') or []):
            normalized = _source_text(avoid_item)
            if not normalized:
                continue
            create_seed_item(
                seed_key=f'conversation_avoid:{index}:{hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]}',
                category='memorial_conversation_avoid',
                summary=_normalize_text(f'avoid: {normalized}')[:280],
                fact_json={
                    'memorial_slug': slug,
                    'memory_kind': 'conversation_avoid',
                    'note': normalized,
                    'memory_axis': 'stylistic',
                },
                public_approved=conversation_style_public,
            )

    for index, prompt in enumerate(memorial_payload.get('suggested_prompts') or []):
        normalized = _source_text(prompt)
        if not normalized:
            continue
        create_seed_item(
            seed_key=f'suggested_prompt:{index}:{hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]}',
            category='memorial_suggested_prompt',
            summary=normalized[:280],
            fact_json={
                'memorial_slug': slug,
                'memory_kind': 'suggested_prompt',
                'note': normalized,
                'memory_axis': 'general',
            },
            public_approved=True,
        )

    for index, source in enumerate(memorial_payload.get('external_sources') or []):
        if not isinstance(source, dict):
            continue
        label = _source_text(source.get('label'))
        raw_url = _source_text(source.get('url'))
        url = _safe_public_https_url(raw_url)
        status = _source_text(source.get('status'))
        if not label and not url:
            continue
        source_public = _source_item_is_public(source) and bool(url)
        create_seed_item(
            seed_key=f'external_source:{index}:{hashlib.sha1((label + url).encode("utf-8")).hexdigest()[:12]}',
            category='memorial_external_source',
            summary=_normalize_text(f'{label} {url}')[:280],
            fact_json={
                'memorial_slug': slug,
                'memory_kind': 'external_source',
                'label': label,
                'url': url,
                'status': status,
                'memory_axis': _infer_memory_axis(kind='external_source', title=label, body=url),
            },
            public_approved=source_public,
        )

    if isinstance(private_profile, dict):
        for index, note in enumerate(private_profile.get('public_source_notes') or []):
            if not isinstance(note, dict):
                continue
            label = _source_text(note.get('label'))
            raw_source_url = _source_text(note.get('source_url'))
            source_url = _safe_public_https_url(raw_source_url)
            note_text = _source_text(note.get('note'))
            confidence = _source_text(note.get('confidence'))
            if not note_text:
                continue
            note_public = _source_item_is_public(note) and (not raw_source_url or bool(source_url))
            create_seed_item(
                seed_key=f'public_source_note:{index}:{hashlib.sha1((label + source_url + note_text).encode("utf-8")).hexdigest()[:12]}',
                category='memorial_public_source_note',
                summary=_normalize_text(f'{label or "public source"}: {note_text}')[:280],
                fact_json={
                    'memorial_slug': slug,
                    'memory_kind': 'public_source_note',
                    'label': label,
                    'source_url': source_url,
                    'note': note_text,
                    'confidence_label': confidence,
                    'memory_axis': _infer_memory_axis(kind='public_source_note', title=label, body=note_text),
                },
                public_approved=note_public,
            )
        for index, note in enumerate(private_profile.get('family_context_notes') or []):
            if not isinstance(note, dict):
                continue
            trait = _source_text(note.get('trait'))
            evidence = _source_text(note.get('evidence'))
            if not (trait or evidence):
                continue
            create_seed_item(
                seed_key=f'family_note:{index}:{hashlib.sha1((trait + evidence).encode("utf-8")).hexdigest()[:12]}',
                category='memorial_family_context',
                summary=_normalize_text(f'{trait}: {evidence}' if trait and evidence else trait or evidence)[:280],
                fact_json={
                    'memorial_slug': slug,
                    'memory_kind': 'family_context_note',
                    'trait': trait,
                    'evidence': evidence,
                    'memory_axis': _infer_memory_axis(kind='family_context_note', trait=trait, body=evidence),
                },
                public_approved=_source_item_is_public(note),
            )

    _save_seed_manifest(
        slug,
        {
            'processed_keys': sorted(processed),
            'public_approval_keys': sorted(current_public_approval_keys),
        },
    )
    return {
        'memorial_slug': slug,
        'principal_id': principal_id,
        'created': created_count,
        'created_keys': created_keys[:100],
        'processed_total': len(processed),
        'public_approval_keys': sorted(current_public_approval_keys),
    }


def retrieve_memorial_memory_items(
    *,
    memory_runtime: MemoryRuntimeService,
    principal_id: str,
    question: str,
    limit: int = 6,
    public_only: bool = False,
    public_approval_keys: Iterable[str] | None = None,
) -> list[MemoryItem]:
    query_tokens = _tokenize(question)
    rows = memory_runtime.list_items(limit=500, principal_id=principal_id)
    if public_only:
        allowed_public_keys = {str(item) for item in (public_approval_keys or []) if str(item).strip()}
        rows = [
            row
            for row in rows
            if dict(row.fact_json or {}).get('public_approved') is True
            and str(dict(row.fact_json or {}).get('public_approval_key') or '') in allowed_public_keys
        ]
    if not query_tokens:
        return rows[:limit]
    scored: list[tuple[float, MemoryItem]] = []
    for row in rows:
        fact = dict(row.fact_json or {})
        haystack = ' '.join([
            row.summary,
            str(fact.get('subject') or ''),
            str(fact.get('body_excerpt') or ''),
            str(fact.get('body') or ''),
            str(fact.get('trait') or ''),
            str(fact.get('evidence') or ''),
            str(fact.get('title') or ''),
            str(fact.get('note') or ''),
            ' '.join(str(item) for item in (fact.get('urls') or [])),
        ])
        tokens = _tokenize(haystack)
        overlap = query_tokens & tokens
        if not overlap:
            continue
        score = float(len(overlap))
        score += _memory_kind_retrieval_boost(query_tokens=query_tokens, fact=fact, row=row)
        if any(token in str(fact.get('subject') or '').lower() for token in query_tokens):
            score += 0.4
        if any(token in str(fact.get('title') or '').lower() for token in query_tokens):
            score += 0.45
        if all(token in tokens for token in query_tokens if len(token) >= 4):
            score += 0.35
        scored.append((score, row))
    scored.sort(key=lambda item: (item[0], item[1].updated_at), reverse=True)
    selected = [row for _, row in scored[:limit]]
    if len(selected) < limit:
        selected_ids = {str(getattr(row, 'item_id', '') or '') for row in selected}
        style_fallbacks = [
            row
            for row in rows
            if str(getattr(row, 'item_id', '') or '') not in selected_ids
            and _normalize_text(dict(getattr(row, 'fact_json', {}) or {}).get('memory_kind')).lower()
            in {'conversation_style', 'conversation_avoid'}
        ]
        style_fallbacks.sort(key=lambda row: str(getattr(row, 'updated_at', '') or ''), reverse=True)
        selected.extend(style_fallbacks[: max(0, limit - len(selected))])
    return selected[:limit]


def format_memorial_memory_context(rows: list[MemoryItem]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        fact = dict(row.fact_json or {})
        axis = _normalize_text(fact.get('memory_axis')).lower()
        memory_kind = _normalize_text(fact.get('memory_kind')).lower()
        subject = _normalize_text(fact.get('subject'))
        source = _normalize_text(fact.get('from'))
        if memory_kind == 'mail_message':
            excerpt = _mail_memory_excerpt(row=row, fact=fact)
            bits = []
        else:
            excerpt = _normalize_text(fact.get('body_excerpt'))[:360]
            if not excerpt:
                excerpt = _normalize_text(fact.get('body') or fact.get('evidence') or fact.get('note') or fact.get('title'))[:360]
            date = _normalize_text(fact.get('date'))
            bits = [bit for bit in [date, subject, source] if bit]
        prefix = ' | '.join(bits)
        axis_label = {
            'stylistic': 'Stil',
            'episodic': 'Erinnerung',
            'legal': 'Grundsatz',
            'general': 'Kontext',
        }.get(axis, '')
        if prefix and excerpt:
            line = f'{prefix}: {excerpt}'
        elif excerpt:
            line = excerpt
        elif row.summary:
            line = _normalize_text(row.summary)
        else:
            continue
        if axis_label:
            line = f'[{axis_label}] {line}'
        lines.append(line)
    return lines[:6]


def memorial_has_imported_mail(memory_runtime: MemoryRuntimeService | None, *, principal_id: str) -> bool:
    if memory_runtime is None:
        return False
    principal = _normalize_text(principal_id)
    slug = _safe_slug(principal.split(':', 1)[-1])
    try:
        manifest = _load_manifest(slug, legacy_principal_id=principal)
    except ValueError:
        return False
    processed_by_principal = dict(manifest.get('processed_by_principal') or {})
    processed = {
        str(item).strip()
        for item in list(processed_by_principal.get(principal) or [])
        if str(item).strip()
    }
    if not processed and principal == f'memorial:{slug}':
        processed = {str(item).strip() for item in list(manifest.get('processed_keys') or []) if str(item).strip()}
    if not processed:
        return False
    try:
        rows = memory_runtime.export_principal_snapshot(
            principal_id=principal,
            max_items=_LOCAL_SNAPSHOT_MAX_MEMORY_ITEMS,
        )
    except Exception:
        return False
    return any(
        _normalize_text(dict(getattr(row, 'fact_json', {}) or {}).get('memory_kind')).lower() == 'mail_message'
        and _normalize_text(dict(getattr(row, 'fact_json', {}) or {}).get('message_key')) in processed
        for row in rows
    )


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(',', ':'),
        ).encode('utf-8')
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError('memorial_local_snapshot_json_invalid') from exc


def _strip_publication_state(value: object, *, _depth: int = 0) -> object:
    if _depth > 64:
        raise ValueError('memorial_local_snapshot_json_invalid')
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError('memorial_local_snapshot_json_invalid')
        return {
            key: _strip_publication_state(item, _depth=_depth + 1)
            for key, item in value.items()
            if key.strip().lower() not in _PUBLICATION_STATE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_strip_publication_state(item, _depth=_depth + 1) for item in value]
    return value


def _require_local_snapshot_scope(*, memorial_slug: str, principal_id: str) -> tuple[str, str]:
    slug = str(memorial_slug or '')
    principal = str(principal_id or '')
    if (
        not slug
        or slug != slug.strip().lower()
        or len(slug) > 80
        or _safe_slug(slug) != slug
    ):
        raise ValueError('memorial_local_snapshot_scope_invalid')
    if principal != f'memorial:{slug}':
        raise ValueError('memorial_local_snapshot_scope_invalid')
    return slug, principal


def _snapshot_memory_record(*, row: object, slug: str, principal: str) -> dict[str, object]:
    if str(getattr(row, 'principal_id', '') or '') != principal:
        raise ValueError('memorial_local_snapshot_memory_scope_mismatch')
    raw_fact = getattr(row, 'fact_json', {}) or {}
    raw_provenance = getattr(row, 'provenance_json', {}) or {}
    if not isinstance(raw_fact, dict) or not isinstance(raw_provenance, dict):
        raise ValueError('memorial_local_snapshot_memory_invalid')
    explicit_slug = _normalize_text(raw_fact.get('memorial_slug'))
    if explicit_slug and explicit_slug != slug:
        raise ValueError('memorial_local_snapshot_memory_scope_mismatch')
    fact = _strip_publication_state(raw_fact)
    provenance = _strip_publication_state(raw_provenance)
    if not isinstance(fact, dict) or not isinstance(provenance, dict):
        raise ValueError('memorial_local_snapshot_memory_invalid')
    provenance.pop('local_recovery_receipt', None)
    fact['memorial_slug'] = slug
    try:
        confidence = float(getattr(row, 'confidence', 0.5))
    except (TypeError, ValueError) as exc:
        raise ValueError('memorial_local_snapshot_memory_invalid') from exc
    if not math.isfinite(confidence):
        raise ValueError('memorial_local_snapshot_memory_invalid')
    last_verified = getattr(row, 'last_verified_at', None)
    last_verified_text = str(last_verified).strip() if last_verified else None
    if last_verified_text:
        if len(last_verified_text) > 200:
            raise ValueError('memorial_local_snapshot_memory_invalid')
        try:
            parsed_last_verified = datetime.fromisoformat(last_verified_text.replace('Z', '+00:00'))
        except ValueError as exc:
            raise ValueError('memorial_local_snapshot_memory_invalid') from exc
        if parsed_last_verified.tzinfo is None:
            raise ValueError('memorial_local_snapshot_memory_invalid')
    category = str(getattr(row, 'category', '') or 'fact').strip() or 'fact'
    summary = str(getattr(row, 'summary', '') or '').strip()
    reviewer = str(getattr(row, 'reviewer', '') or '').strip()
    if len(category) > 200 or len(summary) > 16000 or len(reviewer) > 500:
        raise ValueError('memorial_local_snapshot_memory_invalid')
    return {
        'category': category,
        'summary': summary,
        'fact_json': fact,
        'provenance_json': provenance,
        'confidence': max(0.0, min(1.0, confidence)),
        'sensitivity': 'private',
        'sharing_policy': 'private',
        'reviewer': reviewer,
        'last_verified_at': last_verified_text,
    }


def _snapshot_memory_entry(*, row: object, slug: str, principal: str) -> dict[str, object]:
    record = _snapshot_memory_record(row=row, slug=slug, principal=principal)
    return {
        'content_sha256': hashlib.sha256(_canonical_json_bytes(record)).hexdigest(),
        'record': record,
    }


def _snapshot_memory_rows(
    *,
    memory_runtime: MemoryRuntimeService,
    slug: str,
    principal: str,
) -> list[dict[str, object]]:
    try:
        rows = list(
            memory_runtime.export_principal_snapshot(
                principal_id=principal,
                max_items=_LOCAL_SNAPSHOT_MAX_MEMORY_ITEMS,
            )
        )
    except MemoryItemSnapshotLimitExceeded as exc:
        raise ValueError('memorial_local_snapshot_memory_enumeration_incomplete') from exc
    entries = [_snapshot_memory_entry(row=row, slug=slug, principal=principal) for row in rows]
    entries.sort(key=lambda item: (str(item['content_sha256']), _canonical_json_bytes(item['record'])))
    if len(_canonical_json_bytes(entries)) > _LOCAL_SNAPSHOT_MAX_MEMORY_BYTES:
        raise ValueError('memorial_local_snapshot_memory_too_large')
    return entries


def _snapshot_raw_mail(*, slug: str, principal: str) -> tuple[list[str], list[dict[str, str]]]:
    manifest = _load_manifest(slug, legacy_principal_id=principal)
    processed_by_principal = dict(manifest.get('processed_by_principal') or {})
    message_keys = sorted(
        {
            str(item).strip()
            for item in list(processed_by_principal.get(principal) or [])
            if str(item).strip()
        }
    )
    if len(message_keys) > 5000:
        raise ValueError('memorial_local_snapshot_raw_mail_too_large')
    raw_rows: list[dict[str, str]] = []
    raw_total = 0
    for message_key in message_keys:
        if re.fullmatch(r'[0-9a-f]{40}', message_key) is None:
            raise ValueError('memorial_local_snapshot_raw_mail_invalid')
        raw_path = _archive_root_for(slug) / 'raw' / f'{message_key}.eml'
        try:
            raw_bytes = _read_regular_file_bounded(
                raw_path,
                max_bytes=_MAIL_MAX_RAW_MESSAGE_BYTES,
            )
        except _BoundedFileTooLarge as exc:
            raise ValueError('memorial_local_snapshot_raw_mail_too_large') from exc
        except (OSError, ValueError) as exc:
            raise ValueError('memorial_local_snapshot_raw_mail_incomplete') from exc
        raw_total += len(raw_bytes)
        if raw_total > _MAIL_MAX_IMPORT_BYTES:
            raise ValueError('memorial_local_snapshot_raw_mail_too_large')
        raw_rows.append(
            {
                'message_key': message_key,
                'raw_sha256': hashlib.sha256(raw_bytes).hexdigest(),
                'raw_base64': base64.b64encode(raw_bytes).decode('ascii'),
            }
        )
    return message_keys, raw_rows


def _validate_snapshot_mail_memory_links(
    *,
    memory_items: list[dict[str, object]],
    raw_mail: list[dict[str, str]],
) -> None:
    raw_by_key = {item['message_key']: item for item in raw_mail}
    for item in memory_items:
        record = item.get('record')
        if not isinstance(record, dict) or not isinstance(record.get('fact_json'), dict):
            raise ValueError('memorial_local_snapshot_memory_invalid')
        fact = dict(record['fact_json'])
        if _normalize_text(fact.get('memory_kind')).lower() != 'mail_message':
            continue
        message_key = _normalize_text(fact.get('message_key'))
        raw_sha256 = _normalize_text(fact.get('raw_sha256'))
        raw_archive_relpath = _normalize_text(fact.get('raw_archive_relpath'))
        raw_item = raw_by_key.get(message_key)
        if (
            re.fullmatch(r'[0-9a-f]{40}', message_key) is None
            or re.fullmatch(r'[0-9a-f]{64}', raw_sha256) is None
            or raw_item is None
            or not hmac.compare_digest(raw_sha256, raw_item['raw_sha256'])
            or raw_archive_relpath != f'raw/{message_key}.eml'
        ):
            raise ValueError('memorial_local_snapshot_raw_mail_memory_mismatch')


def _normalize_snapshot_mail_memory_links(
    *,
    memory_items: list[dict[str, object]],
    raw_mail: list[dict[str, str]],
) -> list[dict[str, object]]:
    raw_by_key = {item['message_key']: item for item in raw_mail}
    normalized: list[dict[str, object]] = []
    for item in memory_items:
        entry = dict(item)
        record = dict(entry.get('record') or {})
        fact = dict(record.get('fact_json') or {})
        provenance = dict(record.get('provenance_json') or {})
        if _normalize_text(fact.get('memory_kind')).lower() == 'mail_message':
            message_key = _normalize_text(fact.get('message_key'))
            raw_item = raw_by_key.get(message_key)
            expected_relpath = f'raw/{message_key}.eml'
            current_relpath = _normalize_text(fact.get('raw_archive_relpath'))
            fact_digest = _normalize_text(fact.get('raw_sha256'))
            provenance_digest = _normalize_text(provenance.get('raw_sha256'))
            if (
                re.fullmatch(r'[0-9a-f]{40}', message_key) is None
                or raw_item is None
                or current_relpath != expected_relpath
                or (fact_digest and not hmac.compare_digest(fact_digest, raw_item['raw_sha256']))
                or (provenance_digest and not hmac.compare_digest(provenance_digest, raw_item['raw_sha256']))
            ):
                raise ValueError('memorial_local_snapshot_raw_mail_memory_mismatch')
            fact['raw_sha256'] = raw_item['raw_sha256']
            provenance['raw_sha256'] = raw_item['raw_sha256']
            record['fact_json'] = fact
            record['provenance_json'] = provenance
            entry = {
                'content_sha256': hashlib.sha256(_canonical_json_bytes(record)).hexdigest(),
                'record': record,
            }
        normalized.append(entry)
    normalized.sort(key=lambda item: (str(item['content_sha256']), _canonical_json_bytes(item['record'])))
    return normalized


def export_memorial_local_snapshot(
    *,
    memory_runtime: MemoryRuntimeService,
    principal_id: str,
    memorial_slug: str,
    destination_path: str,
) -> dict[str, object]:
    """Export one private EA-local recovery bundle.

    The bundle is intentionally unencrypted and noncanonical. Its atomic file is
    mode 0600, and it never contains Hub/Registry publication state.
    """

    slug, principal = _require_local_snapshot_scope(
        memorial_slug=memorial_slug,
        principal_id=principal_id,
    )
    destination = Path(str(destination_path or '').strip()).expanduser()
    if not str(destination_path or '').strip():
        raise ValueError('memorial_local_snapshot_destination_invalid')
    with _memorial_storage_lock(slug):
        snapshot_root = _ensure_archive_root(slug, 'snapshots')
        destination = _require_contained_path(root=snapshot_root, candidate=destination)
        if destination.parent != snapshot_root:
            raise ValueError('memorial_local_snapshot_destination_invalid')
        if os.path.lexists(destination):
            raise ValueError('memorial_local_snapshot_destination_exists')
        message_keys, raw_mail = _snapshot_raw_mail(slug=slug, principal=principal)
        memory_items = _normalize_snapshot_mail_memory_links(
            memory_items=_snapshot_memory_rows(
                memory_runtime=memory_runtime,
                slug=slug,
                principal=principal,
            ),
            raw_mail=raw_mail,
        )
        _validate_snapshot_mail_memory_links(memory_items=memory_items, raw_mail=raw_mail)
        payload: dict[str, object] = {
            'authority': dict(_LOCAL_SNAPSHOT_AUTHORITY),
            'memorial_slug': slug,
            'principal_id': principal,
            'memory_items': memory_items,
            'mail_manifest': {
                'schema': _LOCAL_SNAPSHOT_MAIL_SCHEMA,
                'message_keys': message_keys,
            },
            'raw_mail': raw_mail,
        }
        payload_sha256 = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
        envelope = {
            'schema': _LOCAL_SNAPSHOT_SCHEMA,
            'payload_sha256': payload_sha256,
            'payload': payload,
        }
        document = _canonical_json_bytes(envelope) + b'\n'
        if len(document) > _LOCAL_SNAPSHOT_MAX_FILE_BYTES:
            raise ValueError('memorial_local_snapshot_file_too_large')
        try:
            _atomic_write_bytes(destination, document, replace_existing=False)
        except FileExistsError as exc:
            raise ValueError('memorial_local_snapshot_destination_exists') from exc
    return {
        'schema': _LOCAL_SNAPSHOT_SCHEMA,
        'memorial_slug': slug,
        'principal_id': principal,
        'snapshot_path': str(destination),
        'payload_sha256': payload_sha256,
        'snapshot_file_sha256': hashlib.sha256(document).hexdigest(),
        'memory_item_count': len(memory_items),
        'raw_mail_count': len(raw_mail),
        'raw_mail_bytes': sum(len(base64.b64decode(item['raw_base64'])) for item in raw_mail),
        'private_file_mode': '0600',
        'encrypted': False,
        'authenticated': False,
        'integrity_model': 'sha256_accidental_corruption_only',
        'canonical_publication_state_included': False,
    }


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError('memorial_local_snapshot_json_invalid')
        payload[key] = value
    return payload


def _reject_nonfinite_json(_value: str) -> object:
    raise ValueError('memorial_local_snapshot_json_invalid')


def _validate_snapshot_memory_entry(
    *,
    entry: object,
    slug: str,
) -> tuple[str, dict[str, object]]:
    if not isinstance(entry, dict) or set(entry) != {'content_sha256', 'record'}:
        raise ValueError('memorial_local_snapshot_memory_invalid')
    digest = str(entry.get('content_sha256') or '')
    record = entry.get('record')
    required_record_keys = {
        'category',
        'summary',
        'fact_json',
        'provenance_json',
        'confidence',
        'sensitivity',
        'sharing_policy',
        'reviewer',
        'last_verified_at',
    }
    if not isinstance(record, dict) or set(record) != required_record_keys:
        raise ValueError('memorial_local_snapshot_memory_invalid')
    if re.fullmatch(r'[0-9a-f]{64}', digest) is None:
        raise ValueError('memorial_local_snapshot_memory_invalid')
    actual_digest = hashlib.sha256(_canonical_json_bytes(record)).hexdigest()
    if not hmac.compare_digest(digest, actual_digest):
        raise ValueError('memorial_local_snapshot_memory_digest_mismatch')
    category = record.get('category')
    summary = record.get('summary')
    reviewer = record.get('reviewer')
    if (
        not isinstance(category, str)
        or not category
        or len(category) > 200
        or not isinstance(summary, str)
        or len(summary) > 16000
        or not isinstance(reviewer, str)
        or len(reviewer) > 500
    ):
        raise ValueError('memorial_local_snapshot_memory_invalid')
    if record.get('sensitivity') != 'private' or record.get('sharing_policy') != 'private':
        raise ValueError('memorial_local_snapshot_memory_not_private')
    fact = record.get('fact_json')
    provenance = record.get('provenance_json')
    if not isinstance(fact, dict) or not isinstance(provenance, dict):
        raise ValueError('memorial_local_snapshot_memory_invalid')
    if _strip_publication_state(fact) != fact or _strip_publication_state(provenance) != provenance:
        raise ValueError('memorial_local_snapshot_publication_state_forbidden')
    if 'local_recovery_receipt' in provenance or _normalize_text(fact.get('memorial_slug')) != slug:
        raise ValueError('memorial_local_snapshot_memory_scope_mismatch')
    try:
        confidence = float(record.get('confidence'))
    except (TypeError, ValueError) as exc:
        raise ValueError('memorial_local_snapshot_memory_invalid') from exc
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise ValueError('memorial_local_snapshot_memory_invalid')
    last_verified = record.get('last_verified_at')
    if last_verified is not None:
        if not isinstance(last_verified, str) or not last_verified or len(last_verified) > 200:
            raise ValueError('memorial_local_snapshot_memory_invalid')
        try:
            parsed_last_verified = datetime.fromisoformat(last_verified.replace('Z', '+00:00'))
        except ValueError as exc:
            raise ValueError('memorial_local_snapshot_memory_invalid') from exc
        if parsed_last_verified.tzinfo is None:
            raise ValueError('memorial_local_snapshot_memory_invalid')
    return digest, record


def _load_verified_memorial_local_snapshot(
    *,
    snapshot_path: str,
    expected_memorial_slug: str,
    expected_principal_id: str,
) -> tuple[dict[str, object], str, str]:
    slug, principal = _require_local_snapshot_scope(
        memorial_slug=expected_memorial_slug,
        principal_id=expected_principal_id,
    )
    source = Path(str(snapshot_path or '').strip()).expanduser()
    if not str(snapshot_path or '').strip():
        raise ValueError('memorial_local_snapshot_file_invalid')
    try:
        source = _require_contained_path(root=_snapshot_root_for(slug), candidate=source)
        if source.parent != _absolute_path(_snapshot_root_for(slug)):
            raise ValueError('memorial_local_snapshot_file_invalid')
        document = _read_regular_file_bounded(
            source,
            max_bytes=_LOCAL_SNAPSHOT_MAX_FILE_BYTES,
        )
    except _BoundedFileTooLarge as exc:
        raise ValueError('memorial_local_snapshot_file_too_large') from exc
    except (OSError, ValueError) as exc:
        raise ValueError('memorial_local_snapshot_file_invalid') from exc
    try:
        envelope = json.loads(
            document.decode('utf-8'),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ValueError('memorial_local_snapshot_json_invalid') from exc
    if not isinstance(envelope, dict) or set(envelope) != {'schema', 'payload_sha256', 'payload'}:
        raise ValueError('memorial_local_snapshot_invalid')
    if envelope.get('schema') != _LOCAL_SNAPSHOT_SCHEMA:
        raise ValueError('memorial_local_snapshot_schema_unsupported')
    payload = envelope.get('payload')
    payload_sha256 = str(envelope.get('payload_sha256') or '')
    if not isinstance(payload, dict) or set(payload) != {
        'authority',
        'memorial_slug',
        'principal_id',
        'memory_items',
        'mail_manifest',
        'raw_mail',
    }:
        raise ValueError('memorial_local_snapshot_invalid')
    actual_payload_sha256 = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
    if not hmac.compare_digest(payload_sha256, actual_payload_sha256):
        raise ValueError('memorial_local_snapshot_payload_digest_mismatch')
    if payload.get('authority') != _LOCAL_SNAPSHOT_AUTHORITY:
        raise ValueError('memorial_local_snapshot_authority_invalid')
    if payload.get('memorial_slug') != slug or payload.get('principal_id') != principal:
        raise ValueError('memorial_local_snapshot_scope_mismatch')
    memory_items = payload.get('memory_items')
    if not isinstance(memory_items, list) or len(memory_items) > _LOCAL_SNAPSHOT_MAX_MEMORY_ITEMS:
        raise ValueError('memorial_local_snapshot_memory_invalid')
    if len(_canonical_json_bytes(memory_items)) > _LOCAL_SNAPSHOT_MAX_MEMORY_BYTES:
        raise ValueError('memorial_local_snapshot_memory_too_large')
    validated_memory = [
        _validate_snapshot_memory_entry(entry=entry, slug=slug)
        for entry in memory_items
    ]
    if validated_memory != sorted(validated_memory, key=lambda item: (item[0], _canonical_json_bytes(item[1]))):
        raise ValueError('memorial_local_snapshot_memory_order_invalid')
    raw_mail = payload.get('raw_mail')
    mail_manifest = payload.get('mail_manifest')
    if (
        not isinstance(raw_mail, list)
        or len(raw_mail) > 5000
        or not isinstance(mail_manifest, dict)
        or set(mail_manifest) != {'schema', 'message_keys'}
        or mail_manifest.get('schema') != _LOCAL_SNAPSHOT_MAIL_SCHEMA
        or not isinstance(mail_manifest.get('message_keys'), list)
    ):
        raise ValueError('memorial_local_snapshot_raw_mail_invalid')
    decoded_total = 0
    raw_keys: list[str] = []
    for item in raw_mail:
        if not isinstance(item, dict) or set(item) != {'message_key', 'raw_sha256', 'raw_base64'}:
            raise ValueError('memorial_local_snapshot_raw_mail_invalid')
        message_key = str(item.get('message_key') or '')
        raw_sha256 = str(item.get('raw_sha256') or '')
        raw_base64 = item.get('raw_base64')
        if (
            re.fullmatch(r'[0-9a-f]{40}', message_key) is None
            or re.fullmatch(r'[0-9a-f]{64}', raw_sha256) is None
            or not isinstance(raw_base64, str)
        ):
            raise ValueError('memorial_local_snapshot_raw_mail_invalid')
        try:
            raw_bytes = base64.b64decode(raw_base64, validate=True)
        except Exception as exc:
            raise ValueError('memorial_local_snapshot_raw_mail_invalid') from exc
        if base64.b64encode(raw_bytes).decode('ascii') != raw_base64:
            raise ValueError('memorial_local_snapshot_raw_mail_invalid')
        if len(raw_bytes) > _MAIL_MAX_RAW_MESSAGE_BYTES:
            raise ValueError('memorial_local_snapshot_raw_mail_too_large')
        decoded_total += len(raw_bytes)
        if decoded_total > _MAIL_MAX_IMPORT_BYTES:
            raise ValueError('memorial_local_snapshot_raw_mail_too_large')
        if not hmac.compare_digest(hashlib.sha256(raw_bytes).hexdigest(), raw_sha256):
            raise ValueError('memorial_local_snapshot_raw_mail_digest_mismatch')
        raw_keys.append(message_key)
    if raw_keys != sorted(set(raw_keys)) or mail_manifest.get('message_keys') != raw_keys:
        raise ValueError('memorial_local_snapshot_raw_mail_manifest_mismatch')
    _validate_snapshot_mail_memory_links(
        memory_items=[dict(item) for item in memory_items],
        raw_mail=[dict(item) for item in raw_mail],
    )
    return payload, payload_sha256, hashlib.sha256(document).hexdigest()


def verify_memorial_local_snapshot(
    *,
    snapshot_path: str,
    expected_principal_id: str,
    expected_memorial_slug: str,
) -> dict[str, object]:
    payload, payload_sha256, file_sha256 = _load_verified_memorial_local_snapshot(
        snapshot_path=snapshot_path,
        expected_memorial_slug=expected_memorial_slug,
        expected_principal_id=expected_principal_id,
    )
    raw_mail = list(payload['raw_mail'])
    return {
        'valid': True,
        'schema': _LOCAL_SNAPSHOT_SCHEMA,
        'memorial_slug': payload['memorial_slug'],
        'principal_id': payload['principal_id'],
        'payload_sha256': payload_sha256,
        'snapshot_file_sha256': file_sha256,
        'memory_item_count': len(list(payload['memory_items'])),
        'raw_mail_count': len(raw_mail),
        'raw_mail_bytes': sum(len(base64.b64decode(item['raw_base64'])) for item in raw_mail),
        'authenticated': False,
        'integrity_model': 'sha256_accidental_corruption_only',
        'canonical_publication_state_included': False,
    }


def _restore_memorial_local_snapshot_locked(
    *,
    memory_runtime: MemoryRuntimeService,
    principal_id: str,
    memorial_slug: str,
    snapshot_path: str,
    dry_run: bool = True,
    confirmed_payload_sha256: str = '',
    recovery_reviewer: str = 'memorial-local-recovery',
    allow_ephemeral_test_backend: bool = False,
) -> dict[str, object]:
    """Plan or merge a verified local snapshot without deleting target data."""

    if not isinstance(dry_run, bool):
        raise ValueError('memorial_local_snapshot_dry_run_invalid')
    if not isinstance(allow_ephemeral_test_backend, bool):
        raise ValueError('memorial_local_snapshot_ephemeral_override_invalid')
    storage_durable = bool(getattr(memory_runtime, 'snapshot_storage_durable', False))
    if not storage_durable and not allow_ephemeral_test_backend:
        raise ValueError('memorial_local_snapshot_durable_storage_required')
    slug, principal = _require_local_snapshot_scope(
        memorial_slug=memorial_slug,
        principal_id=principal_id,
    )
    payload, payload_sha256, file_sha256 = _load_verified_memorial_local_snapshot(
        snapshot_path=snapshot_path,
        expected_memorial_slug=slug,
        expected_principal_id=principal,
    )
    recovery_actor = _normalize_text(recovery_reviewer) or 'memorial-local-recovery'
    if len(recovery_actor) > 500:
        raise ValueError('memorial_local_snapshot_recovery_reviewer_invalid')
    if not dry_run:
        confirmation = str(confirmed_payload_sha256 or '')
        if not confirmation:
            raise ValueError('memorial_local_snapshot_apply_confirmation_required')
        if not hmac.compare_digest(confirmation, payload_sha256):
            raise ValueError('memorial_local_snapshot_apply_confirmation_mismatch')
    try:
        existing_rows = list(
            memory_runtime.export_principal_snapshot(
                principal_id=principal,
                max_items=_LOCAL_SNAPSHOT_MAX_MEMORY_ITEMS,
            )
        )
    except MemoryItemSnapshotLimitExceeded as exc:
        raise ValueError('memorial_local_snapshot_target_enumeration_incomplete') from exc
    existing_digests: Counter[str] = Counter()
    for row in existing_rows:
        raw_fact = getattr(row, 'fact_json', {}) or {}
        raw_provenance = getattr(row, 'provenance_json', {}) or {}
        recovery_receipt = (
            raw_provenance.get('local_recovery_receipt')
            if isinstance(raw_provenance, dict)
            else None
        )
        if (
            isinstance(recovery_receipt, dict)
            and recovery_receipt.get('schema') == _LOCAL_SNAPSHOT_RECOVERY_SCHEMA
            and recovery_receipt.get('payload_sha256') == payload_sha256
            and re.fullmatch(
                r'[0-9a-f]{64}',
                str(recovery_receipt.get('item_content_sha256') or ''),
            )
            is not None
        ):
            existing_digests[str(recovery_receipt['item_content_sha256'])] += 1
            continue
        if (
            str(getattr(row, 'sharing_policy', 'private') or '') != 'private'
            or str(getattr(row, 'sensitivity', 'private') or '') != 'private'
            or _strip_publication_state(raw_fact) != raw_fact
            or _strip_publication_state(raw_provenance) != raw_provenance
        ):
            continue
        entry = _snapshot_memory_entry(row=row, slug=slug, principal=principal)
        existing_digests[str(entry['content_sha256'])] += 1
    memory_to_create: list[dict[str, object]] = []
    available = Counter(existing_digests)
    for raw_entry in list(payload['memory_items']):
        entry = dict(raw_entry)
        digest = str(entry['content_sha256'])
        if available[digest] > 0:
            available[digest] -= 1
            continue
        memory_to_create.append(entry)

    _load_manifest(slug, legacy_principal_id=principal)
    raw_to_write: list[dict[str, str]] = []
    for raw_entry in list(payload['raw_mail']):
        item = dict(raw_entry)
        message_key = str(item['message_key'])
        raw_bytes = base64.b64decode(str(item['raw_base64']), validate=True)
        target = _archive_root_for(slug) / 'raw' / f'{message_key}.eml'
        try:
            existing_raw = _read_regular_file_bounded(
                target,
                max_bytes=_MAIL_MAX_RAW_MESSAGE_BYTES,
            )
        except FileNotFoundError:
            existing_raw = None
        except (_BoundedFileTooLarge, OSError, ValueError) as exc:
            raise ValueError('memorial_local_snapshot_raw_mail_conflict') from exc
        if existing_raw is not None:
            if not hmac.compare_digest(hashlib.sha256(existing_raw).hexdigest(), str(item['raw_sha256'])):
                raise ValueError('memorial_local_snapshot_raw_mail_conflict')
            continue
        raw_to_write.append(
            {
                'message_key': message_key,
                'raw_sha256': str(item['raw_sha256']),
                'raw_base64': str(item['raw_base64']),
            }
        )

    if len(existing_rows) + len(memory_to_create) > _LOCAL_SNAPSHOT_MAX_MEMORY_ITEMS:
        raise ValueError('memorial_local_snapshot_target_capacity_exceeded')

    result: dict[str, object] = {
        'schema': _LOCAL_SNAPSHOT_SCHEMA,
        'mode': 'merge',
        'dry_run': bool(dry_run),
        'memorial_slug': slug,
        'principal_id': principal,
        'payload_sha256': payload_sha256,
        'snapshot_file_sha256': file_sha256,
        'authenticated': False,
        'integrity_model': 'sha256_accidental_corruption_only',
        'target_storage_durable': storage_durable,
        'ephemeral_test_override': bool(not storage_durable and allow_ephemeral_test_backend),
        'apply_confirmation_matched': bool(not dry_run),
        'memory_items_in_snapshot': len(list(payload['memory_items'])),
        'memory_items_to_create': len(memory_to_create),
        'raw_mail_in_snapshot': len(list(payload['raw_mail'])),
        'raw_mail_to_write': len(raw_to_write),
        'memory_items_created': 0,
        'raw_mail_written': 0,
        'canonical_publication_state_restored': False,
        'hub_identity_restored': False,
        'registry_state_restored': False,
    }
    if dry_run:
        return result

    recovery_time = now_utc_iso()
    for item in raw_to_write:
        raw_bytes = base64.b64decode(item['raw_base64'], validate=True)
        _archive_raw_message(
            slug=slug,
            message_key=item['message_key'],
            raw_bytes=raw_bytes,
        )
        result['raw_mail_written'] = int(result['raw_mail_written']) + 1

    for item in memory_to_create:
        record = dict(item['record'])
        provenance = dict(record['provenance_json'])
        provenance['local_recovery_receipt'] = {
            'schema': _LOCAL_SNAPSHOT_RECOVERY_SCHEMA,
            'payload_sha256': payload_sha256,
            'item_content_sha256': str(item['content_sha256']),
            'reviewer': recovery_actor,
            'authenticated': False,
            'integrity_model': 'sha256_accidental_corruption_only',
            'canonical_publication_state_restored': False,
            'recovered_at': recovery_time,
            'target_storage_durable': storage_durable,
            'active_verification_scope': 'ea_local_recovery_only_noncanonical',
            'untrusted_snapshot_metadata': {
                'reviewer': str(record['reviewer']),
                'last_verified_at': record['last_verified_at'],
            },
        }
        memory_runtime.create_memory_item(
            principal_id=principal,
            category=str(record['category']),
            summary=str(record['summary']),
            fact_json=dict(record['fact_json']),
            provenance_json=provenance,
            confidence=float(record['confidence']),
            sensitivity='private',
            sharing_policy='private',
            reviewer=recovery_actor,
            last_verified_at=recovery_time,
        )
        result['memory_items_created'] = int(result['memory_items_created']) + 1

    message_keys = list(dict(payload['mail_manifest'])['message_keys'])
    if message_keys:
        with _MAIL_MANIFEST_LOCK:
            current_manifest = _load_manifest(slug, legacy_principal_id=principal)
            processed_by_principal = dict(current_manifest.get('processed_by_principal') or {})
            existing_keys = {
                str(item).strip()
                for item in list(processed_by_principal.get(principal) or [])
                if str(item).strip()
            }
            processed_by_principal[principal] = sorted(existing_keys | set(message_keys))
            current_manifest['schema'] = _MAIL_MANIFEST_SCHEMA
            current_manifest['processed_by_principal'] = {
                key: sorted({str(item) for item in value if str(item).strip()})
                for key, value in sorted(processed_by_principal.items())
                if key and isinstance(value, list)
            }
            current_manifest['processed_keys'] = sorted(
                {
                    item
                    for values in current_manifest['processed_by_principal'].values()
                    for item in values
                }
            )
            _save_manifest(slug, current_manifest)
    return result


def restore_memorial_local_snapshot(
    *,
    memory_runtime: MemoryRuntimeService,
    principal_id: str,
    memorial_slug: str,
    snapshot_path: str,
    dry_run: bool = True,
    confirmed_payload_sha256: str = '',
    recovery_reviewer: str = 'memorial-local-recovery',
    allow_ephemeral_test_backend: bool = False,
) -> dict[str, object]:
    """Plan or merge one contained EA-local snapshot under an interprocess lock."""

    slug, _principal = _require_local_snapshot_scope(
        memorial_slug=memorial_slug,
        principal_id=principal_id,
    )
    with _memorial_storage_lock(slug):
        _ensure_archive_root(slug, 'snapshots')
        return _restore_memorial_local_snapshot_locked(
            memory_runtime=memory_runtime,
            principal_id=principal_id,
            memorial_slug=memorial_slug,
            snapshot_path=snapshot_path,
            dry_run=dry_run,
            confirmed_payload_sha256=confirmed_payload_sha256,
            recovery_reviewer=recovery_reviewer,
            allow_ephemeral_test_backend=allow_ephemeral_test_backend,
        )
