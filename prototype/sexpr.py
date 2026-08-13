"""Small, strict S-expression reader used by the Loom surface transcoder."""

from __future__ import annotations

import json


class ParseError(ValueError):
    """Syntax error with a byte-independent character offset."""

    def __init__(self, message: str, offset: int):
        super().__init__(f"{message} at character {offset}")
        self.message = message
        self.offset = offset


def tokenize(src: str) -> list[tuple[object, int]]:
    """Return ``(token, offset)`` pairs. Strings are represented as tagged tuples."""
    tokens: list[tuple[object, int]] = []
    i = 0
    while i < len(src):
        if src[i].isspace():
            i += 1
            continue
        start = i
        if src[i] in "()":
            tokens.append((src[i], i))
            i += 1
            continue
        if src[i] == ";":
            raise ParseError("comments are not part of the canonical surface", i)
        if src[i] == '"':
            i += 1
            escaped = False
            while i < len(src):
                ch = src[i]
                if ch == '"' and not escaped:
                    i += 1
                    break
                if ord(ch) < 0x20:
                    raise ParseError("unescaped control character in string", i)
                if ch == "\\" and not escaped:
                    escaped = True
                else:
                    escaped = False
                i += 1
            else:
                raise ParseError("unterminated string", start)
            raw = src[start:i]
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ParseError("invalid JSON string escape", start + exc.pos) from exc
            tokens.append((("str", value), start))
            continue
        while i < len(src) and not src[i].isspace() and src[i] not in "()":
            if src[i] == '"':
                raise ParseError("quote inside atom", i)
            i += 1
        tokens.append((src[start:i], start))
    return tokens


def parse_all(src: str) -> list:
    """Parse every top-level form in ``src``."""
    tokens = tokenize(src)
    forms = []
    i = 0
    while i < len(tokens):
        form, i = _parse_one(tokens, i, len(src))
        forms.append(form)
    return forms


def _parse_one(tokens: list[tuple[object, int]], i: int, eof: int):
    if i >= len(tokens):
        raise ParseError("unexpected end of input", eof)
    token, offset = tokens[i]
    if token == ")":
        raise ParseError("unexpected ')'", offset)
    if token != "(":
        return token, i + 1
    items = []
    i += 1
    while True:
        if i >= len(tokens):
            raise ParseError("unclosed '('", offset)
        if tokens[i][0] == ")":
            return items, i + 1
        item, i = _parse_one(tokens, i, eof)
        items.append(item)
