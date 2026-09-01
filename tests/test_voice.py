import unittest

from backend.app.voice.providers import (
    DisabledWakeWord,
    SpeechToTextProvider,
    TextToSpeechProvider,
    VoiceService,
)


class FakeSTT(SpeechToTextProvider):
    def transcribe(self, audio, media_type):
        return f"heard {len(audio)} bytes as {media_type}"


class FakeTTS(TextToSpeechProvider):
    def synthesize(self, text):
        return text.encode()


class VoiceTests(unittest.TestCase):
    def setUp(self):
        self.service = VoiceService(FakeSTT(), FakeTTS(), DisabledWakeWord())

    def test_transcription_uses_provider(self):
        self.assertEqual(self.service.transcribe(b"audio", "audio/webm"), "heard 5 bytes as audio/webm")

    def test_empty_audio_is_rejected(self):
        with self.assertRaises(ValueError):
            self.service.transcribe(b"", "audio/webm")

    def test_wake_word_is_disabled(self):
        status = self.service.status()
        self.assertFalse(status["wake_word_enabled"])
        self.assertFalse(status["external_audio_enabled"])
        self.assertEqual(status["mode"], "push-to-talk")


if __name__ == "__main__":
    unittest.main()
