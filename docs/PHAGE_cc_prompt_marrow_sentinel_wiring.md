# PHAGE — Wire SENTINEL into MARROW (build)

## Purpose

Recon confirmed no live or persisted path exists for MACROPHAGE to consume
`sentinel.verdict` — SENTINEL only runs from two standalone scripts, each
in a session `InMemoryRunner` builds fresh, which MARROW never sees. This
build closes that gap: wire SENTINEL into MARROW's fire/capture loop via
`ctx.run_node()` — the same mechanism MARROW already uses for VACCINATOR,
confirmed generic for any `BaseAgent` rather than VACCINATOR-specific
(`context.py:411-422`, `marrow/agent.py:209,216`).

## Scope

- Replace the placeholder comments in `marrow/agent.py` (`:6` "No SENTINEL
  routing yet", `:96` and `:223` "(SENTINEL, later)") with an actual
  `ctx.run_node()` call to `SENTINEL()`.
- Call SENTINEL immediately after each payload fire + OTel trace capture
  (current loop around `:218-278`), so the verdict lands in the same
  session, same invocation, as the fire that produced it.
- Confirm SENTINEL's exact invocation signature by reading
  `sentinel/adk_agent.py` directly first — do not assume parameter names
  from this brief.
- Leave a placeholder comment for MACROPHAGE at the equivalent point
  (mirrors how SENTINEL's own placeholder existed before this build) — no
  MACROPHAGE code. Its containment action is still undesigned.

## Explicitly out of scope

- No `SqliteSessionService`, no persistence layer, no new dependency.
  Durable storage is ARCHIVIST's job later, not this build's.
- No changes to SENTINEL's internals (`triage.py`, the ADK wrapper's own
  logic) — only how it's invoked.
- No MACROPHAGE code.

## Verification — do this, don't assume it worked

After wiring, run the existing fire cycle against the SAIL fleet and
actually read `ctx.session.state` post-run to confirm `sentinel.verdict`
is present for each fired payload — not just "no errors thrown." This is
the same class of claim ("should hold, by typing") the recon flagged as
unverified; verify it for real here.

## Output

Diff + one-line confirmation that `sentinel.verdict` was observed in
session state after a real run, cited file:line. No design proposal for
MACROPHAGE.
