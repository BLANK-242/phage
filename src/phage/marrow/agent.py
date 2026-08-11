"""MARROW — fleet orchestrator.

Iterates the registered SAIL fleet (src/phage/targets.py) and fans out into
VACCINATOR once per target via the `ctx.run_node()` seam proven in the v0
single-target commit. Sequential only — no asyncio.gather, no concurrency
(out of scope for this commit). No SENTINEL routing yet.

MARROW is a workflow `Node`, not a `BaseAgent`/`SequentialAgent`: the shipped
SequentialAgent/ParallelAgent/LoopAgent are all @deprecated in favor of Workflow
(sequential_agent.py:49, parallel_agent.py:167, loop_agent.py:53), and the
runtime-length fleet fan-out MARROW needs next commit is a Node/run_node
pattern, not a fixed construction-time sub_agents list.

Every ADK signature here was re-confirmed against installed 2.6.3 source:
  - Node: google/adk/workflow/_node.py:180 (public: google.adk.workflow.Node,
    workflow/__init__.py:24). Override run_node_impl(self, *, ctx: Context,
    node_input) -> AsyncGenerator (_node.py:237-239; _run_impl dispatches :259).
  - Required field `name` (Field(...), _base_node.py:41; identifier-validated
    _base_node.py:44-49) -> class-level default name = "MARROW".
  - ctx is agents.context.Context (_node.py:40); ctx.session.state reachable
    (context.py:294-296); ctx.run_node (context.py:422); ctx.invocation_id
    (readonly_context.py:45-47).
  - State seam holds BOTH ways via back-pressure: a yielded non-partial Event's
    state_delta is applied to session.state before the node generator resumes,
    because _enqueue_event blocks on `await processed.wait()`
    (invocation_context.py:310-312) until _consume_event_queue calls
    append_event then sets the signal (runners.py:882-888). append_event applies
    the delta via session.state.update (base_session_service.py:204-209). The
    same back-pressure applies to VACCINATOR's payloads delta inside run_node,
    so it is readable from session.state once run_node returns.
  - use_sub_branch does NOT isolate session.state (only the event branch;
    shallow model_copy keeps the same session — _node_runner.py:209-217,
    context.py:180-181) -> read payloads from state, not run_node's return.
    run_node returns child_ctx.output (context.py:678), which is None for
    VACCINATOR (it sets no event.output), so session.state is the read path.
  - Child VACCINATOR shares the same session: get_invocation_context passes
    'session': self.session (context.py:416).

RE-VERIFIED this session (fleet-iteration commit) against a claim that turned
out to be inaccurate: `run_node`'s own docstring at context.py:~458 says
use_sub_branch=True will "isolate its state and events from the main branch."
That is NOT what the implementation does. Fresh re-check, same conclusion as
above: _node_runner.py:213/217 does `ic.model_copy(update={"branch": ...})` —
pydantic model_copy defaults to deep=False, so `session` (and therefore
`session.state`) stays the SAME object across sub-branches; Context's State
wrapper is constructed directly against that shared dict (context.py ~180-185:
`State(value=invocation_context.session.state, ...)`). So use_sub_branch only
tags the event branch (used for LLM context-assembly filtering elsewhere,
flows/llm_flows/contents.py:444) — it does NOT prevent two run_node calls that
reuse the same state keys from overwriting each other. The fleet loop below is
correct ONLY because it is sequential and reads+copies
session.state["vaccinator.payloads"] immediately after each run_node() call,
before the next target's seed overwrites that key. Passing use_sub_branch=True
per call is harmless (it does tag events per target) but is NOT what makes the
per-target isolation correct — the immediate synchronous read is.

Red line (CLAUDE.md): a single config.GEMINI_MODEL for all archetypes with
local-fallback on refusal lives entirely in the engine; this module adds no
model, no routing, no client.
"""

from __future__ import annotations

from typing import Any, AsyncGenerator

from typing_extensions import override

from google.adk.agents.context import Context
from google.adk.events import Event, EventActions
from google.adk.workflow import Node
from google.genai import types

