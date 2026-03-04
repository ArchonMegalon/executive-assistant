from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLL = ROOT / "ea/app/poll_listener.py"


def main() -> int:
    src = POLL.read_text(encoding="utf-8")
    assert "def _validate_newspaper_pdf_bytes" in src
    assert "min_pages=4" in src
    assert "min_images=3" in src
    assert "brief_newspaper_pdf_quality_gate_failed" in src
    print("PASS: newspaper pdf quality gate wiring smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
