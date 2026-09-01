"""Explainable, non-executing intent-route preview."""
from __future__ import annotations

from typing import Any


def preview_intent_route(message: str) -> dict[str, Any]:
    text = message.strip()
    if not 1 <= len(text) <= 2000:
        raise ValueError("Message must be 1-2000 characters")
    lowered = text.lower()
    if any(word in lowered for word in ("search", "news", "latest", "research")):
        route = ("research", "read-only", False, "Structured public search or news")
    elif any(word in lowered for word in ("email", "contact", "message")):
        route = ("contacts", "safe_write", True, "Consent-bound SMTP preview and final approval")
    elif any(word in lowered for word in ("screenshot", "volume", "launch", "local runner")):
        route = ("runner", "safe_write", True, "Outbound-only paired-machine job")
    else:
        route = ("chat", "read-only", False, "Configured model routing with provider policy")
    destination, risk, approval, detail = route
    return {"intent": destination, "risk_level": risk, "approval_required": approval, "nodes": ["message", "intent_classifier", "safety_policy", destination], "detail": detail}
