# Review — S-expression parser and canonical-CBOR transcoder

**Date:** 2026-08-12
**Scope:** `prototype/sexpr.py`, `prototype/transcode.py`, `prototype/loom.gbnf`,
`prototype/test_roundtrip.py`, and the associated claims in `prototype/README.md`.
**Baseline reviewed:** commit `7474944` (`Prototype Loom S-expression transcoder`).

**Resolution:** Implemented in the working tree on 2026-08-12. The implementation
chose the strict canonical-surface option, added an inverse renderer and explicit
validation, covered all tags and literal kinds, added row variables and arbitrary
byte strings, removed comments from machine-emission fixtures, and expanded the
test suite with round-trip, boundary, and rejection cases. The GBNF was then run
through llama.cpp's model-free validator at upstream revision `1f368f354d9e`;
that check exposed and led to correction of invalid multiline alternatives. A
repeatable `task grammar:test` harness now covers positive and negative inputs.

## Conclusion

The prototype is a useful feasibility spike. It reproduces the specification's
worked CBOR encoding and hash exactly, separates the small S-expression reader
from semantic transcoding, and makes the proposed generation surface concrete.
Those are worthwhile results.

It does not yet establish its central claim: that the surface is a total,
deterministic isomorphism of Loom's canonical representation. The implemented
mapping is many-to-one, the grammar and reader accept different languages, some
specified AST values have no surface representation, and the tests exercise
only successful transcoding of four hand-written examples. The current artifact
is best described as a deterministic prototype transcoder, not yet a verified
isomorphism.

The TODO item should therefore be reopened or narrowed to the result that was
actually demonstrated. Completion should require a canonical surface contract,
grammar/reader conformance, complete node coverage, and negative and boundary
tests.

## What is good in the current plan and implementation

- The worked example is pinned byte-for-byte and hash-for-hash. This is a strong
  regression test for the most important identity invariant.
- The surface grammar is small and close to the node tables in `SPEC.md`, making
  omissions and disagreements inspectable.
- The prototype explicitly distinguishes syntax constraints from scope, typing,
  refinement, and evidence checks. That boundary is appropriate.
- NFC normalization, canonical NaN handling, sorted effect hashes, and minimal
  CBOR integer encoding show attention to canonical identity.
- Keeping the implementation standard-library-only makes the spike easy to run
  and audit.

## Findings

### 1. High — semicolons inside strings are treated as comments

`sexpr.tokenize` splits every physical line at its first `;` before recognizing
quoted strings. A valid form such as:

```lisp
(def Text (lit text "a;b"))
```

is truncated and eventually fails with an incidental `IndexError`. Comment
recognition must be integrated into lexical scanning so `;` begins a comment
only when outside a string.

This also shows why malformed-input tests matter: the error currently points at
parser internals rather than the source location or violated rule.

### 2. High — the surface mapping is not an isomorphism

Multiple accepted source forms produce the same canonical bytes:

- `I64` and `(base I64)` encode identically.
- Numeric spellings such as `1` and `01` collapse through `int` conversion.
- Differently ordered effect rows collapse because the transcoder sorts them.
- Upper- and lower-case hexadecimal digits collapse through `bytes.fromhex`.
- Text spellings that differ only by Unicode normalization collapse under NFC.

There is also no inverse transformation from canonical IR or CBOR to the
canonical S-expression surface. Determinism alone means one input has one
output; an isomorphism additionally requires a bijection and an inverse.

There are two defensible resolutions:

1. Define one canonical surface spelling and reject every noncanonical alias.
   Then add `IR -> surface` and prove both round-trip directions in tests.
2. Keep the permissive authoring surface and call it a many-to-one canonicalizing
   transcoder. Update `SPEC.md` and the prototype documentation so they no longer
   rely on "isomorphism" or "zero stylistic freedom."

For constrained generation, option 1 is the cleaner match for the design.

### 3. High — the GBNF grammar and reader accept different languages

The checked-in examples contain `;` comments, and `sexpr.py` accepts comments,
but `loom.gbnf` defines whitespace as spaces, tabs, and line breaks only. The
example corpus therefore is not valid input to the grammar intended for the
actual constrained decoder.

More broadly, no test invokes a GBNF implementation or otherwise checks that
every grammar-generated form is accepted by the reader and that every accepted
form conforms to the grammar. The parser can consequently drift from the
generation constraint without any failing test.

Comments are unnecessary on a machine-emission surface. The simplest canonical
choice is to exclude comments from generated forms and either strip comments
from fixtures or treat commented examples as documentation wrappers whose
payload is separately extracted and grammar-checked.

