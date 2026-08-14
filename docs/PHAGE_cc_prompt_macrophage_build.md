# PHAGE — Build MACROPHAGE (containment)

## Purpose

Recon confirmed tool revocation is buildable with no ADK-side gap:
`_TARGET_AGENTS[target_id].tools` is a mutable field, uncached beyond one
`InvocationContext`, and MARROW already builds a fresh
`InvocationContext` per fire — so a mutation is picked up on the very
next fire against that target. This build wires MACROPHAGE into MARROW's
fire loop (same `ctx.run_node()` pattern as SENTINEL) so a `landed`
verdict revokes the specific tool that was exploited, process-wide for
that target, for the rest of the run.

**Scope decision already made, not open for reinterpretation:**
process-wide per-target revocation, not session-scoped. MARROW gives
every fire a brand-new session, so a session-scoped block would die
before the next fire that needs protecting — there's no live turn left
in an already-completed session to contain.

## Scope

- New module, mirroring SENTINEL's own split: a pure containment
  function (e.g. `src/phage/macrophage/containment.py`) separate from the
  ADK `BaseAgent` wrapper (`src/phage/macrophage/adk_agent.py`) that
  invokes it and writes the result to session state — same shape as
  `triage.py` / `sentinel/adk_agent.py`.
- MACROPHAGE reads `sentinel.verdict` from session state (the same key
  SENTINEL already writes). On `verdict == "landed"`: identify which
  tool was exploited and remove it from that target's live tool list. On
  any other verdict: no-op — don't write a misleading "contained" result
  for a target that wasn't landed.
- Wire the call into `marrow/agent.py` at the existing MACROPHAGE
  placeholder (`:407-412`) via `ctx.run_node()`, immediately after
  SENTINEL in the same fire iteration — mirrors exactly how SENTINEL was
  wired into MARROW.
- Confirm two things from source before writing the mutation logic —
  don't take either from this brief:
  1. Whether `TriageResult.supporting_spans` actually names the tool
     that was called (needed to know *which* tool to revoke) — read
     `triage.py` and an actual captured span in the trace DB to confirm
     the attribute exists and where.
  2. How MACROPHAGE should reach `_TARGET_AGENTS[target_id]` — direct
     import from `marrow.agent`, or something passed in at invocation.
     Follow whatever the existing SENTINEL wiring already establishes as
     idiomatic for this codebase.
- Make the revoke idempotent: if the tool is already absent from that
  target's list (e.g. a second landed verdict against the same target
  via a different archetype), this must not error.
- Write MACROPHAGE's own result to session state under a `macrophage.*`
  key, same convention as `sentinel.verdict` — target_id, tool revoked
  (or none) — for observability and for ARCHIVIST later.

## Explicitly out of scope

- No restoring a revoked tool. That's ARCHIVIST's territory (signature
  memory), not this build's.
- No handling for `ambiguous` or other non-`landed` verdicts beyond a
  clean no-op. No tiered response by verdict severity — that's a stretch
  idea, not this build.
- No `before_tool_callback` / session-scoped guardrail path. Recon
  surfaced it as an alternative; it's not what's being built.
- No changes to SENTINEL or the self-check fix already landed.

## Verification — do this, don't assume it worked

Run the same live fire cycle used to verify the wiring. For any target
that gets a `landed` verdict during the run:

1. Read `_TARGET_AGENTS[target_id].tools` (or call `canonical_tools()`
   fresh) immediately after, and confirm the exploited tool is actually
   gone — not inferred from an absence of errors.
2. If the run's own payload ordering happens to fire another payload at
   that same target afterward that would have used the same tool, note
   what happened to it as corroborating evidence — but don't construct
   an artificial second fire to force this; report what the real run
   actually showed.

If zero payloads land in a given run (possible — SENTINEL's verdicts are
genuinely non-deterministic), say so plainly and re-run rather than
fabricate a landed case. Re-running here is fine — this only needs to
prove the mechanism exists once, not characterize how often it fires.

## Output

Diff + for at least one real `landed` verdict, direct confirmation
(tool-list contents, not inference) that the exploited tool was removed
from that target's live tool list. No MACROPHAGE design changes beyond
what's specified above.
