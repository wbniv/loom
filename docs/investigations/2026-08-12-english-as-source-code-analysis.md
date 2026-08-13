# Analysis — "Programming languages will soon be unnecessary"

**Date:** 2026‑08‑12
**Source:** Essay pasted into session (unattributed). Thesis: high-level
languages are becoming the invisible intermediate layer between English and
the machine, and will disappear the way bytecode disappeared from human view.
**Type:** Argument analysis, not an incident. No repo surface; no mockups.
**See also:** [Loom — design sketch of an agent-native language](2026-08-12-loom-agent-native-language-sketch.md),
which tests §4's claim by actually doing the design.

---

## Conclusion

The essay's engine is a single analogy: *English is to generated code what
source code is to bytecode — an upper layer that makes the one below it
invisible.* The analogy is genuinely illuminating about workflow, and its
near-term prediction (most code will not be written by hand) is probably
right. But the analogy fails at its load-bearing joint, and the essay's
conclusion — that human-readable languages, and with them the notion of "good
code," become pointless — does not follow.

The joint that fails: **bytecode may go unread because the translator above
it is deterministic, semantics-preserving, and vetted once for all
programs.** Nobody audits the IL that `javac` emits because `javac` itself
carries the trust — verify the compiler once and every compilation inherits
the guarantee. An LLM agent is a probabilistic translator vetted never. Its
output must be checked *per program*, and the human-readable middle artifact
is precisely the surface on which that checking is possible. The essay
removes the checkpoint and then proposes "does it work?" as the replacement —
which is the weakest assurance regime software engineering knows.

What's actually likely: hand-*writing* code declines steeply; hand-*reading*
persists and grows in value; and the middle layer evolves toward more
machine-checkable formality (richer types, contracts, properties), not toward
an opaque agent-private notation — because the demand for assurance rises,
not falls, when authorship is automated.

## The argument, claim by claim

| # | Claim | Verdict |
|---|---|---|
| 1 | Code is now the "intermediate language" between English and the machine | Fair as a description of agentic workflow |
| 2 | Nobody writes IL by hand, so soon nobody will write code by hand | Plausible for the *volume* of hand-written code |
| 3 | Therefore the human-readable middle layer can be discarded | **Non sequitur** — readability's remaining job is verification, not authorship |
| 4 | Agents will eventually write any language from its spec alone, without training data | Plausible in principle; ignores ecosystem gravity |
| 5 | Agents will design a language that "meets their needs perfectly" | Possible at the margins; the agent-optimal language is plausibly *more* formal and legible, not less |
| 6 | Quality collapses to "does it work or not?" | The central error — see below |

## Where the analogy holds

Credit where due. The layering observation is real: in an agentic loop the
human expresses intent in prose, the agent produces TypeScript or Rust, and a
toolchain produces machine code. Each historical layer (assembly → compiled
languages → managed runtimes) did push the layer below it out of most
programmers' daily view, and "the abstractions never end" is a good prior.
It is also true that today's agents write mostly in languages that are
popular *because* of training-data mass, and that a sufficiently capable
model reading a language specification could write competent code in a
language it has never seen — that is roughly what human engineers do with a
new language, and models already do a weak version of it with internal DSLs.

## Where it breaks

### 1. A compiler is trusted once; a generator must be checked every time

Compilation is deterministic and semantics-preserving by construction, and
the guarantee is amortised: one vetted compiler covers every program it will
ever compile. That amortisation is *the entire reason* IL can go unread.
Generation by a stochastic model has the opposite structure — no
semantics-preservation guarantee exists even in principle, because the input
(prose) has no formal semantics to preserve. So the checking burden lands on
each individual artifact, per change, forever. Deleting the human-readable
layer doesn't delete that burden; it deletes the only affordable place to
discharge it.

### 2. English is not a specification language — the precision has to live somewhere

