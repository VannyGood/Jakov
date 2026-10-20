"""Text generators produce post *templates* (spintax + {placeholders} + {emoji} tokens).

The template engine below needs no AI. An optional AI generator (Phase 6) implements the
same interface; nothing else depends on it.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Protocol

from jakov.engine.catalog import SECTION_RE, Catalog
from jakov.engine.variables import placeholders


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    post_type: str
    tone: str
    answers: dict[str, str] = field(default_factory=dict)
    has_buttons: bool = False


@dataclass(frozen=True, slots=True)
class GeneratedText:
    """A post template plus who wrote it: "llm" (AI writer) or "template" (built-in)."""

    template: str
    source: str = "template"


# Sections a layout may use without the tone providing them (the line is dropped).
OPTIONAL_SECTIONS = frozenset({"ps", "points"})


class TextGenerator(Protocol):
    name: str

    async def generate(
        self, request: GenerationRequest, count: int, exclude: frozenset[str] = frozenset()
    ) -> list[GeneratedText]: ...


class TemplateGenerator:
    """Composes posts from layouts (data/layouts.yaml) and per-tone sections."""

    name = "templates"

    def __init__(self, catalog: Catalog, rng: random.Random | None = None) -> None:
        self.catalog = catalog
        self.rng = rng or random.Random()

    def required_fields(self, post_type: str) -> set[str]:
        """Answers every variation must mention (choices only steer the wording)."""
        return {q.key for q in self.catalog.types[post_type].questions
                if q.required and q.kind != "choice"}

    def usable_layouts(self, post_type: str, tone: str) -> list[str]:
        pt = self.catalog.types[post_type]
        return [name for name in pt.layouts
                if all(pt.section(tone, s) for s in SECTION_RE.findall(self.catalog.layouts[name])
                       if s not in OPTIONAL_SECTIONS)]

    def compose(self, post_type: str, tone: str, layout: str) -> str:
        pt = self.catalog.types[post_type]
        picks: dict[str, str] = {}
        for section in set(SECTION_RE.findall(self.catalog.layouts[layout])):
            lines = pt.section(tone, section)
            if section == "points":
                picks[section] = "\n".join(lines)
            else:
                picks[section] = self.rng.choice(lines) if lines else ""
        out: list[str] = []
        for line in self.catalog.layouts[layout].split("\n"):
            used = SECTION_RE.findall(line)
            if used and not any(picks[s].strip() for s in used):
                continue
            out.append(SECTION_RE.sub(lambda m: picks[m.group(1)], line))
        return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()

    async def generate(
        self, request: GenerationRequest, count: int, exclude: frozenset[str] = frozenset()
    ) -> list[GeneratedText]:
        return [GeneratedText(t) for t in self.templates(request, count, exclude)]

    def templates(self, request: GenerationRequest, count: int,
                  exclude: frozenset[str] = frozenset()) -> list[str]:
        layouts = self.usable_layouts(request.post_type, request.tone)
        if not layouts:
            raise ValueError(f"no usable layout for {request.post_type}/{request.tone}")
        self.rng.shuffle(layouts)
        required = self.required_fields(request.post_type)
        picked: list[str] = []
        first_lines: set[str] = set()
        attempts = 0
        # Cycle through layouts so consecutive variations look structurally different.
        while len(picked) < count and attempts < count * 60:
            layout = layouts[attempts % len(layouts)]
            attempts += 1
            text = self.compose(request.post_type, request.tone, layout)
            first = text.split("\n", 1)[0]
            if text in exclude or text in picked or not required <= placeholders(text):
                continue
            if first in first_lines and attempts < count * 15:
                continue
            picked.append(text)
            first_lines.add(first)
        return picked
