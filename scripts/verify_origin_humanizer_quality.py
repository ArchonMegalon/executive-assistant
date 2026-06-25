#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any


CONTRACT_NAME = "chummer.origin_dossier.humanizer_quality_gate.v1"
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'-]{2,}")
FUSED_ARTIFACT_RE = re.compile(
    r"\b(?:"
    r"onlyto|usedtoread|butnow|butnowitwasall|allsorts|tobeexact|startingto|"
    r"muffledfootsteps|andeven|tohesitate|topenetrate|installing[a-z]+|"
    r"maketheirpresenceknown|voicewashuge|atinything|somethingyou|"
    r"financialtroubles|droppedslightly|urgedher|toreact|sheknewthat|"
    r"itdidn|thebest|payattention|won'tstop|youre?noteven|"
    r"seemedto|didn'?tneedto|otherstodo|umbrella'?sclarity|"
    r"raindropslooklike|repelthe|somehowseemed|gaveher|"
    r"bloodseeping|hednever|memoriesofher|floodedhermind|"
    r"frustratedcurses|urgedkestreltoleave|alesson|hardway|"
    r"outweighsthe|itstimeto|become|justamoment|wholescene|"
    r"wasyelling|malfunctionedandher|weresuddenlyarmed|theirguns|"
    r"appearingoutofnowhere|reactedquickly|butshewasn|shetargeted|"
    r"blowingit|slammedinto|andgrabbed|haulingherselfup|"
    r"wasn'?tthesame|that'?swhatshe|managedto|thesudden|"
    r"butshegritted|rainslashing|brightlights|headingstraight|"
    r"havelosthislife|hadn'?tevenrealized|caredabout"
    r")\b",
    re.IGNORECASE,
)
PROVIDER_PREAMBLE_RE = re.compile(
    r"\b(?:there\s+is\s+no\s+story\s+provided|please\s+provide\s+the\s+input\s+text|"
    r"here(?:'s| is)\s+(?:a|the)\s+(?:humanized|rewritten)|"
    r"i\s+(?:have|will)\s+(?:humanized|rewritten))\b",
    re.IGNORECASE,
)
CANON_ANCHORS = (
    "Kestrel",
    "Vela",
    "Cale",
    "Mako",
    "reflex booster",
    "ledger",
    "Nobody gets sold",
    "Nobody gets left in the rain",
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tokens(text: str) -> list[str]:
    return [token.lower().strip("'") for token in TOKEN_RE.findall(text)]


def _content_tokens(text: str) -> set[str]:
    stop = {
        "the",
        "and",
        "that",
        "with",
        "for",
        "was",
        "were",
        "had",
        "her",
        "his",
        "she",
        "him",
        "you",
        "not",
        "but",
        "from",
        "this",
        "then",
        "they",
        "there",
        "inside",
        "outside",
    }
    return {token for token in _tokens(text) if token not in stop and len(token) >= 4}


def _word_count(text: str) -> int:
    return len(_tokens(text))


def _missing_anchors(candidate: str) -> list[str]:
    lowered = candidate.lower()
    return [anchor for anchor in CANON_ANCHORS if anchor.lower() not in lowered]


def evaluate(source_text: str, candidate_text: str) -> dict[str, Any]:
    source = source_text.strip()
    candidate = candidate_text.strip()
    source_words = _word_count(source)
    candidate_words = _word_count(candidate)
    length_ratio = candidate_words / max(1, source_words)
    source_content = _content_tokens(source)
    candidate_content = _content_tokens(candidate)
    overlap_count = len(source_content & candidate_content)
    overlap_ratio = overlap_count / max(1, len(source_content))
    fused = FUSED_ARTIFACT_RE.findall(candidate)
    preamble = PROVIDER_PREAMBLE_RE.findall(candidate)
    missing = _missing_anchors(candidate)
    issues: list[str] = []
    if not candidate:
        issues.append("candidate_empty")
    if candidate_words < 80:
        issues.append("candidate_too_short")
    if length_ratio < 0.72 or length_ratio > 1.45:
        issues.append("length_ratio_out_of_bounds")
    if overlap_ratio < 0.52:
        issues.append("source_token_overlap_too_low")
    if missing:
        issues.append("canon_anchors_missing")
    if preamble:
        issues.append("provider_preamble_detected")
    fused_rate = len(fused) / max(1, candidate_words) * 1000
    if len(fused) > 0 and fused_rate > 1.5:
        issues.append("fused_spacing_artifacts_detected")
    if re.search(r"[a-z][.!?][A-Z]", candidate):
        issues.append("sentence_boundary_spacing_missing")
    if re.search(r"\b[a-z]{18,}\b", candidate):
        issues.append("suspicious_long_lowercase_token")
    status = "pass" if not issues else "failed_quality_gate"
    return {
        "status": status,
        "goldEligible": status == "pass",
        "issues": issues,
        "metrics": {
            "sourceWordCount": source_words,
            "candidateWordCount": candidate_words,
            "lengthRatio": round(length_ratio, 4),
            "sourceContentTokenCount": len(source_content),
            "candidateContentTokenCount": len(candidate_content),
            "sourceContentOverlapCount": overlap_count,
            "sourceContentOverlapRatio": round(overlap_ratio, 4),
            "fusedArtifactCount": len(fused),
            "fusedArtifactsPerThousandWords": round(fused_rate, 4),
            "providerPreambleCount": len(preamble),
        },
        "findings": {
            "missingCanonAnchors": missing,
            "fusedArtifactSamples": sorted(set(match.lower() for match in fused))[:20],
            "providerPreambleSamplesSha256": [
                _sha256_bytes(str(match).lower().encode("utf-8")) for match in preamble[:5]
            ],
        },
    }


def build_receipt(*, source_path: Path, candidate_path: Path) -> dict[str, Any]:
    if not source_path.is_file():
        return {
            "contractName": CONTRACT_NAME,
            "status": "blocked",
            "goldEligible": False,
            "issues": ["source_file_missing"],
            "createdAtUtc": _now_iso(),
        }
    if not candidate_path.is_file():
        return {
            "contractName": CONTRACT_NAME,
            "status": "blocked",
            "goldEligible": False,
            "issues": ["candidate_file_missing"],
            "sourceTextSha256": _sha256_file(source_path),
            "createdAtUtc": _now_iso(),
        }
    source = source_path.read_text(encoding="utf-8")
    candidate = candidate_path.read_text(encoding="utf-8")
    evaluation = evaluate(source, candidate)
    return {
        "contractName": CONTRACT_NAME,
        "provider": "Undetectable Humanizer",
        "operation": "humanizer_quality_gate",
        "sourcePath": str(source_path),
        "candidatePath": str(candidate_path),
        "sourceTextSha256": _sha256_file(source_path),
        "candidateTextSha256": _sha256_file(candidate_path),
        "rawCredentialExposed": False,
        "rawProviderTokenExposed": False,
        "createdAtUtc": _now_iso(),
        **evaluation,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Chummer Origin humanizer output quality.")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    receipt = build_receipt(source_path=args.source, candidate_path=args.candidate)
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt.get("status") == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
