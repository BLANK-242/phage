"""VACCINATOR — ADK agent wrapper around the deterministic payload engine.

Scope of this module: wrap `generate_payloads` (engine.py) in a single ADK
agent that reads a target's tool_scope from session state and writes the
generated payloads back to session state. No registry, no identity/gateway
shims, no Firestore, no MARROW, no other agents — those are later prompts.

Design: a custom `BaseAgent` subclass, NOT a tool on an `LlmAgent`. The engine
is deterministic; putting an LlmAgent in the loop would re-invite Gemini
refusals at the agent layer, which the engine's own tailoring design
(per-archetype isolation + local-fallback guarantee, see engine.py) already
exists to avoid. This agent stores no state of its own and owns no model —
`generate_payloads` owns all synthesis logic, provenance, and the no-routing
guardrail; this module is purely an ADK-shaped adapter.

Every signature below was re-verified against installed ADK 2.6.3 source
(not recalled) as this module was written:
  - BaseAgent: google/adk/agents/base_agent.py:93 (pydantic model,
    `extra='forbid'`, `arbitrary_types_allowed=True` — base_agent.py:96-99).
  - `name: str` has NO field default on BaseAgent (base_agent.py:121) and is
    validated to be a Python identifier, not "user" (base_agent.py:619-634).
    Confirmed empirically that overriding it with a class-level default
    (`name: str = "VACCINATOR"`) is valid pydantic-v2 subclassing and makes
    `VACCINATOR()` zero-arg constructible — no custom `__init__` needed.
  - Override target: `_run_async_impl(self, ctx: InvocationContext) ->
    AsyncGenerator[Event, None]` — base_agent.py:370-372 (default impl raises
    NotImplementedError, base_agent.py:381-384). `abc.ABC` on BaseAgent does
    NOT enforce this at construction time (verified empirically); it only
    fails if actually called without an override.
  - No `model` field on BaseAgent (only LlmAgent has `model`/`instruction`) —
    correct, VACCINATOR owns no model; the engine owns its own Gemini client.
  - `Event(LlmResponse)` — google/adk/events/event.py:91. `content:
    Optional[types.Content]` is inherited from LlmResponse
    (models/llm_response.py:62). `invocation_id: str` (event.py:107),
    `author: str` (event.py:109), `branch: str | None` (event.py:126),
    `actions: EventActions` (event.py:112, default_factory=EventActions).
  - Content/role/Part construction pattern matches the closest existing
    precedent for "custom BaseAgent wrapping deterministic external logic
    and emitting its own Event" — LangGraphAgent._run_async_impl,
    google/adk/agents/langgraph_agent.py:105-114: `Event(invocation_id=
    ctx.invocation_id, author=self.name, branch=ctx.branch,
    content=types.Content(role='model', parts=[types.Part.from_text(
    text=result)]))`.
  - `EventActions.state_delta: dict[str, Any]` — events/event_actions.py:94.
    This is the mechanism by which a yielded Event's state changes reach the
    session: `BaseSessionService.append_event` (base_session_service.py:154)
    calls `_update_session_state` (base_session_service.py:204-209), which
    does `session.state.update(...)` for every key in `state_delta`. Confirmed
    the runner appends every yielded event (runners.py, multiple call sites
    to `session_service.append_event`, e.g. :830).
  - ADK's own state-key prefixes are colon-delimited — `State.APP_PREFIX =
    "app:"`, `USER_PREFIX = "user:"`, `TEMP_PREFIX = "temp:"`
    (sessions/state.py:64-66). The dotted keys used below
    (`"vaccinator.tool_scope"` etc.) do NOT collide with any of these; they
    are plain session-scoped state.
  - `InvocationContext.session: Session` (agents/invocation_context.py:186),
    `.invocation_id: str` (:156, required — no default), `.branch:
    Optional[str] = None` (:158). `Session.state: dict[str, Any]`
    (sessions/session.py:51).
  - Trap #1 does NOT apply here: the agent/runner layer imports no Vertex/
    Agent-Engine platform client (confirmed: `grep vertexai|agentplatform|
    \\.Client` over base_agent.py and runners.py returns nothing beyond
    `from google.genai import types`, runners.py:33). The engine's own
    `genai.Client(**config.gemini_client_kwargs())` (engine.py) is the only
    client anywhere in this path; this module adds none.
"""

