# Masked-generation experiment — Phase A results, with Phase B condition 4

**Run (UTC):** 2026-08-15T04:26:07Z  
**Backend:** llama-cpp  
**Model identity:** Qwen2.5-Coder-7B-Instruct GGUF Q4_K_M  
**Hardware:** g2-standard-4 L4 24GB  
**Sampling:** {"temperature": 0.8}  
**Seeds:** [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]  
**Token budget per task:** 512 (max 512 per draw, max 32 draws)  
**Leave-one-out examples:** True  
**Draws recorded:** 188 in 1958.715 s  
**Resolver objects:** {"ability": 8, "data": 4, "definition": 26, "extern": 9}  
**Contract versions:** {"declarations": "1.0", "parser": "1.0", "policies": "1.0", "references": "1.0", "refinements": "1.0", "scope": "1.0", "typecheck": "1.1"}

Condition 4 (type-directed per-token masking) ran; its masking numbers are in their own section below. The failure-distribution gate stays a conditions-2-and-3 table by rule.

## R3 metrics per condition × regime

| condition | regime | attempts | draws | tokens | accepted | acc/1k tok | semantic | sem rate | tok to 1st | redraws | distinct acc | repeat rate | mean lat s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gbnf+typemask | held_out | 96 | 188 | 49152 | 4 | 0.081 | 0 | 0.0 | — | 92 | 2 | 0.5 | 10.3342 |

## Funnel outcome by condition × regime

| condition | regime | parse | scope | references | typecheck | accepted |
|---|---|---|---|---|---|---|
| gbnf+typemask | held_out | 95 | 1 | 7 | 81 | 4 |

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

**Masked draws:** 188  
**Mask steps:** 49152  
**Mask time:** 98.224938 s (0.001998391 s/token; 0.005147401 s/token uncached)  
**Mask share of masked-draw latency:** 0.0506  
**Pruners enabled:** de-bruijn, goal-type, ref-hash  
**Vocabulary:** 152064 tokens  
**Liveness fallbacks:** 3 (steps where the type layer would have emptied a non-empty syntax mask)

### Tokens pruned and time spent, by layer

| layer | tokens pruned | evaluations | seconds |
|---|---|---|---|
| de-bruijn | 514107 | 233788 | 0.200326 |
| goal-type | 73627600 | 304197 | 0.396743 |
| ref-hash | 149895433 | 231244 | 0.27658 |
| syntax | 7229388439 | 49152 | 97.351287 |

Pruner seconds are *uncached* evaluation time — the marginal cost of the check. The combined transition and mask caches are part of the design, not an artefact of the measurement, and their hit rate is in the per-draw records.

### Prediction 5 — is Python-side masking overhead material?

Prediction 5 said masking overhead would be *material relative to local decode speed* but dominated by model latency. The share below is that number: mask time over total masked-draw latency, both measured on the same transport in the same process, so it is a like-for-like ratio rather than a cross-transport comparison.

- **Mask share of masked-draw latency: 0.0506** — the figure to score against.
- Warm: 0.001998391 s/token. Cold: 0.005147401 s/token. Score against both; the caches are part of the design, so the warm number is what a run actually pays and the cold one bounds it.

## Outstanding by rule, not by omission

- R3's hand-scored rubric on held-out successes is outstanding for 0 draws that met the mechanical floor. The metric is partly human and this line is what keeps it from being silently dropped.
- Prediction 5 is scored in the masking section above. Prediction 4 needs a baseline to compare against: set `baseline_summary` in the run config to a Phase A `summary.json` and the R5 table appears here.

