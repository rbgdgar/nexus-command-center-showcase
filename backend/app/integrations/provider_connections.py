from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken

from backend.app.core.config import Settings
from backend.app.database import database_connection


@dataclass(frozen=True)
class ProviderDefinition:
    provider: str
    label: str
    key_setting: str
    base_url_setting: str
    model_setting: str | None
    setup_url: str
    capabilities: tuple[str, ...]
    models: tuple[str, ...]
    test_path: str
    gemini_auth: bool = False
    custom_endpoint: bool = False


PROVIDERS = {
    item.provider: item
    for item in (
        ProviderDefinition(
            "gemini", "Google Gemini", "gemini_api_key", "gemini_base_url",
            "gemini_model_name", "https://aistudio.google.com/apikey",
            ("text", "vision", "tools"),
            ("gemini-3.7-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"),
            "/models?pageSize=1", gemini_auth=True,
        ),
        ProviderDefinition(
            "openrouter", "OpenRouter", "openrouter_api_key", "openrouter_base_url",
            "openrouter_model_name", "https://openrouter.ai/settings/keys",
            ("text", "vision", "tools"), ("openrouter/free",), "/key",
        ),
        ProviderDefinition(
            "groq", "Groq", "groq_api_key", "groq_base_url",
            "groq_model_name", "https://console.groq.com/keys",
            ("text", "tools"),
            ("openai/gpt-oss-120b", "qwen/qwen3.6-27b"), "/models",
        ),
        ProviderDefinition(
            "openai", "OpenAI", "openai_api_key", "openai_base_url",
            "openai_model_name", "https://platform.openai.com/api-keys",
            ("text", "vision", "tools", "media"),
            ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"), "/models",
        ),
        ProviderDefinition(
            "pollinations", "Pollinations", "pollinations_api_key",
            "pollinations_base_url", None, "https://enter.pollinations.ai",
            ("image", "video"), (), "/account/key",
        ),
        ProviderDefinition(
            "compatible", "Compatible API", "compatible_api_key",
            "compatible_base_url", "compatible_model_name", "",
            ("text", "tools"), (), "/models", custom_endpoint=True,
        ),
    )
}


