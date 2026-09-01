from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from backend.app.database import database_connection
from backend.app.core.logging import log_event


JOB_TYPES = {
    "system_health": ("get_system_info", {}),
    "project_health": ("get_index_status", {}),
    "git_status": ("get_git_status", {}),
    "docker_status": ("list_docker_containers", {}),
    "infrastructure_check": ("get_terraform_version", {}),
    "research": ("search_project_knowledge", None),
    "reminder": ("automation_reminder", None),
}


def automation_reminder(message: str) -> dict:
    """Create an in-app reminder result without external side effects."""
    return {"reminder": message}


class TaskScheduler:
    def __init__(
        self,
        executor: Callable[[str, dict], dict],
        database_path: str | Path | None = None,
        poll_seconds: int = 30,
        database_url: str | None = None,
    ):
        self.executor = executor
        self.database_path = Path(database_path) if database_path else None
        self.database_url = database_url
        self.poll_seconds = poll_seconds
        self._task: asyncio.Task | None = None

    def _connection(self):
        return database_connection(self.database_path, self.database_url)

    def initialize(self):
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS automation_jobs (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
                    schedule TEXT NOT NULL, agent TEXT NOT NULL, job_type TEXT NOT NULL,
                    enabled INTEGER NOT NULL, last_run TEXT, next_run TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS automation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                    started_at TEXT NOT NULL, finished_at TEXT NOT NULL,
                    status TEXT NOT NULL, result TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def next_time(schedule: str, now: datetime | None = None) -> datetime:
        now = now or datetime.now(timezone.utc)
        if schedule.startswith("interval:"):
            seconds = int(schedule.split(":", 1)[1])
            if seconds < 60:
                raise ValueError("Minimum automation interval is 60 seconds")
            return now + timedelta(seconds=seconds)
        if schedule == "daily":
            return now + timedelta(days=1)
        raise ValueError("Schedule must be 'daily' or 'interval:<seconds>'")

    def create(self, name: str, description: str, schedule: str, agent: str, job_type: str, enabled: bool = True) -> dict:
        if job_type not in JOB_TYPES:
            raise ValueError("Unsupported automation job type")
        now = datetime.now(timezone.utc)
        job_id = str(uuid.uuid4())
        next_run = self.next_time(schedule, now).isoformat()
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO automation_jobs
                (id, name, description, schedule, agent, job_type, enabled, next_run, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?)""",
                (job_id, name.strip(), description.strip(), schedule, agent, job_type, int(enabled), next_run, now.isoformat()),
            )
        return self.get(job_id)

    def get(self, job_id: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM automation_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job(row) if row else None

    def list(self) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM automation_jobs ORDER BY created_at DESC").fetchall()
        return [self._job(row) for row in rows]

    def set_enabled(self, job_id: str, enabled: bool) -> dict | None:
        with self._connection() as connection:
            connection.execute("UPDATE automation_jobs SET enabled = ? WHERE id = ?", (int(enabled), job_id))
        return self.get(job_id)

    def run(self, job_id: str, now: datetime | None = None) -> dict | None:
        job = self.get(job_id)
        if not job or not job["enabled"]:
            return None
        now = now or datetime.now(timezone.utc)
        tool, fixed_arguments = JOB_TYPES[job["job_type"]]
        arguments = fixed_arguments if fixed_arguments is not None else {
            "query" if job["job_type"] == "research" else "message": job["description"]
        }
        started = now.isoformat()
        try:
            result = self.executor(tool, arguments)
            status = result.get("state", "completed") if isinstance(result, dict) else "completed"
        except Exception as error:
            result = {"error": str(error)}
            status = "failed"
        log_event("automation_run", job_id=job_id, tool=tool, status=status)
        finished = datetime.now(timezone.utc).isoformat()
        next_run = self.next_time(job["schedule"], now).isoformat()
        with self._connection() as connection:
            connection.execute(
                "UPDATE automation_jobs SET last_run = ?, next_run = ?, status = ? WHERE id = ?",
                (started, next_run, status, job_id),
            )
            connection.execute(
                """INSERT INTO automation_history
                (job_id, started_at, finished_at, status, result) VALUES (?, ?, ?, ?, ?)""",
                (job_id, started, finished, status, json.dumps(result, default=str)),
            )
        return {"job_id": job_id, "status": status, "result": result}

    def run_due(self, now: datetime | None = None) -> list[dict]:
        now = now or datetime.now(timezone.utc)
        return [
            result for job in self.list()
            if job["enabled"] and datetime.fromisoformat(job["next_run"]) <= now
            if (result := self.run(job["id"], now)) is not None
        ]

    def history(self, job_id: str | None = None, limit: int = 100) -> list[dict]:
        with self._connection() as connection:
            if job_id:
                rows = connection.execute(
                    "SELECT * FROM automation_history WHERE job_id = ? ORDER BY id DESC LIMIT ?",
                    (job_id, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM automation_history ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["result"] = json.loads(item["result"])
            items.append(item)
        return items

    async def start(self):
        if self._task or self.poll_seconds <= 0:
            return
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self):
        while True:
            self.run_due()
            await asyncio.sleep(self.poll_seconds)

    @staticmethod
    def _job(row) -> dict:
        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        return item
