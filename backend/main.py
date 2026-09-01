import base64
import asyncio
import json
import re
import secrets
import time
import uuid
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr

from backend.app.agents.nexus import NexusAgent

from backend.app.tools.system_tools import (
    get_system_info,
    get_cpu_usage,
    get_memory_usage,
    get_disk_usage,
)

from backend.app.memory.store import (
    initialize_database,
    create_conversation,
    add_message,
    add_message_action,
    delete_conversation,
    delete_message,
    get_conversation,
    get_message,
    get_messages,
    list_conversations,
    restore_conversation,
    trash_conversation,
    update_conversation,
    conversation_exists,
)
from backend.app.memory.long_term import (
    MEMORY_CATEGORIES,
    forget_memory,
    initialize_memory,
    list_memories,
    memory_store,
    remember_fact,
    search_memory,
)
from backend.app.knowledge import (
    get_index_status,
    add_project_note,
    index_project,
    initialize_project_knowledge,
    search_project_knowledge,
)
from backend.app.security.runtime import (
    approval_manager,
    initialize_safety,
    tool_registry,
)
from backend.app.core.config import get_settings
from backend.app.models.catalog import ModelRegistry
from backend.app.media.service import MediaService
from backend.app.integrations.github import GitHubProvider
from backend.app.integrations.mcp import mcp_adapter
from backend.app.integrations.provider_connections import ProviderConnectionService
from backend.app.integrations.infrastructure import infrastructure_status
from backend.app.integrations.web_research import web_research_adapter
from backend.app.integrations.contacts import contact_messaging_service
from backend.app.agents.specialists import get_specialist, list_specialist_agents
from backend.app.agents.orchestration import TERMINAL_STATES, orchestration_service
from backend.app.voice.providers import (
    DisabledSpeechToText,
    DisabledTextToSpeech,
    DisabledWakeWord,
    FasterWhisperProvider,
    VoiceService,
)
from backend.app.automation.scheduler import JOB_TYPES, TaskScheduler
from backend.app.core.logging import log_event
from backend.app.database import DatabaseIntegrityError, database_connection
from backend.app.runner.service import RUNNER_TOOLS, runner_service
from backend.app.intent_routing import preview_intent_route


settings = get_settings()
APP_VERSION = "2.21.0"
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

app = FastAPI(
    title="NEXUS AI OS",
    description="Personal agentic AI operating layer",
    version=APP_VERSION,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


initialize_database()
initialize_memory()
initialize_project_knowledge()
orchestration_service.initialize()
initialize_safety()


def seed_demo_data():
    if not settings.demo_mode:
        return
    if list_conversations(limit=1, include_archived=True, include_deleted=True):
        return
    showcase_conversations = [
        (
            "V2.21 bulk conversation management",
            "How does the V2.21 sidebar workflow improve operator control?",
            "Operators can select conversations directly, see selection counts, and apply bounded bulk archive, restore, delete, or purge actions.",
        ),
        (
            "Safety model walkthrough",
            "What happens before a safe write is executed?",
            "Read-only work can run automatically. Safe writes pause for approval, while destructive objectives remain blocked.",
        ),
        (
            "Local-first architecture",
            "Which parts remain under operator control?",
            "NEXUS keeps local inference, approved project roots, runner capabilities, credentials, and final action authority bounded by explicit policy.",
        ),
    ]
    for title, question, answer in showcase_conversations:
        conversation_id = create_conversation(title)
        add_message(conversation_id, "user", question)
        add_message(conversation_id, "assistant", answer)


seed_demo_data()
provider_connection_service = ProviderConnectionService(settings)
provider_connection_service.initialize()
media_service = MediaService(settings)
media_service.initialize()
runner_service.initialize()
contact_messaging_service.initialize()

try:
    mcp_adapter.load_json(settings.mcp_servers)
except (ValueError, TypeError):
    pass
github_provider = GitHubProvider(settings.github_token)
stt_provider = (
    FasterWhisperProvider(settings.voice_model)
    if settings.voice_stt_provider == "faster-whisper"
    else DisabledSpeechToText()
)


@app.middleware("http")
async def require_api_access(request: Request, call_next):
    if (
        settings.demo_mode
        and request.url.path.startswith("/api/")
        and request.method not in {"GET", "HEAD", "OPTIONS"}
    ):
        return JSONResponse(
            status_code=403,
            content={"detail": "This public showcase is read-only demo mode"},
        )
    runner_worker = (
        request.url.path.startswith("/api/runner/nodes/")
        and request.url.path.rsplit("/", 1)[-1] in {"poll", "result", "heartbeat", "screenshot"}
    )
    protected = (
        request.url.path.startswith("/api/")
        and request.url.path != "/api/config"
        and not runner_worker
    )
    if protected and settings.access_token:
        authorization = request.headers.get("authorization", "")
        scheme, _, supplied_token = authorization.partition(" ")
        valid = (
            scheme.lower() == "bearer"
            and bool(supplied_token)
            and secrets.compare_digest(supplied_token, settings.access_token)
        )
        if not valid:
            return JSONResponse(
                status_code=401,
                content={"detail": "Valid NEXUS access token required"},
                headers={"WWW-Authenticate": "Bearer"},
            )
    return await call_next(request)


@app.middleware("http")
async def observe_and_harden_requests(request: Request, call_next):
    supplied_request_id = request.headers.get("x-request-id", "")
    request_id = (
        supplied_request_id
        if REQUEST_ID_PATTERN.fullmatch(supplied_request_id)
        else uuid.uuid4().hex
    )
    request.state.request_id = request_id
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
        "style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"
    )
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    log_event(
        "http_request",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    return response


voice_service = VoiceService(
    stt_provider, DisabledTextToSpeech(), DisabledWakeWord()
)
task_scheduler = TaskScheduler(approval_manager.execute_or_request)
task_scheduler.initialize()

model_registry = ModelRegistry(settings)


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None


class ConversationUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=100)
    pinned: Optional[bool] = None
    archived: Optional[bool] = None


