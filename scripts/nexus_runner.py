"""Outbound-only NEXUS local runner with a fixed, non-destructive tool allowlist."""

from __future__ import annotations

import argparse
import base64
import ctypes
import io
import json
import os
import platform
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


EXCLUDED_PARTS = {
    ".git", ".venv", "node_modules", "dist", "__pycache__", "logs", "data",
}
SECRET_NAMES = {".env", ".env.deployment", "credentials", "credentials.json"}


class LocalRunner:
    def __init__(self):
        self.url = os.environ.get("NEXUS_URL", "").rstrip("/")
        self.node_id = os.environ.get("NEXUS_RUNNER_ID", "")
        self.token = os.environ.get("NEXUS_RUNNER_TOKEN", "")
        self.root = Path(os.environ.get("NEXUS_RUNNER_ROOT", ".")).resolve()
        self.app_allowlist = self._load_app_allowlist()
        self._validate_configuration()

    def run(self, once=False, interval=10):
        print(f"NEXUS runner online: node={self.node_id} root={self.root}")
        while True:
            try:
                job = self._request("POST", f"/api/runner/nodes/{self.node_id}/poll")
                if job:
                    self._execute_and_report(job)
            except (OSError, ValueError, urllib.error.URLError) as error:
                print(f"Runner connection error: {error}")
            if once:
                return
            time.sleep(max(5, interval))

    def _execute_and_report(self, job):
        try:
            result = self.execute(job["tool"], job.get("arguments") or {})
            if job["tool"] == "capture_screenshot":
                stored = self._request("POST", f"/api/runner/nodes/{self.node_id}/screenshot", {
                    "job_id": job["id"], "image_base64": result.pop("image_base64"),
                })
                result["media_job"] = stored.get("id")
                result["asset_url"] = stored.get("asset_url")
            succeeded = True
        except Exception as error:
            result = {"error": str(error)}
            succeeded = False
        self._request("POST", f"/api/runner/nodes/{self.node_id}/result", {
            "job_id": job["id"], "succeeded": succeeded, "result": result,
        })

    def execute(self, tool, arguments):
        handlers = {
            "system_info": self.system_info,
            "git_status": self.git_status,
            "git_diff": self.git_diff,
            "list_files": self.list_files,
            "read_text_file": self.read_text_file,
            "create_text_file": self.create_text_file,
            "speak_text": self.speak_text,
            "media_control": self.media_control,
            "launch_app": self.launch_app,
            "capture_screenshot": self.capture_screenshot,
        }
        handler = handlers.get(tool)
        if not handler:
            raise ValueError("Runner tool is not allow-listed")
        return handler(**arguments)

    def system_info(self):
        return {
            "computer_name": platform.node(), "operating_system": platform.system(),
            "os_version": platform.version(), "architecture": platform.machine(),
            "python_version": platform.python_version(),
        }

    def git_status(self):
        return self._git(["status", "--short", "--branch"])

    def git_diff(self):
        return self._git(["diff", "--"])

    def list_files(self, path=".", limit=200):
        target = self._safe_path(path)
        if not target.is_dir():
            raise ValueError("Requested path is not a directory")
        files = []
        for item in target.rglob("*"):
            relative = item.relative_to(self.root)
            if self._excluded(relative) or not item.is_file():
                continue
            files.append(str(relative))
            if len(files) >= max(1, min(int(limit), 500)):
                break
        return {"root": str(self.root), "files": files}

    def read_text_file(self, path, max_chars=50000):
        target = self._safe_path(path)
        if not target.is_file() or target.stat().st_size > 2_000_000:
            raise ValueError("File is missing or too large")
        content = target.read_text(encoding="utf-8")
        return {"path": str(target.relative_to(self.root)), "content": content[:max(1, min(int(max_chars), 100000))]}

    def create_text_file(self, path, content):
        target = self._safe_path(path)
        if len(content.encode()) > 200000:
            raise ValueError("New file content exceeds 200 KB")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as output:
            output.write(content)
        return {"created": str(target.relative_to(self.root)), "bytes": len(content.encode())}

    def speak_text(self, text, rate=170, volume=1.0, voice_index=None):
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            raise ValueError("Speech text must be 1-2000 characters")
        if isinstance(rate, bool) or not isinstance(rate, int) or not 120 <= rate <= 220:
            raise ValueError("Speech rate must be an integer from 120 to 220")
        if isinstance(volume, bool) or not isinstance(volume, (int, float)) or not 0 <= volume <= 1:
            raise ValueError("Speech volume must be from 0 to 1")
        if (
            voice_index is not None
            and (isinstance(voice_index, bool) or not isinstance(voice_index, int)
                 or not 0 <= voice_index <= 20)
        ):
            raise ValueError("Speech voice index must be an integer from 0 to 20")
        try:
            import pyttsx3
        except ImportError as error:
            raise RuntimeError(
                "Local speech is unavailable; install requirements-runner.txt"
            ) from error
        engine = pyttsx3.init()
        try:
            engine.setProperty("rate", rate)
            engine.setProperty("volume", float(volume))
            voices = engine.getProperty("voices") or []
            if voice_index is not None:
                if voice_index >= len(voices):
                    raise ValueError("Requested speech voice is not installed")
                engine.setProperty("voice", voices[voice_index].id)
            engine.say(text.strip())
            engine.runAndWait()
        finally:
            engine.stop()
        return {
            "spoken": True,
            "characters": len(text.strip()),
            "rate": rate,
            "volume": float(volume),
            "voice_index": voice_index,
        }

    def media_control(self, action, repeat=1):
        media_keys = {
            "next_track": 0xB0,
            "previous_track": 0xB1,
            "stop": 0xB2,
            "play_pause": 0xB3,
            "volume_mute": 0xAD,
            "volume_down": 0xAE,
            "volume_up": 0xAF,
        }
        if action not in media_keys:
            raise ValueError("Media control action is not allow-listed")
        if isinstance(repeat, bool) or not isinstance(repeat, int) or not 1 <= repeat <= 10:
            raise ValueError("Media control repeat must be an integer from 1 to 10")
        if platform.system() != "Windows":
            raise RuntimeError("Media control currently requires a Windows local runner")
        user32 = ctypes.windll.user32
        virtual_key = media_keys[action]
        for _ in range(repeat):
            user32.keybd_event(virtual_key, 0, 0, 0)
            user32.keybd_event(virtual_key, 0, 0x0002, 0)
        return {"controlled": True, "action": action, "repeat": repeat}

    def launch_app(self, app_id):
        if not isinstance(app_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,49}", app_id):
            raise ValueError("Application ID must be a lowercase allowlist identifier")
        command = self.app_allowlist.get(app_id)
        if not command:
            raise ValueError("Application is not configured in the local allowlist")
        process = subprocess.Popen(command, shell=False, cwd=str(self.root))
        return {"launched": True, "app_id": app_id, "pid": process.pid}

    def capture_screenshot(self):
        try:
            from PIL import ImageGrab
        except ImportError as error:
            raise RuntimeError("Screenshot capture is unavailable; install requirements-runner.txt") from error
        image = ImageGrab.grab(all_screens=True)
        image.thumbnail((1920, 1080))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        data = buffer.getvalue()
        if not data or len(data) > 8_000_000:
            raise ValueError("Screenshot exceeds the 8 MB runner limit")
        return {"captured": True, "width": image.width, "height": image.height, "image_base64": base64.b64encode(data).decode()}

    @staticmethod
    def _load_app_allowlist():
        raw = os.environ.get("NEXUS_RUNNER_APP_ALLOWLIST", "{}").strip() or "{}"
        try:
            configured = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError("NEXUS_RUNNER_APP_ALLOWLIST must be valid JSON") from error
        if not isinstance(configured, dict) or len(configured) > 20:
            raise ValueError("Application allowlist must be an object with at most 20 entries")
        normalized = {}
        for app_id, command in configured.items():
            if not isinstance(app_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,49}", app_id):
                raise ValueError("Application allowlist contains an invalid ID")
            if (
                not isinstance(command, list) or not 1 <= len(command) <= 10
                or any(not isinstance(item, str) or not item or len(item) > 500 for item in command)
            ):
                raise ValueError("Each application must be a bounded argument array")
            executable = Path(command[0]).expanduser()
            if not executable.is_absolute() or not executable.is_file():
                raise ValueError(f"Application executable for {app_id} must be an existing absolute file")
            normalized[app_id] = [str(executable), *command[1:]]
        return normalized

    def _git(self, arguments):
        completed = subprocess.run(
            ["git", "-C", str(self.root), *arguments], shell=False,
            capture_output=True, text=True, timeout=30, check=False,
        )
        return {"returncode": completed.returncode, "output": (completed.stdout or completed.stderr)[:100000]}

    def _safe_path(self, value):
        target = (self.root / value).resolve()
        try:
            relative = target.relative_to(self.root)
        except ValueError as error:
            raise ValueError("Path escapes the approved runner root") from error
        if self._excluded(relative):
            raise ValueError("Path is excluded by runner safety policy")
        return target

    @staticmethod
    def _excluded(relative):
        parts = set(relative.parts)
        return bool(parts & EXCLUDED_PARTS) or relative.name.lower() in SECRET_NAMES

    def _request(self, method, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            f"{self.url}{path}", data=data, method=method,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as error:
            if error.code == 204:
                return None
            detail = error.read().decode(errors="replace")[:500]
            raise RuntimeError(f"NEXUS returned HTTP {error.code}: {detail}") from error

    def _validate_configuration(self):
        parsed = urlparse(self.url)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
            raise ValueError("NEXUS_URL must use HTTPS, except for loopback development")
        if not self.node_id or not self.token:
            raise ValueError("NEXUS_RUNNER_ID and NEXUS_RUNNER_TOKEN are required")
        if not self.root.is_dir():
            raise ValueError("NEXUS_RUNNER_ROOT must be an existing directory")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Poll once and exit")
    parser.add_argument("--interval", type=int, default=10, help="Polling interval in seconds")
    arguments = parser.parse_args()
    LocalRunner().run(once=arguments.once, interval=arguments.interval)


if __name__ == "__main__":
    main()
