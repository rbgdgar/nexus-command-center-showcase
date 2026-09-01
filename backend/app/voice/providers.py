from __future__ import annotations

import tempfile
from abc import ABC, abstractmethod
from pathlib import Path


class SpeechToTextProvider(ABC):
    @abstractmethod
    def transcribe(self, audio: bytes, media_type: str) -> str:
        raise NotImplementedError


class TextToSpeechProvider(ABC):
    @abstractmethod
    def synthesize(self, text: str) -> bytes:
        raise NotImplementedError


class WakeWordProvider(ABC):
    enabled: bool = False

    @abstractmethod
    def detect(self, audio: bytes) -> bool:
        raise NotImplementedError


class DisabledSpeechToText(SpeechToTextProvider):
    def transcribe(self, audio: bytes, media_type: str) -> str:
        raise RuntimeError("Local speech-to-text is not configured")


class FasterWhisperProvider(SpeechToTextProvider):
    """Optional local provider; faster-whisper is loaded only when configured."""

    def __init__(self, model_name: str = "base"):
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise RuntimeError("Install faster-whisper to use local STT") from error
        self.model = WhisperModel(model_name, device="cpu", compute_type="int8")

    def transcribe(self, audio: bytes, media_type: str) -> str:
        suffix = ".webm" if "webm" in media_type else ".wav"
        path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
                handle.write(audio)
                path = Path(handle.name)
            segments, _ = self.model.transcribe(str(path))
            return " ".join(segment.text.strip() for segment in segments).strip()
        finally:
            if path:
                path.unlink(missing_ok=True)


class DisabledTextToSpeech(TextToSpeechProvider):
    def synthesize(self, text: str) -> bytes:
        raise RuntimeError("Server text-to-speech is not configured")


class DisabledWakeWord(WakeWordProvider):
    enabled = False
    def detect(self, audio: bytes) -> bool:
        return False


class VoiceService:
    def __init__(self, stt: SpeechToTextProvider, tts: TextToSpeechProvider, wake_word: WakeWordProvider):
        self.stt = stt
        self.tts = tts
        self.wake_word = wake_word

    def transcribe(self, audio: bytes, media_type: str) -> str:
        if not audio:
            raise ValueError("Audio is empty")
        if len(audio) > 25 * 1024 * 1024:
            raise ValueError("Audio exceeds the 25 MB local limit")
        return self.stt.transcribe(audio, media_type)

    def status(self) -> dict:
        return {
            "stt_provider": type(self.stt).__name__,
            "tts_provider": type(self.tts).__name__,
            "wake_word_enabled": self.wake_word.enabled,
            "external_audio_enabled": False,
            "mode": "push-to-talk",
        }
