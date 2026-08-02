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
PUBLIC_EA_ADMIN_SUPPORT_FILES = {
    Path("ea/app/api/routes/landing_console.py"): Path(
        "ea/app/api/routes/landing_console_support.py"
    ),
}

PUBLIC_APP_ROUTE_ALLOWLIST: set[tuple[str, str]] = {
    ("ea/app/api/routes/landing.py", "/app"),
    ("ea/app/api/routes/landing_console.py", "/app"),
    ("ea/app/api/routes/landing_channel.py", "/app/channel-actions/{token}"),
}

MUTATION_ROUTE_METHODS = frozenset({"delete", "patch", "post", "put"})
ADMIN_OPERATOR_REDIRECT_GUARDS = frozenset(
    {
        "_admin_operator_access_redirect",
        "_admin_operator_bootstrap_redirect",
    }
)
ADMIN_OPERATOR_BOOTSTRAP_ROUTE = "/admin/bootstrap-operator"
ADMIN_OPERATOR_BOOTSTRAP_ACTION_ROUTE = "/admin/actions/bootstrap-operator"


def _depends_texts(node: ast.AST) -> list[str]:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []
    defaults = list(node.args.defaults)
    positional = list(node.args.args)
    matched = positional[-len(defaults):] if defaults else []
    return [ast.unparse(default) for _, default in zip(matched, defaults)]


def _route_paths(
    node: ast.AST,
    *,
    methods: frozenset[str] | None = None,
) -> list[str]:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []
    paths: list[str] = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name) or func.value.id != "router":
            continue
        if methods is not None and func.attr.lower() not in methods:
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


def _is_context_attribute(node: ast.AST, attribute: str) -> bool:
    return bool(
        isinstance(node, ast.Attribute)
        and node.attr == attribute
        and isinstance(node.value, ast.Name)
        and node.value.id == "context"
    )


def _executable_body(node: ast.AST) -> list[ast.stmt]:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def _call_expression(value: ast.AST | None) -> ast.Call | None:
    candidate = value
    if isinstance(candidate, ast.Await):
        candidate = candidate.value
    return candidate if isinstance(candidate, ast.Call) else None


def _return_calls_helper(
    statement: ast.stmt,
    *,
    helper_name: str,
    module_name: str = "",
) -> bool:
    if not isinstance(statement, ast.Return):
        return False
    call = _call_expression(statement.value)
    if call is None:
        return False
    if module_name:
        return bool(
            isinstance(call.func, ast.Attribute)
            and call.func.attr == helper_name
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == module_name
        )
    return bool(isinstance(call.func, ast.Name) and call.func.id == helper_name)


def _is_bootstrap_section_test(node: ast.AST) -> bool:
    if not (
        isinstance(node, ast.Compare)
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.Eq)
        and len(node.comparators) == 1
    ):
        return False
    left, right = node.left, node.comparators[0]
    return bool(
        (
            isinstance(left, ast.Name)
            and left.id == "section"
            and isinstance(right, ast.Constant)
            and right.value == "bootstrap-operator"
        )
        or (
            isinstance(right, ast.Name)
            and right.id == "section"
            and isinstance(left, ast.Constant)
            and left.value == "bootstrap-operator"
        )
    )


def _is_guarded_bootstrap_dispatch(statement: ast.stmt) -> bool:
    if not (
        isinstance(statement, ast.If)
        and _is_bootstrap_section_test(statement.test)
        and not statement.orelse
        and len(statement.body) == 1
    ):
        return False
    returned = statement.body[0]
    return bool(
        _return_calls_helper(returned, helper_name="admin_operator_bootstrap")
        or _return_calls_helper(
            returned,
            module_name="support",
            helper_name="admin_operator_bootstrap",
        )
    )


