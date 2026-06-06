from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from textwrap import wrap

from app.services.fliplink.models import FlipLinkFormat, PacketPrivacyMode, PropertyPacketKind
from app.services.fliplink.privacy import REDACTION_POLICY_VERSION, redact_property_packet


PDF_RENDERER_VERSION = "v2_packet_pdf"


def _safe_token(value: object, fallback: str = "packet") -> str:
    raw = str(value or "").strip().lower()
    token = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    return token[:80] or fallback


def _pdf_escape(value: object) -> str:
    return str(value or "").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap_line(value: object, width: int = 92) -> list[str]:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return []
    return wrap(text, width=width, break_long_words=False) or [text]


def _page_chunks(lines: list[str], *, per_page: int = 44) -> list[list[str]]:
    chunks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        current.append(line)
        if len(current) >= per_page:
            chunks.append(current)
            current = []
    if current or not chunks:
        chunks.append(current)
    return chunks


def _minimal_pdf(lines: list[str]) -> bytes:
    pages = _page_chunks(lines)
    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    catalog_id = add(b"<< /Type /Catalog /Pages 2 0 R >>")
    pages_id = add(b"")
    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids: list[int] = []
    for page_lines in pages:
        ops = ["BT", "/F1 11 Tf", "48 786 Td", "14 TL"]
        for line in page_lines:
            ops.append(f"({_pdf_escape(line)}) Tj")
            ops.append("T*")
        ops.append("ET")
        content = "\n".join(ops).encode("latin-1", errors="replace")
        content_id = add(b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream")
        page_id = add(
            (
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 612 842] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
            ).encode("ascii")
        )
        page_ids.append(page_id)
    objects[pages_id - 1] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{page_id} 0 R' for page_id in page_ids)}] /Count {len(page_ids)} >>"
    ).encode("ascii")
    assert catalog_id == 1

    body = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body.extend(f"{index} 0 obj\n".encode("ascii"))
        body.extend(obj)
        body.extend(b"\nendobj\n")
    xref_at = len(body)
    body.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    body.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        body.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    body.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(body)


