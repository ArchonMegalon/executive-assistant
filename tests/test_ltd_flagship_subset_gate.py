from __future__ import annotations

from scripts.verify_ltd_flagship_subset import build_receipt


def test_ltd_flagship_subset_gate_passes_for_expected_verified_subset() -> None:
    markdown = """
## Discovery Tracking

| Service | Account / Email | Discovery Status | Verification Source | Last Verified | Notes |
|---|---|---|---|---|---|
| `1min.AI` |  | `manual_seeded` | `local_env_browseract_refresh` | 2026-06-02T18:17:17Z | ok |
| `Prompt Architects` |  | `manual_seeded` | `local_env + prompt_foundry_receipts` | 2026-06-01T20:54:48Z | ok |
| `PayFunnels` |  | `manual_seeded` | `payfunnels_test_billing_receipts` | 2026-06-01T00:00:00Z | ok |
| `BrowserAct` | ops@example.com | `complete` | `browseract_live` | 2026-03-07T00:00:00Z | ok |
| `Teable` | ops@teable.example | `complete` | `browseract_live` | 2026-03-07T00:01:00Z | ok |
| `ClickRank.ai` | ops@example.com | `complete` | `clickrank_live` | 2026-05-04T07:44:00Z | ok |
| `Emailit` |  | `manual_seeded` | `emailit_api_live` | 2026-05-01T05:00:00Z | ok |
| `Pixefy` | ops@example.com | `manual_seeded` | `fleet_verified` | 2026-05-29T20:16:00Z | ok |
| `Rafter` | ops@example.com | `manual_seeded` | `fleet_verified` | 2026-05-29T20:16:00Z | ok |
""".strip()

    receipt = build_receipt(markdown_text=markdown)

    assert receipt["status"] == "pass"
    assert receipt["accepted_total"] == 9
    assert receipt["failures"] == []


def test_ltd_flagship_subset_gate_fails_closed_on_missing_or_wrong_sources() -> None:
    markdown = """
## Discovery Tracking

| Service | Account / Email | Discovery Status | Verification Source | Last Verified | Notes |
|---|---|---|---|---|---|
| `BrowserAct` | ops@example.com | `complete` | `browseract_live` | 2026-03-07T00:00:00Z | ok |
| `Teable` | ops@teable.example | `missing` | `manual_inventory` |  | wrong |
""".strip()

    receipt = build_receipt(markdown_text=markdown)

    assert receipt["status"] == "fail"
    assert "flagship_subset_mismatch:Teable:missing:manual_inventory" in receipt["failures"]
    assert "flagship_subset_mismatch:Prompt Architects:missing:missing" in receipt["failures"]
    assert "flagship_subset_coverage_below_floor:1<9" in receipt["failures"]
