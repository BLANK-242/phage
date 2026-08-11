"""SENTINEL — ADK agent wrapper around the triage engine.

Scope of this module: wrap `triage_firing` (triage.py) in a single ADK agent
that reads one firing's inputs from session state and writes the verdict
back. No MARROW integration — that's Stage 3, its own commit, same staged
split VACCINATOR's own build followed (engine -> ADK wrapper -> orchestrator
integration).

Design: a custom `BaseAgent` subclass, same construction pattern as
`vaccinator/adk_agent.py` (commit 99749e6) — re-read in full before writing
this, per the brief's Step 1. Same reasoning applies here: the triage logic
is deterministic-plus-LLM-tiered on its own terms (Gemma first, Gemini only
on genuine ambiguity — triage.py's own discipline); this module adds no
model, no client, no tiering logic of its own. It is a pure ADK-shaped
adapter, exactly like VACCINATOR's.

One firing per invocation (brief's explicit Step 2 instruction), matching how
MARROW already calls VACCINATOR once per target inside its fleet loop — not a
batch. `triage_fleet_firings` (triage.py) already exists for the batch case;
this wrapper deliberately does not reach for it, so Stage 3's future
per-firing loop inside MARROW is a straightforward extension of a pattern
that already exists (run_node once per firing), not a new shape.

Every ADK signature re-verified against installed 2.6.3 source is identical
to vaccinator/adk_agent.py's own citations (BaseAgent, _run_async_impl,
Event, EventActions.state_delta, InvocationContext, state-key prefixes,
trap #1) — see that module's docstring for the full citation list; not
re-derived here since nothing about the ADK contract itself changed.

Session-state contract (Step 1's confirmed triage.py interface, quoted):

    def triage_firing(
        *,
        target_id: str,
        payload: dict[str, Any],
        session_id: str,
        spans: list,
        use_llm: bool = True,
        client=None,
    ) -> TriageResult:
        '''Judge one firing. `spans` should already be filtered to
        execute_tool spans for this firing's session_id (e.g. via
        SqliteSpanExporter.get_all_spans_for_session, filtered by name
        prefix).'''

`spans` is NOT fetched internally by triage_firing — the caller must fetch
and filter it first (triage_fleet_firings does exactly this per-firing,
lines 376-377: `exporter.get_all_spans_for_session(session_id)` then
`[s for s in all_spans if s.name.startswith("execute_tool")]`). This wrapper
does the same fetch+filter step itself, which is why it needs a
trace_db_path input (to construct its own SqliteSpanExporter) in addition to
target_id/payload/session_id — triage.py's interface has no db-path or
exporter parameter of its own to receive one through.
"""

from __future__ import annotations

from typing import Any, AsyncGenerator

from typing_extensions import override

from google.adk.agents import BaseAgent, InvocationContext
from google.adk.events import Event, EventActions
from google.adk.telemetry.sqlite_span_exporter import SqliteSpanExporter
from google.genai import types

from phage.sentinel.triage import TriageResult, triage_firing

# --- session-state contract -------------------------------------------------
# Mirrors vaccinator/adk_agent.py's naming convention exactly (dotted
# <agent_name_lowercase>.<field>) — not a new pattern.
STATE_TARGET_ID = "sentinel.target_id"  # in:  str, registry id of the fired target
STATE_PAYLOAD = "sentinel.payload"  # in:  dict, ONE serialized Payload (VACCINATOR's _serialize_payload shape)
STATE_SESSION_ID = "sentinel.session_id"  # in:  str, this firing's session_id (a marrow.fleet_fire_sessions entry)
STATE_TRACE_DB_PATH = "sentinel.trace_db_path"  # in: str, SqliteSpanExporter db_path to read spans back from
STATE_VERDICT = "sentinel.verdict"  # out: dict, serialized TriageResult


def _serialize_result(r: TriageResult) -> dict[str, Any]:
    """TriageResult -> plain dict, so session state stays JSON-friendly
    (mirrors vaccinator/adk_agent.py's _serialize_payload exactly)."""
    return {
        "target_id": r.target_id,
        "archetype_id": r.archetype_id,
        "session_id": r.session_id,
        "verdict": r.verdict.value,
        "tier": r.tier.value,
        "reasoning": r.reasoning,
        "supporting_spans": list(r.supporting_spans),
    }


class SENTINEL(BaseAgent):
    """ADK adapter around the triage engine (triage.py).

    Reads one firing's target_id/payload/session_id/trace_db_path from
    session state, fetches and filters that firing's execute_tool spans via
    SqliteSpanExporter, calls the module-level `triage_firing` with default
    args (Gemma-first, Gemini-escalation-on-ambiguity — triage.py's own
    tiering, untouched), and writes the serialized verdict back to session
    state. Holds no state of its own and no model of its own — triage.py
    owns the Gemma/Gemini clients and all tiering logic.
    """

    name: str = "SENTINEL"
    description: str = (
        "Triages one fired payload's captured execute_tool spans, judging "
        "whether the injection actually landed, via the Gemma-first / "
        "Gemini-escalation triage engine."
    )

    @override
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        target_id = ctx.session.state.get(STATE_TARGET_ID)
        payload = ctx.session.state.get(STATE_PAYLOAD)
        session_id = ctx.session.state.get(STATE_SESSION_ID)
        trace_db_path = ctx.session.state.get(STATE_TRACE_DB_PATH)

        if not (
            isinstance(target_id, str)
            and target_id
            and isinstance(payload, dict)
            and payload
            and isinstance(session_id, str)
            and session_id
            and isinstance(trace_db_path, str)
            and trace_db_path
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
                                "SENTINEL: skipped — one or more of "
                                f"{STATE_TARGET_ID!r}/{STATE_PAYLOAD!r}/"
                                f"{STATE_SESSION_ID!r}/{STATE_TRACE_DB_PATH!r} "
                                "missing or wrong-typed in session state."
                            )
                        )
                    ],
                ),
            )
            return

        # Fetch + filter this firing's spans — triage_firing does not do this
        # itself (see module docstring: its `spans` param expects a
        # pre-filtered list). Same fetch+filter pattern triage_fleet_firings
        # already uses per-firing (triage.py:376-377).
        exporter = SqliteSpanExporter(db_path=trace_db_path)
        all_spans = exporter.get_all_spans_for_session(session_id)
        tool_spans = [s for s in all_spans if s.name.startswith("execute_tool")]

        # Module-level, default args (use_llm=True — Gemma first, Gemini on
        # genuine ambiguity). Do not re-implement or alter the tiering here —
        # it lives entirely in triage_firing/triage.py and must stay untouched.
        result = triage_firing(
            target_id=target_id,
            payload=payload,
            session_id=session_id,
            spans=tool_spans,
        )

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(
                role="model",
                parts=[
                    types.Part.from_text(
                        text=(
                            f"SENTINEL: {target_id}/{result.archetype_id} -> "
                            f"{result.verdict.value} (tier={result.tier.value})"
                        )
                    )
                ],
            ),
            actions=EventActions(state_delta={STATE_VERDICT: _serialize_result(result)}),
        )
