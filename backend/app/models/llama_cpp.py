from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from backend.app.models.provider import ChatModelResponse


class LlamaCppModel:
    provider_name = "llama_cpp"

    def __init__(self, executable: Path, model_path: Path, context_size: int = 4096, threads: int = 4):
        self.executable = executable.resolve()
        self.model_path = model_path.resolve()
        self.model = self.model_path.name
        if not self.executable.is_absolute() or not self.executable.is_file():
            raise ValueError("NEXUS_LLAMA_CPP_EXECUTABLE must be an existing absolute file")
        if not self.model_path.is_absolute() or not self.model_path.is_file() or self.model_path.suffix.lower() != ".gguf":
            raise ValueError("NEXUS_LLAMA_CPP_MODEL_PATH must be an existing absolute .gguf file")
        if not 512 <= context_size <= 32768 or not 1 <= threads <= 64:
            raise ValueError("llama.cpp context or thread configuration is outside safe bounds")
        self.context_size, self.threads = context_size, threads

    async def chat(self, messages: list[dict[str, Any]], tools: list[object]) -> ChatModelResponse:
        if tools:
            raise RuntimeError("Direct llama.cpp provider does not expose tool calling")
        prompt = self._prompt(messages)
        if len(prompt) > 24000:
            raise ValueError("llama.cpp prompt exceeds the local provider limit")
        args = [str(self.executable), "--model", str(self.model_path), "--prompt", prompt, "--n-predict", "512", "--ctx-size", str(self.context_size), "--threads", str(self.threads), "--no-display-prompt", "--no-show-timings", "--simple-io", "--no-conversation"]
        process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
        except TimeoutError:
            process.kill()
            await process.communicate()
            raise RuntimeError("llama.cpp generation timed out")
        if process.returncode:
            raise RuntimeError(f"llama.cpp exited with code {process.returncode}: {stderr.decode('utf-8', 'replace')[:300]}")
        return ChatModelResponse(content=stdout.decode("utf-8", "replace").strip())

    @staticmethod
    def _prompt(messages: list[dict[str, Any]]) -> str:
        rendered = []
        for message in messages:
            content = message.get("content", "")
            if not isinstance(content, str):
                continue
            role = {"system": "System", "assistant": "Assistant", "user": "User"}.get(message.get("role"), "User")
            rendered.append(f"{role}: {content}")
        return "\n\n".join(rendered) + "\n\nAssistant:"
