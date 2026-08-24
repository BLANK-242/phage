# PHAGE — Claude Code Build Brief: Leave-One-Archetype-Out Re-evaluation

> **Build-history record.** Written during construction and left unedited.
> Figures and `file:line` citations here may be superseded. `docs/writeup.md`
> and `README.md` are the current, audited statements.

**Target path in repo:** `docs/PHAGE_cc_prompt_loao_eval.md`
**Date:** 2026-08-22
**Depends on:** `data/recognition_pairs.jsonl` (commit `1c4ce83`),
`scripts/ab_test_signature_formats.py` (commit `7773494`)

The A/B produced FPR 0.72 at TPR 1.00 and AUC ≈ 0.51 for F0. That measurement is
invalid, and the A/B's own root-cause finding is why: hard negatives are drawn from the
same 8-template library as the anchors, and 6 of 8 archetypes have anchors spanning 3–4
targets. A hard-negative query is therefore often a near-copy of **another anchor already
in the pool**, so recognizing it is correct behaviour scored as an error.

Corroboration: under F1, hard_negative min drops to 0.4091 — the minimum distance across
the F1 hard negatives — **not** the identical-text floor, which measures
0.3861411047948597 (`scripts/probe_distance_output.txt`) —
while variants sit at 0.5863+, inverting AUC to 0.13. Only twin-matching explains that.

Meanwhile variant top-1 identity accuracy under F0 is **1.00 (25/25)**: every variant's
nearest neighbour is its own anchor. The retrieval mechanism works. The negative class
does not.

This brief re-partitions the existing data so that negatives are genuinely unseen. **No
regeneration, no new payloads, no mechanism change.**

---

## 0. Scope

### IN

1. Annotate every record with its true source template (Task 1)
2. Verify the contamination diagnosis directly (Task 2)
3. Leave-one-archetype-out evaluation and re-tune (Task 3)

### OUT

- Regenerating `data/recognition_pairs.jsonl` or calling `_tailor_one()` again
- Changing `_SIGNATURE_FORMAT` — F0 stays; the A/B settled that
- Changing the decision rule away from nearest-neighbour distance vs. threshold
- Any demo, dashboard, video, write-up, or repo-visibility work
- Deleting or rewriting the FPR 0.72 result. It is a real finding about the first
  experimental design and it goes in the write-up alongside the corrected number.

---

## 1. Task 1 — recover the true source template

Every query was drawn from one of the 8 archetype templates, but the JSONL's `archetype`
field records the **anchor's** label, not the query's true source. Add
`query_source_archetype` to every record, recovered by matching query text against the
template library deterministically (longest-common-substring or template-id lookup —
whatever the generator's structure makes reliable).

For `variant` rows this equals `archetype`. For `hard_negative` rows it should differ —
that difference is the whole point. Report any row where the source cannot be identified;
do not guess.

Commit the annotated dataset.

---

## 2. Task 2 — verify the diagnosis before acting on it

Re-run F0 exactly as the A/B did, but record **which anchor each hard negative matched**,
not just the distance.

Report: of the 18 hard negatives that recognized at threshold 0.59, how many matched an
anchor whose archetype equals that negative's `query_source_archetype`?

**This is the falsifiable check.** If most of them matched a same-source anchor, the
contamination diagnosis holds and Task 3 is the right correction. If most matched an
unrelated anchor, the diagnosis is wrong, the mechanism really does over-recognize, and
**you should stop and report rather than proceeding to Task 3.**

---

## 3. Task 3 — leave-one-archetype-out

For each archetype `k` in the 8:

- **Anchor pool:** anchors from all archetypes except `k`
- **Positives:** variants whose own anchor is in that pool
- **Negatives:** all queries with `query_source_archetype == k`

Held-out templates have no twin in the pool, so a recognition is a genuine false
positive. Each fold gets its own isolated eval scope, deleted and verified empty before
the next fold runs.

Pool results across all 8 folds into one distribution and report:

- positives and negatives: min / median / max, and n for each
- AUC (Mann–Whitney)
- FPR at TPR = 1.00 and at TPR ≥ 0.95
- positive top-1 identity accuracy, pooled

**Adoption bar: FPR ≤ 0.25 at TPR ≥ 0.95.** If it clears, re-tune
`RECOGNITION_DISTANCE_THRESHOLD` under the pooled LOAO distribution using the existing
Rule 1 / Rule 2 logic, update its comment to cite this brief and the corrected FPR, and
re-run the full suite. If it does not clear, stop and report — do not adopt a marginal
winner and do not invent a new decision rule.

Commit message if adopted:
`archivist: retune threshold against leave-one-archetype-out evaluation`

---

## 4. Output

In this order, nothing added or omitted.

1. Task 1 — `query_source_archetype` added; counts of `variant` rows where it equals
   `archetype`, `hard_negative` rows where it differs, and any unresolved rows.
2. **Task 2 verdict** — of the hard negatives recognizing at 0.59, how many matched a
   same-source anchor. State plainly whether the contamination diagnosis is confirmed or
   refuted, and whether you proceeded to Task 3.
3. LOAO pooled results — the full metric list above, with n for positives and negatives.
4. Per-fold FPR at the adopted threshold, so fold-to-fold variance is visible.
5. Adoption outcome — new threshold and `file:line`, or a plain statement that nothing
   qualified.
6. Eval-scope cleanup confirmation for all 8 folds.
7. Full pytest output of the final run.
8. Anything in scope you did not do, and why.
