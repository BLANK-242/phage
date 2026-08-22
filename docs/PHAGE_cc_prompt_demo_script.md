# PHAGE — Claude Code Build Brief: Finalize the Demo Script

**Target path in repo:** `docs/PHAGE_cc_prompt_demo_script.md`
**Date:** 2026-08-22
**Revises:** `docs/demo_script.md` (existing first draft, 4 embedded open decisions)
**Spec:** `PHAGE_build_prompt.md:181`, `:193` — two-scene spine, ≤ 4:00

Evaluation is complete and committed (`e18bc53`, `e17b41e`): threshold 0.59, TPR 1.00 at
n=25 variants, FPR 0.1833 at n=60 held-out queries, AUC 0.9727. Recording starts
2026-08-26. This brief resolves the draft's four open decisions and makes the script
executable rather than aspirational.

---

## 0. Preflight — the thing that will ruin a take

**The production memory scope must be empty before scene 1 rolls.** ARCHIVIST has been
recording signatures throughout development. If any signature matching the demo payload
is sitting in `{"app_name": "phage-archivist"}` when the camera starts, recognition fires
on the *first* exposure, scene 1 short-circuits, and there is no compromise, no
containment, and no signature to recognize in scene 2 — the entire demo collapses, and it
collapses in a way that looks like the system working.

Add a pre-take procedure to the script:

1. Retrieve everything in the production scope and print it
2. Delete all of it, verify the scope returns 0 results
3. Only then start the recording

Also confirm the eval scopes (`phage-eval*`, `phage-eval-loao-*`) are empty — they were
verified clean, but a live check costs seconds and a contaminated pool costs a take.

---

## 1. Scope

### IN

1. Rewrite `docs/demo_script.md` with the four decisions resolved (Task 1)
2. Add the pre-take procedure and a rehearsal checklist (Task 2)
3. Verify the script against what the code actually prints (Task 3)

### OUT

- Recording, editing, or producing any video
- Building any dashboard, web UI, or graphic
- The Devpost submission text — it depends on the recorded take
- Any change to `RECOGNITION_DISTANCE_THRESHOLD`, the signature format, the dataset, or
  the evaluation
- Flipping the repo public

---

## 2. Task 1 — the four decisions, resolved

**1. Terminal output, not a dashboard.** No web UI is built and none will be. A judge
watching a security tool sees raw terminal output as evidence, not as a shortcut.

**2. Show the raw `distance` beside the threshold, plus a state banner.** On screen:
`distance=0.4732  threshold=0.59  → RECOGNIZED`. The banner carries the meaning at
glance-speed; the raw number is the evidence. Do **not** convert the distance into a
similarity-style score — a converted number invites "what's the conversion?" and there is
no good answer under time pressure. Say once, in narration, that smaller means closer.

**3. No architecture diagram.** Cut unless everything else is finished with slack, which
it will not be.

**4. Target and archetype come from whichever rehearsal run lands cleanest.** Do not
pre-commit in the script — write it with the target as a placeholder and fill it after
rehearsal. Selection criterion: the payload must actually **land** (SENTINEL returns a
compromised verdict), because a payload blocked at the Model Armor barrier writes no
signature and leaves scene 2 with nothing to recognize.

**Additional item — the agent count.** ARCHIVIST is plain functions, not an ADK agent, so
the repo contains four ADK agents and one library module. Whatever the script's narration
says about "five agents" must not be contradicted by the repo a judge can open. Either
describe ARCHIVIST by what it does rather than by agent count, or state the count in a way
the code supports. Flag your choice; do not restructure ARCHIVIST to fit the narration.

---

## 3. Task 2 — rehearsal checklist

The script must include a rehearsal pass, run at least once before 2026-08-26, that
verifies:

- The production scope purge works and leaves 0 results
- A payload against the chosen target actually lands
- The signature is written on the landed verdict
- Scene 2's mutated payload recognizes, with the distance visible in the real output
- Total runtime for both scenes, measured, against the 4:00 ceiling

**Two failure modes that must be in the checklist as named, expected events:**

- `MutationRefused` can raise mid-take (measured refusal rate 3.8%). It now fails loudly
  by design. If it fires, the take is void — re-run, don't salvage.
- A recognition-path API error returns `recognized=False` with `error` populated. On
  camera that must be distinguishable from a genuine miss. Confirm the error text
  actually appears in the terminal output during rehearsal, by forcing one if necessary.

---

## 4. Task 3 — verify the script against reality

Every line the script claims will appear on screen must be a real string the code
actually prints. Run the relevant paths, capture the actual terminal output, and quote it
in the script rather than paraphrasing what it should say. Where the script says the
narration explains something, check that the corresponding output exists to explain.

Report any place the draft describes output the code does not produce.

---

## 5. Output

In this order, nothing added or omitted.

1. Production-scope check — what was in `phage-archivist` before this brief, and the
   post-purge count (or a statement that it was already empty).
2. The finalized `docs/demo_script.md` — full contents.
3. The four decisions, each with one line on how it was applied.
4. Agent-count choice, and the exact wording used.
5. Any place the draft claimed output the code does not produce, and how it was fixed.
6. Measured runtime estimate for the two scenes against the 4:00 ceiling.
7. Anything in scope you did not do, and why.