def _route_enforces_admin_redirect_guard(node: ast.AST) -> bool:
    body = _executable_body(node)
    if body and _is_guarded_bootstrap_dispatch(body[0]):
        body = body[1:]
    if len(body) < 2:
        return False
    assignment, rejection = body[0], body[1]
    if not (
        isinstance(assignment, ast.Assign)
        and len(assignment.targets) == 1
        and isinstance(assignment.targets[0], ast.Name)
    ):
        return False
    guard_variable = assignment.targets[0].id
    guard_call = _call_expression(assignment.value)
    if not (
        guard_call is not None
        and isinstance(guard_call.func, ast.Name)
        and guard_call.func.id in ADMIN_OPERATOR_REDIRECT_GUARDS
    ):
        return False
    if not (
        isinstance(rejection, ast.If)
        and not rejection.orelse
        and len(rejection.body) == 1
        and isinstance(rejection.test, ast.Compare)
        and isinstance(rejection.test.left, ast.Name)
        and rejection.test.left.id == guard_variable
        and len(rejection.test.ops) == 1
        and isinstance(rejection.test.ops[0], ast.IsNot)
        and len(rejection.test.comparators) == 1
        and isinstance(rejection.test.comparators[0], ast.Constant)
        and rejection.test.comparators[0].value is None
    ):
        return False
    returned = rejection.body[0]
    return bool(
        isinstance(returned, ast.Return)
        and isinstance(returned.value, ast.Name)
        and returned.value.id == guard_variable
    )


def _top_level_auth_raise_index(body: list[ast.stmt]) -> int | None:
    for index, statement in enumerate(body):
        if not (
            isinstance(statement, ast.If)
            and not statement.orelse
            and len(statement.body) == 1
            and isinstance(statement.test, ast.UnaryOp)
            and isinstance(statement.test.op, ast.Not)
            and _is_context_attribute(statement.test.operand, "authenticated")
        ):
            continue
        raised = statement.body[0]
        if not isinstance(raised, ast.Raise) or not isinstance(raised.exc, ast.Call):
            continue
        if not (
            isinstance(raised.exc.func, ast.Name)
            and raised.exc.func.id == "HTTPException"
        ):
            continue
        for keyword in raised.exc.keywords:
            if (
                keyword.arg == "status_code"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value in {401, 403}
            ):
                return index
    return None


def _safe_bootstrap_prefix(statement: ast.stmt) -> bool:
    """Allow no pre-auth work beyond an inert ``pass`` statement."""

    return isinstance(statement, ast.Pass)


def _expression_calls_helper(node: ast.AST | None, *, helper_name: str) -> bool:
    if node is None or isinstance(
        node,
        (
            ast.DictComp,
            ast.GeneratorExp,
            ast.Lambda,
            ast.ListComp,
            ast.SetComp,
        ),
    ):
        return False
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == helper_name
    ):
        return True
    return any(
        _expression_calls_helper(child, helper_name=helper_name)
        for child in ast.iter_child_nodes(node)
        if not isinstance(child, ast.stmt)
    )


def _same_scope_statement_calls_helper(
    statement: ast.stmt,
    *,
    helper_name: str,
) -> bool:
    if isinstance(statement, ast.Assign):
        return _expression_calls_helper(statement.value, helper_name=helper_name)
    if isinstance(statement, ast.AnnAssign):
        return _expression_calls_helper(statement.value, helper_name=helper_name)
    if isinstance(statement, ast.Expr):
        return _expression_calls_helper(statement.value, helper_name=helper_name)
    if isinstance(statement, ast.Return):
        return _expression_calls_helper(statement.value, helper_name=helper_name)
    if isinstance(statement, ast.Raise):
        return _expression_calls_helper(statement.exc, helper_name=helper_name)
    if isinstance(statement, ast.If):
        return _expression_calls_helper(statement.test, helper_name=helper_name)
    if isinstance(statement, ast.Try):
        return any(
            _same_scope_statement_calls_helper(
                nested_statement,
                helper_name=helper_name,
            )
            for nested_statement in statement.body
            if not isinstance(
                nested_statement,
                (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef),
            )
        )
    return False


