import asyncio
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.agents.orchestration import OrchestrationService
from backend.app.models.provider import ChatModelResponse


class FakeModel:
    provider_name = "fake"
    model = "bounded-test"

    def __init__(self):
        self.calls = []

    async def chat(self, messages, tools):
        self.calls.append((messages, tools))
        return ChatModelResponse(content=f"Evidence from {messages[0]['content'][-40:]}")


class BlockingModel(FakeModel):
    def __init__(self):
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def chat(self, messages, tools):
        self.calls.append((messages, tools))
        self.started.set()
        await self.release.wait()
        return ChatModelResponse(content="Bounded background result")


class OrchestrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = OrchestrationService(Path(self.temp_dir.name) / "plans.db")
        self.service.initialize()

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    def create(self, objective="Research and review repository tests", specialists=None):
        return self.service.create_plan(
            objective, specialists or ["research", "developer"], "fake", "bounded-test",
        )

    async def test_plan_is_typed_bounded_and_uses_registered_specialists(self):
        plan = self.create()
        self.assertEqual(plan["state"], "previewed")
        self.assertEqual(plan["risk_level"], "READ_ONLY")
        self.assertEqual([step["specialist"] for step in plan["steps"]], ["research", "developer"])
        self.assertTrue(all(not step["tools_allowed"] for step in plan["steps"]))
        self.assertEqual(plan["limits"]["max_steps"], 4)
        self.assertFalse(plan["limits"]["recursive_delegation"])
        with self.assertRaises(ValueError):
            self.create(specialists=["research", "unknown"])
        with self.assertRaises(ValueError):
            self.create(specialists=["research"] * 2)

    async def test_destructive_objective_is_blocked(self):
        plan = self.create("Destroy the production database", ["devops"])
        self.assertEqual(plan["risk_level"], "DESTRUCTIVE")
        self.assertEqual(plan["state"], "blocked")
        with self.assertRaisesRegex(ValueError, "Destructive"):
            await self.service.execute(plan["id"], FakeModel(), True)

    async def test_safe_write_objective_waits_for_authorization(self):
        plan = self.create("Deploy the reviewed release", ["devops"])
        self.assertEqual(plan["risk_level"], "SAFE_WRITE")
        pending = self.service.mark_approval_pending(plan["id"], "approval-1")
        self.assertEqual(pending["state"], "approval_pending")
        with self.assertRaisesRegex(ValueError, "approval_pending"):
            await self.service.execute(plan["id"], FakeModel(), True)
        self.assertEqual(self.service.authorize(plan["id"])["state"], "authorized")

    async def test_execution_requires_confirmation_and_never_exposes_tools(self):
        plan = self.create()
        model = FakeModel()
        with self.assertRaisesRegex(ValueError, "confirmation"):
            await self.service.execute(plan["id"], model, False)
        result = await self.service.execute(plan["id"], model, True)
        self.assertEqual(result["state"], "completed")
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(len(model.calls), 3)
        self.assertTrue(all(tools == [] for _, tools in model.calls))
        self.assertIn("no tools or recursive agents", result["summary"])

    async def test_plan_executes_only_once(self):
        plan = self.create(specialists=["research"])
        await self.service.execute(plan["id"], FakeModel(), True)
        with self.assertRaisesRegex(ValueError, "cannot execute"):
            await self.service.execute(plan["id"], FakeModel(), True)

    async def test_durable_events_are_metadata_only(self):
        objective = "Research private-marker-123 architecture evidence"
        plan = self.create(objective, ["research"])
        await self.service.execute(plan["id"], FakeModel(), True)
        events = self.service.list_events(plan["id"])
        event_types = {event["event_type"] for event in events}
        self.assertIn("specialist_started", event_types)
        self.assertIn("synthesis_completed", event_types)
        self.assertIn("execution_completed", event_types)
        serialized = json.dumps(events)
        self.assertNotIn("private-marker-123", serialized)
        self.assertNotIn("Evidence from", serialized)
        self.assertNotIn("objective", serialized)

    async def test_background_start_reports_queued_and_running_states(self):
        plan = self.create(specialists=["research"])
        model = BlockingModel()
        queued = self.service.start_execution(plan["id"], model, True)
        task = self.service._tasks[plan["id"]]
        self.assertEqual(queued["state"], "queued")
        await model.started.wait()
        self.assertEqual(self.service.get_plan(plan["id"])["state"], "running")
        model.release.set()
        await task
        self.assertEqual(self.service.get_plan(plan["id"])["state"], "completed")
        self.assertTrue(all(tools == [] for _, tools in model.calls))

    async def test_running_plan_can_be_cancelled_without_more_provider_calls(self):
        plan = self.create(specialists=["research"])
        model = BlockingModel()
        self.service.start_execution(plan["id"], model, True)
        task = self.service._tasks[plan["id"]]
        await model.started.wait()

        requested = self.service.request_cancellation(plan["id"])
        self.assertEqual(requested["state"], "cancellation_requested")
        await task

        cancelled = self.service.get_plan(plan["id"])
        self.assertEqual(cancelled["state"], "cancelled")
        self.assertFalse(cancelled["cancellable"])
        self.assertEqual(len(model.calls), 1)
        event_types = [item["event_type"] for item in self.service.list_events(plan["id"])]
        self.assertIn("cancellation_requested", event_types)
        self.assertIn("execution_cancelled", event_types)

    async def test_stale_running_plan_is_recovered_as_timed_out(self):
        plan = self.create(specialists=["research"])
        stale = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
        with self.service._connection() as connection:
            connection.execute(
                """UPDATE orchestration_plans
                SET state = 'running', queued_at = ?, started_at = ? WHERE id = ?""",
                (stale, stale, plan["id"]),
            )

        self.assertEqual(self.service.recover_stale_executions(), 1)
        recovered = self.service.get_plan(plan["id"])
        self.assertEqual(recovered["state"], "timed_out")
        self.assertIn("recovery window", recovered["summary"])
        self.assertIn(
            "execution_recovered",
            [item["event_type"] for item in self.service.list_events(plan["id"])],
        )

    async def test_initialize_migrates_v216_plan_table(self):
        legacy_path = Path(self.temp_dir.name) / "legacy.db"
        connection = sqlite3.connect(legacy_path)
        try:
            connection.execute(
                """CREATE TABLE orchestration_plans (
                    id TEXT PRIMARY KEY, objective TEXT NOT NULL,
                    risk_level TEXT NOT NULL, state TEXT NOT NULL,
                    provider TEXT NOT NULL, model TEXT NOT NULL,
                    steps TEXT NOT NULL, limits TEXT NOT NULL,
                    approval_id TEXT, results TEXT, summary TEXT,
                    created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                    started_at TEXT, completed_at TEXT
                )"""
            )
            connection.commit()
        finally:
            connection.close()

        legacy_service = OrchestrationService(legacy_path)
        legacy_service.initialize()
        connection = sqlite3.connect(legacy_path)
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(orchestration_plans)")}
        finally:
            connection.close()
        self.assertIn("queued_at", columns)


if __name__ == "__main__":
    unittest.main()
