from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from backend.app.database import database_connection
from backend.app.core.logging import log_event


class RiskLevel(str, Enum):
    READ_ONLY = "READ_ONLY"
    SAFE_WRITE = "SAFE_WRITE"
    PRIVILEGED = "PRIVILEGED"
    DESTRUCTIVE = "DESTRUCTIVE"


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    category: str
    risk_level: RiskLevel
    writes: bool
    approval_required: bool
    function: Callable[..., Any]


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition):
        if definition.risk_level == RiskLevel.READ_ONLY and definition.writes:
            raise ValueError("Read-only tools cannot be marked as writes")
        if definition.risk_level in {RiskLevel.SAFE_WRITE, RiskLevel.PRIVILEGED} and not definition.approval_required:
            raise ValueError("Write and privileged tools require approval")
        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list(self) -> list[dict]:
        return [
            {
                "name": item.name,
                "category": item.category,
                "risk_level": item.risk_level.value,
                "read_write": "write" if item.writes else "read",
                "approval_required": item.approval_required,
            }
            for item in self._tools.values()
        ]


class ApprovalManager:
    def __init__(
        self,
        registry: ToolRegistry,
        database_path: str | Path | None = None,
        database_url: str | None = None,
    ):
        self.registry = registry
        self.database_path = Path(database_path) if database_path else None
        self.database_url = database_url

    def _connection(self):
        return database_connection(self.database_path, self.database_url)

    def initialize(self):
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY, proposed_action TEXT NOT NULL,
                    tool TEXT NOT NULL, arguments TEXT NOT NULL, target TEXT,
                    risk_level TEXT NOT NULL, state TEXT NOT NULL,
                    created_at TEXT NOT NULL, resolved_at TEXT, result TEXT
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, tool TEXT NOT NULL,
                    arguments TEXT NOT NULL, approval_state TEXT NOT NULL,
                    timestamp TEXT NOT NULL, result TEXT
                );
                """
            )

    @staticmethod
    def _safe_json(value: Any) -> str:
        return json.dumps(value, default=str)[:10000]

    def execute_or_request(self, tool_name: str, arguments: dict) -> dict:
        definition = self.registry.get(tool_name)
        if not definition:
            return {"error": f"Tool '{tool_name}' is not registered"}
        if definition.risk_level == RiskLevel.DESTRUCTIVE:
            log_event("approval_blocked", tool=tool_name, risk_level=definition.risk_level.value)
            self._audit(tool_name, arguments, "blocked", "Destructive tools are disabled")
            return {"state": "blocked", "reason": "Destructive tools are disabled by policy"}
        if definition.approval_required:
            return self.request(tool_name, arguments)
        try:
            result = definition.function(**arguments)
            self._audit(tool_name, arguments, "not_required", result)
            return {"state": "executed", "result": result}
        except Exception as error:
            self._audit(tool_name, arguments, "not_required", {"error": str(error)})
            raise

    def request(self, tool_name: str, arguments: dict) -> dict:
        definition = self.registry.get(tool_name)
        if not definition:
            raise ValueError("Unknown tool")
        approval_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        target = next((str(arguments[key]) for key in ("path", "memory_id", "key") if key in arguments), None)
        proposed = f"Run {tool_name} on {target or 'the requested resource'}"
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO approvals
                (id, proposed_action, tool, arguments, target, risk_level, state, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (approval_id, proposed, tool_name, self._safe_json(arguments), target, definition.risk_level.value, now),
            )
        self._audit(tool_name, arguments, "pending", {"approval_id": approval_id})
        log_event("approval_requested", tool=tool_name, approval_id=approval_id, risk_level=definition.risk_level.value)
        return {
            "state": "approval_required", "approval_id": approval_id,
            "proposed_action": proposed, "tool": tool_name, "arguments": arguments,
            "target": target, "risk_level": definition.risk_level.value,
        }

    def resolve(self, approval_id: str, approved: bool) -> dict | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if not row or row["state"] != "pending":
            return None
        arguments = json.loads(row["arguments"])
        state = "approved" if approved else "denied"
        result: Any = {"message": "Approval denied"}
        if approved:
            definition = self.registry.get(row["tool"])
            if not definition or definition.risk_level == RiskLevel.DESTRUCTIVE:
                state = "blocked"
                result = {"error": "Tool is unavailable or blocked"}
            else:
                try:
                    result = definition.function(**arguments)
                    state = "executed"
                except Exception as error:
                    state = "failed"
                    result = {"error": str(error)}
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute(
                "UPDATE approvals SET state = ?, resolved_at = ?, result = ? WHERE id = ?",
                (state, now, self._safe_json(result), approval_id),
            )
        self._audit(row["tool"], arguments, state, result)
        log_event("approval_resolved", tool=row["tool"], approval_id=approval_id, state=state)
        return {"id": approval_id, "state": state, "result": result}

    def list_approvals(self, state: str | None = None) -> list[dict]:
        with self._connection() as connection:
            if state:
                rows = connection.execute(
                    "SELECT * FROM approvals WHERE state = ? ORDER BY created_at DESC", (state,)
                ).fetchall()
            else:
                rows = connection.execute("SELECT * FROM approvals ORDER BY created_at DESC LIMIT 100").fetchall()
        return [self._decode(row) for row in rows]

    def list_audit(self, limit: int = 100) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (max(1, min(limit, 500)),)
            ).fetchall()
        return [self._decode(row) for row in rows]

    def _audit(self, tool: str, arguments: dict, state: str, result: Any):
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO audit_log (tool, arguments, approval_state, timestamp, result)
                VALUES (?, ?, ?, ?, ?)""",
                (tool, self._safe_json(arguments), state, datetime.now(timezone.utc).isoformat(), self._safe_json(result)),
            )

    @staticmethod
    def _decode(row) -> dict:
        item = dict(row)
        for field in ("arguments", "result"):
            if item.get(field):
                try:
                    item[field] = json.loads(item[field])
                except json.JSONDecodeError:
                    pass
        return item