def _top_level_tail_calls_helper(
    body: list[ast.stmt],
    *,
    start_index: int,
    helper_name: str,
) -> bool:
    return any(
        _same_scope_statement_calls_helper(
            statement,
            helper_name=helper_name,
        )
        for statement in body[start_index:]
    )


def _route_has_dominating_bootstrap_guard(
    node: ast.AST,
    *,
    route_path: str,
) -> bool:
    body = _executable_body(node)
    guard_index = _top_level_auth_raise_index(body)
    if guard_index is None or not all(
        _safe_bootstrap_prefix(statement) for statement in body[:guard_index]
    ):
        return False
    if route_path == ADMIN_OPERATOR_BOOTSTRAP_ROUTE:
        return bool(
            _top_level_tail_calls_helper(
                body,
                start_index=guard_index + 1,
                helper_name="is_operator_context",
            )
            and _top_level_tail_calls_helper(
                body,
                start_index=guard_index + 1,
                helper_name="operator_bootstrap_needed",
            )
        )
    if route_path == ADMIN_OPERATOR_BOOTSTRAP_ACTION_ROUTE:
        return _top_level_tail_calls_helper(
            body,
            start_index=guard_index + 1,
            helper_name="bootstrap_initial_operator_profile",
        )
    return False


def _route_body_has_admin_operator_boundary(
    node: ast.AST,
    *,
    route_path: str,
) -> bool:
    if _route_enforces_admin_redirect_guard(node):
        return True
    return _route_has_dominating_bootstrap_guard(node, route_path=route_path)


def _route_definitively_returns_support_delegate(
    node: ast.AST,
    *,
    helper_name: str,
) -> bool:
    body = _executable_body(node)
    if body and _is_guarded_bootstrap_dispatch(body[0]):
        body = body[1:]
    return bool(
        len(body) == 1
        and _return_calls_helper(
            body[0],
            module_name="support",
            helper_name=helper_name,
        )
    )


def _route_has_admin_operator_boundary(
    *,
    route_file: Path,
    route_node: ast.AST,
    route_path: str,
) -> bool:
    if _has_operator_dependency(_depends_texts(route_node)):
        return True
    if _route_body_has_admin_operator_boundary(route_node, route_path=route_path):
        return True
    support_file = PUBLIC_EA_ADMIN_SUPPORT_FILES.get(route_file)
    route_name = getattr(route_node, "name", "")
    if support_file is None or not route_name:
        return False
    if not _route_definitively_returns_support_delegate(
        route_node,
        helper_name=route_name,
    ):
        return False
    support_module = ast.parse(support_file.read_text(encoding="utf-8"))
    for support_node in support_module.body:
        if getattr(support_node, "name", "") != route_name:
            continue
        return _route_body_has_admin_operator_boundary(
            support_node,
            route_path=route_path,
        )
    return False


