"""Parse 'Label - https://link' lines into URL buttons."""

from __future__ import annotations

import re
from urllib.parse import urlparse

MAX_LABEL = 64
_LINE_RE = re.compile(r"^(?P<label>.+?)\s*(?:[-|–—]\s*|\s)(?P<url>(?:https?|tg)://\S+)$")


def valid_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme == "tg":
        return bool(parsed.netloc or parsed.path)
    return parsed.scheme in ("http", "https") and "." in parsed.netloc


def parse_buttons(text: str, limit: int) -> tuple[list[dict[str, str]], list[str]]:
    """Returns (buttons, errors). Each non-empty line must be 'Label - URL'."""
    buttons: list[dict[str, str]] = []
    errors: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        match = _LINE_RE.match(line)
        if not match:
            errors.append(f"“{line[:40]}”: use the format Label - https://link")
            continue
        label, url = match.group("label").strip(" -|–—"), match.group("url")
        if not label:
            errors.append(f"“{line[:40]}”: the label is empty")
        elif len(label) > MAX_LABEL:
            errors.append(f"“{label[:40]}…”: labels can be at most {MAX_LABEL} characters")
        elif not valid_url(url):
            errors.append(f"“{url[:60]}” isn't a valid link")
        else:
            buttons.append({"text": label, "url": url})
    if len(buttons) > limit:
        errors.append(f"At most {limit} buttons; I kept the first {limit}.")
        buttons = buttons[:limit]
    return buttons, errors
