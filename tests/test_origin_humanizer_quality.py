from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "verify_origin_humanizer_quality.py"


def load_module():
    spec = importlib.util.spec_from_file_location("verify_origin_humanizer_quality", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SOURCE = """
Rain made the clinic sign stutter. Kestrel watched the last red letter die, come back wrong, then die again.
Vela opened the clinic door and warned her that the reflex booster would help her react, not make her bulletproof.
Cale waited in the alley for collateral, while Mako ran with the stolen ledger.
Kestrel crossed the roofline toward the courier and the rule she had not known she believed.
Nobody gets sold. Nobody gets left in the rain.
""" * 8


def test_humanizer_quality_accepts_source_bound_story_rewrite(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source.md"
    candidate = tmp_path / "candidate.md"
    source.write_text(SOURCE, encoding="utf-8")
    candidate.write_text(
        """
Rain made the clinic sign stutter while Kestrel watched the last red letter fail, return wrong, and fail again.
Vela opened the door and reminded her that the reflex booster could sharpen reaction, not make her bulletproof.
Cale waited in the alley for collateral, and Mako kept moving with the stolen ledger.
Kestrel crossed the roofline toward the courier and toward the rule she had only just admitted mattered.
Nobody gets sold. Nobody gets left in the rain.
""" * 8,
        encoding="utf-8",
    )

    receipt = module.build_receipt(source_path=source, candidate_path=candidate)

    assert receipt["status"] == "pass"
    assert receipt["goldEligible"] is True
    assert receipt["issues"] == []


def test_humanizer_quality_rejects_fused_spacing_artifacts(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source.md"
    candidate = tmp_path / "candidate.md"
    source.write_text(SOURCE, encoding="utf-8")
    candidate.write_text(
        (
            "Rain made the clinic sign stutter. Kestrel stoodthere while the sign usedtoread WALK-INS WELCOME, "
            "butnowitwasallmessedup. Vela's voicewashuge, Mako was headingstraight for the ledger, "
            "and Cale didn'tneedto yell. Nobody gets sold. Nobody gets left in the rain. "
        )
        * 12,
        encoding="utf-8",
    )

    receipt = module.build_receipt(source_path=source, candidate_path=candidate)

    assert receipt["status"] == "failed_quality_gate"
    assert "fused_spacing_artifacts_detected" in receipt["issues"]


def test_humanizer_quality_rejects_provider_preamble(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source.md"
    candidate = tmp_path / "candidate.md"
    source.write_text(SOURCE, encoding="utf-8")
    candidate.write_text("There is no story provided to humanize. Please provide the input text to be rewritten. " + SOURCE, encoding="utf-8")

    receipt = module.build_receipt(source_path=source, candidate_path=candidate)

    assert receipt["status"] == "failed_quality_gate"
    assert "provider_preamble_detected" in receipt["issues"]


def test_humanizer_quality_rejects_missing_canon_anchors(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source.md"
    candidate = tmp_path / "candidate.md"
    source.write_text(SOURCE, encoding="utf-8")
    candidate.write_text(("Rain crossed a doorway. A stranger ran from a debt. Nobody got left behind. " * 20), encoding="utf-8")

    receipt = module.build_receipt(source_path=source, candidate_path=candidate)

    assert receipt["status"] == "failed_quality_gate"
    assert "canon_anchors_missing" in receipt["issues"]


def test_humanizer_quality_accepts_explicit_story_anchors(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source.md"
    candidate = tmp_path / "candidate.md"
    aster_story = (
        "Aster crossed Lantern Reach with Jun, Mara, and Orin while Halcyon Freight watched the Tideglass route. "
        "The community kept medicine and flood rescue moving through Glass Harbor. "
    ) * 20
    source.write_text(aster_story, encoding="utf-8")
    candidate.write_text(aster_story, encoding="utf-8")

    receipt = module.build_receipt(
        source_path=source,
        candidate_path=candidate,
        canon_anchors=("Aster", "Jun", "Mara", "Orin", "Lantern Reach", "Halcyon Freight"),
    )

    assert receipt["status"] == "pass"
    assert receipt["findings"]["missingCanonAnchors"] == []


def test_humanizer_quality_does_not_treat_become_as_a_fused_token() -> None:
    module = load_module()
    evaluation = module.evaluate(
        ("Aster and Jun become careful route planners for Lantern Reach. " * 20),
        ("Aster and Jun become careful route planners for Lantern Reach. " * 20),
        canon_anchors=("Aster", "Jun", "Lantern Reach"),
    )

    assert evaluation["metrics"]["fusedArtifactCount"] == 0
    assert "fused_spacing_artifacts_detected" not in evaluation["issues"]


def test_humanizer_quality_rejects_too_short_candidate(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source.md"
    candidate = tmp_path / "candidate.md"
    source.write_text(SOURCE, encoding="utf-8")
    candidate.write_text("Rain made the clinic sign stutter. Kestrel ran.", encoding="utf-8")

    receipt = module.build_receipt(source_path=source, candidate_path=candidate)

    assert receipt["status"] == "failed_quality_gate"
    assert "candidate_too_short" in receipt["issues"]
