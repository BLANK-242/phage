# PHAGE — Claude Code brief: MARROW fleet iteration (build)

> **Build-history record.** Written during construction and left unedited.
> Figures and `file:line` citations here may be superseded. `docs/writeup.md`
> and `README.md` are the current, audited statements.

## Scope

**One commit.** Replace MARROW's single hardcoded `_DEMO_TARGET` with a
registry of targets in a new `src/phage/targets.py`, and make MARROW loop over
that registry, invoking VACCINATOR once per target via `ctx.run_node()`.

No SENTINEL, no deploy code, no new agents. This commit takes MARROW from
one-target to N-target and nothing else.

## Established context (confirmed from installed source, Sessions 4–5)

Do not re-derive these. Cite if needed.

- `agents/base_agent.py:93` — `BaseAgent(BaseNode)`. One hierarchy.
- MARROW is a `Node` subclass with `rerun_on_resume = True` (REQUIRED — the
  caller of `ctx.run_node()` must have it, `context.py:503-509`; `BaseNode`
  defaults False, `_base_node.py:54`). It is committed at `eb3bdb2`,
  `src/phage/marrow/agent.py`.
- VACCINATOR is a custom `BaseAgent` at `src/phage/vaccinator/adk_agent.py:101`,
  committed `99749e6`. **Do not modify it.** Its contract: reads
  `state["vaccinator.tool_scope"]` (list[str]) + optional
  `state["vaccinator.target_id"]`; writes `state["vaccinator.payloads"]`
  (list[dict]) via `EventActions.state_delta`.
- `ctx.run_node(node, node_input=None, *, use_as_output, run_id, use_sub_branch,
  override_isolation_scope, raise_on_wait)` — `agents/context.py:422`. Awaited
  inline, returns the child's output. `use_sub_branch=True` isolates the child's
  session-state writes AND events per run.
- Node parameter binding defaults to `'state'` (reads `ctx.state`); `'node_input'`
  mode is only for nodes-acting-as-tools. VACCINATOR reads session state, so
  the default binding is correct.

## Phase A — read before writing (READ-ONLY)

Read the current MARROW so the loop preserves its exact working pattern:

```
cat src/phage/marrow/agent.py
cat scripts/run_marrow.py
```

Confirm and report (short, with line refs into `agent.py`):

1. **How MARROW currently seeds state for the one target** — the exact
   `EventActions.state_delta` construction and the keys it sets
   (`vaccinator.tool_scope`, `vaccinator.target_id`). The loop MUST reuse this
   identical mechanism per target, not a new style.
2. **How MARROW currently reads payloads back** — from `run_node`'s return
   value, or from `ctx.state["vaccinator.payloads"]` after the call. Whichever
   it is, the loop follows the same path per target.
3. **The current `use_sub_branch` value on the single `run_node` call** and
   whether payloads were still readable afterward. This determines the
   per-target isolation approach — see the decision in Phase B.2.
4. The shape of the current `_DEMO_TARGET` constant (fields: `target_id`,
   `tool_scope`, anything else).

If any of these contradicts the plan below, STOP and report.

## Phase B — build

### B.1 — `src/phage/targets.py` (new)

A single registry module. Define the fleet as a list of structured records
mirroring the shape of the current `_DEMO_TARGET`. Minimum per record:
`target_id: str`, `tool_scope: list[str]`.

- Keep `SUPPLIER-RELAY` (the current demo target) as the FIRST entry unchanged,
  so the existing self-check path still exercises the same payloads.
- Add **2–3 more targets** representing distinct SAIL-fleet agents with
  different tool scopes — e.g. a scheduler-type agent, a document/RAG-type
  agent, a customer-facing messaging agent. Choose tool scopes that make the
  per-archetype payload mix meaningfully different across targets (so the demo
  shows the fleet being probed, not the same payload set N times). Read
  `src/phage/vaccinator/` to pick scopes the engine actually branches on, and
  state in your report which targets/scopes you chose and why.
- Expose the registry as a module-level constant, e.g. `FLEET: list[Target]`.
  Use whatever record type fits the existing code (a dataclass, a dict, or a
  simple typed structure) — match what `_DEMO_TARGET` already is; do not
  introduce a heavier abstraction than the current code uses.
- No secrets, no live endpoints, no network references. Static definitions only.

### B.2 — `src/phage/marrow/agent.py` (edit)

Replace the single-target body with a loop over `targets.FLEET`:

For each target in `FLEET`:
1. Seed `vaccinator.tool_scope` + `vaccinator.target_id` for THIS target, using
   the identical `EventActions.state_delta` mechanism Phase A.1 found.
2. `await ctx.run_node(vaccinator, run_id=target_id, use_sub_branch=<Phase A.3
   value>)`.
3. Collect this target's payloads via the same path Phase A.2 found.

**Isolation decision (resolve from Phase A.3):**
- If the single-target call used `use_sub_branch=False` and payloads were
  readable from `ctx.state` afterward: per-target, `use_sub_branch=False` still
  works, but successive targets will OVERWRITE `vaccinator.payloads` — so you
  MUST read each target's payloads back into a per-target collection
  *immediately after its `run_node` call*, before seeding the next target.
  Report that you did this.
- If the single-target call used `use_sub_branch=True`: confirm the parent could
  still read the child's payloads (Phase A.3). If sub-branch isolation hides the
  child's state from the parent, the read must come from `run_node`'s RETURN
  value, not `ctx.state`. Use whichever the source supports.

Accumulate results as `{target_id: [payloads]}` and yield a summary that names
each target and its payload count.

Do NOT change `rerun_on_resume = True`. Do NOT modify VACCINATOR. Single
`config.GEMINI_MODEL`, `local-fallback` on refusal — **no classifier-dodging**
(CLAUDE.md red line).

### B.3 — `scripts/run_marrow.py` (edit)

Extend the self-check to assert **every** target in `FLEET` returned a non-empty
payload list. Print per target: `target_id`, payload count, and that all were
`local-fallback` in `--no-gemini` mode. Must still support `--no-gemini`.

The self-check FAILS if any target returns zero payloads, or if any network
call is made in `--no-gemini` mode.

## Phase C — verify

```
uv run python scripts/run_marrow.py --no-gemini
uv run python scripts/run_marrow.py
git diff --stat
```

Green means: every `FLEET` target got payloads back **through `run_node`** (not
by calling the engine directly), the payload mix differs across targets where
scopes differ, both modes pass, zero network in `--no-gemini`.

`git diff --stat` must show ONLY:
- `src/phage/targets.py` (new)
- `src/phage/marrow/agent.py`
- `scripts/run_marrow.py`

Anything else is a scope breach — STOP and report it.

## Phase D — commit

```
git add src/phage/targets.py src/phage/marrow/agent.py scripts/run_marrow.py
git commit -m "feat(marrow): fleet iteration over target registry via per-target run_node"
```

The `git add` and `git commit` will hit the guardrail's ask-gate — approve them.

## Hard rules

1. `CONFIDENCE: confirmed-from-source` needs a `file:line` citation (CLAUDE.md).
2. Phase A can halt the build. A contradicted assumption is a report, not a
   workaround.
3. Do not modify `src/phage/vaccinator/adk_agent.py`. If you think you must,
   STOP and report why.
4. If the session dies mid-commit, edits are on disk — finish by hand:
   `git add -A && git commit -m "..."`.
5. Confirm the model reads **Sonnet 5** before starting.
