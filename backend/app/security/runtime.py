from backend.app.knowledge import get_index_status, index_project, search_project_knowledge
from backend.app.memory.long_term import (
    forget_memory,
    list_memories,
    remember_fact,
    search_memory,
    update_memory,
)
from backend.app.security.safety import ApprovalManager, RiskLevel, ToolDefinition, ToolRegistry
from backend.app.tools.docker_tools import get_docker_version, list_docker_containers, list_docker_images
from backend.app.tools.file_tools import find_files, list_files, read_text_file
from backend.app.tools.git_tools import get_git_branch, get_git_diff, get_git_status, get_recent_commits
from backend.app.tools.system_tools import (
    get_cpu_usage,
    get_disk_usage,
    get_memory_usage,
    get_running_processes,
    get_system_info,
)
from backend.app.integrations.infrastructure import (
    apply_terraform, check_terraform_format, describe_kubernetes_resource,
    destroy_terraform, get_aws_cloudwatch, get_aws_iam_context, get_aws_identity,
    get_azure_account, get_kubernetes_logs, get_terraform_version, list_aws_ec2,
    list_aws_eks, list_azure_aks, list_azure_resources, list_azure_subscriptions,
    list_azure_vms, list_kubernetes_contexts, list_kubernetes_deployments,
    list_kubernetes_events, list_kubernetes_namespaces, list_kubernetes_pods,
    list_kubernetes_services, plan_terraform, validate_terraform,
)
from backend.app.automation.scheduler import automation_reminder
from backend.app.runner.service import queue_runner_job
from backend.app.integrations.web_research import structured_news_search, structured_web_search
from backend.app.integrations.contacts import send_confirmed_email
from backend.app.agents.orchestration import authorize_orchestration_plan


tool_registry = ToolRegistry()


def _register(function, category, risk=RiskLevel.READ_ONLY, writes=False, approval=False):
    tool_registry.register(ToolDefinition(
        name=function.__name__, category=category, risk_level=risk,
        writes=writes, approval_required=approval, function=function,
    ))


for function in (get_system_info, get_cpu_usage, get_memory_usage, get_disk_usage, get_running_processes):
    _register(function, "system")
for function in (list_files, read_text_file, find_files):
    _register(function, "files")
for function in (get_git_status, get_git_branch, get_recent_commits, get_git_diff):
    _register(function, "git")
for function in (get_docker_version, list_docker_containers, list_docker_images):
    _register(function, "docker")
for function in (search_memory, list_memories):
    _register(function, "memory")
for function in (remember_fact, update_memory):
    _register(function, "memory", RiskLevel.SAFE_WRITE, True, True)
_register(forget_memory, "memory", RiskLevel.DESTRUCTIVE, True, True)
for function in (search_project_knowledge, get_index_status):
    _register(function, "projects")
_register(index_project, "projects", RiskLevel.SAFE_WRITE, True, True)
for function in (
    get_aws_identity, list_aws_ec2, list_aws_eks, get_aws_cloudwatch,
    get_aws_iam_context, get_azure_account, list_azure_subscriptions,
    list_azure_vms, list_azure_aks, list_azure_resources,
    list_kubernetes_contexts, list_kubernetes_namespaces, list_kubernetes_pods,
    list_kubernetes_deployments, list_kubernetes_services,
    list_kubernetes_events, get_kubernetes_logs, describe_kubernetes_resource,
    get_terraform_version, validate_terraform, check_terraform_format,
    plan_terraform,
):
    _register(function, "infrastructure")
_register(apply_terraform, "terraform", RiskLevel.PRIVILEGED, True, True)
_register(destroy_terraform, "terraform", RiskLevel.DESTRUCTIVE, True, True)
_register(automation_reminder, "automation")
_register(queue_runner_job, "runner", RiskLevel.SAFE_WRITE, True, True)
_register(structured_web_search, "research")
_register(structured_news_search, "research")
_register(send_confirmed_email, "messaging", RiskLevel.SAFE_WRITE, True, True)
_register(authorize_orchestration_plan, "orchestration", RiskLevel.SAFE_WRITE, True, True)


approval_manager = ApprovalManager(tool_registry)


def initialize_safety():
    approval_manager.initialize()
