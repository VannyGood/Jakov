"""Final polish on rendered HTML: punctuation, spacing and line-start capitals.

Only visible text is touched; tags and entities are left exactly as they are.
"""

from __future__ import annotations

import re

_TAG_SPLIT = re.compile(r"(<[^>]+>)")
_FIXES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"([!?])\.(?!\.)"), r"\1"),          # "Now!." -> "Now!"
    (re.compile(r"(?<!\.)\.\.(?!\.)"), "."),         # ".." -> "." (keeps "...")
    (re.compile(r",\s*([.!?])"), r"\1"),             # ",." -> "."
    (re.compile(r"\.([!?])"), r"\1"),                # ".!" -> "!"
    (re.compile(r"([!?]){4,}"), r"\1\1\1"),          # "!!!!!" -> "!!!"
    (re.compile(r"[ \t]+([,.!?;:])(?=\s|$)"), r"\1"),  # "word ." -> "word."
    (re.compile(r"[ \t]{2,}"), " "),                 # double spaces
    (re.compile(r"\(\s*\)"), ""),                    # empty "()"
]


def _fix_text(text: str) -> str:
    for pattern, replacement in _FIXES:
        text = pattern.sub(replacement, text)
    return text


def _capitalize_line_starts(html_text: str) -> str:
    """Upper-case the first letter of each line when its first word is all lowercase."""
    out: list[str] = []
    at_line_start = True
    in_tag = False
    i = 0
    while i < len(html_text):
        char = html_text[i]
        if char == "<":
            in_tag = True
        elif char == ">" and in_tag:
            in_tag = False
            out.append(char)
            i += 1
            continue
        if in_tag:
            out.append(char)
            i += 1
            continue
        if char == "\n":
            at_line_start = True
        elif at_line_start and char == "&":
            end = html_text.find(";", i)
            if end != -1:
                out.append(html_text[i:end + 1])
                i = end + 1
                continue
        elif at_line_start and char.isalpha():
            match = re.match(r"[^\s<]+", html_text[i:])
            word = match.group(0) if match else char
            if char.islower() and word == word.lower():
                char = char.upper()
            at_line_start = False
        elif at_line_start and char.isdigit():
            at_line_start = False
        out.append(char)
        i += 1
    return "".join(out)


def tidy(html_text: str, *, capitalize: bool = True) -> str:
    pieces = _TAG_SPLIT.split(html_text)
    fixed = "".join(p if p.startswith("<") and p.endswith(">") else _fix_text(p) for p in pieces)
    if capitalize:
        fixed = _capitalize_line_starts(fixed)
    lines = [line.rstrip() for line in fixed.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
