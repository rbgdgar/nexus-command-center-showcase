from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx


@dataclass
class GeneratedMedia:
    data: bytes
    media_type: str
    provider_id: str | None = None


class PollinationsMediaProvider:
    provider_name = "pollinations"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://gen.pollinations.ai",
        client: httpx.AsyncClient | None = None,
    ):
        if not api_key.strip():
            raise ValueError("NEXUS_POLLINATIONS_API_KEY is required")
        if not base_url.startswith("https://"):
            raise ValueError("Pollinations API must use HTTPS")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.client = client

    async def generate_image(
        self,
        prompt: str,
        model: str = "flux",
        width: int = 1024,
        height: int = 1024,
    ) -> GeneratedMedia:
        return await self._download(
            f"/image/{quote(prompt, safe='')}",
            {"model": model, "width": width, "height": height, "safe": "true"},
            "image/",
            180.0,
        )

    async def generate_video(
        self,
        prompt: str,
        model: str = "wan-fast",
        duration: int = 4,
        aspect_ratio: str = "16:9",
    ) -> GeneratedMedia:
        return await self._download(
            f"/video/{quote(prompt, safe='')}",
            {
                "model": model,
                "duration": duration,
                "aspectRatio": aspect_ratio,
                "safe": "true",
            },
            "video/",
            900.0,
        )

    async def _download(
        self,
        path: str,
        params: dict[str, Any],
        expected_type: str,
        timeout: float,
    ) -> GeneratedMedia:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if self.client:
            response = await self.client.get(path, params=params, headers=headers)
        else:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=timeout, follow_redirects=True
            ) as client:
                response = await client.get(path, params=params, headers=headers)
        response.raise_for_status()
        media_type = response.headers.get("content-type", "").split(";", 1)[0]
        if not media_type.startswith(expected_type):
            raise RuntimeError(f"Provider returned unexpected media type: {media_type}")
        return GeneratedMedia(response.content, media_type)


class OpenAIMediaProvider:
    provider_name = "openai"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        client: httpx.AsyncClient | None = None,
    ):
        if not api_key.strip():
            raise ValueError("NEXUS_OPENAI_API_KEY is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.client = client

    async def generate_image(
        self,
        prompt: str,
        model: str = "gpt-image-2",
        width: int = 1024,
        height: int = 1024,
    ) -> GeneratedMedia:
        response = await self._request(
            "POST",
            "/images/generations",
            json={
                "model": model,
                "prompt": prompt,
                "size": f"{width}x{height}",
                "response_format": "b64_json",
            },
        )
        response.raise_for_status()
        item = (response.json().get("data") or [{}])[0]
        if item.get("b64_json"):
            return GeneratedMedia(base64.b64decode(item["b64_json"]), "image/png")
        if item.get("url"):
            return await self._download_url(item["url"], "image/")
        raise RuntimeError("OpenAI returned no generated image")

    async def generate_video(
        self,
        prompt: str,
        model: str = "sora-2",
        duration: int = 4,
        aspect_ratio: str = "16:9",
    ) -> GeneratedMedia:
        size = "1280x720" if aspect_ratio == "16:9" else "720x1280"
        response = await self._request(
            "POST", "/videos", json={
                "model": model, "prompt": prompt, "seconds": str(duration), "size": size,
            }
        )
        response.raise_for_status()
        job = response.json()
        video_id = job.get("id")
        if not video_id:
            raise RuntimeError("OpenAI returned no video job ID")
        for _ in range(240):
            status_response = await self._request("GET", f"/videos/{video_id}")
            status_response.raise_for_status()
            status = status_response.json().get("status")
            if status == "completed":
                content = await self._request("GET", f"/videos/{video_id}/content")
                content.raise_for_status()
                return GeneratedMedia(content.content, "video/mp4", video_id)
            if status in {"failed", "expired", "cancelled"}:
                raise RuntimeError(f"OpenAI video job ended with status: {status}")
            await asyncio.sleep(5)
        raise TimeoutError("OpenAI video generation timed out")

    async def _request(self, method: str, path: str, **kwargs):
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if self.client:
            return await self.client.request(method, path, headers=headers, **kwargs)
        async with httpx.AsyncClient(base_url=self.base_url, timeout=180.0) as client:
            return await client.request(method, path, headers=headers, **kwargs)

    async def _download_url(self, url: str, expected_type: str) -> GeneratedMedia:
        async with httpx.AsyncClient(timeout=180.0, follow_redirects=True) as client:
            response = await client.get(url)
        response.raise_for_status()
        media_type = response.headers.get("content-type", "").split(";", 1)[0]
        if not media_type.startswith(expected_type):
            raise RuntimeError(f"Provider returned unexpected media type: {media_type}")
        return GeneratedMedia(response.content, media_type)
