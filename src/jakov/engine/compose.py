"""The render pipeline: template -> spintax -> variables -> emoji -> HTML ready to send."""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass

from jakov.engine.emoji_render import EmojiPicker, render_emoji_tokens
from jakov.engine.spintax import spin
from jakov.engine.variables import BUILTIN_NAMES, fill, placeholders


@dataclass(frozen=True, slots=True)
class RenderInput:
    values: Mapping[str, str]
    field_names: frozenset[str]

    @property
    def known(self) -> set[str]:
        return set(self.field_names) | BUILTIN_NAMES


def resolve_spintax(template: str, rng: random.Random) -> str:
    return spin(template, rng)


def render(resolved: str, data: RenderInput, picker: EmojiPicker) -> str:
    """`resolved` is spun text with placeholders and emoji tokens still in it."""
    filled = fill(resolved, data.values, data.known)
    return render_emoji_tokens(filled, picker)


def needed_pools(text: str, pools: Mapping[str, object]) -> list[str]:
    return [name for name in placeholders(text) if name in pools]