class MemoryCreate(BaseModel):
    category: str
    key: str
    content: str
    source: str = "user"
    importance: int = 5


class MemoryUpdate(BaseModel):
    category: Optional[str] = None
    key: Optional[str] = None
    content: Optional[str] = None
    source: Optional[str] = None
    importance: Optional[int] = None


class ApprovalDecision(BaseModel):
    approved: bool


class AutomationCreate(BaseModel):
    name: str
    description: str = ""
    schedule: str
    agent: str = "NEXUS"
    job_type: str
    enabled: bool = True


class AutomationToggle(BaseModel):
    enabled: bool


class ImageGenerationRequest(BaseModel):
    prompt: str
    provider: str = "pollinations"
    model: str = "flux"
    width: int = 1024
    height: int = 1024


class VideoGenerationRequest(BaseModel):
    prompt: str
    provider: str = "pollinations"
    model: str = "wan-fast"
    duration: int = 4
    aspect_ratio: str = "16:9"


class MCPToolRequest(BaseModel):
    arguments: dict = {}


class ProviderConnectionRequest(BaseModel):
    api_key: SecretStr
    model: Optional[str] = None
    base_url: Optional[str] = None


class ProjectMessageRequest(BaseModel):
    project_id: str


class IntegrateMessageRequest(BaseModel):
    provider: str
    model: str
    instruction: str = "Continue from this message and provide an actionable result."
    confirmed: bool = False


class SpecialistRunRequest(BaseModel):
    message: str
    provider: Optional[str] = None
    model: Optional[str] = None


class OrchestrationPlanRequest(BaseModel):
    objective: str
    specialists: list[str] = Field(default_factory=list)
    provider: Optional[str] = None
    model: Optional[str] = None


class OrchestrationExecuteRequest(BaseModel):
    confirmed: bool = False


class RunnerPairRequest(BaseModel):
    name: str
    capabilities: list[str] = []


class RunnerJobRequest(BaseModel):
    node_id: str
    tool: str
    arguments: dict = {}


class RunnerToggleRequest(BaseModel):
    active: bool


class RunnerResultRequest(BaseModel):
    job_id: str
    succeeded: bool
    result: object


class RunnerScreenshotRequest(BaseModel):
    job_id: str
    image_base64: str


class ResearchRequest(BaseModel):
    query: str
    limit: int = 5


class ContactCreateRequest(BaseModel):
    name: str
    email: str
    consent_source: str
    consent_subject: str
    consented_at: str
    consent_expires_at: str | None = None


class ContactMessageRequest(BaseModel):
    subject: str
    body: str
    confirmed: bool = False

class IntentRouteRequest(BaseModel):
    message: str


@app.get("/")
async def root():
    index_path = settings.frontend_dist_path / "index.html"
    if settings.serve_frontend and index_path.is_file():
        return FileResponse(index_path)
    return {
        "name": "NEXUS",
        "version": APP_VERSION,
        "status": "online",
    }


@app.get("/api/config")
async def public_config():
    return {
        "authentication_required": bool(settings.access_token),
        "demo_mode": settings.demo_mode,
        "model_provider": settings.model_provider,
        "model": model_registry.public_catalog()["default_model"],
        "version": app.version,
    }


@app.get("/api/models")
async def models():
    return model_registry.public_catalog()


