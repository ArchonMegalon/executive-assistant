from __future__ import annotations

import ast
import importlib
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
EA_DIR = ROOT / "ea"
for path in (str(ROOT), str(EA_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


def _import_first(*names: str):
    last_exc = None
    for name in names:
        try:
            return importlib.import_module(name)
        except Exception as exc:  # pragma: no cover - smoke fallback path
            last_exc = exc
    raise last_exc  # type: ignore[misc]


def _pass(name: str) -> None:
    print(f"[SMOKE][HOST][PASS] {name}")


def _import_from_path(module_name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module spec for {module_name} from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _import_or_parse(import_name: str, path: pathlib.Path) -> bool:
    try:
        _import_first(import_name)
        return True
    except Exception:
        if path.exists():
            ast.parse(path.read_text(encoding="utf-8"))
            return True
    return False


def test_future_intelligence_modules() -> None:
    assert _import_first("app.intelligence.profile", "app.personalization.profile")
    assert _import_first("app.intelligence.future_situations")
    assert _import_first("app.intelligence.readiness")
    assert _import_first("app.intelligence.scores")
    assert _import_first("app.intelligence.preparation_planner")
    assert _import_first("app.intelligence.critical_lane")
    assert _import_first("app.intelligence.modes")
    assert _import_first("app.intelligence.epics")
    _pass("v1.13 future intelligence module presence")


def test_regression_contracts() -> None:
    rg = _import_first("app.render_guard")
    assert rg.classify_markupgo_error("Invalid template id") == "invalid_template_id"
    assert rg.classify_markupgo_error("EA render guard: markupgo breaker open") == "breaker_open"
    assert isinstance(rg.known_good_template_ids(), list)

    reg = _import_first("app.repair_registry")
    recipes = getattr(reg, "REPAIR_RECIPES")
    assert "renderer_template_swap" in recipes
    assert "renderer_text_only" in recipes
    assert recipes["renderer_template_swap"]["max_attempts"] == 1
    assert "retry_render_step" in recipes["renderer_template_swap"]["typed_actions"]

    try:
        safety = _import_first("app.telegram.safety")
    except Exception:
        safety = _import_from_path(
            "ea_smoke_telegram_safety",
            ROOT / "ea/app/telegram/safety.py",
        )
    sanitize = getattr(safety, "sanitize_for_telegram")
    sample = (
        'MarkupGo API HTTP 400 {"statusCode":400,"message":"bad"}\n'
        "LLM Gateway: direct provider key configured."
    )
    out = sanitize(sample, "cid123", mode="simplified-first")
    assert "statusCode" not in out
    assert "LLM Gateway" not in out
    assert "MarkupGo API HTTP 400" not in out

    assert _import_or_parse("app.supervisor", ROOT / "ea/app/supervisor.py")
    assert _import_or_parse("app.integrations.avomap.service", ROOT / "ea/app/integrations/avomap/service.py")
    assert _import_or_parse("app.queue", ROOT / "ea/app/queue.py") or _import_or_parse(
        "app.operator", ROOT / "ea/app/operator/__init__.py"
    )
    assert _import_or_parse("app.llm_gateway", ROOT / "ea/app/llm_gateway.py") or _import_or_parse(
        "app.contracts.llm_gateway", ROOT / "ea/app/contracts/llm_gateway.py"
    ) or _import_or_parse("app.llm", ROOT / "ea/app/llm.py")
    assert _import_or_parse("app.scheduler", ROOT / "ea/app/scheduler.py") or _import_or_parse(
        "app.planner", ROOT / "ea/app/planner.py"
    )
    # app.telegram may fail to import in host-only smoke when optional deps
    # are missing; verify safety contract file instead.
    assert (ROOT / "ea/app/telegram.py").exists()
    assert (ROOT / "ea/app/telegram/safety.py").exists()
    assert _import_first("app.intelligence.household_graph", "app.policy.household")

    try:
        briefings = _import_first("app.briefings")
        assert hasattr(briefings, "_runtime_confidence_note")
    except Exception:
        brief_src = (ROOT / "ea/app/briefings.py").read_text(encoding="utf-8")
        ast.parse(brief_src)
        assert "def _runtime_confidence_note(" in brief_src
    _pass("v1.13 regression contracts")


def test_release_scaffold() -> None:
    scripts = ROOT / "scripts"
    assert scripts.exists()
    _pass("v1.13 release scaffold")


if __name__ == "__main__":
    test_future_intelligence_modules()
    test_regression_contracts()
    test_release_scaffold()
