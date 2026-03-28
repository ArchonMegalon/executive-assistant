from app.product.extractors import extract_commitment_candidates


def test_extract_commitment_candidates_normalizes_by_eod_deadline() -> None:
    candidates = extract_commitment_candidates(
        "Send revised board packet to Sofia by EOD.",
        counterparty="Sofia N.",
        reference_at="2026-03-28T10:15:00+00:00",
    )

    assert candidates
    assert candidates[0].title == "Revised board packet to Sofia"
    assert candidates[0].suggested_due_at == "2026-03-28T17:00:00+00:00"


def test_extract_commitment_candidates_normalizes_tomorrow_morning_deadline() -> None:
    candidates = extract_commitment_candidates(
        "Please reply to Sofia tomorrow morning.",
        counterparty="Sofia N.",
        reference_at="2026-03-28T18:15:00+00:00",
    )

    assert candidates
    assert candidates[0].title == "Reply to Sofia"
    assert candidates[0].suggested_due_at == "2026-03-29T09:00:00+00:00"
