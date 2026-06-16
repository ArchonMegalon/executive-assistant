from __future__ import annotations

from scripts import mine_memorial_transcript_signals as miner


def _obs(*, created_at: str, source_id: str, title: str, summary: str = "", transcript: str = "", excerpt: str = "") -> miner.TranscriptObservation:
    return miner.TranscriptObservation(
        created_at=created_at,
        source_id=source_id,
        title=title,
        summary=summary,
        transcript=transcript,
        excerpt=excerpt,
    )


def test_query_observations_falls_back_to_archive_when_db_unavailable(monkeypatch) -> None:
    archive_obs = [
        _obs(
            created_at="2026-06-11T10:00:00Z",
            source_id="rec-tribute",
            title="Tribute to Manfred and Justice",
            transcript="Seine Leidenschaft fuer Gerechtigkeit blieb bis zuletzt spuerbar.",
        )
    ]

    monkeypatch.setattr(miner, "_load_env_defaults", lambda: None)
    monkeypatch.setattr(miner, "_query_db_observations", lambda slug: (_ for _ in ()).throw(RuntimeError("db_down")))
    monkeypatch.setattr(miner, "_query_archive_observations", lambda slug: archive_obs)

    rows = miner._query_observations("manfred")
    assert len(rows) == 1
    assert rows[0].title == "Tribute to Manfred and Justice"


def test_build_report_extracts_funeral_and_justice_signals_from_archive_fallback(monkeypatch) -> None:
    observations = [
        _obs(
            created_at="2026-06-11T10:00:00Z",
            source_id="rec-tribute",
            title="Tribute to Manfred and Justice",
            summary="The tribute frames Manfred as someone who cared about justice in lived reality, not only in theory.",
            transcript=(
                "Seine Leidenschaft fuer Gerechtigkeit fuehrte ihn zum Jusstudium. "
                "Aber Theorie reichte ihm nicht; er sah, dass Recht nicht immer recht gelebt wird."
            ),
        ),
        _obs(
            created_at="2026-06-03T10:00:00Z",
            source_id="rec-funeral",
            title="Family discussion about funeral arrangements",
            transcript=(
                "Wegen des Begraebnisses hat sie mich gefragt. "
                "Der Friedhof hat nur Dienstag und Donnerstag Zeiten und ich moechte einen Kranz widmen."
            ),
        ),
    ]

    monkeypatch.setattr(miner, "_query_observations", lambda slug: observations)

    report = miner.build_report("manfred")
    labels = {item["label"] for item in report["signals"]}
    assert "justice_as_lived_principle_not_theory" in labels
    assert "grief_managed_through_logistics_and_duty" in labels
    assert report["observation_count"] == 2
    assert report["titles_seen"][0] == "Tribute to Manfred and Justice"
