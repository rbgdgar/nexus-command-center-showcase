import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from backend.app.models.provider import ChatModelResponse
from backend.app.agents.orchestration import orchestration_service
from backend.main import app, model_registry, settings


class ApiContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://testserver",
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_root_and_health_contracts(self):
        root = await self.client.get("/")
        health = await self.client.get("/health")

        self.assertEqual(root.status_code, 200)
        self.assertEqual(root.json(), {
            "name": "NEXUS", "version": "2.21.0", "status": "online"
        })
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "healthy")

    async def test_readiness_and_security_headers(self):
        response = await self.client.get(
            "/ready", headers={"X-Request-ID": "nexus-test-request"}
        )

        self.assertIn(response.status_code, (200, 503))
        self.assertEqual(response.headers["x-request-id"], "nexus-test-request")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertIn("database", response.json()["checks"])
        self.assertIn("model", response.json()["checks"])

    async def test_api_access_token_protects_private_routes(self):
        original = settings.access_token
        settings.access_token = "test-access-token"
        try:
            config = await self.client.get("/api/config")
            missing = await self.client.get("/api/system")
            wrong = await self.client.get(
                "/api/system", headers={"Authorization": "Bearer wrong"}
            )
            allowed = await self.client.get(
                "/api/system",
                headers={"Authorization": "Bearer test-access-token"},
            )
        finally:
            settings.access_token = original

        self.assertEqual(config.status_code, 200)
        self.assertTrue(config.json()["authentication_required"])
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(allowed.status_code, 200)

    async def test_demo_mode_is_public_but_read_only(self):
        original = settings.demo_mode
        settings.demo_mode = True
        try:
            config = await self.client.get("/api/config")
            collections = await self.client.get("/api/conversations")
            blocked = await self.client.post("/api/automations", json={})
        finally:
            settings.demo_mode = original

        self.assertEqual(config.status_code, 200)
        self.assertTrue(config.json()["demo_mode"])
        self.assertEqual(collections.status_code, 200)
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(
            blocked.json()["detail"],
            "This public showcase is read-only demo mode",
        )

    async def test_read_only_collection_contracts(self):
        contracts = {
            "/api/conversations": "conversations",
            "/api/memories": "memories",
            "/api/projects": "projects",
            "/api/tools": "tools",
            "/api/approvals?state=pending": "approvals",
            "/api/audit": "records",
            "/api/automations": "jobs",
            "/api/automations/history": "history",
            "/api/notifications": "notifications",
            "/api/models": "models",
            "/api/media/providers": "providers",
            "/api/media/jobs": "jobs",
            "/api/runner": "nodes",
            "/api/operations": "services",
            "/api/provider-connections": "providers",
            "/api/orchestration/plans": "plans",
        }

        for path, key in contracts.items():
            with self.subTest(path=path):
                response = await self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIsInstance(response.json()[key], list)

    async def test_authenticated_operations_contract(self):
        original = settings.access_token
        settings.access_token = "operations-token"
        try:
            denied = await self.client.get("/api/operations")
            allowed = await self.client.get(
                "/api/operations",
                headers={"Authorization": "Bearer operations-token"},
            )
        finally:
            settings.access_token = original

        self.assertEqual(denied.status_code, 401)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.json()["version"], "2.21.0")
        self.assertIn(allowed.json()["state"], {"operational", "attention"})
        pwa = next(
            item for item in allowed.json()["services"]
            if item["name"] == "authenticated-pwa"
        )
        self.assertEqual(pwa["state"], "ready")

    async def test_validation_errors_are_http_contracts(self):
        invalid_memory = await self.client.get("/api/memories?category=secret")
        short_search = await self.client.get("/api/projects/search?query=x")
        invalid_job = await self.client.post("/api/automations", json={
            "name": "Unsafe",
            "schedule": "interval:5",
            "job_type": "shell",
        })
        invalid_model = await self.client.post("/api/chat", json={
            "message": "hello",
            "provider": "untrusted-provider",
            "model": "unknown",
        })
        invalid_image = await self.client.post(
            "/api/media/understand",
            files={"image": ("notes.txt", b"not an image", "text/plain")},
        )
        invalid_runner = await self.client.post(
            "/api/runner/nodes/missing/poll",
            headers={"Authorization": "Bearer invalid-runner-token"},
        )
        original_access_token = settings.access_token
        settings.access_token = None
        try:
            provider_write_without_access_control = await self.client.put(
                "/api/provider-connections/gemini",
                json={"api_key": "not-a-real-key"},
            )
        finally:
            settings.access_token = original_access_token

        self.assertEqual(invalid_memory.status_code, 400)
        self.assertEqual(invalid_memory.json()["detail"], "Invalid memory category")
        self.assertEqual(short_search.status_code, 422)
        self.assertEqual(invalid_job.status_code, 400)
        self.assertEqual(invalid_model.status_code, 400)
        self.assertEqual(invalid_image.status_code, 400)
        self.assertEqual(invalid_runner.status_code, 401)
        self.assertEqual(invalid_runner.json()["detail"], "Invalid runner credentials")
        self.assertEqual(provider_write_without_access_control.status_code, 403)

    async def test_provider_connection_rejects_unknown_provider_without_echoing_key(self):
        original = settings.access_token
        settings.access_token = "provider-admin-token"
        try:
            response = await self.client.put(
                "/api/provider-connections/unknown",
                headers={"Authorization": "Bearer provider-admin-token"},
                json={"api_key": "never-echo-this-secret"},
            )
        finally:
            settings.access_token = original

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("never-echo-this-secret", response.text)

    async def test_provider_secret_requires_https_or_loopback(self):
        original = settings.access_token
        settings.access_token = "provider-admin-token"
        insecure_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://remote.example",
        )
        try:
            response = await insecure_client.put(
                "/api/provider-connections/gemini",
                headers={"Authorization": "Bearer provider-admin-token"},
                json={"api_key": "never-send-over-http"},
            )
        finally:
            await insecure_client.aclose()
            settings.access_token = original

        self.assertEqual(response.status_code, 400)
        self.assertIn("HTTPS", response.json()["detail"])
        self.assertNotIn("never-send-over-http", response.text)

    async def test_message_integration_requires_preview_before_egress(self):
        profile = SimpleNamespace(
            provider="gemini", model="gemini-test", cost_tier="free_tier"
        )
        profile.id = f"{profile.provider}:{profile.model}"
        source = {
            "id": 7, "conversation_id": "conversation", "role": "assistant",
            "content": "A selected response", "created_at": "now", "actions": [],
        }
        with (
            patch("backend.main.get_message", return_value=source),
            patch.object(model_registry, "select_profile", return_value=profile),
            patch.object(model_registry, "routed") as routed,
        ):
            response = await self.client.post(
                "/api/conversations/conversation/messages/7/integrate",
                json={
                    "provider": "gemini", "model": "gemini-test",
                    "instruction": "Summarize for implementation", "confirmed": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "confirmation_required")
        self.assertEqual(response.json()["content_characters"], 19)
        routed.assert_not_called()

    async def test_confirmed_message_integration_uses_no_tools(self):
        profile = SimpleNamespace(
            provider="gemini", model="gemini-test", cost_tier="free_tier",
            id="gemini:gemini-test",
        )
        source = {
            "id": 7, "conversation_id": "conversation", "role": "assistant",
            "content": "A selected response", "created_at": "now", "actions": [],
        }
        client = SimpleNamespace(
            chat=AsyncMock(return_value=ChatModelResponse(content="Integrated result"))
        )
        result_message = {**source, "id": 8, "content": "Integrated result"}
        with (
            patch("backend.main.get_message", return_value=source),
            patch("backend.main.add_message", return_value=result_message),
            patch("backend.main.add_message_action") as add_action,
            patch.object(model_registry, "select_profile", return_value=profile),
            patch.object(model_registry, "routed", return_value=client),
        ):
            response = await self.client.post(
                "/api/conversations/conversation/messages/7/integrate",
                json={
                    "provider": "gemini", "model": "gemini-test",
                    "instruction": "Summarize for implementation", "confirmed": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "completed")
        self.assertEqual(client.chat.await_args.args[1], [])
        add_action.assert_called_once_with(7, "integrated", "gemini:gemini-test")

    async def test_orchestration_preview_performs_no_model_call(self):
        profile = SimpleNamespace(provider="gemini", model="gemini-test")
        with (
            patch.object(model_registry, "select_profile", return_value=profile),
            patch.object(model_registry, "routed") as routed,
        ):
            response = await self.client.post("/api/orchestration/plans", json={
                "objective": "Research repository architecture",
                "specialists": ["research", "developer"],
                "provider": "gemini",
                "model": "gemini-test",
            })

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["state"], "previewed")
        self.assertTrue(all(not step["tools_allowed"] for step in response.json()["steps"]))
        routed.assert_not_called()

    async def test_orchestration_execution_calls_specialists_without_tools(self):
        plan = orchestration_service.create_plan(
            "Research repository evidence", ["research"], "gemini", "gemini-test",
        )
        client = SimpleNamespace(
            provider_name="gemini", model="gemini-test",
            chat=AsyncMock(return_value=ChatModelResponse(content="Bounded evidence")),
        )
        with patch.object(model_registry, "routed", return_value=client):
            response = await self.client.post(
                f"/api/orchestration/plans/{plan['id']}/execute",
                json={"confirmed": True},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "completed")
        self.assertEqual(client.chat.await_args.args[1], [])
        self.assertEqual(client.chat.await_count, 2)

    async def test_orchestration_event_stream_is_redacted(self):
        marker = "private-stream-marker-456"
        plan = orchestration_service.create_plan(
            f"Research {marker}", ["research"], "gemini", "gemini-test",
        )
        client = SimpleNamespace(
            provider_name="gemini", model="gemini-test",
            chat=AsyncMock(return_value=ChatModelResponse(content="private model response")),
        )
        await orchestration_service.execute(plan["id"], client, True)
        response = await self.client.get(
            f"/api/orchestration/plans/{plan['id']}/events/stream",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"].split(";")[0], "text/event-stream")
        self.assertIn("specialist_completed", response.text)
        self.assertNotIn(marker, response.text)
        self.assertNotIn("private model response", response.text)

    async def test_queued_orchestration_can_be_cancelled_before_provider_work(self):
        plan = orchestration_service.create_plan(
            "Research cancellation handling", ["research"], "gemini", "gemini-test",
        )
        queued = orchestration_service.queue_execution(plan["id"], True)
        self.assertEqual(queued["state"], "queued")

        response = await self.client.post(
            f"/api/orchestration/plans/{plan['id']}/cancel",
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["state"], "cancelled")
        self.assertFalse(response.json()["cancellable"])
        events = orchestration_service.list_events(plan["id"])
        self.assertEqual(events[-1]["event_type"], "execution_cancelled")

    async def test_missing_resources_return_not_found(self):
        responses = [
            await self.client.patch("/api/memories/missing", json={"content": "none"}),
            await self.client.delete("/api/memories/missing"),
            await self.client.post("/api/approvals/missing", json={"approved": True}),
            await self.client.patch("/api/automations/missing", json={"enabled": True}),
            await self.client.post("/api/automations/missing/run"),
        ]

        for response in responses:
            with self.subTest(path=response.request.url.path):
                self.assertEqual(response.status_code, 404)
                self.assertIn("detail", response.json())

    async def test_conversation_delete_contract(self):
        deleted_conversation = {
            "id": "conversation-id",
            "deleted_at": "2026-08-30T00:00:00+00:00",
            "purge_after": "2026-09-29T00:00:00+00:00",
        }
        with patch("backend.main.trash_conversation", return_value=deleted_conversation):
            deleted = await self.client.delete("/api/conversations/conversation-id")
        with patch("backend.main.trash_conversation", return_value=None):
            missing = await self.client.delete("/api/conversations/missing")

        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json(), {
            "deleted": True,
            "conversation_id": "conversation-id",
            "purge_after": "2026-09-29T00:00:00+00:00",
        })
        self.assertEqual(missing.status_code, 404)

    async def test_conversation_update_contract(self):
        conversation = {
            "id": "conversation-id",
            "title": "Renamed",
            "created_at": "2026-08-30T00:00:00+00:00",
            "updated_at": "2026-08-30T00:00:00+00:00",
            "pinned": True,
            "archived_at": None,
            "deleted_at": None,
            "purge_after": None,
        }
        with (
            patch("backend.main.get_conversation", return_value=conversation),
            patch("backend.main.update_conversation", return_value=conversation),
        ):
            updated = await self.client.patch(
                "/api/conversations/conversation-id",
                json={"title": "Renamed", "pinned": True},
            )

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["conversation"]["title"], "Renamed")
        self.assertTrue(updated.json()["conversation"]["pinned"])

    async def test_conversation_restore_and_purge_contracts(self):
        deleted = {
            "id": "conversation-id",
            "deleted_at": "2026-08-30T00:00:00+00:00",
        }
        restored = {**deleted, "deleted_at": None, "purge_after": None}
        with patch("backend.main.restore_conversation", return_value=restored):
            restore_response = await self.client.post(
                "/api/conversations/conversation-id/restore"
            )
        with (
            patch("backend.main.get_conversation", return_value=deleted),
            patch("backend.main.delete_conversation", return_value=True),
        ):
            purge_response = await self.client.delete(
                "/api/conversations/conversation-id/purge"
            )

        self.assertEqual(restore_response.status_code, 200)
        self.assertIsNone(restore_response.json()["conversation"]["deleted_at"])
        self.assertEqual(purge_response.status_code, 200)
        self.assertTrue(purge_response.json()["purged"])


if __name__ == "__main__":
    unittest.main()
