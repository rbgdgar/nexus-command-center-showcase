import tempfile
import unittest
from pathlib import Path

from backend.app.security.safety import (
    ApprovalManager,
    RiskLevel,
    ToolDefinition,
    ToolRegistry,
)


class SafetyFrameworkTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.registry = ToolRegistry()
        self.registry.register(ToolDefinition(
            "inspect", "test", RiskLevel.READ_ONLY, False, False,
            lambda target: {"target": target},
        ))
        self.registry.register(ToolDefinition(
            "write", "test", RiskLevel.SAFE_WRITE, True, True,
            lambda value: self.calls.append(value) or value,
        ))
        self.registry.register(ToolDefinition(
            "destroy", "test", RiskLevel.DESTRUCTIVE, True, True,
            lambda: self.calls.append("destroyed"),
        ))
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = ApprovalManager(
            self.registry, Path(self.temp_dir.name) / "safety.db"
        )
        self.manager.initialize()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_read_only_executes_automatically(self):
        result = self.manager.execute_or_request("inspect", {"target": "repo"})
        self.assertEqual(result["state"], "executed")

    def test_safe_write_pauses_for_approval(self):
        pending = self.manager.execute_or_request("write", {"value": "change"})
        self.assertEqual(pending["state"], "approval_required")
        self.assertEqual(self.calls, [])
        resolved = self.manager.resolve(pending["approval_id"], True)
        self.assertEqual(resolved["state"], "executed")
        self.assertEqual(self.calls, ["change"])

    def test_denial_and_destructive_block(self):
        pending = self.manager.execute_or_request("write", {"value": "no"})
        self.assertEqual(self.manager.resolve(pending["approval_id"], False)["state"], "denied")
        blocked = self.manager.execute_or_request("destroy", {})
        self.assertEqual(blocked["state"], "blocked")
        self.assertEqual(self.calls, [])

    def test_invalid_metadata_is_rejected(self):
        with self.assertRaises(ValueError):
            self.registry.register(ToolDefinition(
                "unsafe", "test", RiskLevel.SAFE_WRITE, True, False, lambda: None
            ))


if __name__ == "__main__":
    unittest.main()
