"""Shared application objects injected into handlers as `ctx`."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass, field
from time import monotonic
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jakov.config import Settings
from jakov.engine.catalog import Catalog
from jakov.engine.text_generator import TextGenerator
from jakov.services.emoji_capability import EmojiProbe
from jakov.services.emoji_library import EmojiLibrary
from jakov.services.send_queue import SendQueue
from jakov.services.ui_emoji import UiEmojiService

if TYPE_CHECKING:
    from jakov.services.scheduler import Scheduler


@dataclass(slots=True)
class AppContext:
    settings: Settings
    sessions: async_sessionmaker[AsyncSession]
    emoji_probe: EmojiProbe
    catalog: Catalog
    library: EmojiLibrary
    ui: UiEmojiService
    generator: TextGenerator
    queue: SendQueue = field(default_factory=SendQueue)
    scheduler: Scheduler | None = None
    background: set[asyncio.Task[Any]] = field(default_factory=set)
    started_at: float = field(default_factory=monotonic)
    updates_handled: int = 0

    @property
    def owner_id(self) -> int:
        return self.settings.primary_owner_id

    @property
    def admin_ids(self) -> set[int]:
        return set(self.settings.admin_ids)

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.admin_ids

    def spawn(self, coro: Coroutine[Any, Any, Any]) -> None:
        """Run a background job, keeping a reference so it isn't garbage-collected."""
        task = asyncio.create_task(coro)
        self.background.add(task)
        task.add_done_callback(self.background.discard)

    async def reload_emoji(self) -> None:
        """Call after committing library or UI-preference changes."""
        await self.library.reload(self.sessions, self.owner_id)
        await self.ui.load(self.sessions, self.owner_id)


def build_context(settings: Settings, sessions: async_sessionmaker[AsyncSession]) -> AppContext:
    from jakov.engine.text_generator import TemplateGenerator
    from jakov.services.llm.ollama import OllamaClient
    from jakov.services.llm_generator import LlmGenerator

    catalog = Catalog(settings.data_dir)
    # Fail fast on broken data files.
    _ = catalog.types, catalog.tones, catalog.pools, catalog.moods, catalog.ui_icons
    base = catalog.base_packs
    library = EmojiLibrary(catalog.moods, default_ui_pack=base[0] if base else None,
                           ui_icons=catalog.ui_icons, base_packs=frozenset(base))
    return AppContext(
        settings=settings,
        sessions=sessions,
        emoji_probe=EmojiProbe(settings.emoji_test_pack),
        catalog=catalog,
        library=library,
        ui=UiEmojiService(library, set(settings.admin_ids)),
        generator=LlmGenerator(
            OllamaClient(settings.ollama_url, settings.ollama_model, settings.llm_timeout_s),
            catalog, temperature=settings.llm_temperature)
        if settings.llm_enabled else TemplateGenerator(catalog),
    )
