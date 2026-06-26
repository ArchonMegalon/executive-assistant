from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from promo_audio_runtime import cli, verify_continuous_narration


def verify_cinematic_narration_continuity_demo(artifact_dir):
    return verify_continuous_narration(artifact_dir)


if __name__ == "__main__":
    raise SystemExit(cli("verify_narration"))
