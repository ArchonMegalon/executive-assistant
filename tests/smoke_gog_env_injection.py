from pathlib import Path


def test_gog_env_mapping_is_not_crosswired() -> None:
    src = Path('ea/app/gog.py').read_text(encoding='utf-8')
    assert 'LITELLM_API_KEY={os.environ.get(\'GEMINI_API_KEY\'' not in src
    assert 'def _llm_env_values()' in src
    assert 'if litellm_key:' in src


def test_gog_cli_uses_conditional_env_args() -> None:
    src = Path('ea/app/gog.py').read_text(encoding='utf-8')
    assert 'cmd = ["docker", "exec", *_llm_env_cli_args(),' in src
