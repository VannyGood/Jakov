"""Minimal async client for a local Ollama server (structured JSON chat)."""

from __future__ import annotations

import json
from typing import Any

import aiohttp

from jakov.logging_setup import get_logger

log = get_logger(__name__)


class LlmError(Exception):
    """The model is unreachable, too slow, or returned unusable output."""


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout_s: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = aiohttp.ClientTimeout(total=timeout_s)

    async def available(self) -> bool:
        """True when the server answers and the model is pulled."""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as http, \
                    http.get(f"{self.base_url}/api/tags") as resp:
                if resp.status != 200:
                    return False
                tags = await resp.json()
        except (aiohttp.ClientError, TimeoutError, json.JSONDecodeError):
            return False
        names = {m.get("name", "") for m in tags.get("models", [])}
        return self.model in names or f"{self.model}:latest" in names

    async def chat_json(self, system: str, user: str, schema: dict[str, Any], *,
                        seed: int, temperature: float, max_tokens: int = 400
                        ) -> dict[str, Any]:
        body = {
            "model": self.model,
            "stream": False,
            "format": schema,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "options": {"temperature": temperature, "top_p": 0.95, "seed": seed,
                        "num_predict": max_tokens},
        }
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as http, \
                    http.post(f"{self.base_url}/api/chat", json=body) as resp:
                if resp.status != 200:
                    raise LlmError(f"Ollama answered {resp.status}: {(await resp.text())[:200]}")
                payload = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise LlmError(f"Ollama unreachable or too slow: {type(exc).__name__}") from exc
        content = payload.get("message", {}).get("content", "")
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LlmError("The model returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise LlmError("The model returned something other than an object")
        return data
