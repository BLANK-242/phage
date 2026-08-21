"""MARROW — fleet orchestrator.

Iterates the registered SAIL fleet (src/phage/targets.py) and fans out into
VACCINATOR once per target via the `ctx.run_node()` seam proven in the v0
single-target commit. Sequential only — no asyncio.gather, no concurrency
(out of scope for this commit). SENTINEL now triages every firing in this
same loop (see "SENTINEL WIRING" below), and MACROPHAGE now acts on a
"landed" verdict immediately after (see "MACROPHAGE WIRING" below).

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

FIRE-AND-CAPTURE (this commit): after collecting a target's payloads, MARROW
fires each one at the REAL target agent (agents/order_intake, .../
supplier_relay, .../stock_keeper, .../quote_bot — commit a3aad51) via its own
InMemoryRunner + a session scoped to that target+payload, and records the
session_id. Verified facts:
  - Direct agent-to-agent invocation via InMemoryRunner is the same pattern
    already proven four times (run_local.py, run_vaccinator_agent.py,
    run_marrow.py, run_fleet_smoke.py) — just pointed at a target agent with
    a payload string as the new message, instead of at VACCINATOR/MARROW/HELLO.
  - Capturing what a fired payload actually does requires a TracerProvider to
    be installed BEFORE these calls happen — confirmed NOT installed by
    default (telemetry/setup.py: maybe_set_otel_providers only calls
    trace.set_tracer_provider(...) if span_processors is non-empty, which
    needs either explicit hooks or OTEL_EXPORTER_OTLP_*ENDPOINT env vars,
    neither present here). Installing it is an ENTRY-POINT concern (matches
    how real ADK deployments configure tracing at the server/CLI level, not
    inside agent code) — this module does NOT install a TracerProvider
    itself; scripts/run_marrow.py does, once, before any run.
  - execute_tool spans carry gcp.vertex.agent.tool_call_args / tool_response
    as real JSON by default (ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS defaults
    'true', telemetry/context.py:211) — no extra config needed for content.
  - `agents/*` is a repo-root sibling of `src/`, not part of the installed
    `phage` package, so the agents.* imports below only resolve if the repo
    root is already on sys.path — the entry script (run_marrow.py) must do
    that (matching run_local.py's/run_fleet_smoke.py's existing pattern for
    their own target-agent imports) BEFORE importing anything from
    phage.marrow. This module does not mutate sys.path itself: phage.* stays
    a clean, independently-packaged library; agents/* dependency is an
    entry-point wiring concern, consistent with the existing one-directional
    separation (agents/hello/agent.py: "must not import the wider phage
    package").
  - Only the session_id is stored, not the trace itself (marrow.
    fleet_fire_sessions, keyed the same shape as marrow.fleet_payloads:
    {target_id: [session_id, ...]}, parallel-indexed with fleet_payloads'
    per-target payload list) — reading the trace back was left as a
    consumer concern at the time (SENTINEL, later); SENTINEL itself now
    does that read (see "SENTINEL WIRING" below), via
    SqliteSpanExporter.get_all_spans_for_session
    (telemetry/sqlite_span_exporter.py:214-235).

SENTINEL WIRING (this commit): immediately after each payload fire is
captured (previous section), MARROW seeds SENTINEL's inputs and fans out
into it via ctx.run_node — the identical mechanism used for VACCINATOR
above (step 2 in run_node_impl), confirmed generic rather than
VACCINATOR-specific per this commit's own recon brief: ctx.run_node's
`node` param is typed NodeLike = BaseNode | BaseTool | Callable[..., Any] |
Literal["START"] (workflow/_graph.py:40-42), and BaseAgent(BaseNode)
(agents/base_agent.py:93) — SENTINEL, a BaseAgent exactly like VACCINATOR,
qualifies the same way. get_invocation_context's shared-session copy
(context.py:411-422, `'session': self.session` at :416) is what makes a
child's state_delta write land in this same ctx.session.state, readable
immediately after run_node returns — not something special-cased for
VACCINATOR's own invocation.

  - SENTINEL's contract confirmed by reading sentinel/adk_agent.py directly
    this commit, not assumed from the brief (sentinel/adk_agent.py:72-76,
    116-149): four required session-state inputs — sentinel.target_id
    (str), sentinel.payload (dict, ONE payload, not a list — SENTINEL
    triages one firing per invocation), sentinel.session_id (str, this
    firing's fire session_id), sentinel.trace_db_path (str). Missing or
    wrong-typed any of the four -> SENTINEL skips silently
    (adk_agent.py:121-149) rather than raising; this module does not
    change that behavior, only feeds it correctly.
  - trace_db_path is not invented here. SqliteSpanExporter installation is
    already an entry-point concern, not agent code, per FIRE-AND-CAPTURE
    above; the db path SENTINEL needs to read those spans back gets the
    same treatment. Read once from session.state["sentinel.trace_db_path"]
    before the fleet loop starts (this module does not know or guess a
    repo-relative path) — scripts/run_marrow.py seeds it at MARROW's own
    session creation, from the same TRACE_DB_PATH local it already uses for
    its own TracerProvider install (run_marrow.py:60): one path, one source
    of truth, not duplicated.
  - sentinel.verdict is a single non-namespaced key, overwritten on every
    SENTINEL call — the identical overwrite hazard as vaccinator.payloads
    above, same fix: read it immediately into a local (target_verdicts)
    right after each run_node() call, before the next payload's seed
    overwrites it. Aggregated into marrow.fleet_verdicts on the final
    summary event, same shape as marrow.fleet_fire_sessions
    ({target_id: [verdict_dict_or_None, ...]}), positionally parallel to
    fleet_fire_sessions — both lists grow together, only on a fire that
    actually succeeded.
  - A MACROPHAGE placeholder was left at the equivalent point in the loop
    (undesigned at the time — see docs/2026-08-12_PHAGE.md's open
    questions); now replaced (see "MACROPHAGE WIRING" below).

MACROPHAGE WIRING (this commit): immediately after SENTINEL, in the same
try block, same firing — mirrors the SENTINEL WIRING above exactly:
ctx.run_node(MACROPHAGE(), run_id=session_id, use_sub_branch=True), own
try/except so a containment failure is reported as one, not conflated with
a triage or fire failure, and does not abort the rest of the fleet loop.

  - MACROPHAGE reads session.state["sentinel.verdict"] directly — the same
    key SENTINEL just wrote above, still fresh (nothing overwrites it
    between SENTINEL's write and MACROPHAGE's read at this point in the
    same iteration). No macrophage.* input key is seeded here: that dict
    already carries target_id/verdict/supporting_spans
    (sentinel/adk_agent.py:79-90), which is everything MACROPHAGE needs.
  - The SENTINEL try block's except now `continue`s (previously it just
    fell through to the placeholder) — required so MACROPHAGE is never
    reached when SENTINEL itself failed for this firing, which would
    otherwise read a STALE sentinel.verdict left over from an earlier
    firing and act on the wrong evidence. This is the same per-item-skip
    discipline the fire's own except already used one level up.
  - macrophage/adk_agent.py resolves target_id -> the real live Agent
    object via _TARGET_AGENTS (this module, above) — imported directly by
    that module rather than passed through state; see that module's
    docstring for the confirmed reasoning (targets.py's FLEET has no live
    connection to _TARGET_AGENTS at all, and a live object can't cleanly
    round-trip through this codebase's JSON-friendly session-state
    convention).

ARCHIVIST WIRING (this commit): two separate insertion points, per
docs/PHAGE_cc_prompt_archivist_build.md Task 3, contingent on that brief's
Gate A — confirmed against PHAGE_build_prompt.md:35 directly, not assumed:
"On second exposure, ARCHIVIST recognition fires before the payload lands."

  - Pre-fire gate: recognize() is called at the top of the per-payload loop,
    before session_id/otel/fire_runner — i.e. before dispatch, matching
    Gate A's confirmed ordering exactly. Unlike VACCINATOR/SENTINEL/
    MACROPHAGE, ARCHIVIST is NOT a BaseAgent run via ctx.run_node: its build
    brief describes plain function calls ("MARROW calls recognize()"), and
    its own spec is entirely ADK-agnostic (no session-state contract, no
    Event/EventActions) — a run_node round trip would add exactly the kind
    of overhead the spec's "recognition fires in milliseconds"
    (PHAGE_build_prompt.md:193) argues against.
  - recognize() itself fails open (its own docstring) — a Memory Bank
    exception becomes recognized=False, never a raise — so this call cannot
    itself introduce a new per-payload failure mode; no additional
    try/except wraps it here, matching that guarantee rather than
    duplicating it.
  - A recognized=True result short-circuits via a plain `continue`, before
    session_id is even constructed — no fire, no SENTINEL run_node, no
    MACROPHAGE run_node for that payload, exactly as the brief specifies.
    target_recognitions still gets an entry either way (append happens
    before the branch), so — unlike session_ids/target_verdicts, which only
    grow past the firing step — this list is positionally parallel to
    results[target.id] for every payload attempted, recognized or not.
  - Signature write: record() is called after the MACROPHAGE try/except,
    at the tail of the per-payload loop — "where the cycle already ends"
    (build brief Task 3) and the master spec's own explicit order
    (PHAGE_build_prompt.md:35: "...MACROPHAGE contains -> ARCHIVIST records
    the signature"). record() no-ops internally on a non-landed verdict, so
    MARROW calls it unconditionally, reusing verdict_dict captured at the
    SENTINEL read above (fresh by construction: the only path that reaches
    this call is the one where that read just succeeded this iteration).
    Its own try/except does NOT fail open — a write failure is a distinct
    fact from a triage/containment failure, same isolation discipline as
    those two, not the pre-fire-gate's different (fail-open) discipline.
"""

