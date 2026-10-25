"""Voice session: wake → listen → STT → callback, plus push-to-talk."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import numpy as np

from jarvis.voice.stt import SpeechToText
from jarvis.voice.tts import MacSayTTS
from jarvis.voice.wake import WakeWordListener

logger = logging.getLogger(__name__)


class VoiceSession:
    def __init__(
        self,
        stt: SpeechToText,
        tts: MacSayTTS,
        wake: WakeWordListener,
        sample_rate: int = 16000,
        on_utterance: Callable[[str], None] | None = None,
        on_state: Callable[[str], None] | None = None,
    ) -> None:
        self.stt = stt
        self.tts = tts
        self.wake = wake
        self.sample_rate = sample_rate
        self.on_utterance = on_utterance
        self.on_state = on_state
        self._listening = False
        self._lock = threading.Lock()
        self.wake.on_wake = self._on_wake

    def start(self) -> None:
        self._set_state("idle")
        self.wake.start()

    def stop(self) -> None:
        self.wake.stop()
        self.tts.stop()
        self._set_state("stopped")

    def _set_state(self, state: str) -> None:
        if self.on_state:
            self.on_state(state)

    def _on_wake(self, label: str) -> None:
        logger.info("Wake detected: %s", label)
        self.tts.stop()
        self._set_state("wake")
        threading.Thread(target=self.listen_once, name="jarvis-listen", daemon=True).start()

    def push_to_talk_start(self) -> None:
        threading.Thread(target=self.listen_once, name="jarvis-ptt", daemon=True).start()

    def listen_once(self, max_seconds: float = 12.0, silence_seconds: float = 1.2) -> str:
        with self._lock:
            if self._listening:
                return ""
            self._listening = True
        self._set_state("listening")
        try:
            import sounddevice as sd
        except Exception as exc:  # noqa: BLE001
            logger.error("Mikrofon nedostupný: %s", exc)
            self._set_state("error")
            with self._lock:
                self._listening = False
            return ""

        try:
            devices = sd.query_devices()
            if not devices:
                logger.error("Žádné audio zařízení — použij Push-to-talk v JARVIS.app (Swift mic)")
                self._set_state("error")
                return ""
        except Exception as exc:  # noqa: BLE001
            logger.error("Audio zařízení nedostupná: %s", exc)
            self._set_state("error")
            with self._lock:
                self._listening = False
            return ""

        frames: list[np.ndarray] = []
        frame_len = int(0.03 * self.sample_rate)
        started = time.time()
        last_voice = time.time()
        try:
            while time.time() - started < max_seconds:
                audio = sd.rec(frame_len, samplerate=self.sample_rate, channels=1, dtype="float32")
                sd.wait()
                chunk = audio.reshape(-1)
                frames.append(chunk)
                energy = float(np.mean(np.abs(chunk)))
                if energy > 0.015:
                    last_voice = time.time()
                elif time.time() - last_voice > silence_seconds and len(frames) > 10:
                    break
            if not frames:
                return ""
            audio_arr = np.concatenate(frames)
            self._set_state("transcribing")
            text = self.stt.transcribe_audio(audio_arr, sample_rate=self.sample_rate)
            text = (text or "").strip()
            lowered = text.lower()
            for phrase in ("hej jarvisi", "hej jarve", "jarvisi", "jarve", "hey jarvis"):
                if lowered.startswith(phrase):
                    text = text[len(phrase) :].lstrip(" ,.")
                    break
            if text and self.on_utterance:
                self.on_utterance(text)
            self._set_state("idle")
            return text
        except Exception as exc:  # noqa: BLE001
            logger.exception("listen_once failed: %s", exc)
            self._set_state("error")
            return ""
        finally:
            self.wake.pause_cooldown(2.0)
            with self._lock:
                self._listening = False

    def speak(self, text: str, wait: bool = True) -> None:
        self._set_state("speaking")
        self.tts.speak(text, wait=wait)
        self._set_state("idle")
