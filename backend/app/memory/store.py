import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.database import database_connection


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIR / "nexus.db"
MESSAGE_ACTIONS = {"pinned", "project", "integrated"}
DELETED_CONVERSATION_RETENTION_DAYS = 30


def _connection():
    return database_connection()


def initialize_database():
    with _connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id)
                    REFERENCES conversations(id)
                    ON DELETE CASCADE
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS message_actions (
                message_id BIGINT NOT NULL,
                action TEXT NOT NULL,
                target TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(message_id, action, target),
                FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
            )
            """
        )

        if connection.dialect == "sqlite":
            columns = {
                row["name"] for row in connection.execute(
                    "PRAGMA table_info(conversations)"
                ).fetchall()
            }
            if "pinned" not in columns:
                connection.execute(
                    "ALTER TABLE conversations ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0"
                )
            if "archived_at" not in columns:
                connection.execute(
                    "ALTER TABLE conversations ADD COLUMN archived_at TEXT"
                )
            if "deleted_at" not in columns:
                connection.execute(
                    "ALTER TABLE conversations ADD COLUMN deleted_at TEXT"
                )
        else:
            connection.execute(
                "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS pinned INTEGER NOT NULL DEFAULT 0"
            )
            connection.execute(
                "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS archived_at TEXT"
            )
            connection.execute(
                "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS deleted_at TEXT"
            )

        connection.commit()


def create_conversation(title: str = "New Conversation") -> str:
    conversation_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    with _connection() as connection:
        connection.execute(
            """
            INSERT INTO conversations (
                id,
                title,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                conversation_id,
                title,
                now,
                now,
            ),
        )

        connection.commit()

    return conversation_id


def add_message(
    conversation_id: str,
    role: str,
    content: str,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()

    with _connection() as connection:
        row = connection.execute(
            """
            INSERT INTO messages (
                conversation_id,
                role,
                content,
                created_at
            )
            VALUES (?, ?, ?, ?)
            RETURNING id, conversation_id, role, content, created_at
            """,
            (
                conversation_id,
                role,
                content,
                now,
            ),
        ).fetchone()

        connection.execute(
            """
            UPDATE conversations
            SET updated_at = ?
            WHERE id = ?
            """,
            (
                now,
                conversation_id,
            ),
        )

        connection.commit()

    return {**dict(row), "actions": []}


def get_messages(
    conversation_id: str,
    limit: int = 20,
) -> list[dict]:
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT id, conversation_id, role, content, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                conversation_id,
                limit,
            ),
        ).fetchall()

    rows = list(reversed(rows))

    return [{**dict(row), "actions": get_message_actions(row["id"])} for row in rows]


def get_message(conversation_id: str, message_id: int) -> dict | None:
    with _connection() as connection:
        row = connection.execute(
            """SELECT id, conversation_id, role, content, created_at
               FROM messages WHERE conversation_id = ? AND id = ?""",
            (conversation_id, message_id),
        ).fetchone()
    return {**dict(row), "actions": get_message_actions(message_id)} if row else None


def delete_message(conversation_id: str, message_id: int) -> bool:
    with _connection() as connection:
        cursor = connection.execute(
            "DELETE FROM messages WHERE conversation_id = ? AND id = ?",
            (conversation_id, message_id),
        )
        if cursor.rowcount:
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), conversation_id),
            )
    return cursor.rowcount > 0


def delete_conversation(conversation_id: str) -> bool:
    with _connection() as connection:
        cursor = connection.execute(
            "DELETE FROM conversations WHERE id = ?",
            (conversation_id,),
        )
    return cursor.rowcount > 0


def trash_conversation(conversation_id: str) -> dict | None:
    now = datetime.now(timezone.utc)
    with _connection() as connection:
        cursor = connection.execute(
            """UPDATE conversations
               SET deleted_at = ?, archived_at = NULL, pinned = 0, updated_at = ?
               WHERE id = ? AND deleted_at IS NULL""",
            (now.isoformat(), now.isoformat(), conversation_id),
        )
    if not cursor.rowcount:
        return None
    return get_conversation(conversation_id)


