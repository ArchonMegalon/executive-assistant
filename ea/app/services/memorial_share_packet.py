from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import urllib.parse
from pathlib import PurePosixPath
from typing import Iterable, Sequence


SCHEMA_VERSION = "ea.memorial.share_packet.v1"
SHARE_DISCLOSURE = (
    "Unsent draft - review before sharing. It contains only approved public memorial material; "
    "recipients may reshare its links."
)
CORRECTION_DISCLOSURE = "Corrections or removal requests can be made through the public memorial page and are reviewed by its curators."
SUPPORTED_CHANNELS = ("whatsapp", "telegram")
_ROUTE_SEGMENT_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}")
_ASSET_SEGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}")
_AUDIO_EXTENSIONS = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav", ".webm"}


class MemorialSharePacketError(ValueError):
    """A safe, stable error that never includes source content or URLs."""

    def __init__(self, code: str) -> None:
        self.code = (
            str(code or "memorial_share_packet_invalid").strip()
            or "memorial_share_packet_invalid"
        )
        super().__init__(self.code)


def _safe_text(value: object, *, maximum: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:maximum].strip()


def _safe_route_segment(value: object, *, error: str) -> str:
    normalized = _safe_text(value, maximum=80).lower()
    if not normalized or _ROUTE_SEGMENT_RE.fullmatch(normalized) is None:
        raise MemorialSharePacketError(error)
    return normalized


def normalize_public_origin(value: object) -> str:
    raw = _safe_text(value, maximum=2048)
    if not raw:
        raise MemorialSharePacketError("public_origin_required")
    try:
        parsed = urllib.parse.urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise MemorialSharePacketError("public_origin_invalid") from exc
    hostname = str(parsed.hostname or "").strip().lower().rstrip(".")
    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or bool(parsed.query)
        or bool(parsed.fragment)
    ):
        raise MemorialSharePacketError("public_origin_invalid")
    if (
        hostname == "localhost"
        or hostname.endswith(".localhost")
        or "." not in hostname
    ):
        raise MemorialSharePacketError("public_origin_not_public")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            hostname = hostname.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise MemorialSharePacketError("public_origin_invalid") from exc
    else:
        if not address.is_global:
            raise MemorialSharePacketError("public_origin_not_public")
        hostname = (
            f"[{address.compressed}]" if address.version == 6 else address.compressed
        )
    return f"https://{hostname}{f':{port}' if port is not None else ''}"


def _internal_route(value: object, *, public_origin: str, expected_prefix: str) -> str:
    raw = _safe_text(value, maximum=2048)
    if not raw:
        raise MemorialSharePacketError("share_route_missing")
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError as exc:
        raise MemorialSharePacketError("share_route_invalid") from exc
    if parsed.query or parsed.fragment:
        raise MemorialSharePacketError("share_route_invalid")
    if parsed.scheme or parsed.netloc:
        try:
            candidate_origin = normalize_public_origin(
                urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
            )
        except MemorialSharePacketError as exc:
            raise MemorialSharePacketError("share_route_not_internal") from exc
        if candidate_origin != public_origin:
            raise MemorialSharePacketError("share_route_not_internal")
    path = parsed.path
    decoded_path = urllib.parse.unquote(path)
    if (
        not path.startswith("/")
        or not path.startswith(expected_prefix)
        or "\\" in path
        or "%" in path
        or "//" in path
        or any(segment in {"", ".", ".."} for segment in decoded_path.split("/")[1:])
    ):
        raise MemorialSharePacketError("share_route_invalid")
    return f"{public_origin}{path}"


