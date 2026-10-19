"""Text generators produce post *templates* (spintax + {placeholders} + {emoji} tokens).

The template engine below needs no AI. An optional AI generator (Phase 6) implements the
same interface; nothing else depends on it.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Protocol

from jakov.engine.catalog import Catalog


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    post_type: str
    tone: str
    answers: dict[str, str] = field(default_factory=dict)


class TextGenerator(Protocol):
    name: str

    async def generate(
        self, request: GenerationRequest, count: int, exclude: frozenset[str] = frozenset()
    ) -> list[str]: ...


class TemplateGenerator:
    """Combines a hook, body and call to action from the YAML catalog."""

    name = "templates"

    def __init__(self, catalog: Catalog, rng: random.Random | None = None) -> None:
        self.catalog = catalog
        self.rng = rng or random.Random()

    async def generate(
        self, request: GenerationRequest, count: int, exclude: frozenset[str] = frozenset()
    ) -> list[str]:
        parts = self.catalog.types[request.post_type].tones[request.tone]
        combos = [
            "\n\n".join((hook, body, cta))
            for hook in parts.hooks for body in parts.bodies for cta in parts.ctas
        ]
        fresh = [c for c in combos if c not in exclude] or combos
        self.rng.shuffle(fresh)
        # Prefer variations that don't share a hook, so the three previews feel different.
        picked: list[str] = []
        used_hooks: set[str] = set()
        for combo in fresh:
            hook = combo.split("\n\n", 1)[0]
            if hook not in used_hooks:
                picked.append(combo)
                used_hooks.add(hook)
            if len(picked) == count:
                return picked
        for combo in fresh:
            if combo not in picked:
                picked.append(combo)
            if len(picked) == count:
                break
        return picked
