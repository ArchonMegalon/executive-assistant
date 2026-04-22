from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "browseract_template_service_worker.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("browseract_template_service_worker", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BrowserActTemplateWorkerTests(unittest.TestCase):
    def test_failure_code_maps_onemin_auth_cors_block_to_challenge_required(self) -> None:
        module = _load_module()

        detail = (
            "template_worker_failed: Submit Login:auth_request_failed:console:Access to XMLHttpRequest at "
            "'https://api.1min.ai/auth/login' from origin 'https://app.1min.ai' has been blocked by "
            "CORS policy: No 'Access-Control-Allow-Origin' header is present on the requested resource."
        )

        self.assertEqual(module._failure_code_from_error_text(detail), "challenge_required")

    def test_failure_code_maps_onemin_auth_csp_block_to_challenge_required(self) -> None:
        module = _load_module()

        detail = (
            "template_worker_failed: Submit Login:auth_request_failed:console:[Report Only] Refused to connect to "
            "'https://api.1min.ai/auth/login' because it violates the following Content Security Policy directive: "
            "\"connect-src 'none'\"."
        )

        self.assertEqual(module._failure_code_from_error_text(detail), "challenge_required")

    def test_worker_script_fails_fast_on_onemin_auth_request_failure(self) -> None:
        module = _load_module()
        script = module._template_node_script()

        self.assertIn("function noteAuthRequestFailure(detail)", script)
        self.assertIn("async function detectAuthUiFailure(config)", script)
        self.assertIn("function throwIfAuthRequestFailed()", script)
        self.assertIn("async function throwIfAuthUiFailed()", script)
        self.assertIn("auth_request_failed", script)
        self.assertIn("invalid_credentials", script)
        self.assertIn("url.includes('api.1min.ai/auth/')", script)
        self.assertIn("text.includes('api.1min.ai/auth/login')", script)
        self.assertIn("auth_failure_text_markers", script)

    def test_worker_supports_joining_a_named_docker_network(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn("EA_UI_SERVICE_DOCKER_NETWORK", source)
        self.assertIn('command.extend(["--network", docker_network])', source)


if __name__ == "__main__":
    unittest.main()