def _explicitly_public(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    visibility = _safe_text(item.get("visibility"), maximum=40).lower()
    if visibility:
        return visibility == "public" and item.get("public") is not False
    return item.get("public") is True


def _approved(item: dict[str, object]) -> bool:
    status = _safe_text(item.get("review_status"), maximum=40).lower()
    return item.get("approved") is True or status in {"approved", "published"}


def _safe_audio_relpath(value: object) -> str:
    raw = _safe_text(value, maximum=512)
    if not raw or "\\" in raw or "%" in raw or "?" in raw or "#" in raw:
        raise MemorialSharePacketError("share_audio_route_invalid")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise MemorialSharePacketError("share_audio_route_invalid")
    if any(_ASSET_SEGMENT_RE.fullmatch(part) is None for part in path.parts):
        raise MemorialSharePacketError("share_audio_route_invalid")
    if path.suffix.lower() not in _AUDIO_EXTENSIONS:
        raise MemorialSharePacketError("share_audio_type_invalid")
    return path.as_posix()


def _selection(values: Iterable[object] | None, *, maximum: int) -> set[str]:
    selected = {
        normalized
        for value in list(values or [])[:maximum]
        if (normalized := _safe_text(value, maximum=512))
    }
    return selected


def _public_archive_assets(
    *,
    slug: str,
    public_origin: str,
    registry: dict[str, object],
    selected_ids: set[str],
) -> list[dict[str, str]]:
    assets: list[dict[str, str]] = []
    eligible_ids: set[str] = set()
    for raw_item in list(registry.get("fliplink_publications") or [])[:48]:
        if not isinstance(raw_item, dict):
            continue
        audience = _safe_text(raw_item.get("audience"), maximum=40).lower()
        status = _safe_text(raw_item.get("review_status"), maximum=40).lower()
        publication_id = _safe_text(raw_item.get("id"), maximum=160)
        if (
            audience != "public"
            or status not in {"approved", "published"}
            or not publication_id
        ):
            continue
        eligible_ids.add(publication_id)
        if selected_ids and publication_id not in selected_ids:
            continue
        title = _safe_text(raw_item.get("title"), maximum=220)
        if not title:
            continue
        route_prefix = f"/memorials/{slug}/archive/"
        url = _internal_route(
            raw_item.get("url"),
            public_origin=public_origin,
            expected_prefix=route_prefix,
        )
        publication_slug = urllib.parse.urlsplit(url).path.removeprefix(route_prefix)
        if (
            not publication_slug
            or "/" in publication_slug
            or _ROUTE_SEGMENT_RE.fullmatch(publication_slug) is None
        ):
            raise MemorialSharePacketError("share_archive_route_invalid")
        assets.append(
            {
                "kind": "archive_document",
                "id": publication_id,
                "title": title,
                "url": url,
            }
        )
    if selected_ids - eligible_ids:
        raise MemorialSharePacketError("share_archive_selection_not_public")
    deduped = {item["url"]: item for item in assets}
    return sorted(deduped.values(), key=lambda item: (item["id"], item["url"]))[:12]


def _public_audio_assets(
    *,
    slug: str,
    public_origin: str,
    memorial: dict[str, object],
    selected_relpaths: set[str],
) -> list[dict[str, str]]:
    assets: list[dict[str, str]] = []
    eligible_relpaths: set[str] = set()
    for raw_item in list(memorial.get("audio_clips") or [])[:32]:
        if (
            not isinstance(raw_item, dict)
            or not _explicitly_public(raw_item)
            or not _approved(raw_item)
        ):
            continue
        relpath = _safe_audio_relpath(raw_item.get("asset_relpath"))
        eligible_relpaths.add(relpath)
        if selected_relpaths and relpath not in selected_relpaths:
            continue
        title = _safe_text(raw_item.get("title") or raw_item.get("label"), maximum=220)
        if not title:
            continue
        route = f"/memorials/files/{slug}/{relpath}"
        url = _internal_route(
            route,
            public_origin=public_origin,
            expected_prefix=f"/memorials/files/{slug}/",
        )
        assets.append({"kind": "audio", "id": relpath, "title": title, "url": url})
    if selected_relpaths - eligible_relpaths:
        raise MemorialSharePacketError("share_audio_selection_not_public")
    deduped = {item["url"]: item for item in assets}
    return sorted(deduped.values(), key=lambda item: (item["id"], item["url"]))[:8]


def _normalized_channels(channels: Sequence[object] | None) -> tuple[str, ...]:
    requested = {
        _safe_text(channel, maximum=40).lower()
        for channel in (channels if channels is not None else SUPPORTED_CHANNELS)
    }
    if not requested:
        raise MemorialSharePacketError("share_channel_required")
    unsupported = requested - set(SUPPORTED_CHANNELS)
    if unsupported:
        raise MemorialSharePacketError("share_channel_unsupported")
    return tuple(channel for channel in SUPPORTED_CHANNELS if channel in requested)


def _message_text(
    *,
    title: str,
    person_name: str,
    memorial_url: str,
    assets: Sequence[dict[str, str]],
) -> str:
    lines = [title]
    if person_name and person_name.lower() not in title.lower():
        lines.append(person_name)
    lines.extend((memorial_url, ""))
    if assets:
        lines.append("Approved public additions:")
        lines.extend(f"- {item['title']}: {item['url']}" for item in assets)
        lines.append("")
    lines.extend((SHARE_DISCLOSURE, CORRECTION_DISCLOSURE))
    return "\n".join(lines)


def _stable_id(prefix: str, payload: object) -> str:
    serialized = json.dumps(
        payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )
    return f"{prefix}_{hashlib.sha256(serialized.encode('utf-8')).hexdigest()[:24]}"


def build_memorial_share_packet(
    *,
    slug: str,
    public_origin: str,
    memorial: dict[str, object],
    archive_registry: dict[str, object] | None = None,
    channels: Sequence[object] | None = None,
    include_archive: bool = False,
    include_audio: bool = False,
    archive_ids: Iterable[object] | None = None,
    audio_relpaths: Iterable[object] | None = None,
) -> dict[str, object]:
    safe_slug = _safe_route_segment(slug, error="memorial_slug_invalid")
    origin = normalize_public_origin(public_origin)
    normalized_channels = _normalized_channels(channels)
    selected_archive_ids = _selection(archive_ids, maximum=24)
    selected_audio_relpaths = _selection(audio_relpaths, maximum=16)
    archive_requested = bool(include_archive or selected_archive_ids)
    audio_requested = bool(include_audio or selected_audio_relpaths)

    assets: list[dict[str, str]] = []
    if archive_requested:
        assets.extend(
            _public_archive_assets(
                slug=safe_slug,
                public_origin=origin,
                registry=archive_registry if isinstance(archive_registry, dict) else {},
                selected_ids=selected_archive_ids,
            )
        )
    if audio_requested:
        assets.extend(
            _public_audio_assets(
                slug=safe_slug,
                public_origin=origin,
                memorial=memorial if isinstance(memorial, dict) else {},
                selected_relpaths=selected_audio_relpaths,
            )
        )
    assets = sorted(assets, key=lambda item: (item["kind"], item["id"], item["url"]))

    person_name = _safe_text(memorial.get("person_name"), maximum=180)
    title = _safe_text(memorial.get("title"), maximum=220) or (
        f"In memory of {person_name}" if person_name else "Public memorial"
    )
    memorial_url = f"{origin}/memorials/{safe_slug}"
    packet_core = {
        "schema_version": SCHEMA_VERSION,
        "slug": safe_slug,
        "public_origin": origin,
        "title": title,
        "person_name": person_name,
        "memorial_url": memorial_url,
        "assets": assets,
        "channels": list(normalized_channels),
        "share_disclosure": SHARE_DISCLOSURE,
        "correction_disclosure": CORRECTION_DISCLOSURE,
    }
    packet_id = _stable_id("share", packet_core)
    text = _message_text(
        title=title,
        person_name=person_name,
        memorial_url=memorial_url,
        assets=assets,
    )
    links = [memorial_url, *[item["url"] for item in assets]]
    drafts: list[dict[str, object]] = []
    for channel in normalized_channels:
        payload: dict[str, object] = {"text": text, "links": links}
        if channel == "whatsapp":
            payload["link_preview_allowed"] = True
        else:
            payload["web_page_preview_disabled"] = False
            payload["text_format"] = "plain"
        receipt_core = {"packet_id": packet_id, "channel": channel, "state": "unsent"}
        drafts.append(
            {
                "draft_id": _stable_id("draft", receipt_core),
                "channel": channel,
                "payload": payload,
                "receipt": {
                    "receipt_id": _stable_id("receipt", receipt_core),
                    **receipt_core,
                    "sent": False,
                    "attempted": False,
                    "reason": "operator_review_required",
                },
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "packet_id": packet_id,
        "state": "unsent",
        "sent": False,
        "attempted": False,
        "memorial": {
            "slug": safe_slug,
            "title": title,
            **({"person_name": person_name} if person_name else {}),
            "url": memorial_url,
        },
        "assets": assets,
        "disclosures": {
            "share": SHARE_DISCLOSURE,
            "correction": CORRECTION_DISCLOSURE,
        },
        "governance": {
            "operator_review_required": True,
            "delivery_permitted": False,
            "send_requested": False,
        },
        "drafts": drafts,
    }
