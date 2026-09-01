import tempfile
import unittest
from pathlib import Path

from backend.app.memory.long_term import LongTermMemoryStore


class LongTermMemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = LongTermMemoryStore(Path(self.temp_dir.name) / "memory.db")
        self.store.initialize()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_memory_lifecycle(self):
        memory = self.store.remember(
            "preference", "editor", "Prefers VS Code", importance=8
        )
        self.assertEqual(memory["category"], "preference")
        self.assertEqual(len(self.store.list()), 1)
        self.assertEqual(self.store.search("preferred editor")[0]["id"], memory["id"])
        updated = self.store.update(
            memory["id"], content="Prefers Neovim", importance=9
        )
        self.assertEqual(updated["content"], "Prefers Neovim")
        self.assertTrue(self.store.forget(memory["id"]))
        self.assertEqual(self.store.list(), [])

    def test_upsert_preserves_identity(self):
        original = self.store.remember("project", "nexus", "Local agent")
        updated = self.store.remember("project", "nexus", "Local AI OS")
        self.assertEqual(updated["id"], original["id"])
        self.assertEqual(updated["content"], "Local AI OS")

    def test_validation(self):
        with self.assertRaises(ValueError):
            self.store.remember("secret", "token", "never store this")
        with self.assertRaises(ValueError):
            self.store.remember("fact", "x", "y", importance=11)


if __name__ == "__main__":
    unittest.main()
