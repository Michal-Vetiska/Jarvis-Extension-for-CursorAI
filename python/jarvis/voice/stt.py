"""Speech-to-text backends (mlx-whisper on Apple Silicon, with fallback)."""

from __future__ import annotations

import logging
import tempfile
import wave
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class SpeechToText:
    def __init__(self, backend: str = "mlx_whisper", model: str = "mlx-community/whisper-small-mlx", language: str = "cs") -> None:
        self.backend = backend
        self.model = model
        self.language = language
        self._mlx = None

    def _load_mlx(self) -> Any:
        if self._mlx is None:
            try:
                import mlx_whisper  # type: ignore

                self._mlx = mlx_whisper
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(
                    "mlx-whisper nejde načíst (pip install mlx-whisper / Metal GPU). "
                    "Preferuj hlas přes JARVIS.app (Apple Speech)."
                ) from exc
        return self._mlx

    def transcribe_pcm16(self, pcm: bytes, sample_rate: int = 16000) -> str:
        if not pcm:
            return ""
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        return self.transcribe_audio(audio, sample_rate=sample_rate)

    def transcribe_audio(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        if self.backend in {"mlx_whisper", "mlx-whisper"}:
            return self._transcribe_mlx(audio, sample_rate)
        return self._transcribe_stub(audio)

    def transcribe_wav_file(self, path: str) -> str:
        if self.backend in {"mlx_whisper", "mlx-whisper"}:
            mlx_whisper = self._load_mlx()
            result = mlx_whisper.transcribe(
                path,
                path_or_hf_repo=self.model,
                language=self.language,
            )
            return (result.get("text") or "").strip()
        # Fallback: načti wav do numpy
        with wave.open(path, "rb") as wf:
            rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        return self.transcribe_audio(audio, sample_rate=rate)

    def _transcribe_mlx(self, audio: np.ndarray, sample_rate: int) -> str:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            path = Path(tmp.name)
        try:
            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
                wf.writeframes(pcm)
            return self.transcribe_wav_file(str(path))
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def _transcribe_stub(self, audio: np.ndarray) -> str:
        logger.warning("STT stub — žádný backend, délka audia=%.2fs", len(audio) / 16000)
        return ""
