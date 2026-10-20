import random
import re
from typing import Any

import pytest

from jakov.config import PROJECT_ROOT
from jakov.engine import llm_writer
from jakov.engine.catalog import Catalog
from jakov.engine.text_generator import GenerationRequest
from jakov.services.llm.ollama import LlmError
from jakov.services.llm_generator import LlmGenerator

CATALOG = Catalog(PROJECT_ROOT / "data")
SELL = {"product": "Nike Air Max 90", "price": "$99", "offer": "-30% this weekend"}
GOOD = {"headline": "Air Max 90: Step Into Style", "intro": "Ready to own the streets?",
        "body": "Iconic comfort, now 30% off for a few days only.",
        "closing": "Claim yours before it's gone!", "cta": "Shop now"}


def brief(answers: dict[str, str] = SELL, post_type: str = "sell",
          buttons: bool = False) -> llm_writer.Brief:
    return llm_writer.make_brief(CATALOG.types[post_type], "hype", answers, buttons)


def test_brief_excludes_dates_and_lists_facts() -> None:
    b = llm_writer.make_brief(CATALOG.types["sell"], "hype", {**SELL, "deadline": "friday"},
                              False)
    labels = [label for label, _ in b.facts]
    assert "Deadline" not in labels and ("Price", "$99") in b.facts
    assert b.allowed_numbers == {"90", "99", "30"}
    system, user = llm_writer.prompt(b, "bold")
    assert "Tone: hype" in system and "Nike Air Max 90" in user and "friday" not in user


def test_choice_answers_use_labels() -> None:
    b = brief({"for": "Mia", "mood": "missing"}, "romantic")
    assert ("Mood", "Missing you") in b.facts


@pytest.mark.parametrize(("name", "text"), [
    ("cta", "Shop at https://x.io"),
    ("cta", "Tap the link below!"),               # no buttons on this post
    ("body", "Only $79 today!"),                   # invented price
    ("body", "Order 3 and get 1 free"),            # invented numbers
    ("headline", "#sale #shoes"),
    ("intro", "Hello {product}"),
    ("intro", "The start time is shown separately"),
    ("body", "x" * 600),
    ("closing", "   "),
])
def test_bad_sections_are_dropped(name: str, text: str) -> None:
    assert llm_writer.clean_section(name, text, brief()) is None


def test_link_allowed_when_post_has_buttons() -> None:
    assert llm_writer.clean_section("cta", "Tap the link below", brief(buttons=True))


def test_cleaning_strips_markdown_quotes_and_trims() -> None:
    assert llm_writer.clean_section("headline", '"**Big** `drop`"', brief()) == "Big drop"
    long = " ".join(["word"] * 22)  # 109 chars: over 80, under the 120 hard limit
    trimmed = llm_writer.clean_section("headline", long, brief())
    assert trimmed is not None and trimmed.endswith("…") and len(trimmed) <= 81


def test_missing_required_section_rejects_all() -> None:
    assert llm_writer.clean({**GOOD, "cta": "Visit https://spam"}, brief()) is None
    assert llm_writer.clean({**GOOD, "intro": "", "body": ""}, brief()) is None
    assert llm_writer.clean(GOOD, brief()) is not None


@pytest.mark.parametrize("layout", list(llm_writer.LAYOUTS))
def test_compose_escapes_text_and_adds_facts_by_code(layout: str) -> None:
    sections = llm_writer.clean({**GOOD, "body": "Fish & chips, then fresh kicks."}, brief())
    assert sections is not None
    out = llm_writer.compose(sections, layout, CATALOG.types["sell"], SELL)
    assert "@" not in out and "\n\n\n" not in out
    assert all(line == line.strip() for line in out.split("\n"))
    assert "{price}" in out and "{product}" in out  # exact facts via placeholders
    assert "&amp;" in out or layout == "spotlight"  # spotlight has no body


def test_compose_keeps_admin_message_for_custom() -> None:
    answers = {"topic": "News", "message": "We moved to a new studio!", "cta": "Visit us"}
    news = {"headline": "Big News", "intro": "Something exciting happened.",
            "body": "Rewritten by the model.", "closing": "See you soon.", "cta": "Shop now"}
    sections = llm_writer.clean(news, brief(answers, "custom"))
    assert sections is not None
    out = llm_writer.compose(sections, "classic", CATALOG.types["custom"], answers)
    assert "{message}" in out and "{cta}" in out and "Shop now" not in out


def test_compose_adds_missing_name_for_romantic() -> None:
    answers = {"for": "Mia", "mood": "sweet"}
    love = {"headline": "Thinking of You", "intro": "You make every day brighter.",
            "body": "", "closing": "Always yours.", "cta": "Smile today"}
    sections = llm_writer.clean(love, brief(answers, "romantic"))
    assert sections is not None
    out = llm_writer.compose(sections, "classic", CATALOG.types["romantic"], answers)
    assert "{for}, " in out


class FakeClient:
    model = "fake:1b"

    def __init__(self, replies: list[Any], up: bool = True) -> None:
        self.replies = replies
        self.up = up
        self.prompts: list[str] = []

    async def available(self) -> bool:
        return self.up

    async def chat_json(self, system: str, user: str, schema: Any, **kw: Any) -> Any:
        self.prompts.append(system)
        reply = self.replies.pop(0) if self.replies else GOOD
        if isinstance(reply, Exception):
            raise reply
        return reply


def gen(client: FakeClient) -> LlmGenerator:
    return LlmGenerator(client, CATALOG, rng=random.Random(4))  # type: ignore[arg-type]


async def test_llm_writes_three_varied_posts() -> None:
    client = FakeClient([GOOD, {**GOOD, "headline": "Fresh Kicks Alert"},
                         {**GOOD, "headline": "Walk Tall"}])
    out = await gen(client).generate(GenerationRequest("sell", "hype", SELL), 3)
    assert [g.source for g in out] == ["llm"] * 3
    assert len({re.findall(r"Style: (.*)\.", p)[0] for p in client.prompts}) == 3


async def test_rejected_or_failed_outputs_are_filled_by_templates() -> None:
    client = FakeClient([GOOD, {**GOOD, "cta": "Only $5!"}, LlmError("boom")])
    out = await gen(client).generate(GenerationRequest("sell", "hype", SELL), 3)
    assert [g.source for g in out] == ["llm", "template", "template"]


async def test_offline_model_uses_templates_only() -> None:
    client = FakeClient([], up=False)
    out = await gen(client).generate(GenerationRequest("game", "chill", {"game": "Valorant"}), 3)
    assert len(out) == 3 and all(g.source == "template" for g in out) and client.prompts == []


def test_romantic_has_no_cta_and_name_reads_naturally() -> None:
    answers = {"for": "Mia", "mood": "missing"}
    love = {"headline": "Thinking of You", "intro": "Just remembering your smile.",
            "body": "", "closing": "Always yours.", "cta": "Share this with someone"}
    sections = llm_writer.clean(love, brief(answers, "romantic"))
    assert sections is not None
    out = llm_writer.compose(sections, "classic", CATALOG.types["romantic"], answers)
    assert "{for}, just remembering" in out and "Share this" not in out
