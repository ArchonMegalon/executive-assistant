from pathlib import Path


def test_runtime_image_uses_targeted_source_context() -> None:
    dockerfile = (Path(__file__).parents[1] / "ea" / "Dockerfile").read_text()

    assert "COPY . /tmp/src" not in dockerfile
    for required_copy in (
        "COPY ea /tmp/src/ea",
        "COPY scripts /tmp/src/scripts",
        "COPY deploy/runtime-image-verification-inputs.txt ",
        "COPY Makefile LTDs.md /tmp/src/",
        "COPY .codex-design /tmp/src/.codex-design",
        "COPY .codex-studio /tmp/src/.codex-studio",
    ):
        assert required_copy in dockerfile
