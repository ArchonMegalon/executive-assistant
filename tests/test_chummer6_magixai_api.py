from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "chummer6_magixai_api.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("chummer6_magixai_api", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_magixai_api_base_urls_prefer_official_www_first() -> None:
    magix = _load_module()

    urls = magix.magixai_api_base_urls("https://beta.aimagicx.com/api/v1")

    assert urls[0] == "https://www.aimagicx.com/api/v1"
    assert "https://beta.aimagicx.com/api/v1" in urls


def test_normalize_magixai_base_url_strips_endpoint_suffixes() -> None:
    magix = _load_module()

    assert magix.normalize_magixai_base_url("https://www.aimagicx.com/api/v1/chat/completions") == "https://www.aimagicx.com/api/v1"
    assert magix.normalize_magixai_base_url("https://beta.aimagicx.com/api") == "https://beta.aimagicx.com/api/v1"


def test_magixai_size_variants_include_raw_and_shape_aliases() -> None:
    magix = _load_module()

    assert magix.magixai_size_variants(1536, 1024) == ["landscape_4_3", "1536x1024", "1792x1024", "landscape_16_9"]
    assert magix.magixai_size_variants(1024, 1024) == ["square_hd", "1024x1024", "square"]


def test_magixai_looks_like_html_rejects_next_shell() -> None:
    magix = _load_module()

    assert magix.magixai_looks_like_html(content_type="text/html; charset=utf-8", body="<!DOCTYPE html><html>") is True
    assert magix.magixai_looks_like_html(content_type="application/json", body='{"ok":true}') is False
