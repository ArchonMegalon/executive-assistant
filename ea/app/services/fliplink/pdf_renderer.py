from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from textwrap import wrap

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional image appendix support
    Image = None

from app.services.fliplink.models import FlipLinkFormat, PacketPrivacyMode, PropertyPacketKind
from app.services.fliplink.privacy import REDACTION_POLICY_VERSION, redact_property_packet


PDF_RENDERER_VERSION = "v3_visual_packet_pdf"
PDF_RENDERER_FALLBACK_VERSION = "v4_visual_packet_pdf"
PAGE_WIDTH = 612
PAGE_HEIGHT = 842
MARGIN_X = 44
CARD_WIDTH = PAGE_WIDTH - (MARGIN_X * 2)
MAX_MEDIA_REF_CHARS = 180
Color = tuple[float, float, float]


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


def _text_items(value: object, *, limit: int = 10) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item or "").strip() for item in value[:limit] if str(item or "").strip()]


def _joined(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item or "").strip() for item in value if str(item or "").strip())
    return str(value or "").strip()


def _fact_value(facts: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = facts.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _clean_sentence(value: object) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    if text[-1] not in ".!?":
        text = f"{text}."
    return text


def _localize_compare_reason(value: object) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    replacements = {
        "Chosen ahead of the next option because": "Vor der nächstbesten Alternative liegt dieses Objekt, weil",
        "it scored": "es",
        "points higher on the current brief": "Punkte höher auf das aktuelle Suchprofil scored",
        "it includes a floorplan while the next option does not": "ein Grundriss vorliegt, während der nächsten Alternative dieser fehlt",
        "it offers more usable room count": "die Zimmerstruktur besser nutzbar wirkt",
        "next option": "nächstbesten Alternative",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = text.replace(" scored", " bewertet wurde")
    text = text.replace("Punkte höher auf das aktuelle Suchprofil scored", "Punkte höher auf das aktuelle Suchprofil bewertet wurde")
    return _clean_sentence(text)


def _localize_fit_summary(value: object) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    replacements = {
        "Personal fit": "Persönliche Passung",
        "ask for clarification": "mit Klärungsbedarf",
        "high fit": "starke Passung",
        "good fit": "gute Passung",
        "weak fit": "schwache Passung",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return _clean_sentence(text)


def _comparison_rows(value: object, *, limit: int = 6) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, str]] = []
    for row in value[:limit]:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or row.get("property_title") or "").strip()
        if not title:
            continue
        rows.append(
            {
                "title": title,
                "price": _money_phrase(row.get("price") or row.get("rent")),
                "rooms": str(row.get("rooms") or "").strip(),
                "area": str(row.get("area_sqm") or row.get("area") or "").strip(),
                "recommendation": str(row.get("recommendation") or "").strip(),
                "compare_reason": str(row.get("compare_reason") or "").strip(),
            }
        )
    return rows


def _money_phrase(value: object) -> str:
    if isinstance(value, (int, float)):
        try:
            amount = f"{float(value):,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
            return f"EUR {amount}"
        except Exception:
            return str(value)
    return str(value or "").strip()


def _display_price(value: object) -> str:
    phrase = _money_phrase(value)
    return phrase or "On request"


def _display_number(value: object, *, suffix: str = "", decimals: int = 0) -> str:
    if isinstance(value, (int, float)):
        rendered = f"{float(value):.{decimals}f}"
        if decimals > 0:
            rendered = rendered.rstrip("0").rstrip(".")
        return f"{rendered}{suffix}"
    text = str(value or "").strip()
    return f"{text}{suffix}" if text and suffix and not text.endswith(suffix.strip()) else text


def _bool_label(value: object, *, yes: str = "Confirmed", no: str = "No", unknown: str = "Unclear") -> str:
    if isinstance(value, bool):
        return yes if value else no
    text = str(value or "").strip()
    if not text:
        return unknown
    lowered = text.lower()
    if lowered in {"true", "yes", "ja", "1"}:
        return yes
    if lowered in {"false", "no", "nein", "0"}:
        return no
    return text


def _fallback_match_reasons(facts: dict[str, object]) -> list[str]:
    rows: list[str] = []
    if facts.get("floorplan_count") or facts.get("has_floorplan"):
        rows.append("Ein brauchbarer Grundriss liegt bereits vor und macht die Vorprüfung deutlich belastbarer.")
    if facts.get("balcony") or facts.get("terrace") or facts.get("garden") or "loggia" in str(facts.get("title") or "").lower():
        rows.append("Die angebotene Außenfläche verbessert die alltägliche Nutzbarkeit über die reine Innenfläche hinaus.")
    tram_bus = _walk_minutes_phrase(facts.get("nearest_tram_bus_m"))
    if tram_bus:
        rows.append(f"Die öffentliche Anbindung beginnt bereits vor der U-Bahn, da die nächste Straßenbahn- oder Busanbindung {tram_bus} liegt.")
    supermarket = _walk_minutes_phrase(facts.get("nearest_supermarket_m"))
    if supermarket:
        rows.append(f"Die Nahversorgung wirkt alltagstauglich, weil der nächste Supermarkt {supermarket} liegt.")
    return rows


def _fallback_risks(facts: dict[str, object]) -> list[str]:
    rows: list[str] = []
    if not (facts.get("heating_type") or "").strip():
        rows.append("Das Heizsystem ist in den vorliegenden Unterlagen noch nicht ausdrücklich bestätigt.")
    if not facts.get("operating_cost_history_available"):
        rows.append("Eine belastbare Betriebskostenhistorie fehlt noch, daher bleibt die monatliche Belastung offen.")
    if not facts.get("lift") and not facts.get("has_lift"):
        rows.append("Die Liftfrage ist noch nicht so geklärt, dass man sich ohne Besichtigung oder Maklerantwort darauf verlassen sollte.")
    if not facts.get("epc") and not facts.get("energy_certificate"):
        rows.append("Ein aktueller Energieausweis fehlt im bisherigen Dossier noch.")
    return rows


def _fallback_questions(facts: dict[str, object]) -> list[str]:
    rows = [
        "Können Sie den Grundriss mit Raummaßen sowie Balkon- oder Loggia-Tiefe übermitteln?",
        "Können Sie Heizungsart und den aktuellsten verfügbaren Energieausweis bestätigen?",
        "Können Sie die letzte Betriebskostenabrechnung samt allfälligen wiederkehrenden Zusatzkosten senden?",
    ]
    if facts.get("nearest_school_m") or facts.get("school_atlas_selected_school"):
        rows.append("Ist der Weg zur nächsten Volksschule und zu den relevanten Öffis realistisch kindersicher, ohne kritische Straßenquerung?")
    return rows


def _recommendation_label(value: object) -> str:
    normalized = str(value or "").strip().lower().replace("_", " ")
    mapping = {
        "shortlist": "Engere Auswahl",
        "investigate further": "Vertieft prüfen",
        "investigate": "Vertieft prüfen",
        "maybe": "Mit Vorbehalt",
        "pass": "Eher absagen",
        "reject": "Absagen",
        "offer candidate": "Angebotskandidat",
        "offer": "Angebotskandidat",
        "interested": "Interessant",
    }
    return mapping.get(normalized, "Vertieft prüfen")


def _confidence_label(*, risk_lines: list[str], match_reasons: list[str], mismatch_reasons: list[str]) -> str:
    if not risk_lines and match_reasons:
        return "Hoch"
    if len(risk_lines) >= 3 or len(mismatch_reasons) >= 3:
        return "Zurückhaltend"
    return "Mittel"


def _office_packet_label(packet_kind: PropertyPacketKind) -> str:
    labels = {
        PropertyPacketKind.FAMILY_REVIEW: "Family dossier",
        PropertyPacketKind.OWNER_REVIEW: "Owner review dossier",
        PropertyPacketKind.AGENT_BRIEF: "Agent-ready dossier",
        PropertyPacketKind.SHORTLIST_BROCHURE: "Shortlist brochure",
        PropertyPacketKind.PAID_MARKET_REPORT: "Market report dossier",
        PropertyPacketKind.OPEN_HOUSE_QR: "Open house dossier",
    }
    return labels.get(packet_kind, "Property dossier")


def _privacy_label(privacy_mode: PacketPrivacyMode) -> str:
    labels = {
        PacketPrivacyMode.ANONYMOUS_PUBLIC: "Public summary",
        PacketPrivacyMode.PAID_CUSTOMER: "Client copy",
        PacketPrivacyMode.AGENT_SHARE: "Shareable review",
        PacketPrivacyMode.FAMILY_REVIEW: "Private family review",
        PacketPrivacyMode.OWNER_PRIVATE: "Private working copy",
    }
    return labels.get(privacy_mode, "Private review")


def _walk_minutes_phrase(value: object) -> str:
    if not isinstance(value, (int, float)):
        return ""
    meters = float(value)
    if meters <= 0:
        return ""
    minutes = max(1, round(meters / 80.0))
    return f"about {int(meters)} m away, roughly {minutes} minutes on foot"


def _distance_label(value: object, *, name: object = "") -> str:
    phrase = _walk_minutes_phrase(value)
    title = str(name or "").strip()
    if phrase and title:
        return f"{title}, {phrase}"
    return phrase or title


def _future_change_lines(facts: dict[str, object]) -> list[str]:
    future = dict(facts.get("future_change_research") or {}) if isinstance(facts.get("future_change_research"), dict) else {}
    rows: list[str] = []
    projects = _text_items(future.get("planned_infrastructure_projects"), limit=3)
    drivers = _text_items(future.get("future_value_drivers"), limit=3)
    risks = _text_items(future.get("future_value_risks"), limit=3)
    confidence = str(future.get("planning_confidence") or "").strip()
    if projects:
        rows.append("Planned infrastructure nearby: " + "; ".join(projects))
    if drivers:
        rows.append("Potential long-term support factors: " + "; ".join(drivers))
    if risks:
        rows.append("Potential long-term pressure points: " + "; ".join(risks))
    if confidence:
        rows.append("Planning confidence: " + confidence)
    return [_clean_sentence(row) for row in rows if row]


def _official_risk_lines(facts: dict[str, object]) -> list[str]:
    evidence = dict(facts.get("official_risk_evidence") or {}) if isinstance(facts.get("official_risk_evidence"), dict) else {}
    rows = evidence.get("sources")
    if not isinstance(rows, list):
        rows = []
    items: list[str] = []
    for row in rows[:4]:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or row.get("risk_key") or "Risk").strip()
        summary = str(row.get("summary") or row.get("required_next_step") or "").strip()
        verification = str(row.get("verification_state") or "").strip().replace("_", " ")
        parts = [label]
        if verification:
            parts.append(verification)
        if summary:
            parts.append(summary)
        text = ": ".join([parts[0], " · ".join(parts[1:])]) if len(parts) > 1 else parts[0]
        if text:
            items.append(_clean_sentence(text))
    return items


