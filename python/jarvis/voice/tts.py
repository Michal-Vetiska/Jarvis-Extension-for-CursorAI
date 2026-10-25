"""macOS `say` text-to-speech with Czech voice preference."""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from typing import Any

logger = logging.getLogger(__name__)


class MacSayTTS:
    def __init__(self, voice: str = "Zuzana", fallback_voice: str = "Samantha") -> None:
        self.voice = voice
        self.fallback_voice = fallback_voice
        self.audio_device: str | None = None  # jméno/UID pro `say -a`, None = systémový default
        self._proc: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    def available_voices(self) -> list[str]:
        if not shutil.which("say"):
            return []
        result = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, check=False)
        voices = []
        for line in (result.stdout or "").splitlines():
            parts = line.split()
            if parts:
                voices.append(parts[0])
        return voices

    def resolve_voice(self) -> str:
        voices = {v.lower(): v for v in self.available_voices()}
        if self.voice.lower() in voices:
            return voices[self.voice.lower()]
        for name in self.available_voices():
            if "zuza" in name.lower() or "czech" in name.lower() or "cs_" in name.lower():
                return name
        if self.fallback_voice.lower() in voices:
            return voices[self.fallback_voice.lower()]
        return self.fallback_voice

    def set_settings(self, *, voice: str | None = None, audio_device: str | None = None) -> dict[str, Any]:
        if voice:
            self.voice = voice
        # Prázdný string / systémový default
        if audio_device is not None:
            if audio_device in {"", "__system_default__", "default"}:
                self.audio_device = None
            else:
                self.audio_device = audio_device
        return {
            "tts_voice": self.voice,
            "audio_device": self.audio_device,
            "resolved_voice": self.resolve_voice(),
        }

    def speak(self, text: str, wait: bool = True) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            return {"spoken": False, "reason": "empty"}
        voice = self.resolve_voice()
        self.stop()
        cmd = ["say", "-v", voice]
        if self.audio_device:
            cmd.extend(["-a", self.audio_device])
        cmd.append(text)
        with self._lock:
            if wait:
                result = subprocess.run(cmd, capture_output=True, text=True, check=False)
                return {
                    "spoken": result.returncode == 0,
                    "voice": voice,
                    "audio_device": self.audio_device,
                    "error": result.stderr.strip() or None,
                }
            self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"spoken": True, "voice": voice, "audio_device": self.audio_device, "async": True}

    def stop(self) -> None:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
            self._proc = None
            subprocess.run(["killall", "say"], capture_output=True, check=False)