def _packet_lines(
    *,
    payload: dict[str, object],
    packet_kind: PropertyPacketKind,
    privacy_mode: PacketPrivacyMode,
    fliplink_format: FlipLinkFormat,
    recommended_title: str,
) -> list[str]:
    facts = dict(payload.get("facts") or {}) if isinstance(payload.get("facts"), dict) else {}
    cost_facts = [
        ("Purchase price", facts.get("purchase_price_eur") or facts.get("price_eur") or facts.get("price_display")),
        ("Monthly rent", facts.get("total_rent_eur") or facts.get("rent_eur") or facts.get("rent_display")),
        ("Area", facts.get("area_m2") or facts.get("area_sqm") or facts.get("living_area_m2")),
        ("Rooms", facts.get("rooms") or facts.get("room_count")),
        ("District", facts.get("district") or facts.get("postal_name") or facts.get("city")),
    ]
    evidence_facts = [
        ("Floorplan", facts.get("has_floorplan")),
        ("Lift", facts.get("lift") or facts.get("has_lift")),
        ("Outdoor space", facts.get("balcony") or facts.get("terrace") or facts.get("garden") or facts.get("outdoor_space")),
        ("Heating", facts.get("heating_type")),
        ("Availability", facts.get("availability")),
    ]
    location_facts = [
        ("Supermarket", facts.get("nearest_supermarket_m") or facts.get("nearest_supermarket_name")),
        ("Pharmacy", facts.get("nearest_pharmacy_m") or facts.get("nearest_pharmacy_name")),
        ("Subway", facts.get("nearest_subway_m") or facts.get("nearest_subway_name")),
        ("Playground", facts.get("nearest_playground_m") or facts.get("nearest_playground_name")),
    ]
    lines: list[str] = [
        "PROPERTYQUARRY REVIEW PACKET",
        recommended_title,
        f"Packet kind: {packet_kind.value.replace('_', ' ')}",
        f"Privacy mode: {privacy_mode.value.replace('_', ' ')}",
        f"FlipLink format: {fliplink_format.value.replace('_', ' ')}",
        f"Renderer: {PDF_RENDERER_VERSION}",
        "",
        "1. Decision Snapshot",
    ]
    for line in _wrap_line(payload.get("fit_summary") or payload.get("recommendation") or "Review this property against the current PropertyQuarry brief."):
        lines.append(line)
    lines.extend(["", "2. Core Facts"])
    for label, value in cost_facts:
        if str(value or "").strip():
            lines.append(f"- {label}: {value}")
    lines.extend(["", "3. Evidence Readiness"])
    for label, value in evidence_facts:
        if str(value or "").strip():
            lines.append(f"- {label}: {value}")
    if any(str(value or "").strip() for _, value in location_facts):
        lines.extend(["", "4. Daily-Life Radius"])
        for label, value in location_facts:
            if str(value or "").strip():
                lines.append(f"- {label}: {value}")
    lines.extend(["", "5. Why It Matched"])
    match_reasons = [str(item or "").strip() for item in list(payload.get("match_reasons") or []) if str(item or "").strip()]
    for reason in match_reasons[:8] or ["No explicit match reason was included in the source packet."]:
        lines.extend(_wrap_line(f"- {reason}"))
    lines.extend(["", "6. Risks And Unknowns"])
    mismatch_reasons = [str(item or "").strip() for item in list(payload.get("mismatch_reasons") or []) if str(item or "").strip()]
    unknowns = [str(item or "").strip() for item in list(payload.get("unknowns") or []) if str(item or "").strip()]
    for item in (mismatch_reasons + unknowns)[:10] or ["No explicit risk was included. Ask the agent for source documents and current operating costs."]:
        lines.extend(_wrap_line(f"- {item}"))
    lines.extend(["", "7. Viewing Checklist"])
    for item in list(payload.get("viewing_questions") or [])[:10] or [
        "Confirm usable floorplan and room dimensions.",
        "Ask for operating cost history and renovation notes.",
        "Check noise, light, storage, and daily route fit.",
    ]:
        lines.extend(_wrap_line(f"- {item}"))
    if packet_kind == PropertyPacketKind.PAID_MARKET_REPORT:
        lines.extend(
            [
                "",
                "8. Methodology And Freshness",
                "- This report is generated from redacted PropertyQuarry research and market-level evidence only.",
                f"- Freshness date: {facts.get('freshness_date') or 'generated packet timestamp'}",
                f"- Methodology: {facts.get('methodology') or 'provider scan, ranking assessment, and owner-safe redaction'}",
            ]
        )
    lines.extend(["", "Source And Provenance", f"Source: {payload.get('property_url') or 'internal PropertyQuarry packet'}"])
    return lines


def render_property_packet_pdf(
    *,
    artifact_root: Path,
    publication_id: str,
    principal_id: str,
    source: dict[str, object],
    packet_kind: PropertyPacketKind,
    privacy_mode: PacketPrivacyMode,
    fliplink_format: FlipLinkFormat,
    include_exact_address: bool = False,
) -> dict[str, object]:
    redaction = redact_property_packet(
        source=source,
        privacy_mode=privacy_mode,
        include_exact_address=include_exact_address,
    )
    title = str(redaction.payload.get("title") or source.get("title") or "PropertyQuarry packet").strip() or "PropertyQuarry packet"
    recommended_title = f"{title} - {packet_kind.value.replace('_', ' ').title()}"
    lines = _packet_lines(
        payload=redaction.payload,
        packet_kind=packet_kind,
        privacy_mode=privacy_mode,
        fliplink_format=fliplink_format,
        recommended_title=recommended_title,
    )
    pdf_bytes = _minimal_pdf(lines)
    pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    principal_token = _safe_token(principal_id, "principal")
    target_dir = artifact_root / "property_packets" / principal_token
    target_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = target_dir / f"{_safe_token(publication_id)}.pdf"
    receipt_path = target_dir / f"{_safe_token(publication_id)}.receipt.json"
    pdf_path.write_bytes(pdf_bytes)
    receipt = {
        **redaction.receipt,
        "renderer_version": PDF_RENDERER_VERSION,
        "pdf_sha256": pdf_sha256,
        "source_pdf_size_bytes": len(pdf_bytes),
        "source_pdf_artifact_ref": str(pdf_path),
        "redaction_policy_version": REDACTION_POLICY_VERSION,
    }
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "pdf_path": str(pdf_path),
        "receipt_path": str(receipt_path),
        "pdf_sha256": pdf_sha256,
        "pdf_size_bytes": len(pdf_bytes),
        "receipt": receipt,
        "redacted_payload": redaction.payload,
        "recommended_title": recommended_title,
    }
