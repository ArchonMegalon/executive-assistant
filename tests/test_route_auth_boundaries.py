from __future__ import annotations

import ast
import unittest
from pathlib import Path


PUBLIC_EA_PUBLIC_ROUTE_FILES = (
    Path("ea/app/api/routes/landing.py"),
    Path("ea/app/api/routes/landing_console.py"),
    Path("ea/app/api/routes/landing_channel.py"),
    Path("ea/app/api/routes/landing_actions.py"),
    Path("ea/app/api/routes/landing_objects.py"),
    Path("ea/app/api/routes/landing_workspace.py"),
    Path("ea/app/api/routes/landing_property.py"),
)

PUBLIC_EA_ADMIN_ROUTE_FILES = (
    Path("ea/app/api/routes/landing_console.py"),
    Path("ea/app/api/routes/landing.py"),
)

PUBLIC_APP_ROUTE_ALLOWLIST: set[tuple[str, str]] = {
    ("ea/app/api/routes/landing.py", "/app"),
    ("ea/app/api/routes/landing_console.py", "/app"),
    ("ea/app/api/routes/landing_channel.py", "/app/channel-actions/{token}"),
}

PUBLIC_MEMORIAL_OPERATOR_ROUTE_FILE = Path("ea/app/api/routes/public_memorial_operator.py")
MEMORIAL_VOICE_CONFIG_ROUTE_PATH = "/memorials/{slug}/voice-config"
MEMORIAL_OPERATOR_MUTATION_ROUTES = (
    "/memorials/{slug}/voice-ab/rate",
    "/memorials/{slug}/voice-ab-admin/finalize",
    "/memorials/{slug}/voice-ab-admin/maintain",
    "/memorials/{slug}/voice-clone",
    "/memorials/{slug}/voice-profile/build",
    "/memorials/{slug}/voice-config",
)


def _depends_texts(node: ast.AST) -> list[str]:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []
    defaults = list(node.args.defaults)
    positional = list(node.args.args)
    matched = positional[-len(defaults):] if defaults else []
    return [ast.unparse(default) for _, default in zip(matched, defaults)]


def _route_paths(node: ast.AST) -> list[str]:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []
    paths: list[str] = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name) or func.value.id != "router":
            continue
        if not decorator.args:
            continue
        first_arg = decorator.args[0]
        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            paths.append(first_arg.value)
    return paths


def _has_auth_dependency(depends_texts: list[str]) -> bool:
    return any(
        marker in text
        for text in depends_texts
        for marker in (
            "Depends(get_request_context)",
            "Depends(deps.get_request_context)",
            "Depends(require_operator_context)",
            "Depends(deps.require_operator_context)",
        )
    )


def _has_operator_dependency(depends_texts: list[str]) -> bool:
    return any(
        marker in text
        for text in depends_texts
        for marker in (
            "Depends(require_operator_context)",
            "Depends(deps.require_operator_context)",
        )
    )


def _route_has_helper_call(node: ast.AST, helper_name: str) -> bool:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name) and child.func.id == helper_name:
            return True
    return False


class RouteAuthBoundaryTests(unittest.TestCase):
    def test_public_mounted_app_routes_keep_auth_boundary(self) -> None:
        missing: list[str] = []
        for path in PUBLIC_EA_PUBLIC_ROUTE_FILES:
            module = ast.parse(path.read_text(encoding="utf-8"))
            for node in module.body:
                depends_texts = _depends_texts(node)
                for route_path in _route_paths(node):
                    if not route_path.startswith("/app"):
                        continue
                    route_key = (path.as_posix(), route_path)
                    if route_key in PUBLIC_APP_ROUTE_ALLOWLIST:
                        continue
                    if not _has_auth_dependency(depends_texts):
                        missing.append(f"{path}:{getattr(node, 'lineno', '?')}:{route_path}")
        self.assertEqual(missing, [], "public-mounted /app routes missing auth dependency")

    def test_public_mounted_admin_routes_require_operator_context(self) -> None:
        missing: list[str] = []
        for path in PUBLIC_EA_PUBLIC_ROUTE_FILES:
            module = ast.parse(path.read_text(encoding="utf-8"))
            for node in module.body:
                depends_texts = _depends_texts(node)
                for route_path in _route_paths(node):
                    if not route_path.startswith("/admin"):
                        continue
                    if not _has_operator_dependency(depends_texts):
                        missing.append(f"{path}:{getattr(node, 'lineno', '?')}:{route_path}")
        self.assertEqual(missing, [], "public-mounted /admin routes missing operator dependency")

    def test_memorial_voice_config_route_keeps_fail_closed_gating_helpers(self) -> None:
        module = ast.parse(PUBLIC_MEMORIAL_OPERATOR_ROUTE_FILE.read_text(encoding="utf-8"))
        for node in module.body:
            if MEMORIAL_VOICE_CONFIG_ROUTE_PATH not in _route_paths(node):
                continue
            self.assertTrue(_route_has_helper_call(node, "_require_public_memorial_operator_surface_enabled"))
            self.assertTrue(_route_has_helper_call(node, "_require_public_memorial_write_access"))
            break
        else:
            self.fail(f"route missing: {PUBLIC_MEMORIAL_OPERATOR_ROUTE_FILE}:{MEMORIAL_VOICE_CONFIG_ROUTE_PATH}")

    def test_memorial_operator_mutation_routes_keep_mutation_guard(self) -> None:
        module = ast.parse(PUBLIC_MEMORIAL_OPERATOR_ROUTE_FILE.read_text(encoding="utf-8"))
        for route_path in MEMORIAL_OPERATOR_MUTATION_ROUTES:
            for node in module.body:
                if route_path not in _route_paths(node):
                    continue
                self.assertTrue(
                    _route_has_helper_call(node, "_enforce_operator_mutation_limits"),
                    f"route missing operator mutation guard: {route_path}",
                )
                break
            else:
                self.fail(f"route missing: {PUBLIC_MEMORIAL_OPERATOR_ROUTE_FILE}:{route_path}")

    def test_public_landing_admin_routes_require_operator_context(self) -> None:
        missing: list[str] = []
        for path in PUBLIC_EA_ADMIN_ROUTE_FILES:
            module = ast.parse(path.read_text(encoding="utf-8"))
            for node in module.body:
                depends_texts = _depends_texts(node)
                for route_path in _route_paths(node):
                    if not route_path.startswith("/admin"):
                        continue
                    if not _has_operator_dependency(depends_texts):
                        missing.append(f"{path}:{getattr(node, 'lineno', '?')}:{route_path}")
        self.assertEqual(
            missing,
            [],
            "public landing admin routes missing operator dependency",
        )


if __name__ == "__main__":
    unittest.main()
