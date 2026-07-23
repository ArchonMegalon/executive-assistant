#!/usr/bin/env python3
"""Issue one short-lived, fragment-only Manfred voice-review bootstrap link."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import urllib.parse


REPO_ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = REPO_ROOT / "ea"
if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))

from app.api.routes import public_memorials  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Issue a short-lived Manfred conversation-review URL. The bearer "
            "credential is carried only in the URL fragment and is exchanged "
            "for an HttpOnly review-session cookie."
        )
    )
    parser.add_argument(
        "--ttl-seconds",
        type=int,
        default=public_memorials._MEMORIAL_VOICE_REVIEW_BOOTSTRAP_TTL_SECONDS,
        help="Bootstrap lifetime from 60 to 1800 seconds (default: 1800).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        token = public_memorials._issue_memorial_voice_review_bootstrap_token(
            ttl_seconds=args.ttl_seconds,
        )
        context = public_memorials._memorial_voice_review_context()
        if context is None:
            raise RuntimeError("memorial_voice_review_context_unavailable")
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from None
    public_origin = context[1]
    fragment_token = urllib.parse.quote(token, safe="._-")
    print(
        f"{public_origin}/admin/memorials/manfred/voice-review"
        f"#token={fragment_token}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
