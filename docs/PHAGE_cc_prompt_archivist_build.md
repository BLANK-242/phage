# PHAGE — Claude Code Build Brief: ARCHIVIST

**Target path in repo:** `docs/PHAGE_cc_prompt_archivist_build.md`
**Date:** 2026-08-21
**Depends on:** `docs/PHAGE_cc_prompt_archivist_memory_recon.md`, `docs/PHAGE_cc_prompt_archivist_mutation_recon.md`
**Authoritative spec:** `PHAGE_build_prompt.md`

ARCHIVIST is the last unbuilt agent. No ARCHIVIST code exists yet. This brief builds
its recognition and signature-write mechanism, wires it into MARROW's fire loop, and
hardens the one upstream defect that would otherwise silently corrupt the demo take.

---

## 0. Preflight — three gates, before any code is written

Each gate has a stated expected result. **If a gate fails, stop. Do not write code, do
not scaffold, do not "work around it." Report the mismatch and wait.**

### Gate A — hook point (this is the one that has not been confirmed)

Open `PHAGE_build_prompt.md` and read **every** passage describing the vaccination
cycle, the fire loop, and recognition ordering. Do not stop at the first match, and do
not rely on any summary, prior session note, or recon file for this — read the spec
itself.

**Expected:** recognition fires *before* the payload is dispatched through the Gateway
— i.e. on second exposure the attack is neutralized on recognition rather than
re-analysed, so a recognition hit means the payload is never fired at all.

**Report:** exact line numbers and the spec's own wording for every passage bearing on
ordering.

**Stop conditions:** the spec places recognition *after* dispatch; or places it
alongside SENTINEL as a consumer of traces; or the spec is silent on ordering. In the
silent case, report that it is silent and stop — do not infer.

### Gate B — memory API surface

Re-read `docs/PHAGE_cc_prompt_archivist_memory_recon.md`. Extract the **exact,
live-verified** call signatures for create, retrieve, and delete via
`agentplatform.Client(...).agent_engines.memories`.

Use those signatures verbatim. Do **not** reconstruct them from `google-cloud-aiplatform`
docs, from training memory, or from ADK's `BaseMemoryService` — the recon exists
specifically because ADK's `search_memory()` reads only `.fact` and `.update_time` and
silently drops `.distance`.

**Report:** the three signatures, and confirmation that the score field is `distance`
with **smaller = closer** (the opposite direction from a similarity threshold).

### Gate C — mutation hook

Confirm `Payload.paraphrase` still exists and is still `Optional[str]`, and locate the
function that produces it (`_tailor_one()` per the mutation recon).

**Report:** file paths and line numbers for the `Payload` model and for `_tailor_one()`.

---

## 1. Scope

### IN — do all four

1. Harden `_tailor_one()`'s refusal path (Task 1)
2. Build the ARCHIVIST module (Task 2)
3. Wire it into MARROW's fire loop (Task 3)
4. Tests, red→green (Task 4)

### OUT — do not do these, do not scaffold them, do not leave TODOs for them

- The labeled variant/non-variant dataset, threshold tuning, and the false-positive
  rate — that is the **next** brief, and it depends on Task 1 landing first
- Any dashboard, UI, or demo surface
- Editing `docs/demo_script.md`
- Flipping the GitHub repo public
- Any change to MACROPHAGE or SENTINEL logic beyond the single call site required by
  Task 3
- Introducing any new dependency

---

## 2. Task 1 — a refusal must fail loudly, not silently

**The defect:** `paraphrase` is `Optional[str]`. When the model refuses, it comes back
`None`, which is indistinguishable downstream from a successful no-op mutation. A
recorded take where nothing actually mutated would look identical to a real one.

**The fix, in `_tailor_one()`:**

- Retry up to **3 total attempts** when the paraphrase comes back `None`/empty
- On exhaustion, raise a named exception (e.g. `MutationRefused`) carrying the target,
  the archetype, and the attempt count — do not return `None`, do not log-and-continue
- Leave the success path untouched
- Do not add backoff, jitter, or caching — three straight attempts, nothing more

**Why this and not a dedicated deterministic reframe:** a hand-written template would
make the eventual false-positive rate measure the template's own distance distribution
rather than real mutation, which makes the number indefensible in the write-up. Ten
lines here preserve a real measurement. If Task 1's retry loop turns out to exhaust
often in practice, the dataset run in the next brief will surface that with real
numbers, and *that* is when a deterministic fallback gets built — not before.

---

## 3. Task 2 — the ARCHIVIST module

Place it alongside the existing agent modules; match the layout the other four already
use rather than inventing a new one.

### 3.1 Signature text symmetry — the non-obvious constraint

