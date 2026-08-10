# CLAUDE.md — PHAGE build-track context

This file is read automatically at the start of every Claude Code session in this repo.
It carries the standing rules for building PHAGE. Task-specific instructions arrive as
paste-in briefs under `docs/`; this file is the context that outlives any single brief.

PHAGE is a defensive AI-security project for Google Cloud's All Things Agentic Hackathon
(Fortified Enterprise Fleet track). It red-teams AI agents this project itself builds,
owns, and registers — a closed exercise inside our own Google Cloud project, no external
targeting, no export. The repo fills with prompt-injection payloads by design; that is the
subject matter of a defensive tool, and it is exactly why the permission rules below exist.

---

## Verify before you write — never reconstruct from memory

Claims about APIs, signatures, and library behavior must be checked against what is
actually installed and on disk, not recalled. When a brief describes existing code,
verify it against the working tree before editing; if the tree has drifted from the
brief, adapt to the tree and say so in your summary.

The person has been explicit: distinguish "the source/docs say so" from "I'm inferring
this." Never state a guess as fact. If you don't know, say you don't know and go read.

## ADK: consult the on-disk reference before writing any ADK code

Installed ADK is **2.6.3**. Before writing or modifying any ADK agent code:

1. Read the installed ADK source FIRST — it is authoritative for signatures and runtime
   behavior: .venv/lib/python3.12/site-packages/google/adk/
2. Use `docs/reference/adk-llms-full.txt` (73,457 lines) for idiom and usage prose.
   Never load it wholesale — grep for the symbol you need, e.g.
   grep -n InMemoryRunner docs/reference/adk-llms-full.txt
3. Ignore `docs/reference/adk-llms.txt` — it is a 246-line redirect stub, not a condensed
   reference. The real content moved to adk.dev.
4. Any claim about ADK behavior in a report or commit message needs a file:line citation
   from (1) or (2). No citation, no claim.

**Known trap #1:** `vertexai.Client` is deprecated in favor of `agentplatform.Client`.
Find the current import pattern in the installed source before writing it — do not
reproduce a remembered import.

## Region split (do not "fix" this — it is correct)

- **Model inference → Vertex `global` endpoint.** Gemini 3.x is served *only* from `global`;
  `gemini-3.5-flash @ us-central1` returns 404, `@ global` returns 200 (measured on this project).
- **All infra/data → `us-central1`** — Cloud Run, Firestore, Agent Engine, Memory Bank,
  Model Armor, Registry.
- Every client sets an explicit location via `src/phage/config.py`. If you see inference
  pointed at `us-central1`, that's the bug; the split is intentional.

## No classifier-dodging (project red line)

`gemini-3.5-flash` refuses to author some injection content. The correct response to a
refusal is to fall to the deterministic local library (`local-fallback`) — **not** to
reword the prompt to slip past the refusal, and **not** to route that content to a
different model (`flash-lite`, `3.6`) that complies. Do not add per-archetype model
selection to defeat a refusal. The default inference model is `config.GEMINI_MODEL` for
all archetypes. If you find such a route in the tree, flag it — don't extend it.

## Permission mode: acceptEdits / manual approve

Not `bypassPermissions`. This repo fills with injection payloads; a model reading those
with no permission gate is the exact risk the tool exists to study. Read shell commands
before they run. Show diffs before they land. Explain state-changing actions briefly
before doing them.

## Environment & gotchas

- Ubuntu 24.04.4 on VMware/Win11, host `phage-dev`, user `blank`. Python 3.12 via `uv`
  (run scripts with `uv run python …`, not bare `python` — it isn't aliased). AZERTY.
- Respond in English.
- Project `phage-dev` (#680106551305), org `benlekbirwalid3-org`,
  Agent Engine instance `1868793184486686720`.
- **File transfer:** gnome-terminal mangles multi-line pastes (bracketed-paste `^[[200~`).
  Move files via scp (SSH server is installed) or GUI paste in gnome-text-editor — never
  a terminal heredoc (`cat > file << EOF`).
- `llm.py`'s `generate_with_backoff` is **synchronous** and must stay that way (satisfies
  the rate-limit backoff requirement). Don't rewrite it to async.

## Layout

- `src/phage/` — package. `config.py` (region-split clients), `llm.py` (Gemini backoff +
  tolerant JSON), `vaccinator/` (archetype library + tailoring engine).
- `scripts/` — `vaccinate_demo.py` (self-verifying demo), probe/matrix diagnostics.
- `docs/` — build briefs and `reference/` (ADK docs). `docs/reference/` is read material,
  not something to edit.