from phage.targets import FLEET
from phage.vaccinator.adk_agent import (
    STATE_PAYLOADS,
    STATE_TARGET_ID,
    STATE_TOOL_SCOPE,
    VACCINATOR,
)

# MARROW-owned state key (dotted-namespace convention matches vaccinator.* in
# adk_agent.py). Needed because session.state["vaccinator.payloads"] is
# overwritten every loop iteration (state is not branch-isolated — see module
# docstring), so nothing outside this generator's own `results` local can see
# per-target payloads after the loop ends UNLESS the aggregate is also written
# to state. Shared with tests (scripts/run_marrow.py) — import this, don't
# re-type the string.
STATE_FLEET_PAYLOADS = "marrow.fleet_payloads"


class MARROW(Node):
    """Fleet orchestrator: seeds each registered target's tool_scope into session
    state in turn and fans out into VACCINATOR via ctx.run_node, then reports
    what came back per target."""

    name: str = "MARROW"
    description: str = (
        "Orchestrates vaccination cycles: seeds a target's declared tool scope "
        "into session state and invokes VACCINATOR via the workflow node API."
    )
    # Required to call ctx.run_node(): a node that dynamically schedules children
    # must be re-runnable on resume, else _run_node_internal raises ValueError
    # ("A node must have rerun_on_resume=True", context.py:503-509). BaseNode
    # defaults this to False (_base_node.py:54). Semantically correct for MARROW:
    # if a vaccination cycle is interrupted, it re-runs from scratch.
    rerun_on_resume: bool = True

    @override
    async def run_node_impl(
        self, *, ctx: Context, node_input: Any = None
    ) -> AsyncGenerator[Any, None]:
        results: dict[str, list[dict[str, Any]]] = {}

        for target in FLEET:
            # 1. Seed VACCINATOR's inputs into session state via
            #    EventActions.state_delta on a yielded Event — the same
            #    mechanism VACCINATOR itself uses (adk_agent.py). Back-pressure
            #    guarantees this delta reaches session.state before the
            #    generator resumes to call run_node below.
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(text=f"MARROW: seeding target {target.id}")
                    ],
                ),
                actions=EventActions(
                    state_delta={
                        STATE_TOOL_SCOPE: target.tool_scope,
                        STATE_TARGET_ID: target.id,
                    }
                ),
            )

            # 2. Fan out into VACCINATOR through the node seam for this target.
            #    use_sub_branch=True tags this run's events on their own branch
            #    (harmless, matches the fleet-iteration brief); it does NOT
            #    isolate session.state (see module docstring) — session is
            #    shared regardless.
            await ctx.run_node(VACCINATOR(), run_id=target.id, use_sub_branch=True)

            # 3. Read THIS target's payloads back from session state and copy
            #    them into results NOW, sequentially, before the next
            #    iteration's seed overwrites the same state keys. run_node's
            #    return value is not used here — it is None for VACCINATOR
            #    (sets no node output; see module docstring).
            results[target.id] = list(ctx.session.state.get(STATE_PAYLOADS) or [])

        # 4. Fleet summary event.
        total = sum(len(ps) for ps in results.values())
        total_gemini = sum(
            1 for ps in results.values() for p in ps if p.get("source") == "gemini"
        )
        total_local = total - total_gemini
        per_target = ", ".join(f"{tid}={len(ps)}" for tid, ps in results.items())

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            content=types.Content(
                role="model",
                parts=[
                    types.Part.from_text(
                        text=(
                            f"MARROW: {total} payloads across {len(results)} targets "
                            f"({total_gemini} gemini / {total_local} local-fallback) "
                            f"— {per_target}"
                        )
                    )
                ],
            ),
            # Structured per-target results, so a caller can verify each
            # target's payloads without text-parsing the summary above (see
            # STATE_FLEET_PAYLOADS docstring for why this key exists at all).
            actions=EventActions(state_delta={STATE_FLEET_PAYLOADS: results}),
        )
