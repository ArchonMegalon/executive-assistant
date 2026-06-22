from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


def _load_verifier():
    path = Path(__file__).with_name("verify_audiobook_epub_quality_contract.py")
    spec = importlib.util.spec_from_file_location("verify_audiobook_epub_quality_contract", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("quality_contract_verifier_missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def materialize_audiobook_epub_quality_contract(*, output_path: Path) -> dict[str, object]:
    verifier = _load_verifier()
    receipt = verifier.verify_audiobook_epub_quality_contract()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {**receipt, "receipt_path": output_path.as_posix()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = materialize_audiobook_epub_quality_contract(output_path=args.out)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

