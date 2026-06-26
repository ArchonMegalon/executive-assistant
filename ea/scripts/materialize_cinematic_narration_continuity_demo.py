from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from promo_audio_runtime import cli, materialize_continuous_narration, materialize_fallback_promo


def materialize_cinematic_narration_continuity_demo(*, artifact_dir, generated_at="", voice="awb"):
    if not (artifact_dir / "promo.json").is_file():
        materialize_fallback_promo(output_dir=artifact_dir, generated_at=generated_at)
    return materialize_continuous_narration(artifact_dir=artifact_dir, generated_at=generated_at, voice=voice)


if __name__ == "__main__":
    raise SystemExit(cli("materialize_narration"))
