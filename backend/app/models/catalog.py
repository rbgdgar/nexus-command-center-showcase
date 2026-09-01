from __future__ import annotations

from dataclasses import asdict, dataclass

import httpx

from backend.app.core.config import Settings
from backend.app.models.gemini import GeminiModel
from backend.app.models.ollama import OllamaModel
from backend.app.models.llama_cpp import LlamaCppModel
from backend.app.models.openai_compatible import OpenAICompatibleModel
from backend.app.models.router import FallbackChatModel


@dataclass(frozen=True)
class ModelProfile:
    provider: str
    model: str
    label: str
    cost_tier: str
    capabilities: tuple[str, ...]
    configured: bool = False
    allowed: bool = True
    setup_url: str = ""
    notes: str = ""

    @property
    def id(self) -> str:
        return f"{self.provider}:{self.model}"

    def public(self) -> dict:
        state = "ready" if self.configured and self.allowed else (
            "blocked" if self.configured else "setup_required"
        )
        return {
            "id": self.id,
            **asdict(self),
            "capabilities": list(self.capabilities),
            "state": state,
        }


class ModelRegistry:
    def __init__(self, settings: Settings):
        self.settings = settings

    def profiles(self) -> list[ModelProfile]:
        gemini_ready = bool(self.settings.gemini_api_key)
        openrouter_ready = bool(self.settings.openrouter_api_key)
        groq_ready = bool(self.settings.groq_api_key)
        openai_ready = bool(self.settings.openai_api_key)
        paid_allowed = self.settings.allow_paid_models
        profiles = [
            ModelProfile("gemini", "gemini-3.7-flash", "Gemini 3.7 Flash", "free_tier", ("text", "vision", "tools"), gemini_ready, True, "https://aistudio.google.com/apikey", "Primary production model"),
            ModelProfile("gemini", "gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", "free_tier", ("text", "vision", "tools"), gemini_ready, True, "https://aistudio.google.com/apikey", "High-throughput fallback"),
            ModelProfile("gemini", "gemini-3.1-flash-lite", "Gemini 3.1 Flash-Lite", "free_tier", ("text", "vision", "tools"), gemini_ready, True, "https://aistudio.google.com/apikey", "Low-latency fallback"),
            ModelProfile("openrouter", "openrouter/free", "OpenRouter Free Router", "free", ("text", "vision", "tools"), openrouter_ready, True, "https://openrouter.ai/settings/keys", "Routes across currently available free models"),
            ModelProfile("groq", "openai/gpt-oss-120b", "GPT-OSS 120B on Groq", "free_tier", ("text", "tools"), groq_ready, True, "https://console.groq.com/keys", "Hosted free-plan route"),
            ModelProfile("groq", "qwen/qwen3.6-27b", "Qwen 3.6 27B on Groq", "free_tier", ("text", "tools"), groq_ready, True, "https://console.groq.com/keys", "Hosted Qwen fallback"),
            ModelProfile("openai", "gpt-5.6-sol", "GPT-5.6 Sol", "paid", ("text", "vision", "tools"), openai_ready, paid_allowed, "https://platform.openai.com/api-keys", "Frontier reasoning and coding"),
            ModelProfile("openai", "gpt-5.6-terra", "GPT-5.6 Terra", "paid", ("text", "vision", "tools"), openai_ready, paid_allowed, "https://platform.openai.com/api-keys", "Balanced intelligence and cost"),
            ModelProfile("openai", "gpt-5.6-luna", "GPT-5.6 Luna", "paid", ("text", "vision", "tools"), openai_ready, paid_allowed, "https://platform.openai.com/api-keys", "High-volume cost-sensitive workloads"),
        ]
        ollama_ready = self.settings.model_provider == "ollama" or self.settings.ollama_enabled
        installed_ollama = self._installed_ollama_models() if ollama_ready else set()
        local_models = [
            ("qwen3.8:27b", "Qwen 3.8 27B", "18 GB local multimodal release"),
            ("qwen3.8-flash-next:125b-mlx", "Qwen 3.8 Flash-Next 125B", "113 GB experimental MLX release; hardware-specific"),
        ]
        if self.settings.model_name not in {item[0] for item in local_models}:
            local_models.insert(0, (
                self.settings.model_name,
                f"Ollama {self.settings.model_name}",
                "Configured local model",
            ))
        for model_name, label, notes in local_models:
            capabilities = ("text", "vision", "tools") if model_name.startswith("qwen3.8") else ("text", "tools")
            profiles.append(ModelProfile(
                "ollama", model_name, label, "local", capabilities,
                model_name in installed_ollama,
                True, "https://ollama.com/library/qwen3.8", notes,
            ))
        if self.settings.compatible_base_url and self.settings.compatible_model_name:
            cost_tier = self.settings.compatible_cost_tier.strip().lower()
            if cost_tier not in {"local", "free", "free_tier", "paid", "unknown"}:
                cost_tier = "unknown"
            profiles.append(ModelProfile(
                "compatible",
                self.settings.compatible_model_name,
                self.settings.compatible_label,
                cost_tier,
                ("text", "tools"),
                True,
                cost_tier not in {"paid", "unknown"} or paid_allowed,
            ))
        llama_ready = self._llama_cpp_ready()
        llama_name = self.settings.llama_cpp_model_path.name if self.settings.llama_cpp_model_path else "configured.gguf"
        profiles.append(ModelProfile("llama_cpp", llama_name, f"llama.cpp {llama_name}", "local", ("text",), llama_ready, True, "https://github.com/ggml-org/llama.cpp", "Direct local GGUF inference; tools and vision are disabled"))
        return profiles

    def _llama_cpp_ready(self) -> bool:
        executable, model = self.settings.llama_cpp_executable, self.settings.llama_cpp_model_path
        return bool(self.settings.llama_cpp_enabled and executable and model and executable.is_absolute() and executable.is_file() and model.is_absolute() and model.is_file() and model.suffix.lower() == ".gguf")

    def public_catalog(self) -> dict:
        return {
            "default_provider": self.settings.model_provider,
            "default_model": self._default_model(self.settings.model_provider),
            "free_first": True,
            "paid_models_allowed": self.settings.allow_paid_models,
            "models": [profile.public() for profile in self.profiles()],
        }

    def operational_report(self) -> dict:
        profiles = [profile.public() for profile in self.profiles()]
        providers = []
        for provider in sorted({item["provider"] for item in profiles}):
            models = [item for item in profiles if item["provider"] == provider]
            ready = [item for item in models if item["state"] == "ready"]
            blocked = [item for item in models if item["state"] == "blocked"]
            state = "ready" if ready else ("blocked" if blocked else "setup_required")
            providers.append({
                "provider": provider,
                "state": state,
                "ready_models": len(ready),
                "model_count": len(models),
                "setup_url": models[0]["setup_url"],
            })
        return {"providers": providers, "models": profiles}

    def _installed_ollama_models(self) -> set[str]:
        try:
            response = httpx.get(
                f"{self.settings.ollama_url.rstrip('/')}/api/tags",
                timeout=0.5,
            )
            response.raise_for_status()
            return {
                item["name"]
                for item in response.json().get("models", [])
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            }
        except (httpx.HTTPError, TypeError, ValueError):
            return set()

    def routed(self, provider: str | None = None, model: str | None = None):
        selected_provider = (provider or self.settings.model_provider).strip().lower()
        selected_model = model or self._default_model(selected_provider)
        primary_profile = self._profile(selected_provider, selected_model)
        clients = [self._client(primary_profile)]
        if provider is None and self.settings.model_fallback_enabled:
            for fallback_provider in self.settings.model_fallbacks.split(","):
                fallback_provider = fallback_provider.strip().lower()
                if not fallback_provider or fallback_provider == selected_provider:
                    continue
                try:
                    profile = self._profile(fallback_provider, self._default_model(fallback_provider))
                except ValueError:
                    continue
                if profile.configured and profile.allowed:
                    clients.append(self._client(profile))
        return clients[0] if len(clients) == 1 else FallbackChatModel(clients)

    def provider_ready(self, provider: str | None = None) -> bool:
        selected = provider or self.settings.model_provider
        try:
            profile = self._profile(selected, self._default_model(selected))
        except ValueError:
            return False
        return profile.configured and profile.allowed

    def select_profile(self, provider: str | None, model: str | None) -> ModelProfile:
        selected_provider = (provider or self.settings.model_provider).strip().lower()
        selected_model = model or self._default_model(selected_provider)
        return self._profile(selected_provider, selected_model)

    def _profile(self, provider: str, model: str) -> ModelProfile:
        profile = next(
            (item for item in self.profiles() if item.provider == provider and item.model == model),
            None,
        )
        if not profile:
            raise ValueError(f"Model is not in the NEXUS catalog: {provider}:{model}")
        if not profile.configured:
            raise ValueError(f"Provider is not configured: {provider}")
        if not profile.allowed:
            raise ValueError("Paid or unknown-cost models are disabled by policy")
        return profile

    def _client(self, profile: ModelProfile):
        if profile.provider == "gemini":
            return GeminiModel(
                self.settings.gemini_api_key or "",
                profile.model,
                self.settings.gemini_base_url,
            )
        if profile.provider == "ollama":
            return OllamaModel(profile.model, self.settings.ollama_url)
        if profile.provider == "llama_cpp":
            return LlamaCppModel(self.settings.llama_cpp_executable, self.settings.llama_cpp_model_path, self.settings.llama_cpp_context_size, self.settings.llama_cpp_threads)
        configurations = {
            "openrouter": (
                self.settings.openrouter_base_url,
                self.settings.openrouter_api_key,
                {"HTTP-Referer": self.settings.public_url, "X-OpenRouter-Title": "NEXUS"},
            ),
            "groq": (self.settings.groq_base_url, self.settings.groq_api_key, {}),
            "openai": (self.settings.openai_base_url, self.settings.openai_api_key, {}),
            "compatible": (
                self.settings.compatible_base_url or "",
                self.settings.compatible_api_key,
                {},
            ),
        }
        base_url, api_key, headers = configurations[profile.provider]
        return OpenAICompatibleModel(
            profile.provider, profile.model, base_url, api_key, headers=headers
        )

    def _default_model(self, provider: str) -> str:
        defaults = {
            "gemini": self.settings.gemini_model_name,
            "ollama": self.settings.model_name,
            "openrouter": self.settings.openrouter_model_name,
            "groq": self.settings.groq_model_name,
            "openai": self.settings.openai_model_name,
            "compatible": self.settings.compatible_model_name or "",
            "llama_cpp": self.settings.llama_cpp_model_path.name if self.settings.llama_cpp_model_path else "configured.gguf",
        }
        if provider not in defaults:
            raise ValueError(f"Unsupported model provider: {provider}")
        return defaults[provider]
