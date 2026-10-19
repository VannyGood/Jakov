"""Fill `{name}` placeholders and drop optional `[[ ... ]]` blocks whose values are empty."""

from __future__ import annotations

import html
import re
from collections.abc import Mapping
from datetime import datetime

# {name} or {name.filter}: filters are upper, lower, title, a (adds "a"/"an").
PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z0-9_]*)(?:\.(upper|lower|title|a))?\}")
_AN_EXCEPTIONS = ("hour", "honest", "honor", "honour", "heir")
_A_EXCEPTIONS = ("uni", "use", "user", "usu", "eu", "one", "once", "ur")
OPTIONAL_RE = re.compile(r"\[\[(.*?)\]\]", re.DOTALL)
_DROPPED = "\x00"


def placeholders(text: str) -> set[str]:
    return {m.group(1) for m in PLACEHOLDER_RE.finditer(text)}


def with_article(value: str) -> str:
    """'apple' -> 'an apple', 'Air Max' -> 'an Air Max', 'user guide' -> 'a user guide'."""
    word = value.strip().lower()
    if not word:
        return value
    if word.startswith(_AN_EXCEPTIONS):
        article = "an"
    elif word.startswith(_A_EXCEPTIONS):
        article = "a"
    else:
        article = "an" if word[0] in "aeiou" else "a"
    return f"{article} {value.strip()}"


def apply_filter(value: str, name: str | None) -> str:
    if name == "upper":
        return value.upper()
    if name == "lower":
        return value.lower()
    if name == "title":
        # Keep words that already have capitals (iPhone, USDT) as written.
        return " ".join(w if any(c.isupper() for c in w) else w.capitalize()
                        for w in value.split(" "))
    if name == "a":
        return with_article(value)
    return value


def drop_empty_optionals(text: str, values: Mapping[str, str], known: set[str]) -> str:
    """`[[...]]` survives only if every known placeholder inside has a non-empty value."""

    def keep(match: re.Match[str]) -> str:
        inner = match.group(1)
        for name in placeholders(inner):
            if name in known and not values.get(name, "").strip():
                return _DROPPED
        return inner

    text = OPTIONAL_RE.sub(keep, text)
    # A line that held only dropped blocks disappears entirely, newline included.
    lines = [line for line in text.split("\n")
             if not (_DROPPED in line and not line.replace(_DROPPED, "").strip())]
    text = "\n".join(lines).replace(_DROPPED, "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fill(text: str, values: Mapping[str, str], known: set[str], *, escape: bool = True) -> str:
    """Replace known placeholders; leave unknown `{things}` untouched (they may be literal)."""
    text = drop_empty_optionals(text, values, known)

    def sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in known:
            return match.group(0)
        value = apply_filter(values.get(name, ""), match.group(2))
        return html.escape(value, quote=False) if escape else value

    return PLACEHOLDER_RE.sub(sub, text)


def humanize_delta(seconds: float) -> str:
    """'2 days 5 hours', '3 hours 12 minutes', '45 minutes', 'less than a minute'."""
    if seconds <= 0:
        return ""
    minutes = int(seconds // 60)
    days, rem = divmod(minutes, 24 * 60)
    hours, mins = divmod(rem, 60)

    def unit(n: int, word: str) -> str:
        return f"{n} {word}{'' if n == 1 else 's'}"

    if days:
        return unit(days, "day") + (f" {unit(hours, 'hour')}" if hours else "")
    if hours:
        return unit(hours, "hour") + (f" {unit(mins, 'minute')}" if mins else "")
    if mins:
        return unit(mins, "minute")
    return "less than a minute"


def format_moment(moment: datetime, now: datetime) -> str:
    """'today 21:00', 'tomorrow 18:30', 'Fri 25 Oct, 20:00', 'Fri 25 Oct 2027, 20:00'."""
    day_diff = (moment.date() - now.date()).days
    clock = moment.strftime("%H:%M")
    if day_diff == 0:
        return f"today {clock}"
    if day_diff == 1:
        return f"tomorrow {clock}"
    if moment.year != now.year:
        return moment.strftime(f"%a %d %b %Y, {clock}")
    return moment.strftime(f"%a %d %b, {clock}")


def builtin_values(now_local: datetime, moments: Mapping[str, datetime] | None = None
                   ) -> dict[str, str]:
    """Values computed at send time in the admin's timezone.

    `moments` maps datetime fields (e.g. deadline) to aware datetimes; each produces
    `{field}` (formatted) and the first one also feeds `{countdown}`.
    """
    values = {
        "date": now_local.strftime("%d %b %Y"),
        "weekday": now_local.strftime("%A"),
        "time": now_local.strftime("%H:%M"),
        "year": str(now_local.year),
        "countdown": "",
    }
    for name, moment in (moments or {}).items():
        local = moment.astimezone(now_local.tzinfo)
        remaining = (local - now_local).total_seconds()
        values[name] = format_moment(local, now_local) if remaining > 0 else ""
        if not values["countdown"]:
            values["countdown"] = humanize_delta(remaining)
    return values


BUILTIN_NAMES = {"date", "weekday", "time", "year", "countdown", "channel", "tip", "quote", "fact"}
