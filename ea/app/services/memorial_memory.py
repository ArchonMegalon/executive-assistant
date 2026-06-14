from __future__ import annotations

import email
import hashlib
import json
import mailbox
import re
from collections.abc import Iterable
from email.message import Message
from email.policy import default as default_email_policy
from pathlib import Path
from typing import Any

from app.domain.models import MemoryItem
from app.services.memory_runtime import MemoryRuntimeService

_ARCHIVE_ROOT = Path('/data/artifacts/memorial_mail_archive')
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


def _manifest_path(slug: str) -> Path:
    return _archive_root_for(slug) / 'ingest_manifest.json'


def _load_manifest(slug: str) -> dict[str, Any]:
    path = _manifest_path(slug)
    if not path.is_file():
        return {'processed_keys': []}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if not isinstance(payload.get('processed_keys'), list):
        payload['processed_keys'] = []
    return payload


def _save_manifest(slug: str, payload: dict[str, Any]) -> None:
    root = _archive_root_for(slug)
    root.mkdir(parents=True, exist_ok=True)
    _manifest_path(slug).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _archive_raw_message(*, slug: str, message_key: str, raw_bytes: bytes) -> str:
    archive_dir = _archive_root_for(slug) / 'raw'
    archive_dir.mkdir(parents=True, exist_ok=True)
    filename = f'{message_key}.eml'
    path = archive_dir / filename
    if not path.exists():
        path.write_bytes(raw_bytes)
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
    manifest = _load_manifest(slug)
    processed_keys = {str(item) for item in (manifest.get('processed_keys') or []) if str(item).strip()}
    imported = 0
    skipped = 0
    seen_now: list[str] = []
    for index, (message, raw_bytes) in enumerate(_iter_messages(path, mailbox_format), start=1):
        if index > max_messages:
            break
        body_text = _message_body_text(message)
        message_key = _message_key(message, body_text)
        if message_key in processed_keys:
            skipped += 1
            continue
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
        }
        memory_runtime.create_memory_item(
            principal_id=principal_id,
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
        seen_now.append(message_key)
        imported += 1
    manifest['processed_keys'] = sorted(processed_keys)
    manifest['last_source_path'] = str(path)
    manifest['last_mailbox_format'] = mailbox_format
    _save_manifest(slug, manifest)
    return {
        'memorial_slug': slug,
        'principal_id': principal_id,
        'source_path': str(path),
        'mailbox_format': mailbox_format,
        'imported': imported,
        'skipped': skipped,
        'processed_total': len(processed_keys),
        'new_message_keys': seen_now[:50],
    }


def _seed_manifest_path(slug: str) -> Path:
    return _archive_root_for(slug) / 'seed_manifest.json'


def _load_seed_manifest(slug: str) -> dict[str, Any]:
    path = _seed_manifest_path(slug)
    if not path.is_file():
        return {'processed_keys': []}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if not isinstance(payload.get('processed_keys'), list):
        payload['processed_keys'] = []
    return payload


def memorial_seed_manifest_processed_total(slug: str) -> int:
    payload = _load_seed_manifest(slug)
    return len([str(item) for item in (payload.get('processed_keys') or []) if str(item).strip()])


def _save_seed_manifest(slug: str, payload: dict[str, Any]) -> None:
    root = _archive_root_for(slug)
    root.mkdir(parents=True, exist_ok=True)
    _seed_manifest_path(slug).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def seed_memorial_source_memories(
    *,
    memory_runtime: MemoryRuntimeService,
    principal_id: str,
    memorial_slug: str,
    memorial_payload: dict[str, object],
    private_profile: dict[str, object] | None = None,
    reviewer: str = 'memorial-source-seed',
) -> dict[str, object]:
    slug = _safe_slug(memorial_slug)
    processed = {str(item) for item in (_load_seed_manifest(slug).get('processed_keys') or []) if str(item).strip()}
    created_keys: list[str] = []
    created_count = 0

    def create_seed_item(*, seed_key: str, category: str, summary: str, fact_json: dict[str, object]) -> None:
        nonlocal created_count
        if seed_key in processed:
            return
        memory_runtime.create_memory_item(
            principal_id=principal_id,
            category=category,
            summary=summary,
            fact_json=fact_json,
            provenance_json={
                'source_type': 'memorial_seed',
                'memorial_slug': slug,
                'seed_key': seed_key,
            },
            confidence=0.82,
            sensitivity='private',
            sharing_policy='private',
            reviewer=reviewer,
        )
        processed.add(seed_key)
        created_keys.append(seed_key)
        created_count += 1

    for index, card in enumerate(memorial_payload.get('memory_cards') or []):
        if not isinstance(card, dict):
            continue
        title = _normalize_text(card.get('title'))
        body = _normalize_text(card.get('body'))
        source_label = _normalize_text(card.get('source_label'))
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
        )

    for index, item in enumerate(memorial_payload.get('source_grounded_profile') or []):
        if not isinstance(item, dict):
            continue
        trait = _normalize_text(item.get('trait'))
        evidence = _normalize_text(item.get('evidence'))
        confidence = _normalize_text(item.get('confidence'))
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
        )

    for index, note in enumerate(memorial_payload.get('character_notes') or []):
        normalized = _normalize_text(note)
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
        )

    conversation_style = memorial_payload.get('conversation_style')
    if isinstance(conversation_style, dict):
        for style_key in ('reasoning_frame', 'conflict_style', 'social_tone'):
            normalized = _normalize_text(conversation_style.get(style_key))
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
            )
        for index, avoid_item in enumerate(conversation_style.get('should_avoid') or []):
            normalized = _normalize_text(avoid_item)
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
            )

    for index, prompt in enumerate(memorial_payload.get('suggested_prompts') or []):
        normalized = _normalize_text(prompt)
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
        )

    for index, source in enumerate(memorial_payload.get('external_sources') or []):
        if not isinstance(source, dict):
            continue
        label = _normalize_text(source.get('label'))
        url = _normalize_text(source.get('url'))
        status = _normalize_text(source.get('status'))
        if not (label or url):
            continue
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
        )

    if isinstance(private_profile, dict):
        for index, note in enumerate(private_profile.get('public_source_notes') or []):
            if not isinstance(note, dict):
                continue
            label = _normalize_text(note.get('label'))
            source_url = _normalize_text(note.get('source_url'))
            note_text = _normalize_text(note.get('note'))
            confidence = _normalize_text(note.get('confidence'))
            if not note_text:
                continue
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
            )
        for index, note in enumerate(private_profile.get('family_context_notes') or []):
            if not isinstance(note, dict):
                continue
            trait = _normalize_text(note.get('trait'))
            evidence = _normalize_text(note.get('evidence'))
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
            )

    _save_seed_manifest(slug, {'processed_keys': sorted(processed)})
    return {
        'memorial_slug': slug,
        'principal_id': principal_id,
        'created': created_count,
        'created_keys': created_keys[:100],
        'processed_total': len(processed),
    }


def retrieve_memorial_memory_items(
    *,
    memory_runtime: MemoryRuntimeService,
    principal_id: str,
    question: str,
    limit: int = 6,
) -> list[MemoryItem]:
    query_tokens = _tokenize(question)
    rows = memory_runtime.list_items(limit=500, principal_id=principal_id)
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
    return [row for _, row in scored[:limit]]


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
    del memory_runtime
    slug = _safe_slug(str(principal_id or '').split(':', 1)[-1])
    manifest = _load_manifest(slug)
    processed = manifest.get('processed_keys') or []
    return any(str(item).strip() for item in processed)
