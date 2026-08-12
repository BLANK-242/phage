"""MACROPHAGE — ADK agent wrapper around the containment engine.

Scope of this module: wrap `contain` (containment.py) in a single ADK
agent that reads the CURRENT firing's SENTINEL verdict from session state
and writes MACROPHAGE's own result back. Same construction pattern as
sentinel/adk_agent.py (which itself mirrors vaccinator/adk_agent.py,
commit 99749e6) — re-read in full before writing this, per the build
brief. Same reasoning applies here: contain() is deterministic and owns
all the containment logic; this module adds no model, no client, no
tiering logic of its own. It is a pure ADK-shaped adapter, exactly like
SENTINEL's and VACCINATOR's.

Reads session.state["sentinel.verdict"] DIRECTLY (build brief, Scope: "the
same key SENTINEL already writes") rather than having MARROW re-seed a
redundant macrophage.* copy of it — that dict already carries everything
this module needs (target_id, verdict, supporting_spans —
sentinel/adk_agent.py:79-90's _serialize_result shape), and MARROW's fire
loop calls this agent immediately after SENTINEL in the same iteration,
before anything else can overwrite that key. This is safe ONLY because the
caller (marrow/agent.py) never reaches this agent's ctx.run_node() call at
all when SENTINEL's own call failed for this firing (its try/except
`continue`s past this agent on a SENTINEL exception) — otherwise this
module could read a stale verdict left over from an earlier firing. That
guarantee lives in the caller, not here; documented so it isn't silently
assumed by a future reader of just this file.

How this module reaches the real target agent object to mutate — the
build brief's second confirm-from-source item, not assumed:
    _TARGET_AGENTS (marrow/agent.py:187-192) is the ONLY place in this
    repo mapping a registry target_id to the actual live Agent object
    (agents/*/agent.py's root_agent). src/phage/targets.py's FLEET/Target
    has NO live connection to it at all — confirmed by grepping every use
    of tool_scope this session: it flows exclusively into VACCINATOR's
    payload-crafting path (vaccinator/adk_agent.py, vaccinator/engine.py),
    never into anything that fires or into _TARGET_AGENTS.

    SENTINEL's own established idiom is "receive everything via session
    state, no cross-module imports of the caller's internals" — but a
    live Agent object cannot be round-tripped through session state
    without breaking this codebase's explicit JSON-friendly state
    convention (vaccinator/adk_agent.py's _serialize_payload and
    sentinel/adk_agent.py's _serialize_result both exist specifically to
    keep state JSON-friendly, by their own docstrings) and would silently
    break under any future session-service backend that actually
    serializes state (the installed ADK ships one:
    sessions/sqlite_session_service.py, unused today but real). No
    existing shared, non-MARROW-private registry of live target-agent
    objects exists to import instead, and creating one is out of this
    brief's scope.

    So: this module imports _TARGET_AGENTS directly from
    phage.marrow.agent — a deliberate, one-off exception to the "children
    never import their orchestrator" pattern SENTINEL/VACCINATOR otherwise
    follow, made because the alternative (a live object through session
    state) is worse, not because the reverse import is free. Flagged here
    rather than done silently; a future MACROPHAGE/ARCHIVIST-only shared
    registry (parallel to how targets.py already anticipates being needed
    by three future agents) would remove the need for it, but that's a
    relocation this brief doesn't ask for.

    The import is LAZY (inside _run_async_impl, not at module top) —
    required, not stylistic: marrow/agent.py now imports MACROPHAGE from
    this module at its own top level (mirroring SENTINEL/VACCINATOR's
    import style there), so a module-top `from phage.marrow.agent import
    _TARGET_AGENTS` here would be a genuine circular import — confirmed
    empirically, not just reasoned: marrow/agent.py defines _TARGET_AGENTS
    AFTER its `from phage.macrophage.adk_agent import MACROPHAGE` line, so
    at the point this module would be loading, the partially-initialized
    phage.marrow.agent module doesn't have that attribute yet, and the
    module-top form raised ImportError on the very first run. Deferring
    the import to first call time (well after all top-level module
    loading has finished) sidesteps it — same kind of deferred import
    triage.py itself already uses for `from google import genai` inside
    triage_firing when client is None, not a new pattern for this repo.

Every ADK signature re-verified against installed 2.6.3 source is
identical to sentinel/adk_agent.py's own citations (BaseAgent,
_run_async_impl, Event, EventActions.state_delta, InvocationContext,
state-key prefixes) — see that module's docstring for the citation list;
not re-derived here since nothing about the ADK contract itself changed.
"""

