import unittest

from scripts.nexus_wakeword import WakeWordCompanion, validate_command_center_url


class FakeWakeWordModel:
    def __init__(self, predictions):
        self.predictions = iter(predictions)

    def predict(self, _audio_frame):
        return next(self.predictions)


class WakeWordCompanionTests(unittest.TestCase):
    def test_detection_is_local_and_reports_no_audio_retention(self):
        companion = WakeWordCompanion(
            model=FakeWakeWordModel([{"hey_jarvis": 0.73}]),
            threshold=0.5,
        )

        event = companion.process_frame(b"frame", now=10)

        self.assertEqual(event["event"], "wake_word_detected")
        self.assertEqual(event["model"], "hey_jarvis")
        self.assertEqual(event["score"], 0.73)
        self.assertFalse(event["audio_retained"])
        self.assertFalse(event["audio_uploaded"])

    def test_low_score_and_cooldown_suppress_detection(self):
        companion = WakeWordCompanion(
            model=FakeWakeWordModel(
                [{"hey_jarvis": 0.49}, {"hey_jarvis": 0.8}, {"hey_jarvis": 0.9}]
            ),
            threshold=0.5,
            cooldown_seconds=3,
        )

        self.assertIsNone(companion.process_frame(b"low", now=1))
        self.assertIsNotNone(companion.process_frame(b"first", now=2))
        self.assertIsNone(companion.process_frame(b"cooldown", now=4))

    def test_configuration_is_bounded(self):
        with self.assertRaisesRegex(ValueError, "allow-listed"):
            WakeWordCompanion(model_name="custom", model=FakeWakeWordModel([]))
        with self.assertRaisesRegex(ValueError, "threshold"):
            WakeWordCompanion(threshold=0.1, model=FakeWakeWordModel([]))
        with self.assertRaisesRegex(ValueError, "cooldown"):
            WakeWordCompanion(cooldown_seconds=0, model=FakeWakeWordModel([]))

    def test_command_center_url_requires_https_or_loopback(self):
        self.assertEqual(
            validate_command_center_url("https://nexus.example/"),
            "https://nexus.example",
        )
        self.assertEqual(
            validate_command_center_url("http://127.0.0.1:8000/"),
            "http://127.0.0.1:8000",
        )
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            validate_command_center_url("http://nexus.example")


if __name__ == "__main__":
    unittest.main()
