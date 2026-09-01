from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.app.database import database_connection


MEMORY_CATEGORIES = {
    "fact",
    "preference",
    "project",
    "environment",
    "architecture",
    "note",
}


class LongTermMemoryStore:
    def __init__(
        self,
        database_path: str | Path | None = None,
        database_url: str | None = None,
    ):
        self.database_path = Path(database_path) if database_path else None
        self.database_url = database_url

    def _connection(self):
        return database_connection(self.database_path, self.database_url)

    def initialize(self):
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    key TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    importance INTEGER NOT NULL DEFAULT 5,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(category, key)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memories_category
                ON memories(category)
                """
            )

    def remember(
        self,
        category: str,
        key: str,
        content: str,
        source: str = "user",
        importance: int = 5,
    ) -> dict:
        category = category.strip().lower()
        key = key.strip()
        content = content.strip()
        if category not in MEMORY_CATEGORIES:
            raise ValueError(f"Unsupported memory category: {category}")
        if not key or not content:
            raise ValueError("Memory key and content are required")
        if not 1 <= importance <= 10:
            raise ValueError("Memory importance must be between 1 and 10")

        memory_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO memories (
                    id, category, key, content, source, importance,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(category, key) DO UPDATE SET
                    content = excluded.content,
                    source = excluded.source,
                    importance = excluded.importance,
                    updated_at = excluded.updated_at
                """,
                (
                    memory_id,
                    category,
                    key,
                    content,
                    source.strip() or "user",
                    importance,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM memories WHERE category = ? AND key = ?",
                (category, key),
            ).fetchone()
        return dict(row)

    def list(self, category: str | None = None, limit: int = 100) -> list[dict]:
        limit = max(1, min(limit, 500))
        with self._connection() as connection:
            if category:
                rows = connection.execute(
                    """
                    SELECT * FROM memories WHERE category = ?
                    ORDER BY importance DESC, updated_at DESC LIMIT ?
                    """,
                    (category.lower(), limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM memories
                    ORDER BY importance DESC, updated_at DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def search(self, query: str, limit: int = 5) -> list[dict]:
        terms = {
            term.lower()
            for term in re.findall(r"[A-Za-z0-9_.-]{2,}", query)
        }
        if not terms:
            return []

        candidates = self.list(limit=500)
        ranked = []
        for memory in candidates:
            key_text = memory["key"].lower()
            content_text = memory["content"].lower()
            category_text = memory["category"].lower()
            matches = sum(
                3 if term in key_text else 2 if term in content_text else
                1 if term in category_text else 0
                for term in terms
            )
            if matches:
                score = matches * 10 + memory["importance"]
                ranked.append((score, memory))

        ranked.sort(key=lambda item: item[0], reverse=True)
        return [memory for _, memory in ranked[: max(1, min(limit, 20))]]

    def update(self, memory_id: str, **changes) -> dict | None:
        allowed = {"category", "key", "content", "source", "importance"}
        changes = {key: value for key, value in changes.items() if key in allowed}
        if not changes:
            return self.get(memory_id)
        current = self.get(memory_id)
        if not current:
            return None
        merged = {**current, **changes}
        category = str(merged["category"]).strip().lower()
        importance = int(merged["importance"])
        if category not in MEMORY_CATEGORIES or not 1 <= importance <= 10:
            raise ValueError("Invalid memory category or importance")
        if not str(merged["key"]).strip() or not str(merged["content"]).strip():
            raise ValueError("Memory key and content are required")

        fields = list(changes)
        values = [changes[field] for field in fields]
        fields.append("updated_at")
        values.append(datetime.now(timezone.utc).isoformat())
        values.append(memory_id)
        assignments = ", ".join(f"{field} = ?" for field in fields)
        with self._connection() as connection:
            connection.execute(
                f"UPDATE memories SET {assignments} WHERE id = ?",
                values,
            )
        return self.get(memory_id)

    def get(self, memory_id: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
        return dict(row) if row else None

    def forget(self, memory_id: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM memories WHERE id = ?", (memory_id,)
            )
        return cursor.rowcount > 0


memory_store = LongTermMemoryStore()


def initialize_memory():
    memory_store.initialize()


def remember_fact(
    key: str,
    content: str,
    category: str = "fact",
    source: str = "user",
    importance: int = 5,
) -> dict:
    """Persist a user-approved fact, preference, context, decision, or note."""
    return memory_store.remember(category, key, content, source, importance)


def search_memory(query: str, limit: int = 5) -> list[dict]:
    """Return only long-term memories relevant to a query."""
    return memory_store.search(query, limit)


def list_memories(category: str | None = None, limit: int = 100) -> list[dict]:
    """List persisted memories, optionally restricted by category."""
    return memory_store.list(category, limit)


def update_memory(
    memory_id: str,
    content: str,
    importance: int = 5,
) -> dict | None:
    """Update an existing memory's content and importance."""
    return memory_store.update(
        memory_id, content=content, importance=importance
    )


def forget_memory(memory_id: str) -> bool:
    """Explicitly delete one memory by id."""
    return memory_store.forget(memory_id)
