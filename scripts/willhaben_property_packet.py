#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.parse
from dataclasses import dataclass

import requests


USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0 Safari/537.36"
NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL)
FLOORPLAN_TOKENS = (
    "grundriss",
    "lageplan",
    "raumplan",
    "floorplan",
    "plan",
    "schnitt",
    "skizze",
)


@dataclass(frozen=True)
class Variant:
    variant_key: str
    scene_strategy: str
    theme_name: str
    tour_style: str
    audience: str
    creative_brief: str
    call_to_action: str
    scene_selection_json: dict[str, object]
    tour_settings_json: dict[str, object]


def fetch_html(url: str) -> str:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    response.raise_for_status()
    return response.text


def extract_next_data(html: str) -> dict[str, object]:
    match = NEXT_DATA_RE.search(html)
    if not match:
        raise RuntimeError("willhaben_next_data_missing")
    loaded = json.loads(match.group(1))
    if not isinstance(loaded, dict):
        raise RuntimeError("willhaben_next_data_invalid")
    return loaded


def deep_get(mapping: object, *keys: str) -> object:
    current = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = re.sub(r"<[^>]+>", " ", value)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        parts = [as_text(entry) for entry in value]
        return " | ".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in ("value", "label", "text", "name"):
            text = as_text(value.get(key))
            if text:
                return text
        return ""
    return str(value).strip()


