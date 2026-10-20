"""Prompting and guarding a small local LLM that writes post copy.

The model writes only the prose (headline, intro, body, closing, call to action). Facts such
as prices, dates and links are never re-typed by the model: they come from the admin's
answers as `{placeholders}` / bullet points, so they're always exact. Every section the
model returns is cleaned and checked; anything suspicious is dropped.
"""

from __future__ import annotations

import html
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from jakov.engine.catalog import PostType

SECTIONS = ("headline", "intro", "body", "closing", "cta")
REQUIRED = ("headline", "cta")
MAX_LEN = {"headline": 80, "intro": 240, "body": 340, "closing": 140, "cta": 110}

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {name: {"type": "string"} for name in SECTIONS},
    "required": list(SECTIONS),
}

TONE_GUIDE = {
    "hype": "hype: energetic, bold, exciting, a little urgent",
    "chill": "chill: relaxed, warm, easy-going, zero pressure",
    "funny": "funny: witty, playful, light-hearted humour",
    "serious": "serious: professional, clear, trustworthy",
}
STYLES = (
    "bold and punchy",
    "storytelling: paint a vivid picture",
    "benefit-focused and persuasive",
    "short, elegant and confident",
    "conversational, like talking to a friend",
)
LAYOUTS: dict[str, tuple[str, ...]] = {
    "classic": ("@headline", "", "@intro @body", "", "@points", "", "@cta"),
    "spotlight": ("@headline", "", "@intro", "", "@points", "", "@cta"),
    "story": ("@intro @body", "", "<blockquote>@closing</blockquote>", "", "@points", "",
              "@cta"),
    "signature": ("@headline", "", "@body", "", "@points", "", "<i>@closing</i>", "@cta"),
}
LABELS = {"cta": "How to join", "how": "How to enter", "for": "For", "topic": "Topic",
          "details": "Details", "message": "Main message"}

SYSTEM = """You are an expert social media copywriter for Telegram channels.
Write in English. Reply with JSON only, using exactly these keys:
headline: max 8 words, catchy, no quotes.
intro: one engaging sentence.
body: one or two sentences that build interest.
closing: a short memorable line.
cta: a short call to action, max 10 words.
Rules: use at most 2 emoji in total. No hashtags, no links, no markdown, no placeholders.
Only use facts that are given. Never invent numbers, prices, dates, rules or names."""

_EMOJI_START = re.compile(r"^[\U0001F000-\U0001FAFF☀-➿⬀-⯿]")
_BANNED = re.compile(r"https?://|www\.|t\.me/|[{}\[\]<>@#]|placeholder|shown separately",
                     re.IGNORECASE)
_NUMBER = re.compile(r"\d+")


@dataclass(frozen=True, slots=True)
class Brief:
    """What the model is told about one post."""

    type_title: str
    tone: str
    facts: tuple[tuple[str, str], ...]
    has_buttons: bool
    allowed_numbers: frozenset[str] = field(default_factory=frozenset)


def make_brief(post_type: PostType, tone: str, answers: Mapping[str, str],
               has_buttons: bool) -> Brief:
    facts: list[tuple[str, str]] = []
    for q in post_type.questions:
        value = answers.get(q.key, "").strip()
        if not value or q.kind == "datetime":
            continue  # dates are added by code, never by the model
        if q.kind == "choice":
            value = next((o.label.split(" ", 1)[-1] for o in q.options if o.value == value), value)
        facts.append((LABELS.get(q.key, q.key.replace("_", " ").capitalize()), value))
    numbers = frozenset(_NUMBER.findall(" ".join(v for _, v in facts)))
    title = post_type.title.split(" ", 1)[-1]
    return Brief(title, tone, tuple(facts), has_buttons, numbers)


def prompt(brief: Brief, style: str) -> tuple[str, str]:
    system = f"{SYSTEM}\nTone: {TONE_GUIDE.get(brief.tone, brief.tone)}.\nStyle: {style}."
    lines = [f"Post type: {brief.type_title}."]
    lines += [f"{label}: {value}" for label, value in brief.facts]
    return system, "\n".join(lines)


def clean_section(name: str, raw: Any, brief: Brief) -> str | None:
    """Return safe plain text for a section, or None if it must be dropped."""
    if not isinstance(raw, str):
        return None
    text = raw.replace("**", "").replace("__", "").replace("`", "")
    text = " ".join(text.split()).strip().strip("\"'“”‘’ ")
    if not text or _BANNED.search(text):
        return None
    lowered = text.lower()
    if "link" in lowered and not brief.has_buttons:
        return None  # don't promise a link that isn't there
    if any(n not in brief.allowed_numbers for n in _NUMBER.findall(text)):
        return None  # invented number (price, date, quantity...)
    limit = MAX_LEN[name]
    if len(text) > limit * 1.5:
        return None
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(",;:-–") + "…"
    return text


def clean(raw: Mapping[str, Any], brief: Brief) -> dict[str, str] | None:
    """Cleaned sections, or None when a required one is unusable."""
    sections = {name: clean_section(name, raw.get(name), brief) for name in SECTIONS}
    if any(sections[name] is None for name in REQUIRED):
        return None
    if sections["intro"] is None and sections["body"] is None:
        return None
    return {k: v for k, v in sections.items() if v is not None}


def _lower_first(sentence: str) -> str:
    """'Just remembering…' -> 'just remembering…' (keeps 'I', 'NASA', 'iPhone' as they are)."""
    word = sentence.split(" ", 1)[0]
    if len(word) > 1 and word[0].isupper() and word[1:].islower():
        return sentence[0].lower() + sentence[1:]
    return sentence


def compose(sections: Mapping[str, str], layout: str, post_type: PostType,
            answers: Mapping[str, str]) -> str:
    """Build a Jakov template: model prose (escaped) + facts as placeholders/points."""
    text = {k: html.escape(v, quote=False) for k, v in sections.items()}
    if "headline" in text:
        flair = "" if _EMOJI_START.match(sections["headline"]) else "{emoji} "
        text["headline"] = f"{flair}<b>{text['headline']}</b>"
    if "cta" in text:
        text["cta"] = f"{{emoji:point}} <b>{text['cta']}</b>"
    if post_type.key == "custom":
        text["body"] = "{message}"  # the admin's own words, kept exactly
        if answers.get("cta", "").strip():
            text["cta"] = "{emoji:point} <b>{cta}</b>"
    if post_type.key == "romantic":
        text.pop("cta", None)  # a love note ends on its closing line, not a call to action
        name = answers.get("for", "").strip()
        if name and not any(name.lower() in v.lower() for v in sections.values()):
            first = "intro" if "intro" in text else "body"
            text[first] = "{for}, " + _lower_first(text.get(first, ""))
    text["points"] = "\n".join(post_type.points)

    out: list[str] = []
    for line in LAYOUTS[layout]:
        used = re.findall(r"@([a-z]+)", line)
        if used and not any(text.get(s, "").strip() for s in used):
            continue
        out.append(re.sub(r"@([a-z]+)", lambda m: text.get(m.group(1), ""), line).strip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