def _school_route_line(facts: dict[str, object]) -> str:
    selected_school = dict(facts.get("school_atlas_selected_school") or {}) if isinstance(facts.get("school_atlas_selected_school"), dict) else {}
    school_name = str(selected_school.get("name") or facts.get("nearest_school_name") or "").strip()
    school_type = str(selected_school.get("type") or "").strip()
    school_distance = _distance_label(selected_school.get("distance_m") or facts.get("nearest_school_m"), name=school_name)
    tram_bus = _distance_label(facts.get("nearest_tram_bus_m"), name=facts.get("nearest_tram_bus_name"))
    subway = _distance_label(facts.get("nearest_subway_m"), name=facts.get("nearest_subway_name"))
    cycleway = _distance_label(facts.get("nearest_cycleway_m"), name=facts.get("nearest_cycleway_name"))
    route_posture = []
    if cycleway:
        route_posture.append(f"eine geschützte oder klar erkennbare Radanbindung liegt {cycleway}")
    else:
        route_posture.append("eine eigenständige und sichere Radroute für ein Kind muss vor Ort noch ausdrücklich geprüft werden")
    if tram_bus:
        route_posture.append(f"die nächste Straßenbahn- oder Busanbindung liegt {tram_bus}")
    if subway:
        route_posture.append(f"die nächste U-Bahn-Anbindung liegt {subway}")
    school_bits = []
    if school_type:
        school_bits.append(school_type)
    if school_distance:
        school_bits.append(school_distance)
    school_prefix = f"Die maßgebliche Schulroute führt in Richtung {school_name}" if school_name else "Die Schulroute"
    if school_bits:
        school_prefix += f" ({', '.join(school_bits)})"
    school_prefix += "; daran lässt sich ablesen, ob ein siebenjähriges Kind den Weg realistisch allein per Rad oder Öffis bewältigen könnte"
    return _clean_sentence(school_prefix + "; " + "; ".join(route_posture))


