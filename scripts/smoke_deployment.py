"""Safe production smoke test that never prints credentials or private data."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import dotenv_values


def request_json(base_url: str, path: str, token: str | None = None, method: str = "GET", payload: dict | None = None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    if data:
        headers["Content-Type"] = "application/json"
    request = Request(f"{base_url.rstrip('/')}{path}", headers=headers, method=method, data=data)
    try:
        with urlopen(request, timeout=90) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        try:
            payload = json.loads(error.read())
        except (ValueError, TypeError):
            payload = {}
        return error.code, payload
    except (URLError, TimeoutError):
        return 0, {}


def request_status(base_url: str, path: str) -> int:
    try:
        with urlopen(f"{base_url.rstrip('/')}{path}", timeout=90) as response:
            return response.status
    except HTTPError as error:
        return error.code
    except (URLError, TimeoutError):
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Optional ignored dotenv file used only to load NEXUS_ACCESS_TOKEN",
    )
    args = parser.parse_args()
    token = os.getenv("NEXUS_ACCESS_TOKEN")
    if not token and args.env_file:
        token = dotenv_values(args.env_file).get("NEXUS_ACCESS_TOKEN")

    health_status, health = request_json(args.base_url, "/health")
    config_status, config = request_json(args.base_url, "/api/config")
    private_status, _ = request_json(args.base_url, "/api/system")
    ready_status, ready = request_json(args.base_url, "/ready")
    manifest_status = request_status(args.base_url, "/manifest.webmanifest")
    worker_status = request_status(args.base_url, "/service-worker.js")
    icon_status = request_status(args.base_url, "/nexus-icon.svg")

    checks = {
        "health": health_status == 200 and health.get("status") == "healthy",
        "config": config_status == 200 and bool(config.get("version")),
        "authentication": private_status == 401 if config.get("authentication_required") else True,
        "readiness": ready_status == 200 and ready.get("status") == "ready",
        "pwa_manifest": manifest_status == 200,
        "pwa_worker": worker_status == 200,
        "pwa_icon": icon_status == 200,
    }
    if token:
        authenticated_status, _ = request_json(args.base_url, "/api/system", token)
        operations_status, operations = request_json(args.base_url, "/api/operations", token)
        models_status, models = request_json(args.base_url, "/api/models", token)
        runner_status, runner = request_json(args.base_url, "/api/runner", token)
        contacts_status, contacts = request_json(args.base_url, "/api/contacts", token)
        route_status, route = request_json(args.base_url, "/api/intent-routing/preview", token, "POST", {"message": "search current news"})
        plans_status, plans = request_json(args.base_url, "/api/orchestration/plans", token)
        plan_items = plans.get("plans", []) if isinstance(plans, dict) else []
        if plan_items:
            plan_id = plan_items[0].get("id", "")
            events_status, events = request_json(args.base_url, f"/api/orchestration/plans/{plan_id}/events", token)
        else:
            events_status, events = 200, {"events": []}
        checks["authenticated_api"] = authenticated_status == 200
        checks["operations_matrix"] = (
            operations_status == 200
            and operations.get("version") == config.get("version")
            and isinstance(operations.get("services"), list)
        )
        checks["model_catalog"] = models_status == 200 and isinstance(models.get("models"), list)
        checks["runner_status"] = runner_status == 200 and isinstance(runner.get("tools"), list)
        checks["contacts_status"] = contacts_status == 200 and isinstance(contacts.get("contacts"), list)
        checks["intent_route"] = route_status == 200 and route.get("intent") == "research" and route.get("approval_required") is False
        checks["orchestration_plans"] = plans_status == 200 and isinstance(plans.get("plans"), list)
        checks["orchestration_events"] = events_status == 200 and isinstance(events.get("events"), list)
        checks["orchestration_control"] = plans_status == 200 and all(
            isinstance(item.get("cancellable"), bool) for item in plan_items
        )

    print(json.dumps({"target": args.base_url, "checks": checks}, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
