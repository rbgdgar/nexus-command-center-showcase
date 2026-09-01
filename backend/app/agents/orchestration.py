"""Bounded multi-agent plans governed by the NEXUS safety model."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.app.agents.specialists import get_specialist
from backend.app.core.logging import log_event
from backend.app.database import database_connection


MAX_OBJECTIVE_CHARACTERS = 4000
MAX_PLAN_STEPS = 4
MAX_PROVIDER_CALLS = MAX_PLAN_STEPS + 1
PLAN_TTL_MINUTES = 30
EXECUTION_TIMEOUT_SECONDS = 90
STALE_EXECUTION_GRACE_SECONDS = 30
ACTIVE_STATES = {"queued", "running", "cancellation_requested"}
TERMINAL_STATES = {
    "blocked", "completed", "completed_with_errors", "timed_out",
    "failed", "cancelled", "expired",
}

DESTRUCTIVE_TERMS = (
    "destroy", "wipe", "erase", "drop database", "format disk",
    "terraform destroy", "delete everything", "remove all",
)
SAFE_WRITE_TERMS = (
    "send email", "email ", "message contact", "launch ", "screenshot",
    "volume ", "write ", "modify ", "create file", "deploy ",
    "terraform apply", "publish ",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _decode_json(value: Any, fallback: Any) -> Any:
    if not value:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


class OrchestrationService:
    def __init__(
        self,
        database_path: str | Path | None = None,
        database_url: str | None = None,
    ) -> None:
        self.database_path = Path(database_path) if database_path else None
        self.database_url = database_url
        self._tasks: dict[str, asyncio.Task] = {}

    def _connection(self):
        return database_connection(self.database_path, self.database_url)

    def initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS orchestration_plans (
                    id TEXT PRIMARY KEY, objective TEXT NOT NULL,
                    risk_level TEXT NOT NULL, state TEXT NOT NULL,
                    provider TEXT NOT NULL, model TEXT NOT NULL,
                    steps TEXT NOT NULL, limits TEXT NOT NULL,
                    approval_id TEXT, results TEXT, summary TEXT,
                    created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                    queued_at TEXT, started_at TEXT, completed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS orchestration_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id TEXT NOT NULL, event_type TEXT NOT NULL,
                    state TEXT NOT NULL, specialist TEXT,
                    detail TEXT NOT NULL, timestamp TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS orchestration_events_plan_id
                    ON orchestration_events (plan_id, id);
                """
            )
            if connection.dialect == "sqlite":
                columns = {
                    row["name"] for row in connection.execute(
                        "PRAGMA table_info(orchestration_plans)"
                    ).fetchall()
                }
                if "queued_at" not in columns:
                    connection.execute(
                        "ALTER TABLE orchestration_plans ADD COLUMN queued_at TEXT"
                    )
            else:
                connection.execute(
                    "ALTER TABLE orchestration_plans ADD COLUMN IF NOT EXISTS queued_at TEXT"
                )
        self.recover_stale_executions()

    @staticmethod
    def classify_risk(objective: str) -> str:
        lowered = objective.lower()
        if any(term in lowered for term in DESTRUCTIVE_TERMS):
            return "DESTRUCTIVE"
        if any(term in lowered for term in SAFE_WRITE_TERMS):
            return "SAFE_WRITE"
        return "READ_ONLY"

    @staticmethod
    def suggest_specialists(objective: str) -> list[str]:
        lowered = objective.lower()
        selected: list[str] = []
        signals = (
            ("kubernetes", ("kubernetes", "k8s", "cluster", "pod ", "helm")),
            ("cloud", ("aws", "azure", "gcp", "cloud", "cost")),
            ("devops", ("deploy", "docker", "terraform", "pipeline", "ci", "release")),
            ("developer", ("code", "repository", "bug", "test", "build", "implement")),
            ("research", ("research", "compare", "investigate", "evidence", "latest", "news")),
        )
        for slug, keywords in signals:
            if any(keyword in lowered for keyword in keywords):
                selected.append(slug)
        return (selected or ["research", "developer"])[:MAX_PLAN_STEPS]

    def create_plan(
        self,
        objective: str,
        specialist_slugs: list[str],
        provider: str,
        model: str,
    ) -> dict[str, Any]:
        objective = objective.strip()
        if not 1 <= len(objective) <= MAX_OBJECTIVE_CHARACTERS:
            raise ValueError(f"Objective must be 1-{MAX_OBJECTIVE_CHARACTERS} characters")

        slugs = specialist_slugs or self.suggest_specialists(objective)
        if len(slugs) > MAX_PLAN_STEPS:
            raise ValueError(f"A plan may contain at most {MAX_PLAN_STEPS} specialists")
        if len(set(slugs)) != len(slugs):
            raise ValueError("Specialists must be unique within a plan")

        steps = []
        for position, slug in enumerate(slugs, start=1):
            specialist = get_specialist(slug)
            if not specialist:
                raise ValueError(f"Unknown specialist: {slug}")
            steps.append({
                "position": position,
                "specialist": specialist.slug,
                "name": specialist.name,
                "instruction": specialist.instruction,
                "risk_level": "READ_ONLY",
                "tools_allowed": False,
            })

        risk_level = self.classify_risk(objective)
        state = "blocked" if risk_level == "DESTRUCTIVE" else "previewed"
        created_at = _now()
        plan_id = str(uuid.uuid4())
        limits = {
            "max_steps": MAX_PLAN_STEPS,
            "max_provider_calls": MAX_PROVIDER_CALLS,
            "timeout_seconds": EXECUTION_TIMEOUT_SECONDS,
            "recursive_delegation": False,
            "tools_allowed": False,
        }
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO orchestration_plans
                (id, objective, risk_level, state, provider, model, steps, limits,
                 created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    plan_id, objective, risk_level, state, provider, model,
                    json.dumps(steps), json.dumps(limits), created_at.isoformat(),
                    (created_at + timedelta(minutes=PLAN_TTL_MINUTES)).isoformat(),
                ),
            )
        log_event(
            "orchestration_plan_created", plan_id=plan_id,
            risk_level=risk_level, step_count=len(steps),
        )
        self._event(
            plan_id, "plan_blocked" if state == "blocked" else "plan_previewed",
            state, None,
            "Destructive objective blocked" if state == "blocked" else "Plan preview stored",
        )
        return self.get_plan(plan_id) or {}

    def mark_approval_pending(self, plan_id: str, approval_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            connection.execute(
                """UPDATE orchestration_plans
                SET state = 'approval_pending', approval_id = ?
                WHERE id = ? AND risk_level = 'SAFE_WRITE' AND state = 'previewed'""",
                (approval_id, plan_id),
            )
        self._event(
            plan_id, "approval_pending", "approval_pending", None,
            "Safe-write objective is waiting for approval",
        )
        return self.get_plan(plan_id) or {}

    def authorize(self, plan_id: str) -> dict[str, Any]:
        plan = self.get_plan(plan_id)
        if not plan:
            raise ValueError("Orchestration plan not found")
        if plan["risk_level"] != "SAFE_WRITE" or plan["state"] != "approval_pending":
            raise ValueError("Plan is not waiting for safe-write approval")
        if self._expired(plan):
            self._set_state(plan_id, "expired")
            raise ValueError("Orchestration plan expired")
        self._set_state(plan_id, "authorized")
        self._event(
            plan_id, "plan_authorized", "authorized", None,
            "Safe-write objective authorized for read-only specialist analysis",
        )
        log_event("orchestration_plan_authorized", plan_id=plan_id)
        return {"plan_id": plan_id, "state": "authorized"}

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM orchestration_plans WHERE id = ?", (plan_id,)
            ).fetchone()
        return self._decode(row) if row else None

    def list_plans(self, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM orchestration_plans ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def list_events(
        self, plan_id: str, after_id: int = 0, limit: int = 100,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT id, plan_id, event_type, state, specialist, detail, timestamp
                FROM orchestration_events WHERE plan_id = ? AND id > ?
                ORDER BY id ASC LIMIT ?""",
                (plan_id, max(0, after_id), limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def queue_execution(self, plan_id: str, confirmed: bool) -> dict[str, Any]:
        if not confirmed:
            raise ValueError("Explicit plan confirmation is required before execution")
        plan = self.get_plan(plan_id)
        if not plan:
            raise ValueError("Orchestration plan not found")
        if self._expired(plan):
            self._set_state(plan_id, "expired")
            self._event(plan_id, "plan_expired", "expired", None, "Plan expired before execution")
            raise ValueError("Orchestration plan expired")
        if plan["risk_level"] == "DESTRUCTIVE":
            raise ValueError("Destructive orchestration plans are blocked")
        allowed_state = "authorized" if plan["risk_level"] == "SAFE_WRITE" else "previewed"
        if plan["state"] != allowed_state:
            raise ValueError(f"Plan cannot execute while state is {plan['state']}")
        with self._connection() as connection:
            cursor = connection.execute(
                """UPDATE orchestration_plans SET state = 'queued', queued_at = ?
                WHERE id = ? AND state = ?""",
                (_now().isoformat(), plan_id, allowed_state),
            )
            if cursor.rowcount != 1:
                raise ValueError("Plan is already running or has been executed")
        self._event(plan_id, "execution_queued", "queued", None, "Bounded execution queued")
        return self.get_plan(plan_id) or {}

    def start_execution(
        self, plan_id: str, model_client: Any, confirmed: bool,
    ) -> dict[str, Any]:
        plan = self.queue_execution(plan_id, confirmed)
        task = asyncio.create_task(self._execute_queued(plan_id, model_client))
        self._tasks[plan_id] = task
        task.add_done_callback(lambda finished: self._task_finished(plan_id, finished))
        return plan

    def request_cancellation(self, plan_id: str) -> dict[str, Any]:
        plan = self.get_plan(plan_id)
        if not plan:
            raise ValueError("Orchestration plan not found")
        if plan["state"] in {"cancelled", "cancellation_requested"}:
            return plan
        if plan["state"] not in {"queued", "running"}:
            raise ValueError(f"Plan cannot be cancelled while state is {plan['state']}")

        requested_at = _now().isoformat()
        if plan["state"] == "queued":
            with self._connection() as connection:
                cursor = connection.execute(
                    """UPDATE orchestration_plans
                    SET state = 'cancelled', summary = ?, completed_at = ?
                    WHERE id = ? AND state = 'queued'""",
                    ("Execution was cancelled before it started.", requested_at, plan_id),
                )
            if cursor.rowcount != 1:
                return self.request_cancellation(plan_id)
            self._event(
                plan_id, "cancellation_requested", "cancelled", None,
                "Operator cancellation accepted before execution started",
            )
            self._event(
                plan_id, "execution_cancelled", "cancelled", None,
                "Execution cancelled before provider work started",
            )
        else:
            with self._connection() as connection:
                cursor = connection.execute(
                    """UPDATE orchestration_plans SET state = 'cancellation_requested'
                    WHERE id = ? AND state = 'running'""",
                    (plan_id,),
                )
            if cursor.rowcount != 1:
                return self.request_cancellation(plan_id)
            self._event(
                plan_id, "cancellation_requested", "cancellation_requested", None,
                "Operator requested a bounded execution stop",
            )

        task = self._tasks.get(plan_id)
        if task and not task.done():
            task.cancel()
        return self.get_plan(plan_id) or {}

    def recover_stale_executions(self) -> int:
        cutoff = (
            _now() - timedelta(
                seconds=EXECUTION_TIMEOUT_SECONDS + STALE_EXECUTION_GRACE_SECONDS,
            )
        ).isoformat()
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT id, state FROM orchestration_plans
                WHERE state IN ('queued', 'running', 'cancellation_requested')
                AND COALESCE(started_at, queued_at, created_at) <= ?""",
                (cutoff,),
            ).fetchall()
        recovered = 0
        for row in rows:
            state = "cancelled" if row["state"] == "cancellation_requested" else "timed_out"
            summary = (
                "A previously requested cancellation was recovered after interruption."
                if state == "cancelled"
                else "An interrupted execution exceeded its bounded recovery window."
            )
            with self._connection() as connection:
                cursor = connection.execute(
                    """UPDATE orchestration_plans
                    SET state = ?, summary = ?, completed_at = ?
                    WHERE id = ? AND state = ?""",
                    (state, summary, _now().isoformat(), row["id"], row["state"]),
                )
            if cursor.rowcount == 1:
                recovered += 1
                self._event(
                    row["id"], "execution_recovered", state, None,
                    "Interrupted execution closed within fixed recovery policy",
                )
        return recovered

    async def shutdown(self) -> None:
        tasks = list(self._tasks.items())
        for plan_id, task in tasks:
            if not task.done():
                self.request_cancellation(plan_id)
        if tasks:
            await asyncio.gather(*(task for _, task in tasks), return_exceptions=True)

    def _task_finished(self, plan_id: str, task: asyncio.Task) -> None:
        self._tasks.pop(plan_id, None)
        if task.cancelled():
            return
        error = task.exception()
        if error:
            log_event(
                "orchestration_background_failure", plan_id=plan_id,
                error=error.__class__.__name__,
            )

    async def execute(self, plan_id: str, model_client: Any, confirmed: bool) -> dict[str, Any]:
        self.queue_execution(plan_id, confirmed)
        return await self._execute_queued(plan_id, model_client)

    async def _execute_queued(self, plan_id: str, model_client: Any) -> dict[str, Any]:
        plan = self.get_plan(plan_id)
        if not plan:
            raise ValueError("Orchestration plan not found")
        if plan["state"] == "cancelled":
            return plan
        if plan["state"] != "queued":
            raise ValueError(f"Plan cannot execute while state is {plan['state']}")

        with self._connection() as connection:
            cursor = connection.execute(
                """UPDATE orchestration_plans SET state = 'running', started_at = ?
                WHERE id = ? AND state = 'queued'""",
                (_now().isoformat(), plan_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Plan is already running or has been executed")
        self._event(plan_id, "execution_started", "running", None, "Bounded execution started")

        async def run_step(step: dict[str, Any]) -> dict[str, Any]:
            self._raise_if_cancellation_requested(plan_id)
            self._event(
                plan_id, "specialist_started", "running", step["specialist"],
                "Specialist analysis started",
            )
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a bounded NEXUS specialist. Analyze only; do not request "
                        "tools, delegate, write, send, deploy, or perform machine actions. "
                        f"Your assignment: {step['instruction']}"
                    ),
                },
                {"role": "user", "content": plan["objective"]},
            ]
            try:
                response = await model_client.chat(messages, [])
                self._raise_if_cancellation_requested(plan_id)
                self._event(
                    plan_id, "specialist_completed", "running", step["specialist"],
                    "Specialist analysis completed",
                )
                return {
                    "position": step["position"], "specialist": step["specialist"],
                    "name": step["name"], "status": "completed",
                    "response": response.content,
                }
            except Exception as error:
                self._event(
                    plan_id, "specialist_failed", "running", step["specialist"],
                    "Specialist analysis failed",
                )
                return {
                    "position": step["position"], "specialist": step["specialist"],
                    "name": step["name"], "status": "failed", "error": str(error),
                }

        async def run_plan() -> tuple[list[dict[str, Any]], str, str]:
            results = await asyncio.gather(*(run_step(step) for step in plan["steps"]))
            self._raise_if_cancellation_requested(plan_id)
            completed = sum(item["status"] == "completed" for item in results)
            state = "completed" if completed == len(results) else "completed_with_errors"
            completed_results = [item for item in results if item["status"] == "completed"]
            if not completed_results:
                return results, "completed_with_errors", (
                    "No specialist completed; no synthesis call was made. "
                    "No tools or recursive agents were used."
                )
            synthesis_payload = [
                {
                    "specialist": item["name"],
                    "response": item["response"][:6000],
                }
                for item in completed_results
            ]
            synthesis_messages = [
                {
                    "role": "system",
                    "content": (
                        "You are the bounded NEXUS orchestrator. Synthesize the supplied "
                        "specialist analyses into one concise deliverable with findings, "
                        "gaps, and recommended next steps. Do not request tools, delegate, "
                        "or claim that any write or machine action occurred."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({
                        "objective": plan["objective"],
                        "specialist_results": synthesis_payload,
                    }),
                },
            ]
            self._event(
                plan_id, "synthesis_started", "running", None,
                "Final synthesis started",
            )
            try:
                synthesis = await model_client.chat(synthesis_messages, [])
                self._raise_if_cancellation_requested(plan_id)
                self._event(
                    plan_id, "synthesis_completed", "running", None,
                    "Final synthesis completed",
                )
                summary = (
                    f"{completed} of {len(results)} bounded specialists completed; "
                    "no tools or recursive agents were used.\n\n"
                    f"{synthesis.content}"
                )
            except Exception as error:
                self._event(
                    plan_id, "synthesis_failed", "running", None,
                    "Final synthesis failed",
                )
                state = "completed_with_errors"
                summary = (
                    f"{completed} of {len(results)} bounded specialists completed, but "
                    f"final synthesis failed: {str(error)[:1000]}. No tools or recursive "
                    "agents were used."
                )
            return results, state, summary

        try:
            results, state, summary = await asyncio.wait_for(
                run_plan(), timeout=EXECUTION_TIMEOUT_SECONDS,
            )
            self._raise_if_cancellation_requested(plan_id)
        except TimeoutError:
            results = []
            state = "timed_out"
            summary = f"The plan exceeded its {EXECUTION_TIMEOUT_SECONDS}-second runtime limit."
            self._event(
                plan_id, "execution_timed_out", state, None,
                "Execution reached its fixed runtime limit",
            )
        except asyncio.CancelledError:
            self._finalize_cancelled(plan_id)
            return self.get_plan(plan_id) or {}
        except Exception:
            self._set_state(plan_id, "failed")
            self._event(plan_id, "execution_failed", "failed", None, "Execution failed")
            raise

        with self._connection() as connection:
            connection.execute(
                """UPDATE orchestration_plans
                SET state = ?, results = ?, summary = ?, completed_at = ? WHERE id = ?""",
                (state, json.dumps(results), summary, _now().isoformat(), plan_id),
            )
        log_event("orchestration_plan_completed", plan_id=plan_id, state=state)
        self._event(plan_id, "execution_completed", state, None, "Bounded execution finished")
        return self.get_plan(plan_id) or {}

    def _set_state(self, plan_id: str, state: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE orchestration_plans SET state = ? WHERE id = ?",
                (state, plan_id),
            )

    def _raise_if_cancellation_requested(self, plan_id: str) -> None:
        plan = self.get_plan(plan_id)
        if plan and plan["state"] in {"cancellation_requested", "cancelled"}:
            raise asyncio.CancelledError

    def _finalize_cancelled(self, plan_id: str) -> None:
        with self._connection() as connection:
            cursor = connection.execute(
                """UPDATE orchestration_plans
                SET state = 'cancelled', summary = ?, completed_at = ?
                WHERE id = ? AND state IN ('queued', 'running', 'cancellation_requested')""",
                ("Execution was cancelled by the operator.", _now().isoformat(), plan_id),
            )
        if cursor.rowcount == 1:
            self._event(
                plan_id, "execution_cancelled", "cancelled", None,
                "Execution stopped by operator request",
            )
            log_event("orchestration_plan_cancelled", plan_id=plan_id)

    def _event(
        self, plan_id: str, event_type: str, state: str,
        specialist: str | None, detail: str,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO orchestration_events
                (plan_id, event_type, state, specialist, detail, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    plan_id, event_type[:80], state[:40],
                    specialist[:80] if specialist else None,
                    detail[:200], _now().isoformat(),
                ),
            )

    @staticmethod
    def _expired(plan: dict[str, Any]) -> bool:
        return datetime.fromisoformat(plan["expires_at"]) <= _now()

    @staticmethod
    def _decode(row: Any) -> dict[str, Any]:
        item = dict(row)
        item["steps"] = _decode_json(item.get("steps"), [])
        item["limits"] = _decode_json(item.get("limits"), {})
        item["results"] = _decode_json(item.get("results"), [])
        item["approval_required"] = item["risk_level"] == "SAFE_WRITE"
        item["cancellable"] = item["state"] in ACTIVE_STATES
        item["execution_mode"] = "bounded-read-only-specialists"
        return item


orchestration_service = OrchestrationService()


def authorize_orchestration_plan(plan_id: str) -> dict[str, Any]:
    """Authorize a previously previewed safe-write orchestration objective."""
    return orchestration_service.authorize(plan_id)
