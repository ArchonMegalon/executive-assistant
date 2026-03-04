from __future__ import annotations

import ast
from pathlib import Path

src = Path('/docker/EA/ea/app/poll_listener.py').read_text(encoding='utf-8')
mod = ast.parse(src)
fn_node = None
for n in mod.body:
    if isinstance(n, ast.FunctionDef) and n.name == '_humanize_agent_report':
        fn_node = n
        break
assert fn_node is not None, 'missing _humanize_agent_report'

ns: dict[str, object] = {}
exec(compile(ast.Module(body=[fn_node], type_ignores=[]), filename='<smoke>', mode='exec'), ns)
fn = ns['_humanize_agent_report']

assert 'Execution backend is temporarily unavailable' in fn("Error: [Errno 2] No such file or directory: 'docker'")
assert 'AI provider authentication failed' in fn('HTTP 400: litellm.BadRequestError: Vertex_ai_betaException ... API_KEY_INVALID ... API key expired')
assert 'could not complete that request' in fn('Error: some backend badrequesterror stack')
assert fn('all good') == 'all good'

print('PASS: bot error sanitization mappings')
