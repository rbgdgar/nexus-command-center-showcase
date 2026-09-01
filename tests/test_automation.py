import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.automation.scheduler import TaskScheduler


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.executions = []
        self.temp_dir = tempfile.TemporaryDirectory()
        self.scheduler = TaskScheduler(
            lambda tool, args: self.executions.append((tool, args)) or {"state": "executed"},
            Path(self.temp_dir.name) / "jobs.db",
            poll_seconds=0,
        )
        self.scheduler.initialize()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_run_and_history(self):
        job = self.scheduler.create("Git check", "Repository health", "interval:300", "DevOps Agent", "git_status")
        result = self.scheduler.run(job["id"])
        self.assertEqual(result["status"], "executed")
        self.assertEqual(self.executions[0], ("get_git_status", {}))
        self.assertEqual(len(self.scheduler.history(job["id"])), 1)

    def test_due_jobs_and_toggle(self):
        job = self.scheduler.create("Reminder", "Review alerts", "daily", "NEXUS", "reminder")
        due = datetime.now(timezone.utc) + timedelta(days=2)
        self.assertEqual(len(self.scheduler.run_due(due)), 1)
        self.scheduler.set_enabled(job["id"], False)
        self.assertEqual(self.scheduler.run_due(due + timedelta(days=2)), [])

    def test_schedule_and_type_validation(self):
        with self.assertRaises(ValueError):
            self.scheduler.create("Bad", "", "interval:5", "NEXUS", "git_status")
        with self.assertRaises(ValueError):
            self.scheduler.create("Bad", "", "daily", "NEXUS", "shell")


if __name__ == "__main__":
    unittest.main()
