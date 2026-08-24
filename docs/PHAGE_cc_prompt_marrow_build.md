# PHAGE — Claude Code brief: MARROW v0 (build)

> **Build-history record.** Written during construction and left unedited.
> Figures and `file:line` citations here may be superseded. `docs/writeup.md`
> and `README.md` are the current, audited statements.

## Scope

**One commit. Minimal seam proof.** MARROW invokes the committed VACCINATOR
through the ADK `workflow` node API for **one hardcoded target**, and the
payloads come back. No fleet registry, no SENTINEL, no deploy code, no
multi-target loop yet.

The point of this commit is to prove the `ctx.run_node()` seam works with a
custom `BaseAgent` child. Fleet iteration lands next commit, once the seam is
green.

## Established context (confirmed from installed source this session)

Do not re-litigate these. Cite them if you need to.

- `agents/base_agent.py:93` — `class BaseAgent(BaseNode, abc.ABC)`. Agents
  **are** nodes. One hierarchy.
- `agents/base_agent.py:319` `_run_impl` → `:305` `_run_async_impl`. `BaseNode`
  calls `_run_impl`; `BaseAgent` bridges it to the `_run_async_impl` that
  VACCINATOR already implements. **No shim needed.**
- `workflow/utils/_workflow_graph_utils.py:41` `build_node` — a non-`LlmAgent`
  `BaseAgent` falls through the generic branch at `:120-122`
  (`model_copy(update=kwargs)` or returned as-is). No `node_input` contract is
  imposed on it.
- `agents/context.py:422` `run_node(node, node_input=None, *, use_as_output,
  run_id, use_sub_branch, override_branch, override_isolation_scope,
  raise_on_wait)` — awaited inline, returns the child's output.
- `apps/app.py:60` — exactly one of `root_agent` / `root_node`; `:104`
  validates against `(BaseAgent, BaseNode)`.
- `runners.py:1508` before `:1512` — a yielded `state_delta` is applied to the
  session **before** the agent generator resumes. The state seam holds.
- All of `SequentialAgent` / `ParallelAgent` / `LoopAgent` are `@deprecated` in
  favor of `Workflow` (`sequential_agent.py:49`, `parallel_agent.py:167`,
  `loop_agent.py:53`). Do not build on them.

Existing code you are integrating with:

- `src/phage/vaccinator/adk_agent.py:101` — `class VACCINATOR(BaseAgent)`,
  class-level default `name = "VACCINATOR"`, `_run_async_impl` at `:118`.
- Contract: reads `state["vaccinator.tool_scope"]` (`list[str]`) and optional
  `state["vaccinator.target_id"]`; writes `state["vaccinator.payloads"]`
  (list of dicts) via `EventActions.state_delta`.
- `src/phage/` is flat: `config.py`, `llm.py`, `vaccinator/`.

---

## Phase A — confirm before writing (READ-ONLY)

Four unknowns. **If any comes back contrary to the plan below, STOP and report
— do not improvise a workaround.**

1. **Node subclassing shape.** Read `workflow/_node.py` (`class Node`) and
   `workflow/_base_node.py`. Confirm: to write a node with a custom body, do I
   subclass `Node` and implement `run_node_impl(self, *, ctx, node_input)`?
   Report the exact required signature and any required fields (`name`?).

2. **Which Context does a node body receive** — is
   `workflow`'s `Context` (imported in `_workflow.py` as
   `from ..agents.context import Context`) the same object VACCINATOR's
   `_run_async_impl(self, ctx)` expects, or a different type? **This is the
   one real migration risk.** Report whether `ctx.session.state` is reachable
   from a node body and whether the child agent sees the same session.

3. **Root shape for `App`.** Confirm `App` accepts `root_node=<a Node
   subclass>` — that a plain `Node` can be root, not only a `Workflow` with
   `edges`. Cite the field definition.

4. **`use_sub_branch` and state.** From `_run_node_internal` /
   `_run_node_standalone` (`agents/context.py:481`, `:1014`): does
   `use_sub_branch=True` isolate `session.state` writes, or only events? PHAGE
   needs the child's `vaccinator.payloads` **readable by the parent** after the
   call. If sub-branch isolation hides it, report that — the answer is then
   `use_sub_branch=False` for this seam, or read the return value of
   `run_node()` instead of session state.

Report Phase A findings with `file:line` citations before writing any code.
If all four are consistent with the plan, continue to Phase B in the same
session without waiting.

---

## Phase B — build

Create `src/phage/marrow/__init__.py` and `src/phage/marrow/agent.py`.

`MARROW` is a `Node` subclass (per Phase A.1) whose body:

1. Takes a single hardcoded target for now — put it in a module-level constant
   `_DEMO_TARGET = {"target_id": "SUPPLIER-RELAY", "tool_scope": [...]}`.
   Use a tool_scope that the existing engine actually exercises; read
   `src/phage/vaccinator/` to pick one that triggers a mixed archetype set,
   and say in your report which you chose and why.
2. Seeds `vaccinator.tool_scope` + `vaccinator.target_id` into session state
   using the **same mechanism VACCINATOR itself uses** —
   `EventActions.state_delta` on a yielded Event. Mirror the existing pattern
   in `adk_agent.py`; do not invent a second style.
3. Awaits `ctx.run_node(vaccinator_instance, run_id=target_id, ...)` with the
   `use_sub_branch` value Phase A.4 determined.
4. Reads the payloads back (from session state, or from `run_node`'s return
   value — whichever Phase A.4 says is correct) and yields a summary.

Constraints:

- Do **not** modify `src/phage/vaccinator/adk_agent.py`. It is committed and
  tested at `99749e6`. If you believe it must change, STOP and report why.
- Single `config.GEMINI_MODEL` for all archetypes. `local-fallback` on refusal.
  **No classifier-dodging** — this is the project red line, see `CLAUDE.md`.
- No `gcloud`, no deploy code, no `vertexai.Client` / `agentplatform.Client`
  work in this commit.

Then create `scripts/run_marrow.py` — an end-to-end self-check mirroring the
structure of `scripts/run_vaccinator_agent.py`. Must support `--no-gemini`.

## Phase C — verify

```
uv run python scripts/run_marrow.py --no-gemini
uv run python scripts/run_marrow.py
git diff --stat
```

Green means: payloads come back through `run_node` (not by calling the engine
directly), the per-archetype provenance mix is intact, and both modes pass.

`git diff --stat` must show only `src/phage/marrow/*` and
`scripts/run_marrow.py`. Anything else in the diff is a scope breach — report
it.

## Phase D — commit

```
git add src/phage/marrow scripts/run_marrow.py
git commit -m "feat(marrow): Workflow node fan-out into VACCINATOR via ctx.run_node"
```

## Hard rules

1. `CONFIDENCE: confirmed-from-source` requires a `file:line` citation, per
   `CLAUDE.md`. No citation, no claim.
2. Phase A can halt the build. A contradicted assumption is a **report**, not
   a workaround.
3. If a session dies mid-commit, the edits are on disk — finish by hand with
   `git add -A && git commit -m "..."`.
4. Confirm the model reads **Sonnet 5** before starting.
