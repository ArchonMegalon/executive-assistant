from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ea"))
from app.services.dispatch_draft_adapters.syllabbles_adapter import DispatchDraftRequest, create_dispatch_drafts


def test_syllabbles_dispatch_draft_lane_keeps_fact_backed_public_safe_drafts() -> None:
    drafts = create_dispatch_drafts(
        DispatchDraftRequest(
            world_id="emerald-sprawl-prelude",
            turn=1,
            source_receipt_ids=("ledger_tick_0001_preseeded",),
            facts=(
                "Rust Bazaar called in old favors before sunrise.",
                "Ashline pressure pulled package demand toward awakened build support.",
                "Ghostline suppressed two rumor lanes before they became package truth.",
            ),
            forbidden_claims=("private campaign data", "sourcebook text"),
            output_count=3,
        )
    )

    assert len(drafts) == 3
    for draft in drafts:
        assert draft.tool == "syllabbles"
        assert "public-safe seeded preview" in draft.body_markdown
        assert "Rust Bazaar called in old favors before sunrise." in draft.body_markdown
        assert not draft.unsupported_claims_detected
