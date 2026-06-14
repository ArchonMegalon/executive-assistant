#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".codex-design" / "product" / "MEMORIAL_PHRASE_BANK.manfred.generated.json"


def main() -> int:
    payload = {
        "contract_name": "ea.memorial_phrase_bank",
        "generated_by": "scripts/materialize_memorial_phrase_bank.py",
        "slug": "manfred",
        "phrases": [
            {
                "id": "contact_opening",
                "purpose": "direct_contact_opening",
                "audio_text": "Worum geht es?",
                "visible_text": "Worum geht es?",
                "min_f1": 0.92,
                "critical_tokens": ["worum", "geht", "es"],
                "status": "approved",
            },
            {
                "id": "present_world_guardrail",
                "purpose": "current_world_memory_boundary",
                "audio_text": "Das kann ich aus meiner Erinnerung nicht sagen.",
                "visible_text": "Das kann ich aus meiner Erinnerung nicht sagen. Sag mir den aktuellen Stand kurz, dann ordne ich es mit dir.",
                "min_f1": 0.92,
                "critical_tokens": ["erinnerung", "nicht", "sagen"],
                "status": "approved",
            },
            {
                "id": "weather_guardrail",
                "purpose": "weather_memory_boundary",
                "audio_text": "Zum Wetter brauche ich den Ort.",
                "visible_text": "Zum Wetter brauche ich den Ort. Sag ihn mir kurz, dann bleibe ich bei deiner Schilderung.",
                "min_f1": 0.92,
                "critical_tokens": ["wetter", "ort"],
                "status": "approved",
            },
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "pass", "output": OUTPUT.as_posix()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