from __future__ import annotations

from typing import Any, AsyncGenerator

from typing_extensions import override

from google.adk.agents import BaseAgent, InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types

from phage.vaccinator.engine import Payload, generate_payloads

# --- session-state contract -----------------------------------------------
# Shared with MARROW (later) and with tests — import these, don't re-type the
# strings, so the contract stays a single source of truth.
STATE_TOOL_SCOPE = "vaccinator.tool_scope"  # in:  list[str], the target's declared tools
STATE_TARGET_ID = "vaccinator.target_id"  # in (optional): str, registry id, echoed through
STATE_PAYLOADS = "vaccinator.payloads"  # out: list[dict], serialized Payload


def _serialize_payload(p: Payload) -> dict[str, Any]:
    """Payload dataclass -> plain dict, so session state stays JSON-friendly."""
    return {
        "archetype_id": p.archetype_id,
        "category": p.category,
        "intent": p.intent,
        "target_tools": list(p.target_tools),
        "injection_text": p.injection_text,
        "paraphrase": p.paraphrase,
        "source": p.source,
    }


class VACCINATOR(BaseAgent):
    """ADK adapter around the deterministic templated-mutation payload engine.

    Reads `tool_scope` (and optional `target_id`) from session state, calls
    the module-level `generate_payloads` engine with default args (Gemini
    enabled; per-archetype isolation and the local-fallback guarantee live
    entirely in the engine — see engine.py), and writes the serialized
    payloads back to session state. Holds no state of its own and no model.
    """

    name: str = "VACCINATOR"
    description: str = (
        "Generates tool-tailored prompt-injection payloads for a target's "
        "declared tool scope, via the deterministic templated-mutation engine."
    )

    @override
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        tool_scope = ctx.session.state.get(STATE_TOOL_SCOPE)
        target_id = ctx.session.state.get(STATE_TARGET_ID)

        if not (
            isinstance(tool_scope, list)
            and tool_scope
            and all(isinstance(t, str) for t in tool_scope)
        ):
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                branch=ctx.branch,
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(
                            text=(
                                f"VACCINATOR: skipped — session.state[{STATE_TOOL_SCOPE!r}] "
                                "is missing or not a non-empty list[str]."
                            )
                        )
                    ],
                ),
            )
            return

        # Module-level, default args (Gemini enabled). Do not re-implement or
        # alter the engine here — provenance and the no-routing guardrail live
        # entirely in generate_payloads/engine.py and must stay untouched.
        # target_id (already read above) is threaded through purely so a
        # MutationRefused raised inside the engine identifies its target; it
        # is not caught here — see engine.MutationRefused's docstring for why
        # it must propagate rather than be turned into a graceful skip.
        payloads: list[Payload] = generate_payloads(tool_scope, target_id=target_id)

        state_delta: dict[str, Any] = {
            STATE_PAYLOADS: [_serialize_payload(p) for p in payloads],
        }
        if target_id is not None:
            state_delta[STATE_TARGET_ID] = target_id

        n_gemini = sum(1 for p in payloads if p.source == "gemini")
        n_local = len(payloads) - n_gemini
        label = target_id if target_id else "target"

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(
                role="model",
                parts=[
                    types.Part.from_text(
                        text=(
                            f"VACCINATOR: {len(payloads)} payloads for {label} "
                            f"({n_gemini} gemini / {n_local} local-fallback)"
                        )
                    )
                ],
            ),
            actions=EventActions(state_delta=state_delta),
        )
