from pathlib import Path


def test_auth_flow_avoids_shell_interpolation_for_email_cleanup() -> None:
    src = Path('ea/app/poll_listener.py').read_text(encoding='utf-8')
    assert "def _openclaw_candidates(" in src
    trigger_start = src.find('async def trigger_auth_flow(')
    assert trigger_start >= 0, 'trigger_auth_flow missing'
    cb_start = src.find('async def handle_callback(', trigger_start)
    block = src[trigger_start:cb_start if cb_start > trigger_start else None]

    assert "'sh', '-c'" not in block
    assert "candidates = _openclaw_candidates" in block
    assert "for t_openclaw in candidates:" in block
    assert "gog', 'auth', 'remove', email" in block
