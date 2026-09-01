import tempfile
import unittest
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.database import database_connection
from backend.app.memory.store import (
    add_message,
    add_message_action,
    create_conversation,
    delete_conversation,
    delete_message,
    get_message,
    get_messages,
    initialize_database,
    list_conversations,
    restore_conversation,
    trash_conversation,
    update_conversation,
)


class ChatMessageActionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings = get_settings()
        self.original_path = self.settings.database_path
        self.original_url = self.settings.database_url
        self.database_path = Path(self.temp_dir.name) / "chat-actions.db"
        self.settings.database_path = self.database_path
        self.settings.database_url = None
        initialize_database()

    def tearDown(self):
        self.settings.database_path = self.original_path
        self.settings.database_url = self.original_url
        self.temp_dir.cleanup()

    def test_message_identity_actions_and_delete(self):
        conversation_id = create_conversation("Action test")
        message = add_message(conversation_id, "assistant", "Pin this result")
        add_message_action(message["id"], "pinned", "memory-id")
        add_message_action(message["id"], "project", "project-note-id")

        stored = get_message(conversation_id, message["id"])

        self.assertEqual(stored["content"], "Pin this result")
        self.assertEqual(
            {item["action"] for item in stored["actions"]},
            {"pinned", "project"},
        )
        self.assertEqual(get_messages(conversation_id)[0]["id"], message["id"])
        self.assertTrue(delete_message(conversation_id, message["id"]))
        self.assertIsNone(get_message(conversation_id, message["id"]))
        with database_connection(database_path=self.database_path) as connection:
            action_count = connection.execute(
                "SELECT COUNT(*) AS count FROM message_actions"
            ).fetchone()["count"]
        self.assertEqual(action_count, 0)

    def test_message_action_allowlist(self):
        conversation_id = create_conversation("Action validation")
        message = add_message(conversation_id, "user", "Validate action")
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            add_message_action(message["id"], "share-secret", "target")

    def test_delete_conversation_cascades_messages_and_actions(self):
        conversation_id = create_conversation("Delete this conversation")
        message = add_message(conversation_id, "assistant", "Temporary content")
        add_message_action(message["id"], "pinned", "memory-id")

        self.assertTrue(delete_conversation(conversation_id))
        self.assertFalse(delete_conversation(conversation_id))
        self.assertEqual(get_messages(conversation_id), [])
        with database_connection(database_path=self.database_path) as connection:
            message_count = connection.execute(
                "SELECT COUNT(*) AS count FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()["count"]
            action_count = connection.execute(
                "SELECT COUNT(*) AS count FROM message_actions"
            ).fetchone()["count"]
        self.assertEqual(message_count, 0)
        self.assertEqual(action_count, 0)

    def test_conversation_organization(self):
        first_id = create_conversation("First conversation")
        second_id = create_conversation("Second conversation")

        updated = update_conversation(
            first_id,
            title="Pinned conversation",
            pinned=True,
            archived=True,
        )

        self.assertEqual(updated["title"], "Pinned conversation")
        self.assertTrue(updated["pinned"])
        self.assertIsNotNone(updated["archived_at"])
        self.assertEqual(
            [item["id"] for item in list_conversations()],
            [second_id],
        )
        all_conversations = list_conversations(include_archived=True)
        self.assertEqual(all_conversations[0]["id"], first_id)
        self.assertTrue(all_conversations[0]["pinned"])

        restored = update_conversation(first_id, archived=False, pinned=False)
        self.assertIsNone(restored["archived_at"])
        self.assertFalse(restored["pinned"])

    def test_conversation_trash_restore_and_purge(self):
        conversation_id = create_conversation("Recoverable conversation")
        message = add_message(conversation_id, "user", "Keep this for now")

        trashed = trash_conversation(conversation_id)
        self.assertIsNotNone(trashed["deleted_at"])
        self.assertIsNotNone(trashed["purge_after"])
        self.assertEqual(list_conversations(), [])
        self.assertEqual(
            list_conversations(include_deleted=True)[0]["id"],
            conversation_id,
        )
        self.assertEqual(get_messages(conversation_id)[0]["id"], message["id"])

        restored = restore_conversation(conversation_id)
        self.assertIsNone(restored["deleted_at"])
        self.assertEqual(list_conversations()[0]["id"], conversation_id)

        trash_conversation(conversation_id)
        self.assertTrue(delete_conversation(conversation_id))
        self.assertEqual(list_conversations(include_deleted=True), [])

        expired_id = create_conversation("Expired conversation")
        expired_message = add_message(expired_id, "assistant", "Expired content")
        add_message_action(expired_message["id"], "pinned", "expired-memory")
        with database_connection(database_path=self.database_path) as connection:
            connection.execute(
                "UPDATE conversations SET deleted_at = ? WHERE id = ?",
                ("2000-01-01T00:00:00+00:00", expired_id),
            )
        self.assertEqual(list_conversations(include_deleted=True), [])
        self.assertEqual(get_messages(expired_id), [])


if __name__ == "__main__":
    unittest.main()