### 4. Medium — the transcoder accepts invalid field values

The grammar restricts some lexical shapes, but the public transcoder does not
enforce those restrictions:

- Hashes are not required to contain exactly 32 bytes.
- Variable, type-variable, constructor, operation, and binder indices may be
  negative.
- `i64` literals may exceed the signed 64-bit range.
- Any boolean token other than `true` silently becomes `false`.
- Several structural checks use `assert`, which disappears under `python -O`.
- Missing delimiters and malformed shapes commonly produce `IndexError`,
  `KeyError`, or unpacking errors rather than a deliberate parse error.

The transcoder should validate every field independent of the masking layer.
Generated input may normally be grammar-constrained, but tests, tools, future
callers, and corrupted artifacts can invoke the transcoder directly. The
identity boundary should fail closed.

### 5. Medium — the surface is not total over the specified representation

`SPEC.md` permits an effect row optionally ending in a row variable `[5, i]`,
while the grammar and transcoder accept only ability hashes in rows. Conversely,
the grammar reuses the fixed 32-byte `hash` production for `bytes` literals,
although byte strings are not specified as fixed-length hashes.

Thus at least one valid type cannot be expressed, while a general literal kind
is accidentally narrowed to a hash-sized value. A coverage matrix from every
normative AST field to its surface production would have exposed both gaps.

### 6. Medium — the tests do not perform a round trip or cover every tag

`test_every_example_transcodes_deterministically` runs the same pure function
twice on the same input. This checks repeatability, but not a round trip. A real
round-trip test needs an inverse, for example:

```text
surface -> IR -> canonical surface -> IR
IR -> surface -> IR
```

The examples also do not cover every reachable node as claimed. Missing cases
include `handle`, `fix`, `cap`, `tyvar`, `forall`, and several literal kinds.
Checking that four fixtures have distinct SHA-256 hashes provides little useful
assurance; exhaustive shape, canonicalization, and rejection tests would be
more valuable.

## Recommended plan

### Phase 1 — settle the contract

1. Decide whether the surface is strictly canonical and bijective or permissive
   and canonicalizing. Prefer a strictly canonical generation surface.
2. Specify lexical rules for whitespace, comments, strings, escapes, integers,
   floats, hashes, and arbitrary bytes.
3. Specify numeric domains and structural invariants for every field.
4. Add a table mapping every term/type/literal shape in `SPEC.md` to exactly one
   surface production, including row variables.

### Phase 2 — make one parser enforce the contract

1. Replace line-based comment stripping with a state-aware lexer.
2. Introduce a dedicated exception carrying an input offset and useful message.
3. Replace assertions and incidental Python exceptions with explicit validation.
4. Require canonical spellings: fixed hash length and case, nonnegative canonical
   indices, signed-64-bit literals, canonical effect-row ordering, and defined
   string escapes.
5. Separate hashes from arbitrary byte-string literals in both grammar and IR
   conversion.

### Phase 3 — prove grammar/reader agreement

1. Load `loom.gbnf` with the intended constrained-decoding grammar engine in CI,
   or add an equivalent executable conformance harness.
2. Check every example against both the grammar and parser.
3. Generate a bounded corpus from the grammar and ensure the parser accepts it.
4. Maintain negative fixtures for forms the canonical grammar must reject.

### Phase 4 — test the actual claims

1. Add at least one positive case for every term tag, type tag, literal kind,
   empty/nonempty list, and row-variable form.
2. Add boundary cases for all integer domains, float special values, hash length,
   arbitrary byte lengths, Unicode normalization, escapes, nesting, and EOF.
3. Add malformed cases for delimiters, arity, unknown keywords, invalid atoms,
   trailing forms, and comments inside versus outside strings.
4. Implement the inverse surface renderer if retaining the isomorphism claim,
   then test both round-trip directions.
5. Retain the §4.4 byte/hash fixture as the independent golden identity test.

## Suggested completion criteria

The parser prototype can reasonably be marked done when all of the following
are true:

- Every normative canonical term and type has exactly one generated surface
  representation, or the documentation explicitly abandons the isomorphism
  claim.
- The grammar, parser, and examples accept the same surface language.
- All tags and field variants have positive coverage.
- Invalid and noncanonical input is rejected with stable, intentional errors.
- The worked example still produces the exact specified bytes and identity.
- If "isomorphism" remains the term, both inverse round trips are executable and
  tested.

Until then, the current result should be recorded as: **a successful proof that
one small S-expression subset can deterministically reproduce Loom's worked
canonical-CBOR identity example**, with broader feasibility still under
verification.