class RouteAuthBoundaryTests(unittest.TestCase):
    def test_admin_boundary_classifier_rejects_non_dominating_guards(self) -> None:
        before_guard = ast.parse(
            """
async def route(request, context):
    payload = await request.body()
    redirect = _admin_operator_access_redirect(context=context)
    if redirect is not None:
        return redirect
    return payload
"""
        ).body[0]
        ignored_rejection = ast.parse(
            """
def route(context):
    redirect = _admin_operator_access_redirect(context=context)
    if redirect is not None:
        audit(redirect)
    return sensitive_payload()
"""
        ).body[0]
        nested_auth_raise = ast.parse(
            """
def route(context):
    if False:
        if not context.authenticated:
            raise HTTPException(status_code=403)
    return bootstrap_initial_operator_profile()
"""
        ).body[0]
        unreturned_delegate = ast.parse(
            """
def admin_root(request, context):
    support.admin_root(request=request, context=context)
    return sensitive_payload()
"""
        ).body[0]
        pre_auth_call_assignment = ast.parse(
            """
def route(request, context):
    return_to = normalize(request.query_params)
    if not context.authenticated:
        raise HTTPException(status_code=403)
    if is_operator_context(context):
        return ready()
    if operator_bootstrap_needed():
        return bootstrap()
"""
        ).body[0]
        pre_auth_await_assignment = ast.parse(
            """
async def route(request, context):
    payload = await request.body()
    if not context.authenticated:
        raise HTTPException(status_code=403)
    return bootstrap_initial_operator_profile(payload)
"""
        ).body[0]
        pre_auth_mutation = ast.parse(
            """
def route(context):
    audit.append(context.principal_id)
    if not context.authenticated:
        raise HTTPException(status_code=403)
    return bootstrap_initial_operator_profile()
"""
        ).body[0]
        dead_tail_helper = ast.parse(
            """
def route(context):
    if not context.authenticated:
        raise HTTPException(status_code=403)
    if False:
        return bootstrap_initial_operator_profile()
    return sensitive_payload()
"""
        ).body[0]
        nested_tail_helper = ast.parse(
            """
def route(context):
    if not context.authenticated:
        raise HTTPException(status_code=403)
    def hidden():
        return bootstrap_initial_operator_profile()
    return sensitive_payload()
"""
        ).body[0]
        conditional_delegate = ast.parse(
            """
def admin_root(request, context):
    if context.authenticated:
        return support.admin_root(request=request, context=context)
    return sensitive_payload()
"""
        ).body[0]

        self.assertFalse(
            _route_body_has_admin_operator_boundary(
                before_guard,
                route_path="/admin/actions/example",
            )
        )
        self.assertFalse(
            _route_body_has_admin_operator_boundary(
                ignored_rejection,
                route_path="/admin/actions/example",
            )
        )
        self.assertFalse(
            _route_body_has_admin_operator_boundary(
                nested_auth_raise,
                route_path=ADMIN_OPERATOR_BOOTSTRAP_ACTION_ROUTE,
            )
        )
        self.assertFalse(
            _route_definitively_returns_support_delegate(
                unreturned_delegate,
                helper_name="admin_root",
            )
        )
        for unsafe_prefix in (
            pre_auth_call_assignment,
            pre_auth_await_assignment,
            pre_auth_mutation,
        ):
            self.assertFalse(
                _route_has_dominating_bootstrap_guard(
                    unsafe_prefix,
                    route_path=ADMIN_OPERATOR_BOOTSTRAP_ACTION_ROUTE,
                )
            )
        for hidden_helper in (dead_tail_helper, nested_tail_helper):
            self.assertFalse(
                _route_has_dominating_bootstrap_guard(
                    hidden_helper,
                    route_path=ADMIN_OPERATOR_BOOTSTRAP_ACTION_ROUTE,
                )
            )
        self.assertFalse(
            _route_definitively_returns_support_delegate(
                conditional_delegate,
                helper_name="admin_root",
            )
        )

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
                for route_path in _route_paths(node):
                    if not route_path.startswith("/admin"):
                        continue
                    if not _route_has_admin_operator_boundary(
                        route_file=path,
                        route_node=node,
                        route_path=route_path,
                    ):
                        missing.append(f"{path}:{getattr(node, 'lineno', '?')}:{route_path}")
        self.assertEqual(missing, [], "public-mounted /admin routes missing operator dependency")



    def test_public_landing_admin_routes_require_operator_context(self) -> None:
        missing: list[str] = []
        for path in PUBLIC_EA_ADMIN_ROUTE_FILES:
            module = ast.parse(path.read_text(encoding="utf-8"))
            for node in module.body:
                for route_path in _route_paths(node):
                    if not route_path.startswith("/admin"):
                        continue
                    if not _route_has_admin_operator_boundary(
                        route_file=path,
                        route_node=node,
                        route_path=route_path,
                    ):
                        missing.append(f"{path}:{getattr(node, 'lineno', '?')}:{route_path}")
        self.assertEqual(
            missing,
            [],
            "public landing admin routes missing operator dependency",
        )


if __name__ == "__main__":
    unittest.main()