def normalize_attribute_value(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        result: list[str] = []
        for entry in raw:
            text = as_text(entry)
            if text:
                result.append(text)
        return result
    if isinstance(raw, dict):
        nested = raw.get("value")
        if nested is not None and nested is not raw:
            return normalize_attribute_value(nested)
        text = as_text(raw)
        return [text] if text else []
    text = as_text(raw)
    return [text] if text else []


def load_advert(url: str) -> dict[str, object]:
    next_data = extract_next_data(fetch_html(url))
    advert = deep_get(next_data, "props", "pageProps", "advertDetails")
    if not isinstance(advert, dict):
        raise RuntimeError("willhaben_advert_details_missing")
    return advert


def extract_attributes(advert: dict[str, object]) -> dict[str, list[str]]:
    raw = deep_get(advert, "attributes", "attribute")
    if not isinstance(raw, list):
        return {}
    attributes: dict[str, list[str]] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = as_text(entry.get("name"))
        if not name:
            continue
        values = normalize_attribute_value(entry.get("values"))
        if not values:
            values = normalize_attribute_value(entry.get("value"))
        if values:
            attributes[name] = values
    return attributes


def numeric_from_text(value: str) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = re.sub(r"[^0-9,.\-]", "", text)
    if not text:
        return None
    if "." in text and "," in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    elif text.count(".") > 1:
        head, tail = text.rsplit(".", 1)
        text = head.replace(".", "") + "." + tail
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except Exception:
        return None


def pick_first_attribute(attributes: dict[str, list[str]], *names: str) -> str:
    for name in names:
        values = attributes.get(name) or []
        if values:
            return values[0]
    return ""


def looks_like_floorplan(*values: object) -> bool:
    haystack = " ".join(as_text(value).lower() for value in values if as_text(value))
    return any(token in haystack for token in FLOORPLAN_TOKENS)


def best_image_url(image: dict[str, object]) -> str:
    for key in ("mainImageUrl", "referenceImageUrl", "largeImageUrl", "middleImageUrl", "smallImageUrl"):
        text = as_text(image.get(key))
        if text:
            return text
    return ""


def extract_media(advert: dict[str, object]) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    images = deep_get(advert, "advertImageList", "advertImage")
    photos: list[dict[str, object]] = []
    floorplans: list[dict[str, object]] = []
    all_assets: list[dict[str, object]] = []
    if isinstance(images, list):
        for index, entry in enumerate(images):
            if not isinstance(entry, dict):
                continue
            url = best_image_url(entry)
            if not url:
                continue
            description = as_text(entry.get("description"))
            asset = {
                "index": index,
                "url": url,
                "description": description,
                "role": "floorplan" if looks_like_floorplan(description, url) else "photo",
            }
            all_assets.append(asset)
            if asset["role"] == "floorplan":
                floorplans.append(asset)
            else:
                photos.append(asset)
    attachments = deep_get(advert, "advertAttachmentList", "advertAttachment")
    if isinstance(attachments, list):
        for entry in attachments:
            if not isinstance(entry, dict):
                continue
            url = as_text(entry.get("url") or entry.get("attachmentUrl") or entry.get("downloadUrl"))
            if not url:
                continue
            description = as_text(entry.get("description") or entry.get("name") or entry.get("title"))
            if looks_like_floorplan(description, url):
                asset = {"index": len(all_assets), "url": url, "description": description or "Attachment floorplan", "role": "floorplan"}
                floorplans.append(asset)
                all_assets.append(asset)
    return photos, floorplans, all_assets


def teaser_values(advert: dict[str, object]) -> tuple[float | None, float | None, list[str]]:
    teaser = advert.get("teaserAttributes")
    rooms = None
    area = None
    labels: list[str] = []
    if isinstance(teaser, list):
        for entry in teaser:
            if not isinstance(entry, dict):
                continue
            value = as_text(entry.get("value"))
            postfix = as_text(entry.get("postfix"))
            joined = " ".join(part for part in (value, postfix) if part).strip()
            if joined:
                labels.append(joined)
            lowered = postfix.lower()
            if "m²" in postfix or "m2" in lowered:
                area = numeric_from_text(value)
            if "zimmer" in lowered:
                rooms = numeric_from_text(value)
    return rooms, area, labels


def build_variants(*, title: str, floorplan_count: int, photo_count: int, facts: dict[str, object]) -> list[dict[str, object]]:
    headline = str(facts.get("headline_hook") or title).strip()
    availability = str(facts.get("availability") or "").strip()
    room_text = str(facts.get("rooms_label") or "").strip()
    area_text = str(facts.get("area_label") or "").strip()
    layout_first = Variant(
        variant_key="layout_first",
        scene_strategy="layout_first",
        theme_name="clean_light",
        tour_style="guided_layout_walkthrough",
        audience="tenant_screening",
        creative_brief=f"Lead with orientation and clarity. Open on the floor plan, then walk the viewer through the most decision-relevant spaces for {headline}.",
        call_to_action="Book a viewing or save this tour for shortlist review.",
        scene_selection_json={"include_floorplans": floorplan_count > 0, "floorplan_position": "start", "max_photos": min(max(photo_count, 1), 10)},
        tour_settings_json={"showSceneNumbers": True, "defaultPanel": "share", "tone": "practical"},
    )
    lifestyle = Variant(
        variant_key="light_and_view",
        scene_strategy="story_first",
        theme_name="warm_editorial",
        tour_style="atmospheric_highlights",
        audience="urban_renter",
        creative_brief=f"Sell the first impression. Emphasize light, views, outdoor space, and the spaces a renter imagines using every day. Mention {room_text or 'the room layout'} and {area_text or 'overall scale'}.",
        call_to_action="Open the share link for the most photogenic version of this home.",
        scene_selection_json={"include_floorplans": floorplan_count > 0, "floorplan_position": "end", "max_photos": min(max(photo_count, 1), 8)},
        tour_settings_json={"showSceneNumbers": False, "defaultPanel": "theme", "tone": "editorial"},
    )
    shortlist = Variant(
        variant_key="shortlist_comparison",
        scene_strategy="compact",
        theme_name="minimal_analyst",
        tour_style="comparison_ready",
        audience="shortlist_reviewer",
        creative_brief=f"Create a fast shortlist artifact with compact scenes, a direct title, and cues for rent, availability, and tradeoffs. Availability: {availability or 'not stated'}.",
        call_to_action="Compare this listing against the other Brigittenau options.",
        scene_selection_json={"include_floorplans": floorplan_count > 0, "floorplan_position": "alternate" if floorplan_count > 0 else "omit", "max_photos": min(max(photo_count, 1), 6)},
        tour_settings_json={"showSceneNumbers": True, "defaultPanel": "ctas", "tone": "analyst"},
    )
    return [variant.__dict__ for variant in (layout_first, lifestyle, shortlist)]


def summarize_listing(url: str) -> dict[str, object]:
    advert = load_advert(url)
    attributes = extract_attributes(advert)
    photos, floorplans, assets = extract_media(advert)
    rooms, area, teaser_labels = teaser_values(advert)
    seo = deep_get(advert, "seoMetaData") or {}
    address = deep_get(advert, "advertAddressDetails") or {}
    organisation = deep_get(advert, "organisationDetails") or {}
    canonical_url = as_text((seo or {}).get("canonicalUrl")) or url
    description = as_text(advert.get("description"))
    title = description or as_text((seo or {}).get("title")) or canonical_url
    description = as_text(advert.get("description"))
    total_rent = numeric_from_text(pick_first_attribute(attributes, "RENTAL_PRICE/TOTAL_ENCUMBRANCE", "PRICE", "EUROPRICE"))
    area_label = pick_first_attribute(attributes, "ESTATE_SIZE/LIVING_AREA", "ESTATE_SIZE/USEABLE_AREA")
    if area is None:
        area = numeric_from_text(area_label)
    rooms_label = pick_first_attribute(attributes, "NUMBER_OF_ROOMS", "ESTATE_SIZE/NUMBER_OF_ROOMS")
    if rooms is None:
        rooms = numeric_from_text(rooms_label)
    availability = pick_first_attribute(
        attributes,
        "AVAILABLE_NOW",
        "AVAILABLE_DATE",
        "GENERAL_TEXT_ADVERT/Available from",
        "GENERAL_TEXT_ADVERT/verfuegbar ab",
        "DURATION/TERMLIMITTEXT",
    )
    headline_hook = (
        pick_first_attribute(attributes, "GENERAL_TEXT_ADVERT/Ausstattung")
        or pick_first_attribute(attributes, "GENERAL_TEXT_ADVERT/Zusatzinformationen")
        or description
        or title
    )
    address_lines = normalize_attribute_value((address or {}).get("addressLines"))
    if not address_lines and isinstance((address or {}).get("addressLine"), list):
        address_lines = normalize_attribute_value((address or {}).get("addressLine"))
    facts = {
        "title": title,
        "canonical_url": canonical_url,
        "headline_hook": headline_hook,
        "description": description,
        "rooms": rooms,
        "rooms_label": rooms_label or (f"{rooms:g} Zimmer" if rooms is not None else ""),
        "area_sqm": area,
        "area_label": area_label or (f"{area:g} m²" if area is not None else ""),
        "total_rent_eur": total_rent,
        "availability": availability,
        "teaser_attributes": teaser_labels,
        "address_lines": address_lines,
        "postal_code": as_text((address or {}).get("postCode")),
        "postal_name": as_text((address or {}).get("postalName")),
        "country": as_text((address or {}).get("country")),
        "organisation_name": as_text((organisation or {}).get("orgName")),
        "organisation_phone": as_text((organisation or {}).get("orgPhone")),
        "organisation_email": as_text((organisation or {}).get("orgEmail")),
        "attribute_map": attributes,
        "photo_count": len(photos),
        "floorplan_count": len(floorplans),
    }
    return {
        "source": "willhaben",
        "property_url": canonical_url,
        "listing_id": as_text(advert.get("id")),
        "listing_uuid": as_text(advert.get("uuid")),
        "title": title,
        "description": description,
        "address_lines": address_lines,
        "property_facts_json": facts,
        "media_urls_json": [entry["url"] for entry in photos],
        "floorplan_urls_json": [entry["url"] for entry in floorplans],
        "media_assets_json": assets,
        "tour_variants_json": build_variants(title=title, floorplan_count=len(floorplans), photo_count=len(photos), facts=facts),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Willhaben property packets for the Crezlo tour workflow.")
    parser.add_argument("urls", nargs="*", help="Willhaben property URLs.")
    parser.add_argument("--url-file", help="Optional newline-delimited URL file.")
    parser.add_argument("--output", help="Optional path for JSON output.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    return parser.parse_args(argv)


def load_urls(args: argparse.Namespace) -> list[str]:
    urls = [str(url or "").strip() for url in args.urls if str(url or "").strip()]
    if args.url_file:
        with open(args.url_file, "r", encoding="utf-8") as handle:
            for raw in handle:
                url = raw.strip()
                if url:
                    urls.append(url)
    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        normalized = urllib.parse.urldefrag(url)[0]
        if normalized not in seen:
            deduped.append(normalized)
            seen.add(normalized)
    if not deduped:
        raise SystemExit("willhaben_urls_required")
    return deduped


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    payload = [summarize_listing(url) for url in load_urls(args)]
    text = json.dumps(payload, ensure_ascii=True, indent=2 if args.pretty else None)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.write("\n")
    else:
        sys.stdout.write(text)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
