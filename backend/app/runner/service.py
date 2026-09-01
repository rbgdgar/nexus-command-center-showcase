from __future__ import annotations

import hashlib
import json
import secrets
import re
import uuid
from datetime import datetime, timedelta, timezone

from backend.app.core.config import Settings, get_settings
from backend.app.database import database_connection


RUNNER_TOOLS = {
    "system_info": {"risk_level": "READ_ONLY", "description": "Inspect local OS and Python details"},
    "git_status": {"risk_level": "READ_ONLY", "description": "Inspect the approved root Git status"},
    "git_diff": {"risk_level": "READ_ONLY", "description": "Inspect the approved root Git diff"},
    "list_files": {"risk_level": "READ_ONLY", "description": "List files below the approved root"},
    "read_text_file": {"risk_level": "READ_ONLY", "description": "Read a non-secret text file below the approved root"},
    "create_text_file": {"risk_level": "SAFE_WRITE", "description": "Create a new text file below the approved root"},
    "speak_text": {"risk_level": "SAFE_WRITE", "description": "Speak bounded text through the local system voice"},
    "media_control": {"risk_level": "SAFE_WRITE", "description": "Send a fixed media or volume command to the local system"},
    "launch_app": {"risk_level": "SAFE_WRITE", "description": "Launch an application from the local runner allowlist"},
    "capture_screenshot": {"risk_level": "SAFE_WRITE", "description": "Capture a bounded local screenshot into protected media storage"},
}

MAX_SPEECH_CHARS = 2000
MEDIA_ACTIONS = {
    "play_pause", "next_track", "previous_track", "stop",
    "volume_mute", "volume_down", "volume_up",
}
APP_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,49}$")


