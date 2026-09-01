from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SpecialistAgent:
    slug: str
    name: str
    description: str
    capabilities: tuple[str, ...]
    instruction: str


SPECIALISTS = (
    SpecialistAgent("developer", "Developer Agent", "Repository and application engineering", ("files", "git", "project knowledge"), "Focus on evidence from repository tools, code quality, tests, and reversible engineering guidance."),
    SpecialistAgent("devops", "DevOps Agent", "Delivery, containers, and infrastructure workflows", ("docker", "terraform", "workflows"), "Focus on safe delivery diagnostics. Never bypass approvals or destructive-action blocks."),
    SpecialistAgent("cloud", "Cloud Agent", "Cloud account and resource inspection", ("aws", "azure", "gcp via MCP"), "Focus on read-only cloud inventory and cost-aware operational guidance."),
    SpecialistAgent("kubernetes", "Kubernetes Agent", "Cluster workload diagnostics", ("contexts", "workloads", "events", "logs"), "Focus on read-only cluster diagnosis and cite observed command results."),
    SpecialistAgent("research", "Research Agent", "Evidence-oriented information synthesis", ("project knowledge", "GitHub", "remote MCP"), "Focus on source-backed research and distinguish observations from inference."),
)


def list_specialist_agents() -> list[dict]:
    return [
        {
            **asdict(agent),
            "capabilities": list(agent.capabilities),
            "orchestrator": "NEXUS",
            "status": "ready",
            "execution": "bounded-single-run",
        }
        for agent in SPECIALISTS
    ]


def get_specialist(slug: str) -> SpecialistAgent | None:
    return next((agent for agent in SPECIALISTS if agent.slug == slug), None)
