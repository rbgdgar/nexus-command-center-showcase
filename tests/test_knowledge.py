import tempfile
import unittest
from pathlib import Path

from backend.app.knowledge import ProjectKnowledgeStore


class ProjectKnowledgeStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        self.root.mkdir()
        self.store = ProjectKnowledgeStore(
            Path(self.temp_dir.name) / "index.db", approved_root=self.root
        )
        self.store.initialize()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_index_search_and_exclusions(self):
        (self.root / "main.py").write_text("def nexus_agent():\n    return 'orchestrator'\n")
        (self.root / ".env").write_text("SECRET=do-not-index")
        modules = self.root / "node_modules"
        modules.mkdir()
        (modules / "secret.js").write_text("credential material")

        status = self.store.index(self.root)
        self.assertEqual(status["indexed_file_count"], 1)
        results = self.store.search("nexus orchestrator")
        self.assertEqual(results[0]["relative_path"], "main.py")
        self.assertEqual(self.store.search("do-not-index credential"), [])

    def test_reindex_detects_changes_and_stale_files(self):
        source = self.root / "README.md"
        source.write_text("first version")
        self.store.index(self.root)
        source.write_text("second version")
        changed = self.store.index(self.root)
        self.assertEqual(changed["changed_file_count"], 1)
        source.unlink()
        stale = self.store.index(self.root)
        self.assertEqual(stale["stale_file_count"], 1)

    def test_rejects_unapproved_root(self):
        with self.assertRaises(ValueError):
            self.store.index(Path(self.temp_dir.name))

    def test_chat_note_is_searchable_and_survives_reindex(self):
        project_id = self.store.status()["id"]
        note = self.store.add_note(
            project_id, "chat:conversation:42", "Decision: use encrypted provider storage"
        )

        first = self.store.search("encrypted provider")
        self.store.index(self.root)
        second = self.store.search("encrypted provider")

        self.assertEqual(first[0]["metadata"]["kind"], "project_note")
        self.assertEqual(first[0]["relative_path"], f"project-note:{note['id']}")
        self.assertEqual(second[0]["content"], note["content"])


if __name__ == "__main__":
    unittest.main()