from __future__ import annotations

from typing import Any, AsyncGenerator

from typing_extensions import override

from google.adk.agents.context import Context
from google.adk.events import Event, EventActions
from google.adk.runners import InMemoryRunner
from google.adk.workflow import Node
from google.genai import types
from opentelemetry import context as otel_context_api

from agents.order_intake.agent import root_agent as _order_intake_agent
from agents.quote_bot.agent import root_agent as _quote_bot_agent
from agents.stock_keeper.agent import root_agent as _stock_keeper_agent
from agents.supplier_relay.agent import root_agent as _supplier_relay_agent
from phage.archivist.memory import RecognitionResult, record, recognize
from phage.macrophage.adk_agent import MACROPHAGE
from phage.sentinel.adk_agent import (
    SENTINEL,
    STATE_PAYLOAD as SENTINEL_STATE_PAYLOAD,
    STATE_SESSION_ID as SENTINEL_STATE_SESSION_ID,
    STATE_TARGET_ID as SENTINEL_STATE_TARGET_ID,
    STATE_TRACE_DB_PATH as SENTINEL_STATE_TRACE_DB_PATH,
    STATE_VERDICT as SENTINEL_STATE_VERDICT,
)
from phage.targets import FLEET
from phage.vaccinator.adk_agent import (
    STATE_PAYLOADS,
    STATE_TARGET_ID,
    STATE_TOOL_SCOPE,
    VACCINATOR,
)

