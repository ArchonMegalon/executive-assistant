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


if __name__ == "__main__":
    unittest.main()
