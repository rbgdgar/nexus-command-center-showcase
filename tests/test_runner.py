import base64
import json
import os
import sqlite3
import tempfile
import unittest
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.app.core.config import Settings
from backend.app.runner.service import RunnerService
from backend.app.security.safety import ApprovalManager, RiskLevel, ToolDefinition, ToolRegistry
from scripts.nexus_runner import LocalRunner


class RunnerServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        settings = Settings(
            _env_file=None,
            database_path=Path(self.temp_dir.name) / "runner.db",
            media_storage_path=Path(self.temp_dir.name) / "media",
        )
        self.service = RunnerService(settings)
        self.service.initialize()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_pair_poll_complete_and_token_hashing(self):
        pairing = self.service.pair("Development laptop")
        node_id = pairing["node"]["id"]
        token = pairing["runner_token"]
        self.assertNotIn("token_hash", pairing["node"])
        job = self.service.create_job(node_id, "system_info", {})
        claimed = self.service.poll(node_id, token)
        self.assertEqual(claimed["id"], job["id"])
        completed = self.service.complete(node_id, token, job["id"], True, {"os": "test"})
        self.assertEqual(completed["state"], "completed")
        self.assertFalse(self.service.disable(node_id)["active"])
        with self.assertRaises(PermissionError):
            self.service.poll(node_id, "wrong-token")

    def test_safe_write_waits_for_approval(self):
        pairing = self.service.pair("Writer", ["create_text_file"])
        job = self.service.create_job(
            pairing["node"]["id"], "create_text_file", {"path": "note.txt", "content": "ok"}
        )
        self.assertEqual(job["state"], "approval_pending")
        self.assertIsNone(self.service.poll(pairing["node"]["id"], pairing["runner_token"]))
        self.service.queue_approved(job["id"])
        self.assertEqual(
            self.service.poll(pairing["node"]["id"], pairing["runner_token"])["state"],
            "running",
        )

    def test_safe_write_uses_approval_manager(self):
        pairing = self.service.pair("Approved writer", ["create_text_file"])
        job = self.service.create_job(
            pairing["node"]["id"], "create_text_file", {"path": "new.txt", "content": "ok"}
        )
        registry = ToolRegistry()
        registry.register(ToolDefinition(
            "queue_test_runner_job", "runner", RiskLevel.SAFE_WRITE, True, True,
            self.service.queue_approved,
        ))
        manager = ApprovalManager(registry, database_path=self.service.settings.database_path)
        manager.initialize()
        requested = manager.execute_or_request("queue_test_runner_job", {"job_id": job["id"]})
        self.service.set_approval(job["id"], requested["approval_id"])
        self.assertEqual(self.service.get_job(job["id"])["state"], "approval_pending")
        resolved = manager.resolve(requested["approval_id"], True)
        self.assertEqual(resolved["state"], "executed")
        self.assertEqual(self.service.get_job(job["id"])["state"], "queued")

    def test_interrupted_job_is_requeued_on_recovery(self):
        pairing = self.service.pair("Recoverable runner", ["system_info"])
        job = self.service.create_job(pairing["node"]["id"], "system_info", {})
        self.service.poll(pairing["node"]["id"], pairing["runner_token"])
        stale = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        connection = sqlite3.connect(self.service.settings.database_path)
        try:
            connection.execute(
                "UPDATE runner_jobs SET started_at = ? WHERE id = ?", (stale, job["id"])
            )
            connection.commit()
        finally:
            connection.close()
        self.assertEqual(self.service.recover_stale_jobs(), 1)
        self.assertEqual(self.service.get_job(job["id"])["state"], "queued")

    def test_speech_job_is_bounded_and_approval_gated(self):
        pairing = self.service.pair("Speech runner", ["speak_text"])
        job = self.service.create_job(
            pairing["node"]["id"],
            "speak_text",
            {"text": "  NEXUS online  ", "rate": 180, "volume": 0.7},
        )
        self.assertEqual(job["state"], "approval_pending")
        self.assertEqual(job["risk_level"], "SAFE_WRITE")
        self.assertEqual(job["arguments"]["text"], "NEXUS online")
        self.assertIsNone(self.service.poll(
            pairing["node"]["id"], pairing["runner_token"],
        ))
        for arguments in (
            {"text": ""},
            {"text": "x" * 2001},
            {"text": "hello", "rate": 500},
            {"text": "hello", "volume": 2},
            {"text": "hello", "command": "calc.exe"},
        ):
            with self.assertRaises(ValueError):
                self.service.create_job(
                    pairing["node"]["id"], "speak_text", arguments,
                )

    def test_media_control_job_is_fixed_and_approval_gated(self):
        pairing = self.service.pair("Media runner", ["media_control"])
        job = self.service.create_job(
            pairing["node"]["id"], "media_control",
            {"action": "volume_up", "repeat": 3},
        )
        self.assertEqual(job["state"], "approval_pending")
        self.assertEqual(job["arguments"], {"action": "volume_up", "repeat": 3})
        for arguments in (
            {"action": "launch_anything"},
            {"action": "volume_up", "repeat": 11},
            {"action": "volume_up", "key": 65},
        ):
            with self.assertRaises(ValueError):
                self.service.create_job(pairing["node"]["id"], "media_control", arguments)

    def test_application_launch_is_allowlist_id_only_and_approval_gated(self):
        pairing = self.service.pair("Application runner", ["launch_app"])
        job = self.service.create_job(
            pairing["node"]["id"], "launch_app", {"app_id": "notepad"},
        )
        self.assertEqual(job["state"], "approval_pending")
        self.assertEqual(job["arguments"], {"app_id": "notepad"})
        for arguments in (
            {"app_id": "Notepad"},
            {"app_id": "notepad", "arguments": ["unsafe"]},
            {"path": "C:/Windows/notepad.exe"},
        ):
            with self.assertRaises(ValueError):
                self.service.create_job(pairing["node"]["id"], "launch_app", arguments)


