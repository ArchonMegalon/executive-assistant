from __future__ import annotations

import json
from pathlib import Path


def test_load_questions_defaults_when_empty() -> None:
    import scripts.memorial_demo_rehearsal as rehearsal

    questions, difficult = rehearsal.load_questions("")
    assert questions
    assert "Schuld" in difficult or "schuld" in difficult.lower()


def test_load_questions_from_file(tmp_path: Path) -> None:
    import scripts.memorial_demo_rehearsal as rehearsal

    path = tmp_path / "questions.json"
    path.write_text(json.dumps({"questions": ["A?", "B?"], "difficult_question": "C?"}), encoding="utf-8")

    questions, difficult = rehearsal.load_questions(str(path))

    assert questions == ["A?", "B?"]
    assert difficult == "C?"


def test_rehearsal_report_status() -> None:
    import scripts.memorial_demo_rehearsal as rehearsal

    report = rehearsal.RehearsalReport(slug="manfred", base_url="https://example.test")
    report.add("pass", "ok", "ok")
    assert report.as_dict()["status"] == "pass"
    report.add("warn", "warn", "warn")
    assert report.as_dict()["status"] == "warn"
    report.add("fail", "fail", "fail")
    assert report.as_dict()["status"] == "fail"