@app.get("/api/operations")
async def operations():
    services = []
    try:
        with database_connection() as connection:
            connection.execute("SELECT 1")
            database_state = "ready"
            database_detail = connection.dialect
    except Exception as error:
        database_state = "unavailable"
        database_detail = error.__class__.__name__
    services.append({
        "name": "database", "state": database_state, "detail": database_detail,
    })

    model_report = model_registry.operational_report()
    services.extend({
        "name": f"model:{provider['provider']}",
        "state": provider["state"],
        "detail": f"{provider['ready_models']} of {provider['model_count']} models ready",
        "setup_url": provider["setup_url"],
    } for provider in model_report["providers"])

    mcp_status = mcp_adapter.status()
    services.append({
        "name": "remote-mcp",
        "state": "ready" if any(
            item["status"] in {"ready", "online"} for item in mcp_status
        ) else "setup_required",
        "detail": f"{sum(item['tool_count'] for item in mcp_status)} tools discovered",
    })
    media = media_service.providers()
    services.append({
        "name": "media-generation",
        "state": "ready" if media else "setup_required",
        "detail": f"{len(media)} providers configured",
    })
    nodes = runner_service.list_nodes()
    services.append({
        "name": "local-runner",
        "state": "ready" if any(node["active"] for node in nodes) else "setup_required",
        "detail": f"{sum(1 for node in nodes if node['active'])} active machines",
    })
    asset_names = ("manifest.webmanifest", "service-worker.js", "nexus-icon.svg")
    asset_roots = (Path(settings.frontend_dist_path), Path("frontend/public"))
    pwa_ready = any(
        all((asset_root / name).is_file() for name in asset_names)
        for asset_root in asset_roots
    )
    services.append({
        "name": "authenticated-pwa", "state": "ready" if pwa_ready else "unavailable",
        "detail": "offline shell excludes APIs and credentials from cache",
    })
    required = [item for item in services if item["name"] in {
        "database", f"model:{settings.model_provider}", "authenticated-pwa",
    }]
    return {
        "version": APP_VERSION,
        "state": "operational" if all(item["state"] == "ready" for item in required) else "attention",
        "services": services,
        "models": model_report["models"],
        "approval_policy": "read-only automatic; safe writes approved; destructive blocked",
    }


@app.get("/api/media/providers")
async def media_providers():
    return {"providers": media_service.providers()}


@app.post("/api/media/understand")
async def understand_image(
    image: UploadFile,
    prompt: str = "Describe this image and extract all visible text.",
    provider: Optional[str] = None,
    model: Optional[str] = None,
):
    media_type = image.content_type or "application/octet-stream"
    if media_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=400, detail="JPEG, PNG, or WebP image required")
    data = await image.read(settings.media_max_upload_bytes + 1)
    if not data or len(data) > settings.media_max_upload_bytes:
        raise HTTPException(status_code=400, detail="Image is empty or exceeds the upload limit")
    try:
        profile = model_registry.select_profile(provider, model)
        if "vision" not in profile.capabilities:
            raise ValueError("Selected model does not support image understanding")
        client = model_registry.routed(profile.provider, profile.model)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    response = await client.chat([{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image", "mime_type": media_type, "data": base64.b64encode(data).decode()},
        ],
    }], [])
    return {"response": response.content, "provider": profile.provider, "model": profile.model}