class ProviderConnectionService:
    def __init__(
        self,
        settings: Settings,
        database_path=None,
        database_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self.settings = settings
        self.database_path = database_path
        self.database_url = database_url
        self.client = client
        self._session: dict[str, dict[str, str]] = {}
        self._baseline = {
            definition.provider: self._settings_values(definition)
            for definition in PROVIDERS.values()
        }
        self._fernet = None
        if settings.provider_secret_encryption_key:
            try:
                self._fernet = Fernet(
                    settings.provider_secret_encryption_key.strip().encode("ascii")
                )
            except (ValueError, UnicodeEncodeError) as error:
                raise ValueError(
                    "NEXUS_PROVIDER_SECRET_ENCRYPTION_KEY must be a valid Fernet key"
                ) from error

    def initialize(self):
        with self._connection() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS provider_connections (
                    provider TEXT PRIMARY KEY,
                    encrypted_key TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    model TEXT,
                    verified_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
        self.apply_to_settings()

    @property
    def persistent_available(self) -> bool:
        return self._fernet is not None

    def public_status(self) -> dict[str, Any]:
        return {
            "persistent_available": self.persistent_available,
            "write_enabled": bool(self.settings.access_token),
            "providers": [self._public_provider(item) for item in PROVIDERS.values()],
        }

    async def connect(
        self,
        provider: str,
        api_key: str,
        model: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        definition = self._definition(provider)
        secret = api_key.strip()
        if not 8 <= len(secret) <= 4096:
            raise ValueError("API key must contain 8 to 4,096 characters")
        selected_model = self._validated_model(definition, model)
        selected_base_url = self._validated_base_url(definition, base_url)
        await self._verify(definition, secret, selected_base_url)
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "api_key": secret,
            "base_url": selected_base_url,
            "model": selected_model or "",
            "verified_at": now,
        }
        if self._fernet:
            encrypted = self._fernet.encrypt(secret.encode("utf-8")).decode("ascii")
            with self._connection() as connection:
                connection.execute(
                    "DELETE FROM provider_connections WHERE provider = ?",
                    (definition.provider,),
                )
                connection.execute(
                    """INSERT INTO provider_connections
                       (provider, encrypted_key, base_url, model, verified_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        definition.provider, encrypted, selected_base_url,
                        selected_model, now, now,
                    ),
                )
            self._session.pop(definition.provider, None)
        else:
            self._session[definition.provider] = record
        self._apply(definition, record)
        return self._public_provider(definition)

    def disconnect(self, provider: str) -> dict[str, Any]:
        definition = self._definition(provider)
        self._session.pop(definition.provider, None)
        with self._connection() as connection:
            connection.execute(
                "DELETE FROM provider_connections WHERE provider = ?",
                (definition.provider,),
            )
        self._apply(definition, self._baseline[definition.provider])
        return self._public_provider(definition)

    def resolve_key(self, provider: str) -> str | None:
        definition = self._definition(provider)
        record, _ = self._active_record(definition)
        return record.get("api_key") or None

    def apply_to_settings(self):
        for definition in PROVIDERS.values():
            record, _ = self._active_record(definition)
            self._apply(definition, record)

    def _public_provider(self, definition: ProviderDefinition) -> dict[str, Any]:
        record, mode = self._active_record(definition)
        configured = bool(record.get("api_key"))
        return {
            "provider": definition.provider,
            "label": definition.label,
            "configured": configured,
            "mode": mode,
            "secret": "configured" if configured else "not_configured",
            "base_url": record.get("base_url") or self._baseline[definition.provider]["base_url"],
            "model": record.get("model") or self._baseline[definition.provider]["model"],
            "models": list(definition.models),
            "capabilities": list(definition.capabilities),
            "setup_url": definition.setup_url,
            "custom_endpoint": definition.custom_endpoint,
            "verified_at": record.get("verified_at"),
            "disconnectable": mode in {"encrypted", "session"},
        }

    def _active_record(self, definition: ProviderDefinition) -> tuple[dict[str, str], str]:
        if definition.provider in self._session:
            return self._session[definition.provider], "session"
        stored = self._stored_record(definition.provider)
        if stored:
            return stored, "encrypted"
        baseline = self._baseline[definition.provider]
        return baseline, "environment" if baseline.get("api_key") else "not_configured"

    def _stored_record(self, provider: str) -> dict[str, str] | None:
        if not self._fernet:
            return None
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM provider_connections WHERE provider = ?", (provider,)
            ).fetchone()
        if not row:
            return None
        try:
            api_key = self._fernet.decrypt(row["encrypted_key"].encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError) as error:
            raise RuntimeError(f"Stored {provider} credential cannot be decrypted") from error
        return {
            "api_key": api_key,
            "base_url": row["base_url"],
            "model": row["model"] or "",
            "verified_at": row["verified_at"],
        }

    async def _verify(
        self, definition: ProviderDefinition, api_key: str, base_url: str
    ):
        headers = {"Accept": "application/json"}
        if definition.gemini_auth:
            headers["x-goog-api-key"] = api_key
        else:
            headers["Authorization"] = f"Bearer {api_key}"
        endpoint = f"{base_url.rstrip('/')}{definition.test_path}"
        try:
            if self.client:
                response = await self.client.get(endpoint, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
                    response = await client.get(endpoint, headers=headers)
            response.raise_for_status()
            if definition.provider == "pollinations" and not response.json().get("valid"):
                raise ValueError("Pollinations reported that the key is not active")
        except httpx.HTTPStatusError as error:
            raise ValueError(
                f"Provider rejected the credential (HTTP {error.response.status_code})"
            ) from error
        except httpx.RequestError as error:
            raise RuntimeError("Provider connection test could not reach the endpoint") from error
        except (TypeError, ValueError) as error:
            if isinstance(error, ValueError) and str(error).startswith("Pollinations"):
                raise
            raise RuntimeError("Provider returned an invalid connection-test response") from error

    def _validated_model(
        self, definition: ProviderDefinition, model: str | None
    ) -> str | None:
        selected = (model or self._baseline[definition.provider]["model"] or "").strip()
        if definition.model_setting is None:
            return None
        if not 1 <= len(selected) <= 200:
            raise ValueError("Model name must contain 1 to 200 characters")
        if definition.models and selected not in definition.models:
            raise ValueError("Model is not allow-listed for this provider")
        return selected

    def _validated_base_url(
        self, definition: ProviderDefinition, base_url: str | None
    ) -> str:
        configured = self._baseline[definition.provider]["base_url"]
        selected = (base_url if definition.custom_endpoint else configured) or ""
        selected = selected.strip().rstrip("/")
        parsed = urlsplit(selected)
        loopback = parsed.scheme == "http" and parsed.hostname in {
            "127.0.0.1", "::1", "localhost",
        }
        allowed_hosts = {
            item.strip().lower()
            for item in self.settings.provider_allowed_hosts.split(",")
            if item.strip()
        }
        secure_allowed = (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.hostname.lower() in allowed_hosts
        )
        if definition.custom_endpoint and not (loopback or secure_allowed):
            raise ValueError(
                "Compatible API host must be loopback or listed in NEXUS_PROVIDER_ALLOWED_HOSTS"
            )
        if not definition.custom_endpoint and not (
            parsed.scheme == "https" and bool(parsed.hostname)
        ):
            raise ValueError("Provider endpoint must use HTTPS")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Provider endpoint cannot contain credentials, query, or fragment")
        return selected

    def _settings_values(self, definition: ProviderDefinition) -> dict[str, str]:
        return {
            "api_key": getattr(self.settings, definition.key_setting) or "",
            "base_url": getattr(self.settings, definition.base_url_setting) or "",
            "model": (
                getattr(self.settings, definition.model_setting) or ""
                if definition.model_setting else ""
            ),
            "verified_at": "",
        }

    def _apply(self, definition: ProviderDefinition, record: dict[str, str]):
        setattr(self.settings, definition.key_setting, record.get("api_key") or None)
        setattr(self.settings, definition.base_url_setting, record.get("base_url") or None)
        if definition.model_setting:
            setattr(self.settings, definition.model_setting, record.get("model") or None)

    @staticmethod
    def _definition(provider: str) -> ProviderDefinition:
        definition = PROVIDERS.get(provider.strip().lower())
        if not definition:
            raise ValueError("Provider is not allow-listed")
        return definition

    def _connection(self):
        return database_connection(
            database_path=self.database_path or self.settings.database_path,
            database_url=self.database_url if self.database_url is not None else self.settings.database_url,
        )
