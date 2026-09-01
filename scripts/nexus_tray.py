"""Explicitly launched Windows tray companion for local NEXUS status."""
from __future__ import annotations

import argparse
import threading
import webbrowser
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx


STATES = {"online": "NEXUS online", "attention": "NEXUS needs attention", "offline": "NEXUS offline"}


def validate_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
        raise ValueError("NEXUS URL must use HTTPS, except for loopback")
    return value.rstrip("/")


@dataclass
class TrayStatus:
    state: str
    detail: str


class TrayCompanion:
    def __init__(self, url: str, client: httpx.Client | None = None):
        self.url = validate_url(url)
        self.client = client or httpx.Client(timeout=3.0, follow_redirects=False)

    def status(self) -> TrayStatus:
        try:
            health = self.client.get(f"{self.url}/health")
            if health.status_code != 200:
                return TrayStatus("attention", "Health endpoint needs attention")
            ready = self.client.get(f"{self.url}/ready")
            return TrayStatus("online" if ready.status_code == 200 else "attention", "Ready" if ready.status_code == 200 else "Some services need setup")
        except httpx.HTTPError:
            return TrayStatus("offline", "Command Center unreachable")

    def open_command_center(self):
        webbrowser.open(self.url, new=2, autoraise=True)

    def refresh_loop(self, update, stop_event, interval_seconds: float = 15):
        while not stop_event.is_set():
            update(self.status())
            stop_event.wait(interval_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--check", action="store_true", help="Print one status check and exit")
    arguments = parser.parse_args()
    companion = TrayCompanion(arguments.url)
    if arguments.check:
        status = companion.status()
        print(f"{status.state}: {status.detail}")
        return 0
    import pystray
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (64, 64), "#101827")
    ImageDraw.Draw(image).ellipse((16, 16, 48, 48), fill="#36d399")
    icon = pystray.Icon("NEXUS", image, "NEXUS checking", menu=pystray.Menu(pystray.MenuItem("Open Command Center", lambda *_: companion.open_command_center()), pystray.MenuItem("Quit", lambda *_: icon.stop())))
    def refresh(status):
        icon.title = f"{STATES[status.state]} · {status.detail}"
    stop_event = threading.Event()
    worker = threading.Thread(target=companion.refresh_loop, args=(refresh, stop_event), daemon=True)
    worker.start()
    original_stop = icon.stop
    def stop():
        stop_event.set()
        original_stop()
    icon.stop = stop
    icon.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
