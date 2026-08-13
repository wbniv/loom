# Is Loom a Lisp?

Loom's machine-emission surface looks Lisp-like because it renders trees as
S-expressions. That resemblance is useful, but Loom is not a Lisp dialect. Its
surface is a rigid, canonical serialization of a typed CBOR intermediate
representation rather than a flexible symbolic source language.

For example, a Lisp identity function might be written as:

```lisp
(lambda (x) x)
```

The corresponding complete Loom definition is:

```loom
(def (fn I64 () I64) (lam I64 (var 0)))
```

Here `(fn I64 () I64)` declares a function from `I64` to `I64` with an empty
effect row. `(lam I64 ...)` binds its argument, and `(var 0)` refers to the
nearest binder by de Bruijn index. There is no semantic variable name to resolve
or rename.

## Principal differences

| Lisp | Loom |
|---|---|
| S-expressions are normally the source language. | S-expressions are the canonical model-emission view of a CBOR AST. |
| Symbols and variable names carry meaning. | Variables use nameless de Bruijn indices such as `(var 0)`. |
| Files, modules, or bindings commonly identify code. | A definition is identified by the SHA-256 hash of its canonical bytes. |
| Whitespace, formatting, and often equivalent spellings may vary. | Every accepted program has exactly one canonical surface spelling. |
| Macros can extend or transform the language's syntax. | Loom has a fixed, grammar-constrained node vocabulary. |
| Typing depends on the Lisp dialect and may be dynamic or optional. | Types are intrinsic to definitions and binders. |
| Effects are ordinarily calls or runtime conventions. | Effects occur in function types and dangerous operations require explicit capability values. |
| Running the program is the primary semantic test. | Loom additionally represents verification obligations and evidence. |
| The language is primarily designed for human authors. | The representation is primarily designed for constrained generation by agents. |

Loom retains the useful Lisp property that code has a simple tree structure.
It deliberately gives up Lisp's extensible syntax, loose textual equivalence,
and name-centered programming model in exchange for deterministic identity,
grammar-constrained generation, explicit effects, and mechanical auditability.

A better analogy is therefore **a readable compiler IR written with Lisp
parentheses**, not a new Lisp dialect.

## Larger Loom program

This definition accepts a capability for Loom's builtin `clock` ability, reads
the wall clock, and handles both clock operations locally. The following is an
indented display projection for readability:

```loom
(def
  (fn (cap 0xe6eb1adefeb5a68998deb5f6840f95be2bd5540650fda7b31e79e7440ba2a51d)
      ()
      I64)
  (lam (cap 0xe6eb1adefeb5a68998deb5f6840f95be2bd5540650fda7b31e79e7440ba2a51d)
    (handle 0xe6eb1adefeb5a68998deb5f6840f95be2bd5540650fda7b31e79e7440ba2a51d
      (perform 0xe6eb1adefeb5a68998deb5f6840f95be2bd5540650fda7b31e79e7440ba2a51d 0 ())
      ((0 (app (var 0) (lit i64 7)))
       (1 (app (var 0) (lit unit))))
      (var 0))))
```

The empty outer effect row `()` shows that the handler discharges the clock
effect. Operation 0 (`wallMillis`) resumes its continuation with the synthetic
time `7`. Operation 1 (`sleepMillis`) resumes with `Unit`. In each operation
clause `(var 0)` is the continuation; in the return clause it is the value
produced by the handled computation.

The long value is the content hash of the builtin clock ability declaration,
not a human-chosen name. The actual accepted surface is the same tree on exactly
one line:

```loom
(def (fn (cap 0xe6eb1adefeb5a68998deb5f6840f95be2bd5540650fda7b31e79e7440ba2a51d) () I64) (lam (cap 0xe6eb1adefeb5a68998deb5f6840f95be2bd5540650fda7b31e79e7440ba2a51d) (handle 0xe6eb1adefeb5a68998deb5f6840f95be2bd5540650fda7b31e79e7440ba2a51d (perform 0xe6eb1adefeb5a68998deb5f6840f95be2bd5540650fda7b31e79e7440ba2a51d 0 ()) ((0 (app (var 0) (lit i64 7))) (1 (app (var 0) (lit unit)))) (var 0))))
```

The prototype parser, scope checker, declaration resolver, and effect-directed
checker all accept this canonical form. Its authoritative, regression-tested
copy is [`05_clock_handler.loom.sexpr`](../prototype/examples/05_clock_handler.loom.sexpr).