class LocalRunnerTests(unittest.TestCase):
    def test_path_boundary_and_create_only(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "NEXUS_URL": "https://nexus.example",
            "NEXUS_RUNNER_ID": "node",
            "NEXUS_RUNNER_TOKEN": "token",
            "NEXUS_RUNNER_ROOT": directory,
        }, clear=False):
            runner = LocalRunner()
            result = runner.create_text_file("notes/new.txt", "hello")
            self.assertEqual(result["bytes"], 5)
            with self.assertRaises(FileExistsError):
                runner.create_text_file("notes/new.txt", "replace")
            with self.assertRaises(ValueError):
                runner.read_text_file("../outside.txt")
            with self.assertRaises(ValueError):
                runner.read_text_file(".env")

    def test_speak_text_uses_local_engine_without_subprocess(self):
        engine = MagicMock()
        engine.getProperty.return_value = [SimpleNamespace(id="voice-0")]
        pyttsx3 = SimpleNamespace(init=MagicMock(return_value=engine))
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "NEXUS_URL": "https://nexus.example",
            "NEXUS_RUNNER_ID": "node",
            "NEXUS_RUNNER_TOKEN": "token",
            "NEXUS_RUNNER_ROOT": directory,
        }, clear=False), patch.dict(sys.modules, {"pyttsx3": pyttsx3}):
            result = LocalRunner().speak_text(
                "NEXUS speech ready", rate=180, volume=0.6, voice_index=0,
            )

        self.assertTrue(result["spoken"])
        engine.say.assert_called_once_with("NEXUS speech ready")
        engine.runAndWait.assert_called_once_with()
        engine.stop.assert_called_once_with()
        engine.setProperty.assert_any_call("voice", "voice-0")

    def test_media_control_sends_only_allowlisted_windows_key(self):
        user32 = MagicMock()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "NEXUS_URL": "https://nexus.example",
            "NEXUS_RUNNER_ID": "node",
            "NEXUS_RUNNER_TOKEN": "token",
            "NEXUS_RUNNER_ROOT": directory,
        }, clear=False), patch("scripts.nexus_runner.platform.system", return_value="Windows"), \
                patch("scripts.nexus_runner.ctypes.windll", SimpleNamespace(user32=user32), create=True):
            result = LocalRunner().media_control("play_pause", repeat=2)

        self.assertEqual(result, {"controlled": True, "action": "play_pause", "repeat": 2})
        self.assertEqual(user32.keybd_event.call_count, 4)
        user32.keybd_event.assert_any_call(0xB3, 0, 0, 0)
        user32.keybd_event.assert_any_call(0xB3, 0, 0x0002, 0)

    def test_application_launch_uses_local_allowlist_argument_array(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "demo.exe"
            executable.touch()
            environment = {
                "NEXUS_URL": "https://nexus.example",
                "NEXUS_RUNNER_ID": "node",
                "NEXUS_RUNNER_TOKEN": "token",
                "NEXUS_RUNNER_ROOT": directory,
                "NEXUS_RUNNER_APP_ALLOWLIST": json.dumps({"demo": [str(executable), "--safe"]}),
            }
            process = SimpleNamespace(pid=4321)
            with patch.dict(os.environ, environment, clear=False), \
                    patch("scripts.nexus_runner.subprocess.Popen", return_value=process) as popen:
                result = LocalRunner().launch_app("demo")
            self.assertEqual(result, {"launched": True, "app_id": "demo", "pid": 4321})
            popen.assert_called_once_with([str(executable), "--safe"], shell=False, cwd=directory)
            with patch.dict(os.environ, environment, clear=False):
                with self.assertRaises(ValueError):
                    LocalRunner().launch_app("missing")

    def test_screenshot_capture_is_bounded_and_reports_encoded_png(self):
        image = MagicMock(width=2560, height=1440)
        def save(output, **_kwargs):
            output.write(b"png-data")
        image.save.side_effect = save
        image_grab = SimpleNamespace(grab=MagicMock(return_value=image))
        pil = SimpleNamespace(ImageGrab=image_grab)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "NEXUS_URL": "https://nexus.example",
            "NEXUS_RUNNER_ID": "node",
            "NEXUS_RUNNER_TOKEN": "token",
            "NEXUS_RUNNER_ROOT": directory,
        }, clear=False), patch.dict(sys.modules, {"PIL": pil, "PIL.ImageGrab": image_grab}):
            result = LocalRunner().capture_screenshot()
        self.assertTrue(result["captured"])
        self.assertEqual(result["width"], 2560)
        self.assertEqual(base64.b64decode(result["image_base64"]), b"png-data")
        image.thumbnail.assert_called_once_with((1920, 1080))


if __name__ == "__main__":
    unittest.main()
