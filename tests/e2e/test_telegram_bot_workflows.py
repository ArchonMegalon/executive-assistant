from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import zipfile
from zoneinfo import ZoneInfo

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def _client(*, principal_id: str) -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = ""
    os.environ.pop("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", None)
    os.environ.pop("EA_OPERATOR_PRINCIPAL_IDS", None)
    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"X-EA-Principal-ID": principal_id})
    return client


@pytest.fixture(autouse=True)
def _enable_legacy_runtime_surfaces(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_ENABLE_LEGACY_RUNTIME_SURFACES", "1")


class _TelegramScenarioAgent:
    def __init__(self, client: TestClient, *, secret: str, chat_id: int | str = 1354554303):
        self.client = client
        self.secret = secret
        self.chat_id = chat_id
        self._message_id = 9000

    def ask(self, text: str) -> dict[str, object]:
        self._message_id += 1
        return self.send_message_payload({"text": text})

    def send_message_payload(self, payload: dict[str, object]) -> dict[str, object]:
        response = self.client.post(
            "/v1/channels/telegram/ingest",
            headers={"X-Telegram-Bot-Api-Secret-Token": self.secret},
            json={
                "message": {
                    "message_id": self._message_id,
                    "date": 123 + self._message_id,
                    "chat": {"id": self.chat_id, "type": "private"},
                    **payload,
                }
            },
        )
        assert response.status_code == 200
        return response.json()

    def send_callback_query(self, payload: dict[str, object]) -> dict[str, object]:
        response = self.client.post(
            "/v1/channels/telegram/ingest",
            headers={"X-Telegram-Bot-Api-Secret-Token": self.secret},
            json={"callback_query": dict(payload)},
        )
        assert response.status_code == 200
        return response.json()


def test_telegram_bot_workflow_routes_documents_photos_and_ltd_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_TELEGRAM_INGEST_SECRET", "tg-secret")
    monkeypatch.setenv("EA_TELEGRAM_AUTO_BIND_UNKNOWN_CHAT", "1")
    monkeypatch.setenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID", "exec-telegram-e2e-routing")
    monkeypatch.setenv("EA_TELEGRAM_BOT_HANDLE", "ea_concierge_bot")
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token-e2e-routing")
    monkeypatch.setenv("EA_ANSWERLY_ONEDRIVE_API_KEY", "onedrive-key")
    monkeypatch.setenv("EA_ANSWERLY_ONEDRIVE_AGENT_ID", "onedrive-agent")
    monkeypatch.setenv("EA_ANSWERLY_ONEDRIVE_LABEL", "OneDrive documents")
    monkeypatch.setenv("EA_ANSWERLY_SHAREONE_API_KEY", "shareone-key")
    monkeypatch.setenv("EA_ANSWERLY_SHAREONE_AGENT_ID", "shareone-agent")
    monkeypatch.setenv("EA_ANSWERLY_SHAREONE_LABEL", "ShareOne documents")
    from app.api.routes import channels as channels_route
    from app.domain.models import ToolInvocationResult

    sent: list[dict[str, object]] = []
    answerly_calls: list[dict[str, object]] = []
    executed_requests = []

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": 9901}}).encode("utf-8")

    def _fake_urlopen(request, timeout=30):
        sent.append(json.loads(request.data.decode("utf-8")))
        return _FakeResponse()

    class _Account:
        def __init__(self):
            self.token_status = "active"
            self.binding = type("Binding", (), {"status": "enabled"})()
            self.granted_scopes = [channels_route.google_oauth_service.GOOGLE_SCOPE_PHOTOS_PICKER]
            self.google_email = "principal@example.test"

    def _fake_answerly_chat(*, config, message, conversation_id=""):
        answerly_calls.append({"scope": config["scope"], "label": config["label"], "message": message})
        if config["scope"] == "onedrive":
            if "birth certificate" in message.lower():
                return {
                    "status": True,
                    "data": {
                        "messages": ["Noah Girschele's birth certificate is in the OneDrive document vault."],
                        "actionResponse": {"name": "conversational"},
                        "meta": {"source": [{"dataItemId": "onedrive-birth-cert-1"}]},
                    },
                }
            if "medication" in message.lower():
                return {
                    "status": True,
                    "data": {
                        "messages": ["Your medication is currently listed in the bedside drawer medication organizer."],
                        "actionResponse": {"name": "conversational"},
                        "meta": {"source": [{"dataItemId": "onedrive-medication-1"}]},
                    },
                }
            return {
                "status": True,
                "data": {
                    "messages": ["The OneDrive rehab approval confirms Rosenhügel NRZ and says the KfA authorization is active."],
                    "actionResponse": {"name": "conversational"},
                    "meta": {"source": [{"dataItemId": "onedrive-kfa-1"}]},
                },
            }
        return {
            "status": True,
            "data": {
                "messages": ["The ShareOne school packet says Noah still needs one follow-up form."],
                "actionResponse": {"name": "conversational"},
                "meta": {"source": [{"dataItemId": "shareone-school-1"}]},
            },
        }

    def _fake_execute(request):  # noqa: ANN001
        executed_requests.append(request)
        return ToolInvocationResult(
            tool_name=request.tool_name,
            action_kind=request.action_kind,
            target_ref="provider://onemin/background-remove",
            output_json={"ok": True},
            receipt_json={"principal_id": request.context_json["principal_id"]},
        )

    monkeypatch.setattr(channels_route.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(channels_route, "_answerly_chat", _fake_answerly_chat)
    monkeypatch.setattr(
        channels_route,
        "resolve_telegram_message_payload",
        lambda **kwargs: {
            **dict(kwargs.get("payload") or {}),
            "text": (
                "Can you start the photo picker now?"
                if str(dict(kwargs.get("payload") or {}).get("kind") or "").strip().lower() == "voice"
                else str(dict(kwargs.get("payload") or {}).get("text") or "")
            ),
            "transcription_status": (
                "ok" if str(dict(kwargs.get("payload") or {}).get("kind") or "").strip().lower() == "voice" else ""
            ),
        },
    )
    monkeypatch.setattr(channels_route.google_oauth_service, "list_google_accounts", lambda **kwargs: [_Account()])
    monkeypatch.setattr(
        channels_route,
        "_telegram_ltd_runtime_profiles",
        lambda container: [
            SimpleNamespace(
                service_name="1min.AI",
                runtime_state="provider_executable",
                workspace_integration_tier="Tier 1",
                aliases=("1min ai",),
                actions=(
                    SimpleNamespace(
                        action_key="background_remove",
                        route_path="/v1/ltds/runtime-catalog/1min.AI/actions/background_remove",
                        executable=True,
                        description="Remove the background from an image.",
                        tool_name="provider.onemin.media_transform",
                        action_kind="media_transform",
                    ),
                ),
            ),
        ],
    )

    class _FakeCatalog:
        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setattr(channels_route, "LtdRuntimeCatalogService", _FakeCatalog)
    monkeypatch.setattr(
        channels_route,
        "projected_task_key_for_request",
        lambda **kwargs: channels_route.projected_task_key("1min.AI", "background_remove")
        if "1min.ai" in str(kwargs.get("goal") or "").lower()
        else "",
    )

    client = _client(principal_id="")
    monkeypatch.setattr(client.app.state.container.tool_execution, "execute_invocation", _fake_execute)
    agent = _TelegramScenarioAgent(client, secret="tg-secret")

    onedrive = agent.ask("What does the latest OneDrive KfA rehab approval say?")
    assert onedrive["reply_sent"] is True
    assert "OneDrive rehab approval confirms Rosenhügel NRZ" in onedrive["reply_text"]
    assert answerly_calls[-1]["scope"] == "onedrive"

    birth_certificate = agent.ask("Send me the birth certificate of Noah Girschele.")
    assert birth_certificate["reply_sent"] is True
    assert "Noah Girschele's birth certificate is in the OneDrive document vault." in birth_certificate["reply_text"]
    assert answerly_calls[-1]["scope"] == "onedrive"

    medication = agent.ask("Where is my medication right now?")
    assert medication["reply_sent"] is True
    assert "Your medication is currently listed in the bedside drawer medication organizer." in medication["reply_text"]
    assert answerly_calls[-1]["scope"] == "onedrive"

    ambiguous = agent.ask("Search the documents for the rehab approval.")
    assert ambiguous["reply_sent"] is True
    assert "Your document backends stay separated." in ambiguous["reply_text"]

    shareone = agent.ask("Search ShareOne documents for the school paperwork.")
    assert shareone["reply_sent"] is True
    assert "ShareOne school packet says Noah still needs one follow-up form." in shareone["reply_text"]
    assert answerly_calls[-1]["scope"] == "shareone"

    photos = agent.ask("You should have access to my Google photos. Can you find me the picture where Noah is sleeping on a mattress?")
    assert photos["reply_sent"] is True
    assert "only on photos you explicitly select in the picker" in photos["reply_text"]

    agent._message_id += 1
    voice = agent.send_message_payload({"voice": {"file_id": "voice-file-1", "duration": 8}})
    assert voice["reply_sent"] is True
    assert "Google Photos Picker access is connected" in voice["reply_text"] or "Google Photos Picker is ready" in voice["reply_text"]

    image = agent.ask("Use 1min.AI to remove the background from https://example.invalid/cat.png")
    assert image["reply_sent"] is True
    assert "Executed 1min.AI background_remove." in image["reply_text"]
    assert executed_requests[-1].payload_json["image_url"] == "https://example.invalid/cat.png"
    assert len(sent) >= 5


def test_telegram_bot_workflow_media_prompts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_TELEGRAM_INGEST_SECRET", "tg-secret")
    monkeypatch.setenv("EA_TELEGRAM_AUTO_BIND_UNKNOWN_CHAT", "1")
    monkeypatch.setenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID", "exec-telegram-e2e-media")
    monkeypatch.setenv("EA_TELEGRAM_BOT_HANDLE", "ea_concierge_bot")
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token-e2e-media")

    from app.api.routes import channels as channels_route

    sent: list[dict[str, object]] = []
    scheduled: list[dict[str, object]] = []

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": 9901}}).encode("utf-8")

    def _fake_urlopen(request, timeout=30):
        sent.append(json.loads(request.data.decode("utf-8")))
        return _FakeResponse()

    monkeypatch.setattr(channels_route.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(
        channels_route,
        "resolve_telegram_message_payload",
        lambda **kwargs: {
            **dict(kwargs.get("payload") or {}),
            "message_metadata": {
                **dict(dict(kwargs.get("payload") or {}).get("message_metadata") or {}),
                "download_url": "https://api.telegram.org/file/bot/video-or-doc",
            },
            "video_transcript_text": (
                "Please summarize the meeting and flag action items."
                if str(dict(kwargs.get("payload") or {}).get("kind") or "").strip().lower() == "video"
                else ""
            ),
            "transcription_status": (
                "ok" if str(dict(kwargs.get("payload") or {}).get("kind") or "").strip().lower() == "video" else ""
            ),
        },
    )
    monkeypatch.setattr(channels_route, "_telegram_schedule_async_assistant_reply", lambda **kwargs: scheduled.append(kwargs))

    client = _client(principal_id="")
    agent = _TelegramScenarioAgent(client, secret="tg-secret")

    video = agent.send_message_payload({"video": {"file_id": "video-file"}})
    assert video["reply_sent"] is True
    assert "Got the video" in str(video["reply_text"])

    agent._message_id += 1
    video_with_caption = agent.send_message_payload(
        {"video": {"file_id": "video-file-caption"}, "caption": "summarize this video into action items"}
    )
    assert video_with_caption["reply_sent"] is False
    assert video_with_caption["reply_text"] == ""
    assert scheduled and dict(scheduled[-1]["async_payload"] or {})["kind"] == "instructional_video"
    assert dict(scheduled[-1]["async_payload"] or {})["instruction_text"] == "summarize this video into action items"

    agent._message_id += 1
    document = agent.send_message_payload({"document": {"file_id": "doc-file", "file_name": "travel-plan.pdf"}})
    assert document["reply_sent"] is True
    assert "Got the document" in str(document["reply_text"])

    agent._message_id += 1
    document_with_caption = agent.send_message_payload(
        {"document": {"file_id": "doc-file-caption", "file_name": "receipt.pdf"}, "caption": "please scan this"}
    )
    assert document_with_caption["reply_sent"] is True
    assert "Got the document" in str(document_with_caption["reply_text"])

    agent._message_id += 1
    plain_video = agent.send_message_payload({"video": {"file_id": "video-followup-file"}})
    assert plain_video["reply_sent"] is True
    assert "Got the video" in str(plain_video["reply_text"])

    followup = agent.ask("pull the key points and any risks from that video")
    assert followup["reply_sent"] is False
    assert followup["reply_text"] == ""
    assert dict(scheduled[-1]["async_payload"] or {})["kind"] == "instructional_video"
    assert dict(scheduled[-1]["async_payload"] or {})["instruction_text"] == "pull the key points and any risks from that video"
    assert dict(scheduled[-1]["async_payload"] or {})["video_file_id"] == "video-followup-file"

    audiobook_request = agent.ask("Audiobook plz")
    assert audiobook_request["reply_sent"] is True
    assert "Send the EPUB, AZW, AZW3, or MOBI file here in Telegram" in str(audiobook_request["reply_text"])
    assert "Pocket recording" not in str(audiobook_request["reply_text"])

    assert len(sent) == 7


def test_telegram_bot_workflow_stages_inline_proactive_task_packet(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_TELEGRAM_INGEST_SECRET", "tg-secret")
    monkeypatch.setenv("EA_TELEGRAM_AUTO_BIND_UNKNOWN_CHAT", "1")
    monkeypatch.setenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID", "exec-telegram-inline-proactive")
    monkeypatch.setenv("EA_TELEGRAM_BOT_HANDLE", "ea_concierge_bot")
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token-inline-proactive")
    monkeypatch.setenv("EA_TELEGRAM_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_PROACTIVE_OODA_SAFE_WORK_NETWORK_FETCH_ENABLED", "0")
    monkeypatch.setenv("EA_PROACTIVE_OODA_STAGE_PACKET_DIR", str(tmp_path / "stage-packets"))
    monkeypatch.setenv("EA_PROACTIVE_OODA_SAFE_WORK_RESULT_DIR", str(tmp_path / "safe-work"))
    monkeypatch.setenv("EA_PROACTIVE_OODA_STATE_PATH", str(tmp_path / "state" / "notified.json"))
    monkeypatch.setenv("EA_PROACTIVE_OODA_RECEIPT_PATH", str(tmp_path / "state" / "inline-receipt.generated.json"))

    from app.api.routes import channels as channels_route

    sent: list[dict[str, object]] = []

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": 9902}}).encode("utf-8")

    def _fake_urlopen(request, timeout=30):
        payload = json.loads(request.data.decode("utf-8"))
        sent.append(payload)
        return _FakeResponse()

    monkeypatch.setattr(channels_route.urllib.request, "urlopen", _fake_urlopen)

    client = _client(principal_id="")
    agent = _TelegramScenarioAgent(client, secret="tg-secret")

    response = agent.ask("When you find a chimney sweep, draft an email inquiry and save it for approval.")
    assert response["reply_sent"] is True
    assert "Saved. I staged this as a reversible next step." in str(response["reply_text"])
    assert "Queue: https://myexternalbrain.com/app/queue" in str(response["reply_text"])
    assert "Draft preview:" in str(response["reply_text"])

    assert len(sent) == 1
    reply_markup = dict(sent[0].get("reply_markup") or {})
    inline_keyboard = list(reply_markup.get("inline_keyboard") or [])
    assert inline_keyboard
    first_row = [dict(button) for button in inline_keyboard[0]]
    assert [button.get("text") for button in first_row] == ["Approve", "Reject", "Later"]
    assert all(str(button.get("callback_data") or "").startswith("po|") for button in first_row)

    stage_paths = list((tmp_path / "stage-packets").glob("*.json"))
    safe_work_paths = list((tmp_path / "safe-work").glob("*.json"))
    callback_paths = list((tmp_path / "state" / "proactive_ooda_approval_callbacks").glob("*.json"))
    assert len(stage_paths) == 1
    assert len(safe_work_paths) == 1
    assert len(callback_paths) == 1

    stage_packet = json.loads(stage_paths[0].read_text(encoding="utf-8"))
    safe_work_result = json.loads(safe_work_paths[0].read_text(encoding="utf-8"))
    callback_record = json.loads(callback_paths[0].read_text(encoding="utf-8"))

    assert stage_packet["approval"]["required"] is True
    assert stage_packet["stage"]["kind"] == "approval_packet"
    assert safe_work_result["work_type"] == "draft"
    assert safe_work_result["status"] == "staged_for_user_decision"
    assert safe_work_result["recommended_option_or_draft"]["kind"] == "draft_text"
    assert callback_record["status"] == "pending"
    assert callback_record["prompt_message_count"] == 1


def test_telegram_bot_inline_proactive_overrides_generic_async_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_TELEGRAM_INGEST_SECRET", "tg-secret")
    monkeypatch.setenv("EA_TELEGRAM_AUTO_BIND_UNKNOWN_CHAT", "1")
    monkeypatch.setenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID", "exec-telegram-inline-proactive-async")
    monkeypatch.setenv("EA_TELEGRAM_BOT_HANDLE", "ea_concierge_bot")
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token-inline-proactive-async")
    monkeypatch.setenv("EA_TELEGRAM_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_PROACTIVE_OODA_SAFE_WORK_NETWORK_FETCH_ENABLED", "0")
    monkeypatch.setenv("EA_PROACTIVE_OODA_STAGE_PACKET_DIR", str(tmp_path / "stage-packets"))
    monkeypatch.setenv("EA_PROACTIVE_OODA_SAFE_WORK_RESULT_DIR", str(tmp_path / "safe-work"))
    monkeypatch.setenv("EA_PROACTIVE_OODA_STATE_PATH", str(tmp_path / "state" / "notified.json"))
    monkeypatch.setenv("EA_PROACTIVE_OODA_RECEIPT_PATH", str(tmp_path / "state" / "inline-receipt.generated.json"))

    from app.api.routes import channels as channels_route

    sent: list[dict[str, object]] = []
    scheduled: list[dict[str, object]] = []
    acks: list[dict[str, object]] = []

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": 9903}}).encode("utf-8")

    def _fake_urlopen(request, timeout=30):
        payload = json.loads(request.data.decode("utf-8"))
        sent.append(payload)
        return _FakeResponse()

    monkeypatch.setattr(channels_route.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(
        channels_route,
        "_telegram_session_turn",
        lambda **kwargs: channels_route.TelegramTurnDecision(
            reply_text="Working on it.",
            schedule_async=True,
            async_text=str(dict(kwargs.get("payload") or {}).get("text") or ""),
            async_message_id=str(dict(kwargs.get("payload") or {}).get("message_id") or ""),
            async_payload={"kind": "generic_task"},
        ),
    )
    monkeypatch.setattr(channels_route, "_telegram_send_processing_ack", lambda **kwargs: acks.append(kwargs))
    monkeypatch.setattr(channels_route, "_telegram_schedule_async_assistant_reply", lambda **kwargs: scheduled.append(kwargs))

    client = _client(principal_id="")
    agent = _TelegramScenarioAgent(client, secret="tg-secret")

    response = agent.ask("When you find a chimney sweep, draft an email inquiry and save it for approval.")
    assert response["reply_sent"] is True
    assert "Saved. I staged this as a reversible next step." in str(response["reply_text"])
    assert "Queue: https://myexternalbrain.com/app/queue" in str(response["reply_text"])
    assert not acks
    assert not scheduled

    assert len(sent) == 1
    reply_markup = dict(sent[0].get("reply_markup") or {})
    inline_keyboard = list(reply_markup.get("inline_keyboard") or [])
    assert inline_keyboard

    stage_paths = list((tmp_path / "stage-packets").glob("*.json"))
    safe_work_paths = list((tmp_path / "safe-work").glob("*.json"))
    assert len(stage_paths) == 1
    assert len(safe_work_paths) == 1


def test_telegram_bot_followup_draft_reuses_recent_search_context_and_auto_executes_gmail_draft(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_TELEGRAM_INGEST_SECRET", "tg-secret")
    monkeypatch.setenv("EA_TELEGRAM_AUTO_BIND_UNKNOWN_CHAT", "1")
    monkeypatch.setenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID", "exec-telegram-inline-proactive-followup")
    monkeypatch.setenv("EA_TELEGRAM_BOT_HANDLE", "ea_concierge_bot")
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token-inline-proactive-followup")
    monkeypatch.setenv("EA_TELEGRAM_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_PROACTIVE_OODA_SAFE_WORK_NETWORK_FETCH_ENABLED", "0")
    monkeypatch.setenv("EA_PROACTIVE_OODA_STAGE_PACKET_DIR", str(tmp_path / "stage-packets"))
    monkeypatch.setenv("EA_PROACTIVE_OODA_SAFE_WORK_RESULT_DIR", str(tmp_path / "safe-work"))
    monkeypatch.setenv("EA_PROACTIVE_OODA_STATE_PATH", str(tmp_path / "state" / "notified.json"))
    monkeypatch.setenv("EA_PROACTIVE_OODA_RECEIPT_PATH", str(tmp_path / "state" / "inline-receipt.generated.json"))

    from app.api.routes import channels as channels_route

    sent: list[dict[str, object]] = []
    executions: list[dict[str, object]] = []

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": 9904}}).encode("utf-8")

    def _fake_urlopen(request, timeout=30):
        payload = json.loads(request.data.decode("utf-8"))
        sent.append(payload)
        return _FakeResponse()

    def _fake_execute(**kwargs):
        executions.append(kwargs)
        return {
            "status": "executed",
            "action": "save_gmail_draft",
            "work_type": "draft",
            "gmail_draft_id": "gmail-draft-followup-1",
            "draft_folder_url": "https://mail.google.com/mail/u/0/#drafts",
        }

    monkeypatch.setattr(channels_route.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(channels_route, "execute_proactive_ooda_action", _fake_execute)

    client = _client(principal_id="")
    agent = _TelegramScenarioAgent(client, secret="tg-secret")

    first = agent.ask("suche mir rauchfangkehrer - ich brauche ein Gutachten, ob ich meinen Zimmerkamin als Abluftrohr eines Klimageraets verwenden kann")
    assert first["reply_sent"] is True
    assert "Saved. I staged this as a reversible next step." in str(first["reply_text"])

    followup = agent.ask("wenn du einen gefunden hast formuliere eine emailanfrage und speicher sie als draft in meiner inbox. schicke mir hier den link zu ihr.")
    assert followup["reply_sent"] is True
    assert "Saved. I created the Gmail draft." in str(followup["reply_text"])
    assert "Open Drafts: https://mail.google.com/mail/u/0/#drafts" in str(followup["reply_text"])
    assert executions

    stage_paths = sorted((tmp_path / "stage-packets").glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    assert len(stage_paths) >= 2
    latest_stage = json.loads(stage_paths[0].read_text(encoding="utf-8"))
    input_contract = dict(latest_stage["safe_work_order"]["input_contract"])

    assert latest_stage["approval"]["required"] is False
    assert latest_stage["stage"]["payload"]["auto_execute_action"] == "save_gmail_draft"
    assert input_contract["draft_mode"] == "research_backed_inquiry"
    assert "suche mir rauchfangkehrer" in input_contract["draft_request_text"].lower()
    assert "speicher sie als draft in meiner inbox" in input_contract["draft_request_text"].lower()
    assert input_contract["research_query"] == "rauchfangkehrer"
    assert input_contract["search_queries"][0].startswith("rauchfangkehrer ")
    assert "Gutachten" in input_contract["search_queries"][0]
    assert input_contract["search_queries"][1] == "rauchfangkehrer Gutachten Zimmerkamin Abluftrohr"
    assert input_contract["search_queries"][-1] == "rauchfangkehrer"
    assert executions[0]["packet_ref"] == latest_stage["packet_ref"]
    reply_markup = dict(sent[-1].get("reply_markup") or {})
    inline_keyboard = list(reply_markup.get("inline_keyboard") or [])
    assert inline_keyboard
    callback_dir = tmp_path / "state" / "proactive_ooda_approval_callbacks"
    callback_rows = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in callback_dir.glob("*.json")
    ]
    assert any(row.get("packet_ref") == latest_stage["packet_ref"] for row in callback_rows)


def test_telegram_epub_webhook_sends_three_voice_samples_with_inline_controls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_TELEGRAM_INGEST_SECRET", "tg-secret")
    monkeypatch.setenv("EA_TELEGRAM_AUTO_BIND_UNKNOWN_CHAT", "1")
    monkeypatch.setenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID", "exec-telegram-e2e-audiobook")
    monkeypatch.setenv("EA_TELEGRAM_BOT_HANDLE", "ea_concierge_bot")
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token-e2e-audiobook")
    monkeypatch.setenv("EA_TELEGRAM_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_INSTANT_SENDER_WHITELIST", "telegram:1354554303")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": "voice-one", "label": "Voice One", "language": "en-US", "tags": ["audiobook", "narration", "clear"]},
                {"voice_id": "voice-two", "label": "Voice Two", "language": "en-US", "tags": ["audiobook", "narration", "warm"]},
                {"voice_id": "voice-three", "label": "Voice Three", "language": "en-US", "tags": ["audiobook", "narration", "story"]},
            ]
        ),
    )
    from app.api.routes import channels as channels_route
    from app.services import audiobook_epub_pipeline as pipeline

    class _InlineExecutor:
        def submit(self, fn, *args, **kwargs):  # noqa: ANN001
            fn(*args, **kwargs)
            return SimpleNamespace()

    class _FakeResponse:
        def __init__(self, message_id: int) -> None:
            self._message_id = message_id

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": self._message_id}}).encode("utf-8")

    def _write_epub(path: Path) -> None:
        with zipfile.ZipFile(path, "w") as book:
            book.writestr("mimetype", "application/epub+zip")
            book.writestr(
                "META-INF/container.xml",
                """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
            )
            book.writestr(
                "OEBPS/content.opf",
                """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Telegram Sample Book</dc:title>
    <dc:creator>A. Writer</dc:creator>
    <dc:language>en-US</dc:language>
  </metadata>
  <manifest>
    <item id="chap1" href="chapters/chapter-1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chap1"/>
  </spine>
</package>
""",
            )
            book.writestr(
                "OEBPS/chapters/chapter-1.xhtml",
                "<html><head><title>Opening</title></head><body><h1>Opening</h1><p>Hello from the sample audiobook. It should let the listener compare voices before the full render.</p></body></html>",
            )

    source_epub = tmp_path / "sample.epub"
    _write_epub(source_epub)
    sent_messages: list[dict[str, object]] = []
    sent_audio_bodies: list[bytes] = []

    def _fake_urlopen(request, timeout=30):
        url = str(getattr(request, "full_url", ""))
        body = bytes(getattr(request, "data", b"") or b"")
        if url.endswith("/sendAudio"):
            sent_audio_bodies.append(body)
        elif url.endswith("/sendMessage"):
            sent_messages.append(json.loads(body.decode("utf-8")))
        return _FakeResponse(18000 + len(sent_messages) + len(sent_audio_bodies))

    def _fake_resolve_telegram_message_payload(**kwargs):
        payload = dict(kwargs.get("payload") or {})
        metadata = dict(payload.get("message_metadata") or {})
        if str(payload.get("kind") or "").strip().lower() == "document":
            metadata["download_url"] = "https://api.telegram.org/file/botTOKEN/books/sample.epub"
            payload["message_metadata"] = metadata
            payload["text"] = "Document: sample.epub"
        return payload

    def _fake_download_telegram_epub(*, source_url: str, target_path: Path, max_bytes: int | None = None) -> dict[str, object]:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(source_epub.read_bytes())
        return {"bytes": target_path.stat().st_size, "sha256": "test-sha", "archive_validation": {"status": "pass"}}

    monkeypatch.setattr(channels_route, "_TELEGRAM_ASYNC_EXECUTOR", _InlineExecutor())
    monkeypatch.setattr(channels_route.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(channels_route, "resolve_telegram_message_payload", _fake_resolve_telegram_message_payload)
    monkeypatch.setattr(pipeline, "download_telegram_epub", _fake_download_telegram_epub)
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", lambda **kwargs: (b"fake-wav", "audio/wav"))
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)

    client = _client(principal_id="")
    agent = _TelegramScenarioAgent(client, secret="tg-secret")
    response = agent.send_message_payload(
        {
            "document": {
                "file_id": "epub-file-1",
                "file_name": "sample.epub",
                "mime_type": "application/epub+zip",
                "file_size": source_epub.stat().st_size,
            },
            "caption": "Audiobook plz",
        }
    )

    assert response["reply_sent"] is False
    assert response["reply_text"] == ""
    assert len(sent_audio_bodies) == 3
    assert any("I sent 3 short voice samples" in str(message.get("text") or "") for message in sent_messages)
    for body in sent_audio_bodies:
        assert b"Use this" in body
        assert b"Dismiss" in body
        assert b"ab|u|" in body
        assert b"ab|d|" in body
        assert b'filename="' in body
    rendered_audio_payload = b"\n".join(sent_audio_bodies).decode("utf-8", "replace")
    assert "Voice One" in rendered_audio_payload
    assert "Voice Two" in rendered_audio_payload
    assert "Voice Three" in rendered_audio_payload


def test_telegram_epub_webhook_dismiss_replaces_voice_sample_immediately(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_epub = tmp_path / "sample.epub"
    with zipfile.ZipFile(source_epub, "w") as book:
        book.writestr("mimetype", "application/epub+zip")
        book.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        book.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Telegram Replacements</dc:title>
    <dc:creator>Replacement Author</dc:creator>
    <dc:language>en-US</dc:language>
  </metadata>
  <manifest>
    <item id="chap1" href="chapters/chapter-1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chap1"/>
  </spine>
</package>
""",
        )
        book.writestr(
            "OEBPS/chapters/chapter-1.xhtml",
            "<html><head><title>Opening</title></head><body><h1>Opening</h1><p>Short opening scene for replacement checks.</p></body></html>",
        )

    monkeypatch.setenv("EA_TELEGRAM_INGEST_SECRET", "tg-secret")
    monkeypatch.setenv("EA_TELEGRAM_AUTO_BIND_UNKNOWN_CHAT", "1")
    monkeypatch.setenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID", "exec-telegram-e2e-audiobook-replace")
    monkeypatch.setenv("EA_TELEGRAM_BOT_HANDLE", "ea_concierge_bot")
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token-e2e-audiobook-replace")
    monkeypatch.setenv("EA_TELEGRAM_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_INSTANT_SENDER_WHITELIST", "telegram:1354554303")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": f"voice-{index}", "label": f"Voice {index}", "language": "en-US", "tags": ["audiobook", "narration"]}
                for index in range(1, 6)
            ]
        ),
    )
    from app.api.routes import channels as channels_route
    from app.services import audiobook_epub_pipeline as pipeline

    class _InlineExecutor:
        def submit(self, fn, *args, **kwargs):  # noqa: ANN001
            fn(*args, **kwargs)
            return SimpleNamespace()

    class _FakeResponse:
        def __init__(self, message_id: int) -> None:
            self._message_id = message_id

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": self._message_id}}).encode("utf-8")

    sent_messages: list[dict[str, object]] = []
    sent_audio_bodies: list[bytes] = []

    def _fake_urlopen(request, timeout=30):
        url = str(getattr(request, "full_url", ""))
        body = bytes(getattr(request, "data", b"") or b"")
        if url.endswith("/sendAudio"):
            sent_audio_bodies.append(body)
        elif url.endswith("/sendMessage"):
            sent_messages.append(json.loads(body.decode("utf-8")))
        return _FakeResponse(18000 + len(sent_messages) + len(sent_audio_bodies))

    def _fake_resolve_telegram_message_payload(**kwargs):
        payload = dict(kwargs.get("payload") or {})
        metadata = dict(payload.get("message_metadata") or {})
        if str(payload.get("kind") or "").strip().lower() == "document":
            metadata["download_url"] = "https://api.telegram.org/file/botTOKEN/books/sample.epub"
            payload["message_metadata"] = metadata
            payload["text"] = "Document: sample.epub"
        return payload

    def _fake_download_telegram_epub(*, source_url: str, target_path: Path, max_bytes: int | None = None) -> dict[str, object]:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(source_epub.read_bytes())
        return {"bytes": target_path.stat().st_size, "sha256": "test-sha", "archive_validation": {"status": "pass"}}

    def _extract_dismiss_callback(body: bytes) -> str:
        text = body.decode("utf-8", "replace")
        match = re.search(r'"text":"Dismiss","callback_data":"([^"\\]+)"', text)
        assert match is not None
        return match.group(1)

    monkeypatch.setattr(channels_route, "_TELEGRAM_ASYNC_EXECUTOR", _InlineExecutor())
    monkeypatch.setattr(channels_route.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(channels_route, "resolve_telegram_message_payload", _fake_resolve_telegram_message_payload)
    monkeypatch.setattr(pipeline, "download_telegram_epub", _fake_download_telegram_epub)
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", lambda **kwargs: (b"fake-wav", "audio/wav"))
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)

    client = _client(principal_id="")
    agent = _TelegramScenarioAgent(client, secret="tg-secret")
    response = agent.send_message_payload(
        {
            "document": {
                "file_id": "epub-file-1",
                "file_name": "sample.epub",
                "mime_type": "application/epub+zip",
                "file_size": source_epub.stat().st_size,
            },
            "caption": "Audiobook plz",
        }
    )

    assert response["reply_sent"] is False
    assert response["reply_text"] == ""
    assert len(sent_audio_bodies) == 3

    dismiss_callback = _extract_dismiss_callback(sent_audio_bodies[0])
    dismissal_response = agent.send_callback_query(
        {
            "id": "dismiss-callback-1",
            "from": {"id": agent.chat_id, "first_name": "Tester"},
            "message": {
                "message_id": 123456,
                "chat": {"id": agent.chat_id, "type": "private"},
            },
            "data": dismiss_callback,
        }
    )

    assert dismissal_response["reply_sent"] is True
    assert "I sent 1 replacement audiobook voice sample" in str(dismissal_response["reply_text"])
    assert len(sent_audio_bodies) == 4

    dismiss_callback_2 = _extract_dismiss_callback(sent_audio_bodies[-1])
    dismissal_response_2 = agent.send_callback_query(
        {
            "id": "dismiss-callback-2",
            "from": {"id": agent.chat_id, "first_name": "Tester"},
            "message": {
                "message_id": 123456,
                "chat": {"id": agent.chat_id, "type": "private"},
            },
            "data": dismiss_callback_2,
        }
    )

    assert dismissal_response_2["reply_sent"] is True
    assert "replacement audiobook voice sample" in str(dismissal_response_2["reply_text"])
    assert len(sent_audio_bodies) == 5

    dismiss_callback_3 = _extract_dismiss_callback(sent_audio_bodies[-1])
    dismissal_response_3 = agent.send_callback_query(
        {
            "id": "dismiss-callback-3",
            "from": {"id": agent.chat_id, "first_name": "Tester"},
            "message": {
                "message_id": 123456,
                "chat": {"id": agent.chat_id, "type": "private"},
            },
            "data": dismiss_callback_3,
        }
    )

    assert dismissal_response_3["reply_sent"] is True
    assert (
        "replacement audiobook voice sample" in str(dismissal_response_3["reply_text"])
        or "No replacement audiobook voice is available yet." in str(dismissal_response_3["reply_text"])
        or "No more configured audiobook voice samples" in str(dismissal_response_3["reply_text"])
    )


def test_telegram_epub_webhook_dismiss_replaces_voice_sample_immediately_with_small_catalog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import channels as channels_route
    from app.services import audiobook_epub_pipeline as pipeline

    source_epub = tmp_path / "sample.epub"
    with zipfile.ZipFile(source_epub, "w") as book:
        book.writestr("mimetype", "application/epub+zip")
        book.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        book.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Small Catalog Replacement</dc:title>
    <dc:creator>Replacement Author</dc:creator>
    <dc:language>en-US</dc:language>
  </metadata>
  <manifest>
    <item id="chap1" href="chapters/chapter-1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chap1"/>
  </spine>
</package>
""",
        )
        book.writestr("OEBPS/chapters/chapter-1.xhtml", "<html><body><p>Replacement loop test sample chapter.</p></body></html>")

    monkeypatch.setenv("EA_TELEGRAM_INGEST_SECRET", "tg-secret")
    monkeypatch.setenv("EA_TELEGRAM_AUTO_BIND_UNKNOWN_CHAT", "1")
    monkeypatch.setenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID", "exec-telegram-e2e-audiobook-replace-small")
    monkeypatch.setenv("EA_TELEGRAM_BOT_HANDLE", "ea_concierge_bot")
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token-e2e-audiobook-replace-small")
    monkeypatch.setenv("EA_TELEGRAM_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_INSTANT_SENDER_WHITELIST", "telegram:1354554303")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": f"voice-{index}", "label": f"Voice {index}", "language": "en-US", "tags": ["audiobook", "narration"]}
                for index in range(1, 4)
            ]
        ),
    )

    class _InlineExecutor:
        def submit(self, fn, *args, **kwargs):  # noqa: ANN001
            fn(*args, **kwargs)
            return SimpleNamespace()

    class _FakeResponse:
        def __init__(self, message_id: int) -> None:
            self._message_id = message_id

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": self._message_id}}).encode("utf-8")

    sent_audio_bodies: list[bytes] = []

    def _fake_urlopen(request, timeout=30):
        url = str(getattr(request, "full_url", ""))
        body = bytes(getattr(request, "data", b"") or b"")
        if url.endswith("/sendAudio"):
            sent_audio_bodies.append(body)
        return _FakeResponse(16000 + len(sent_audio_bodies))

    def _fake_resolve_telegram_message_payload(**kwargs):
        payload = dict(kwargs.get("payload") or {})
        metadata = dict(payload.get("message_metadata") or {})
        if str(payload.get("kind") or "").strip().lower() == "document":
            metadata["download_url"] = "https://api.telegram.org/file/botTOKEN/books/sample.epub"
            payload["message_metadata"] = metadata
            payload["text"] = "Document: sample.epub"
        return payload

    def _fake_download_telegram_epub(*, source_url: str, target_path: Path, max_bytes: int | None = None) -> dict[str, object]:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(source_epub.read_bytes())
        return {"bytes": target_path.stat().st_size, "sha256": "test-sha", "archive_validation": {"status": "pass"}}

    def _extract_dismiss_callback(body: bytes) -> str:
        text = body.decode("utf-8", "replace")
        match = re.search(r'"text":"Dismiss","callback_data":"([^"\\]+)"', text)
        assert match is not None
        return match.group(1)

    monkeypatch.setattr(channels_route, "_TELEGRAM_ASYNC_EXECUTOR", _InlineExecutor())
    monkeypatch.setattr(channels_route.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(channels_route, "resolve_telegram_message_payload", _fake_resolve_telegram_message_payload)
    monkeypatch.setattr(pipeline, "download_telegram_epub", _fake_download_telegram_epub)
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", lambda **kwargs: (b"fake-wav", "audio/wav"))
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)

    client = _client(principal_id="")
    agent = _TelegramScenarioAgent(client, secret="tg-secret")
    response = agent.send_message_payload(
        {
            "document": {
                "file_id": "epub-file-small",
                "file_name": "sample.epub",
                "mime_type": "application/epub+zip",
                "file_size": source_epub.stat().st_size,
            },
            "caption": "Audiobook plz",
        }
    )

    assert response["reply_sent"] is False
    assert response["reply_text"] == ""
    assert len(sent_audio_bodies) == 3

    def dismiss_latest() -> str:
        return _extract_dismiss_callback(sent_audio_bodies[-1])

    for idx in range(3):
        data = dismiss_latest()
        result = agent.send_callback_query(
            {
                "id": f"dismiss-callback-small-{idx}",
                "from": {"id": agent.chat_id, "first_name": "Tester"},
                "message": {
                    "message_id": 123456,
                    "chat": {"id": agent.chat_id, "type": "private"},
                },
                "data": data,
            }
        )
        assert result["reply_sent"] is True
        assert "replacement audiobook voice sample" in str(result["reply_text"])


def test_telegram_epub_webhook_uses_supplied_knuf_epub_for_german_voice_samples(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_epub = Path(
        os.getenv(
            "EA_E2E_SUPPLIED_EPUB_PATH",
            "/mnt/pcloud/EA/audiobook_jobs/epub-audiobook-20260619T120239Z-9d82d2ec/source/Knuf_Sei-nicht-so-hart-zu-dir-selbs_9783641178222.epub",
        )
    )
    if not source_epub.is_file():
        pytest.skip(f"operator-supplied EPUB not present: {source_epub}")

    monkeypatch.setenv("EA_TELEGRAM_INGEST_SECRET", "tg-secret")
    monkeypatch.setenv("EA_TELEGRAM_AUTO_BIND_UNKNOWN_CHAT", "1")
    monkeypatch.setenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID", "exec-telegram-e2e-knuf-audiobook")
    monkeypatch.setenv("EA_TELEGRAM_BOT_HANDLE", "ea_concierge_bot")
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token-e2e-knuf-audiobook")
    monkeypatch.setenv("EA_TELEGRAM_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_INSTANT_SENDER_WHITELIST", "telegram:1354554303")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": "de-voice-one", "label": "German Clear", "language": "de", "tags": ["audiobook", "narration", "german", "nonfiction", "clear"]},
                {"voice_id": "de-voice-two", "label": "German Warm", "language": "de", "tags": ["audiobook", "narration", "german", "nonfiction", "warm"]},
                {"voice_id": "de-voice-three", "label": "German Calm", "language": "de", "tags": ["audiobook", "narration", "german", "nonfiction", "calm"]},
            ]
        ),
    )
    from app.api.routes import channels as channels_route
    from app.services import audiobook_epub_pipeline as pipeline

    class _InlineExecutor:
        def submit(self, fn, *args, **kwargs):  # noqa: ANN001
            fn(*args, **kwargs)
            return SimpleNamespace()

    class _FakeResponse:
        def __init__(self, message_id: int) -> None:
            self._message_id = message_id

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": self._message_id}}).encode("utf-8")

    sent_messages: list[dict[str, object]] = []
    sent_audio_bodies: list[bytes] = []

    def _fake_urlopen(request, timeout=30):
        url = str(getattr(request, "full_url", ""))
        body = bytes(getattr(request, "data", b"") or b"")
        if url.endswith("/sendAudio"):
            sent_audio_bodies.append(body)
        elif url.endswith("/sendMessage"):
            try:
                sent_messages.append(json.loads(body.decode("utf-8")))
            except json.JSONDecodeError:
                sent_messages.append({"raw": body.decode("utf-8", "replace")})
        return _FakeResponse(19000 + len(sent_messages) + len(sent_audio_bodies))

    def _fake_resolve_telegram_message_payload(**kwargs):
        payload = dict(kwargs.get("payload") or {})
        metadata = dict(payload.get("message_metadata") or {})
        if str(payload.get("kind") or "").strip().lower() == "document":
            metadata["download_url"] = "https://api.telegram.org/file/botTOKEN/books/knuf.epub"
            payload["message_metadata"] = metadata
            payload["text"] = f"Document: {source_epub.name}"
        return payload

    def _fake_download_telegram_epub(*, source_url: str, target_path: Path, max_bytes: int | None = None) -> dict[str, object]:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(source_epub.read_bytes())
        return {"bytes": target_path.stat().st_size, "sha256": "test-sha", "archive_validation": {"status": "pass"}}

    monkeypatch.setattr(channels_route, "_TELEGRAM_ASYNC_EXECUTOR", _InlineExecutor())
    monkeypatch.setattr(channels_route.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(channels_route, "resolve_telegram_message_payload", _fake_resolve_telegram_message_payload)
    monkeypatch.setattr(pipeline, "download_telegram_epub", _fake_download_telegram_epub)
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", lambda **kwargs: (b"fake-wav", "audio/wav"))
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)

    client = _client(principal_id="")
    agent = _TelegramScenarioAgent(client, secret="tg-secret")
    response = agent.send_message_payload(
        {
            "document": {
                "file_id": "epub-file-knuf",
                "file_name": source_epub.name,
                "mime_type": "application/epub+zip",
                "file_size": source_epub.stat().st_size,
            },
            "caption": "Audiobook plz",
        }
    )

    assert response["reply_sent"] is False
    assert response["reply_text"] == ""
    assert len(sent_audio_bodies) == 3
    assert any("I sent 3 short voice samples" in str(message.get("text") or message.get("raw") or "") for message in sent_messages)
    job_paths = sorted((tmp_path / "jobs").glob("epub-audiobook-*/job.json"))
    assert len(job_paths) == 1
    job = json.loads(job_paths[0].read_text(encoding="utf-8"))
    assert job["metadata"]["language"] == "de"
    assert job["metadata"]["title"] == "Sei nicht so hart zu dir selbst"
    profile = job["provider"]["voice_selection"]["book_profile"]
    assert profile["language"] == "de"
    assert "nonfiction" in profile["recommended_tags"]
    rendered_audio_payload = b"\n".join(sent_audio_bodies).decode("utf-8", "replace")
    assert "German Clear" in rendered_audio_payload
    assert "German Warm" in rendered_audio_payload
    assert "German Calm" in rendered_audio_payload
    assert b"Use this" in sent_audio_bodies[0]
    assert b"Dismiss" in sent_audio_bodies[0]


def test_telegram_audiobook_status_webhook_resends_playback_buttons(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_TELEGRAM_INGEST_SECRET", "tg-secret")
    monkeypatch.setenv("EA_TELEGRAM_AUTO_BIND_UNKNOWN_CHAT", "1")
    monkeypatch.setenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID", "exec-telegram-e2e-audiobook-status")
    monkeypatch.setenv("EA_TELEGRAM_BOT_HANDLE", "ea_concierge_bot")
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token-e2e-audiobook-status")
    monkeypatch.setenv("EA_TELEGRAM_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("UNMIXR_API_KEY", "fake-unmixr-key")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": f"voice-{index}", "label": f"Voice {index}", "language": "en-US", "tags": ["audiobook", "narration"]}
                for index in range(1, 4)
            ]
        ),
    )
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-ready"
    job_dir.mkdir(parents=True)
    target_path = tmp_path / "audiobookshelf" / "A. Writer" / "Ready Book" / "Ready Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"fake m4b")
    (job_dir / "job.json").write_text(
        json.dumps(
            {
                "job_id": "job-ready",
                "status": "audiobookshelf_imported",
                "updated_at": "2026-06-20T04:06:00Z",
                "metadata": {"title": "Ready Book", "author": "A. Writer", "language": "en-US"},
                "storage": {"job_dir": str(job_dir)},
                "telegram": {"chat_id": "1354554303", "message_id": "7"},
                "audiobookshelf_import": {
                    "status": "imported",
                    "target_path": str(target_path),
                    "public_share": {
                        "status": "public_share_ready",
                        "absolute_url": "https://abs.example.com/share/ea-ready-book",
                        "telegram_delivery": {"status": "sent", "message_id": "2942"},
                        "playback_acceptance_callback": {
                            "status": "ready",
                            "token": "callback-token",
                            "raw_token_exposed": False,
                        },
                    },
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    from app.api.routes import channels as channels_route

    sent_messages: list[dict[str, object]] = []

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": 19500}}).encode("utf-8")

    def _fake_urlopen(request, timeout=30):
        sent_messages.append(json.loads(bytes(getattr(request, "data", b"") or b"{}").decode("utf-8")))
        return _FakeResponse()

    monkeypatch.setattr(channels_route.urllib.request, "urlopen", _fake_urlopen)

    client = _client(principal_id="")
    agent = _TelegramScenarioAgent(client, secret="tg-secret")
    response = agent.ask("audiobook status")

    assert response["reply_sent"] is True
    assert sent_messages
    reply_markup = sent_messages[-1]["reply_markup"]
    buttons = [
        button
        for row in list(reply_markup.get("inline_keyboard") or [])
        for button in row
    ]
    assert any(button.get("text") == "Playback works" for button in buttons)
    assert any(button.get("text") == "Problem" for button in buttons)
    assert any(str(button.get("callback_data") or "").startswith("ap|a|callback-token|") for button in buttons)


def test_telegram_bot_workflow_persists_async_admin_followup_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_TELEGRAM_INGEST_SECRET", "tg-secret")
    monkeypatch.setenv("EA_TELEGRAM_AUTO_BIND_UNKNOWN_CHAT", "1")
    monkeypatch.setenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID", "exec-telegram-e2e-admin")
    monkeypatch.setenv("EA_TELEGRAM_BOT_HANDLE", "ea_concierge_bot")
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token-e2e-admin")
    from app.api.routes import channels as channels_route

    class _InlineExecutor:
        def submit(self, fn, *args, **kwargs):  # noqa: ANN001
            fn(*args, **kwargs)
            return SimpleNamespace()

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": 9902}}).encode("utf-8")

    def _fake_urlopen(request, timeout=30):
        return _FakeResponse()

    class _FakeProductService:
        def list_brief_items(self, *, principal_id: str, limit: int = 8, **kwargs):
            return []

        def list_queue(self, *, principal_id: str, limit: int = 8, **kwargs):
            return [
                SimpleNamespace(
                    id="queue-rehab",
                    object_ref="queue-rehab",
                    priority="high",
                    rank_score=96.0,
                    title="Check KfA rehab authorization",
                    summary="Rehab approval and KfA paperwork still need review.",
                    recommended_action="check rehab approvals",
                    profile_followup_refs=("profile_followup:insurance_admin:rehab_authorization_management",),
                ),
                SimpleNamespace(
                    id="queue-school",
                    object_ref="queue-school",
                    priority="high",
                    rank_score=85.0,
                    title="Review Noah school paperwork",
                    summary="School enrollment and coordination paperwork need a pass.",
                    recommended_action="review school paperwork",
                    profile_followup_refs=("profile_followup:school_admin:school_and_kindergarten_coordination",),
                ),
            ]

        def get_preference_profile(self, *, principal_id: str, person_id: str = "self"):
            return {"preference_nodes": []}

        def list_office_events(self, *, principal_id: str, limit: int = 12, **kwargs):
            return []

    monkeypatch.setattr(channels_route.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(channels_route, "_telegram_real_ea_reply_text", lambda **kwargs: "Focus on the rehab approvals and KfA authorization paperwork first.")
    monkeypatch.setattr(channels_route, "_TELEGRAM_ASYNC_EXECUTOR", _InlineExecutor())
    monkeypatch.setattr(channels_route, "build_product_service", lambda container: _FakeProductService())
    client = _client(principal_id="")
    agent = _TelegramScenarioAgent(client, secret="tg-secret")

    first = agent.ask("What should I tackle first?")
    assert first["reply_sent"] is False
    observations = list(client.app.state.container.channel_runtime.list_recent_observations(limit=20, principal_id="exec-telegram-e2e-admin"))
    async_payload = next(dict(row.payload or {}) for row in observations if str(row.event_type) == "telegram.reply_async_sent")
    assert async_payload["intent_state"]["active_intent"] == "admin_followup"
    assert async_payload["intent_state"]["active_admin_primary_title"] == "Check KfA rehab authorization"

    second = agent.ask("And after that?")
    assert second["reply_sent"] is True
    assert "After that, focus on Review Noah school paperwork." in second["reply_text"]


def test_telegram_bot_workflow_persists_property_comparison_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_TELEGRAM_INGEST_SECRET", "tg-secret")
    monkeypatch.setenv("EA_TELEGRAM_AUTO_BIND_UNKNOWN_CHAT", "1")
    monkeypatch.setenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID", "exec-telegram-e2e-property")
    monkeypatch.setenv("EA_TELEGRAM_BOT_HANDLE", "ea_concierge_bot")
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token-e2e-property")
    from app.api.routes import channels as channels_route
    from app.product.models import EvidenceRef

    upstream_groundings: list[str] = []

    class _InlineExecutor:
        def submit(self, fn, *args, **kwargs):  # noqa: ANN001
            fn(*args, **kwargs)
            return SimpleNamespace()

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": 9903}}).encode("utf-8")

    class _FakeResult:
        def __init__(self, text: str) -> None:
            self.text = text

    def _fake_urlopen(request, timeout=30):
        return _FakeResponse()

    def _fake_generate_upstream_text(**kwargs):
        system_messages = [item["content"] for item in kwargs["messages"] if item["role"] == "system"]
        grounding_text = str(system_messages[1]) if len(system_messages) > 1 else ""
        upstream_groundings.append(grounding_text)
        user_messages = [item["content"] for item in kwargs["messages"] if item["role"] == "user"]
        prompt = str(user_messages[-1]) if user_messages else ""
        if "what about the other one" in prompt.lower():
            assert "comparison_secondary: Strong Doebling listing | willhaben:1071155412" in grounding_text
            return _FakeResult("The other one is the Strong Doebling listing. It is the backup because it still has lift and bike access, but the Waehring one stays ahead.")
        return _FakeResult("The Strong Waehring listing is still better. Keep the Strong Doebling listing as the backup option.")

    class _FakeProductService:
        def get_preference_profile(self, *, principal_id: str, person_id: str = "self"):
            return {"preference_nodes": [{"domain": "willhaben", "status": "active", "key": "preferred_districts", "value_json": ["Waehring", "Doebling"], "confidence": 0.95}]}

        def list_office_events(self, *, principal_id: str, limit: int = 12, **kwargs):
            return [{"channel": "product", "event_type": "property_alert_review_created", "summary": "New property alert analyzed."}]

        def list_brief_items(self, *, principal_id: str, limit: int = 5, **kwargs):
            return [
                SimpleNamespace(
                    id="brief-strong-waehring",
                    score=97.0,
                    title="Strong Waehring listing",
                    why_now="High-fit property alert with 360 media and preferred district match.",
                    recommended_action="review property alert",
                    object_ref="willhaben:1411708198",
                    evidence_refs=(EvidenceRef(ref_id="listing:1411708198", href="https://www.willhaben.at/iad/immobilien/d/eigentumswohnung/wien/wien-1180-waehring/1411708198/", label="Willhaben listing"),),
                ),
                SimpleNamespace(
                    id="brief-doebling-listing",
                    score=91.0,
                    title="Strong Doebling listing",
                    why_now="Another high-fit property alert with lift and bike access.",
                    recommended_action="compare against shortlist",
                    object_ref="willhaben:1071155412",
                    evidence_refs=(EvidenceRef(ref_id="listing:1071155412", href="https://www.willhaben.at/iad/immobilien/d/eigentumswohnung/wien/wien-1190-doebling/1071155412/", label="Willhaben listing"),),
                ),
            ]

        def list_queue(self, *, principal_id: str, limit: int = 5, **kwargs):
            return [
                SimpleNamespace(id="queue-property-1411708198", object_ref="queue-property-1411708198", priority="high", rank_score=96.0, title="Review apartment alert: Strong Waehring listing", summary="Personal fit 96/100 · shortlist · The listing is in Waehring.", evidence_refs=(EvidenceRef(ref_id="listing:1411708198", href="https://www.willhaben.at/iad/immobilien/d/eigentumswohnung/wien/wien-1180-waehring/1411708198/", label="Willhaben listing"),)),
                SimpleNamespace(id="queue-property-1071155412", object_ref="queue-property-1071155412", priority="high", rank_score=91.0, title="Review apartment alert: Strong Doebling listing", summary="Personal fit 91/100 · shortlist · Lift and bike access look strong.", evidence_refs=(EvidenceRef(ref_id="listing:1071155412", href="https://www.willhaben.at/iad/immobilien/d/eigentumswohnung/wien/wien-1190-doebling/1071155412/", label="Willhaben listing"),)),
            ]

    monkeypatch.setattr(channels_route.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(channels_route.responses_route, "_generate_upstream_text", _fake_generate_upstream_text)
    monkeypatch.setattr(channels_route, "_TELEGRAM_ASYNC_EXECUTOR", _InlineExecutor())
    monkeypatch.setattr(channels_route, "build_product_service", lambda container: _FakeProductService())
    monkeypatch.setattr(channels_route, "_telegram_upcoming_calendar_events", lambda *args, **kwargs: [])
    client = _client(principal_id="")
    agent = _TelegramScenarioAgent(client, secret="tg-secret")

    first = agent.ask("Compare the two best property candidates.")
    assert first["reply_sent"] is False
    observations = list(client.app.state.container.channel_runtime.list_recent_observations(limit=24, principal_id="exec-telegram-e2e-property"))
    first_async = next(dict(row.payload or {}) for row in observations if str(row.event_type) == "telegram.reply_async_sent")
    assert first_async["comparison_state"]["comparison_primary"].startswith("Strong Waehring listing")
    assert first_async["comparison_state"]["comparison_secondary"].startswith("Strong Doebling listing")

    second = agent.ask("What about the other one?")
    assert second["reply_sent"] is False
    assert any("comparison_secondary: Strong Doebling listing | willhaben:1071155412" in item for item in upstream_groundings)


def test_telegram_bot_workflow_answers_focus_on_tomorrow_from_calendar_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_TELEGRAM_INGEST_SECRET", "tg-secret")
    monkeypatch.setenv("EA_TELEGRAM_AUTO_BIND_UNKNOWN_CHAT", "1")
    monkeypatch.setenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID", "exec-telegram-e2e-focus")
    monkeypatch.setenv("EA_TELEGRAM_BOT_HANDLE", "ea_concierge_bot")
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token-e2e-focus")
    from app.api.routes import channels as channels_route

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": 9904}}).encode("utf-8")

    def _fake_urlopen(request, timeout=30):
        return _FakeResponse()

    monkeypatch.setattr(channels_route.urllib.request, "urlopen", _fake_urlopen)
    client = _client(principal_id="")
    agent = _TelegramScenarioAgent(client, secret="tg-secret")

    tomorrow_vienna = (datetime.now(ZoneInfo("Europe/Vienna")) + timedelta(days=1)).replace(
        hour=9,
        minute=30,
        second=0,
        microsecond=0,
    )
    client.app.state.container.channel_runtime.ingest_observation(
        principal_id="exec-telegram-e2e-focus",
        channel="calendar",
        event_type="office_signal_calendar_note",
        payload={
            "title": "Strategy Review",
            "summary": "Strategy Review",
            "start_at": tomorrow_vienna.isoformat(),
            "location": "HQ",
        },
        source_id="calendar-event:e2e-focus-1",
        external_id="calendar-event:e2e-focus-1",
        dedupe_key="calendar-event:e2e-focus-1",
    )

    reply = agent.ask("What should I focus on tomorrow?")
    assert reply["reply_sent"] is True
    assert "Tomorrow, focus first on Strategy Review at 09:30." in reply["reply_text"]
    assert "Location: HQ." in reply["reply_text"]


def test_telegram_codex_human_audit_simulation_checks_calendar_pocket_semantic_fallback_and_async(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_TELEGRAM_INGEST_SECRET", "tg-secret")
    monkeypatch.setenv("EA_TELEGRAM_AUTO_BIND_UNKNOWN_CHAT", "1")
    monkeypatch.setenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID", "exec-telegram-e2e-codex-audit")
    monkeypatch.setenv("EA_TELEGRAM_BOT_HANDLE", "ea_concierge_bot")
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token-e2e-codex-audit")
    from app.api.routes import channels as channels_route

    sent_payloads: list[dict[str, object]] = []

    class _InlineExecutor:
        def submit(self, fn, *args, **kwargs):  # noqa: ANN001
            fn(*args, **kwargs)
            return SimpleNamespace()

    class _FakeResponse:
        def __init__(self, message_id: int) -> None:
            self._message_id = message_id

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": self._message_id}}).encode("utf-8")

    def _fake_urlopen(request, timeout=30):
        payload = json.loads(request.data.decode("utf-8"))
        sent_payloads.append(payload)
        return _FakeResponse(12000 + len(sent_payloads))

    class _FakeResult:
        def __init__(self, text: str) -> None:
            self.text = text

    class _FakeProductService:
        def search_pocket_recordings(
            self,
            *,
            principal_id: str,
            actor: str,
            query: str = "",
            before: str = "",
            after: str = "",
            limit: int = 10,
        ) -> dict[str, object]:
            exact_hit = {
                "recording_id": "rec-hanusch-1",
                "title": "Hospital medical discussion and care",
                "recording_at": "2026-05-22T15:28:13Z",
                "archive_status": "archived",
                "archive_path": "/mnt/pcloud/EA/pocket-ai-audio/hanusch.mp3",
                "archive_sha256": "abc123",
                "summary_markdown": "Conversation with father in hospital about his condition.",
                "transcript_text": "We are in Hanusch hospital and he talks about his condition and the family.",
                "transcript_excerpt": "Hanusch hospital conversation with father about his condition.",
                "location_name": "Hanusch Spital",
                "location_address": "Hanusch Krankenhaus, Wien",
                "location_match_status": "nearest",
                "location_confidence": 0.95,
            }
            semantic_candidates = [
                {
                    "recording_id": "rec-hanusch-2",
                    "title": "Hospital call about emergency admission",
                    "recording_at": "2026-05-22T10:11:00Z",
                    "archive_status": "archived",
                    "archive_path": "/mnt/pcloud/EA/pocket-ai-audio/hanusch-2.mp3",
                    "archive_sha256": "def456",
                    "summary_markdown": "Hospital conversation with father and family context.",
                    "transcript_text": "He talks about his chessboard staying in the family and his mother being a power person.",
                    "transcript_excerpt": "chessboard staying in the family",
                    "location_name": "Hanusch Spital",
                    "location_address": "Hanusch Krankenhaus, Wien",
                    "location_match_status": "matched",
                    "location_confidence": 0.91,
                },
                {
                    "recording_id": "rec-hanusch-3",
                    "title": "Noah medication and feeding",
                    "recording_at": "2026-05-22T18:05:40Z",
                    "archive_status": "archived",
                    "archive_path": "/mnt/pcloud/EA/pocket-ai-audio/hanusch-3.mp3",
                    "archive_sha256": "ghi789",
                    "summary_markdown": "Hospital bedside conversation with family context.",
                    "transcript_text": "His brother and mother are mentioned in the hospital discussion.",
                    "transcript_excerpt": "brother and mother in the hospital discussion",
                    "location_name": "Hanusch Spital",
                    "location_address": "Hanusch Krankenhaus, Wien",
                    "location_match_status": "matched",
                    "location_confidence": 0.89,
                },
            ]
            normalized_query = str(query or "").strip().lower()
            if actor == "telegram-semantic-fallback":
                items = semantic_candidates[:limit]
            elif "hanusch" in normalized_query:
                items = [exact_hit][:limit]
            elif "chessboard" in normalized_query or "power person" in normalized_query:
                items = []
            else:
                items = []
            return {
                "generated_at": "2026-05-30T00:00:00Z",
                "query": str(query or "").strip(),
                "before": before,
                "after": after,
                "total": len(items),
                "items": items,
            }

        def deliver_pocket_recording_to_telegram(self, *, principal_id: str, actor: str, recording_id: str) -> dict[str, object]:
            return {
                "recording_id": recording_id,
                "title": "Hospital call about emergency admission" if recording_id == "rec-hanusch-2" else "Hospital medical discussion and care",
                "telegram_delivery_status": "sent",
                "telegram_message_ids": ["tg-msg-pocket-1"],
                "telegram_chat_ref": "1354554303",
            }

        def list_brief_items(self, *, principal_id: str, limit: int = 8, **kwargs):
            return []

        def list_queue(self, *, principal_id: str, limit: int = 8, **kwargs):
            return []

        def get_preference_profile(self, *, principal_id: str, person_id: str = "self"):
            return {"preference_nodes": []}

        def list_office_events(self, *, principal_id: str, limit: int = 12, **kwargs):
            return []

    def _fake_generate_upstream_text(**kwargs):
        payload = json.loads(str(kwargs["messages"][-1]["content"]))
        candidates = list(payload.get("candidates") or [])
        chosen = []
        for item in candidates[:2]:
            chosen.append(
                {
                    "recording_id": item["recording_id"],
                    "reason": "Mentions the chessboard staying in the family and the mother as a power person.",
                }
            )
        return _FakeResult(json.dumps({"candidates": chosen}))

    monkeypatch.setattr(channels_route.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(channels_route, "_TELEGRAM_ASYNC_EXECUTOR", _InlineExecutor())
    monkeypatch.setattr(channels_route, "build_product_service", lambda container: _FakeProductService())
    monkeypatch.setattr(channels_route.responses_route, "_generate_upstream_text", _fake_generate_upstream_text)
    monkeypatch.setattr(
        channels_route,
        "_telegram_real_ea_reply_text",
        lambda **kwargs: "Short audit result: next check the appointment timing and then send the selected hospital recording.",
    )

    client = _client(principal_id="")
    agent = _TelegramScenarioAgent(client, secret="tg-secret")

    next_vienna = (datetime.now(ZoneInfo("Europe/Vienna")) + timedelta(hours=2)).replace(second=0, microsecond=0)
    client.app.state.container.channel_runtime.ingest_observation(
        principal_id="exec-telegram-e2e-codex-audit",
        channel="calendar",
        event_type="office_signal_calendar_note",
        payload={
            "title": "BIP appointment",
            "summary": "BIP appointment",
            "start_at": next_vienna.isoformat(),
            "location": "Hanusch",
        },
        source_id="calendar-event:e2e-codex-audit-1",
        external_id="calendar-event:e2e-codex-audit-1",
        dedupe_key="calendar-event:e2e-codex-audit-1",
    )

    appointment = agent.ask("What is my next appointment?")
    assert appointment["reply_sent"] is True
    assert "BIP appointment" in appointment["reply_text"]

    exact_pocket = agent.ask("Please summarize the best Hanusch hospital Pocket audio before May 23 and tell me why it matches.")
    assert exact_pocket["reply_sent"] is True
    assert "Hospital medical discussion and care" in exact_pocket["reply_text"]
    assert "Hanusch Spital" in exact_pocket["reply_text"]

    upload_announcement = agent.ask(
        "Ich schicke mir die Audioaufnahme vom Gespräch im Hanusch Krankenhaus zwischen mir und meinem Vater."
    )
    assert upload_announcement["reply_sent"] is True
    assert "schick die Audioaufnahme" in upload_announcement["reply_text"]
    assert "Pocket recording" not in upload_announcement["reply_text"]

    vague_memory = agent.ask(
        "I am looking for the conversation with my father in the hospital where he talked about his chessboard and his mother being a power person before May 23."
    )
    assert vague_memory["reply_sent"] is True
    assert "I found these likely Pocket candidates:" in vague_memory["reply_text"]
    assert "send 1" in vague_memory["reply_text"]

    send_selected = agent.ask("send 1")
    assert send_selected["reply_sent"] is True
    assert "Sent: Hospital call about emergency admission." in send_selected["reply_text"]

    async_audit = agent.ask("Bip, bip, bip. Give me a short audit plan for today.")
    assert async_audit["reply_sent"] is False
    channels_route._telegram_async_assistant_reply_worker(
        container=client.app.state.container,
        principal_id="exec-telegram-e2e-codex-audit",
        bot_config={"handle": "ea_concierge_bot", "token": "telegram-token-e2e-codex-audit"},
        chat_id=str(agent.chat_id),
        text="Bip, bip, bip. Give me a short audit plan for today.",
        current_message_id=str(agent._message_id),
    )
    observations = list(
        client.app.state.container.channel_runtime.list_recent_observations(
            limit=40,
            principal_id="exec-telegram-e2e-codex-audit",
        )
    )
    assert any(str(row.event_type) == "telegram.reply_async_started" for row in observations)
    assert any(str(row.event_type) == "telegram.reply_async_sent" for row in observations)
    assert any(str(row.event_type) == "telegram.pocket_candidate_suggestions_sent" for row in observations)
    assert any(
        "processing this asynchronously now" in str(payload.get("text") or "")
        or "processing it asynchronously" in str(payload.get("text") or "")
        for payload in sent_payloads
        if isinstance(payload, dict)
    )
