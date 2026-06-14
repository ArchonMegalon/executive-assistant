from __future__ import annotations

from app.services import memorial_memory


class _FakeMemoryRuntime:
    def __init__(self) -> None:
        self.created_items: list[dict[str, object]] = []

    def create_memory_item(self, **kwargs):
        self.created_items.append(dict(kwargs))
        return None


def test_seed_memorial_source_memories_includes_public_source_notes(monkeypatch) -> None:
    runtime = _FakeMemoryRuntime()
    monkeypatch.setattr(memorial_memory, "_load_seed_manifest", lambda slug: {"processed_keys": []})
    monkeypatch.setattr(memorial_memory, "_save_seed_manifest", lambda slug, payload: None)

    result = memorial_memory.seed_memorial_source_memories(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        memorial_payload={},
        private_profile={
            "public_source_notes": [
                {
                    "label": "Jimdo",
                    "source_url": "https://manfred-hoza.jimdofree.com/",
                    "note": "Stellt ihn als autoritaetskritisch und opferschutzorientiert dar.",
                    "confidence": "hoch",
                }
            ]
        },
        reviewer="test",
    )

    assert result["created"] == 1
    assert len(runtime.created_items) == 1
    created = runtime.created_items[0]
    assert created["category"] == "memorial_public_source_note"
    assert created["fact_json"]["memory_kind"] == "public_source_note"
    assert created["fact_json"]["label"] == "Jimdo"
    assert created["fact_json"]["source_url"] == "https://manfred-hoza.jimdofree.com/"
    assert created["fact_json"]["confidence_label"] == "hoch"
    assert created["fact_json"]["memory_axis"] in {"general", "legal", "stylistic", "episodic"}
    assert created["reviewer"] == "test"
