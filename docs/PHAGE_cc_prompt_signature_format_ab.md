# PHAGE — Claude Code Build Brief: Signature Format A/B

> **Build-history record.** Written during construction and left unedited.
> Figures and `file:line` citations here may be superseded. `docs/writeup.md`
> and `README.md` are the current, audited statements.

**Target path in repo:** `docs/PHAGE_cc_prompt_signature_format_ab.md`
**Date:** 2026-08-22
**Depends on:** `data/recognition_pairs.jsonl` (65 labeled records, commit `1c4ce83`),
`scripts/tune_threshold.py` (commit `6866b42`)

The tuned threshold produced TPR 1.00 / **FPR 0.72** against hard negatives. That is a
functional failure: most genuinely novel attacks would be wrongly short-circuited as
repeats, so the fleet would stop being tested after the first landed payload.

Diagnosis: every signature embeds `target=... archetype=... tools=[...]` verbatim before
the injection text. Shared boilerplate raises pairwise similarity uniformly, compressing
the real intent difference into noise. Evidence it's compression rather than absence of
signal: 9 of 25 hard negatives already separate cleanly above variant's max (0.5824),
while 16 collapse into the variant range.

**The existing dataset is reused as-is.** Only the embedded string changes, not the
labeled intents, so all 65 pairs stay valid across every format tested here.

---

## 0. Scope

### IN

1. Parameterise `_signature_text` over four formats (Task 1)
2. Measure all four against the existing dataset (Task 2)
3. Adopt the winner and re-tune, or stop and report if none qualifies (Task 3)

### OUT

- Regenerating `data/recognition_pairs.jsonl` — it is fixed input here
- Any new LLM call at record or recognition time. If the answer turns out to be
  canonicalised intent summaries, that is a separate brief with a latency budget
  attached; do not build it here.
- Demo, dashboard, video, write-up, repo visibility
- Changing the recognition decision rule (still nearest-neighbour distance vs. a single
  threshold). Rank-based and margin-based rules are out of scope for this brief.

---

## 1. Task 1 — parameterise the signature text

Refactor `_signature_text` to take a format identifier. It stays the single shared
function called by both `record()` and `recognize()` — the symmetry constraint is
unchanged and non-negotiable.

| ID | Embedded text |
|---|---|
| `F0` | current: `target=` + `archetype=` + `tools=[...]` prefix, then injection text |
| `F1` | injection text only, no prefix of any kind |
| `F2` | `archetype=` prefix only, then injection text |
| `F3` | `tools=[...]` prefix only, then injection text |

`F0` is the baseline and must reproduce the numbers already reported (variant median
≈ 0.4976, hard_negative median ≈ 0.4838); if it doesn't, the harness is wrong — stop and
report before interpreting anything else.

Default remains `F0` until Task 3 changes it.

---

## 2. Task 2 — measure

Extend `scripts/tune_threshold.py` (or add a sibling script, committed either way) to run
the full sweep once per format.

**Isolation:** each format writes its anchors to its own eval scope, e.g.
`{"app_name": "phage-eval-f1"}`. Anchors from one format must never be retrievable while
querying another — a cross-format nearest neighbour silently corrupts every number.
Delete every eval memory at the end of each format's run and verify empty before the next
starts.

**Retrieval stays top-1 over the whole anchor pool.** That is the real deployment
condition: a hard negative gets 25 chances to sit near something. Do not narrow the query
to its own paired anchor.

Report per format:

- variant and hard_negative: min / median / max
- **AUC** over variant vs. hard_negative (Mann–Whitney: the fraction of
  variant × hard_negative pairs where the variant distance is smaller). Below 0.5 means
  the ranking is inverted and no threshold can work.
- **FPR at TPR = 1.00** and **FPR at TPR ≥ 0.95**
- **Top-1 identity accuracy for variants** — how often a variant's nearest neighbour is
  its own anchor rather than some other anchor in the pool. Report this even though it
  isn't the decision rule; if it is high while FPR is bad, that is a strong signal worth
  knowing about.
- `cross_target` median, to see whether dropping `target=` moves fleet transfer

---

## 3. Task 3 — adopt or stop

**Selection:** lowest FPR at TPR ≥ 0.95. Ties break toward the simpler format.

**Qualifying bar: FPR ≤ 0.25.** If the best format clears it, set that format as the
default, re-tune `RECOGNITION_DISTANCE_THRESHOLD` against it using the existing Rule 1 /
Rule 2 logic, update the constant's comment to cite this brief and the new FPR, and re-run
the full suite.

**If no format clears 0.25: stop.** Do not adopt a marginal winner, do not invent a new
decision rule, do not start on intent summarisation. Report the four tables and stop —
that outcome means the mechanism needs a different approach and the choice is not
Claude Code's to make unilaterally under deadline.

Commit message if a format is adopted:
`archivist: strip shared scaffolding from signature text, retune threshold`

---

## 4. Output

In this order, nothing added or omitted.

1. `F0` reproduction check — the baseline medians, and whether they match the previously
   reported values.
2. One table per format (`F0`–`F3`): variant min/median/max, hard_negative min/median/max,
   AUC, FPR@TPR=1.00, FPR@TPR≥0.95, variant top-1 identity accuracy, cross_target median.
3. The winning format, its FPR at TPR ≥ 0.95, and whether it clears the 0.25 bar.
4. If adopted: the new threshold value, its `file:line`, and the resulting TPR/FPR.
   If not adopted: state plainly that nothing qualified and that no format change was made.
5. Eval-scope cleanup confirmation for every scope used.
6. Full pytest output of the final run.
7. Anything in scope you did not do, and why.