# Registry-id (targets.py, hyphenated) -> the real target agent to fire at.
# Explicit, not derived by string transform, because the agent's own `name`
# field (underscored, identifier-validated) and the registry id (hyphenated)
# are deliberately different namespaces (established when the fleet was built,
# commit a3aad51) — a mechanical hyphen/underscore swap would be fragile.
_TARGET_AGENTS = {
    "ORDER-INTAKE": _order_intake_agent,
    "SUPPLIER-RELAY": _supplier_relay_agent,
    "STOCK-KEEPER": _stock_keeper_agent,
    "QUOTE-BOT": _quote_bot_agent,
}

_FIRE_APP = "phage-marrow-fire"
_FIRE_USER = "fire"

# MARROW-owned state key (dotted-namespace convention matches vaccinator.* in
# adk_agent.py). Needed because session.state["vaccinator.payloads"] is
# overwritten every loop iteration (state is not branch-isolated — see module
# docstring), so nothing outside this generator's own `results` local can see
# per-target payloads after the loop ends UNLESS the aggregate is also written
# to state. Shared with tests (scripts/run_marrow.py) — import this, don't
# re-type the string.
STATE_FLEET_PAYLOADS = "marrow.fleet_payloads"

# {target_id: [session_id, ...]} — one session_id per fired payload, same
# order/shape as STATE_FLEET_PAYLOADS' per-target payload list, so a caller
# can zip the two by position to correlate a specific payload with its trace.
# Only the session_id is stored; the trace itself is a read-back concern for
# whoever consumes this next (SqliteSpanExporter.get_all_spans_for_session).
STATE_FLEET_FIRE_SESSIONS = "marrow.fleet_fire_sessions"

