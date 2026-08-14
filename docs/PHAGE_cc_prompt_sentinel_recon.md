# PHAGE — Claude Code brief: SENTINEL recon

Scope: **read-only.** No file edits, no commits, no new files, no `gcloud` state changes (list/describe only).

## Before you start

Confirm the MODEL LINE reads **Sonnet 5**.

## Why this recon exists

SENTINEL's founding spec: VACCINATOR's payload fires through Agent Gateway → Model Armor blocks it at the barrier or lets it through → SENTINEL reads the target's Agent Observability traces to see what actually happened → Gemma does first-pass triage, Gemini only on ambiguous cases. SENTINEL's real input is a trace of a *fired* payload — not the payload itself.

Gateway firing + Model Armor placement is Q4, explicitly deferred at checkpoint-1 as a "Phase 2b/3 boundary call." So as specced, SENTINEL's actual input doesn't exist in this repo yet.

ARCHIVIST already hit the same wall: semantic recognition is its own Phase 3 feature, deferred, with a deterministic mutation step standing in for now — validated as correct at checkpoint-1, not a shortcut. The working assumption is SENTINEL gets identical treatment: a Phase 2 core built against a stand-in input, real Gateway/Observability wiring deferred alongside Q4. This recon exists to confirm that assumption against the actual spec — not to build on a guess.

## Step 1 — Read SENTINEL's phase-by-phase spec

`PHAGE_build_prompt.md` — find every section mentioning SENTINEL. Quote with line numbers:

- What the spec says SENTINEL should consume in whichever phase is currently active (pre-Gateway).
- What it says for the Gateway/Observability-integrated phase.
- If the spec doesn't split SENTINEL by phase at all — say so plainly. Don't infer a split that isn't written down.

## Step 2 — Check what's actually provisioned

Read-only `gcloud` only (`list` / `describe`, nothing that creates or modifies): is Agent Gateway, Model Armor, or Agent Observability provisioned at all on `phage-dev` (`680106551305`)? This tells us whether Q4 is undecided-and-unbuilt or undecided-but-partially-provisioned — materially different situations for scoping the build brief.

## Step 3 — Confirm the ARCHIVIST precedent as documented, not assumed

Find wherever ARCHIVIST's "deterministic mutation now, semantic recognition later" decision actually lives (CLAUDE.md, a handoff, code comments) — quote it. If SENTINEL's spec doesn't define its own Phase 2 stand-in, this is the closest real precedent for what one should look like.

## Step 4 — Report back

Quote the source for every claim, file:line. State plainly what SENTINEL's current-phase input contract is — or should be, per Step 3's precedent if Step 1 comes up empty — before anything gets built against it.
