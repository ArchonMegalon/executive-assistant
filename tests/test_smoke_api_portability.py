from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke_api.sh"


def test_smoke_api_temp_dir_is_repo_local_and_overridable() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "EA_SMOKE_TMP_DIR" in source
    assert "SMOKE_TMP_DIR" in source
    assert "/docker/" + "EA/.smoke_tmp" not in source
    bad_python_literal = 'Path("' + "${SMOKE_TMP_DIR}"
    assert bad_python_literal not in source
    assert 'Path(os.environ["SMOKE_TMP_DIR"])' in source


def test_smoke_api_shell_syntax_is_valid() -> None:
    result = subprocess.run(["bash", "-n", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr
