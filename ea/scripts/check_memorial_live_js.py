#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import requests


BANNED_TOKENS = (
    ".rsplit(",
    ".startswith(",
    ".endswith(",
    ".strip(",
    ".items(",
    ".values(",
    "None",
    "True",
    "False",
)


def extract_inline_script(html: str) -> str:
    match = re.search(r"<script>(.*?)</script>\s*</body>", html, re.S)
    if not match:
        raise RuntimeError("inline memorial script not found")
    return match.group(1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    args = parser.parse_args()

    response = requests.get(
        args.url,
        timeout=30,
        headers={"User-Agent": "EA Memorial JS Audit/1.0"},
    )
    response.raise_for_status()
    html = response.text
    script = extract_inline_script(html)

    findings: list[str] = []
    for token in BANNED_TOKENS:
        if token in script:
            findings.append(f"banned token present: {token}")

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "memorial_live.js"
        script_path.write_text(script, encoding="utf-8")
        proc = subprocess.run(
            ["node", "--check", str(script_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            findings.append(f"node --check failed: {(proc.stderr or proc.stdout).strip()}")

    if findings:
        for finding in findings:
            print(finding)
        return 1

    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
