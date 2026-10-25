"""Local wake-word detection via openWakeWord + Czech phrase post-filter."""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Callable

import numpy as np

logger = logging.getLogger(__name__)

PHRASE_RE = re.compile(
    r"\b((hej|ahoj|hey)\s+)?(adame|adam)\b",
    re.IGNORECASE,
)


class WakeWordListener:
    def __init__(
        self,
        threshold: float = 0.55,
        sample_rate: int = 16000,
        phrases: list[str] | None = None,
        on_wake: Callable[[str], None] | None = None,
    ) -> None:
        self.threshold = threshold
        self.sample_rate = sample_rate
        self.phrases = [p.lower() for p in (phrases or ["adame", "adam", "hej adame"])]
        self.on_wake = on_wake
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._model = None
        self._cooldown_until = 0.0

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        try:
            import openwakeword
            from openwakeword.model import Model

            openwakeword.utils.download_models()
            self._model = Model(wakeword_models=["hey_jarvis"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("openWakeWord nedostupný: %s", exc)
            self._model = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="jarvis-wake", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def pause_cooldown(self, seconds: float = 4.0) -> None:
        self._cooldown_until = time.time() + seconds

    def match_transcript(self, text: str) -> bool:
        if not text:
            return False
        if PHRASE_RE.search(text):
            return True
        lowered = text.lower()
        return any(p in lowered for p in self.phrases)

    def _loop(self) -> None:
        try:
            import sounddevice as sd
        except Exception as exc:  # noqa: BLE001
            logger.error("sounddevice nedostupný pro wake word: %s", exc)
            return
        self._ensure_model()
        frame = 1280  # 80 ms @ 16 kHz
        while not self._stop.is_set():
            try:
                audio = sd.rec(frame, samplerate=self.sample_rate, channels=1, dtype="int16")
                sd.wait()
                pcm = audio.reshape(-1)
                if time.time() < self._cooldown_until:
                    continue
                triggered = False
                label = "hey_jarvis"
                if self._model is not None:
                    preds = self._model.predict(pcm)
                    score = float(max(preds.values())) if preds else 0.0
                    if score >= self.threshold:
                        triggered = True
                        label = max(preds, key=preds.get) if preds else label
                # Energy gate as weak fallback / secondary cue.
                energy = float(np.mean(np.abs(pcm.astype(np.float32))))
                if triggered or energy > 1800:
                    # Optional: caller can confirm with STT; here we fire on model hit.
                    if triggered and self.on_wake:
                        self.pause_cooldown(3.0)
                        self.on_wake(label)
            except Exception as exc:  # noqa: BLE001
                logger.debug("wake loop error: %s", exc)
                time.sleep(0.2)
