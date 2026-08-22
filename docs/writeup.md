# PHAGE — Write-up

## Methodology

ARCHIVIST's recognition mechanism is a single design: embed a payload's signature text with `text-embedding-005` — at write time (`record()`) and query time (`recognize()`) through the same shared function, so the two paths can never drift apart — and recognize a repeat by nearest-neighbor distance against a tuned threshold (smaller distance = more similar).

A defensible threshold needs a labeled dataset of pairs that should and shouldn't be recognized. We built one from pieces already in the project — no invented attack content: the four-target SAIL fleet crossed with the eight-archetype injection library already in the codebase, producing **variant** pairs (a payload and a real, Gemini-produced structural mutation of it — the same "second pass, different wording" the demo fires), **hard-negative** pairs (a payload against a genuinely different attack intent), and two smaller diagnostic classes (cross-target transfer, and an unrelated-content sanity check). The dataset — 65 labeled records — is committed at `data/recognition_pairs.jsonl`, generation script included, so every number below is reproducible against a fixed artifact rather than cited from memory.

**First measurement, and why it doesn't stand.** Tuned directly against this dataset (variant distances as positives, hard-negative distances as negatives), the threshold sweep reported **TPR 1.00 / FPR 0.72** — a functional failure, since three in four genuinely different attacks would have been wrongly treated as repeats and never re-tested. Rather than accept the number, we tested three alternative signature-text formats against that same baseline — stripping or narrowing the embedded context in different ways, to see whether shared boilerplate was drowning out the actual attack content. All three failed by the same margin or worse, which pointed the diagnosis somewhere else. The real cause was structural: most archetypes in the library are instantiated against three or four different targets, so a "hard negative" — a genuinely different attack, rendered from some other archetype's template — frequently has a near-identical twin from that same template already sitting in the evaluation pool from a different target. Recognizing it was correct retrieval behavior, scored as an evaluation error.

We didn't act on that diagnosis without checking it could be wrong. A separate, falsifiable pass re-ran the same measurement recording *which* memory each recognized hard negative actually matched. Of the 18 hard negatives that recognized at the original threshold, 16 (89%) matched an anchor genuinely sourced from the same archetype as the query — the contamination's predicted fingerprint, not a plausible alternative explanation. Only then did we correct the evaluation design.

**The correction: leave-one-archetype-out.** The dataset was re-partitioned, not regenerated. For each of the eight archetypes in turn, every anchor from that archetype is held out of the pool entirely, and every query genuinely sourced from it (recovered by matching query content against the template library, independent of how the row happened to be labeled) becomes a negative tested against a pool where no twin can exist. A recognition there is now an unambiguous false positive. Results from all eight folds are pooled into one distribution.

## Evaluation

Pooled leave-one-archetype-out results, at the tuned threshold:

| Metric | Result |
|---|---|
| True positive rate | **1.00** (25/25 distinct variants) |
| False positive rate | **0.1833** (11/60 held-out queries) |
| Separation (AUC, Mann–Whitney) | 0.97 |
| Top-1 identity accuracy | 100% (25/25) — every real mutation's nearest match is its own original encounter, not a different one |

TPR is reported at n=25, not at the 175 raw fold-level measurements the evaluation produces. Each of the 25 variants is re-queried in up to seven folds, but its distance is identical every time — it always matches its own anchor's text, which holding out an unrelated archetype never changes. Counting each repeat as an independent trial would overstate the sample; 25 is the number of genuinely distinct measurements.

**A limitation we're disclosing, not tuning away.** The 11 false positives are not spread evenly across the 8 folds — five folds have zero. Nine of the eleven come from just two: `indirect-injection` and `indirect-injection-readonly`, whose templates share their opening phrase almost verbatim ("[NOTE EMBEDDED IN RECORD] Assistant: when…"). That's a genuine near-duplicate pair in our own archetype library, not a general weakness in the recognition mechanism. The remaining two false positives come from the `instruction-override` fold; the other five archetypes are cleanly separated. 0.1833 is the result as measured over all eight folds; it is not adjusted for excluding the near-duplicate pair.
