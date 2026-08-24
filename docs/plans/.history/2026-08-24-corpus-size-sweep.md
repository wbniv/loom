| Date | Change |
|------|--------|
| [2026-08-24](https://github.com/wbniv/loom/commit/80746d3) | Pre-register the corpus-size sweep: nested 8/15/25/41-def stores, LR trend test |

<!--history-meta v1
80746d3	author	Will Norris
80746d3	added	342
80746d3	deleted	0
80746d3	files	1
80746d3	body	Closes the diversity-harvest report's "what this does not license" gap:\nevery pairwise comparison behind "acceptance tracks mass, not quality" was\nnon-significant (p=0.29-1.00) because each recorded size differed in draw\nselection as well as count. This sweep removes that confound: one 55-item\ncandidate pool (recorded accepted, non-heldout, not-already-curated\nidentities), one deterministic identity-hash order, four nested prefixes\n(8/15/25/41 defs) built via harvest_select's existing size-match policy.\nNesting verified by direct hash-set inclusion, not assumed.\n\nPre-registered before any GPU run: logistic-regression LR test on\nlogit(accepted) ~ log1p(defs), pooled across the reused 0-def curated\nanchor (1.377 acc/1k, not re-run) plus the four fresh arms. Power is\nhonest: ~38% at the ~198-draw/arm matched budget under a planning\nassumption interpolated from the two ends of the range already measured\n(curated 0.2806, generated-41 0.3495 per-draw) — better than any pairwise\nalternative (0-vs-41 Fisher ~27%, adjacent-gap-sized ~8%), still\nunderpowered by conventional standards, stated as such rather than treated\nas a refutation if null.\n\nConfigs are diverse_followup.config.json with only store_export/output_dir\nchanged (matched seeds/regimes/pruners -> matched draw budgets, confirmed\n102 cells/arm via --dry-run on all four). Stub-backend check confirms\nsweep41 fits n_ctx at 1.84x headroom and prompt tokens grow monotonically\nwith declared store size.\n\nNo GPU run yet -- stores, configs and pre-registration only.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>
-->
