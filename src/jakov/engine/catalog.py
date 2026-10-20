"""Load post types, tones, moods and pools from the data/ directory (YAML)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, Literal

import yaml

from jakov.engine.emoji_render import TOKEN_RE
from jakov.engine.variables import BUILTIN_NAMES, placeholders

QuestionKind = Literal["text", "choice", "datetime"]
SECTIONS = ("headline", "intro", "body", "points", "closing", "cta", "action", "ps")
REQUIRED_SECTIONS = ("headline", "intro", "body", "closing", "cta")
SECTION_RE = re.compile(r"@([a-z]+)")


class CatalogError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ChoiceOption:
    value: str
    label: str
    palette: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Question:
    key: str
    prompt: str
    required: bool = True
    kind: QuestionKind = "text"
    max_len: int = 200
    options: tuple[ChoiceOption, ...] = ()


@dataclass(frozen=True, slots=True)
class ToneParts:
    """Lines per section for one tone; `points` falls back to the type's points."""

    sections: dict[str, tuple[str, ...]]

    def get(self, name: str) -> tuple[str, ...]:
        return self.sections.get(name, ())


@dataclass(frozen=True, slots=True)
class PostType:
    key: str
    title: str
    palette: tuple[str, ...]
    questions: tuple[Question, ...]
    tones: dict[str, ToneParts]
    layouts: tuple[str, ...] = ()
    points: tuple[str, ...] = ()

    @property
    def field_names(self) -> set[str]:
        return {q.key for q in self.questions}

    @property
    def datetime_fields(self) -> list[str]:
        return [q.key for q in self.questions if q.kind == "datetime"]

    def question(self, key: str) -> Question:
        return next(q for q in self.questions if q.key == key)

    def section(self, tone: str, name: str) -> tuple[str, ...]:
        lines = self.tones[tone].get(name)
        if lines:
            return lines
        if name == "points":
            return self.points
        if name == "action":
            return self.tones[tone].get("cta")
        return ()


@dataclass(frozen=True, slots=True)
class Tone:
    key: str
    title: str
    palette: tuple[str, ...]


@dataclass
class Catalog:
    data_dir: Path
    type_order: tuple[str, ...] = ("game", "sell", "romantic", "announcement", "giveaway", "custom")

    @cached_property
    def moods(self) -> dict[str, list[str]]:
        raw = self._yaml(self.data_dir / "emoji_moods.yaml")
        return {str(k): [str(c) for c in v] for k, v in raw.items()}

    @cached_property
    def tones(self) -> dict[str, Tone]:
        raw = self._yaml(self.data_dir / "tones.yaml")
        return {k: Tone(k, v["title"], tuple(v.get("palette", ()))) for k, v in raw.items()}

    @cached_property
    def types(self) -> dict[str, PostType]:
        types = {}
        for key in self.type_order:
            types[key] = self._load_type(self.data_dir / "templates" / f"{key}.yaml")
        return types

    @cached_property
    def layouts(self) -> dict[str, str]:
        raw = self._yaml(self.data_dir / "layouts.yaml")
        layouts = {str(k): str(v).strip("\n") for k, v in raw.items()}
        for name, text in layouts.items():
            unknown = set(SECTION_RE.findall(text)) - set(SECTIONS)
            if unknown:
                raise CatalogError(f"layouts.yaml/{name}: unknown sections {unknown}")
        return layouts

    @cached_property
    def pools(self) -> dict[str, list[str]]:
        pools = {}
        for path in sorted((self.data_dir / "pools").glob("*.yaml")):
            items = self._yaml(path)
            if not isinstance(items, list) or not items:
                raise CatalogError(f"{path.name}: pool must be a non-empty list")
            pools[path.stem.removesuffix("s")] = [str(i) for i in items]
        return pools

    @cached_property
    def _starter(self) -> dict[str, list[str]]:
        raw = self._yaml(self.data_dir / "starter_packs.yaml")
        return {k: [str(p) for p in raw.get(k) or []] for k in ("showcase", "base", "retired")}

    @cached_property
    def starter_packs(self) -> list[str]:
        """All packs imported automatically: base packs first."""
        return self._starter["base"] + self._starter["showcase"]

    @cached_property
    def retired_packs(self) -> list[str]:
        """Packs to remove from the library and never import again."""
        return self._starter["retired"]

    @cached_property
    def base_packs(self) -> list[str]:
        """Packs that mirror standard emoji: menu fallback, last resort in posts."""
        return self._starter["base"]

    @cached_property
    def ui_icons(self) -> dict[str, str]:
        """Curated menu icons: UI emoji -> custom_emoji_id."""
        raw = self._yaml(self.data_dir / "ui_icons.yaml").get("icons") or {}
        icons = {str(k): str(v["id"]) for k, v in raw.items()}
        if not all(i.isdigit() for i in icons.values()):
            raise CatalogError("ui_icons.yaml: every id must be a numeric custom_emoji_id")
        return icons

    def _load_type(self, path: Path) -> PostType:
        raw = self._yaml(path)
        questions = tuple(
            Question(
                key=q["key"], prompt=q["prompt"], required=q.get("required", True),
                kind=q.get("kind", "text"), max_len=q.get("max_len", 200),
                options=tuple(ChoiceOption(o["value"], o["label"], tuple(o.get("palette", ())))
                              for o in q.get("options", ())),
            )
            for q in raw["questions"]
        )
        tones = {
            tone: ToneParts({name: tuple(str(x) for x in lines)
                             for name, lines in (parts or {}).items()})
            for tone, parts in raw["tones"].items()
        }
        post_type = PostType(
            raw["type"], raw["title"], tuple(raw.get("palette", ())), questions, tones,
            layouts=tuple(raw.get("layouts") or self.layouts),
            points=tuple(str(p) for p in raw.get("points") or ()),
        )
        self._validate(post_type, path.name)
        return post_type

    def _validate(self, post_type: PostType, name: str) -> None:
        missing = set(self.tones) - set(post_type.tones)
        if missing:
            raise CatalogError(f"{name}: missing tones {sorted(missing)}")
        unknown_layouts = set(post_type.layouts) - set(self.layouts)
        if unknown_layouts:
            raise CatalogError(f"{name}: unknown layouts {sorted(unknown_layouts)}")
        allowed = post_type.field_names | BUILTIN_NAMES
        for tone, parts in post_type.tones.items():
            extra = set(parts.sections) - set(SECTIONS)
            if extra:
                raise CatalogError(f"{name}/{tone}: unknown sections {sorted(extra)}")
            for section in REQUIRED_SECTIONS:
                if not parts.get(section):
                    raise CatalogError(f"{name}/{tone}: no {section} lines")
            for section in SECTIONS:
                for line in post_type.section(tone, section):
                    unknown = placeholders(line) - allowed - {"emoji"}
                    if unknown:
                        raise CatalogError(f"{name}/{tone}: unknown placeholders {unknown}")
                    bad_moods = {m for m in TOKEN_RE.findall(line) if m} - set(self.moods)
                    if bad_moods:
                        raise CatalogError(f"{name}/{tone}: unknown emoji moods {bad_moods}")
        for mood in post_type.palette:
            if mood not in self.moods:
                raise CatalogError(f"{name}: unknown palette mood {mood!r}")

    @staticmethod
    def _yaml(path: Path) -> Any:
        try:
            with path.open(encoding="utf-8") as fh:
                return yaml.safe_load(fh)
        except (OSError, yaml.YAMLError) as exc:
            raise CatalogError(f"Can't load {path}: {exc}") from exc
