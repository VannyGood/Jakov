"""AI writer: a local Ollama model writes the copy; templates fill in whenever it can't."""

from __future__ import annotations

import asyncio
import random
from time import monotonic

from jakov.engine import llm_writer
from jakov.engine.catalog import Catalog
from jakov.engine.text_generator import GeneratedText, GenerationRequest, TemplateGenerator
from jakov.logging_setup import get_logger
from jakov.services.llm.ollama import LlmError, OllamaClient

log = get_logger(__name__)
_HEALTH_TTL = 60.0


class LlmGenerator:
    name = "llm"

    def __init__(self, client: OllamaClient, catalog: Catalog, *, temperature: float = 0.9,
                 rng: random.Random | None = None) -> None:
        self.client = client
        self.catalog = catalog
        self.temperature = temperature
        self.rng = rng or random.Random()
        self.fallback = TemplateGenerator(catalog, self.rng)
        self._healthy: bool | None = None
        self._checked_at = 0.0

    @property
    def model(self) -> str:
        return self.client.model

    async def is_available(self, *, refresh: bool = False) -> bool:
        if refresh or self._healthy is None or monotonic() - self._checked_at > _HEALTH_TTL:
            self._healthy = await self.client.available()
            self._checked_at = monotonic()
        return bool(self._healthy)

    async def _one(self, request: GenerationRequest, style: str, layout: str) -> str | None:
        post_type = self.catalog.types[request.post_type]
        brief = llm_writer.make_brief(post_type, request.tone, request.answers,
                                      request.has_buttons)
        system, user = llm_writer.prompt(brief, style)
        try:
            raw = await self.client.chat_json(system, user, llm_writer.SCHEMA,
                                              seed=self.rng.randrange(1, 2**31),
                                              temperature=self.temperature)
        except LlmError as exc:
            log.warning("llm_failed", error=str(exc))
            self._healthy = None if "unreachable" in str(exc) else self._healthy
            return None
        sections = llm_writer.clean(raw, brief)
        if sections is None:
            log.info("llm_output_rejected", type=request.post_type)
            return None
        return llm_writer.compose(sections, layout, post_type, request.answers)

    async def generate(self, request: GenerationRequest, count: int,
                       exclude: frozenset[str] = frozenset()) -> list[GeneratedText]:
        written: list[GeneratedText] = []
        if await self.is_available():
            styles = list(llm_writer.STYLES)
            layouts = list(llm_writer.LAYOUTS)
            self.rng.shuffle(styles)
            self.rng.shuffle(layouts)
            results = await asyncio.gather(*(
                self._one(request, styles[i % len(styles)], layouts[i % len(layouts)])
                for i in range(count)))
            written = [GeneratedText(t, "llm") for t in results if t and t not in exclude]
        missing = count - len(written)
        if missing > 0:  # AI offline or some outputs rejected: templates fill the gap
            used = exclude | {g.template for g in written}
            written += await self.fallback.generate(request, missing, used)
        return written
