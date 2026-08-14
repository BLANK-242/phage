# PHAGE — MACROPHAGE Containment Feasibility Recon (read-only)

## Purpose

MACROPHAGE's containment action is still undesigned. The narratively
correct version — matching the original "revokes identity / cuts routes /
quarantines" framing — is revoking the specific tool a landed exploit
used, so a re-fired payload against that target can't use it again. That
only works if SAIL target tool lists are actually mutable at runtime.
This recon settles that before any design gets locked in.

**No code writes this pass. Recon only — every finding cited file:line.**

## What to inspect

1. **`src/phage/targets.py`** — the `Target` dataclass and `FLEET`
   registry. How is each target's underlying ADK agent constructed — is
   its tool list a static attribute set once at import/construction time,
   or something rebuilt per-invocation? Concretely: if a tool were
   removed from a target's definition, would a subsequent fire against
   that same target actually reflect the change, or is the agent/tool
   list cached somewhere that wouldn't see it?
2. **`src/phage/marrow/agent.py`** — how MARROW invokes each target per
   payload. Does it construct the target agent fresh from `FLEET` on
   every fire, or reuse one long-lived instance across the whole run?
   This decides whether revocation needs to mutate `FLEET`'s stored
   definition (affecting every future fire against that target) or
   something more localized to one session.
3. **ADK reference docs + existing code** — whether there's already a
   pattern in this repo or the ADK docs for scoping tool availability
   per-session or per-invocation, as a lighter-weight alternative to
   physically editing a target's tool list.

## Output format

- Plain answer: is target-level tool revocation buildable against the
  current `FLEET`/`Target` architecture? Cite file:line.
- If yes, how invasive — touches `FLEET` only, touches every target
  definition, or needs something ADK doesn't currently give this repo.
- If no, say so plainly and name the actual blocker, rather than
  softening into "might be possible with more work."
- No design proposal, no code. This is one input to the next MACROPHAGE
  architecture decision, not the decision itself.
