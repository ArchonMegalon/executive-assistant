from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from promo_audio_runtime import cli, materialize_continuous_narration as materialize_cinematic_narration_segment_chain


if __name__ == "__main__":
    raise SystemExit(cli("materialize_narration"))
