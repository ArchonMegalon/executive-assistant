from __future__ import annotations

import argparse
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
EA_ROOT = SCRIPT_PATH.parents[1]
REPO_ROOT = SCRIPT_PATH.parents[2]


def verify_cinematic_media_pipeline_contract() -> dict[str, object]:
    scripts = EA_ROOT / "scripts"
    audiobook = (EA_ROOT / "app" / "services" / "audiobook_epub_pipeline.py").read_text(encoding="utf-8")
    promo_runtime = (scripts / "promo_audio_runtime.py").read_text(encoding="utf-8") if (scripts / "promo_audio_runtime.py").is_file() else ""
    checks = {
        "ongoing_not_scene_bound": "scene_bound" in promo_runtime and "False" in promo_runtime,
        "voice_audition_contract": "_discover_or_build_cinematic_master_audio" in audiobook,
        "audio_quality_gates": "waiting_for_unmixr_export" in audiobook,
        "promo_video_fallback_truth": "provider_ready" in promo_runtime and "False" in promo_runtime,
        "audiobook_m4b_structure_probe_present": (scripts / "materialize_audiobook_m4b_structure_probe.py").is_file(),
        "continuity_demo_scripts_present": (scripts / "materialize_cinematic_narration_continuity_demo.py").is_file()
        and (scripts / "verify_cinematic_narration_continuity_demo.py").is_file(),
        "promo_quality_rubric_requires_continuity_demo": "continuous_narration_demo_reviewable" in promo_runtime,
        "implementation_contains_audition_and_m4b_hooks": "_merge_m4b_if_ready" in audiobook and "_CINEMATIC_MASTER_SINGLE_PASS_MODE" in audiobook,
    }
    issues = [f"cinematic_media_check_failed:{key}" for key, value in checks.items() if value is not True]
    return {
        "contract_name": "ea.cinematic_narration_and_promo_pipeline.v1",
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the cinematic narration and promo media pipeline contract.")
    parser.parse_args()
    payload = verify_cinematic_media_pipeline_contract()
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
