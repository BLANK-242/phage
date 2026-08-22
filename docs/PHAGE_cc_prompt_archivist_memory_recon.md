# PHAGE — ARCHIVIST Memory Bank Feasibility Recon (read-only)

## Purpose

The master spec (`PHAGE_build_prompt.md:175-184`) specifies ARCHIVIST's
recognition mechanism concretely: embed every encountered payload with
`text-embedding-005`, store the vector plus metadata in Memory Bank,
recognize repeat/variant threats by cosine similarity above a tuned
threshold — not exact match. Before any ARCHIVIST design gets locked in,
confirm whether that exact infrastructure is actually reachable from this
project's credentials and setup. Don't assume it from the spec's wording.

**No code writes this pass. Recon only — every finding cited file:line
or command output.**

## What to inspect

1. **Is "Memory Bank" here Vertex AI Agent Engine's actual Memory Bank
   product, or generic terminology?** Check the installed ADK / Vertex AI
   SDK versions for any Memory Bank client already present. Check
   whether the existing Agent Engine instance (`1868793184486686720`,
   project `phage-dev` / `680106551305`) has Memory Bank enabled, or
   would need explicit provisioning.
2. **Is `text-embedding-005` actually callable from this project's
   credentials today?** Look for any existing embedding call anywhere in
   the codebase, even unused or example code, that would confirm the API
   is reachable — or determine this would be a first-time call with
   unknown auth/quota status.
3. **What would storing and querying a vector concretely take** from
   Python/ADK code in this repo — a documented client method for
   writing to Memory Bank and running a cosine-similarity query against
   it, or something that would need to be assembled from lower-level
   pieces?
4. **Is `SqliteSessionService` (found sitting unused in the installed
   ADK during the MACROPHAGE recon) a realistic local fallback** —
   storing raw vectors and computing cosine similarity in Python — if
   real Memory Bank access turns out not to be practically usable in the
   time remaining?

## Output format

- A plain answer: is real Memory Bank + `text-embedding-005` actually
  usable here today? Cite file:line or actual command output, not
  documentation-reading alone.
- If not directly usable, name the specific blocker — credentials, API
  not enabled, SDK version, quota, something else — rather than
  softening into "might work with more setup."
- A plain answer on whether the `SqliteSessionService` local-vector
  fallback is realistic as a substitute, if needed.
- No design proposal, no code. This is one input to ARCHIVIST's next
  architecture decision, not the decision itself.