The text embedded at write time and the query text used at recognition time **must be
produced by one shared function**. Memory Bank embeds server-side from the `fact`
string, so any asymmetry between the two construction paths poisons every distance the
demo puts on screen.

Implement exactly one `_signature_text(...)` and call it from both `record()` and
`recognize()`. Do not build the query string inline at either call site.

### 3.2 Threshold

One module-level constant, one place:

```python
RECOGNITION_DISTANCE_THRESHOLD = 0.35  # UNTUNED placeholder — tuned in the next brief
                                       # against the labeled pair set. Single source of
                                       # truth: do not inline this value anywhere else.
```

Comparison is **strictly** `distance < RECOGNITION_DISTANCE_THRESHOLD`. A result exactly
at the threshold is a miss. Anyone writing `>` here has inverted the semantics.

### 3.3 `recognize(...)`

Returns a small frozen result type carrying: `recognized: bool`, `distance: float | None`,
`matched_fact: str | None`, `matched_memory_name: str | None`.

- Retrieve with top-k, take the nearest result
- **Fail open.** Wrap the API call: on any client exception, log a warning and return
  `recognized=False`. A recognition subsystem that raises would kill the fire loop, and
  a false block is worse than a missed one — the demo depends on the loop completing.
- If a returned result has no `distance` field, treat it as a miss rather than assuming
  a value

### 3.4 `record(...)`

- Writes a signature **only** on a `landed` verdict
- Idempotent: an identical signature for the same target/archetype/tool must not create
  a duplicate memory. Check before writing.
- Returns the memory resource name

---

## 4. Task 3 — wiring into MARROW's fire loop

Contingent on Gate A passing. Two separate insertion points:

- **Recognition** is a pre-fire gate: MARROW calls `recognize()` after VACCINATOR has
  produced the payload and **before** dispatch through the Gateway. A hit
  short-circuits the entire cycle — no fire, no SENTINEL, no MACROPHAGE — and returns a
  result that makes the short-circuit and the distance visible to the caller.
- **The signature write** stays where the cycle already ends: after SENTINEL's verdict,
  on `landed`.

MARROW holds no domain logic. It calls ARCHIVIST and routes the result; the decision
logic lives in ARCHIVIST.

---

## 5. Task 4 — tests, red→green

Write the test first, run it, confirm it fails for the right reason, then implement,
then confirm it passes. Report the actual failure output, not a claim that it failed.

Unit tests use fakes — **no live API calls in the unit suite**:

1. `_signature_text` produces identical output for identical inputs via both the
   `record()` and `recognize()` paths
2. `recognize()` returns `recognized=True` when the fake returns a distance below
   threshold
3. `recognize()` returns `recognized=False` at *exactly* the threshold (boundary)
4. `recognize()` returns `recognized=False` and does not raise when the client raises
5. `recognize()` returns `recognized=False` when the result carries no `distance`
6. `record()` is a no-op when the verdict is not `landed`
7. `record()` does not create a duplicate for an identical signature
8. On a recognition hit, the fire loop short-circuits — assert with mocks that dispatch,
   SENTINEL, and MACROPHAGE are **not** called
9. On a recognition miss, the fire loop proceeds normally
10. `_tailor_one()` raises `MutationRefused` after 3 refusals, and succeeds normally
    when the second attempt returns a paraphrase

Plus **one** live integration test, gated behind an env var (e.g.
`PHAGE_LIVE_MEMORY_TESTS=1`) so it is skipped by default: create → retrieve → assert a
real `distance` is present → delete. Run it once and paste the real output.

---

## 6. Commits

Four commits, in order, one per task:

```
archivist: fail loudly on mutation refusal instead of returning None
archivist: add recognition and signature write via agent_engines.memories
archivist: gate MARROW's fire loop on recognition before dispatch
archivist: tests for recognition, signature write, and refusal handling
```

---

## Output

Report back in exactly this order. Nothing added, nothing omitted.

1. **Gate A** — every spec passage on ordering, with `file:line` and the spec's own
   wording. State plainly whether the pre-fire placement is confirmed, contradicted, or
   unaddressed.
2. **Gate B** — the three verified call signatures, and confirmation of `distance`
   direction.
3. **Gate C** — `file:line` for the `Payload` model and `_tailor_one()`.
4. **Diff summary** — every file touched: path, lines added, lines removed.
5. **Threshold constant** — its `file:line`, and confirmation that the value appears
   nowhere else in the codebase.
6. **Full pytest output** of the final run — the real terminal output, pasted.
7. **Live integration test** — the real output including the actual `distance` value
   returned by the production Agent Engine instance.
8. **Anything in scope you did not do**, and why.
