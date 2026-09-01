from backend.app.tools.system_tools import (
    get_system_info,
    get_cpu_usage,
    get_memory_usage,
    get_disk_usage,
    get_running_processes,
)

from backend.app.tools.file_tools import (
    list_files,
    read_text_file,
    find_files,
)

from backend.app.tools.git_tools import (
    get_git_status,
    get_git_branch,
    get_recent_commits,
    get_git_diff,
)

from backend.app.tools.docker_tools import (
    get_docker_version,
    list_docker_containers,
    list_docker_images,
)
from backend.app.memory.long_term import (
    forget_memory,
    list_memories,
    remember_fact,
    search_memory,
    update_memory,
)
from backend.app.knowledge import (
    get_index_status,
    index_project,
    search_project_knowledge,
)
from backend.app.security.runtime import approval_manager, tool_registry
from backend.app.core.config import get_settings
from backend.app.integrations.infrastructure import (
    apply_terraform, check_terraform_format, describe_kubernetes_resource,
    destroy_terraform, get_aws_cloudwatch, get_aws_iam_context, get_aws_identity,
    get_azure_account, get_kubernetes_logs, get_terraform_version, list_aws_ec2,
    list_aws_eks, list_azure_aks, list_azure_resources, list_azure_subscriptions,
    list_azure_vms, list_kubernetes_contexts, list_kubernetes_deployments,
    list_kubernetes_events, list_kubernetes_namespaces, list_kubernetes_pods,
    list_kubernetes_services, plan_terraform, validate_terraform,
)
from backend.app.core.logging import log_event
from backend.app.models.catalog import ModelRegistry
from backend.app.integrations.mcp import mcp_adapter


SYSTEM_PROMPT = """
You are NEXUS, a local-first personal AI operating assistant.

You help the user inspect and understand their computer,
development environment, repositories, containers,
cloud systems, and engineering workflows.

You have safe read-only tools for:

- system information
- CPU, RAM and disk usage
- running processes
- project files
- Git repository information
- Docker information

Rules:

1. Use tools whenever real machine or project information is required.
2. Never invent system, repository, Docker, or file information.
3. Never claim to inspect something unless you actually used a tool.
4. Prefer read-only inspection.
5. Do not modify files.
6. Do not run arbitrary shell commands.
7. Do not perform Git writes.
8. Do not start, stop, delete, or modify Docker resources.
9. Explain findings clearly and practically.
10. Use long-term memory tools only for durable, useful information.
11. Never store credentials, tokens, passwords, or other secrets.
12. Never delete a memory unless the user explicitly asks you to.
13. Search project knowledge for repository or code questions.
14. Delegate conceptually to specialist capabilities without autonomous loops.
"""


