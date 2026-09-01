"""One-time, non-destructive NEXUS SQLite to PostgreSQL migration."""

import argparse
import os
import sqlite3
import sys
from pathlib import Path

import psycopg
from psycopg import sql


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


TABLES = (
    "conversations",
    "messages",
    "memories",
    "projects",
    "project_files",
    "project_chunks",
    "approvals",
    "audit_log",
    "automation_jobs",
    "automation_history",
    "media_jobs",
    "runner_nodes",
    "runner_jobs",
)
GENERATED_IDS = {"messages", "project_chunks", "audit_log", "automation_history"}


def initialize_target(database_url: str):
    os.environ["NEXUS_DATABASE_URL"] = database_url
    from backend.app.core.config import get_settings

    get_settings.cache_clear()
    from backend.app.automation.scheduler import TaskScheduler
    from backend.app.knowledge import initialize_project_knowledge
    from backend.app.memory.long_term import initialize_memory
    from backend.app.memory.store import initialize_database
    from backend.app.security.runtime import approval_manager
    from backend.app.media.service import MediaService
    from backend.app.runner.service import RunnerService

    initialize_database()
    initialize_memory()
    initialize_project_knowledge()
    approval_manager.initialize()
    TaskScheduler(lambda _tool, _arguments: {}).initialize()
    MediaService(get_settings()).initialize()
    RunnerService(get_settings()).initialize()


def migrate(source_path: Path, database_url: str) -> dict[str, int]:
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {source_path}")

    initialize_target(database_url)
    source = sqlite3.connect(source_path)
    source.row_factory = sqlite3.Row
    counts: dict[str, int] = {}
    try:
        with psycopg.connect(database_url) as target:
            populated = []
            for table in TABLES:
                count = target.execute(
                    sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table))
                ).fetchone()[0]
                if count:
                    populated.append(f"{table}={count}")
            if populated:
                raise RuntimeError(
                    "Target is not empty; migration stopped to prevent duplicates: "
                    + ", ".join(populated)
                )

            for table in TABLES:
                exists = source.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                    (table,),
                ).fetchone()
                if not exists:
                    counts[table] = 0
                    continue
                rows = source.execute(f'SELECT * FROM "{table}"').fetchall()
                if not rows:
                    counts[table] = 0
                    continue
                columns = list(rows[0].keys())
                if table in GENERATED_IDS:
                    columns.remove("id")
                statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    sql.Identifier(table),
                    sql.SQL(", ").join(map(sql.Identifier, columns)),
                    sql.SQL(", ").join(sql.Placeholder() for _ in columns),
                )
                with target.cursor() as cursor:
                    cursor.executemany(
                        statement,
                        [tuple(row[column] for column in columns) for row in rows],
                    )
                counts[table] = len(rows)
    finally:
        source.close()
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("data/nexus.db"))
    parser.add_argument("--database-url", required=True)
    arguments = parser.parse_args()
    counts = migrate(arguments.source, arguments.database_url)
    print("Migration complete:", ", ".join(f"{key}={value}" for key, value in counts.items()))


if __name__ == "__main__":
    main()
