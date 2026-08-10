"""MARROW v0 — fleet orchestrator, single-target seam proof.

Scope: prove the `ctx.run_node()` seam works with the committed VACCINATOR
(a custom BaseAgent) for ONE hardcoded target. No fleet registry, no SENTINEL,
no multi-target loop — those are later commits.

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
    context.py:180-181) -> use_sub_branch=False and read payloads from state.
    run_node returns child_ctx.output (context.py:678), which is None for
    VACCINATOR (it sets no event.output), so session.state is the read path.
  - Child VACCINATOR shares the same session: get_invocation_context passes
    'session': self.session (context.py:416).

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

from phage.vaccinator.adk_agent import (
    STATE_PAYLOADS,
    STATE_TARGET_ID,
    STATE_TOOL_SCOPE,
    VACCINATOR,
)

# One hardcoded target for v0. SUPPLIER-RELAY is a sink+source scope: send_email
# is an external sink, read_contacts a sensitive source. That combination
# triggers a MIXED archetype set where Gemini declines the exfil-class archetype
# (data-exfiltration -> local-fallback) while non-exfil archetypes are
# gemini-tailored — so the seam proof shows the per-archetype provenance mix
# surviving the round-trip through run_node, not just "payloads came back".
_DEMO_TARGET: dict[str, Any] = {
    "target_id": "SUPPLIER-RELAY",
    "tool_scope": ["send_email(to, subject, body)", "read_contacts(name)"],
}


class MARROW(Node):
    """Fleet orchestrator (v0): seeds one target's tool_scope into session state
    and fans out into VACCINATOR via ctx.run_node, then reports what came back."""

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
        target_id = _DEMO_TARGET["target_id"]
        tool_scope = _DEMO_TARGET["tool_scope"]

        # 1. Seed VACCINATOR's inputs into session state via EventActions.state_delta
        #    on a yielded Event — the same mechanism VACCINATOR itself uses
        #    (adk_agent.py). Back-pressure guarantees this delta reaches
        #    session.state before the generator resumes to call run_node below.
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=f"MARROW: seeding target {target_id}")],
            ),
            actions=EventActions(
                state_delta={
                    STATE_TOOL_SCOPE: tool_scope,
                    STATE_TARGET_ID: target_id,
                }
            ),
        )

        # 2. Fan out into VACCINATOR through the node seam. Shared session
        #    (use_sub_branch=False) so its state_delta writes are readable here.
        await ctx.run_node(VACCINATOR(), run_id=target_id, use_sub_branch=False)

        # 3. Read the payloads back from session state (run_node's return value
        #    is None — VACCINATOR sets no node output).
        payloads = ctx.session.state.get(STATE_PAYLOADS) or []
        n_gemini = sum(1 for p in payloads if p.get("source") == "gemini")
        n_local = len(payloads) - n_gemini

        # 4. Summary event.
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            content=types.Content(
                role="model",
                parts=[
                    types.Part.from_text(
                        text=(
                            f"MARROW: {len(payloads)} payloads for {target_id} "
                            f"({n_gemini} gemini / {n_local} local-fallback)"
                        )
                    )
                ],
            ),
        )
