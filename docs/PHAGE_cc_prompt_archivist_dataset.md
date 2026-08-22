# PHAGE — Claude Code Build Brief: Recognition Dataset & Threshold Tuning

**Target path in repo:** `docs/PHAGE_cc_prompt_archivist_dataset.md`
**Date:** 2026-08-22
**Depends on:** ARCHIVIST build (commits `e6b01dc`, `54164fd`, `91fd841`, `c151548`) plus the
uncommitted fleet-wide scope / `error` field changes
**Spec requirement:** `PHAGE_build_prompt.md:184` — labeled variant/non-variant pair set,
tuned threshold, reported false-positive rate

Live probe results this session, against one recorded signature:

| Query | Distance |
|---|---|
| byte-identical | 0.386 |
| paraphrase, same intent | 0.529 |
| unrelated topic | 0.875 |

The band is usable. This brief replaces the placeholder threshold with a number tuned
against a real labeled set, and produces the false-positive rate the write-up requires.

---

## 0. Preflight

1. Commit the currently uncommitted work (`src/phage/archivist/memory.py`,
   `src/phage/marrow/agent.py`, `tests/test_archivist_memory.py`) before starting.
   Message: `archivist: fleet-wide memory scope and surfaced fail-open errors`.
   Leave `scripts/probe_distance.py` untracked — it stays throwaway.
2. Confirm `RECOGNITION_DISTANCE_THRESHOLD` is still a single constant with the literal
   appearing exactly once. Report `file:line`.

---

## 1. Scope

### IN

1. Raise the provisional threshold so the code isn't in a broken state (Task 1)
2. Generate and commit the labeled dataset (Task 2)
3. Tune the threshold against it and report the FPR (Task 3)

### OUT

- Any demo, dashboard, video, or UI work
- Editing `docs/demo_script.md`
- Flipping the repo public
- Building a deterministic reframe fallback — the refusal count from Task 2 decides
  whether that is ever needed, and this brief only measures it
- Changing the signature text format. If Task 3's diagnostics show the format is wrong,
  **report it and stop**; do not redesign it inside this brief, because the dataset was
  generated under the current format and changing it invalidates every number here.

---

## 2. Task 1 — provisional threshold

Set `RECOGNITION_DISTANCE_THRESHOLD = 0.65`, keeping the `UNTUNED` comment but updating
it to reference this brief. Rationale: 0.65 sits 0.12 above the observed paraphrase
distance and 0.22 below the observed unrelated distance, so ARCHIVIST behaves sanely if
anything runs before Task 3 lands. It is a stopgap, not the answer.

---

## 3. Task 2 — the labeled dataset

### 3.1 Isolation — non-negotiable

Every write in this task uses a **dedicated eval scope**, e.g. `{"app_name": "phage-eval"}`,
never the production `phage-archivist` scope. Eval signatures must not enter the pool the
demo retrieves from. Delete every eval memory at the end of the run, and verify the
deletion by retrieving against the eval scope and confirming it comes back empty.

### 3.2 Composition

Four classes. The first two are what the FPR is computed from; the last two are
diagnostics.

| Class | n | Anchor | Query | Should recognize |
|---|---|---|---|---|
| `variant` | 25 | payload P against target T | `_tailor_one()` mutation of P, same T | yes |
| `hard_negative` | 25 | payload P against target T | a **different** attack intent against the **same** T, same archetype | no |
| `cross_target` | 10 | payload P against target T | mutation of P fired at a **different** target U | diagnostic |
| `easy_negative` | 5 | payload P against target T | unrelated content | no |

`hard_negative` is the class that matters. Both sides share the `target=`,
`archetype=`, and `tools=[...]` prefix verbatim — only the injection intent differs.
That is the realistic false-positive population, and an FPR measured against
`easy_negative` instead would be meaningless. Draw the differing intents from the
archetypes the codebase already defines; do not invent new attack families.

`cross_target` answers whether fleet-wide immunity is real: if these distances cluster
with `variant`, a signature learned on one agent protects the whole fleet. If they
cluster with `hard_negative`, the `target=` line in the signature text is dominating
the embedding and blocking transfer. Report which, plainly.

### 3.3 Generation

- Positives go through the real hardened `_tailor_one()`. **Count every `MutationRefused`
  raised across the whole run** and report it — this is the free measurement that settles
  whether reusing VACCINATOR's reframe holds or a deterministic fallback earns its build
  time. On a refusal, retry with a different source payload rather than aborting the run.
- Commit the dataset as JSONL under `data/recognition_pairs.jsonl`, one record per line:
  `{"id", "class", "anchor_text", "query_text", "target", "archetype", "expected_recognize"}`.
  It must be regenerable but also committed, so the write-up can cite a fixed artifact.
- Commit the generator as `scripts/build_recognition_dataset.py` (this one **is**
  committed, unlike the probe).

---

## 4. Task 3 — tuning and FPR

Write `scripts/tune_threshold.py`, committed. It reads the JSONL, writes each anchor to
the eval scope, queries each pair, and records the distance.

Report per class: min, median, max, and the full sorted distance list for `variant` and
`hard_negative`.

Sweep the threshold from 0.30 to 0.95 in 0.01 steps over `variant` (positives) and
`hard_negative` (negatives). Selection rule, in order:

1. If the classes are cleanly separable, choose the midpoint of the gap between the
   highest `variant` distance and the lowest `hard_negative` distance.
2. If they overlap, choose the threshold that minimises FPR subject to TPR ≥ 0.95, and
   report the full trade-off — a missed variant is fatal on camera, a false positive is
   merely a number in the write-up, so bias toward recall and be honest about the cost.

Set `RECOGNITION_DISTANCE_THRESHOLD` to the chosen value, comment updated to cite the
dataset and the resulting FPR. Re-run the full suite; fix any boundary test that assumed
the old value.

---

## 5. Output

In this order, nothing added or omitted.

1. Preflight — commit hash for the scope/error work, and `file:line` for the threshold
   constant.
2. Dataset — path, per-class counts, and three real example records (one `variant`, one
   `hard_negative`, one `cross_target`) with their full anchor and query text.
3. **`MutationRefused` count** across the generation run, as a raw count and a percentage
   of attempts.
4. Distance distributions — min / median / max per class, plus the sorted `variant` and
   `hard_negative` lists in full.
5. `cross_target` verdict — does it cluster with `variant` or with `hard_negative`? State
   plainly whether fleet-wide transfer works.
6. Chosen threshold, which selection rule applied, and the resulting **TPR and FPR**.
7. Eval-scope cleanup confirmation — the retrieve-after-delete result proving the eval
   scope is empty.
8. Full pytest output of the final run.
9. Anything in scope you did not do, and why.
