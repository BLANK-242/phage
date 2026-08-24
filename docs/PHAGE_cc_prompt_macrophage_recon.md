# PHAGE — MACROPHAGE Recon (read-only)

> **Build-history record.** Written during construction and left unedited.
> Figures and `file:line` citations here may be superseded. `docs/writeup.md`
> and `README.md` are the current, audited statements.

## Purpose

Before writing any MACROPHAGE code, resolve two open questions from the
Session 6 handoff — which are very likely the same question asked twice:

1. **State-read mechanism.** How does a sibling `BaseAgent` (MACROPHAGE)
   read another agent's (SENTINEL's) `state_delta` write mid-run — same
   mechanism as the MARROW→VACCINATOR precedent from Session 4, or
   different?
2. **Wiring prerequisite.** SENTINEL is currently standalone — not invoked
   inside MARROW's fire/capture loop (`marrow/agent.py:6,96,223` are
   placeholder comments only, per Session 6). Does MACROPHAGE therefore
   require SENTINEL→MARROW wiring to exist first, or can it be built to
   consume `sentinel.verdict` from a recorded/persisted session
   independent of that wiring?

**No code writes this pass. Recon only — every finding cited file:line.**

## What to inspect

1. **`src/phage/sentinel/adk_agent.py`** — confirm the `state_delta` write
   (`:76`, `:184` per last session) and the exact session/invocation
   context it writes into. Is this a session MARROW could see, or one
   SENTINEL creates for itself in isolation?
2. **`src/phage/marrow/agent.py`** — the actual MARROW→VACCINATOR
   state-read pattern resolved in Session 4 (cite file:line). Confirm
   whether that same session object would be in scope for a SENTINEL or
   MACROPHAGE sub-agent call, or whether it's specific to VACCINATOR's
   invocation path.
3. **`docs/reference/adk-llms.txt`** (condensed, per `CLAUDE.md` — grep
   `adk-llms-full.txt` only for what the condensed file doesn't answer) —
   the canonical ADK pattern for sibling sub-agents sharing `session.state`
   under one orchestrator.
4. **How SENTINEL is actually invoked today** — what runner, what session
   context, confirmed standalone from MARROW. This determines whether
   MACROPHAGE can hook into live state or needs to read from
   `phage_traces.db` / a `session_id` lookup instead.

## Output format

- Direct answer to both questions above, each a one-line verdict with a
  supporting file:line citation.
- If the two questions turn out to be entangled (e.g. MACROPHAGE genuinely
  can't get live state without the wiring existing), say so plainly —
  don't soften it into "probably fine."
- No design proposal, no code. This feeds the next architecture-review
  checkpoint before MACROPHAGE gets built.