# {target_id: [verdict_dict | None, ...]} — one SENTINEL verdict per fired
# payload, positionally parallel to STATE_FLEET_FIRE_SESSIONS' per-target
# session_id list (both grow together, only on a fire that succeeded — see
# "SENTINEL WIRING" in the module docstring). verdict_dict is
# adk_agent._serialize_result's shape (sentinel/adk_agent.py:79-90); None
# means SENTINEL skipped or failed for that one firing (module docstring).
STATE_FLEET_VERDICTS = "marrow.fleet_verdicts"

# {target_id: [recognition_dict, ...]} — one ARCHIVIST recognition result per
# payload ATTEMPTED (unlike the three lists above, this one grows for every
# payload in results[target.id], including short-circuited ones — see
# "ARCHIVIST WIRING" in the module docstring). recognition_dict is
# _serialize_recognition's shape, below. recognized=True entries are the ones
# that short-circuited (no fire, no SENTINEL, no MACROPHAGE for that payload).
STATE_FLEET_RECOGNITIONS = "marrow.fleet_recognitions"


def _serialize_recognition(r: RecognitionResult) -> dict[str, Any]:
    """RecognitionResult -> plain dict, so session state stays JSON-friendly
    (mirrors vaccinator/adk_agent.py's _serialize_payload / sentinel/
    adk_agent.py's _serialize_result)."""
    return {
        "recognized": r.recognized,
        "distance": r.distance,
        "matched_fact": r.matched_fact,
        "matched_memory_name": r.matched_memory_name,
        "error": r.error,
    }


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
        fire_sessions: dict[str, list[str]] = {}
        verdicts: dict[str, list[dict[str, Any] | None]] = {}
        recognitions: dict[str, list[dict[str, Any]]] = {}

        # Read once, outside the loop — the db path SENTINEL needs to read
        # spans back from doesn't change per target. Seeded by the entry
        # point at session-creation time (scripts/run_marrow.py), same
        # separation-of-concerns as the TracerProvider install itself (see
        # FIRE-AND-CAPTURE above): this module does not know or guess a
        # repo-relative db path. None if the caller didn't seed it —
        # SENTINEL itself then skips gracefully on the missing value
        # (sentinel/adk_agent.py:121-149), unchanged by this module.
        trace_db_path = ctx.session.state.get(SENTINEL_STATE_TRACE_DB_PATH)

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

            # 4. Fire each of this target's payloads at the REAL target agent
            #    (direct agent-to-agent invocation via InMemoryRunner — the
            #    same proven pattern as run_local.py/run_fleet_smoke.py, just
            #    pointed at a target with the payload's injection_text as the
            #    new message). One session per payload, so its trace can be
            #    pulled back individually by session_id — SENTINEL does
            #    exactly that immediately below, once per firing (see
            #    "SENTINEL WIRING" in the module docstring). Sequential, same
            #    as the rest of this loop — no
            #    concurrency. One payload's failure (e.g. a transient
            #    call error) must not abort the rest of the fleet loop, so
            #    it's caught and skipped rather than propagated — the same
            #    per-item isolation the engine already uses for its own
            #    per-archetype Gemini calls (vaccinator/engine.py).
            #
            #    otel_context_api.attach(Context())/detach(...) around each
            #    call: WITHOUT this, every fired payload in this loop inherits
            #    ONE shared trace_id from the outer run_async(MARROW()) call
            #    that is still the "current span" for the whole lifetime of
            #    this generator — confirmed empirically (queried
            #    phage_traces.db directly): all ~28 firings across all 4
            #    targets landed under a single trace_id, so
            #    SqliteSpanExporter.get_all_spans_for_session(session_id)
            #    (which looks up by trace_id, not the session_id column —
            #    sqlite_span_exporter.py's own docstring) returned the WHOLE
            #    fleet's spans for ANY one session_id, not just that firing's.
            #    Detaching to a fresh, empty Context before each fire call
            #    forces ADK's invoke_agent span to start a genuinely new root
            #    trace, so each firing gets its own trace_id and
            #    get_all_spans_for_session(session_id) is correctly isolated
            #    to just that one firing.
            target_agent = _TARGET_AGENTS.get(target.id)
            session_ids: list[str] = []
            target_verdicts: list[dict[str, Any] | None] = []
            target_recognitions: list[dict[str, Any]] = []
            if target_agent is not None:
                fire_runner = InMemoryRunner(agent=target_agent, app_name=_FIRE_APP)
                for payload in results[target.id]:
                    # ARCHIVIST pre-fire gate (Gate A, PHAGE_build_prompt.md:35:
                    # "On second exposure, ARCHIVIST recognition fires before
                    # the payload lands") — called unconditionally, before any
                    # dispatch. recognize() itself fails open, so this can
                    # never raise and never blocks the loop on its own.
                    recognition = recognize(
                        target_id=target.id,
                        archetype_id=payload["archetype_id"],
                        target_tools=payload["target_tools"],
                        injection_text=payload["injection_text"],
                    )
                    target_recognitions.append(_serialize_recognition(recognition))
                    if recognition.error:
                        # recognize() fails open on a client exception, so
                        # recognized is always False here too — but that read
                        # as a silent miss with no print at all before this
                        # fix. Surface it: a Memory Bank outage masquerading
                        # as "nothing recognized" is worth seeing, even though
                        # (by design) it must not block the fire loop.
                        print(
                            f"MARROW: recognition check failed for {target.id}/"
                            f"{payload['archetype_id']}: {recognition.error} "
                            "— failing open, proceeding to fire"
                        )
                    if recognition.recognized:
                        print(
                            f"MARROW: recognized {target.id}/{payload['archetype_id']} "
                            f"at distance={recognition.distance} — short-circuiting "
                            "(no fire, no SENTINEL, no MACROPHAGE)"
                        )
                        continue

                    session_id = f"fire-{target.id}-{payload['archetype_id']}"
                    otel_token = otel_context_api.attach(otel_context_api.Context())
                    try:
                        await fire_runner.session_service.create_session(
                            app_name=_FIRE_APP,
                            user_id=_FIRE_USER,
                            session_id=session_id,
                        )
                        message = types.Content(
                            role="user",
                            parts=[types.Part(text=payload["injection_text"])],
                        )
                        async for _fired_event in fire_runner.run_async(
                            user_id=_FIRE_USER,
                            session_id=session_id,
                            new_message=message,
                        ):
                            pass  # drain; the trace is what matters here, not the reply
                        session_ids.append(session_id)
                    except Exception as exc:  # noqa: BLE001 -- isolate per payload
                        print(
                            f"MARROW: fire failed for {target.id}/"
                            f"{payload['archetype_id']}: {exc}"
                        )
                        continue
                    finally:
                        otel_context_api.detach(otel_token)

                    # Immediately triage this firing via SENTINEL — same
                    # ctx.run_node() mechanism as step 2 above (VACCINATOR),
                    # confirmed generic for any BaseAgent rather than
                    # VACCINATOR-specific (see "SENTINEL WIRING" in the
                    # module docstring). Own try/except, separate from the
                    # fire's above: a triage failure is a different fact
                    # than a fire failure and must not be reported as one,
                    # and must not abort the rest of the fleet loop either
                    # (same per-item isolation as the fire itself). Runs
                    # after otel_token is detached above — triage is not
                    # part of the fire's own isolated trace.
                    try:
                        yield Event(
                            invocation_id=ctx.invocation_id,
                            author=self.name,
                            content=types.Content(
                                role="model",
                                parts=[
                                    types.Part.from_text(
                                        text=f"MARROW: triaging {session_id}"
                                    )
                                ],
                            ),
                            actions=EventActions(
                                state_delta={
                                    SENTINEL_STATE_TARGET_ID: target.id,
                                    SENTINEL_STATE_PAYLOAD: payload,
                                    SENTINEL_STATE_SESSION_ID: session_id,
                                    SENTINEL_STATE_TRACE_DB_PATH: trace_db_path,
                                }
                            ),
                        )
                        await ctx.run_node(
                            SENTINEL(), run_id=session_id, use_sub_branch=True
                        )
                        # Read back NOW, before the next payload's seed
                        # overwrites sentinel.verdict — a single
                        # non-namespaced key, same overwrite hazard as
                        # vaccinator.payloads (module docstring above), same
                        # fix: immediate synchronous read into a local.
                        # Captured into verdict_dict (not just appended) so
                        # the ARCHIVIST record() call below the MACROPHAGE
                        # block can reuse this exact value — reached only via
                        # this same try succeeding, so it is never stale.
                        verdict_dict = ctx.session.state.get(SENTINEL_STATE_VERDICT)
                        target_verdicts.append(verdict_dict)
                    except Exception as exc:  # noqa: BLE001 -- isolate per payload
                        print(
                            f"MARROW: triage failed for {target.id}/"
                            f"{payload['archetype_id']}: {exc}"
                        )
                        target_verdicts.append(None)
                        continue

                    # Immediately act on this firing's SENTINEL verdict via
                    # MACROPHAGE — same ctx.run_node() mechanism, mirrors
                    # exactly how SENTINEL itself was wired in above (see
                    # "MACROPHAGE WIRING" in the module docstring). No
                    # state to seed here: MACROPHAGE reads
                    # session.state["sentinel.verdict"] directly, still
                    # fresh from the read above. Own try/except: a
                    # containment failure is a different fact than a
                    # triage failure and must not be reported as one, and
                    # must not abort the rest of the fleet loop either
                    # (same per-item isolation as fire/triage above). The
                    # `continue` in SENTINEL's except above guarantees this
                    # is only ever reached with a fresh, this-firing
                    # verdict already in state.
                    try:
                        await ctx.run_node(
                            MACROPHAGE(), run_id=session_id, use_sub_branch=True
                        )
                    except Exception as exc:  # noqa: BLE001 -- isolate per payload
                        print(
                            f"MARROW: containment failed for {target.id}/"
                            f"{payload['archetype_id']}: {exc}"
                        )

                    # ARCHIVIST signature write — "where the cycle already
                    # ends" (build brief Task 3), after MACROPHAGE, matching
                    # the master spec's own cycle order (PHAGE_build_prompt.md
                    # :35: "...MACROPHAGE contains -> ARCHIVIST records the
                    # signature"). record() itself no-ops on a non-landed
                    # verdict, so this is called unconditionally — "MARROW
                    # holds no domain logic." Own try/except: does NOT fail
                    # open the way recognize() does — a write failure here is
                    # a distinct fact from a triage/containment failure, same
                    # per-payload isolation discipline as those two above.
                    try:
                        verdict_str = (
                            verdict_dict.get("verdict")
                            if isinstance(verdict_dict, dict)
                            else None
                        )
                        record(
                            target_id=target.id,
                            archetype_id=payload["archetype_id"],
                            target_tools=payload["target_tools"],
                            injection_text=payload["injection_text"],
                            verdict=verdict_str or "",
                        )
                    except Exception as exc:  # noqa: BLE001 -- isolate per payload
                        print(
                            f"MARROW: signature write failed for {target.id}/"
                            f"{payload['archetype_id']}: {exc}"
                        )
            fire_sessions[target.id] = session_ids
            verdicts[target.id] = target_verdicts
            recognitions[target.id] = target_recognitions

        # 5. Fleet summary event.
        total = sum(len(ps) for ps in results.values())
        total_gemini = sum(
            1 for ps in results.values() for p in ps if p.get("source") == "gemini"
        )
        total_local = total - total_gemini
        total_recognized = sum(
            1 for rs in recognitions.values() for r in rs if r.get("recognized")
        )
        total_fired = sum(len(sids) for sids in fire_sessions.values())
        total_triaged = sum(1 for vs in verdicts.values() for v in vs if v is not None)
        verdict_counts: dict[str, int] = {}
        for vs in verdicts.values():
            for v in vs:
                if v is not None:
                    verdict_counts[v["verdict"]] = verdict_counts.get(v["verdict"], 0) + 1
        verdict_breakdown = (
            ", ".join(f"{k}={n}" for k, n in sorted(verdict_counts.items())) or "none"
        )
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
                            f"({total_gemini} gemini / {total_local} local-fallback), "
                            f"{total_recognized}/{total} recognized by ARCHIVIST "
                            f"(short-circuited before dispatch), "
                            f"{total_fired}/{total} fired at real targets, "
                            f"{total_triaged}/{total_fired} triaged by SENTINEL "
                            f"({verdict_breakdown}) — {per_target}"
                        )
                    )
                ],
            ),
            # Structured per-target results, so a caller can verify each
            # target's payloads without text-parsing the summary above (see
            # STATE_FLEET_PAYLOADS / STATE_FLEET_FIRE_SESSIONS /
            # STATE_FLEET_VERDICTS / STATE_FLEET_RECOGNITIONS docstrings for
            # why these keys exist).
            actions=EventActions(
                state_delta={
                    STATE_FLEET_PAYLOADS: results,
                    STATE_FLEET_FIRE_SESSIONS: fire_sessions,
                    STATE_FLEET_VERDICTS: verdicts,
                    STATE_FLEET_RECOGNITIONS: recognitions,
                }
            ),
        )