class NexusAgent:
    def __init__(self, model_client=None):
        settings = get_settings()
        if model_client is not None:
            self.client = model_client
        else:
            self.client = ModelRegistry(settings).routed()
        self.model = self.client.model
        self.provider_name = self.client.provider_name

        self.tools = [
            # System
            get_system_info,
            get_cpu_usage,
            get_memory_usage,
            get_disk_usage,
            get_running_processes,

            # Files
            list_files,
            read_text_file,
            find_files,

            # Git
            get_git_status,
            get_git_branch,
            get_recent_commits,
            get_git_diff,

            # Docker
            get_docker_version,
            list_docker_containers,
            list_docker_images,
            remember_fact,
            search_memory,
            list_memories,
            update_memory,
            forget_memory,
            index_project,
            search_project_knowledge,
            get_index_status,
            get_aws_identity, list_aws_ec2, list_aws_eks, get_aws_cloudwatch,
            get_aws_iam_context, get_azure_account, list_azure_subscriptions,
            list_azure_vms, list_azure_aks, list_azure_resources,
            list_kubernetes_contexts, list_kubernetes_namespaces,
            list_kubernetes_pods, list_kubernetes_deployments,
            list_kubernetes_services, list_kubernetes_events,
            get_kubernetes_logs, describe_kubernetes_resource,
            get_terraform_version, validate_terraform,
            check_terraform_format, plan_terraform, apply_terraform,
            destroy_terraform,
        ]
        self.tools.extend(mcp_adapter.tool_functions())

        self.available_functions = {
            # System
            "get_system_info": get_system_info,
            "get_cpu_usage": get_cpu_usage,
            "get_memory_usage": get_memory_usage,
            "get_disk_usage": get_disk_usage,
            "get_running_processes": get_running_processes,

            # Files
            "list_files": list_files,
            "read_text_file": read_text_file,
            "find_files": find_files,

            # Git
            "get_git_status": get_git_status,
            "get_git_branch": get_git_branch,
            "get_recent_commits": get_recent_commits,
            "get_git_diff": get_git_diff,

            # Docker
            "get_docker_version": get_docker_version,
            "list_docker_containers": list_docker_containers,
            "list_docker_images": list_docker_images,
            "remember_fact": remember_fact,
            "search_memory": search_memory,
            "list_memories": list_memories,
            "update_memory": update_memory,
            "forget_memory": forget_memory,
            "index_project": index_project,
            "search_project_knowledge": search_project_knowledge,
            "get_index_status": get_index_status,
        }
        self.available_functions.update({tool.__name__: tool for tool in self.tools})

    async def run(
        self,
        message: str,
        history: list[dict] | None = None,
        relevant_memories: list[dict] | None = None,
        specialist_instruction: str | None = None,
    ) -> str:
        log_event("agent_request", history_count=len(history or []), memory_count=len(relevant_memories or []))
        messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            }
        ]

        if specialist_instruction:
            messages.append({
                "role": "system",
                "content": f"Specialist assignment for this bounded run: {specialist_instruction}",
            })

        if relevant_memories:
            memory_context = "\n".join(
                f"- [{item['category']}] {item['key']}: {item['content']}"
                for item in relevant_memories
            )
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Relevant long-term memories for this request only:\n"
                        f"{memory_context}"
                    ),
                }
            )

        # Load previous conversation context.
        if history:
            for item in history:
                if item["role"] in {"user", "assistant"}:
                    messages.append(
                        {
                            "role": item["role"],
                            "content": item["content"],
                        }
                    )

        # Add the current user message.
        messages.append(
            {
                "role": "user",
                "content": message,
            }
        )

        max_iterations = 8

        for _ in range(max_iterations):
            try:
                response = await self.client.chat(
                    messages, [] if self.provider_name == "llama_cpp" else self.tools
                )
            except Exception as error:
                log_event("model_failure", provider=self.provider_name, model=self.model, error=str(error))
                raise

            messages.append({
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {"name": call.name, "arguments": call.arguments}
                    for call in response.tool_calls
                ],
            })

            # No tool request means NEXUS has completed its response.
            if not response.tool_calls:
                return response.content

            # Execute all requested tools.
            for tool_call in response.tool_calls:
                function_name = tool_call.name
                log_event("tool_request", tool=function_name)

                function_to_call = self.available_functions.get(function_name)

                if not function_to_call:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_name": function_name,
                            "content": (
                                f"Tool '{function_name}' "
                                "is not available."
                            ),
                        }
                    )
                    continue

                arguments = tool_call.arguments

                try:
                    definition = tool_registry.get(function_name)
                    if not definition:
                        result = {"error": "Tool has no safety metadata"}
                    else:
                        result = approval_manager.execute_or_request(
                            function_name, arguments
                        )

                except Exception as error:
                    log_event("tool_failure", tool=function_name, error=str(error))
                    result = {
                        "error": str(error),
                        "tool": function_name,
                    }

                messages.append(
                    {
                        "role": "tool",
                        "tool_name": function_name,
                        "content": str(result),
                    }
                )

        return (
            "I reached the maximum number of tool iterations "
            "before completing the request."
        )
