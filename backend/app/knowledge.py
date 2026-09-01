from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

import httpx

from backend.app.memory.store import PROJECT_ROOT
from backend.app.database import database_connection


SUPPORTED_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".yaml", ".yml",
    ".md", ".txt", ".toml",
}
EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "node_modules", "dist", "build", "coverage",
    "__pycache__", ".pytest_cache", ".vite", "data", "logs",
}
EXCLUDED_NAMES = {".env", ".env.local", ".env.production", ".env.development"}


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class OllamaEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model: str = "nomic-embed-text", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url.rstrip("/")

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = httpx.post(
            f"{self.base_url}/api/embed",
            json={"model": self.model, "input": texts},
            timeout=120,
        )
        response.raise_for_status()
        return response.json()["embeddings"]


class ProjectKnowledgeStore:
    def __init__(
        self,
        database_path: str | Path | None = None,
        approved_root: str | Path = PROJECT_ROOT,
        database_url: str | None = None,
    ):
        self.database_path = Path(database_path) if database_path else None
        self.database_url = database_url
        self.approved_root = Path(approved_root).resolve()

    def _connection(self):
        return database_connection(self.database_path, self.database_url)

    def initialize(self):
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, root_path TEXT NOT NULL,
                    status TEXT NOT NULL, indexed_file_count INTEGER NOT NULL DEFAULT 0,
                    last_indexed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS project_files (
                    project_id TEXT NOT NULL, relative_path TEXT NOT NULL,
                    content_hash TEXT NOT NULL, modified_at REAL NOT NULL,
                    PRIMARY KEY(project_id, relative_path)
                );
                CREATE TABLE IF NOT EXISTS project_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL,
                    relative_path TEXT NOT NULL, chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL, metadata TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_project_chunks_project
                ON project_chunks(project_id);
                CREATE TABLE IF NOT EXISTS project_notes (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                    source_id TEXT NOT NULL, content TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(project_id, source_id)
                );
                """
            )

    @staticmethod
    def _project_id(root: Path) -> str:
        return hashlib.sha256(str(root).lower().encode()).hexdigest()[:16]

    @staticmethod
    def _is_allowed(root: Path, path: Path) -> bool:
        relative = path.relative_to(root)
        if any(part in EXCLUDED_DIRS for part in relative.parts[:-1]):
            return False
        name = path.name.lower()
        if name in EXCLUDED_NAMES or name.startswith(".env."):
            return False
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            return False
        return path.stat().st_size <= 2_000_000

    @staticmethod
    def _chunks(text: str, size: int = 1800, overlap: int = 200):
        start = 0
        while start < len(text):
            end = min(len(text), start + size)
            yield text[start:end]
            if end == len(text):
                break
            start = end - overlap

    def index(self, root_path: str | Path = PROJECT_ROOT) -> dict:
        root = Path(root_path).resolve()
        if root != self.approved_root:
            raise ValueError("Only the current NEXUS repository is approved for indexing")
        project_id = self._project_id(root)
        now = datetime.now(timezone.utc).isoformat()
        files = []
        for path in root.rglob("*"):
            if path.is_file() and self._is_allowed(root, path):
                try:
                    raw = path.read_bytes()
                    if b"\x00" in raw:
                        continue
                    text = raw.decode("utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                files.append((path, text, hashlib.sha256(raw).hexdigest()))

        with self._connection() as connection:
            existing = {
                row["relative_path"]: row["content_hash"]
                for row in connection.execute(
                    "SELECT relative_path, content_hash FROM project_files WHERE project_id = ?",
                    (project_id,),
                )
            }
            seen = set()
            changed = 0
            for path, text, digest in files:
                relative = path.relative_to(root).as_posix()
                seen.add(relative)
                if existing.get(relative) == digest:
                    continue
                changed += 1
                connection.execute(
                    "DELETE FROM project_chunks WHERE project_id = ? AND relative_path = ?",
                    (project_id, relative),
                )
                connection.execute(
                    """INSERT INTO project_files
                    (project_id, relative_path, content_hash, modified_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(project_id, relative_path) DO UPDATE SET
                        content_hash = excluded.content_hash,
                        modified_at = excluded.modified_at""",
                    (project_id, relative, digest, path.stat().st_mtime),
                )
                for index, chunk in enumerate(self._chunks(text)):
                    metadata = json.dumps({"path": relative, "suffix": path.suffix.lower(), "chunk": index})
                    connection.execute(
                        """INSERT INTO project_chunks
                        (project_id, relative_path, chunk_index, content, metadata)
                        VALUES (?, ?, ?, ?, ?)""",
                        (project_id, relative, index, chunk, metadata),
                    )
            stale = set(existing) - seen
            for relative in stale:
                connection.execute(
                    "DELETE FROM project_files WHERE project_id = ? AND relative_path = ?",
                    (project_id, relative),
                )
                connection.execute(
                    "DELETE FROM project_chunks WHERE project_id = ? AND relative_path = ?",
                    (project_id, relative),
                )
            connection.execute(
                """INSERT INTO projects
                (id, name, root_path, status, indexed_file_count, last_indexed_at)
                VALUES (?, ?, ?, 'ready', ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    root_path = excluded.root_path,
                    status = excluded.status,
                    indexed_file_count = excluded.indexed_file_count,
                    last_indexed_at = excluded.last_indexed_at""",
                (project_id, root.name, str(root), len(files), now),
            )
        return {**self.status(), "changed_file_count": changed, "stale_file_count": len(stale)}

    def search(self, query: str, limit: int = 5) -> list[dict]:
        terms = {term.lower() for term in re.findall(r"[A-Za-z0-9_.-]{2,}", query)}
        if not terms:
            return []
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT relative_path, chunk_index, content, metadata FROM project_chunks"
            ).fetchall()
            note_rows = connection.execute(
                "SELECT id, project_id, source_id, content, updated_at FROM project_notes"
            ).fetchall()
        ranked = []
        for row in rows:
            text = row["content"].lower()
            path = row["relative_path"].lower()
            score = sum(text.count(term) + (5 if term in path else 0) for term in terms)
            if score:
                item = dict(row)
                item["metadata"] = json.loads(item["metadata"])
                ranked.append((score, item))
        for row in note_rows:
            text = row["content"].lower()
            source = row["source_id"].lower()
            score = sum(text.count(term) + (5 if term in source else 0) for term in terms)
            if score:
                ranked.append((score, {
                    "relative_path": f"project-note:{row['id']}",
                    "chunk_index": 0,
                    "content": row["content"],
                    "metadata": {
                        "kind": "project_note",
                        "project_id": row["project_id"],
                        "source_id": row["source_id"],
                        "updated_at": row["updated_at"],
                    },
                }))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in ranked[: max(1, min(limit, 20))]]

    def add_note(self, project_id: str, source_id: str, content: str) -> dict:
        if project_id != self._project_id(self.approved_root):
            raise ValueError("Only the approved NEXUS project can receive chat notes")
        source_id = source_id.strip()
        content = content.strip()
        if not 1 <= len(source_id) <= 200:
            raise ValueError("Project note source must contain 1 to 200 characters")
        if not 1 <= len(content) <= 20_000:
            raise ValueError("Project note must contain 1 to 20,000 characters")
        now = datetime.now(timezone.utc).isoformat()
        note_id = str(uuid.uuid4())
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO project_notes
                   (id, project_id, source_id, content, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(project_id, source_id) DO UPDATE SET
                       content = excluded.content, updated_at = excluded.updated_at""",
                (note_id, project_id, source_id, content, now, now),
            )
            row = connection.execute(
                "SELECT * FROM project_notes WHERE project_id = ? AND source_id = ?",
                (project_id, source_id),
            ).fetchone()
        return dict(row)

    def status(self) -> dict:
        project_id = self._project_id(self.approved_root)
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return dict(row) if row else {
            "id": project_id, "name": self.approved_root.name, "root_path": str(self.approved_root),
            "status": "not_indexed", "indexed_file_count": 0, "last_indexed_at": None,
        }


project_knowledge = ProjectKnowledgeStore()


def initialize_project_knowledge():
    project_knowledge.initialize()


def index_project() -> dict:
    """Index or refresh the approved current NEXUS repository."""
    return project_knowledge.index()


def search_project_knowledge(query: str, limit: int = 5) -> list[dict]:
    """Search indexed NEXUS source code and project documentation."""
    return project_knowledge.search(query, limit)


def add_project_note(project_id: str, source_id: str, content: str) -> dict:
    """Add or refresh a user-confirmed chat note in the approved project index."""
    return project_knowledge.add_note(project_id, source_id, content)


def get_index_status() -> dict:
    """Return the current NEXUS project index status."""
    return project_knowledge.status()
