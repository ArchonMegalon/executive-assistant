#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${OPENVOICE_VENV_DIR:-$ROOT_DIR/.venv-openvoice}"
CHECKPOINT_ROOT="${OPENVOICE_CHECKPOINT_ROOT:-$ROOT_DIR/.models/openvoice}"
CHECKPOINT_URL="${OPENVOICE_CHECKPOINT_ZIP_URL:-https://myshell-public-repo-hosting.s3.amazonaws.com/openvoice/checkpoints_v2_0417.zip}"
CONVERTER_CONFIG_URL="${OPENVOICE_CONVERTER_CONFIG_URL:-https://huggingface.co/rsxdalv/OpenVoiceV2/resolve/main/checkpoints_v2/converter/config.json?download=true}"
CONVERTER_CHECKPOINT_URL="${OPENVOICE_CONVERTER_CHECKPOINT_URL:-https://huggingface.co/rsxdalv/OpenVoiceV2/resolve/main/checkpoints_v2/converter/checkpoint.pth?download=true}"
SOURCE_DIR="${OPENVOICE_SOURCE_DIR:-$ROOT_DIR/third_party/OpenVoice}"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"
MICROMAMBA_ROOT="${OPENVOICE_MICROMAMBA_ROOT:-$ROOT_DIR/.micromamba}"
MICROMAMBA_BIN="$MICROMAMBA_ROOT/bin/micromamba"

mkdir -p "$CHECKPOINT_ROOT"

bootstrap_micromamba_python() {
  mkdir -p "$MICROMAMBA_ROOT/bin"
  if [ ! -x "$MICROMAMBA_BIN" ]; then
    curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest -o /tmp/micromamba.tar.bz2
    tar -xjf /tmp/micromamba.tar.bz2 -C "$MICROMAMBA_ROOT" bin/micromamba
    rm -f /tmp/micromamba.tar.bz2
  fi
  "$MICROMAMBA_BIN" create -y -p "$VENV_DIR" python=3.11 pip
  PYTHON_BIN="$VENV_DIR/bin/python"
}

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  bootstrap_micromamba_python
elif ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)
PY
then
  bootstrap_micromamba_python
elif [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

PYTHON_EXE="$VENV_DIR/bin/python"
PIP_EXE="$VENV_DIR/bin/pip"
"$PIP_EXE" install --upgrade pip wheel setuptools
"$PIP_EXE" install -r "$ROOT_DIR/requirements.txt"
"$PIP_EXE" install -r "$ROOT_DIR/requirements-openvoice.txt"

if [ ! -f "$SOURCE_DIR/openvoice/models.py" ]; then
  mkdir -p "$(dirname "$SOURCE_DIR")"
  rm -rf "$SOURCE_DIR"
  git clone --depth 1 https://github.com/myshell-ai/OpenVoice.git "$SOURCE_DIR"
fi

TMP_ZIP="$(mktemp --suffix=.zip)"
trap 'rm -f "$TMP_ZIP"' EXIT

if [ ! -f "$CHECKPOINT_ROOT/checkpoints_v2/converter/config.json" ] || [ ! -f "$CHECKPOINT_ROOT/checkpoints_v2/converter/checkpoint.pth" ]; then
  mkdir -p "$CHECKPOINT_ROOT/checkpoints_v2/converter"
  if curl -fL "$CHECKPOINT_URL" -o "$TMP_ZIP"; then
    unzip -o "$TMP_ZIP" -d "$CHECKPOINT_ROOT" || true
  fi
fi

if [ ! -f "$CHECKPOINT_ROOT/checkpoints_v2/converter/config.json" ]; then
  curl -fL "$CONVERTER_CONFIG_URL" -o "$CHECKPOINT_ROOT/checkpoints_v2/converter/config.json"
fi

if [ ! -f "$CHECKPOINT_ROOT/checkpoints_v2/converter/checkpoint.pth" ]; then
  curl -fL "$CONVERTER_CHECKPOINT_URL" -o "$CHECKPOINT_ROOT/checkpoints_v2/converter/checkpoint.pth"
fi

echo "OPENVOICE_VENV_DIR=$VENV_DIR"
echo "OPENVOICE_CHECKPOINT_ROOT=$CHECKPOINT_ROOT"
echo "OPENVOICE_SOURCE_DIR=$SOURCE_DIR"
