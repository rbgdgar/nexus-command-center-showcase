import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.app.database import (
    DatabaseConnection,
    backup_sqlite_database,
    database_connection,
)


class _FakeConnection:
    def __init__(self):
        self.calls = []

    def execute(self, statement, parameters=()):
        self.calls.append((statement, parameters))
        return self


class DatabaseCompatibilityTests(unittest.TestCase):
    def test_explicit_path_uses_sqlite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "portable.db"
            with database_connection(path) as connection:
                self.assertEqual(connection.dialect, "sqlite")
                connection.execute("CREATE TABLE items (id TEXT PRIMARY KEY)")
                connection.execute("INSERT INTO items (id) VALUES (?)", ("one",))
            raw = sqlite3.connect(path)
            try:
                self.assertEqual(raw.execute("SELECT id FROM items").fetchone()[0], "one")
            finally:
                raw.close()

    def test_postgres_sql_translation(self):
        raw = _FakeConnection()
        connection = DatabaseConnection(raw, "postgresql")
        connection.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)"
        )
        connection.execute("SELECT * FROM items WHERE name = ?", ("NEXUS",))
        self.assertIn("BIGSERIAL PRIMARY KEY", raw.calls[0][0])
        self.assertIn("name = %s", raw.calls[1][0])

    def test_sqlite_backup_is_create_only_and_recoverable(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.db"
            backup = Path(directory) / "recovery" / "backup.db"
            connection = sqlite3.connect(source)
            try:
                connection.execute("CREATE TABLE evidence (value TEXT NOT NULL)")
                connection.execute("INSERT INTO evidence VALUES ('recovered')")
                connection.commit()
            finally:
                connection.close()
            result = backup_sqlite_database(source, backup)
            self.assertEqual(result["status"], "verified")
            connection = sqlite3.connect(backup)
            try:
                self.assertEqual(
                    connection.execute("SELECT value FROM evidence").fetchone()[0],
                    "recovered",
                )
            finally:
                connection.close()
            with self.assertRaises(FileExistsError):
                backup_sqlite_database(source, backup)
