# Masked-generation experiment — Phase A results, with Phase B condition 4

**Run (UTC):** 2026-08-14T19:01:47Z  
**Backend:** llama-cpp  
**Model identity:** Qwen2.5-Coder-7B-Instruct GGUF Q4_K_M  
**Hardware:** g2-standard-4 L4 24GB  
**Sampling:** {"temperature": 0.8}  
**Seeds:** [1, 2, 3]  
**Token budget per task:** 512 (max 512 per draw, max 32 draws)  
**Leave-one-out examples:** True  
**Draws recorded:** 773 in 4041.43 s  
**Resolver objects:** {"ability": 8, "data": 4, "definition": 26, "extern": 9}  
**Contract versions:** {"declarations": "1.0", "parser": "1.0", "policies": "1.0", "references": "1.0", "refinements": "1.0", "scope": "1.0", "typecheck": "1.1"}

Condition 4 (type-directed per-token masking) ran; its masking numbers are in their own section below. The failure-distribution gate stays a conditions-2-and-3 table by rule.

## R3 metrics per condition × regime

| condition | regime | attempts | draws | tokens | accepted | acc/1k tok | semantic | sem rate | tok to 1st | redraws | distinct acc | repeat rate | mean lat s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gbnf+typemask | few_shot | 78 | 200 | 39936 | 19 | 0.476 | 1 | 0.0128 | 429.0 | 122 | 11 | 0.4211 | 4.631 |
| gbnf+typemask | full_corpus | 78 | 196 | 39936 | 55 | 1.377 | 5 | 0.0641 | 152.0 | 118 | 9 | 0.8364 | 8.7971 |
| gbnf+typemask | held_out | 24 | 47 | 12288 | 1 | 0.081 | 0 | 0.0 | — | 23 | 1 | 0.0 | 10.2609 |
| gbnf+typemask | none | 78 | 330 | 39936 | 34 | 0.851 | 0 | 0.0 | — | 252 | 19 | 0.4412 | 2.6135 |

## Funnel outcome by condition × regime

| condition | regime | parse | scope | references | typecheck | accepted |
|---|---|---|---|---|---|---|
| gbnf+typemask | few_shot | 77 | 6 | 36 | 62 | 19 |
| gbnf+typemask | full_corpus | 77 | 1 | 5 | 58 | 55 |
| gbnf+typemask | held_out | 24 | 0 | 4 | 18 | 1 |
| gbnf+typemask | none | 78 | 10 | 30 | 178 | 34 |

## Failure distribution by checker layer — the Phase B gate

Grammar-constrained draws only (conditions 2 and 3), which is what R2.1 asks for: Phase B prunes first whatever layer actually kills most GBNF-valid generations.

| regime | parse | scope | references | typecheck | accepted | reject rate |
|---|---|---|---|---|---|---|
| **all** | 0 | 0 | 0 | 0 | 0 | 100.0% |

**No grammar-constrained rejections recorded.**

De Bruijn share of scope failures (heuristic, message-based): None

## Error localization — most frequent failing paths


## Masking overhead — condition 4 (R3)

Comparability boundary (R1): condition 4 decodes on the in-process transport, conditions 1-3 on `llama-server`, so **wall clock is not comparable across that line**. The comparable numbers are accepted definitions per token (the budget rule) and the per-token mask overhead below, which is measured inside the masker.

**Masked draws:** 773  
**Mask steps:** 132096  
**Mask time:** 416.479895 s (0.003152858 s/token; 0.006686029 s/token uncached)  
**Mask share of masked-draw latency:** 0.1042  
**Pruners enabled:** de-bruijn, goal-type, ref-hash  
**Vocabulary:** 152064 tokens  
**Liveness fallbacks:** 123 (steps where the type layer would have emptied a non-empty syntax mask)

### Tokens pruned and time spent, by layer

| layer | tokens pruned | evaluations | seconds |
|---|---|---|---|
| de-bruijn | 1503942 | 855327 | 0.700826 |
| goal-type | 220842284 | 1064708 | 1.337295 |
| ref-hash | 382401243 | 847860 | 0.975055 |
| syntax | 19420054375 | 132096 | 413.466706 |

Pruner seconds are *uncached* evaluation time — the marginal cost of the check. The combined transition and mask caches are part of the design, not an artefact of the measurement, and their hit rate is in the per-draw records.

### Prediction 5 — is Python-side masking overhead material?

Prediction 5 said masking overhead would be *material relative to local decode speed* but dominated by model latency. The share below is that number: mask time over total masked-draw latency, both measured on the same transport in the same process, so it is a like-for-like ratio rather than a cross-transport comparison.

- **Mask share of masked-draw latency: 0.1042** — the figure to score against.
- Warm: 0.003152858 s/token. Cold: 0.006686029 s/token. Score against both; the caches are part of the design, so the warm number is what a run actually pays and the cold one bounds it.

## R5 — condition 4 against conditions 2 and 3

Not computed: baseline summary /opt/loom/repo/docs/results/2026-08-14-phase-a-summary.json unreadable: [Errno 2] No such file or directory: '/opt/loom/repo/docs/results/2026-08-14-phase-a-summary.json'


## Outstanding by rule, not by omission

- R3's hand-scored rubric on held-out successes is outstanding for 0 draws that met the mechanical floor. The metric is partly human and this line is what keeps it from being silently dropped.
- Prediction 5 is scored in the masking section above. Prediction 4 needs a baseline to compare against: set `baseline_summary` in the run config to a Phase A `summary.json` and the R5 table appears here.


## R5 — computed locally (2026‑08‑14)

The remote R5 section above is empty because the repo tarball shipped to the
instance does not carry `docs/`, so the configured `baseline_summary` path was
unreadable there. The comparison below is hand-computed from this run's
`summary.json` and the committed Phase A summary — same metric, same budget
rule (accepted definitions per 1,000 budget tokens).

| regime | gbnf (c2) | gbnf+rejection (c3) | **gbnf+typemask (c4)** | c4 vs c3 |
|---|---|---|---|---|
| none | 0.326 | 0.501 | **0.851** | **+70 %** |
| few_shot | 0.376 | 0.326 | **0.476** | **+46 %** |
| full_corpus | **1.452** | 1.377 | 1.377 | ±0 |
| held_out | 0.000 | 0.081 | 0.081 | ±0 |

Semantic successes: c4 full_corpus **5** (c2: 4, c3: 3), few_shot **1**
(c2: 0, c3: 3), held_out 0 everywhere. Repeat rate in full_corpus: c4 0.836
vs c2 0.879 — masking did not collapse diversity.

Funnel movement against Phase A's grammar conditions (rates over draws):
scope failures **268 → 17** (the de Bruijn pruner's kill), references
115 → 75, typecheck 590 → 316 (now 41 % of draws — the dominant survivor,
as the abstention list predicts), parse/truncation ~unchanged (~33 %).

**Verdict in one line: per-token masking weakly dominates rejection
sampling — it never loses, and wins large exactly where examples are
scarce — but it does not beat plain grammar sampling in the corpus-rich
regime (1.377 vs the 1.452 bar).**
