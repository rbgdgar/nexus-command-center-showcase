from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.app.core.config import Settings
from backend.app.core.logging import log_event
from backend.app.database import database_connection
from backend.app.media.providers import OpenAIMediaProvider, PollinationsMediaProvider


MEDIA_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
}


class MediaService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.media_root = settings.media_storage_path.resolve()
        self._tasks: set[asyncio.Task] = set()

    def initialize(self):
        self.media_root.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS media_jobs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    status TEXT NOT NULL,
                    asset_name TEXT,
                    media_type TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

    def providers(self) -> list[dict]:
        paid_allowed = self.settings.allow_paid_models
        return [
            {
                "provider": "pollinations",
                "configured": bool(self.settings.pollinations_api_key),
                "allowed": True,
                "cost_tier": "free_credits",
                "image_models": ["flux"],
                "video_models": ["wan-fast", "seedance-pro", "veo"],
            },
            {
                "provider": "openai",
                "configured": bool(self.settings.openai_api_key),
                "allowed": paid_allowed,
                "cost_tier": "paid",
                "image_models": ["gpt-image-2"],
                "video_models": ["sora-2", "sora-2-pro"],
            },
        ]

    async def generate_image(
        self, prompt: str, provider: str, model: str, width: int, height: int
    ) -> dict:
        media_provider = self._provider(provider)
        result = await media_provider.generate_image(prompt, model, width, height)
        if len(result.data) > self.settings.media_max_image_bytes:
            raise ValueError("Generated image exceeds the configured size limit")
        return self._save_completed("image", provider, model, prompt, result)

    def submit_video(
        self, prompt: str, provider: str, model: str, duration: int, aspect_ratio: str
    ) -> dict:
        self._provider(provider)
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO media_jobs
                   (id, kind, provider, model, prompt, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (job_id, "video", provider, model, prompt, "queued", now, now),
            )
        task = asyncio.create_task(
            self._run_video(job_id, prompt, provider, model, duration, aspect_ratio)
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return self.get_job(job_id) or {}

    def store_runner_screenshot(self, data: bytes) -> dict:
        if not data or len(data) > self.settings.media_max_image_bytes:
            raise ValueError("Screenshot is empty or exceeds the protected image limit")
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        asset_name = self._write_asset(job_id, "image/png", data)
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO media_jobs
                   (id, kind, provider, model, prompt, status, asset_name, media_type,
                    created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (job_id, "screenshot", "local-runner", "screen-capture", "Approved local screenshot",
                 "completed", asset_name, "image/png", now, now),
            )
        return self.get_job(job_id) or {}

    async def _run_video(
        self, job_id: str, prompt: str, provider: str, model: str,
        duration: int, aspect_ratio: str,
    ):
        self._update(job_id, status="running")
        try:
            result = await self._provider(provider).generate_video(
                prompt, model, duration, aspect_ratio
            )
            if len(result.data) > self.settings.media_max_video_bytes:
                raise ValueError("Generated video exceeds the configured size limit")
            asset_name = self._write_asset(job_id, result.media_type, result.data)
            self._update(
                job_id, status="completed", asset_name=asset_name,
                media_type=result.media_type,
            )
        except Exception as error:
            log_event("media_generation_failure", job_id=job_id, provider=provider, error=str(error))
            self._update(job_id, status="failed", error=str(error)[:1000])

    def list_jobs(self, limit: int = 50) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM media_jobs ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [self._public(dict(row)) for row in rows]

    def get_job(self, job_id: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM media_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._public(dict(row)) if row else None

    def asset_path(self, job_id: str) -> Path | None:
        job = self.get_job(job_id)
        if not job or job["status"] != "completed" or not job.get("asset_name"):
            return None
        path = (self.media_root / job["asset_name"]).resolve()
        if path.parent != self.media_root or not path.is_file():
            return None
        return path

    def _save_completed(self, kind, provider, model, prompt, result):
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        asset_name = self._write_asset(job_id, result.media_type, result.data)
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO media_jobs
                   (id, kind, provider, model, prompt, status, asset_name, media_type,
                    created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (job_id, kind, provider, model, prompt, "completed", asset_name,
                 result.media_type, now, now),
            )
        return self.get_job(job_id) or {}

    def _write_asset(self, job_id: str, media_type: str, data: bytes) -> str:
        suffix = MEDIA_TYPES.get(media_type)
        if not suffix:
            raise ValueError(f"Unsupported generated media type: {media_type}")
        name = f"{job_id}{suffix}"
        (self.media_root / name).write_bytes(data)
        return name

    def _provider(self, provider: str):
        if provider == "pollinations":
            return PollinationsMediaProvider(
                self.settings.pollinations_api_key or "",
                self.settings.pollinations_base_url,
            )
        if provider == "openai":
            if not self.settings.allow_paid_models:
                raise ValueError("Paid media providers are disabled by policy")
            return OpenAIMediaProvider(
                self.settings.openai_api_key or "", self.settings.openai_base_url
            )
        raise ValueError(f"Unsupported media provider: {provider}")

    def _connection(self):
        return database_connection(
            database_path=self.settings.database_path,
            database_url=self.settings.database_url,
        )

    def _update(self, job_id: str, **fields):
        allowed = {"status", "asset_name", "media_type", "error"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        statement = ", ".join(f"{key} = ?" for key in updates)
        with self._connection() as connection:
            connection.execute(
                f"UPDATE media_jobs SET {statement} WHERE id = ?",
                (*updates.values(), job_id),
            )

    @staticmethod
    def _public(job: dict) -> dict:
        if job.get("asset_name"):
            job["asset_url"] = f"/api/media/assets/{job['id']}"
        return job
