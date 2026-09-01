import tempfile
import unittest
from pathlib import Path

import httpx

from backend.app.core.config import Settings
from backend.app.media.providers import (
    GeneratedMedia,
    OpenAIMediaProvider,
    PollinationsMediaProvider,
)
from backend.app.media.service import MediaService


class MediaProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_pollinations_image_generation(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, content=b"image-bytes", headers={"content-type": "image/png"})

        async with httpx.AsyncClient(
            base_url="https://gen.pollinations.ai",
            transport=httpx.MockTransport(handler),
        ) as client:
            provider = PollinationsMediaProvider("secret", client=client)
            result = await provider.generate_image("NEXUS command center", "flux", 512, 512)

        self.assertEqual(result.data, b"image-bytes")
        self.assertEqual(result.media_type, "image/png")
        self.assertEqual(requests[0].headers["authorization"], "Bearer secret")
        self.assertNotIn("secret", str(requests[0].url))

    async def test_openai_image_generation(self):
        def handler(request):
            return httpx.Response(200, json={"data": [{"b64_json": "aW1hZ2U="}]})

        async with httpx.AsyncClient(
            base_url="https://api.openai.com/v1",
            transport=httpx.MockTransport(handler),
        ) as client:
            provider = OpenAIMediaProvider("secret", client=client)
            result = await provider.generate_image("NEXUS", "gpt-image-2", 1024, 1024)

        self.assertEqual(result.data, b"image")
        self.assertEqual(result.media_type, "image/png")


class MediaServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.service = MediaService(Settings(
            _env_file=None,
            database_path=root / "media.db",
            media_storage_path=root / "assets",
            model_provider="ollama",
        ))
        self.service.initialize()

    def tearDown(self):
        self.temp.cleanup()

    def test_completed_media_metadata_and_asset_are_persisted(self):
        job = self.service._save_completed(
            "image", "test", "test-image", "safe prompt",
            GeneratedMedia(b"generated", "image/png"),
        )

        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["asset_url"], f"/api/media/assets/{job['id']}")
        self.assertEqual(self.service.asset_path(job["id"]).read_bytes(), b"generated")
        self.assertEqual(len(self.service.list_jobs()), 1)


if __name__ == "__main__":
    unittest.main()
