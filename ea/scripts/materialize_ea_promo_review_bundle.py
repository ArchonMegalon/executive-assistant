from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from promo_audio_runtime import cli, materialize_bundle as materialize_ea_promo_review_bundle


if __name__ == "__main__":
    raise SystemExit(cli("materialize_bundle"))
