import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend.app.models.llama_cpp import LlamaCppModel


class LlamaCppTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_fixed_argument_array_without_shell(self):
        with patch.object(Path, "is_file", return_value=True):
            model = LlamaCppModel(Path("C:/models/llama-cli.exe"), Path("C:/models/test.gguf"))
        with patch("backend.app.models.llama_cpp.asyncio.create_subprocess_exec") as create:
            process = create.return_value
            process.communicate = AsyncMock(return_value=(b"local answer", b""))
            process.returncode = 0
            result = await model.chat([{"role": "user", "content": "Hello"}], [])
        self.assertEqual(result.content, "local answer")
        arguments = create.call_args.args
        self.assertIn("--model", arguments)
        self.assertIn("--no-conversation", arguments)
        self.assertNotIn("shell", create.call_args.kwargs)

    async def test_tools_are_explicitly_unsupported(self):
        with patch.object(Path, "is_file", return_value=True):
            model = LlamaCppModel(Path("C:/models/llama-cli.exe"), Path("C:/models/test.gguf"))
        with self.assertRaisesRegex(RuntimeError, "tool calling"):
            await model.chat([], [object()])