def _num(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _rgb(color: Color) -> str:
    return " ".join(_num(max(0.0, min(1.0, value))) for value in color)


def _draw_rect(ops: list[str], x: float, y: float, width: float, height: float, *, fill: Color) -> None:
    ops.append(f"{_rgb(fill)} rg")
    ops.append(f"{_num(x)} {_num(y)} {_num(width)} {_num(height)} re f")


def _draw_text(
    ops: list[str],
    text: object,
    *,
    x: float,
    y: float,
    size: float = 10,
    font: str = "F1",
    fill: Color = (0.12, 0.13, 0.13),
) -> None:
    value = str(text or "").strip()
    if not value:
        return
    ops.append(
        "BT "
        f"/{font} {_num(size)} Tf "
        f"{_rgb(fill)} rg "
        f"1 0 0 1 {_num(x)} {_num(y)} Tm "
        f"({_pdf_escape(value)}) Tj "
        "ET"
    )


def _draw_image(
    ops: list[str],
    *,
    name: str,
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    ops.append(
        "q "
        f"{_num(width)} 0 0 {_num(height)} {_num(x)} {_num(y)} cm "
        f"/{name} Do "
        "Q"
    )


def _safe_pdf_href(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return raw[:1800]


def _append_query_param(url: str, **params: str) -> str:
    href = _safe_pdf_href(url)
    if not href:
        return ""
    parsed = urllib.parse.urlparse(href)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    current = [(key, value) for key, value in query if key not in params]
    for key, value in params.items():
        if str(value or "").strip():
            current.append((key, str(value)))
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(current)))


def _resolve_pdf_primary_tour_url(*, source: dict[str, object], payload: dict[str, object]) -> str:
    facts = dict(payload.get("facts") or {}) if isinstance(payload.get("facts"), dict) else {}
    for value in (
        payload.get("tour_url"),
        source.get("tour_url"),
        source.get("hosted_url"),
        source.get("public_url"),
        source.get("share_url"),
        source.get("crezlo_public_url"),
        source.get("vendor_tour_url"),
        facts.get("tour_url"),
        facts.get("source_virtual_tour_url"),
        source.get("source_virtual_tour_url"),
    ):
        href = _safe_pdf_href(value)
        if href:
            return href
    return ""


def _resolve_pdf_flythrough_url(*, source: dict[str, object], payload: dict[str, object]) -> str:
    for value in (
        payload.get("flythrough_url"),
        source.get("flythrough_url"),
        source.get("video_url"),
    ):
        href = _safe_pdf_href(value)
        if href:
            return href
    return ""


def _resolve_pdf_review_url(*, source: dict[str, object], payload: dict[str, object]) -> str:
    for value in (
        payload.get("review_url"),
        source.get("review_url"),
        source.get("packet_url"),
    ):
        href = _safe_pdf_href(value)
        if href:
            return href
    return ""


def _draw_wrapped(
    ops: list[str],
    text: object,
    *,
    x: float,
    y: float,
    width_chars: int,
    size: float = 10,
    leading: float = 13,
    font: str = "F1",
    fill: Color = (0.17, 0.18, 0.18),
) -> float:
    for line in _wrap_line(text, width_chars):
        _draw_text(ops, line, x=x, y=y, size=size, font=font, fill=fill)
        y -= leading
    return y


def _data_url_bytes(value: str) -> bytes:
    match = re.match(r"^data:([^;,]+)?(?:;charset=[^;,]+)?;base64,(.+)$", value, re.IGNORECASE | re.DOTALL)
    if match is None:
        return b""
    try:
        return base64.b64decode(match.group(2), validate=False)
    except Exception:
        return b""


def _pdf_image_host(value: str) -> str:
    if value.startswith("data:image/"):
        return ""
    try:
        return str(urllib.parse.urlparse(value).hostname or "").strip().lower()
    except Exception:
        return ""


def _white_ratio(image: Image.Image) -> float:
    rgb = image.convert("RGB")
    width, height = rgb.size
    if width <= 0 or height <= 0:
        return 0.0
    total = width * height
    white = 0
    for r, g, b in rgb.getdata():
        if r >= 236 and g >= 236 and b >= 236:
            white += 1
    return white / float(total)


def _looks_like_broker_logo(image: Image.Image) -> bool:
    width, height = image.size
    if width <= 0 or height <= 0:
        return False
    aspect = width / float(height)
    if not 0.75 <= aspect <= 1.35:
        return False
    if min(width, height) < 200:
        return False
    return _white_ratio(image) >= 0.34


def _crop_broker_watermark(image: Image.Image, *, host: str) -> Image.Image:
    normalized_host = str(host or "").strip().lower()
    if not normalized_host or not any(marker in normalized_host for marker in ("justimmo", "kalandra")):
        return image
    width, height = image.size
    if width < 900 or height < 640:
        return image
    right_crop = max(int(round(width * 0.09)), 72)
    cropped_width = width - right_crop
    if cropped_width < int(width * 0.72):
        return image
    return image.crop((0, 0, cropped_width, height))


def _load_pdf_image_resource(url: str) -> dict[str, object] | None:
    if not url or Image is None:
        return None
    raw_bytes = b""
    image_host = _pdf_image_host(url)
    if url.startswith("data:image/"):
        raw_bytes = _data_url_bytes(url)
    else:
        request = urllib.request.Request(str(url), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw_bytes = bytes(response.read() or b"")
        except Exception:
            return None
    if not raw_bytes:
        return None
    try:
        with Image.open(io.BytesIO(raw_bytes)) as image:
            prepared = image.convert("RGB")
            if _looks_like_broker_logo(prepared):
                return None
            prepared = _crop_broker_watermark(prepared, host=image_host)
            rgb_image = prepared.convert("RGB")
            width, height = rgb_image.size
            target = io.BytesIO()
            rgb_image.save(target, format="JPEG", quality=86, optimize=True)
    except Exception:
        return None
    return {
        "width": width,
        "height": height,
        "bytes": target.getvalue(),
        "filter": "/DCTDecode",
        "color_space": "/DeviceRGB",
        "bits_per_component": 8,
    }


def _build_pdf(pages: list[dict[str, object]]) -> bytes:
    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    catalog_id = add(b"<< /Type /Catalog /Pages 2 0 R >>")
    pages_id = add(b"")
    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    bold_font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    page_ids: list[int] = []
    for page in pages or [{"ops": [], "images": []}]:
        page_ops = list(page.get("ops") or []) if isinstance(page, dict) else []
        page_images = list(page.get("images") or []) if isinstance(page, dict) else []
        page_annotations = list(page.get("annotations") or []) if isinstance(page, dict) else []
        xobject_entries: list[str] = []
        for index, image in enumerate(page_images, start=1):
            image_bytes = bytes(image.get("bytes") or b"")
            if not image_bytes:
                continue
            width = int(image.get("width") or 0)
            height = int(image.get("height") or 0)
            if width <= 0 or height <= 0:
                continue
            filter_name = str(image.get("filter") or "/DCTDecode").strip() or "/DCTDecode"
            color_space = str(image.get("color_space") or "/DeviceRGB").strip() or "/DeviceRGB"
            bits_per_component = int(image.get("bits_per_component") or 8)
            image_id = add(
                (
                    f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
                    f"/ColorSpace {color_space} /BitsPerComponent {bits_per_component} /Filter {filter_name} "
                    f"/Length {len(image_bytes)} >>\nstream\n"
                ).encode("ascii")
                + image_bytes
                + b"\nendstream"
            )
            image_name = str(image.get("name") or f"Im{index}").strip() or f"Im{index}"
            xobject_entries.append(f"/{image_name} {image_id} 0 R")
        annotation_ids: list[int] = []
        for annotation in page_annotations:
            if not isinstance(annotation, dict):
                continue
            href = _safe_pdf_href(annotation.get("url"))
            rect = annotation.get("rect")
            if not href or not isinstance(rect, (list, tuple)) or len(rect) != 4:
                continue
            try:
                x1, y1, x2, y2 = [float(value) for value in rect]
            except Exception:
                continue
            annotation_id = add(
                (
                    "<< /Type /Annot /Subtype /Link "
                    f"/Rect [{_num(x1)} {_num(y1)} {_num(x2)} {_num(y2)}] "
                    "/Border [0 0 0] "
                    f"/A << /S /URI /URI ({_pdf_escape(href)}) >> >>"
                ).encode("latin-1", errors="replace")
            )
            annotation_ids.append(annotation_id)
        content = "\n".join(page_ops).encode("latin-1", errors="replace")
        content_id = add(b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream")
        xobject_resource = f" /XObject << {' '.join(xobject_entries)} >>" if xobject_entries else ""
        annots_resource = f" /Annots [{' '.join(f'{annotation_id} 0 R' for annotation_id in annotation_ids)}]" if annotation_ids else ""
        page_id = add(
            (
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
                f"/Resources << /Font << /F1 {font_id} 0 R /F2 {bold_font_id} 0 R >>{xobject_resource} >>{annots_resource} /Contents {content_id} 0 R >>"
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


def _draw_footer(ops: list[str], *, page_number: int, privacy_mode: PacketPrivacyMode) -> None:
    _draw_rect(ops, MARGIN_X, 34, CARD_WIDTH, 1.2, fill=(0.82, 0.80, 0.75))
    _draw_text(
        ops,
        f"PropertyQuarry Dossier - {privacy_mode.value.replace('_', ' ')} - Seite {page_number}",
        x=MARGIN_X,
        y=20,
        size=8,
        fill=(0.36, 0.37, 0.36),
    )


def _new_page(*, page_number: int, privacy_mode: PacketPrivacyMode) -> list[str]:
    ops: list[str] = []
    _draw_rect(ops, 0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=(0.965, 0.95, 0.91))
    _draw_footer(ops, page_number=page_number, privacy_mode=privacy_mode)
    return ops


def _section(title: str, items: list[str], *, accent: Color = (0.15, 0.38, 0.30)) -> dict[str, object]:
    return {"title": title, "items": items, "accent": accent}


def _media_counts(payload: dict[str, object]) -> dict[str, int]:
    floorplans = payload.get("floorplan_refs") if isinstance(payload.get("floorplan_refs"), list) else []
    photos = payload.get("photo_refs") if isinstance(payload.get("photo_refs"), list) else []
    return {"floorplans": len(floorplans), "photos": len(photos)}


def _media_refs(payload: dict[str, object]) -> dict[str, list[str]]:
    floorplans = payload.get("floorplan_refs") if isinstance(payload.get("floorplan_refs"), list) else []
    photos = payload.get("photo_refs") if isinstance(payload.get("photo_refs"), list) else []
    return {
        "floorplans": [str(item).strip() for item in floorplans if str(item).strip()],
        "photos": [str(item).strip() for item in photos if str(item).strip()],
    }


def _media_ref_display(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    display = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", parsed.query, ""))
    display = display or value
    if len(display) <= MAX_MEDIA_REF_CHARS:
        return display
    return f"{display[: MAX_MEDIA_REF_CHARS - 3]}..."


def _wrap_media_ref(value: str, width: int = 74) -> list[str]:
    text = " ".join(value.split()).strip()
    if not text:
        return []
    return wrap(text, width=width, break_long_words=True, break_on_hyphens=False) or [text]


def _packet_sections(
    *,
    payload: dict[str, object],
    packet_kind: PropertyPacketKind,
) -> list[dict[str, object]]:
    facts = dict(payload.get("facts") or {}) if isinstance(payload.get("facts"), dict) else {}

    def row(label: str, value: object) -> str:
        text = _joined(value)
        return f"{label}: {text}" if text else ""

    if packet_kind == PropertyPacketKind.PAID_MARKET_REPORT:
        market_scope = payload.get("market_scope") or facts.get("market_scope") or facts.get("market_scope_label")
        coverage = [
            row("Market scope", market_scope),
            row("Freshness date", facts.get("freshness_date")),
            row("Coverage window", facts.get("coverage_window")),
            row("Listing count", facts.get("listing_count") or facts.get("sample_size")),
        ]
        pricing = [
            row("Median buy per sqm", facts.get("median_price_per_sqm_eur") or facts.get("market_buy_per_sqm_eur")),
            row("Median rent per sqm", facts.get("median_rent_per_sqm_eur") or facts.get("market_rent_per_sqm_eur")),
            row("Median price", facts.get("median_price_eur")),
            row("Median rent", facts.get("median_rent_eur")),
            row("Gross yield", facts.get("gross_yield_pct")),
            row("Payback years", facts.get("payback_years")),
        ]
        methodology = [
            row("Data sources", facts.get("data_sources")),
            row("Data coverage", facts.get("data_coverage") or facts.get("source_coverage")),
            row("Methodology", facts.get("methodology") or "provider scan, market aggregation, and owner-safe redaction"),
        ]
        market_observations = _text_items(payload.get("market_observations"), limit=8)
        examples = _text_items(payload.get("market_examples"), limit=8) or _text_items(facts.get("market_examples"), limit=8)
        exclusions = [
            *_text_items(payload.get("unknowns"), limit=6),
            row("Exclusions", facts.get("exclusions")),
            row("Accuracy notes", facts.get("accuracy_notes")),
            row("Disclaimer", facts.get("legal_disclaimer")),
        ]
        return [
            _section("Market scope", [item for item in coverage if item] or ["Market scope was not supplied."], accent=(0.15, 0.38, 0.30)),
            _section("Pricing signals", [item for item in pricing if item] or ["No pricing signal was supplied."], accent=(0.74, 0.55, 0.18)),
            _section(
                "Source coverage",
                [item for item in methodology if item] or ["Only redacted market-level source coverage is included."],
                accent=(0.19, 0.36, 0.53),
            ),
            _section(
                "Market observations",
                market_observations or examples or ["No comparable example summary was included."],
                accent=(0.17, 0.45, 0.37),
            ),
            _section(
                "Exclusions and accuracy",
                [item for item in exclusions if item] or ["This is not a valuation, legal opinion, or offer recommendation."],
                accent=(0.62, 0.29, 0.26),
            ),
            _section(
                "Source, provenance, and privacy",
                [
                    "Source: redacted market evidence only.",
                    "No owner preference snapshot, exact address, property URL, floorplan, or photo reference is included.",
                    "PropertyQuarry remains the source of truth for ranking, methodology, and audit state.",
                    f"Renderer fallback available: {PDF_RENDERER_FALLBACK_VERSION}",
                ],
                accent=(0.30, 0.31, 0.30),
            ),
        ]

    core_facts = [
        row("Purchase price", facts.get("purchase_price_eur") or facts.get("price_eur") or facts.get("price_display")),
        row("Monthly rent", facts.get("total_rent_eur") or facts.get("rent_eur") or facts.get("rent_display")),
        row("Area", facts.get("area_m2") or facts.get("area_sqm") or facts.get("living_area_m2")),
        row("Rooms", facts.get("rooms") or facts.get("room_count")),
        row("District", facts.get("district") or facts.get("postal_name") or facts.get("city")),
    ]
    evidence = [
        row("Floorplan", facts.get("has_floorplan")),
        row("Lift", facts.get("lift") or facts.get("has_lift")),
        row("Outdoor space", facts.get("balcony") or facts.get("terrace") or facts.get("garden") or facts.get("outdoor_space")),
        row("Heating", facts.get("heating_type")),
        row("Availability", facts.get("availability")),
        row("Building type", facts.get("building_type") or facts.get("building_style")),
        row("Year built", facts.get("year_built") or facts.get("construction_year") or facts.get("building_year")),
    ]
    radius = [
        row("Supermarket", facts.get("nearest_supermarket_m") or facts.get("nearest_supermarket_name")),
        row("Pharmacy", facts.get("nearest_pharmacy_m") or facts.get("nearest_pharmacy_name")),
        row("Library", facts.get("nearest_library_m") or facts.get("nearest_library_name")),
        row("Medical care", facts.get("nearest_medical_care_m") or facts.get("nearest_medical_care_name")),
        row("Hospital", facts.get("nearest_hospital_m") or facts.get("nearest_hospital_name")),
        row("Straßenbahn / Bus", facts.get("nearest_tram_bus_m") or facts.get("nearest_tram_bus_name")),
        row("Subway", facts.get("nearest_subway_m") or facts.get("nearest_subway_name")),
        row("Playground", facts.get("nearest_playground_m") or facts.get("nearest_playground_name")),
        row("Run or green space", facts.get("nearest_running_m") or facts.get("nearest_running_name")),
    ]
    school_and_family = []
    school_quality = str(facts.get("school_atlas_quality_summary") or "").strip()
    school_progression = str(facts.get("school_atlas_progression_summary") or "").strip()
    school_route = _school_route_line(facts)
    if school_quality:
        school_and_family.append(_clean_sentence("School quality read: " + school_quality))
    if school_progression:
        school_and_family.append(_clean_sentence("School progression read: " + school_progression))
    if school_route:
        school_and_family.append(school_route)
    building_context = [
        row("Building type", facts.get("building_type") or facts.get("building_style")),
        row("Year built", facts.get("year_built") or facts.get("construction_year") or facts.get("building_year")),
        row("Heating", facts.get("heating_type")),
        row("Lift", facts.get("lift") or facts.get("has_lift")),
        row("Availability", facts.get("availability")),
    ]
    future_change = _future_change_lines(facts)
    risk_context = _official_risk_lines(facts)
    match_reasons = _text_items(payload.get("match_reasons"), limit=4)
    risks = [*_text_items(payload.get("mismatch_reasons"), limit=4), *_text_items(payload.get("unknowns"), limit=4)]
    viewing_questions = _text_items(payload.get("viewing_questions"), limit=4)

    sections = [
        _section("Core facts", [item for item in core_facts if item] or ["No core facts were supplied."], accent=(0.15, 0.38, 0.30)),
        _section("Evidence readiness", [item for item in evidence if item] or ["Evidence readiness is not yet available."], accent=(0.74, 0.55, 0.18)),
    ]
    if any(item for item in radius):
        sections.append(_section("Umfeld und tägliche Wege", [item for item in radius if item][:3], accent=(0.19, 0.36, 0.53)))
    if school_and_family:
        sections.append(_section("Familienroute", school_and_family[:2], accent=(0.18, 0.41, 0.44)))
    if risk_context:
        sections.append(_section("Sicherheit, Kriminalität und Klimarisiko", risk_context[:2], accent=(0.62, 0.29, 0.26)))
    sections.extend(
        [
            _section("Was für das Objekt spricht", match_reasons[:4] or ["Im Quelldossier wurde kein ausdrücklicher Positivgrund genannt."], accent=(0.17, 0.45, 0.37)),
            _section(
                "Risiken und offene Punkte",
                risks[:4] or ["Ein ausdrückliches Risiko wurde nicht genannt. Daher sollten Unterlagen und laufende Kosten aktiv nachgefordert werden."],
                accent=(0.62, 0.29, 0.26),
            ),
            _section(
                "Besichtigungs- und Rückfragenliste",
                viewing_questions[:4]
                or [
                    "Brauchbaren Grundriss und exakte Raummaße bestätigen.",
                    "Betriebskostenhistorie und allfällige Sanierungshinweise nachfordern.",
                    "Lärm, Licht, Stauraum und Alltagstauglichkeit vor Ort prüfen.",
                ],
                accent=(0.20, 0.37, 0.52),
            ),
        ]
    )
    sections = sections[:6]
    if packet_kind == PropertyPacketKind.PAID_MARKET_REPORT:
        sections.append(
            _section(
                "Methodology and freshness",
                [
                    "This report is generated from redacted PropertyQuarry research and market-level evidence only.",
                    row("Freshness date", facts.get("freshness_date") or "generated packet timestamp"),
                    row("Methodology", facts.get("methodology") or "provider scan, ranking assessment, and owner-safe redaction"),
                ],
                accent=(0.42, 0.25, 0.48),
            )
        )
    sections.append(
        _section(
            "Quelle, Provenienz und Datenschutz",
            [
                f"Quelle: {payload.get('property_url') or 'internes PropertyQuarry-Dossier'}",
                "Dieses Dossier wurde vor der Veröffentlichung redigiert.",
                "PropertyQuarry bleibt die maßgebliche Quelle für Ranking, Lernlogik und Prüfpfad.",
                f"Fallback-Renderer verfügbar: {PDF_RENDERER_FALLBACK_VERSION}",
            ],
            accent=(0.30, 0.31, 0.30),
        )
    )
    return sections


def _property_narrative(payload: dict[str, object]) -> list[str]:
    facts = dict(payload.get("facts") or {}) if isinstance(payload.get("facts"), dict) else {}
    title = str(payload.get("title") or "This property").strip() or "This property"
    district = str(facts.get("district") or facts.get("postal_name") or facts.get("city") or "").strip()
    rooms = facts.get("rooms") or facts.get("room_count")
    area = facts.get("area_m2") or facts.get("area_sqm") or facts.get("living_area_m2")
    price = facts.get("purchase_price_eur") or facts.get("price_eur") or facts.get("price_display")
    rent = facts.get("total_rent_eur") or facts.get("rent_eur") or facts.get("rent_display")
    availability = str(facts.get("availability") or "").strip()
    lift = facts.get("lift") if "lift" in facts else facts.get("has_lift")
    has_floorplan = facts.get("has_floorplan")
    heating = str(facts.get("heating_type") or "").strip()
    match_reasons = _text_items(payload.get("match_reasons"), limit=3)
    risks = [*_text_items(payload.get("mismatch_reasons"), limit=2), *_text_items(payload.get("unknowns"), limit=2)]
    questions = _text_items(payload.get("viewing_questions"), limit=3)
    daily_life = []
    supermarket = _walk_minutes_phrase(facts.get("nearest_supermarket_m"))
    pharmacy = _walk_minutes_phrase(facts.get("nearest_pharmacy_m"))
    library = _walk_minutes_phrase(facts.get("nearest_library_m"))
    medical_care = _walk_minutes_phrase(facts.get("nearest_medical_care_m"))
    hospital = _walk_minutes_phrase(facts.get("nearest_hospital_m"))
    tram_bus = _walk_minutes_phrase(facts.get("nearest_tram_bus_m") or facts.get("nearest_transit_m"))
    subway = _walk_minutes_phrase(facts.get("nearest_subway_m"))
    playground = _walk_minutes_phrase(facts.get("nearest_playground_m"))
    running = _walk_minutes_phrase(facts.get("nearest_running_m"))
    school_route = _school_route_line(facts)
    if supermarket:
        daily_life.append(f"der nächste Supermarkt liegt {supermarket}")
    if pharmacy:
        daily_life.append(f"die nächste Apotheke liegt {pharmacy}")
    if library:
        daily_life.append(f"die nächste Bücherei liegt {library}")
    if medical_care:
        daily_life.append(f"die nächste medizinische Versorgung liegt {medical_care}")
    if hospital:
        daily_life.append(f"das nächste Spital liegt {hospital}")
    if tram_bus:
        daily_life.append(f"die nächste Straßenbahn- oder Bushaltestelle liegt {tram_bus}")
    if subway:
        daily_life.append(f"die nächste U-Bahn-Station liegt {subway}")
    if playground:
        daily_life.append(f"der nächste Spielplatz liegt {playground}")
    if running:
        daily_life.append(f"die nächste realistische Lauf- oder Grünroute liegt {running}")

    intro_bits = [title]
    if district:
        intro_bits.append(f"in {district}")
    if rooms or area:
        shape = []
        if rooms:
            shape.append(f"{_display_number(rooms, decimals=0)} Zimmer")
        if area:
            shape.append(f"rund {_display_number(area, decimals=0)} m2")
        intro_bits.append("bietet " + " und ".join(shape))
    pricing = _money_phrase(price or rent)
    if pricing:
        intro_bits.append(f"mit einem aktuellen Ansatz von {pricing}")
    intro = _clean_sentence(", ".join(intro_bits))

    evidence_parts = []
    if has_floorplan is True:
        evidence_parts.append("ein brauchbarer Grundriss liegt bereits vor")
    if lift is True:
        evidence_parts.append("das Haus verfügt über einen Lift")
    if heating:
        evidence_parts.append(f"als Heizungsart ist {heating} angegeben")
    if availability:
        evidence_parts.append(f"die Verfügbarkeit ist mit {availability} angegeben")
    evidence = _clean_sentence(", ".join(evidence_parts))

    fit = _localize_fit_summary(payload.get("fit_summary"))
    compare_reason = _localize_compare_reason(payload.get("compare_reason"))
    if not fit and match_reasons:
        fit = _clean_sentence("Positiv fällt auf: " + "; ".join(match_reasons))
    elif not fit:
        fallback = _fallback_match_reasons(facts)
        if fallback:
            fit = _clean_sentence("Positiv fällt auf: " + "; ".join(fallback[:3]))
    neighborhood = _clean_sentence("Im Alltag spricht dafür, dass " + ", und ".join(daily_life)) if daily_life else ""
    school_quality = str(facts.get("school_atlas_quality_summary") or "").strip()
    school_progression = str(facts.get("school_atlas_progression_summary") or "").strip()
    school_items = [item for item in [school_route, school_quality, school_progression] if item]
    school = _clean_sentence("Für die Familienperspektive ist entscheidend: " + "; ".join(school_items)) if school_items else ""
    official_risk = _clean_sentence("Offizieller Risikokontext: " + "; ".join(_official_risk_lines(facts)[:3])) if _official_risk_lines(facts) else ""
    future_change = _clean_sentence("Zum Gebietsausblick gehört: " + "; ".join(_future_change_lines(facts)[:3])) if _future_change_lines(facts) else ""
    if not risks:
        risks = _fallback_risks(facts)
    risk = _clean_sentence("Vor einer Entscheidung sollte noch belastbar geklärt werden: " + "; ".join(risks)) if risks else ""
    if not questions:
        questions = _fallback_questions(facts)
    next_step = _clean_sentence("Sinnvolle nächste Fragen an Makler oder Eigentümer sind: " + "; ".join(questions)) if questions else ""

    return [item for item in [intro, compare_reason, fit, neighborhood, evidence, school, official_risk, future_change, risk, next_step] if item]


def _visual_pdf(
    *,
    payload: dict[str, object],
    title: str,
    recommended_title: str,
    packet_kind: PropertyPacketKind,
    privacy_mode: PacketPrivacyMode,
    fliplink_format: FlipLinkFormat,
    summary: str,
    media_counts: dict[str, int],
    media_refs: dict[str, list[str]],
    magic_fit_scene: dict[str, object],
    diorama_scene: dict[str, object],
    comparison_rows: list[dict[str, str]],
    packet_facts: dict[str, object],
    sections: list[dict[str, object]],
    narrative_lines: list[str],
    tour_url: str,
    flythrough_url: str,
    review_url: str,
) -> bytes:
    pages: list[dict[str, object]] = []
    redacted_tour_url = _safe_pdf_href(tour_url)
    redacted_flythrough_url = _safe_pdf_href(flythrough_url)
    redacted_review_url = _safe_pdf_href(review_url)
    photo_refs = list(media_refs.get("photos") or [])
    floorplan_refs = list(media_refs.get("floorplans") or [])
    diorama_cover_ref = str(diorama_scene.get("image_url") or "").strip() if isinstance(diorama_scene, dict) else ""
    magicfit_cover_ref = str(magic_fit_scene.get("image_url") or "").strip() if isinstance(magic_fit_scene, dict) else ""
    cover_image = (
        _load_pdf_image_resource(diorama_cover_ref)
        if diorama_cover_ref
        else (_load_pdf_image_resource(magicfit_cover_ref) if magicfit_cover_ref else (_load_pdf_image_resource(photo_refs[0]) if photo_refs else None))
    )
    floorplan_image = _load_pdf_image_resource(floorplan_refs[0]) if floorplan_refs else None
    gallery_images = []
    for ref in photo_refs[:4]:
        image = _load_pdf_image_resource(str(ref or "").strip())
        if image is not None:
            gallery_images.append(image)
    ask_value = _fact_value(packet_facts, "price_display", "price", "rent_display", "rent")
    if not ask_value:
        ask_value = _display_price(packet_facts.get("total_rent_eur") or packet_facts.get("price_eur") or packet_facts.get("purchase_price_eur") or packet_facts.get("rent_eur"))
    rooms_value = _fact_value(packet_facts, "room_count", "rooms_label")
    if not rooms_value:
        rooms_value = _display_number(packet_facts.get("room_count") or packet_facts.get("rooms"), decimals=0)
    area_value = _fact_value(packet_facts, "area_label")
    if not area_value:
        area_raw = packet_facts.get("area_m2") or packet_facts.get("area_sqm") or packet_facts.get("living_area_m2")
        area_value = _display_number(area_raw, decimals=0)
    if area_value and "m2" not in area_value.lower():
        area_value = f"{area_value} m2"
    district_value = _fact_value(packet_facts, "postal_name", "district", "city")
    office_label = _office_packet_label(packet_kind)
    privacy_label = _privacy_label(privacy_mode)
    executive_lines = narrative_lines[:2] or [summary or "Diese Liegenschaft sollte gegen das aktuelle PropertyQuarry-Suchprofil geprüft werden."]
    recommendation_label = _recommendation_label(payload.get("recommendation"))
    fit_score = payload.get("fit_score")
    try:
        fit_score_label = f"{float(fit_score):.0f}/100"
    except Exception:
        fit_score_label = "Not scored"
    mismatch_reasons = [*_text_items(payload.get("mismatch_reasons"), limit=2), *_text_items(payload.get("unknowns"), limit=2)]
    match_reasons = _text_items(payload.get("match_reasons"), limit=2) or _fallback_match_reasons(packet_facts)
    if not mismatch_reasons:
        mismatch_reasons = _fallback_risks(packet_facts)
    viewing_questions = _text_items(payload.get("viewing_questions"), limit=2) or _fallback_questions(packet_facts)
    household_review = dict(payload.get("household_review") or {}) if isinstance(payload.get("household_review"), dict) else {}
    household_stakeholders = [
        str(row.get("label") or row.get("name") or row.get("stakeholder") or "").strip()
        + (
            f": {str(row.get('decision') or row.get('reaction') or row.get('summary') or '').strip()}"
            if str(row.get("decision") or row.get("reaction") or row.get("summary") or "").strip()
            else ""
        )
        for row in list(household_review.get("stakeholders") or [])[:3]
        if isinstance(row, dict)
    ]
    household_alignment = str(household_review.get("alignment_label") or "").strip().replace("_", " ")
    household_score = household_review.get("alignment_score") or payload.get("household_alignment_score") or ""
    household_question = str(household_review.get("next_best_question") or "").strip()
    investment = dict(payload.get("investment") or {}) if isinstance(payload.get("investment"), dict) else {}
    investment_headline = str(investment.get("headline") or investment.get("recommendation") or "").strip()
    investment_rows = [
        row
        for row in [
            f"Kaufpreis: {_money_phrase(investment.get('purchase_price_eur') or packet_facts.get('purchase_price_eur') or packet_facts.get('price_eur'))}"
            if (investment.get("purchase_price_eur") or packet_facts.get("purchase_price_eur") or packet_facts.get("price_eur"))
            else "",
            f"Erwartete Miete: {_money_phrase(investment.get('expected_rent_eur') or investment.get('rent_eur'))}"
            if (investment.get("expected_rent_eur") or investment.get("rent_eur"))
            else "",
            f"Bruttorendite: {investment.get('gross_yield_pct')}%" if investment.get("gross_yield_pct") else "",
            f"Nettorendite-Spanne: {investment.get('net_yield_range')}" if investment.get("net_yield_range") else "",
        ]
        if row
    ]
    location_lines = []
    for label, distance_key, name_key in (
        ("Supermarkt", "nearest_supermarket_m", "nearest_supermarket_name"),
        ("Apotheke", "nearest_pharmacy_m", "nearest_pharmacy_name"),
        ("Bücherei", "nearest_library_m", "nearest_library_name"),
        ("Medizinische Versorgung", "nearest_medical_care_m", "nearest_medical_care_name"),
        ("Spital", "nearest_hospital_m", "nearest_hospital_name"),
        ("Straßenbahn / Bus", "nearest_tram_bus_m", "nearest_tram_bus_name"),
        ("U-Bahn", "nearest_subway_m", "nearest_subway_name"),
        ("Schule", "nearest_school_m", "nearest_school_name"),
        ("Spielplatz", "nearest_playground_m", "nearest_playground_name"),
        ("Laufen / Grünraum", "nearest_running_m", "nearest_running_name"),
    ):
        line = _distance_label(packet_facts.get(distance_key), name=packet_facts.get(name_key))
        if line:
            location_lines.append(f"{label}: {line}")
    risk_lines = _official_risk_lines(packet_facts)
    future_change_lines = _future_change_lines(packet_facts)
    school_route_line = _school_route_line(packet_facts)
    packet_contents = [
        "Hero + Urteil",
        "Eckdaten",
        "Top Chancen",
        "Top Risiken",
        "Nächste Fragen",
    ]
    if floorplan_image is not None:
        packet_contents.append("Grundriss")
    if diorama_scene and str(diorama_scene.get("image_url") or "").strip():
        packet_contents.append("Cutaway-Diorama")
    if cover_image is None and floorplan_image is not None:
        cover_image = floorplan_image
    ops = _new_page(page_number=1, privacy_mode=privacy_mode)
    hero_height = PAGE_HEIGHT
    _draw_rect(ops, 0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=(0.82, 0.83, 0.80))
    cover_kicker = "Schnelle Entscheidungsvorlage. Wenig Text, klare Signale, direkte nächste Schritte."
    if redacted_tour_url:
        redacted_tour_url = _append_query_param(redacted_tour_url, pane="floorplan-pane")
    flythrough_candidate = _safe_pdf_href(diorama_scene.get("video_url") if isinstance(diorama_scene, dict) else "")
    if not flythrough_candidate:
        flythrough_candidate = redacted_flythrough_url
    redacted_flythrough_url = flythrough_candidate
    cover_page_images: list[dict[str, object]] = []
    cover_page_annotations: list[dict[str, object]] = []
    if cover_image is not None:
        source_width = max(int(cover_image.get("width") or 1), 1)
        source_height = max(int(cover_image.get("height") or 1), 1)
        hero_x = 0.0
        hero_y = PAGE_HEIGHT - hero_height
        hero_w = float(PAGE_WIDTH)
        hero_h = float(hero_height)
        scale = max(hero_w / float(source_width), hero_h / float(source_height))
        draw_width = max(1.0, float(source_width) * scale)
        draw_height = max(1.0, float(source_height) * scale)
        draw_x = hero_x + ((hero_w - draw_width) / 2.0)
        draw_y = hero_y + ((hero_h - draw_height) / 2.0)
        _draw_image(ops, name="Im1", x=draw_x, y=draw_y, width=draw_width, height=draw_height)
        _draw_rect(ops, 0, 0, PAGE_WIDTH, 178, fill=(0.08, 0.09, 0.09))
        cover_page_images.append({**cover_image, "name": "Im1"})
    _draw_text(ops, "PropertyQuarry", x=MARGIN_X, y=PAGE_HEIGHT - 42, size=18, font="F2", fill=(0.96, 0.97, 0.95) if cover_image is not None else (0.15, 0.38, 0.30))
    _draw_text(ops, office_label, x=MARGIN_X, y=PAGE_HEIGHT - 60, size=10.8, font="F2", fill=(0.92, 0.94, 0.92) if cover_image is not None else (0.43, 0.38, 0.29))
    _draw_text(ops, privacy_label, x=MARGIN_X, y=PAGE_HEIGHT - 76, size=9.2, fill=(0.85, 0.88, 0.85) if cover_image is not None else (0.52, 0.46, 0.35))
    title_y = 146
    title_fill = (0.98, 0.98, 0.96) if cover_image is not None else (0.13, 0.14, 0.13)
    kicker_fill = (0.92, 0.94, 0.92) if cover_image is not None else (0.36, 0.37, 0.36)
    y = _draw_wrapped(
        ops,
        title,
        x=MARGIN_X,
        y=title_y,
        width_chars=30 if cover_image is not None else 38,
        size=22,
        leading=22,
        font="F2",
        fill=title_fill,
    )
    if cover_image is None:
        _draw_text(
            ops,
            district_value or "Vienna review packet",
            x=MARGIN_X,
            y=86,
            size=10.0,
            font="F2",
            fill=(0.43, 0.38, 0.29),
        )
        _draw_wrapped(
            ops,
            cover_kicker,
            x=MARGIN_X,
            y=70,
            width_chars=46,
            size=8.6,
            leading=10.6,
            fill=(0.36, 0.37, 0.36),
        )
    cta_y = 28
    if redacted_tour_url:
        button_width = 214
        button_height = 38
        _draw_rect(ops, MARGIN_X, cta_y, button_width, button_height, fill=(0.15, 0.38, 0.30))
        _draw_text(
            ops,
            "Open 3D reconstruction floor plan",
            x=MARGIN_X + 16,
            y=cta_y + 14,
            size=10.2,
            font="F2",
            fill=(0.98, 0.98, 0.96),
        )
        cover_page_annotations.append(
            {"url": redacted_tour_url, "rect": [MARGIN_X, cta_y, MARGIN_X + button_width, cta_y + button_height]}
        )
    if redacted_flythrough_url:
        fly_x = MARGIN_X + (226 if redacted_tour_url else 0)
        fly_width = 164
        fly_height = 38
        _draw_rect(ops, fly_x, cta_y, fly_width, fly_height, fill=(0.74, 0.55, 0.18))
        _draw_text(
            ops,
            "Play flythrough",
            x=fly_x + 16,
            y=cta_y + 14,
            size=10,
            font="F2",
            fill=(0.98, 0.98, 0.96),
        )
        cover_page_annotations.append(
            {"url": redacted_flythrough_url, "rect": [fly_x, cta_y, fly_x + fly_width, cta_y + fly_height]}
        )
    if redacted_review_url:
        review_x = MARGIN_X + (402 if redacted_flythrough_url else (226 if redacted_tour_url else 0))
        review_width = 182
        review_height = 38
        _draw_rect(ops, review_x, cta_y, review_width, review_height, fill=(0.93, 0.96, 0.94))
        _draw_text(
            ops,
            "Open review packet",
            x=review_x + 16,
            y=cta_y + 14,
            size=10,
            font="F2",
            fill=(0.15, 0.38, 0.30),
        )
        cover_page_annotations.append(
            {"url": redacted_review_url, "rect": [review_x, cta_y, review_x + review_width, cta_y + review_height]}
        )
    pages.append({"ops": ops, "images": cover_page_images, "annotations": cover_page_annotations})

    page_number = 2
    ops = _new_page(page_number=page_number, privacy_mode=privacy_mode)
    y = 786
    _draw_text(ops, "Entscheidung auf einen Blick", x=MARGIN_X, y=y, size=18, font="F2", fill=(0.15, 0.38, 0.30))
    _draw_rect(ops, MARGIN_X, 528, 204, 190, fill=(1.0, 0.995, 0.97))
    _draw_rect(ops, MARGIN_X, 528, 8, 190, fill=(0.15, 0.38, 0.30))
    _draw_text(ops, "Aktuelle Einordnung", x=MARGIN_X + 18, y=688, size=10.8, font="F2", fill=(0.43, 0.38, 0.29))
    _draw_text(ops, recommendation_label, x=MARGIN_X + 18, y=656, size=21, font="F2", fill=(0.12, 0.14, 0.13))
    confidence_label = _confidence_label(risk_lines=risk_lines, match_reasons=match_reasons, mismatch_reasons=mismatch_reasons)
    _draw_text(ops, f"Passung: {fit_score_label}", x=MARGIN_X + 18, y=626, size=10.2, font="F2", fill=(0.15, 0.38, 0.30))
    _draw_text(ops, f"Vertrauen in den Stand: {confidence_label}", x=MARGIN_X + 18, y=608, size=10.0, font="F2", fill=(0.35, 0.37, 0.35))
    next_action = viewing_questions[0] if viewing_questions else "Bitte Betriebskosten, Grundrisslogik und Schlafraumlage konkret nachfordern."
    _draw_text(ops, "Nächster sinnvoller Schritt", x=MARGIN_X + 18, y=578, size=10.4, font="F2", fill=(0.43, 0.38, 0.29))
    _draw_wrapped(ops, _clean_sentence(next_action), x=MARGIN_X + 18, y=560, width_chars=28, size=9.4, leading=11.2)
    _draw_rect(ops, MARGIN_X + 224, 528, CARD_WIDTH - 224, 190, fill=(1.0, 0.995, 0.97))
    _draw_rect(ops, MARGIN_X + 224, 528, 6, 190, fill=(0.74, 0.55, 0.18))
    _draw_text(ops, "Warum diese Liegenschaft nähere Prüfung verdient", x=MARGIN_X + 242, y=688, size=11.2, font="F2", fill=(0.43, 0.38, 0.29))
    prose_y = 664
    for paragraph in executive_lines[:2]:
        prose_y = _draw_wrapped(ops, paragraph, x=MARGIN_X + 242, y=prose_y, width_chars=47, size=9.6, leading=11.8)
        prose_y -= 3
        if prose_y < 548:
            break
    _draw_text(ops, "Was für das Objekt spricht", x=MARGIN_X, y=478, size=15, font="F2", fill=(0.15, 0.38, 0.30))
    _draw_text(ops, "Was noch dagegensprechen kann", x=MARGIN_X + 308, y=478, size=15, font="F2", fill=(0.62, 0.29, 0.26))
    left_y = 450
    for row in match_reasons[:2]:
        left_y = _draw_wrapped(ops, f"- {row}", x=MARGIN_X, y=left_y, width_chars=40, size=10.0, leading=13)
    right_y = 450
    for row in mismatch_reasons[:2]:
        right_y = _draw_wrapped(ops, f"- {row}", x=MARGIN_X + 308, y=right_y, width_chars=38, size=10.0, leading=13)
    _draw_rect(ops, MARGIN_X, 132, CARD_WIDTH, 206, fill=(1.0, 0.995, 0.97))
    _draw_rect(ops, MARGIN_X, 132, 6, 206, fill=(0.15, 0.38, 0.30))
    _draw_text(ops, "Kurzfazit", x=MARGIN_X + 18, y=308, size=12, font="F2", fill=(0.15, 0.38, 0.30))
    prose_y = 284
    for paragraph in narrative_lines[:2]:
        prose_y = _draw_wrapped(ops, paragraph, x=MARGIN_X + 18, y=prose_y, width_chars=88, size=9.8, leading=12.0)
        prose_y -= 3
        if prose_y < 156:
            break
    pages.append({"ops": ops, "images": []})
    page_number += 1

    ops = _new_page(page_number=page_number, privacy_mode=privacy_mode)
    _draw_text(ops, "Eckdaten und Kennzahlen", x=MARGIN_X, y=786, size=18, font="F2", fill=(0.15, 0.38, 0.30))
    fact_cards = [
        ("Preis", ask_value or "auf Anfrage"),
        ("Fläche", area_value or "k. A."),
        ("Zimmer", rooms_value or "k. A."),
        ("Lage", district_value or "k. A."),
        ("Grundriss", "vorhanden" if (packet_facts.get("has_floorplan") or packet_facts.get("floorplan_count") or floorplan_refs) else "noch nicht gesichert"),
        ("Heizung", _fact_value(packet_facts, "heating_type") or "noch offen"),
        ("Lift", _bool_label(packet_facts.get("lift") if "lift" in packet_facts else packet_facts.get("has_lift"), yes="bestätigt", no="kein Lift", unknown="noch offen")),
        ("Außenfläche", _fact_value(packet_facts, "balcony", "terrace", "garden", "outdoor_space") or "nicht bestätigt"),
        ("Energie / EPC", _fact_value(packet_facts, "epc", "energy_class", "energy_certificate") or "noch nicht bestätigt"),
    ]
    card_width = (CARD_WIDTH - 20) / 3.0
    start_y = 726.0
    for index, (label, value) in enumerate(fact_cards):
        col = index % 3
        row_index = index // 3
        x = MARGIN_X + col * (card_width + 10)
        y0 = start_y - row_index * 122
        _draw_rect(ops, x, y0 - 96, card_width, 102, fill=(1.0, 0.995, 0.97))
        _draw_rect(ops, x, y0 - 96, card_width, 8, fill=(0.15, 0.38, 0.30) if col != 2 else (0.74, 0.55, 0.18))
        _draw_text(ops, label, x=x + 14, y=y0 - 28, size=9, font="F2", fill=(0.43, 0.38, 0.29))
        _draw_wrapped(ops, value, x=x + 14, y=y0 - 52, width_chars=20, size=12.4, leading=14, font="F2", fill=(0.12, 0.14, 0.13))
    _draw_text(ops, "Was für das Objekt spricht", x=MARGIN_X, y=308, size=14, font="F2", fill=(0.15, 0.38, 0.30))
    _draw_text(ops, "Was noch dagegensprechen kann", x=MARGIN_X + 308, y=308, size=14, font="F2", fill=(0.62, 0.29, 0.26))
    left_y = 282
    for row in (match_reasons[:4] or ["No explicit match reason was supplied."]):
        left_y = _draw_wrapped(ops, f"- {row}", x=MARGIN_X, y=left_y, width_chars=38, size=9.8, leading=12.2)
    right_y = 282
    for row in (mismatch_reasons[:4] or ["No blocker was surfaced in the source packet."]):
        right_y = _draw_wrapped(ops, f"- {row}", x=MARGIN_X + 308, y=right_y, width_chars=38, size=9.8, leading=12.2)
    pages.append({"ops": ops, "images": []})
    page_number += 1

    ops = _new_page(page_number=page_number, privacy_mode=privacy_mode)
    _draw_text(ops, "3D-Tour, Grundriss und Medien", x=MARGIN_X, y=786, size=18, font="F2", fill=(0.15, 0.38, 0.30))
    preview_image = floorplan_image or cover_image or (gallery_images[0] if gallery_images else None)
    media_page_images: list[dict[str, object]] = []
    media_annotations: list[dict[str, object]] = []
    _draw_rect(ops, MARGIN_X, 212, 350, 506, fill=(0.98, 0.97, 0.94))
    if preview_image is not None:
        available_width = 324
        available_height = 454
        source_width = max(int(preview_image.get("width") or 1), 1)
        source_height = max(int(preview_image.get("height") or 1), 1)
        scale = min(available_width / float(source_width), available_height / float(source_height))
        draw_width = max(1.0, float(source_width) * scale)
        draw_height = max(1.0, float(source_height) * scale)
        draw_x = MARGIN_X + 13 + ((available_width - draw_width) / 2.0)
        draw_y = 238 + ((available_height - draw_height) / 2.0)
        _draw_image(ops, name="Im1", x=draw_x, y=draw_y, width=draw_width, height=draw_height)
        media_page_images.append({**preview_image, "name": "Im1"})
    _draw_rect(ops, MARGIN_X + 368, 212, CARD_WIDTH - 368, 506, fill=(1.0, 0.995, 0.97))
    _draw_rect(ops, MARGIN_X + 368, 212, 6, 506, fill=(0.74, 0.55, 0.18))
    _draw_text(ops, "Medienstatus", x=MARGIN_X + 386, y=694, size=12, font="F2", fill=(0.15, 0.38, 0.30))
    media_rows = [
        f"Gehostete 3D-Tour: {'verfügbar' if redacted_tour_url else 'noch nicht verfügbar'}",
        f"Flythrough: {'verfügbar' if redacted_flythrough_url else 'noch ausständig oder nicht vorhanden'}",
        f"Eingebettete Bilder: {len(gallery_images)}",
        f"Grundriss: {'eingebettet' if floorplan_image is not None else 'nur Quelle oder noch fehlend'}",
    ]
    status_y = 668
    for row in media_rows:
        status_y = _draw_wrapped(ops, row, x=MARGIN_X + 386, y=status_y, width_chars=26, size=9.8, leading=12)
    _draw_text(ops, "Empfohlene Medienreihenfolge", x=MARGIN_X + 386, y=560, size=11, font="F2", fill=(0.43, 0.38, 0.29))
    next_media_action = "Zuerst die gehostete 3D-Rekonstruktion öffnen, danach den Flythrough nutzen, um Raumfluss, Möblierbarkeit und Blickachsen zu beurteilen."
    if not redacted_tour_url and not redacted_flythrough_url:
        next_media_action = "Noch ist keine gehostete 3D-Tour verfügbar. In diesem Fall sollte man sich auf Grundriss, Quellmaterial und gezielte Mediennachforderung stützen."
    _draw_wrapped(ops, next_media_action, x=MARGIN_X + 386, y=538, width_chars=26, size=9.5, leading=11.8)
    cta_y = 262
    if redacted_tour_url:
        _draw_rect(ops, MARGIN_X + 386, cta_y, 168, 34, fill=(0.15, 0.38, 0.30))
        _draw_text(ops, "Open 3D reconstruction floor plan", x=MARGIN_X + 398, y=275, size=8.6, font="F2", fill=(0.98, 0.98, 0.96))
        media_annotations.append({"url": redacted_tour_url, "rect": [MARGIN_X + 386, cta_y, MARGIN_X + 554, cta_y + 34]})
    if redacted_flythrough_url:
        _draw_rect(ops, MARGIN_X + 386, cta_y - 46, 140, 34, fill=(0.74, 0.55, 0.18))
        _draw_text(ops, "Play flythrough", x=MARGIN_X + 410, y=229, size=9.3, font="F2", fill=(0.98, 0.98, 0.96))
        media_annotations.append({"url": redacted_flythrough_url, "rect": [MARGIN_X + 386, cta_y - 46, MARGIN_X + 526, cta_y - 12]})
    if redacted_review_url:
        _draw_rect(ops, MARGIN_X + 386, cta_y - 92, 150, 34, fill=(0.93, 0.96, 0.94))
        _draw_text(ops, "Open review packet", x=MARGIN_X + 412, y=183, size=9.2, font="F2", fill=(0.15, 0.38, 0.30))
        media_annotations.append({"url": redacted_review_url, "rect": [MARGIN_X + 386, cta_y - 92, MARGIN_X + 536, cta_y - 58]})
    pages.append({"ops": ops, "images": media_page_images, "annotations": media_annotations})
    page_number += 1

    ops = _new_page(page_number=page_number, privacy_mode=privacy_mode)
    _draw_text(ops, "Lage und Alltagsradius", x=MARGIN_X, y=786, size=18, font="F2", fill=(0.15, 0.38, 0.30))
    _draw_rect(ops, MARGIN_X, 196, 238, 520, fill=(0.98, 0.97, 0.94))
    _draw_rect(ops, MARGIN_X, 196, 238, 36, fill=(0.19, 0.36, 0.53))
    _draw_text(ops, "Alltagsradius", x=MARGIN_X + 18, y=690, size=12, font="F2", fill=(0.98, 0.98, 0.96))
    location_y = 662
    for row in (location_lines[:9] or ["Zum Alltagsradius liegt noch keine verwertbare Distanzlage vor."]):
        location_y = _draw_wrapped(ops, row, x=MARGIN_X + 18, y=location_y, width_chars=28, size=9.6, leading=12)
    _draw_rect(ops, MARGIN_X + 258, 446, CARD_WIDTH - 258, 270, fill=(1.0, 0.995, 0.97))
    _draw_rect(ops, MARGIN_X + 258, 446, 6, 270, fill=(0.18, 0.41, 0.44))
    _draw_text(ops, "Familienroute und schulische Selbstständigkeit", x=MARGIN_X + 278, y=690, size=12, font="F2", fill=(0.15, 0.38, 0.30))
    family_lines = []
    if school_route_line:
        family_lines.append(school_route_line)
    if packet_facts.get("school_atlas_quality_summary"):
        family_lines.append(_clean_sentence("Schulprofil: " + str(packet_facts.get("school_atlas_quality_summary") or "").strip()))
    if packet_facts.get("school_atlas_progression_summary"):
        family_lines.append(_clean_sentence("Übergangsprofil: " + str(packet_facts.get("school_atlas_progression_summary") or "").strip()))
    family_y = 664
    for row in (family_lines[:4] or ["Zur schulischen Eigenständigkeit liegt noch keine belastbare Einschätzung vor."]):
        family_y = _draw_wrapped(ops, row, x=MARGIN_X + 278, y=family_y, width_chars=38, size=9.4, leading=11.6)
        family_y -= 2
    _draw_rect(ops, MARGIN_X + 258, 196, CARD_WIDTH - 258, 226, fill=(1.0, 0.995, 0.97))
    _draw_rect(ops, MARGIN_X + 258, 196, 6, 226, fill=(0.43, 0.38, 0.29))
    _draw_text(ops, "Gebietsausblick und künftige Infrastruktur", x=MARGIN_X + 278, y=396, size=12, font="F2", fill=(0.15, 0.38, 0.30))
    outlook_y = 372
    for row in (future_change_lines[:4] or ["Zu künftigen Infrastruktur- oder Gebietsentwicklungen liegt aktuell kein belastbares Signal vor."]):
        outlook_y = _draw_wrapped(ops, row, x=MARGIN_X + 278, y=outlook_y, width_chars=38, size=9.4, leading=11.6)
    pages.append({"ops": ops, "images": []})
    page_number += 1

    ops = _new_page(page_number=page_number, privacy_mode=privacy_mode)
    _draw_text(ops, "Risikoregister und nächste Nachweise", x=MARGIN_X, y=786, size=18, font="F2", fill=(0.62, 0.29, 0.26))
    register_y = 736.0
    for index, row in enumerate((risk_lines[:5] or mismatch_reasons[:5] or ["Es liegt noch kein explizites Risikoregister vor. Fehlende Unterlagen sind bis zur Klärung als offenes Risiko zu behandeln."]), start=1):
        card_height = 94
        _draw_rect(ops, MARGIN_X, register_y - card_height, CARD_WIDTH, card_height, fill=(1.0, 0.995, 0.97))
        _draw_rect(ops, MARGIN_X, register_y - card_height, 8, card_height, fill=(0.62, 0.29, 0.26))
        _draw_text(ops, f"{index}. Prüffeld", x=MARGIN_X + 18, y=register_y - 24, size=10.2, font="F2", fill=(0.62, 0.29, 0.26))
        _draw_wrapped(ops, row, x=MARGIN_X + 18, y=register_y - 44, width_chars=84, size=9.4, leading=11.4)
        register_y -= card_height + 12
        if register_y < 248:
            break
    lower_left_x = MARGIN_X
    lower_right_x = MARGIN_X + 300
    _draw_text(ops, "Fragen an Makler oder Eigentümer", x=lower_left_x, y=220, size=13, font="F2", fill=(0.15, 0.38, 0.30))
    qy = 196
    for row in (viewing_questions[:4] or ["Can you send the floorplan with room dimensions and the latest operating-cost history?"]):
        qy = _draw_wrapped(ops, f"- {row}", x=lower_left_x, y=qy, width_chars=36, size=9.4, leading=11.5)
    _draw_text(ops, "Haushaltsbild" if household_stakeholders else "Wirkung der Entscheidung", x=lower_right_x, y=220, size=13, font="F2", fill=(0.43, 0.38, 0.29))
    hy = 196
    if household_stakeholders:
        if household_alignment:
            hy = _draw_wrapped(ops, f"Abgleich: {household_alignment}", x=lower_right_x, y=hy, width_chars=34, size=9.4, leading=11.5)
        if household_score != "":
            hy = _draw_wrapped(ops, f"Abgleichswert: {household_score}", x=lower_right_x, y=hy, width_chars=34, size=9.4, leading=11.5)
        for row in household_stakeholders[:3]:
            hy = _draw_wrapped(ops, f"- {row}", x=lower_right_x, y=hy, width_chars=34, size=9.2, leading=11.2)
        if household_question:
            _draw_wrapped(ops, "Nächste Frage: " + household_question, x=lower_right_x, y=max(112, hy - 8), width_chars=34, size=9.2, leading=11.2)
    else:
        for row in [
            "Die nächste gespeicherte Entscheidung wirkt direkt auf die künftige Rangfolge ähnlicher Angebote.",
            "Fehlende Fakten sollten sofort in konkrete Nachfragen übersetzt werden.",
            "Anonymisierte Risikosignale werden erst nach Erreichen der Datenschutzschwellen veröffentlicht.",
        ]:
            hy = _draw_wrapped(ops, row, x=lower_right_x, y=hy, width_chars=34, size=9.2, leading=11.2)
    pages.append({"ops": ops, "images": []})
    page_number += 1

    if investment_headline or investment_rows:
        ops = _new_page(page_number=page_number, privacy_mode=privacy_mode)
        _draw_text(ops, "Investment-Blick", x=MARGIN_X, y=786, size=18, font="F2", fill=(0.15, 0.38, 0.30))
        _draw_wrapped(
            ops,
            investment_headline or "Diese Seite ist als nüchterne Investment-Einschätzung zu lesen, nicht als Vermarktungstext.",
            x=MARGIN_X,
            y=760,
            width_chars=84,
            size=10.0,
            leading=12.2,
        )
        iy = 716
        for row in investment_rows or ["Der Basiscase hängt weiterhin von bestätigten Betriebskosten, Rücklagenlage und Rechtsfakten ab."]:
            iy = _draw_wrapped(ops, row, x=MARGIN_X, y=iy, width_chars=86, size=9.5, leading=12)
        pages.append({"ops": ops, "images": []})
        page_number += 1

    if comparison_rows:
        ops = _new_page(page_number=page_number, privacy_mode=privacy_mode)
        _draw_text(ops, "Vergleichsbild", x=MARGIN_X, y=786, size=18, font="F2", fill=(0.15, 0.38, 0.30))
        _draw_wrapped(
            ops,
            "Diese Vergleichsseite stellt die führende Option den naheliegendsten Alternativen gegenüber, damit die Auswahl wie eine echte Empfehlung und nicht wie eine lose Link-Sammlung wirkt.",
            x=MARGIN_X,
            y=764,
            width_chars=86,
            size=9.6,
            leading=12,
            fill=(0.35, 0.37, 0.35),
        )
        card_width = (CARD_WIDTH - 24) / 3.0
        base_x = MARGIN_X
        card_top = 710.0
        for index, row in enumerate(comparison_rows[:3]):
            x = base_x + index * (card_width + 12)
            card_height = 518
            fill = (0.97, 0.98, 0.96) if index == 0 else (1.0, 0.995, 0.97)
            accent = (0.15, 0.38, 0.30) if index == 0 else (0.74, 0.55, 0.18)
            _draw_rect(ops, x, card_top - card_height, card_width, card_height, fill=fill)
            _draw_rect(ops, x, card_top - card_height, card_width, 18, fill=accent)
            _draw_text(ops, "Führende Option" if index == 0 else f"Alternative {index}", x=x + 14, y=card_top - 36, size=8.7, font="F2", fill=(0.30, 0.36, 0.32))
            title_y = _draw_wrapped(ops, row.get("title"), x=x + 14, y=card_top - 56, width_chars=22, size=11.5, leading=13.5, font="F2", fill=(0.12, 0.14, 0.13))
            stat_y = title_y - 8
            for stat in (
                row.get("price") or "",
                f"{row.get('rooms')} Zimmer" if row.get("rooms") else "",
                f"{row.get('area')} m2" if row.get("area") else "",
                row.get("recommendation") or "",
            ):
                if stat:
                    _draw_text(ops, stat, x=x + 14, y=stat_y, size=8.8, font="F2", fill=(0.30, 0.36, 0.32))
                    stat_y -= 13
            _draw_text(ops, "Warum diese Option vorne liegt" if index == 0 else "Warum sie zurückliegt", x=x + 14, y=stat_y - 8, size=9.4, font="F2", fill=(0.15, 0.38, 0.30))
            _draw_wrapped(
                ops,
                _localize_compare_reason(row.get("compare_reason")) or "Für diese Vergleichszeile liegt noch keine präzise Begründung vor.",
                x=x + 14,
                y=stat_y - 26,
                width_chars=22,
                size=8.8,
                leading=10.8,
                fill=(0.18, 0.19, 0.18),
            )
        pages.append({"ops": ops, "images": []})
        page_number += 1

    if floorplan_image is not None:
        ops = _new_page(page_number=page_number, privacy_mode=privacy_mode)
        _draw_text(ops, "Grundriss", x=MARGIN_X, y=786, size=18, font="F2", fill=(0.15, 0.38, 0.30))
        _draw_wrapped(
            ops,
            "Der Grundriss steht hier bewusst früh, damit Raumfluss, Möblierbarkeit und Stauraum vor einer Besichtigung nachvollziehbar geprüft werden können.",
            x=MARGIN_X,
            y=764,
            width_chars=86,
            size=9.6,
            leading=12,
            fill=(0.35, 0.37, 0.35),
        )
        _draw_rect(ops, MARGIN_X, 122, CARD_WIDTH, 608, fill=(0.99, 0.99, 0.97))
        _draw_rect(ops, MARGIN_X, 122, 6, 608, fill=(0.15, 0.38, 0.30))
        source_width = max(int(floorplan_image.get("width") or 1), 1)
        source_height = max(int(floorplan_image.get("height") or 1), 1)
        available_width = CARD_WIDTH - 26
        available_height = 560
        scale = min(available_width / float(source_width), available_height / float(source_height))
        draw_width = max(1.0, float(source_width) * scale)
        draw_height = max(1.0, float(source_height) * scale)
        draw_x = MARGIN_X + 13 + ((available_width - draw_width) / 2.0)
        draw_y = 150 + ((available_height - draw_height) / 2.0)
        _draw_image(ops, name="Im1", x=draw_x, y=draw_y, width=draw_width, height=draw_height)
        _draw_text(ops, "Grundriss aus der Quelle", x=MARGIN_X + 18, y=700, size=11, font="F2", fill=(0.12, 0.14, 0.13))
        pages.append({"ops": ops, "images": [{**floorplan_image, "name": "Im1"}]})
        page_number += 1

    ops = _new_page(page_number=page_number, privacy_mode=privacy_mode)
    y = 786
    _draw_text(ops, "Research-Notizen und Beleglage", x=MARGIN_X, y=y, size=17, font="F2", fill=(0.15, 0.38, 0.30))
    _draw_wrapped(
        ops,
        "Dieser Abschnitt hält die Beleglage sichtbar, ohne das gesamte Dossier in einen technischen Ausdruck kippen zu lassen.",
        x=MARGIN_X,
        y=y - 22,
        width_chars=82,
        size=9.4,
        leading=12,
        fill=(0.36, 0.37, 0.36),
    )
    col_gap = 18
    col_width = (CARD_WIDTH - col_gap) / 2.0
    col_y = [720.0, 720.0]
    for index, section in enumerate(sections):
        title_text = str(section.get("title") or "").strip()
        raw_items = section.get("items")
        items = [str(item or "").strip() for item in raw_items if str(item or "").strip()] if isinstance(raw_items, list) else []
        raw_accent = section.get("accent")
        accent: Color = raw_accent if isinstance(raw_accent, tuple) and len(raw_accent) == 3 else (0.15, 0.38, 0.30)  # type: ignore[assignment]
        wrapped_count = sum(max(1, len(_wrap_line(item, 34))) for item in items[:6])
        card_height = max(84, 42 + wrapped_count * 12)
        column = 0 if col_y[0] >= col_y[1] else 1
        x = MARGIN_X if column == 0 else MARGIN_X + col_width + col_gap
        if col_y[column] - card_height < 64:
            pages.append({"ops": ops, "images": []})
            page_number += 1
            ops = _new_page(page_number=page_number, privacy_mode=privacy_mode)
            _draw_text(ops, "Research-Notizen und Beleglage", x=MARGIN_X, y=786, size=17, font="F2", fill=(0.15, 0.38, 0.30))
            col_y = [744.0, 744.0]
            column = 0
            x = MARGIN_X
        y_cursor = col_y[column]
        _draw_rect(ops, x, y_cursor - card_height, col_width, card_height, fill=(1.0, 0.995, 0.97))
        _draw_rect(ops, x, y_cursor - card_height, 6, card_height, fill=accent)
        _draw_text(ops, title_text, x=x + 18, y=y_cursor - 21, size=12, font="F2", fill=(0.12, 0.14, 0.13))
        item_y = y_cursor - 40
        for item in items[:6] or ["No source item supplied."]:
            item_y = _draw_wrapped(ops, item, x=x + 20, y=item_y, width_chars=34, size=9.2, leading=11.5)
        col_y[column] -= card_height + 16
    pages.append({"ops": ops, "images": []})
    page_number += 1

    ops = _new_page(page_number=page_number, privacy_mode=privacy_mode)
    y = 786
    _draw_text(ops, "Provenienz, Datenschutz und Hinweis", x=MARGIN_X, y=y, size=17, font="F2", fill=(0.15, 0.38, 0.30))
    provenance_blocks = [
        ("Provenienz", [
            f"Quellinserat: {payload.get('property_url') or 'internes PropertyQuarry-Dossier'}",
            f"Renderer-Version: {PDF_RENDERER_VERSION}",
            f"Datenschutzmodus: {privacy_mode.value.replace('_', ' ')}",
            "Jeder gehostete Link in diesem Dossier führt auf eine freigegebene White-Label-Oberfläche und nicht auf eine interne Debug-Ansicht.",
        ]),
        ("Datenschutz", [
            "Dieses Dossier blendet private Präferenzstände, interne Quelldiagnostik, Principal-IDs, Tokens und exakte Adressfelder aus, sofern sie nicht ausdrücklich freigegeben wurden.",
            "Familien-, Berater- und Haushaltsansichten werden vor Veröffentlichung redigiert.",
        ]),
        ("Hinweis", [
            "Dieses Dossier unterstützt die Entscheidungsfindung, ersetzt aber keine rechtliche, technische, steuerliche oder investmentbezogene Beratung.",
            "Distanzen, Routensicherheit, schulische Selbstständigkeit und Gebietsausblick sollten vor einer bindenden Entscheidung weiterhin vor Ort überprüft werden.",
        ]),
    ]
    prov_y = 730
    for title_text, items in provenance_blocks:
        block_height = 140
        _draw_rect(ops, MARGIN_X, prov_y - block_height, CARD_WIDTH, block_height, fill=(1.0, 0.995, 0.97))
        _draw_rect(ops, MARGIN_X, prov_y - block_height, 6, block_height, fill=(0.43, 0.38, 0.29))
        _draw_text(ops, title_text, x=MARGIN_X + 18, y=prov_y - 22, size=12, font="F2", fill=(0.12, 0.14, 0.13))
        item_y = prov_y - 44
        for item in items:
            item_y = _draw_wrapped(ops, item, x=MARGIN_X + 18, y=item_y, width_chars=88, size=9.2, leading=11.4)
        prov_y -= block_height + 18
    pages.append({"ops": ops, "images": []})

    if gallery_images:
        page_number += 1
        ops = _new_page(page_number=page_number, privacy_mode=privacy_mode)
        y = 786
        _draw_text(ops, "Bildauswahl", x=MARGIN_X, y=y, size=17, font="F2", fill=(0.15, 0.38, 0.30))
        _draw_wrapped(
            ops,
            "Ausgewählte Objektbilder sind direkt eingebettet, damit das Dossier wie eine ernsthafte Präsentation und nicht wie ein bloßer Medienanhang wirkt.",
            x=MARGIN_X,
            y=y - 24,
            width_chars=82,
            size=9.5,
            leading=12,
            fill=(0.36, 0.37, 0.36),
        )
        placements = [
            (MARGIN_X, 444, 250, 184),
            (MARGIN_X + 274, 444, 250, 184),
            (MARGIN_X, 208, 250, 184),
            (MARGIN_X + 274, 208, 250, 184),
        ]
        gallery_page_images: list[dict[str, object]] = []
        for index, image in enumerate(gallery_images[:4], start=1):
            x, y0, w, h = placements[index - 1]
            _draw_rect(ops, x - 4, y0 - 4, w + 8, h + 24, fill=(0.96, 0.94, 0.90))
            source_width = max(int(image.get("width") or 1), 1)
            source_height = max(int(image.get("height") or 1), 1)
            scale = min(w / float(source_width), h / float(source_height))
            draw_width = max(1.0, float(source_width) * scale)
            draw_height = max(1.0, float(source_height) * scale)
            draw_x = x + ((w - draw_width) / 2.0)
            draw_y = y0 + ((h - draw_height) / 2.0)
            image_name = f"Im{index}"
            _draw_image(ops, name=image_name, x=draw_x, y=draw_y, width=draw_width, height=draw_height)
            _draw_text(ops, f"Listing view {index}", x=x + 10, y=y0 - 16, size=8.6, font="F2", fill=(0.30, 0.36, 0.32))
            gallery_page_images.append({**image, "name": image_name})
        pages.append({"ops": ops, "images": gallery_page_images})

    diorama_image = _load_pdf_image_resource(str(diorama_scene.get("image_url") or "").strip()) if diorama_scene else None
    if diorama_scene and diorama_image is not None:
        page_number += 1
        ops = _new_page(page_number=page_number, privacy_mode=privacy_mode)
        y = 786
        _draw_text(ops, "Diorama preview", x=MARGIN_X, y=y, size=17, font="F2", fill=(0.15, 0.38, 0.30))
        _draw_wrapped(
            ops,
            str(diorama_scene.get("summary") or "A white-label diorama preview of the property route and occupied interior scene."),
            x=MARGIN_X,
            y=y - 24,
            width_chars=82,
            size=9.5,
            leading=12,
            fill=(0.36, 0.37, 0.36),
        )
        _draw_rect(ops, MARGIN_X, 162, CARD_WIDTH, 474, fill=(0.98, 0.97, 0.94))
        available_width = CARD_WIDTH - 26
        available_height = 416
        source_width = max(int(diorama_image.get("width") or 1), 1)
        source_height = max(int(diorama_image.get("height") or 1), 1)
        scale = min(available_width / float(source_width), available_height / float(source_height))
        draw_width = max(1.0, float(source_width) * scale)
        draw_height = max(1.0, float(source_height) * scale)
        draw_x = MARGIN_X + 13 + ((available_width - draw_width) / 2.0)
        draw_y = 198 + ((available_height - draw_height) / 2.0)
        _draw_image(ops, name="Im1", x=draw_x, y=draw_y, width=draw_width, height=draw_height)
        annotations = []
        if redacted_tour_url:
            annotations.append({"url": redacted_tour_url, "rect": [MARGIN_X + 18, 142, MARGIN_X + 210, 176]})
            _draw_rect(ops, MARGIN_X + 18, 142, 192, 34, fill=(0.15, 0.38, 0.30))
            _draw_text(ops, "Open 3D reconstruction", x=MARGIN_X + 32, y=155, size=9.5, font="F2", fill=(0.98, 0.98, 0.96))
        if redacted_flythrough_url:
            annotations.append({"url": redacted_flythrough_url, "rect": [MARGIN_X + 224, 142, MARGIN_X + 392, 176]})
            _draw_rect(ops, MARGIN_X + 224, 142, 168, 34, fill=(0.74, 0.55, 0.18))
            _draw_text(ops, "Play flythrough", x=MARGIN_X + 250, y=155, size=9.5, font="F2", fill=(0.98, 0.98, 0.96))
        pages.append({"ops": ops, "images": [{**diorama_image, "name": "Im1"}], "annotations": annotations})

    scene_image = _load_pdf_image_resource(str(magic_fit_scene.get("image_url") or "").strip()) if magic_fit_scene else None
    if magic_fit_scene and scene_image is not None:
        page_number += 1
        ops = _new_page(page_number=page_number, privacy_mode=privacy_mode)
        y = 786
        _draw_text(ops, "Lifestyle scene", x=MARGIN_X, y=y, size=17, font="F2", fill=(0.15, 0.38, 0.30))
        y = _draw_wrapped(
            ops,
            str(magic_fit_scene.get("summary") or "Visual simulation for the property packet."),
            x=MARGIN_X,
            y=y - 24,
            width_chars=80,
            size=9.5,
            leading=12,
            fill=(0.36, 0.37, 0.36),
        )
        _draw_rect(ops, MARGIN_X, 164, CARD_WIDTH, 470, fill=(0.98, 0.97, 0.94))
        _draw_rect(ops, MARGIN_X, 164, 6, 470, fill=(0.74, 0.55, 0.18))
        available_width = CARD_WIDTH - 28
        available_height = 420
        source_width = max(int(scene_image.get("width") or 1), 1)
        source_height = max(int(scene_image.get("height") or 1), 1)
        scale = min(available_width / float(source_width), available_height / float(source_height))
        draw_width = max(1.0, float(source_width) * scale)
        draw_height = max(1.0, float(source_height) * scale)
        draw_x = MARGIN_X + 14 + ((available_width - draw_width) / 2.0)
        draw_y = 196 + ((available_height - draw_height) / 2.0)
        _draw_image(ops, name="Im1", x=draw_x, y=draw_y, width=draw_width, height=draw_height)
        _draw_text(ops, "Visual simulation", x=MARGIN_X + 18, y=610, size=11.5, font="F2", fill=(0.12, 0.14, 0.13))
        _draw_text(
            ops,
            str(magic_fit_scene.get("scene_type") or "scene").replace("_", " "),
            x=MARGIN_X + 18,
            y=592,
            size=9,
            fill=(0.43, 0.38, 0.29),
        )
        _draw_wrapped(
            ops,
            "This image is a generated lifestyle simulation for decision-making only. It is not listing photography and should not be treated as factual evidence.",
            x=MARGIN_X + 18,
            y=145,
            width_chars=82,
            size=8.8,
            leading=11,
            fill=(0.36, 0.37, 0.36),
        )
        pages.append({"ops": ops, "images": [{**scene_image, "name": "Im1"}]})

    return _build_pdf(pages)


def render_property_packet_pdf_legacy(
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
) -> dict[str, object]:
    redaction = redact_property_packet(
        source=source,
        privacy_mode=privacy_mode,
        packet_kind=packet_kind,
        include_exact_address=include_exact_address,
        include_floorplan=include_floorplan,
        include_photos=include_photos,
    )
    title = str(redaction.payload.get("title") or source.get("title") or "PropertyQuarry packet").strip() or "PropertyQuarry packet"
    recommended_title = f"{title} - {packet_kind.value.replace('_', ' ').title()}"
    sections = _packet_sections(payload=redaction.payload, packet_kind=packet_kind)
    media_counts = _media_counts(redaction.payload)
    media_refs = _media_refs(redaction.payload)
    media_link_count = sum(len(items) for items in media_refs.values())
    pdf_bytes = _visual_pdf(
        payload=redaction.payload,
        title=title,
        recommended_title=recommended_title,
        packet_kind=packet_kind,
        privacy_mode=privacy_mode,
        fliplink_format=fliplink_format,
        summary=str(redaction.payload.get("fit_summary") or redaction.payload.get("recommendation") or ""),
        media_counts=media_counts,
        media_refs=media_refs,
        magic_fit_scene=dict(redaction.payload.get("magic_fit_scene") or {}) if isinstance(redaction.payload.get("magic_fit_scene"), dict) else {},
        diorama_scene=dict(redaction.payload.get("diorama_scene") or {}) if isinstance(redaction.payload.get("diorama_scene"), dict) else {},
        comparison_rows=_comparison_rows(redaction.payload.get("comparison_rows")),
        packet_facts=dict(redaction.payload.get("facts") or {}) if isinstance(redaction.payload.get("facts"), dict) else {},
        sections=sections,
        narrative_lines=_property_narrative(redaction.payload),
        tour_url=_resolve_pdf_primary_tour_url(source=source, payload=redaction.payload),
        flythrough_url=_resolve_pdf_flythrough_url(source=source, payload=redaction.payload),
        review_url=_resolve_pdf_review_url(source=source, payload=redaction.payload),
    )
    pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    principal_token = _safe_token(principal_id, "principal")
    target_dir = artifact_root / "property_packets" / principal_token
    target_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = target_dir / f"{_safe_token(publication_id)}.pdf"
    receipt_path = target_dir / f"{_safe_token(publication_id)}.receipt.json"
    pdf_path.write_bytes(pdf_bytes)
    visual_elements = ["cover", "metric_cards", "section_cards", "privacy_footer"]
    if _comparison_rows(redaction.payload.get("comparison_rows")):
        visual_elements.insert(1, "comparison_snapshot")
    if media_counts.get("floorplans"):
        visual_elements.insert(2 if "comparison_snapshot" in visual_elements else 1, "floorplan_sheet")
    if media_counts.get("photos"):
        visual_elements.insert(3, "photo_gallery")
    if isinstance(redaction.payload.get("diorama_scene"), dict):
        visual_elements.insert(4 if "photo_gallery" in visual_elements else 3, "diorama_scene")
    if isinstance(redaction.payload.get("magic_fit_scene"), dict):
        visual_elements.insert(5 if "diorama_scene" in visual_elements or "photo_gallery" in visual_elements else 3, "magic_fit_scene")
    receipt = {
        **redaction.receipt,
        "renderer_version": PDF_RENDERER_VERSION,
        "renderer_kind": "branded_visual_pdf",
        "visual_elements": visual_elements,
        "media_link_count": media_link_count,
        "embedded_media_refs": {key: len(items) for key, items in media_refs.items()},
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
    include_floorplan: bool = True,
    include_photos: bool = True,
) -> dict[str, object]:
    from app.services.premium_dossier import render_property_packet_pdf_via_premium_pipeline

    return render_property_packet_pdf_via_premium_pipeline(
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
        legacy_renderer=render_property_packet_pdf_legacy,
    )
