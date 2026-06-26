from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from promo_audio_runtime import cli, materialize_video as materialize_ea_fallback_promo_video


if __name__ == "__main__":
    raise SystemExit(cli("materialize_video"))