def restore_conversation(conversation_id: str) -> dict | None:
    now = datetime.now(timezone.utc).isoformat()
    with _connection() as connection:
        cursor = connection.execute(
            """UPDATE conversations
               SET deleted_at = NULL, updated_at = ?
               WHERE id = ? AND deleted_at IS NOT NULL""",
            (now, conversation_id),
        )
    if not cursor.rowcount:
        return None
    return get_conversation(conversation_id)


def purge_expired_conversations() -> int:
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=DELETED_CONVERSATION_RETENTION_DAYS)
    ).isoformat()
    with _connection() as connection:
        cursor = connection.execute(
            "DELETE FROM conversations WHERE deleted_at IS NOT NULL AND deleted_at <= ?",
            (cutoff,),
        )
    return cursor.rowcount


def update_conversation(
    conversation_id: str,
    *,
    title: str | None = None,
    pinned: bool | None = None,
    archived: bool | None = None,
) -> dict | None:
    updates = []
    parameters = []
    if title is not None:
        title = title.strip()
        if not 1 <= len(title) <= 100:
            raise ValueError("Conversation title must contain 1 to 100 characters")
        updates.append("title = ?")
        parameters.append(title)
    if pinned is not None:
        updates.append("pinned = ?")
        parameters.append(1 if pinned else 0)
    if archived is not None:
        updates.append("archived_at = ?")
        parameters.append(
            datetime.now(timezone.utc).isoformat() if archived else None
        )
    if updates:
        updates.append("updated_at = ?")
        parameters.append(datetime.now(timezone.utc).isoformat())
        parameters.append(conversation_id)
        with _connection() as connection:
            connection.execute(
                f"UPDATE conversations SET {', '.join(updates)} WHERE id = ?",
                tuple(parameters),
            )
    return get_conversation(conversation_id)


def add_message_action(message_id: int, action: str, target: str) -> dict:
    if action not in MESSAGE_ACTIONS:
        raise ValueError("Unsupported message action")
    target = target.strip()
    if not 1 <= len(target) <= 500:
        raise ValueError("Message action target must contain 1 to 500 characters")
    now = datetime.now(timezone.utc).isoformat()
    with _connection() as connection:
        connection.execute(
            """INSERT INTO message_actions (message_id, action, target, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(message_id, action, target) DO NOTHING""",
            (message_id, action, target, now),
        )
    return {"action": action, "target": target, "created_at": now}


def get_message_actions(message_id: int) -> list[dict]:
    with _connection() as connection:
        rows = connection.execute(
            """SELECT action, target, created_at FROM message_actions
               WHERE message_id = ? ORDER BY created_at""",
            (message_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_conversations(
    limit: int = 50,
    include_archived: bool = False,
    include_deleted: bool = False,
) -> list[dict]:
    purge_expired_conversations()
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT id, title, created_at, updated_at, pinned, archived_at, deleted_at
            FROM conversations
            WHERE (deleted_at IS NULL OR ? = 1)
              AND (deleted_at IS NOT NULL OR archived_at IS NULL OR ? = 1)
            ORDER BY pinned DESC, updated_at DESC
            LIMIT ?
            """,
            (
                1 if include_deleted else 0,
                1 if include_archived else 0,
                limit,
            ),
        ).fetchall()

    return [_serialize_conversation(row) for row in rows]


def get_conversation(conversation_id: str) -> dict | None:
    with _connection() as connection:
        row = connection.execute(
            """SELECT id, title, created_at, updated_at, pinned, archived_at, deleted_at
               FROM conversations WHERE id = ?""",
            (conversation_id,),
        ).fetchone()
    return _serialize_conversation(row) if row else None


def _serialize_conversation(row) -> dict:
    item = {**dict(row), "pinned": bool(row["pinned"])}
    deleted_at = item.get("deleted_at")
    item["purge_after"] = (
        datetime.fromisoformat(deleted_at)
        + timedelta(days=DELETED_CONVERSATION_RETENTION_DAYS)
    ).isoformat() if deleted_at else None
    return item


def conversation_exists(conversation_id: str) -> bool:
    with _connection() as connection:
        row = connection.execute(
            """
            SELECT id
            FROM conversations
            WHERE id = ? AND deleted_at IS NULL
            """,
            (conversation_id,),
        ).fetchone()

    return row is not None
