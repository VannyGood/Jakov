"""Spintax: `{Hello|Hi|Hey}` picks one option; groups can nest.

Braces without a top-level `|` are placeholders (`{product}`, `{emoji:fire}`) and are kept
as-is, with their contents spun. Use `\\{`, `\\}` and `\\|` for literal characters.
An unmatched `{` is kept literally.
"""

from __future__ import annotations

import random

_ESCAPES = {"\\{": "\x00", "\\}": "\x01", "\\|": "\x02"}
_RESTORE = {"\x00": "{", "\x01": "}", "\x02": "|"}


def spin(text: str, rng: random.Random | None = None) -> str:
    rng = rng or random.Random()
    for raw, marker in _ESCAPES.items():
        text = text.replace(raw, marker)
    result, _ = _parse(text, 0, rng, inside=False)
    for marker, char in _RESTORE.items():
        result = result.replace(marker, char)
    return result


def _parse(text: str, pos: int, rng: random.Random, inside: bool) -> tuple[str, int]:
    """Parse until the closing brace of the current group (or end of text).

    Returns the output and the index just after the closing brace. When `inside` is
    True, the returned output is the *group's* result (chosen option or placeholder).
    """
    options: list[list[str]] = [[]]
    while pos < len(text):
        char = text[pos]
        if char == "{":
            group, new_pos = _parse(text, pos + 1, rng, inside=True)
            options[-1].append(group)
            pos = new_pos
        elif char == "}" and inside:
            return _close(options, rng), pos + 1
        elif char == "|" and inside:
            options.append([])
            pos += 1
        else:
            options[-1].append(char)
            pos += 1
    if inside:
        # Unmatched "{": keep literally, including any pipes we consumed.
        return "{" + "|".join("".join(o) for o in options), pos
    return "".join(options[0]), pos


def _close(options: list[list[str]], rng: random.Random) -> str:
    if len(options) == 1:
        return "{" + "".join(options[0]) + "}"
    return "".join(rng.choice(options))

