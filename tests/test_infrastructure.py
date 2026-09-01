import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from backend.app.agents.specialists import list_specialist_agents
from backend.app.integrations.infrastructure import (
    AWSAdapter,
    AllowListedCommandRunner,
    KubernetesAdapter,
    TerraformAdapter,
)
from scripts.smoke_deployment import request_json, request_status


class FakeRunner:
    def __init__(self): self.calls = []
    def run(self, executable, arguments, cwd=None):
        self.calls.append((executable, arguments, cwd))
        return {"available": True, "returncode": 0, "output": {}}


class InfrastructureTests(unittest.TestCase):
    def test_aws_and_kubernetes_use_allowlisted_argument_arrays(self):
        runner = FakeRunner()
        AWSAdapter(runner).caller_identity()
        KubernetesAdapter(runner).pods("default")
        self.assertEqual(runner.calls[0][:2], ("aws", ["sts", "get-caller-identity", "--output", "json"]))
        self.assertEqual(runner.calls[1][0], "kubectl")
        self.assertIn("default", runner.calls[1][1])

    def test_terraform_destroy_is_blocked(self):
        adapter = TerraformAdapter(FakeRunner())
        self.assertTrue(adapter.destroy()["blocked"])

    def test_runner_rejects_unknown_executable(self):
        with self.assertRaises(ValueError):
            AllowListedCommandRunner().run("powershell", ["anything"])

    def test_specialists_remain_under_nexus(self):
        agents = list_specialist_agents()
        self.assertEqual(len(agents), 5)
        self.assertTrue(all(agent["orchestrator"] == "NEXUS" for agent in agents))
        self.assertTrue(all(agent["status"] == "ready" for agent in agents))

    def test_pwa_shell_never_caches_api_or_tokens(self):
        worker = Path("frontend/public/service-worker.js").read_text(encoding="utf-8")
        manifest = Path("frontend/public/manifest.webmanifest").read_text(encoding="utf-8")
        self.assertIn('url.pathname.startsWith("/api/")', worker)
        self.assertNotIn("nexus_access_token", worker)
        self.assertIn('\"display\": \"standalone\"', manifest)
        smoke = Path("scripts/smoke_deployment.py").read_text(encoding="utf-8")
        self.assertIn('\"/manifest.webmanifest\"', smoke)
        self.assertIn('\"/api/operations\"', smoke)
        self.assertIn('\"/api/intent-routing/preview\"', smoke)
        self.assertIn('\"/api/orchestration/plans\"', smoke)
        self.assertIn('operations.get(\"version\") == config.get(\"version\")', smoke)
        self.assertNotIn("print(token", smoke)

    @patch("scripts.smoke_deployment.urlopen", side_effect=URLError("dns unavailable"))
    def test_deployment_smoke_reports_network_failure_without_traceback(self, _urlopen):
        self.assertEqual(request_json("https://example.invalid", "/health"), (0, {}))
        self.assertEqual(request_status("https://example.invalid", "/manifest.webmanifest"), 0)


if __name__ == "__main__":
    unittest.main()