The essay treats prose as the new source code, but prose underdetermines
behaviour: "handle retries sensibly" compiles to nothing. Every real system
is a mountain of decisions — boundary conditions, concurrency, failure modes,
rounding — that were never in anyone's prompt and currently live *only in the
code*. If the middle layer is discarded, those decisions must be recorded in
some other notation precise enough to be unambiguous and stable enough to be
diffed, reviewed, and versioned. A notation with those properties **is a
programming language**. The middle step doesn't vanish; it moves, and
whatever it moves into inherits the same requirements. Dijkstra made this
argument about natural-language programming in
[EWD667](https://www.cs.utexas.edu/users/EWD/transcriptions/EWD06xx/EWD667.html)
in 1978, and nothing about LLMs changes it: the value of a formal notation is
that it *narrows* what you can say until what you said is exactly one thing.

### 3. "Does it work?" is not a measurement

Testing demonstrates the presence of desired behaviour on the cases you
thought to try; it cannot demonstrate the absence of undesired behaviour —
Dijkstra again, but also every CVE ever filed against software that "worked."
Three specific collapses hide inside the phrase:

- **Security.** Exploits live exactly in the behaviours no acceptance test
  exercises. A codebase judged solely by observable happy-path behaviour is a
  codebase whose failure modes are unexamined by anyone — the generating
  agent included, if nothing in the loop rewards examining them.
- **The derivative.** "Good code" was never an aesthetic; it is a prediction
  about the cost of the *next* change. Systems live for years and are judged
  by how safely they absorb requirement changes. "Works today" says nothing
  about that, and an illegible codebase makes the next change a fresh
  act of faith.
- **Spec recovery.** In mature systems, the code is the only complete record
  of what the system actually does. When behaviour surprises you, reading is
  how you find out whether the surprise is a bug in the code or a gap in your
  intent. If nothing human-legible exists, "is this a bug?" becomes
  unanswerable even in principle — there is nothing to compare the behaviour
  *against* except recollections of prompts.

### 4. Languages are for the writer too — and the writer is now the agent

The essay frames types, loops, and object structure as concessions to human
limitation. But a type system is generation-time error rejection: it is
machinery that refuses whole classes of wrong programs before they run, and
it disciplines an LLM exactly as it disciplines a human. Agents measurably do
better with compilers, linters, and borrow checkers in the loop, because the
feedback is deterministic ground truth rather than more sampling. So if an
agent designed a language that "meets its needs perfectly," its needs are:
maximal static checkability, unambiguous semantics, machine-verifiable
contracts. That language looks like *more* structure — closer to Rust plus
contracts than to an opaque token soup. The essay's own premise, followed
honestly, predicts richer formal languages rather than none. And a formally
structured language is largely human-legible as a side effect, because
legibility and static analysability come from the same properties:
explicitness, locality, compositionality.

### 5. Ecosystem gravity

The value of Python was never syntax; it is hundreds of thousands of
packages, twenty years of battle-tested runtimes, debuggers, profilers, and
CVE response processes. An agent that abandons the ecosystem re-implements
(and re-verifies) the world from scratch, in a notation no existing tool can
lint, fuzz, or audit. Interoperability adds a second wall: mixed fleets of
agents from different vendors, plus regulated industries whose auditors
demand inspectable artifacts, give every party an incentive to converge on
shared, legible substrates. Private languages fragment exactly the network
effects that make code generation cheap in the first place.

## The essay's two open questions

**Will agentic AI choose its own languages and tools?** At the margins, yes —
and it already does: agents pick libraries, emit build configs, and generate
small DSLs today, and compilers have used machine-oriented IRs (LLVM IR,
WebAssembly) for decades. The defensible version of the essay's prediction is
that agents will increasingly *target* such IRs directly for narrow, fully
specified transformations, and that new languages will be designed with
agents as first-class users. The indefensible version is a general-purpose
language that is deliberately illegible to humans: it forfeits the ecosystem
(§5), concentrates all assurance in behavioural testing (§3), and — the
alignment point the essay never raises — removes the principal channel by
which anyone could notice an agent's output doing something other than what
was asked.

**What are the risks of blindly accepting AI-generated codebases?** The essay
asks this and then answers, in effect, "none, eventually." The actual list:
verification asymmetry (generation is now cheaper than review, so unreviewed
code accretes at the rate its checks are shallow); security debt concentrated
in never-exercised paths; monoculture — correlated defects stamped across
thousands of codebases by the same model families, turning single bugs into
systemic events; and the skills pipeline the essay itself worries about, then
waves off. That last one is self-undermining: if no juniors become seniors,
the population able to check the middle layer shrinks *while* the essay's
proposal makes checking impossible by construction. "We won't need to know
what good code is" is not a prediction there; it is capitulation dressed as
inevitability.

## What happens instead — a falsifiable version

1. **Hand-written code volume keeps falling.** The essay is right here, and
   it matters: authorship as a career skill is depreciating.
2. **The durable artifact moves up, but stays formal.** Specs, acceptance
   tests, and property definitions become the reviewed, versioned contract —
   prose alone never does, because prose cannot be diffed against behaviour.
3. **Languages evolve toward the agent-optimal point:** more static
   verification, contracts, and effect tracking — legible formality, since
   analysability and legibility are the same properties (§4).
4. **Reading outlives writing.** Review, audit, and debugging remain human
   competencies precisely because they are the per-artifact check a
   stochastic translator cannot amortise away (§1).
5. **If a true agent-native target emerges,** it looks like verified
   compilation — an IR that carries machine-checkable proofs of its own
   properties — because that is the only form in which "nobody reads it" is
   ever safe. That is not the death of programming languages; it is their
   apotheosis.

Falsifier for this analysis: a production system of real scale whose only
maintained artifact is prose plus an illegible generated blob, surviving
multiple years of requirement changes and a security audit, with no formal
intermediate representation anyone can inspect. If those start existing and
persisting, the essay was right and this document was wrong.
