from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from promo_audio_runtime import cli, verify_quality as verify_ea_promo_quality_rubric


def write_ea_promo_quality_rubric(*, artifact_dir):
    return verify_ea_promo_quality_rubric(artifact_dir, write=True)


if __name__ == "__main__":
    raise SystemExit(cli("verify_quality"))
