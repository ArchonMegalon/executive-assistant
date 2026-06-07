from __future__ import annotations

import json
from pathlib import Path


class _Response:
    def __init__(self, body: bytes) -> None:
        self.status = 200
        self.headers = {"Content-Type": "application/json"}
        self._body = body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


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


def test_request_retries_after_timeout(monkeypatch) -> None:
    import scripts.memorial_demo_rehearsal as rehearsal

    calls = {"count": 0}

    def _fake_urlopen(request, timeout):
        del request, timeout
        calls["count"] += 1
        if calls["count"] == 1:
            raise TimeoutError("timed out")
        return _Response(b'{"status":"ok"}')

    monkeypatch.setattr(rehearsal.urllib.request, "urlopen", _fake_urlopen)

    status, _, raw = rehearsal.request("https://example.test/api", retries=1)

    assert calls["count"] == 2
    assert status == 200
    assert raw == b'{"status":"ok"}'
