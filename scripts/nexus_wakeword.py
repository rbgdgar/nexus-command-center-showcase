"""Explicitly enabled, fully local wake-word companion for NEXUS."""

from __future__ import annotations

import argparse
import json
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlparse


SAMPLE_RATE = 16_000
CHUNK_SAMPLES = 1_280
SUPPORTED_MODELS = {"alexa", "hey_jarvis", "hey_mycroft", "hey_rhasspy"}


class WakeWordCompanion:
    def __init__(
        self,
        model_name: str = "hey_jarvis",
        threshold: float = 0.5,
        cooldown_seconds: float = 3.0,
        model_path: str | Path | None = None,
        model=None,
        clock=time.monotonic,
    ):
        if model_name not in SUPPORTED_MODELS:
            raise ValueError("Wake-word model is not allow-listed")
        if not 0.3 <= threshold <= 0.95:
            raise ValueError("Wake-word threshold must be from 0.3 to 0.95")
        if not 1 <= cooldown_seconds <= 60:
            raise ValueError("Wake-word cooldown must be from 1 to 60 seconds")
        self.model_name = model_name
        self.threshold = float(threshold)
        self.cooldown_seconds = float(cooldown_seconds)
        self.clock = clock
        self.last_detection = float("-inf")
        self.model = model or self._load_model(model_path)

    def _load_model(self, model_path: str | Path | None):
        import openwakeword
        from openwakeword.model import Model

        if model_path:
            selected = Path(model_path).expanduser().resolve()
        else:
            configured = Path(openwakeword.MODELS[self.model_name]["model_path"])
            selected = configured.with_suffix(".onnx")
        if not selected.is_file() or selected.suffix.lower() != ".onnx":
            raise ValueError(
                "Wake-word ONNX model is missing; run with --download-model first"
            )
        return Model(wakeword_models=[str(selected)], inference_framework="onnx")

    def process_frame(self, audio_frame, now: float | None = None) -> dict | None:
        prediction = self.model.predict(audio_frame)
        candidates = [
            (name, float(score))
            for name, score in prediction.items()
            if self.model_name in name.lower()
        ]
        if not candidates:
            return None
        detected_model, score = max(candidates, key=lambda item: item[1])
        timestamp = self.clock() if now is None else now
        if score < self.threshold or timestamp - self.last_detection < self.cooldown_seconds:
            return None
        self.last_detection = timestamp
        return {
            "event": "wake_word_detected",
            "model": detected_model,
            "score": round(score, 4),
            "audio_retained": False,
            "audio_uploaded": False,
        }

    def listen(self, on_detection, once: bool = False):
        import numpy as np
        import sounddevice as sd

        with sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=CHUNK_SAMPLES,
            channels=1,
            dtype="int16",
        ) as microphone:
            while True:
                frame, overflowed = microphone.read(CHUNK_SAMPLES)
                if overflowed:
                    continue
                event = self.process_frame(np.frombuffer(frame, dtype=np.int16))
                if event:
                    on_detection(event)
                    if once:
                        return event


def validate_command_center_url(value: str) -> str:
    parsed = urlparse(value)
    loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
        raise ValueError("Command Center URL must use HTTPS, except for loopback")
    return value.rstrip("/")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable", action="store_true", help="Explicitly enable microphone listening")
    parser.add_argument("--download-model", action="store_true", help="Download only the selected official model, then exit")
    parser.add_argument("--model", choices=sorted(SUPPORTED_MODELS), default="hey_jarvis")
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--cooldown", type=float, default=3.0)
    parser.add_argument("--once", action="store_true", help="Exit after the first activation")
    parser.add_argument("--open-command-center", action="store_true")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    arguments = parser.parse_args()

    if arguments.download_model:
        from openwakeword.utils import download_models

        download_models([arguments.model])
        print(json.dumps({"downloaded": arguments.model}))
        return 0
    if not arguments.enable:
        parser.error("microphone listening requires the explicit --enable flag")
    command_center_url = validate_command_center_url(arguments.url)
    companion = WakeWordCompanion(
        model_name=arguments.model,
        threshold=arguments.threshold,
        cooldown_seconds=arguments.cooldown,
        model_path=arguments.model_path,
    )

    def activate(event):
        print(json.dumps(event), flush=True)
        if arguments.open_command_center:
            webbrowser.open(command_center_url, new=2, autoraise=True)

    print(json.dumps({
        "status": "listening",
        "model": arguments.model,
        "sample_rate": SAMPLE_RATE,
        "audio_retained": False,
        "audio_uploaded": False,
    }), flush=True)
    try:
        companion.listen(activate, once=arguments.once)
    except KeyboardInterrupt:
        print(json.dumps({"status": "stopped"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
