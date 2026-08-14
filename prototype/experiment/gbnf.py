"""R2's syntax layer: an incremental byte-level automaton over `loom.gbnf`.

The question this module answers is the only one a masker asks of syntax:
*given the bytes emitted so far, which bytes can come next, and may the string
end here?* It is a prefix oracle, not a parser — it never builds a tree, and it
is deliberately total over partial input.

Why our own automaton rather than llama.cpp's grammar engine
------------------------------------------------------------
The plan (R2) allows either. Three things decided it:

1. **R4 is the critical property and must be testable with no model.** The
   soundness suite walks every corpus fixture token-by-token on every
   `task prototype:test`. A syntax layer that lives inside llama.cpp can only be
   tested where llama.cpp is loadable; this one is tested everywhere.
2. **The type-state layer needs the same byte stream anyway.** Sharing one
   feed keeps the two layers trivially in step.
3. **`loom.gbnf` stays the single source of truth.** The grammar is read and
   compiled at run time, so a grammar edit cannot silently desynchronize a
   hand-written parser from the file llama.cpp is given in conditions 2 and 3.

The algorithm is llama.cpp's: a state is a set of *stacks*, each stack a chain
of positions into rule alternatives, with the innermost position always sitting
on a terminal. Advancing a byte keeps the stacks whose terminal matches and
re-normalizes. Emptiness means "this prefix is dead"; a normalized empty stack
means "the string may end here".

Deviation, recorded because it is a soundness-relevant difference: character
classes are interpreted **byte-wise** rather than codepoint-wise. For Loom's
canonical surface — which is ASCII by construction, see the corpus charset —
the two agree. Where they differ (a negated class inside a text literal) the
byte-wise reading accepts a *superset*, which is the safe side for a mask: a
mask may never exclude a valid continuation, and a superset never does.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

GRAMMAR_PATH = Path(__file__).resolve().parent.parent / "loom.gbnf"

#: Item kinds inside a compiled alternative.
CHAR = "c"   # (CHAR, ranges, negated) — matches one byte
REF = "r"    # (REF, rule_id)          — descends into another rule


class GrammarError(ValueError):
    """The grammar file could not be compiled. Never raised at match time."""


# --------------------------------------------------------------------------
# Lexing
# --------------------------------------------------------------------------

_IDENT = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")

_SIMPLE_ESCAPES = {
    "n": ord("\n"), "r": ord("\r"), "t": ord("\t"), "b": 8, "f": 12,
    "\\": ord("\\"), '"': ord('"'), "/": ord("/"), "[": ord("["),
    "]": ord("]"), "-": ord("-"), "^": ord("^"), "'": ord("'"),
}


def _read_escape(text: str, i: int) -> tuple[int, int]:
    """Read the escape starting at `text[i] == '\\'`; return (codepoint, next)."""
    if i + 1 >= len(text):
        raise GrammarError("grammar ends inside an escape")
    kind = text[i + 1]
    if kind == "x":
        return int(text[i + 2:i + 4], 16), i + 4
    if kind == "u":
        return int(text[i + 2:i + 6], 16), i + 6
    if kind == "U":
        return int(text[i + 2:i + 10], 16), i + 10
    if kind in _SIMPLE_ESCAPES:
        return _SIMPLE_ESCAPES[kind], i + 2
    raise GrammarError(f"unknown escape \\{kind}")


@dataclass(frozen=True)
class _Token:
    kind: str      # ident | ::= | | | ( | ) | * | + | ? | { | } | , | number | string | class
    value: object


def _lex(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if ch == "#":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if text.startswith("::=", i):
            tokens.append(_Token("::=", None))
            i += 3
            continue
        if ch in "|()*+?{},":
            tokens.append(_Token(ch, None))
            i += 1
            continue
        if ch == '"':
            i += 1
            codepoints: list[int] = []
            while i < n and text[i] != '"':
                if text[i] == "\\":
                    code, i = _read_escape(text, i)
                    codepoints.append(code)
                else:
                    codepoints.append(ord(text[i]))
                    i += 1
            if i >= n:
                raise GrammarError("unterminated string literal in grammar")
            i += 1
            tokens.append(_Token("string", tuple(codepoints)))
            continue
        if ch == "[":
            i += 1
            negated = False
            if i < n and text[i] == "^":
                negated = True
                i += 1
            ranges: list[tuple[int, int]] = []
            while i < n and text[i] != "]":
                if text[i] == "\\":
                    low, i = _read_escape(text, i)
                else:
                    low = ord(text[i])
                    i += 1
                high = low
                if i + 1 < n and text[i] == "-" and text[i + 1] != "]":
                    i += 1
                    if text[i] == "\\":
                        high, i = _read_escape(text, i)
                    else:
                        high = ord(text[i])
                        i += 1
                ranges.append((low, high))
            if i >= n:
                raise GrammarError("unterminated character class in grammar")
            i += 1
            tokens.append(_Token("class", (tuple(ranges), negated)))
            continue
        if ch.isdigit():
            start = i
            while i < n and text[i].isdigit():
                i += 1
            tokens.append(_Token("number", int(text[start:i])))
            continue
        if ch in _IDENT:
            start = i
            while i < n and text[i] in _IDENT:
                i += 1
            tokens.append(_Token("ident", text[start:i]))
            continue
        raise GrammarError(f"unexpected character {ch!r} in grammar at offset {i}")
    return tokens


# --------------------------------------------------------------------------
# Compilation
# --------------------------------------------------------------------------


class Grammar:
    """A compiled GBNF grammar plus the incremental prefix oracle over it.

    Rules are stored as `alts[rule_id] -> tuple of alternatives`, each
    alternative a tuple of items. Sugar (`*`, `+`, `?`, `{n}`, groups) is
    desugared into generated rules at compile time, so the matcher only ever
    sees CHAR and REF.
    """

    def __init__(self, text: str, root: str = "root") -> None:
        self._names: list[str] = []
        self._alts: list[tuple] = []
        self._by_name: dict[str, int] = {}
        self._anon = 0
        self._compile(text)
        if root not in self._by_name:
            raise GrammarError(f"grammar has no {root!r} rule")
        self.root_id = self._by_name[root]
        self._step_cache: dict[tuple, frozenset] = {}
        self._bytes_cache: dict[frozenset, frozenset] = {}
        self.initial = self._normalize_all(
            tuple(((self.root_id, index, 0),) for index in range(len(self._alts[self.root_id]))))

    # -- compile ---------------------------------------------------------

    def _rule_id(self, name: str) -> int:
        if name not in self._by_name:
            self._by_name[name] = len(self._names)
            self._names.append(name)
            self._alts.append(())
        return self._by_name[name]

    def _fresh(self, hint: str) -> int:
        self._anon += 1
        return self._rule_id(f"{hint}#{self._anon}")

    def _compile(self, text: str) -> None:
        tokens = _lex(text)
        i = 0
        defined: set[str] = set()
        while i < len(tokens):
            if tokens[i].kind != "ident" or i + 1 >= len(tokens) or tokens[i + 1].kind != "::=":
                raise GrammarError(f"expected a rule definition at token {i}: {tokens[i]}")
            name = tokens[i].value
            i += 2
            end = i
            while end < len(tokens):
                if (tokens[end].kind == "ident" and end + 1 < len(tokens)
                        and tokens[end + 1].kind == "::="):
                    break
                end += 1
            rule_id = self._rule_id(name)
            self._alts[rule_id] = self._parse_alternates(tokens[i:end], name)
            defined.add(name)
            i = end
        undefined = [n for n in self._names if "#" not in n and n not in defined]
        if undefined:
            raise GrammarError(f"grammar references undefined rules: {', '.join(sorted(undefined))}")

    def _parse_alternates(self, tokens: list[_Token], hint: str) -> tuple:
        alternatives: list[tuple] = []
        depth = 0
        current: list[_Token] = []
        for token in tokens:
            if token.kind == "(":
                depth += 1
            elif token.kind == ")":
                depth -= 1
            if token.kind == "|" and depth == 0:
                alternatives.append(tuple(self._parse_sequence(current, hint)))
                current = []
                continue
            current.append(token)
        alternatives.append(tuple(self._parse_sequence(current, hint)))
        return tuple(alternatives)

    def _parse_sequence(self, tokens: list[_Token], hint: str) -> list:
        items: list = []
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if token.kind == "ident":
                produced = [(REF, self._rule_id(token.value))]
                i += 1
            elif token.kind == "string":
                produced = [
                    (CHAR, ((byte, byte),), False)
                    for code in token.value
                    for byte in chr(code).encode("utf-8")
                ]
                i += 1
            elif token.kind == "class":
                ranges, negated = token.value
                produced = [(CHAR, tuple(ranges), negated)]
                i += 1
            elif token.kind == "(":
                depth, j = 1, i + 1
                while j < len(tokens) and depth:
                    if tokens[j].kind == "(":
                        depth += 1
                    elif tokens[j].kind == ")":
                        depth -= 1
                    j += 1
                if depth:
                    raise GrammarError("unbalanced '(' in grammar")
                inner = self._parse_alternates(tokens[i + 1:j - 1], hint)
                group = self._fresh(hint)
                self._alts[group] = inner
                produced = [(REF, group)]
                i = j
            else:
                raise GrammarError(f"unexpected token {token.kind!r} in rule {hint!r}")

            # Postfix operators bind to the item just produced.
            while i < len(tokens) and tokens[i].kind in ("*", "+", "?", "{"):
                if tokens[i].kind == "{":
                    if (i + 2 >= len(tokens) or tokens[i + 1].kind != "number"
                            or tokens[i + 2].kind != "}"):
                        raise GrammarError(f"only {{n}} repetition is supported (rule {hint!r})")
                    count = tokens[i + 1].value
                    produced = list(produced) * count
                    i += 3
                    continue
                produced = [(REF, self._repeat(produced, tokens[i].kind, hint))]
                i += 1
            items.extend(produced)
        return items

    def _repeat(self, items: list, operator: str, hint: str) -> int:
        """`X*` → `S ::= X S | ε`; `X?` → `S ::= X | ε`; `X+` → `X S*`."""
        rule = self._fresh(hint)
        body = tuple(items)
        if operator == "?":
            self._alts[rule] = (body, ())
        elif operator == "*":
            self._alts[rule] = (body + ((REF, rule),), ())
        elif operator == "+":
            self._alts[rule] = (body + ((REF, rule),), body)
        else:  # pragma: no cover - guarded by the caller
            raise GrammarError(f"unknown repetition {operator!r}")
        return rule

    # -- the prefix oracle -----------------------------------------------

    def _normalize_all(self, stacks) -> frozenset:
        """Expand rule references until every stack sits on a terminal.

        A normalized empty stack `()` is the *may end here* marker. Descent
        into a rule that is the last item of its alternative pops the parent
        frame first (a proper tail call); without that, a `X*` rule would grow
        the stack once per repetition and turn a 64-hex hash into 64 distinct
        states that share nothing.
        """
        out: set = set()
        seen: set = set()
        work = list(stacks)
        while work:
            stack = work.pop()
            if stack in seen:
                continue
            seen.add(stack)
            if not stack:
                out.add(())
                continue
            rule_id, alt_index, item_index = stack[-1]
            items = self._alts[rule_id][alt_index]
            if item_index >= len(items):
                parent = stack[:-1]
                if parent:
                    prule, palt, pitem = parent[-1]
                    work.append(parent[:-1] + ((prule, palt, pitem + 1),))
                else:
                    out.add(())
                continue
            item = items[item_index]
            if item[0] == REF:
                target = item[1]
                base = stack if item_index + 1 < len(items) else stack[:-1]
                for alt_index2 in range(len(self._alts[target])):
                    work.append(base + ((target, alt_index2, 0),))
                continue
            out.add(stack)
        return frozenset(out)

    @staticmethod
    def _matches(item, byte: int) -> bool:
        hit = any(low <= byte <= high for low, high in item[1])
        return (not hit) if item[2] else hit

    def step(self, state: frozenset, byte: int) -> frozenset:
        """The state after consuming `byte`; empty means the prefix is dead."""
        key = (state, byte)
        cached = self._step_cache.get(key)
        if cached is not None:
            return cached
        advanced = []
        for stack in state:
            if not stack:
                continue
            rule_id, alt_index, item_index = stack[-1]
            item = self._alts[rule_id][alt_index][item_index]
            if self._matches(item, byte):
                advanced.append(stack[:-1] + ((rule_id, alt_index, item_index + 1),))
        result = self._normalize_all(tuple(advanced)) if advanced else frozenset()
        if len(self._step_cache) < 200_000:
            self._step_cache[key] = result
        return result

    def allowed_bytes(self, state: frozenset) -> frozenset:
        """Every byte that keeps the prefix alive. The token prefilter's input."""
        cached = self._bytes_cache.get(state)
        if cached is not None:
            return cached
        allowed: set[int] = set()
        for stack in state:
            if not stack:
                continue
            rule_id, alt_index, item_index = stack[-1]
            _, ranges, negated = self._alts[rule_id][alt_index][item_index]
            if negated:
                blocked = {b for low, high in ranges for b in range(low, min(high, 255) + 1)}
                allowed |= set(range(256)) - blocked
            else:
                for low, high in ranges:
                    allowed.update(range(low, min(high, 255) + 1))
        result = frozenset(allowed)
        if len(self._bytes_cache) < 100_000:
            self._bytes_cache[state] = result
        return result

    @staticmethod
    def can_end(state: frozenset) -> bool:
        """True when the emitted prefix is already a complete sentence."""
        return () in state

    def feed(self, state: frozenset, data: bytes) -> frozenset:
        for byte in data:
            if not state:
                return state
            state = self.step(state, byte)
        return state

    def accepts(self, data: bytes) -> bool:
        return self.can_end(self.feed(self.initial, data))

    # -- introspection, for tests and reports ----------------------------

    @property
    def rule_count(self) -> int:
        return len(self._names)

    def cache_sizes(self) -> dict[str, int]:
        return {"step": len(self._step_cache), "bytes": len(self._bytes_cache)}


_CACHED: dict[str, Grammar] = {}


def loom_grammar(path: Path | str = GRAMMAR_PATH) -> Grammar:
    """The compiled `loom.gbnf`, compiled once per path per process."""
    key = str(path)
    grammar = _CACHED.get(key)
    if grammar is None:
        grammar = Grammar(Path(path).read_text(encoding="utf-8"))
        _CACHED[key] = grammar
    return grammar