class RunnerService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _connection(self):
        return database_connection(self.settings.database_path, self.settings.database_url)

    def initialize(self):
        with self._connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS runner_nodes (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT NOT NULL,
                    capabilities TEXT NOT NULL, active INTEGER NOT NULL,
                    created_at TEXT NOT NULL, last_seen_at TEXT
                );
                CREATE TABLE IF NOT EXISTS runner_jobs (
                    id TEXT PRIMARY KEY, node_id TEXT NOT NULL, tool TEXT NOT NULL,
                    arguments TEXT NOT NULL, risk_level TEXT NOT NULL, state TEXT NOT NULL,
                    approval_id TEXT, result TEXT, created_at TEXT NOT NULL,
                    started_at TEXT, completed_at TEXT,
                    FOREIGN KEY (node_id) REFERENCES runner_nodes(id)
                );
            """)
        self.recover_stale_jobs()

    def recover_stale_jobs(self, max_age_minutes: int = 15) -> int:
        """Requeue interrupted jobs; their original approval state is preserved."""
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)).isoformat()
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT id FROM runner_jobs
                   WHERE state = 'running' AND started_at IS NOT NULL AND started_at < ?""",
                (cutoff,),
            ).fetchall()
            for row in rows:
                connection.execute(
                    "UPDATE runner_jobs SET state = 'queued', started_at = NULL WHERE id = ?",
                    (row["id"],),
                )
        return len(rows)

    def pair(self, name: str, capabilities: list[str] | None = None) -> dict:
        name = name.strip()
        if not name or len(name) > 100:
            raise ValueError("Runner name must be 1-100 characters")
        node_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc).isoformat()
        advertised = sorted(set(capabilities or RUNNER_TOOLS))
        if any(item not in RUNNER_TOOLS for item in advertised):
            raise ValueError("Runner advertised an unsupported capability")
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO runner_nodes
                   (id, name, token_hash, capabilities, active, created_at)
                   VALUES (?, ?, ?, ?, 1, ?)""",
                (node_id, name, self._hash(token), json.dumps(advertised), now),
            )
        return {"node": self.get_node(node_id), "runner_token": token}

    def create_job(self, node_id: str, tool: str, arguments: dict) -> dict:
        node = self.get_node(node_id)
        if not node or not node["active"]:
            raise ValueError("Runner node is unavailable")
        definition = RUNNER_TOOLS.get(tool)
        if not definition or tool not in node["capabilities"]:
            raise ValueError("Tool is not allowed for this runner")
        arguments = self._validate_arguments(tool, arguments)
        encoded = json.dumps(arguments, default=str)
        if len(encoded) > 50000:
            raise ValueError("Runner arguments are too large")
        job_id = str(uuid.uuid4())
        state = "queued" if definition["risk_level"] == "READ_ONLY" else "approval_pending"
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO runner_jobs
                   (id, node_id, tool, arguments, risk_level, state, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (job_id, node_id, tool, encoded, definition["risk_level"], state,
                 datetime.now(timezone.utc).isoformat()),
            )
        return self.get_job(job_id) or {}

    @staticmethod
    def _validate_arguments(tool: str, arguments: dict) -> dict:
        if not isinstance(arguments, dict):
            raise ValueError("Runner arguments must be an object")
        if tool == "media_control":
            allowed = {"action", "repeat"}
            if set(arguments) - allowed:
                raise ValueError("Media control arguments contain unsupported fields")
            action = arguments.get("action")
            if action not in MEDIA_ACTIONS:
                raise ValueError("Media control action is not allow-listed")
            repeat = arguments.get("repeat", 1)
            if isinstance(repeat, bool) or not isinstance(repeat, int) or not 1 <= repeat <= 10:
                raise ValueError("Media control repeat must be an integer from 1 to 10")
            return {"action": action, "repeat": repeat}
        if tool == "launch_app":
            if set(arguments) != {"app_id"}:
                raise ValueError("Application launch accepts only app_id")
            app_id = arguments.get("app_id")
            if not isinstance(app_id, str) or not APP_ID_PATTERN.fullmatch(app_id):
                raise ValueError("Application ID must be a lowercase allowlist identifier")
            return {"app_id": app_id}
        if tool == "capture_screenshot":
            if arguments:
                raise ValueError("Screenshot capture does not accept arguments")
            return {}
        if tool != "speak_text":
            return arguments
        allowed = {"text", "rate", "volume", "voice_index"}
        if set(arguments) - allowed:
            raise ValueError("Speech arguments contain unsupported fields")
        text = arguments.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_SPEECH_CHARS:
            raise ValueError(f"Speech text must be 1-{MAX_SPEECH_CHARS} characters")
        rate = arguments.get("rate", 170)
        if isinstance(rate, bool) or not isinstance(rate, int) or not 120 <= rate <= 220:
            raise ValueError("Speech rate must be an integer from 120 to 220")
        volume = arguments.get("volume", 1.0)
        if isinstance(volume, bool) or not isinstance(volume, (int, float)) or not 0 <= volume <= 1:
            raise ValueError("Speech volume must be from 0 to 1")
        voice_index = arguments.get("voice_index")
        if (
            voice_index is not None
            and (isinstance(voice_index, bool) or not isinstance(voice_index, int)
                 or not 0 <= voice_index <= 20)
        ):
            raise ValueError("Speech voice index must be an integer from 0 to 20")
        normalized = {"text": text.strip(), "rate": rate, "volume": float(volume)}
        if voice_index is not None:
            normalized["voice_index"] = voice_index
        return normalized

    def set_approval(self, job_id: str, approval_id: str):
        with self._connection() as connection:
            connection.execute(
                "UPDATE runner_jobs SET approval_id = ? WHERE id = ? AND state = 'approval_pending'",
                (approval_id, job_id),
            )

    def queue_approved(self, job_id: str) -> dict:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM runner_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if not row:
                raise ValueError("Runner job not found")
            if row["risk_level"] != "SAFE_WRITE" or row["state"] != "approval_pending":
                raise ValueError("Runner job is not awaiting safe-write approval")
            connection.execute(
                "UPDATE runner_jobs SET state = 'queued' WHERE id = ?", (job_id,)
            )
        return {"job_id": job_id, "state": "queued"}

    def apply_approval_result(self, approval_id: str, state: str):
        if state in {"denied", "blocked", "failed"}:
            with self._connection() as connection:
                connection.execute(
                    "UPDATE runner_jobs SET state = ? WHERE approval_id = ? AND state = 'approval_pending'",
                    (state, approval_id),
                )

    def poll(self, node_id: str, token: str) -> dict | None:
        self._authenticate(node_id, token)
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute(
                "UPDATE runner_nodes SET last_seen_at = ? WHERE id = ?", (now, node_id)
            )
            row = connection.execute(
                """SELECT * FROM runner_jobs WHERE node_id = ? AND state = 'queued'
                   ORDER BY created_at LIMIT 1""", (node_id,),
            ).fetchone()
            if not row:
                return None
            connection.execute(
                "UPDATE runner_jobs SET state = 'running', started_at = ? WHERE id = ? AND state = 'queued'",
                (now, row["id"]),
            )
        job = dict(row)
        job["state"] = "running"
        return self._public_job(job)

    def complete(self, node_id: str, token: str, job_id: str, succeeded: bool, result) -> dict:
        self._authenticate(node_id, token)
        encoded = json.dumps(result, default=str)
        if len(encoded) > 200000:
            raise ValueError("Runner result is too large")
        state = "completed" if succeeded else "failed"
        with self._connection() as connection:
            row = connection.execute(
                "SELECT id FROM runner_jobs WHERE id = ? AND node_id = ? AND state = 'running'",
                (job_id, node_id),
            ).fetchone()
            if not row:
                raise ValueError("Running job not found")
            connection.execute(
                "UPDATE runner_jobs SET state = ?, result = ?, completed_at = ? WHERE id = ?",
                (state, encoded, datetime.now(timezone.utc).isoformat(), job_id),
            )
        return self.get_job(job_id) or {}

    def heartbeat(self, node_id: str, token: str):
        self._authenticate(node_id, token)
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute(
                "UPDATE runner_nodes SET last_seen_at = ? WHERE id = ?", (now, node_id)
            )
        return {"status": "online", "last_seen_at": now}

    def list_nodes(self) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM runner_nodes ORDER BY created_at DESC"
            ).fetchall()
        return [self._public_node(dict(row)) for row in rows]

    def get_node(self, node_id: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM runner_nodes WHERE id = ?", (node_id,)
            ).fetchone()
        return self._public_node(dict(row)) if row else None

    def disable(self, node_id: str) -> dict:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT id FROM runner_nodes WHERE id = ?", (node_id,)
            ).fetchone()
            if not row:
                raise ValueError("Runner node not found")
            connection.execute(
                "UPDATE runner_nodes SET active = 0 WHERE id = ?", (node_id,)
            )
        return self.get_node(node_id) or {}

    def list_jobs(self, limit: int = 100) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM runner_jobs ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [self._public_job(dict(row)) for row in rows]

    def get_job(self, job_id: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM runner_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._public_job(dict(row)) if row else None

    def _authenticate(self, node_id: str, token: str):
        with self._connection() as connection:
            row = connection.execute(
                "SELECT token_hash, active FROM runner_nodes WHERE id = ?", (node_id,)
            ).fetchone()
        if not row or not row["active"] or not secrets.compare_digest(row["token_hash"], self._hash(token)):
            raise PermissionError("Invalid runner credentials")

    def validate_running_job(self, node_id: str, token: str, job_id: str, tool: str):
        self._authenticate(node_id, token)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT id FROM runner_jobs WHERE id = ? AND node_id = ? AND tool = ? AND state = 'running'",
                (job_id, node_id, tool),
            ).fetchone()
        if not row:
            raise ValueError("Running runner job not found")

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def _public_node(node: dict) -> dict:
        node.pop("token_hash", None)
        node["active"] = bool(node["active"])
        node["capabilities"] = json.loads(node["capabilities"])
        return node

    @staticmethod
    def _public_job(job: dict) -> dict:
        for field in ("arguments", "result"):
            if job.get(field):
                job[field] = json.loads(job[field])
        return job


runner_service = RunnerService(get_settings())


def queue_runner_job(job_id: str):
    """Queue a previously created safe-write runner job after approval."""
    return runner_service.queue_approved(job_id)
