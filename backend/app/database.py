from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from backend.app.core.config import get_settings


class DatabaseIntegrityError(ValueError):
    """Portable constraint error raised by either supported database driver."""


class DatabaseConnection:
    def __init__(self, connection: Any, dialect: str):
        self._connection = connection
        self.dialect = dialect

    def _sql(self, statement: str) -> str:
        if self.dialect == "postgresql":
            statement = statement.replace("?", "%s")
            statement = statement.replace(
                "INTEGER PRIMARY KEY AUTOINCREMENT",
                "BIGSERIAL PRIMARY KEY",
            )
        return statement

    def execute(self, statement: str, parameters: tuple | list = ()):
        try:
            return self._connection.execute(self._sql(statement), parameters)
        except sqlite3.IntegrityError as error:
            raise DatabaseIntegrityError(str(error)) from error
        except Exception as error:
            if error.__class__.__module__.startswith("psycopg") and any(
                name in error.__class__.__name__.lower()
                for name in ("integrity", "unique", "foreignkey", "check")
            ):
                raise DatabaseIntegrityError(str(error)) from error
            raise

    def executescript(self, script: str):
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def commit(self):
        self._connection.commit()


def backup_sqlite_database(source: str | Path, destination: str | Path) -> dict:
    """Create and verify a new SQLite backup without overwriting any file."""
    source_path = Path(source).resolve()
    destination_path = Path(destination).resolve()
    if not source_path.is_file():
        raise ValueError("SQLite source database does not exist")
    if destination_path.exists():
        raise FileExistsError("Backup destination already exists")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(source_path)
    backup_connection = sqlite3.connect(destination_path)
    try:
        source_connection.backup(backup_connection)
        result = backup_connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        backup_connection.close()
        source_connection.close()
    if result != "ok":
        raise RuntimeError(f"SQLite backup integrity check failed: {result}")
    return {"status": "verified", "path": str(destination_path)}


@contextmanager
def database_connection(
    database_path: str | Path | None = None,
    database_url: str | None = None,
) -> Iterator[DatabaseConnection]:
    """Open SQLite locally or PostgreSQL when NEXUS_DATABASE_URL is set."""
    settings = get_settings()
    configured_url = database_url if database_url is not None else (
        settings.database_url if database_path is None else None
    )

    if configured_url:
        import psycopg
        from psycopg.rows import dict_row

        raw_connection = psycopg.connect(configured_url, row_factory=dict_row)
        dialect = "postgresql"
    else:
        path = Path(database_path or settings.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        raw_connection = sqlite3.connect(path)
        raw_connection.row_factory = sqlite3.Row
        raw_connection.execute("PRAGMA foreign_keys = ON")
        dialect = "sqlite"

    connection = DatabaseConnection(raw_connection, dialect)
    try:
        yield connection
        raw_connection.commit()
    except Exception:
        raw_connection.rollback()
        raise
    finally:
        raw_connection.close()