@app.post("/api/media/images", status_code=201)
async def generate_image(request: ImageGenerationRequest):
    if not request.prompt.strip() or len(request.prompt) > 4000:
        raise HTTPException(status_code=400, detail="Image prompt must be 1-4000 characters")
    if request.width not in {512, 768, 1024, 1280, 1536} or request.height not in {
        512, 768, 1024, 1280, 1536,
    }:
        raise HTTPException(status_code=400, detail="Unsupported image dimensions")
    try:
        return await media_service.generate_image(**request.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except (httpx.HTTPError, RuntimeError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.post("/api/media/videos", status_code=202)
async def generate_video(request: VideoGenerationRequest):
    if not request.prompt.strip() or len(request.prompt) > 4000:
        raise HTTPException(status_code=400, detail="Video prompt must be 1-4000 characters")
    if request.duration < 2 or request.duration > 20:
        raise HTTPException(status_code=400, detail="Video duration must be 2-20 seconds")
    if request.aspect_ratio not in {"16:9", "9:16"}:
        raise HTTPException(status_code=400, detail="Unsupported video aspect ratio")
    try:
        return media_service.submit_video(**request.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/media/jobs")
async def media_jobs(limit: int = 50):
    return {"jobs": media_service.list_jobs(limit)}


@app.get("/api/media/jobs/{job_id}")
async def media_job(job_id: str):
    job = media_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Media job not found")
    return job


@app.get("/api/media/assets/{job_id}")
async def media_asset(job_id: str):
    path = media_service.asset_path(job_id)
    job = media_service.get_job(job_id)
    if not path or not job:
        raise HTTPException(status_code=404, detail="Media asset not found")
    return FileResponse(path, media_type=job.get("media_type"), filename=path.name)


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "agent": "online",
        "memory": "online",
    }


@app.get("/ready")
async def readiness():
    checks = {
        "database": {"ready": False},
        "model": {"ready": False, "provider": settings.model_provider},
    }
    try:
        with database_connection() as connection:
            connection.execute("SELECT 1")
        checks["database"] = {"ready": True}
    except Exception as error:
        log_event("readiness_failure", dependency="database", error=str(error))

    if settings.demo_mode:
        checks["model"] = {
            "ready": True,
            "provider": "demo",
            "detail": "Provider calls are intentionally disabled in demo mode",
        }
    else:
        checks["model"]["ready"] = model_registry.provider_ready()

    ready = all(check["ready"] for check in checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "checks": checks},
    )


@app.get("/api/system")
async def system_status():
    return {
        "system": get_system_info(),
        "cpu": get_cpu_usage(),
        "memory": get_memory_usage(),
        "disk": get_disk_usage(),
    }


@app.post("/api/chat")
async def chat(request: ChatRequest):
    try:
        model_client = model_registry.routed(request.provider, request.model)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    conversation_id = request.conversation_id

    if (
        not conversation_id
        or not conversation_exists(conversation_id)
    ):
        title = request.message[:60]

        conversation_id = create_conversation(
            title=title
        )

    history = get_messages(
        conversation_id,
        limit=20,
    )

    agent = NexusAgent(model_client=model_client)
    response = await agent.run(
        request.message,
        history=history,
        relevant_memories=search_memory(request.message, limit=5),
    )

    user_message = add_message(
        conversation_id,
        "user",
        request.message,
    )

    assistant_message = add_message(
        conversation_id,
        "assistant",
        response,
    )

    return {
        "conversation_id": conversation_id,
        "response": response,
        "provider": getattr(model_client, "active_provider", model_client.provider_name),
        "model": getattr(model_client, "active_model", model_client.model),
        "user_message": user_message,
        "assistant_message": assistant_message,
    }


@app.get("/api/conversations")
async def conversations(
    include_archived: bool = False,
    include_deleted: bool = False,
):
    return {
        "conversations": list_conversations(
            include_archived=include_archived,
            include_deleted=include_deleted,
        )
    }


@app.get("/api/conversations/{conversation_id}")
async def conversation(conversation_id: str):
    if not conversation_exists(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        "conversation_id": conversation_id,
        "messages": get_messages(
            conversation_id,
            limit=100,
        ),
    }


@app.patch("/api/conversations/{conversation_id}")
async def revise_conversation(conversation_id: str, request: ConversationUpdate):
    if not get_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    try:
        updated = update_conversation(
            conversation_id,
            title=request.title,
            pinned=request.pinned,
            archived=request.archived,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    log_event(
        "conversation_updated",
        conversation_id=conversation_id,
        title_changed=request.title is not None,
        pinned=request.pinned,
        archived=request.archived,
    )
    return {"conversation": updated}


@app.delete("/api/conversations/{conversation_id}")
async def remove_conversation(conversation_id: str):
    deleted = trash_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    log_event("conversation_deleted", conversation_id=conversation_id)
    return {
        "deleted": True,
        "conversation_id": conversation_id,
        "purge_after": deleted["purge_after"],
    }


@app.post("/api/conversations/{conversation_id}/restore")
async def recover_conversation(conversation_id: str):
    restored = restore_conversation(conversation_id)
    if not restored:
        raise HTTPException(status_code=404, detail="Deleted conversation not found")
    log_event("conversation_restored", conversation_id=conversation_id)
    return {"conversation": restored}


@app.delete("/api/conversations/{conversation_id}/purge")
async def purge_conversation(conversation_id: str):
    conversation = get_conversation(conversation_id)
    if not conversation or not conversation["deleted_at"]:
        raise HTTPException(status_code=404, detail="Deleted conversation not found")
    if not delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Deleted conversation not found")
    log_event("conversation_purged", conversation_id=conversation_id)
    return {"purged": True, "conversation_id": conversation_id}


@app.delete("/api/conversations/{conversation_id}/messages/{message_id}")
async def remove_chat_message(conversation_id: str, message_id: int):
    if message_id < 1 or not delete_message(conversation_id, message_id):
        raise HTTPException(status_code=404, detail="Chat message not found")
    log_event("chat_message_deleted", conversation_id=conversation_id, message_id=message_id)
    return {"deleted": True, "message_id": message_id}


@app.post("/api/conversations/{conversation_id}/messages/{message_id}/pin")
async def pin_chat_message(conversation_id: str, message_id: int):
    message = get_message(conversation_id, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Chat message not found")
    memory = remember_fact(
        key=f"chat-message:{conversation_id}:{message_id}",
        content=message["content"],
        category="note",
        source="chat-pin",
        importance=8,
    )
    add_message_action(message_id, "pinned", memory["id"])
    return {"memory": memory, "message": get_message(conversation_id, message_id)}


@app.post("/api/conversations/{conversation_id}/messages/{message_id}/project")
async def add_chat_message_to_project(
    conversation_id: str, message_id: int, request: ProjectMessageRequest
):
    message = get_message(conversation_id, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Chat message not found")
    try:
        note = add_project_note(
            request.project_id,
            f"chat:{conversation_id}:{message_id}",
            message["content"],
        )
        add_message_action(message_id, "project", note["id"])
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"project_note": note, "message": get_message(conversation_id, message_id)}


@app.post("/api/conversations/{conversation_id}/messages/{message_id}/integrate")
async def integrate_chat_message(
    conversation_id: str, message_id: int, request: IntegrateMessageRequest
):
    message = get_message(conversation_id, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Chat message not found")
    instruction = request.instruction.strip()
    if not 1 <= len(instruction) <= 2_000:
        raise HTTPException(
            status_code=400, detail="Integration instruction must contain 1 to 2,000 characters"
        )
    try:
        profile = model_registry.select_profile(request.provider, request.model)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if not request.confirmed:
        return {
            "state": "confirmation_required",
            "provider": profile.provider,
            "model": profile.model,
            "cost_tier": profile.cost_tier,
            "instruction": instruction,
            "content_characters": len(message["content"]),
            "content_preview": message["content"][:500],
        }
    try:
        client = model_registry.routed(profile.provider, profile.model)
        integrated = await client.chat(
            [
                {
                    "role": "system",
                    "content": "Transform the selected NEXUS chat message according to the user instruction. Do not call tools. Return only the result.",
                },
                {
                    "role": "user",
                    "content": f"Instruction:\n{instruction}\n\nSelected message:\n{message['content']}",
                },
            ],
            [],
        )
        if not integrated.content.strip():
            raise RuntimeError("Integrated provider returned no text")
    except (httpx.HTTPError, RuntimeError) as error:
        log_event(
            "chat_integration_failure",
            conversation_id=conversation_id,
            message_id=message_id,
            provider=profile.provider,
            error=error.__class__.__name__,
        )
        raise HTTPException(status_code=502, detail="Provider integration failed") from error
    result_message = add_message(conversation_id, "assistant", integrated.content)
    add_message_action(message_id, "integrated", profile.id)
    log_event(
        "chat_message_integrated",
        conversation_id=conversation_id,
        message_id=message_id,
        provider=profile.provider,
        model=profile.model,
    )
    return {
        "state": "completed",
        "provider": profile.provider,
        "model": profile.model,
        "message": result_message,
        "source_message": get_message(conversation_id, message_id),
    }


@app.get("/api/memories")
async def memories(
    category: Optional[str] = None,
    query: Optional[str] = Query(default=None, min_length=2),
):
    if category and category not in MEMORY_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid memory category")
    items = search_memory(query, limit=50) if query else list_memories(category)
    return {"memories": items, "categories": sorted(MEMORY_CATEGORIES)}


@app.post("/api/memories", status_code=201)
async def create_memory(request: MemoryCreate):
    try:
        return remember_fact(**request.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.patch("/api/memories/{memory_id}")
async def edit_memory(memory_id: str, request: MemoryUpdate):
    try:
        memory = memory_store.update(
            memory_id, **request.model_dump(exclude_none=True)
        )
    except (ValueError, DatabaseIntegrityError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory


@app.delete("/api/memories/{memory_id}", status_code=204)
async def delete_memory(memory_id: str):
    if not forget_memory(memory_id):
        raise HTTPException(status_code=404, detail="Memory not found")
    return Response(status_code=204)


@app.get("/api/projects")
async def projects():
    return {"projects": [get_index_status()]}


@app.post("/api/projects/index")
async def refresh_project_index():
    return approval_manager.execute_or_request("index_project", {})


@app.get("/api/projects/search")
async def search_project(query: str = Query(min_length=2), limit: int = 5):
    return {"results": search_project_knowledge(query, limit)}


@app.get("/api/tools")
async def tools():
    return {"tools": tool_registry.list()}


@app.get("/api/approvals")
async def approvals(state: Optional[str] = None):
    return {"approvals": approval_manager.list_approvals(state)}


@app.post("/api/approvals/{approval_id}")
async def decide_approval(approval_id: str, request: ApprovalDecision):
    result = approval_manager.resolve(approval_id, request.approved)
    if not result:
        raise HTTPException(status_code=404, detail="Pending approval not found")
    runner_service.apply_approval_result(approval_id, result["state"])
    return result


@app.get("/api/audit")
async def audit(limit: int = 100):
    return {"records": approval_manager.list_audit(limit)}


@app.get("/api/integrations")
async def integrations():
    return {
        "mcp": mcp_adapter.status(),
        "github": github_provider.status(settings.github_repository),
    }


@app.get("/api/provider-connections")
async def provider_connections():
    return provider_connection_service.public_status()


@app.put("/api/provider-connections/{provider}")
async def connect_provider(
    provider: str, payload: ProviderConnectionRequest, request: Request
):
    if not settings.access_token:
        raise HTTPException(
            status_code=403,
            detail="Set NEXUS_ACCESS_TOKEN before managing provider secrets in the UI",
        )
    loopback = request.url.hostname in {"localhost", "127.0.0.1", "::1"}
    if request.url.scheme != "https" and not loopback:
        raise HTTPException(
            status_code=400,
            detail="Provider secrets may be submitted only over HTTPS or loopback HTTP",
        )
    try:
        result = await provider_connection_service.connect(
            provider,
            payload.api_key.get_secret_value(),
            payload.model,
            payload.base_url,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    log_event(
        "provider_connection_verified",
        provider=result["provider"],
        storage_mode=result["mode"],
    )
    return result


@app.delete("/api/provider-connections/{provider}")
async def disconnect_provider(provider: str):
    if not settings.access_token:
        raise HTTPException(
            status_code=403,
            detail="Set NEXUS_ACCESS_TOKEN before managing provider secrets in the UI",
        )
    try:
        result = provider_connection_service.disconnect(provider)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    log_event("provider_connection_removed", provider=result["provider"])
    return result


@app.post("/api/integrations/mcp/{server_name}/refresh")
async def refresh_mcp(server_name: str):
    try:
        return await asyncio.to_thread(mcp_adapter.refresh, server_name, tool_registry)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except (httpx.HTTPError, RuntimeError) as error:
        log_event("integration_failure", integration=f"mcp:{server_name}", error=str(error))
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.post("/api/integrations/mcp/{server_name}/tools/{tool_name}")
async def call_mcp_tool(server_name: str, tool_name: str, request: MCPToolRequest):
    nexus_name = mcp_adapter.nexus_tool_name(server_name, tool_name)
    definition = tool_registry.get(nexus_name)
    if not definition:
        raise HTTPException(status_code=404, detail="Refresh this MCP connector before calling its tools")
    try:
        return await asyncio.to_thread(
            approval_manager.execute_or_request, nexus_name, request.arguments
        )
    except (ValueError, httpx.HTTPError, RuntimeError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.get("/api/integrations/github/{resource}")
async def github_resource(resource: str, repository: Optional[str] = None):
    repo = repository or settings.github_repository
    if not repo:
        raise HTTPException(status_code=400, detail="GitHub repository is not configured")
    handlers = {
        "repository": github_provider.repository,
        "branches": github_provider.branches,
        "commits": github_provider.commits,
        "issues": github_provider.issues,
        "pull-requests": github_provider.pull_requests,
        "workflows": github_provider.workflow_runs,
    }
    handler = handlers.get(resource)
    if not handler:
        raise HTTPException(status_code=404, detail="Unsupported GitHub resource")
    try:
        return {"data": handler(repo)}
    except (ValueError, httpx.HTTPError) as error:
        log_event("integration_failure", integration="github", error=str(error))
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.get("/api/agents")
async def agents():
    return {
        "orchestrator": "NEXUS",
        "agents": list_specialist_agents(),
        "infrastructure": infrastructure_status(),
    }


@app.get("/api/orchestration/plans")
async def orchestration_plans(limit: int = 20):
    return {"plans": orchestration_service.list_plans(limit)}


@app.post("/api/orchestration/plans", status_code=201)
async def create_orchestration_plan(request: OrchestrationPlanRequest):
    try:
        profile = model_registry.select_profile(request.provider, request.model)
        plan = orchestration_service.create_plan(
            request.objective, request.specialists, profile.provider, profile.model,
        )
        if plan["risk_level"] == "SAFE_WRITE":
            approval = approval_manager.execute_or_request(
                "authorize_orchestration_plan", {"plan_id": plan["id"]},
            )
            plan = orchestration_service.mark_approval_pending(
                plan["id"], approval["approval_id"],
            )
        return plan
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/orchestration/plans/{plan_id}")
async def get_orchestration_plan(plan_id: str):
    plan = orchestration_service.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Orchestration plan not found")
    return plan


@app.post("/api/orchestration/plans/{plan_id}/execute")
async def execute_orchestration_plan(
    plan_id: str, request: OrchestrationExecuteRequest,
):
    plan = orchestration_service.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Orchestration plan not found")
    try:
        model_client = model_registry.routed(plan["provider"], plan["model"])
        return await orchestration_service.execute(
            plan_id, model_client, request.confirmed,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/orchestration/plans/{plan_id}/start", status_code=202)
async def start_orchestration_plan(
    plan_id: str, request: OrchestrationExecuteRequest,
):
    plan = orchestration_service.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Orchestration plan not found")
    try:
        model_client = model_registry.routed(plan["provider"], plan["model"])
        return orchestration_service.start_execution(
            plan_id, model_client, request.confirmed,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/orchestration/plans/{plan_id}/cancel", status_code=202)
async def cancel_orchestration_plan(plan_id: str):
    if not orchestration_service.get_plan(plan_id):
        raise HTTPException(status_code=404, detail="Orchestration plan not found")
    try:
        return orchestration_service.request_cancellation(plan_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/orchestration/plans/{plan_id}/events")
async def orchestration_plan_events(
    plan_id: str, after_id: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200),
):
    if not orchestration_service.get_plan(plan_id):
        raise HTTPException(status_code=404, detail="Orchestration plan not found")
    return {"events": orchestration_service.list_events(plan_id, after_id, limit)}


@app.get("/api/orchestration/plans/{plan_id}/events/stream")
async def stream_orchestration_plan_events(
    plan_id: str, request: Request, after_id: int = Query(0, ge=0),
):
    if not orchestration_service.get_plan(plan_id):
        raise HTTPException(status_code=404, detail="Orchestration plan not found")
    header_cursor = request.headers.get("last-event-id", "")
    cursor = max(after_id, int(header_cursor) if header_cursor.isdigit() else 0)

    async def stream():
        nonlocal cursor
        yield "retry: 1000\n\n"
        idle_cycles = 0
        while not await request.is_disconnected():
            events = await asyncio.to_thread(
                orchestration_service.list_events, plan_id, cursor, 100,
            )
            for event in events:
                cursor = event["id"]
                yield (
                    f"id: {event['id']}\n"
                    f"event: {event['event_type']}\n"
                    f"data: {json.dumps(event)}\n\n"
                )
            plan = await asyncio.to_thread(orchestration_service.get_plan, plan_id)
            if plan and plan["state"] in TERMINAL_STATES and not events:
                break
            idle_cycles += 1
            if idle_cycles % 20 == 0:
                yield ": keepalive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.post("/api/research/search")
async def structured_search(request: ResearchRequest):
    try:
        return await asyncio.to_thread(web_research_adapter.search, request.query, request.limit)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except (httpx.HTTPError, ValueError) as error:
        log_event("integration_failure", integration="web_search", error=str(error))
        raise HTTPException(status_code=502, detail="Search provider unavailable") from error

@app.post("/api/intent-routing/preview")
async def intent_routing_preview(request: IntentRouteRequest):
    try:
        return preview_intent_route(request.message)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/research/news")
async def news_search(request: ResearchRequest):
    try:
        return await asyncio.to_thread(web_research_adapter.news, request.query, request.limit)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except (httpx.HTTPError, ElementTree.ParseError) as error:
        log_event("integration_failure", integration="news", error=str(error))
        raise HTTPException(status_code=502, detail="News provider unavailable") from error


@app.get("/api/contacts")
async def contacts():
    return {"contacts": contact_messaging_service.list_contacts(), "messages": contact_messaging_service.list_messages(), "smtp_configured": bool(settings.smtp_host and settings.smtp_from_address)}


@app.post("/api/contacts", status_code=201)
async def create_contact(request: ContactCreateRequest):
    try:
        return contact_messaging_service.create_contact(**request.model_dump())
    except (ValueError, DatabaseIntegrityError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/contacts/{contact_id}/opt-out")
async def opt_out_contact(contact_id: str):
    try:
        return contact_messaging_service.opt_out(contact_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/contacts/{contact_id}/messages")
async def send_contact_message(contact_id: str, request: ContactMessageRequest):
    try:
        preview = contact_messaging_service.preview(contact_id, request.subject, request.body)
        if not request.confirmed:
            return preview
        staged = contact_messaging_service.stage(contact_id, preview["subject"], request.body)
        approval = approval_manager.execute_or_request("send_confirmed_email", {"message_id": staged["id"]})
        return {**preview, "message_id": staged["id"], "approval": approval}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/agents/{agent_slug}/run")
async def run_specialist(agent_slug: str, request: SpecialistRunRequest):
    specialist = get_specialist(agent_slug)
    if not specialist:
        raise HTTPException(status_code=404, detail="Specialist agent not found")
    if not request.message.strip() or len(request.message) > 12000:
        raise HTTPException(status_code=400, detail="Agent message must be 1-12000 characters")
    try:
        model_client = model_registry.routed(request.provider, request.model)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    response = await NexusAgent(model_client=model_client).run(
        request.message,
        relevant_memories=search_memory(request.message, limit=5),
        specialist_instruction=specialist.instruction,
    )
    return {
        "agent": specialist.name,
        "status": "completed",
        "response": response,
        "provider": getattr(model_client, "active_provider", model_client.provider_name),
        "model": getattr(model_client, "active_model", model_client.model),
    }


@app.get("/api/runner")
async def runner_status():
    return {
        "nodes": runner_service.list_nodes(),
        "jobs": runner_service.list_jobs(),
        "tools": [{"name": name, **item} for name, item in RUNNER_TOOLS.items()],
        "transport": "outbound-polling",
    }


@app.post("/api/runner/nodes", status_code=201)
async def pair_runner(request: RunnerPairRequest):
    try:
        return runner_service.pair(request.name, request.capabilities or None)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.patch("/api/runner/nodes/{node_id}")
async def update_runner(node_id: str, request: RunnerToggleRequest):
    if request.active:
        raise HTTPException(status_code=400, detail="Disabled runners must be paired again")
    try:
        return runner_service.disable(node_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/runner/jobs", status_code=201)
async def create_runner_job(request: RunnerJobRequest):
    try:
        job = runner_service.create_job(request.node_id, request.tool, request.arguments)
        if job["risk_level"] == "SAFE_WRITE":
            approval = approval_manager.execute_or_request(
                "queue_runner_job", {"job_id": job["id"]}
            )
            runner_service.set_approval(job["id"], approval["approval_id"])
            job = runner_service.get_job(job["id"]) or job
            job["approval"] = approval
        return job
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _runner_bearer(request: Request) -> str:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Runner bearer token required")
    return token


@app.post("/api/runner/nodes/{node_id}/poll")
async def poll_runner(node_id: str, request: Request):
    try:
        job = runner_service.poll(node_id, _runner_bearer(request))
    except PermissionError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    return job or Response(status_code=204)


@app.post("/api/runner/nodes/{node_id}/result")
async def complete_runner_job(node_id: str, request: Request, result: RunnerResultRequest):
    try:
        return runner_service.complete(
            node_id, _runner_bearer(request), result.job_id, result.succeeded, result.result
        )
    except PermissionError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/runner/nodes/{node_id}/screenshot", status_code=201)
async def store_runner_screenshot(node_id: str, request: Request, payload: RunnerScreenshotRequest):
    try:
        token = _runner_bearer(request)
        runner_service.validate_running_job(node_id, token, payload.job_id, "capture_screenshot")
        if len(payload.image_base64) > settings.media_max_image_bytes * 2:
            raise ValueError("Screenshot payload exceeds the protected image limit")
        data = base64.b64decode(payload.image_base64, validate=True)
        job = media_service.store_runner_screenshot(data)
    except PermissionError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    log_event("runner_screenshot_stored", node_id=node_id, runner_job_id=payload.job_id, media_job_id=job["id"])
    return job


@app.post("/api/runner/nodes/{node_id}/heartbeat")
async def heartbeat_runner(node_id: str, request: Request):
    try:
        return runner_service.heartbeat(node_id, _runner_bearer(request))
    except PermissionError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error


@app.get("/api/voice/status")
async def voice_status():
    return voice_service.status()


@app.post("/api/voice/transcribe")
async def transcribe_voice(audio: UploadFile):
    media_type = audio.content_type or "application/octet-stream"
    if not media_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="An audio file is required")
    try:
        transcript = voice_service.transcribe(await audio.read(), media_type)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"transcript": transcript}


@app.on_event("startup")
async def start_automation_scheduler():
    for server in mcp_adapter.status():
        if server["enabled"] and server["auth_configured"]:
            try:
                await asyncio.to_thread(mcp_adapter.refresh, server["name"], tool_registry)
            except Exception as error:
                log_event("integration_failure", integration=f"mcp:{server['name']}", error=str(error))
    if settings.automation_enabled:
        await task_scheduler.start()


@app.on_event("shutdown")
async def stop_automation_scheduler():
    await orchestration_service.shutdown()
    await task_scheduler.stop()


@app.get("/api/automations")
async def automations():
    return {"jobs": task_scheduler.list(), "job_types": sorted(JOB_TYPES)}


@app.post("/api/automations", status_code=201)
async def create_automation(request: AutomationCreate):
    try:
        return task_scheduler.create(**request.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.patch("/api/automations/{job_id}")
async def toggle_automation(job_id: str, request: AutomationToggle):
    job = task_scheduler.set_enabled(job_id, request.enabled)
    if not job:
        raise HTTPException(status_code=404, detail="Automation not found")
    return job


@app.post("/api/automations/{job_id}/run")
async def run_automation(job_id: str):
    result = task_scheduler.run(job_id)
    if not result:
        raise HTTPException(status_code=404, detail="Enabled automation not found")
    return result


@app.get("/api/automations/history")
async def automation_history(job_id: Optional[str] = None, limit: int = 100):
    return {"history": task_scheduler.history(job_id, limit)}


@app.get("/api/notifications")
async def notifications():
    return {"notifications": task_scheduler.history(limit=20)}


frontend_path = Path(settings.frontend_dist_path)
assets_path = frontend_path / "assets"
if settings.serve_frontend and assets_path.is_dir():
    app.mount("/assets", StaticFiles(directory=assets_path), name="frontend-assets")
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend-public")
