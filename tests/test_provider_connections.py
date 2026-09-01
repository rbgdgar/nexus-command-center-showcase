import tempfile
import unittest
from pathlib import Path

import httpx
from cryptography.fernet import Fernet

from backend.app.core.config import Settings
from backend.app.database import database_connection
from backend.app.integrations.provider_connections import ProviderConnectionService


class ProviderConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_verified_key_is_encrypted_and_restored(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"models": [{"name": "gemini-test"}]})

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "connections.db"
            encryption_key = Fernet.generate_key().decode("ascii")
            settings = Settings(
                _env_file=None,
                database_path=database_path,
                provider_secret_encryption_key=encryption_key,
            )
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                service = ProviderConnectionService(settings, client=client)
                service.initialize()
                result = await service.connect(
                    "gemini", "test-provider-secret", "gemini-3.7-flash"
                )

            self.assertEqual(result["mode"], "encrypted")
            self.assertNotIn("test-provider-secret", str(result))
            self.assertNotIn("test-provider-secret", str(service.public_status()))
            self.assertEqual(requests[0].headers["x-goog-api-key"], "test-provider-secret")
            with database_connection(database_path=database_path) as connection:
                row = connection.execute(
                    "SELECT encrypted_key FROM provider_connections WHERE provider = ?",
                    ("gemini",),
                ).fetchone()
            self.assertNotIn("test-provider-secret", row["encrypted_key"])

            restored_settings = Settings(
                _env_file=None,
                database_path=database_path,
                provider_secret_encryption_key=encryption_key,
            )
            restored = ProviderConnectionService(restored_settings)
            restored.initialize()
            self.assertEqual(restored.resolve_key("gemini"), "test-provider-secret")
            self.assertEqual(restored_settings.gemini_api_key, "test-provider-secret")
            disconnected = restored.disconnect("gemini")
            self.assertFalse(disconnected["configured"])
            self.assertIsNone(restored.resolve_key("gemini"))

    async def test_without_encryption_key_connection_is_session_only(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"data": []})

        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Settings(
                _env_file=None,
                database_path=Path(temp_dir) / "connections.db",
            )
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                service = ProviderConnectionService(settings, client=client)
                service.initialize()
                result = await service.connect("openrouter", "session-secret")

            self.assertEqual(result["mode"], "session")
            self.assertFalse(service.public_status()["persistent_available"])
            self.assertEqual(service.resolve_key("openrouter"), "session-secret")
            self.assertEqual(requests[0].url.path, "/api/v1/key")

    async def test_compatible_endpoint_requires_allowlisted_host(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Settings(
                _env_file=None,
                database_path=Path(temp_dir) / "connections.db",
                provider_allowed_hosts="models.example.test",
            )
            service = ProviderConnectionService(settings)
            service.initialize()
            with self.assertRaisesRegex(ValueError, "NEXUS_PROVIDER_ALLOWED_HOSTS"):
                await service.connect(
                    "compatible", "provider-secret", "example-model",
                    "https://unlisted.example.test/v1",
                )

    async def test_rejected_key_is_not_stored(self):
        def handler(_request):
            return httpx.Response(401, json={"error": "invalid key"})

        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Settings(
                _env_file=None,
                database_path=Path(temp_dir) / "connections.db",
            )
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                service = ProviderConnectionService(settings, client=client)
                service.initialize()
                with self.assertRaisesRegex(ValueError, "HTTP 401"):
                    await service.connect("groq", "rejected-secret")
            self.assertIsNone(service.resolve_key("groq"))


if __name__ == "__main__":
    unittest.main()
