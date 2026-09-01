from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="NEXUS_", extra="ignore")

    model_provider: str = "ollama"
    model_name: str = "qwen3:4b"
    ollama_url: str = "http://localhost:11434"
    gemini_api_key: str | None = None
    gemini_model_name: str = "gemini-3.7-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    openrouter_api_key: str | None = None
    openrouter_model_name: str = "openrouter/free"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    groq_api_key: str | None = None
    groq_model_name: str = "openai/gpt-oss-120b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    openai_api_key: str | None = None
    openai_model_name: str = "gpt-5.6-luna"
    openai_base_url: str = "https://api.openai.com/v1"
    compatible_api_key: str | None = None
    compatible_model_name: str | None = None
    compatible_base_url: str | None = None
    compatible_label: str = "Compatible API"
    compatible_cost_tier: str = "unknown"
    provider_secret_encryption_key: str | None = None
    provider_allowed_hosts: str = ""
    model_fallback_enabled: bool = True
    model_fallbacks: str = "gemini,openrouter,groq"
    allow_paid_models: bool = False
    ollama_enabled: bool = False
    llama_cpp_enabled: bool = False
    llama_cpp_executable: Path | None = None
    llama_cpp_model_path: Path | None = None
    llama_cpp_context_size: int = 4096
    llama_cpp_threads: int = 4
    public_url: str = "https://nexus-command-center-r3h8.onrender.com"
    pollinations_api_key: str | None = None
    pollinations_base_url: str = "https://gen.pollinations.ai"
    media_storage_path: Path = Path("data/media")
    media_max_upload_bytes: int = 10 * 1024 * 1024
    media_max_image_bytes: int = 20 * 1024 * 1024
    media_max_video_bytes: int = 250 * 1024 * 1024
    database_path: Path = Path("data/nexus.db")
    database_url: str | None = None
    project_root: Path = Path(".")
    mcp_servers: str = '[{"name":"openai-docs","transport":"streamable_http","endpoint":"https://developers.openai.com/mcp","read_only":true,"allowed_tools":["search_openai_docs","list_openai_docs","fetch_openai_doc","list_api_endpoints","get_openapi_spec"]}]'
    github_token: str | None = None
    github_repository: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_address: str | None = None
    smtp_starttls: bool = True
    voice_stt_provider: str = "browser"
    voice_tts_provider: str = "browser"
    voice_model: str = "base"
    automation_enabled: bool = True
    access_token: str | None = None
    demo_mode: bool = False
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    serve_frontend: bool = False
    frontend_dist_path: Path = Path("frontend/dist")


@lru_cache
def get_settings() -> Settings:
    return Settings()
