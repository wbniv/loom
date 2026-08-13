"""Minimal S-expression reader. No language semantics here — just turns
source text into nested Python lists of atoms (str). transcode.py assigns
meaning to the shapes per SPEC.md SS2.
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\(|\)|[^\s()]+')


def tokenize(src: str) -> list[str]:
    tokens = []
    for line in src.splitlines():
        code = line.split(";", 1)[0]  # ';' starts a line comment
        tokens.extend(_TOKEN_RE.findall(code))
    return tokens


def parse_all(src: str) -> list:
    """Parse every top-level form in `src`; returns a list of forms."""
    tokens = tokenize(src)
    forms = []
    i = 0
    while i < len(tokens):
        form, i = _parse_one(tokens, i)
        forms.append(form)
    return forms


def _parse_one(tokens: list[str], i: int):
    if tokens[i] != "(":
        return _atom(tokens[i]), i + 1
    i += 1
    items = []
    while tokens[i] != ")":
        item, i = _parse_one(tokens, i)
        items.append(item)
    return items, i + 1


def _atom(tok: str):
    if tok.startswith('"') and tok.endswith('"'):
        return ("str", tok[1:-1].replace('\\"', '"').replace("\\\\", "\\"))
    return tok
