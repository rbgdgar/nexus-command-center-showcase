from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from backend.app.memory.store import PROJECT_ROOT


class AllowListedCommandRunner:
    ALLOWED = {"aws", "az", "kubectl", "terraform"}

    def run(self, executable: str, arguments: list[str], cwd: str | Path | None = None) -> dict:
        if executable not in self.ALLOWED:
            raise ValueError("Command is not allow-listed")
        path = shutil.which(executable)
        if not path:
            return {"available": False, "command": executable, "error": "CLI not installed"}
        completed = subprocess.run(
            [path, *arguments], cwd=cwd, capture_output=True, text=True,
            timeout=120, shell=False, check=False,
        )
        output = completed.stdout.strip() or completed.stderr.strip()
        try:
            output = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            pass
        return {"available": True, "returncode": completed.returncode, "output": output}


runner = AllowListedCommandRunner()


class AWSAdapter:
    def __init__(self, command_runner=runner): self.runner = command_runner
    def caller_identity(self): return self.runner.run("aws", ["sts", "get-caller-identity", "--output", "json"])
    def ec2_instances(self): return self.runner.run("aws", ["ec2", "describe-instances", "--output", "json"])
    def eks_clusters(self): return self.runner.run("aws", ["eks", "list-clusters", "--output", "json"])
    def cloudwatch_alarms(self): return self.runner.run("aws", ["cloudwatch", "describe-alarms", "--output", "json"])
    def iam_context(self): return self.runner.run("aws", ["iam", "get-account-summary", "--output", "json"])


class AzureAdapter:
    def __init__(self, command_runner=runner): self.runner = command_runner
    def account(self): return self.runner.run("az", ["account", "show", "--output", "json"])
    def subscriptions(self): return self.runner.run("az", ["account", "list", "--output", "json"])
    def virtual_machines(self): return self.runner.run("az", ["vm", "list", "--output", "json"])
    def aks_clusters(self): return self.runner.run("az", ["aks", "list", "--output", "json"])
    def resources(self): return self.runner.run("az", ["resource", "list", "--output", "json"])


class KubernetesAdapter:
    def __init__(self, command_runner=runner): self.runner = command_runner
    def _get(self, resource, namespace=None):
        args = ["get", resource]
        if namespace: args += ["--namespace", namespace]
        args += ["--output", "json"]
        return self.runner.run("kubectl", args)
    def contexts(self): return self.runner.run("kubectl", ["config", "get-contexts", "--output", "name"])
    def namespaces(self): return self._get("namespaces")
    def pods(self, namespace=None): return self._get("pods", namespace)
    def deployments(self, namespace=None): return self._get("deployments", namespace)
    def services(self, namespace=None): return self._get("services", namespace)
    def events(self, namespace=None): return self._get("events", namespace)
    def logs(self, pod: str, namespace=None):
        args = ["logs", pod, "--tail", "200"]
        if namespace: args += ["--namespace", namespace]
        return self.runner.run("kubectl", args)
    def describe(self, resource: str, name: str, namespace=None):
        args = ["describe", resource, name]
        if namespace: args += ["--namespace", namespace]
        return self.runner.run("kubectl", args)


class TerraformAdapter:
    def __init__(self, command_runner=runner, project_root=PROJECT_ROOT):
        self.runner = command_runner
        self.project_root = Path(project_root)
    def version(self): return self.runner.run("terraform", ["version", "-json"], self.project_root)
    def validate(self): return self.runner.run("terraform", ["validate", "-json"], self.project_root)
    def fmt_check(self): return self.runner.run("terraform", ["fmt", "-check", "-diff"], self.project_root)
    def plan(self): return self.runner.run("terraform", ["plan", "-input=false", "-no-color"], self.project_root)
    def apply(self): return self.runner.run("terraform", ["apply", "-input=false", "-auto-approve"], self.project_root)
    def destroy(self): return {"blocked": True, "reason": "Terraform destroy is disabled"}


aws_adapter = AWSAdapter()
azure_adapter = AzureAdapter()
kubernetes_adapter = KubernetesAdapter()
terraform_adapter = TerraformAdapter()


def infrastructure_status() -> dict:
    return {
        name: {"available": bool(shutil.which(name)), "mode": "read-only"}
        for name in ("aws", "az", "kubectl", "terraform")
    }


def get_aws_identity(): return aws_adapter.caller_identity()
def list_aws_ec2(): return aws_adapter.ec2_instances()
def list_aws_eks(): return aws_adapter.eks_clusters()
def get_aws_cloudwatch(): return aws_adapter.cloudwatch_alarms()
def get_aws_iam_context(): return aws_adapter.iam_context()
def get_azure_account(): return azure_adapter.account()
def list_azure_subscriptions(): return azure_adapter.subscriptions()
def list_azure_vms(): return azure_adapter.virtual_machines()
def list_azure_aks(): return azure_adapter.aks_clusters()
def list_azure_resources(): return azure_adapter.resources()
def list_kubernetes_contexts(): return kubernetes_adapter.contexts()
def list_kubernetes_namespaces(): return kubernetes_adapter.namespaces()
def list_kubernetes_pods(namespace: str | None = None): return kubernetes_adapter.pods(namespace)
def list_kubernetes_deployments(namespace: str | None = None): return kubernetes_adapter.deployments(namespace)
def list_kubernetes_services(namespace: str | None = None): return kubernetes_adapter.services(namespace)
def list_kubernetes_events(namespace: str | None = None): return kubernetes_adapter.events(namespace)
def get_kubernetes_logs(pod: str, namespace: str | None = None): return kubernetes_adapter.logs(pod, namespace)
def describe_kubernetes_resource(resource: str, name: str, namespace: str | None = None): return kubernetes_adapter.describe(resource, name, namespace)
def get_terraform_version(): return terraform_adapter.version()
def validate_terraform(): return terraform_adapter.validate()
def check_terraform_format(): return terraform_adapter.fmt_check()
def plan_terraform(): return terraform_adapter.plan()
def apply_terraform(): return terraform_adapter.apply()
def destroy_terraform(): return terraform_adapter.destroy()