from __future__ import annotations

from typing import Any, AsyncGenerator

from typing_extensions import override

from google.adk.agents import BaseAgent, InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types

from phage.macrophage.containment import ContainmentResult, contain
from phage.sentinel.adk_agent import STATE_VERDICT as SENTINEL_STATE_VERDICT

# --- session-state contract -------------------------------------------------
# Mirrors sentinel/adk_agent.py's naming convention (dotted
# <agent_name_lowercase>.<field>) — not a new pattern. No macrophage.* INPUT
# key: this agent's one input is sentinel.verdict itself, SENTINEL's own
# output key (imported above, not redefined).
STATE_RESULT = "macrophage.result"  # out: dict, serialized ContainmentResult


def _serialize_result(r: ContainmentResult) -> dict[str, Any]:
    """ContainmentResult -> plain dict, so session state stays JSON-friendly
    (mirrors sentinel/adk_agent.py's _serialize_result exactly)."""
    return {
        "target_id": r.target_id,
        "verdict": r.verdict,
        "tools_revoked": list(r.tools_revoked),
        "reasoning": r.reasoning,
    }


class MACROPHAGE(BaseAgent):
    """ADK adapter around the containment engine (containment.py).

    Reads the current firing's verdict from
    session.state["sentinel.verdict"] (SENTINEL's own output, written
    immediately before this agent runs in MARROW's fire loop), resolves
    the real target agent via _TARGET_AGENTS, calls the module-level
    `contain` (no tiering/model logic of its own), and writes the
    serialized result back to session state. Holds no state of its own —
    containment.py owns all the decision logic.
    """

    name: str = "MACROPHAGE"
    description: str = (
        "On a 'landed' SENTINEL verdict, revokes the exploited tool from "
        "that target's live tool list, process-wide, for the rest of the "
        "run. No-ops on any other verdict."
    )

    @override
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        verdict_dict = ctx.session.state.get(SENTINEL_STATE_VERDICT)

        if not (isinstance(verdict_dict, dict) and verdict_dict):
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                branch=ctx.branch,
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(
                            text=(
                                "MACROPHAGE: skipped — "
                                f"{SENTINEL_STATE_VERDICT!r} missing or "
                                "wrong-typed in session state."
                            )
                        )
                    ],
                ),
            )
            return

        target_id = verdict_dict.get("target_id")
        verdict = verdict_dict.get("verdict")
        supporting_spans = verdict_dict.get("supporting_spans")

        # Lazy, not module-top — required to avoid a circular import;
        # see module docstring for the empirically-confirmed reason
        # (marrow.agent imports MACROPHAGE from this module at its own
        # top level).
        from phage.marrow.agent import _TARGET_AGENTS

        target_agent = (
            _TARGET_AGENTS.get(target_id) if isinstance(target_id, str) else None
        )
        if target_agent is None:
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                branch=ctx.branch,
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(
                            text=(
                                "MACROPHAGE: skipped — unknown target_id "
                                f"{target_id!r} (not in _TARGET_AGENTS)."
                            )
                        )
                    ],
                ),
            )
            return

        result = contain(
            target_id=target_id,
            verdict=verdict if isinstance(verdict, str) else "",
            supporting_spans=supporting_spans,
            target_tools=target_agent.tools,
        )

        summary = (
            f"revoked {list(result.tools_revoked)!r}"
            if result.tools_revoked
            else "no-op"
        )
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(
                role="model",
                parts=[
                    types.Part.from_text(
                        text=f"MACROPHAGE: {target_id} -> {summary}"
                    )
                ],
            ),
            actions=EventActions(
                state_delta={STATE_RESULT: _serialize_result(result)}
            ),
        )
