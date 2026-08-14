# PHAGE — Claude Code brief: MARROW fleet iteration

Scope: **one commit.** Replace MARROW's single hardcoded `_DEMO_TARGET` seed with a loop over the four registered SAIL targets. No changes to VACCINATOR, SENTINEL/MACROPHAGE/ARCHIVIST (unbuilt), CLAUDE.md, or `.claude/settings.json`.

## Before you write anything

Confirm the MODEL LINE at the `>` prompt reads **Sonnet 5**. The tab name persists across model switches and is not a reliable indicator. This build has died mid-work on Opus four times on this repo — do not proceed if it doesn't say Sonnet 5.

## Step 1 — Targeted evidence read (not a full recon pass)

The ADK `workflow` API is already mapped (Session 5) — don't re-derive it, build against the confirmed signatures in "Confirmed contract" below. What is *not* yet confirmed and must come from source before writing code:

1. `src/phage/marrow/agent.py` — the exact current seeding call for `_DEMO_TARGET` / `vaccinator.tool_scope`: state key name, seeding mechanism, and where it sits relative to `ctx.run_node()`. Quote the exact lines back before generalizing them.
2. `_DEMO_TARGET`'s full value (`SUPPLIER-RELAY`'s `tool_scope`) — exact shape: dict, dataclass, TypedDict, or other.
3. Grep the repo (`vaccinator/`, `tests/`, `scripts/`, `docs/`) for existing declarations of the other three SAIL targets — **QUOTE-BOT, ORDER-INTAKE, STOCK-KEEPER**. The Session 4 differentiation-matrix self-check proved payloads tailored to each target's declared tool scope across the fleet, which means all four targets' `tool_scope` values likely already exist somewhere. Find that source; don't re-derive values.

**If any of the three non-`SUPPLIER-RELAY` targets' `tool_scope` can't be found anywhere in the repo: stop, do not invent values, report back exactly what was searched and what's missing.** These represent real SAIL agents — fabricated tool scopes make the fleet demo meaningless, not just wrong.

## Decision (made — do not re-litigate)

**Target registry lives in a new `src/phage/targets.py`, not `config.py`.** `config.py` is environment/runtime configuration (region split, `GEMINI_MODEL`); the target registry is fleet data that SENTINEL, MACROPHAGE, and ARCHIVIST will all need to reference later (attribution, containment scoping, per-target signature history). Keeping it out of `config.py` now avoids a forced refactor when those three agents get built.

Shape — adapt field names/container type to match whatever Step 1.2 finds, but keep this structure:

```python
# src/phage/targets.py

@dataclass
class Target:
    id: str
    tool_scope: ...  # mirror whatever shape Step 1.2 finds — don't invent a new type

FLEET: list[Target] = [
    Target(id="SUPPLIER-RELAY", tool_scope=...),
    Target(id="QUOTE-BOT", tool_scope=...),
    Target(id="ORDER-INTAKE", tool_scope=...),
    Target(id="STOCK-KEEPER", tool_scope=...),
]
```

## Confirmed contract (from Session 5 source reads — cite, don't re-derive)

- `ctx.run_node(node, *, use_as_output, run_id, use_sub_branch, override_isolation_scope, raise_on_wait)` — awaited inline, returns the child's output.
- `use_sub_branch=True` isolates state + events per child (`context.py:422`). This is why the seeding call can reuse the same state key every loop iteration without cross-target bleed — each call gets a clean isolated branch.
- Parameter binding defaults to `'state'` (reads `ctx.state`); `'node_input'` mode doesn't apply here.
- MARROW's node already has `rerun_on_resume = True` (class-level, `agent.py:87`, committed `eb3bdb2`) — this covers the new loop automatically. Do not duplicate it per-iteration.

## Step 2 — Build

In `src/phage/marrow/agent.py`:

- Import `FLEET` from `targets.py`.
- Replace the single hardcoded seed + `run_node` call with a **sequential** loop — no `asyncio.gather`, no concurrency. Out of scope for this commit.

```python
results: dict[str, list] = {}
for target in FLEET:
    # reuse the exact seeding call found in Step 1.1, parameterized on target.tool_scope
    ...
    results[target.id] = await ctx.run_node(
        vaccinator, use_sub_branch=True, run_id=target.id
    )
```

## Step 3 — Update the self-check

In `scripts/run_marrow.py`: replace the single "7 payloads" assertion with a per-target assertion — every `FLEET` entry must return at least one payload via `run_node`. Keep `--no-gemini` support and the zero-network / all-`local-fallback` guarantee for that mode.

## Step 4 — Verify

- `git diff --stat` — expect exactly: `targets.py` (new), `marrow/agent.py` (modified), `scripts/run_marrow.py` (modified). Anything outside this, stop and flag it before committing.
- `uv run python scripts/run_marrow.py --no-gemini` — must pass, must show payloads for all four targets, zero network calls.

## Step 5 — Commit

One commit. Suggested message: `marrow: fleet iteration over registered SAIL targets`.

## Do NOT touch this commit

VACCINATOR internals (`vaccinator/adk_agent.py`, `engine.py`), SENTINEL/MACROPHAGE/ARCHIVIST (not yet built), `CLAUDE.md`, `.claude/settings.json`, `config.py`'s region split or `GEMINI_MODEL`, GitHub push (still local-only, unrelated to this step).

## Report back

- Whether all four targets' `tool_scope` were found, and where — or exactly what's missing.
- The `diff --stat` output.
- Self-check output: payload count per target.
