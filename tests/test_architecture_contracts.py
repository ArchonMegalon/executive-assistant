from __future__ import annotations

from app.domain.office.surfaces import OfficeSurfacePayload
from app.services import release_materialization_service
from app.services.memorial_turn_service import transcribe_public_memorial_audio


def test_office_surface_payload_roundtrip_preserves_core_contracts() -> None:
    payload = OfficeSurfacePayload.from_mapping(
        {
            "title": "Morning Memo",
            "summary": "What changed first.",
            "stats": [{"label": "Queue items", "value": "4"}],
            "cards": [
                {
                    "eyebrow": "Top priorities",
                    "title": "What deserves attention first",
                    "body": "Start on the ranked work.",
                    "items": [{"title": "Follow up", "detail": "Board chair", "tag": "Priority"}],
                }
            ],
            "console_form": {"kind": "capture"},
            "activation_banner": {"body": "Open Today first."},
        }
    )

    rendered = payload.as_template_payload()

    assert rendered["title"] == "Morning Memo"
    assert rendered["summary"] == "What changed first."
    assert rendered["stats"] == [{"label": "Queue items", "value": "4"}]
    assert rendered["cards"][0]["title"] == "What deserves attention first"
    assert rendered["console_form"] == {"kind": "capture"}
    assert rendered["activation_banner"] == {"body": "Open Today first."}


def test_release_materialization_service_runs_expected_scripts_in_order(monkeypatch) -> None:
    calls: list[tuple[str, tuple[str, ...], dict[str, str] | None]] = []

    def fake_run_python(*, python_bin: str, command: list[str], extra_env: dict[str, str] | None = None) -> None:
        calls.append((python_bin, tuple(command), extra_env))

    monkeypatch.setattr(release_materialization_service, "_run_python", fake_run_python)

    release_materialization_service.materialize_release_assets(python_bin="/tmp/python")

    assert calls[0] == ("/tmp/python", ("scripts/materialize_ea_browser_workflow_proof.py",), None)
    assert calls[-1] == ("/tmp/python", ("scripts/materialize_memorial_operator_status.py",), None)
    assert any(command == ("scripts/materialize_whole_project_gold_map.py",) and env == {"PYTHONPATH": "ea"} for _, command, env in calls)


def test_transcribe_public_memorial_audio_preserves_visible_transcript() -> None:
    class Shared:
        @staticmethod
        def _memorial_transcribe_audio_blob(*, payload: bytes, content_type: str) -> dict[str, object]:
            return {
                "transcript_text": "Hallo Manfred, kannst du jetzt mit mir sprechen?",
                "transcription_status": "transcribed",
                "transcriber": "stub",
            }

        @staticmethod
        def _text(value: object, default: str = "") -> str:
            return str(value or default)

        @staticmethod
        def _canonical_memorial_contact_opening_question(text: str) -> str:
            return "Worum geht es?" if text else ""

        @staticmethod
        def _memorial_visible_transcript_text(*, transcript_text: str, effective_question: str) -> str:
            return transcript_text

    result = transcribe_public_memorial_audio(shared=Shared, payload=b"audio", content_type="audio/wav").as_public_payload()

    assert result["transcript_text"] == "Worum geht es?"
    assert result["transcript_effective_text"] == "Worum geht es?"
    assert result["transcript_original_text"] == "Hallo Manfred, kannst du jetzt mit mir sprechen?"
