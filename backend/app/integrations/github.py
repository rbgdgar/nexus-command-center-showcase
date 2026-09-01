from __future__ import annotations

from typing import Any

import httpx


class GitHubProvider:
    def __init__(
        self,
        token: str | None = None,
        client: httpx.Client | None = None,
        base_url: str = "https://api.github.com",
    ):
        self.token = token
        self.client = client or httpx.Client(timeout=20)
        self.base_url = base_url.rstrip("/")

    def _get(self, path: str, params: dict | None = None) -> Any:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        response = self.client.get(f"{self.base_url}{path}", headers=headers, params=params)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _repo_path(repository: str) -> str:
        parts = repository.strip("/").split("/")
        if len(parts) != 2 or not all(parts):
            raise ValueError("Repository must use owner/name format")
        return f"/repos/{parts[0]}/{parts[1]}"

    def repository(self, repository: str) -> dict:
        return self._get(self._repo_path(repository))

    def branches(self, repository: str) -> list[dict]:
        return self._get(f"{self._repo_path(repository)}/branches", {"per_page": 50})

    def commits(self, repository: str) -> list[dict]:
        return self._get(f"{self._repo_path(repository)}/commits", {"per_page": 30})

    def issues(self, repository: str) -> list[dict]:
        return self._get(f"{self._repo_path(repository)}/issues", {"state": "all", "per_page": 50})

    def pull_requests(self, repository: str) -> list[dict]:
        return self._get(f"{self._repo_path(repository)}/pulls", {"state": "all", "per_page": 50})

    def workflow_runs(self, repository: str) -> dict:
        return self._get(f"{self._repo_path(repository)}/actions/runs", {"per_page": 30})

    def status(self, repository: str | None) -> dict:
        return {
            "configured": bool(repository),
            "repository": repository,
            "authenticated": bool(self.token),
            "mode": "read-only",
        }
