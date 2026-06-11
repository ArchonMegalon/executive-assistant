from __future__ import annotations

from pathlib import Path
from typing import Callable

from app.services.fliplink.models import FlipLinkFormat, PacketPrivacyMode, PropertyPacketKind


def render_property_packet_pdf_via_premium_pipeline(
    *,
    artifact_root: Path,
    publication_id: str,
    principal_id: str,
    source: dict[str, object],
    packet_kind: PropertyPacketKind,
    privacy_mode: PacketPrivacyMode,
    fliplink_format: FlipLinkFormat,
    include_exact_address: bool = False,
    include_floorplan: bool = True,
    include_photos: bool = True,
    legacy_renderer: Callable[..., dict[str, object]],
) -> dict[str, object]:
    """Compatibility seam for the premium packet renderer.

    The premium pipeline entry point is intentionally thin until the paid
    dossier lane owns a separate implementation; FlipLink still gets the
    governed legacy renderer and its privacy receipt.
    """

    return legacy_renderer(
        artifact_root=artifact_root,
        publication_id=publication_id,
        principal_id=principal_id,
        source=source,
        packet_kind=packet_kind,
        privacy_mode=privacy_mode,
        fliplink_format=fliplink_format,
        include_exact_address=include_exact_address,
        include_floorplan=include_floorplan,
        include_photos=include_photos,
    )
