from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class OpenVoiceServiceConfig:
    base_dir: Path
    checkpoint_root: Path
    converter_dir: Path
    device: str
    base_tts: str
    piper_bin: str
    piper_model: str
    piper_model_alt: str
    piper_default_variant: str
    piper_alt_variant: str
    piper_speaker: int | None
    espeak_bin: str
    sample_rate: int


def _env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_optional_int(name: str) -> int | None:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _run_command(*, cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=300,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _normalize_variant(value: object) -> str:
    normalized = "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum() or ch in {"-", "_"})
    return normalized[:40].strip("-_")


def _ffmpeg_bin() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def _safe_voice_id(value: str) -> str:
    normalized = "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum() or ch in {"-", "_"})
    return normalized[:80].strip("-_")


def load_openvoice_service_config() -> OpenVoiceServiceConfig:
    base_dir = Path(str(os.environ.get("OPENVOICE_DATA_DIR") or "/tmp/openvoice")).expanduser()
    checkpoint_root = Path(str(os.environ.get("OPENVOICE_CHECKPOINT_ROOT") or "/models/openvoice")).expanduser()
    converter_dir = checkpoint_root / str(os.environ.get("OPENVOICE_CONVERTER_SUBDIR") or "checkpoints_v2/converter").strip("/")
    device = str(os.environ.get("OPENVOICE_DEVICE") or ("cuda:0" if os.path.exists("/dev/nvidia0") else "cpu")).strip() or "cpu"
    base_tts = str(os.environ.get("OPENVOICE_BASE_TTS") or "").strip().lower() or "espeak"
    piper_bin = str(os.environ.get("PIPER_BIN") or shutil.which("piper") or "").strip()
    piper_model = str(os.environ.get("PIPER_MODEL_PATH") or "").strip()
    piper_model_alt = str(os.environ.get("PIPER_MODEL_PATH_ALT") or "").strip()
    espeak_bin = str(os.environ.get("ESPEAK_BIN") or shutil.which("espeak-ng") or shutil.which("espeak") or "").strip()
    return OpenVoiceServiceConfig(
        base_dir=base_dir,
        checkpoint_root=checkpoint_root,
        converter_dir=converter_dir,
        device=device,
        base_tts=base_tts,
        piper_bin=piper_bin,
        piper_model=piper_model,
        piper_model_alt=piper_model_alt,
        piper_default_variant=_normalize_variant(os.environ.get("PIPER_DEFAULT_VARIANT") or "high") or "high",
        piper_alt_variant=_normalize_variant(os.environ.get("PIPER_ALT_VARIANT") or "balanced") or "balanced",
        piper_speaker=_env_optional_int("PIPER_SPEAKER_ID"),
        espeak_bin=espeak_bin,
        sample_rate=_env_int("OPENVOICE_SAMPLE_RATE", 24000),
    )


class OpenVoiceRuntime:
    def __init__(self, config: OpenVoiceServiceConfig) -> None:
        self.config = config
        self._loaded = False
        self._torch = None
        self._tone_color_converter = None
        self._load_lock = threading.Lock()
        self._voice_locks: dict[str, threading.Lock] = {}
        self._voice_locks_guard = threading.Lock()

    def openvoice_source_dir(self) -> Path:
        return Path(
            str(
                os.environ.get("OPENVOICE_SOURCE_DIR")
                or (Path(__file__).resolve().parents[2] / "third_party" / "OpenVoice")
            )
        ).expanduser()

    def _ensure_source_path(self) -> None:
        source_dir = self.openvoice_source_dir()
        if not (source_dir / "openvoice" / "models.py").is_file():
            raise RuntimeError(f"openvoice_source_missing:{source_dir}")
        source_dir_text = str(source_dir)
        if source_dir_text not in sys.path:
            sys.path.insert(0, source_dir_text)

    def _voice_lock(self, voice_id: str) -> threading.Lock:
        normalized = _safe_voice_id(voice_id)
        if not normalized:
            raise ValueError("voice_id_invalid")
        with self._voice_locks_guard:
            lock = self._voice_locks.get(normalized)
            if lock is None:
                lock = threading.Lock()
                self._voice_locks[normalized] = lock
            return lock

    @staticmethod
    def _build_tone_color_converter_class():
        from openvoice import utils
        from openvoice.mel_processing import spectrogram_torch
        from openvoice.models import SynthesizerTrn
        import librosa
        import numpy as np
        import soundfile
        import torch

        class _OpenVoiceBaseClass:
            def __init__(self, config_path: str, device: str = "cuda:0"):
                if "cuda" in device:
                    assert torch.cuda.is_available()
                hps = utils.get_hparams_from_file(config_path)
                model = SynthesizerTrn(
                    len(getattr(hps, "symbols", [])),
                    hps.data.filter_length // 2 + 1,
                    n_speakers=hps.data.n_speakers,
                    **hps.model,
                ).to(device)
                model.eval()
                self.model = model
                self.hps = hps
                self.device = device

            def load_ckpt(self, ckpt_path: str) -> None:
                checkpoint_dict = torch.load(ckpt_path, map_location=torch.device(self.device))
                self.model.load_state_dict(checkpoint_dict["model"], strict=False)

        class _ToneColorConverter(_OpenVoiceBaseClass):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                if kwargs.get("enable_watermark", True):
                    import wavmark

                    self.watermark_model = wavmark.load_model().to(self.device)
                else:
                    self.watermark_model = None
                self.version = getattr(self.hps, "_version_", "v1")

            def extract_se(self, ref_wav_list: list[str] | str, se_save_path: str | None = None):
                if isinstance(ref_wav_list, str):
                    ref_wav_list = [ref_wav_list]
                gs = []
                for fname in ref_wav_list:
                    audio_ref, _sr = librosa.load(fname, sr=self.hps.data.sampling_rate)
                    y = torch.FloatTensor(audio_ref).to(self.device).unsqueeze(0)
                    y = spectrogram_torch(
                        y,
                        self.hps.data.filter_length,
                        self.hps.data.sampling_rate,
                        self.hps.data.hop_length,
                        self.hps.data.win_length,
                        center=False,
                    ).to(self.device)
                    with torch.no_grad():
                        g = self.model.ref_enc(y.transpose(1, 2)).unsqueeze(-1)
                        gs.append(g.detach())
                gs = torch.stack(gs).mean(0)
                if se_save_path is not None:
                    os.makedirs(os.path.dirname(se_save_path), exist_ok=True)
                    torch.save(gs.cpu(), se_save_path)
                return gs

            def convert(self, audio_src_path: str, src_se, tgt_se, output_path: str | None = None, tau: float = 0.3, message: str = "default"):
                audio, _sample_rate = librosa.load(audio_src_path, sr=self.hps.data.sampling_rate)
                audio_tensor = torch.tensor(audio).float()
                with torch.no_grad():
                    y = torch.FloatTensor(audio_tensor).to(self.device).unsqueeze(0)
                    spec = spectrogram_torch(
                        y,
                        self.hps.data.filter_length,
                        self.hps.data.sampling_rate,
                        self.hps.data.hop_length,
                        self.hps.data.win_length,
                        center=False,
                    ).to(self.device)
                    spec_lengths = torch.LongTensor([spec.size(-1)]).to(self.device)
                    audio_out = self.model.voice_conversion(spec, spec_lengths, sid_src=src_se, sid_tgt=tgt_se, tau=tau)[0][0, 0].data.cpu().float().numpy()
                    audio_out = self.add_watermark(audio_out, message)
                    if output_path is None:
                        return audio_out
                    soundfile.write(output_path, audio_out, self.hps.data.sampling_rate)

            def add_watermark(self, audio, message: str):
                if self.watermark_model is None:
                    return audio
                bits = utils.string_to_bits(message).reshape(-1)
                n_repeat = len(bits) // 32
                k_value = 16000
                coeff = 2
                for n in range(n_repeat):
                    trunck = audio[(coeff * n) * k_value : (coeff * n + 1) * k_value]
                    if len(trunck) != k_value:
                        break
                    message_npy = bits[n * 32 : (n + 1) * 32]
                    with torch.no_grad():
                        signal = torch.FloatTensor(trunck).to(self.device)[None]
                        message_tensor = torch.FloatTensor(message_npy).to(self.device)[None]
                        signal_wmd_tensor = self.watermark_model.encode(signal, message_tensor)
                        signal_wmd_npy = signal_wmd_tensor.detach().cpu().squeeze()
                    audio[(coeff * n) * k_value : (coeff * n + 1) * k_value] = signal_wmd_npy
                return audio

        return _ToneColorConverter

    @property
    def voices_dir(self) -> Path:
        return self.config.base_dir / "voices"

    def available_base_voice_variants(self) -> list[str]:
        variants = [self.config.piper_default_variant]
        if self.config.piper_model_alt:
            alt_variant = self.config.piper_alt_variant
            if alt_variant and alt_variant not in variants:
                variants.append(alt_variant)
        return variants

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._load_lock:
            if self._loaded:
                return
            try:
                self._torch = importlib.import_module("torch")
            except Exception as exc:
                raise RuntimeError(
                    "openvoice_python_missing: install optional OpenVoice runtime dependencies before starting EA_ROLE=openvoice"
                ) from exc
            self._ensure_source_path()
            converter_dir = self.config.converter_dir
            config_path = converter_dir / "config.json"
            checkpoint_path = converter_dir / "checkpoint.pth"
            if not config_path.is_file() or not checkpoint_path.is_file():
                raise RuntimeError(
                    f"openvoice_checkpoint_missing:{converter_dir}"
                )
            self.config.base_dir.mkdir(parents=True, exist_ok=True)
            self.voices_dir.mkdir(parents=True, exist_ok=True)
            converter_cls = self._build_tone_color_converter_class()
            self._tone_color_converter = converter_cls(str(config_path), device=self.config.device)
            self._tone_color_converter.load_ckpt(str(checkpoint_path))
            self._loaded = True

    def _voice_dir(self, voice_id: str) -> Path:
        normalized = _safe_voice_id(voice_id)
        if not normalized:
            raise ValueError("voice_id_invalid")
        return self.voices_dir / normalized

    def _manifest_path(self, voice_id: str) -> Path:
        return self._voice_dir(voice_id) / "manifest.json"

    def _target_embedding_path(self, voice_id: str) -> Path:
        return self._voice_dir(voice_id) / "target_se.pth"

    def _convert_to_wav(self, *, source_path: Path, target_path: Path) -> None:
        cmd = [
            _ffmpeg_bin(),
            "-hide_banner",
            "-nostdin",
            "-y",
            "-i",
            str(source_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(self.config.sample_rate),
            str(target_path),
        ]
        return_code, _, stderr = _run_command(cmd=cmd)
        if return_code != 0 or not target_path.is_file():
            raise RuntimeError(f"ffmpeg_convert_failed:{stderr[:160]}")

    def _concat_wavs(self, *, wav_paths: list[Path], output_path: Path) -> None:
        if len(wav_paths) == 1:
            shutil.copyfile(wav_paths[0], output_path)
            return
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt") as handle:
            concat_list = Path(handle.name)
            for wav_path in wav_paths:
                handle.write(f"file '{wav_path.as_posix()}'\n")
        cmd = [
            _ffmpeg_bin(),
            "-hide_banner",
            "-nostdin",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(output_path),
        ]
        try:
            return_code, _, stderr = _run_command(cmd=cmd)
            if return_code != 0 or not output_path.is_file():
                raise RuntimeError(f"ffmpeg_concat_failed:{stderr[:160]}")
        finally:
            concat_list.unlink(missing_ok=True)

    def _resolve_piper_model(self, requested_variant: str) -> str:
        variant = _normalize_variant(requested_variant)
        default_variant = self.config.piper_default_variant
        alt_variant = self.config.piper_alt_variant
        if not variant or variant in {"default", default_variant}:
            return self.config.piper_model
        if self.config.piper_model_alt and variant == alt_variant:
            return self.config.piper_model_alt
        return self.config.piper_model

    def _build_source_audio(self, *, text: str, output_path: Path, lang: str, base_voice_variant: str = "") -> None:
        provider = self.config.base_tts
        if provider == "piper":
            piper_model = self._resolve_piper_model(base_voice_variant)
            if not self.config.piper_bin or not piper_model:
                raise RuntimeError("piper_not_configured")
            cmd = [
                self.config.piper_bin,
                "--model",
                piper_model,
                "--output_file",
                str(output_path),
            ]
            if self.config.piper_speaker is not None:
                cmd.extend(["--speaker", str(self.config.piper_speaker)])
            proc = subprocess.run(
                cmd,
                input=text,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=300,
            )
            if proc.returncode != 0 or not output_path.is_file():
                raise RuntimeError(f"piper_tts_failed:{proc.stderr[:160]}")
            return
        normalized_lang = str(lang or "").strip().lower() or "de"
        if normalized_lang.startswith("de"):
            espeak_voice = "de"
        elif normalized_lang.startswith("en"):
            espeak_voice = "en"
        else:
            espeak_voice = str(os.environ.get("OPENVOICE_ESPEAK_VOICE") or "de")
        if self.config.espeak_bin:
            cmd = [
                self.config.espeak_bin,
                "-v",
                espeak_voice,
                "-s",
                str(_env_int("OPENVOICE_ESPEAK_SPEED", 155)),
                "-w",
                str(output_path),
                text,
            ]
            return_code, _, stderr = _run_command(cmd=cmd)
            if return_code != 0 or not output_path.is_file():
                raise RuntimeError(f"espeak_tts_failed:{stderr[:160]}")
            return
        flite_voice = "kal16"
        if normalized_lang.startswith("en"):
            flite_voice = str(os.environ.get("OPENVOICE_FLITE_VOICE_EN") or "kal16")
        else:
            flite_voice = str(os.environ.get("OPENVOICE_FLITE_VOICE_DEFAULT") or "kal16")
        escaped_text = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "'\\\\''")
        cmd = [
            _ffmpeg_bin(),
            "-hide_banner",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"flite=text='{escaped_text}':voice={flite_voice}",
            "-ar",
            str(self.config.sample_rate),
            "-ac",
            "1",
            str(output_path),
        ]
        return_code, _, stderr = _run_command(cmd=cmd)
        if return_code != 0 or not output_path.is_file():
            raise RuntimeError(f"flite_tts_failed:{stderr[:160]}")

    def clone_voice(self, *, voice_id: str, voice_label: str, source_files: list[tuple[str, bytes]]) -> dict[str, object]:
        self._ensure_loaded()
        with self._voice_lock(voice_id):
            voice_dir = self._voice_dir(voice_id)
            voice_dir.mkdir(parents=True, exist_ok=True)
            wav_paths: list[Path] = []
            for index, (filename, payload) in enumerate(source_files, start=1):
                suffix = Path(filename or f"sample-{index}.bin").suffix or ".bin"
                sample_path = voice_dir / f"sample-{index}{suffix}"
                sample_path.write_bytes(payload)
                wav_path = voice_dir / f"sample-{index}.wav"
                self._convert_to_wav(source_path=sample_path, target_path=wav_path)
                wav_paths.append(wav_path)
            if not wav_paths:
                raise RuntimeError("voice_profile_samples_unusable")
            merged_reference = voice_dir / "reference.wav"
            self._concat_wavs(wav_paths=wav_paths, output_path=merged_reference)
            target_se = self._tone_color_converter.extract_se([str(path) for path in wav_paths], se_save_path=None)
            embedding_path = self._target_embedding_path(voice_id)
            self._torch.save(target_se, embedding_path)
            manifest = {
                "voice_id": _safe_voice_id(voice_id),
                "voice_label": str(voice_label or "").strip() or _safe_voice_id(voice_id),
                "reference_audio_path": str(merged_reference),
                "sample_count": len(wav_paths),
                "base_tts": self.config.base_tts,
            }
            self._manifest_path(voice_id).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            return manifest

    def synthesize(self, *, voice_id: str, text: str, lang: str, base_voice_variant: str = "") -> bytes:
        self._ensure_loaded()
        with self._voice_lock(voice_id):
            voice_dir = self._voice_dir(voice_id)
            embedding_path = self._target_embedding_path(voice_id)
            if not embedding_path.is_file():
                raise RuntimeError("voice_id_not_found")
            with tempfile.TemporaryDirectory(prefix="openvoice-synth-") as tmp_dir:
                tmp_root = Path(tmp_dir)
                base_wav = tmp_root / "base.wav"
                converted_wav = tmp_root / "converted.wav"
                source_embedding_wav = tmp_root / "source.wav"
                self._build_source_audio(
                    text=text,
                    output_path=base_wav,
                    lang=lang,
                    base_voice_variant=base_voice_variant,
                )
                self._convert_to_wav(source_path=base_wav, target_path=source_embedding_wav)
                source_se = self._tone_color_converter.extract_se([str(source_embedding_wav)], se_save_path=None)
                target_se = self._torch.load(str(embedding_path), map_location=self.config.device)
                self._tone_color_converter.convert(
                    audio_src_path=str(source_embedding_wav),
                    src_se=source_se,
                    tgt_se=target_se,
                    output_path=str(converted_wav),
                    message=str(os.environ.get("OPENVOICE_WATERMARK_TEXT") or "@EA Memorial"),
                )
                if not converted_wav.is_file():
                    raise RuntimeError("openvoice_output_missing")
                return converted_wav.read_bytes()


_runtime_singleton: OpenVoiceRuntime | None = None


def get_openvoice_runtime() -> OpenVoiceRuntime:
    global _runtime_singleton
    if _runtime_singleton is None:
        _runtime_singleton = OpenVoiceRuntime(load_openvoice_service_config())
    return _runtime_singleton
