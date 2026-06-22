from __future__ import annotations

from pathlib import Path


def test_public_memorial_family_mail_copy_does_not_embed_named_child_example() -> None:
    source = (Path(__file__).resolve().parents[1] / "ea" / "app" / "api" / "routes" / "public_memorials.py").read_text(
        encoding="utf-8"
    )
    named_example = "Lieber " + "Tibor"

    assert named_example not in source
    assert "knappe Anreden mit einem kurzen Dank" in source
