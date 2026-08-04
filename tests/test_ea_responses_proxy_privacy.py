from __future__ import annotations

import http.client
import json
import threading

from fastapi.responses import JSONResponse


def test_no_retention_client_file_is_strict_and_deduplicated(tmp_path) -> None:
    from scripts import ea_responses_proxy as proxy

    config_path = tmp_path / "clients.json"
    config_path.write_text(
        json.dumps(
            {
                "clients": [
                    {
                        "principal_id": "memorial-service",
                        "token": "m" * 48,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    clients = proxy._load_no_retention_clients(str(config_path))

    assert clients == (
        proxy._NoRetentionClient(principal_id="memorial-service", token="m" * 48),
    )


def test_no_retention_scope_disables_store_and_debug_writes(monkeypatch) -> None:
    from app.api.routes import responses

    request, _ = responses._parse_create_request({"input": "private memorial transcript"})

    def fail(*args, **kwargs):
        raise AssertionError("persistence helper must not be reached")

    monkeypatch.setattr(responses, "_responses_debug_capture_dir", fail)
    monkeypatch.setattr(responses, "Path", fail)

    with responses._no_retention_response_scope():
        assert responses._should_store_response(request) is False
        responses._capture_responses_debug(name="request", payload={"secret": "transcript"})
        responses._write_responses_live_summary(name="request", payload={"secret": "transcript"})


def test_no_retention_response_requires_onemin_and_adds_receipt() -> None:
    from scripts import ea_responses_proxy as proxy

    accepted = proxy._no_retention_response(
        JSONResponse(
            {
                "id": "resp_test",
                "status": "completed",
                "metadata": {
                    "upstream_provider": "onemin",
                    "upstream_model": "gpt-5.4",
                },
                "output_text": "{}",
            }
        )
    )
    accepted_payload = json.loads(bytes(accepted.body).decode("utf-8"))

    assert accepted.status_code == 200
    assert accepted.headers["cache-control"] == "no-store"
    assert accepted_payload["metadata"]["ea_retention"] == "none"
    assert accepted_payload["metadata"]["ea_retention_contract"] == "no_response_storage_no_debug_v1"

    rejected = proxy._no_retention_response(
        JSONResponse(
            {
                "id": "resp_wrong_provider",
                "status": "completed",
                "metadata": {"upstream_provider": "fallback"},
                "output_text": "must not leak",
            }
        )
    )
    rejected_payload = json.loads(bytes(rejected.body).decode("utf-8"))

    assert rejected.status_code == 503
    assert rejected_payload == {
        "error": {
            "code": "required_provider_unavailable",
            "message": "required provider unavailable",
        }
    }
    assert "must not leak" not in bytes(rejected.body).decode("utf-8")


def test_no_retention_http_contract_fixes_principal_and_request_shape(monkeypatch) -> None:
    from app.api.routes import responses
    from scripts import ea_responses_proxy as proxy

    token = "n" * 48
    monkeypatch.setattr(proxy, "AUTH_TOKEN", "a" * 48)
    monkeypatch.setattr(
        proxy,
        "NO_RETENTION_CLIENTS",
        (proxy._NoRetentionClient(principal_id="memorial-service", token=token),),
    )
    captured: dict[str, object] = {}

    def fake_run_response(payload, **kwargs):
        captured["payload"] = dict(payload)
        captured["principal_id"] = kwargs["context"].principal_id
        captured["profile"] = kwargs["codex_profile"]
        captured["preferred_onemin_labels"] = kwargs["preferred_onemin_labels"]
        captured["no_retention_active"] = responses._NO_RETENTION_RESPONSE_ACTIVE.get()
        return JSONResponse(
            {
                "id": "resp_http_test",
                "status": "completed",
                "metadata": {"upstream_provider": "onemin", "upstream_model": "gpt-5.4"},
                "output_text": "{}",
            }
        )

    monkeypatch.setattr(proxy, "_run_response", fake_run_response)
    server = proxy.ThreadingHTTPServer(("127.0.0.1", 0), proxy.ResponsesProxyHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        connection.request(
            "POST",
            "/v1/responses",
            body=json.dumps({"input": "private transcript", "model": "ea-onemin-coder"}),
            headers={
                "Content-Type": "application/json",
                "X-EA-API-Token": token,
                "X-EA-Principal-ID": "attacker-selected-principal",
                "X-EA-Retention": "none",
            },
        )
        response = connection.getresponse()
        response_payload = json.loads(response.read().decode("utf-8"))
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert response.status == 200
    assert response.getheader("Cache-Control") == "no-store"
    assert response_payload["metadata"]["ea_retention"] == "none"
    assert captured == {
        "payload": {
            "input": "private transcript",
            "model": "ea-onemin-coder",
            "store": False,
            "stream": False,
            "background": False,
            "tools": [],
            "tool_choice": "none",
        },
        "principal_id": "memorial-service",
        "profile": "groundwork",
        "preferred_onemin_labels": (),
        "no_retention_active": True,
    }
