# Masked-generation experiment — Phase A results

**Run (UTC):** 2026-08-14T11:14:03Z  
**Backend:** llama-server  
**Model identity:** Qwen2.5-Coder-7B-Instruct GGUF Q4_K_M (Qwen/Qwen2.5-Coder-7B-Instruct-GGUF @ HF main, 2026-08-13)  
**Hardware:** g2-standard-4 L4 24GB  
**Sampling:** {"temperature": 0.8}  
**Seeds:** [1, 2, 3]  
**Token budget per task:** 512 (max 512 per draw, max 32 draws)  
**Leave-one-out examples:** True  
**Draws recorded:** 2335 in 11845.577 s  
**Resolver objects:** {"ability": 8, "data": 4, "definition": 26, "extern": 9}  
**Contract versions:** {"declarations": "1.0", "parser": "1.0", "policies": "1.0", "references": "1.0", "refinements": "1.0", "scope": "1.0", "typecheck": "1.1"}

Conditions 1-3 only. Condition 4 (type-directed per-token masking) is Phase B and is gated on the failure distribution below.

## R3 metrics per condition × regime

| condition | regime | attempts | draws | tokens | accepted | acc/1k tok | semantic | sem rate | tok to 1st | redraws | distinct acc | repeat rate | mean lat s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gbnf | few_shot | 78 | 199 | 39936 | 15 | 0.376 | 0 | 0.0 | — | 121 | 7 | 0.5333 | 4.6429 |
| gbnf | full_corpus | 78 | 198 | 39936 | 58 | 1.452 | 4 | 0.0513 | 120.8 | 120 | 7 | 0.8793 | 9.056 |
| gbnf | held_out | 24 | 42 | 12288 | 0 | 0.0 | 0 | 0.0 | — | 18 | 0 | 0.0 | 11.1305 |
| gbnf | none | 78 | 397 | 39936 | 13 | 0.326 | 0 | 0.0 | — | 319 | 10 | 0.2308 | 2.2484 |
| gbnf+rejection | few_shot | 78 | 203 | 39936 | 13 | 0.326 | 3 | 0.0385 | 337.0 | 125 | 7 | 0.4615 | 4.5791 |
| gbnf+rejection | full_corpus | 78 | 199 | 39936 | 55 | 1.377 | 3 | 0.0385 | 28.0 | 121 | 4 | 0.9273 | 9.0512 |
| gbnf+rejection | held_out | 24 | 41 | 12288 | 1 | 0.081 | 0 | 0.0 | — | 17 | 1 | 0.0 | 11.3052 |
| gbnf+rejection | none | 78 | 392 | 39936 | 20 | 0.501 | 0 | 0.0 | — | 314 | 11 | 0.45 | 2.2887 |
| unconstrained | few_shot | 78 | 153 | 39936 | 1 | 0.025 | 0 | 0.0 | — | 75 | 1 | 0.0 | 5.82 |
| unconstrained | full_corpus | 78 | 142 | 39936 | 17 | 0.426 | 3 | 0.0385 | 199.3 | 64 | 3 | 0.8235 | 10.8123 |
| unconstrained | held_out | 24 | 35 | 12288 | 0 | 0.0 | 0 | 0.0 | — | 11 | 0 | 0.0 | 12.4286 |
| unconstrained | none | 78 | 334 | 39936 | 0 | 0.0 | 0 | 0.0 | — | 256 | 0 | 0.0 | 2.4379 |

## Funnel outcome by condition × regime

| condition | regime | parse | scope | references | typecheck | accepted |
|---|---|---|---|---|---|---|
| gbnf | few_shot | 78 | 29 | 28 | 49 | 15 |
| gbnf | full_corpus | 78 | 7 | 3 | 52 | 58 |
| gbnf | held_out | 24 | 0 | 0 | 18 | 0 |
| gbnf | none | 81 | 95 | 28 | 180 | 13 |
| gbnf+rejection | few_shot | 77 | 34 | 20 | 59 | 13 |
| gbnf+rejection | full_corpus | 78 | 9 | 4 | 53 | 55 |
| gbnf+rejection | held_out | 24 | 0 | 0 | 16 | 1 |
| gbnf+rejection | none | 83 | 94 | 32 | 163 | 20 |
| unconstrained | few_shot | 135 | 3 | 6 | 8 | 1 |
| unconstrained | full_corpus | 104 | 2 | 0 | 19 | 17 |
| unconstrained | held_out | 21 | 0 | 0 | 14 | 0 |
| unconstrained | none | 334 | 0 | 0 | 0 | 0 |

## Failure distribution by checker layer — the Phase B gate

Grammar-constrained draws only (conditions 2 and 3), which is what R2.1 asks for: Phase B prunes first whatever layer actually kills most GBNF-valid generations.

| regime | parse | scope | references | typecheck | accepted | reject rate |
|---|---|---|---|---|---|---|
| none | 164 | 189 | 60 | 343 | 33 | 95.8% |
| few_shot | 155 | 63 | 48 | 108 | 28 | 93.0% |
| full_corpus | 156 | 16 | 7 | 105 | 113 | 71.5% |
| held_out | 48 | 0 | 0 | 34 | 1 | 98.8% |
| **all** | 523 | 268 | 115 | 590 | 175 | 89.5% |

**Dominant post-syntax failure layer:** `typecheck` (590 of 1671 grammar-constrained draws; ties break in funnel order, so read the row above before acting on a close call). This is the layer Phase B's incremental type-state masker prunes first.

De Bruijn share of scope failures (heuristic, message-based): 0.9776

## Error localization — most frequent failing paths

**scope** — `definition.type.domain` ×32, `definition.term.parameter-type` ×23, `definition.type.row[1]` ×17, `definition.term.argument` ×15, `definition.term.condition` ×15
**references** — `definition.term` ×30, `definition.term.body` ×26, `definition.type` ×10, `definition.term.body.arms[1].body` ×8, `definition.type.domain` ×8
**typecheck** — `definition.term` ×330, `definition.term.body` ×45, `definition.term.body.condition` ×37, `definition.term.body.arms[0].body` ×30, `definition.term.body.body` ×30

## Outstanding by rule, not by omission

- R3's hand-scored rubric on held-out successes is outstanding for 0 draws that met the mechanical floor. The metric is partly human and this line is what keeps it from being silently dropped.
- Predictions 4 and 5 (rejection sampling versus masking, and masking overhead) cannot be scored from Phase A alone: both compare against condition 4.

