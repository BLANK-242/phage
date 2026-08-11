#!/usr/bin/env python3
"""End-to-end self-check for MARROW's fleet iteration via run_node into VACCINATOR.

Mirrors scripts/run_vaccinator_agent.py. Two modes:

  (default)      Runs MARROW via InMemoryRunner. MARROW loops over the
                 registered SAIL fleet (src/phage/targets.py), seeding each
                 target's tool_scope into session state and fanning out into
                 VACCINATOR via ctx.run_node in turn. session.state["vaccinator.
                 payloads"] is overwritten every iteration (use_sub_branch does
                 not isolate state — see marrow/agent.py's module docstring), so
                 this reads MARROW's own structured aggregate,
                 state["marrow.fleet_payloads"], and asserts every FLEET target
                 returned at least one payload via run_node. Gemini on.

  --no-gemini    Offline guarantee: calls the engine directly with
                 use_gemini=False for every FLEET target. Bypasses the agent
                 (VACCINATOR's own engine call is fixed to default args) —
                 zero network for payload generation. Still fires ONE
                 generated payload at its real target agent (firing an
                 LlmAgent target inherently needs a live model call — there is
                 no local-only way to observe how a target reacts) so the
                 fire-and-capture mechanism itself is proven in both modes.

Both modes install ONE TracerProvider (module scope, before either mode runs)
wrapping ADK's own shipped local-dev exporter, SqliteSpanExporter — confirmed
NOT installed by default (see marrow/agent.py's module docstring). Every
execute_tool span from every fired payload lands in phage_traces.db,
queryable afterward via SqliteSpanExporter.get_all_spans_for_session(session_id).
"""

import asyncio
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
# phage.marrow.agent imports agents.* (the real target agents) to fire
# payloads at them; agents/ is a repo-root sibling of src/, not part of the
# installed phage package, so the repo root must be on sys.path BEFORE that
# import happens — matching run_local.py's/run_fleet_smoke.py's existing
# pattern for their own target-agent imports.

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.adk.telemetry.sqlite_span_exporter import SqliteSpanExporter  # noqa: E402
from google.genai import types  # noqa: E402
from opentelemetry import trace  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402

from phage.marrow.agent import (  # noqa: E402
    MARROW,
    STATE_FLEET_FIRE_SESSIONS,
    STATE_FLEET_PAYLOADS,
)
from phage.targets import FLEET  # noqa: E402
from phage.vaccinator.engine import generate_payloads  # noqa: E402

APP = "phage-marrow"
TRACE_DB_PATH = os.path.join(REPO_ROOT, "phage_traces.db")


def install_tracer_provider() -> SqliteSpanExporter:
    """Install ONE TracerProvider for the whole script run (not per-target),
    wrapping ADK's own shipped local-dev exporter. SimpleSpanProcessor (not
    Batch): exports synchronously as each span ends, so spans are durably in
    the sqlite file by the time this script reads them back at the end — no
    batching delay to race against. Returns the exporter so the self-check
    can query it directly without re-opening the db file.
    """
    exporter = SqliteSpanExporter(db_path=TRACE_DB_PATH)
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return exporter


def _print_span(span) -> None:
    args = span.attributes.get("gcp.vertex.agent.tool_call_args", "<none>")
    resp = span.attributes.get("gcp.vertex.agent.tool_response", "<none>")
    print(f"    span: {span.name}")
    print(f"      tool_call_args: {args}")
    print(f"      tool_response:  {resp}")


def _print_provenance(entries: list[tuple[str, str]]) -> None:
    for archetype_id, source in entries:
        print(f"    [{source:14}] {archetype_id}")


def _fail(problems: list[str]) -> int:
    print("SELF-CHECK: FAIL")
    for pr in problems:
        print("  -", pr)
    return 1


async def run_local_only(exporter: SqliteSpanExporter) -> int:
    """Engine local-only path, direct call per FLEET target — zero network for
    payload generation. Then fires ONE generated payload (preferring
    data-exfiltration — deterministic, since use_gemini=False rendering has
    no randomness) at its real target agent, to prove the fire-and-capture
    mechanism itself works even when VACCINATOR made zero network calls.
    Firing itself is NOT zero-network — the target is a real LlmAgent and
    must call Gemini to decide how to react; there is no local-only way to
    observe that.
    """
    problems: list[str] = []
    all_payloads: dict[str, list] = {}
    for target in FLEET:
        print(f"[local-only] target={target.id}  tool_scope={target.tool_scope}")
        payloads = generate_payloads(target.tool_scope, use_gemini=False)
        all_payloads[target.id] = payloads
        entries = [(p.archetype_id, p.source) for p in payloads]
        _print_provenance(entries)
        print()

        if not payloads:
            problems.append(f"{target.id}: no payloads generated")
        if any(src != "local-fallback" for _, src in entries):
            problems.append(f"{target.id}: expected ALL payloads local-fallback with use_gemini=False")

    if problems:
        return _fail(problems)

    # Prefer data-exfiltration for the fire-and-capture spot-check: its
    # template supplies a concrete destination (audit@external-check.example)
    # and a specific source->sink instruction, so the target has enough to
    # actually construct real tool call arguments — unlike e.g.
    # instruction-override's bare "call {action}", which a target reasonably
    # declines to act on with no recipient/content to work from (confirmed
    # empirically: fired instruction-override -> 0 execute_tool spans).
    first_target, first_payload = None, None
    for target in FLEET:
        for p in all_payloads[target.id]:
            if p.archetype_id == "data-exfiltration":
                first_target, first_payload = target, p
                break
        if first_target:
            break
    if first_target is None:
        first_target = FLEET[0]
        first_payload = all_payloads[first_target.id][0]

    from agents.order_intake.agent import root_agent as order_intake_agent
    from agents.quote_bot.agent import root_agent as quote_bot_agent
    from agents.stock_keeper.agent import root_agent as stock_keeper_agent
    from agents.supplier_relay.agent import root_agent as supplier_relay_agent

    target_agents = {
        "ORDER-INTAKE": order_intake_agent,
        "SUPPLIER-RELAY": supplier_relay_agent,
        "STOCK-KEEPER": stock_keeper_agent,
        "QUOTE-BOT": quote_bot_agent,
    }
    fire_agent = target_agents[first_target.id]
    session_id = f"local-only-fire-{first_target.id}-{first_payload.archetype_id}"
    print(f"[local-only] firing {first_target.id}/{first_payload.archetype_id} -> {session_id}")

    fire_runner = InMemoryRunner(agent=fire_agent, app_name=APP)
    await fire_runner.session_service.create_session(
        app_name=APP, user_id="fire", session_id=session_id
    )
    message = types.Content(role="user", parts=[types.Part(text=first_payload.injection_text)])
    async for _event in fire_runner.run_async(
        user_id="fire", session_id=session_id, new_message=message
    ):
        pass

    spans = exporter.get_all_spans_for_session(session_id)
    tool_spans = [s for s in spans if s.name.startswith("execute_tool")]
    print(f"  {len(spans)} spans total, {len(tool_spans)} execute_tool spans")
    for s in tool_spans:
        _print_span(s)

    if not tool_spans:
        return _fail([f"no execute_tool spans captured for session {session_id}"])
    if not any(s.attributes.get("gcp.vertex.agent.tool_call_args") not in (None, "{}") for s in tool_spans):
        return _fail([f"execute_tool spans present but tool_call_args empty for session {session_id}"])

    print()
    print(
        f"SELF-CHECK: PASS — all {len(FLEET)} targets produced local-fallback "
        "payloads, zero network; fire-and-capture confirmed with real "
        "execute_tool span content."
    )
    return 0


async def run_via_marrow(exporter: SqliteSpanExporter) -> int:
    """Full ADK wrapper path: MARROW loops FLEET, seeding state + run_node ->
    VACCINATOR per target, then fires every returned payload at its real
    target agent (marrow/agent.py's extended loop) and records a session_id
    per firing in state["marrow.fleet_fire_sessions"]."""
    print(f"[marrow]     fleet={[t.id for t in FLEET]}\n")

    runner = InMemoryRunner(agent=MARROW(), app_name=APP)
    session = await runner.session_service.create_session(app_name=APP, user_id="dev")
    message = types.Content(role="user", parts=[types.Part(text="run")])

    async for event in runner.run_async(
        user_id="dev", session_id=session.id, new_message=message
    ):
        if event.content and event.content.parts:
            text = "".join(part.text or "" for part in event.content.parts)
            if text:
                print("  event:", text)

    final_session = await runner.session_service.get_session(
        app_name=APP, user_id="dev", session_id=session.id
    )
    state = final_session.state if final_session else {}
    fleet_payloads = state.get(STATE_FLEET_PAYLOADS)
    fleet_fire_sessions = state.get(STATE_FLEET_FIRE_SESSIONS)

    print()
    if not fleet_payloads:
        return _fail([f"session.state[{STATE_FLEET_PAYLOADS!r}] missing/empty after the run"])
    if not fleet_fire_sessions:
        return _fail([f"session.state[{STATE_FLEET_FIRE_SESSIONS!r}] missing/empty after the run"])

    problems: list[str] = []
    expected_ids = {t.id for t in FLEET}
    seen_ids = set(fleet_payloads.keys())
    if seen_ids != expected_ids:
        problems.append(f"target mismatch: expected {sorted(expected_ids)}, got {sorted(seen_ids)}")

    for target in FLEET:
        payloads = fleet_payloads.get(target.id) or []
        fired = fleet_fire_sessions.get(target.id) or []
        print(f"  {target.id}: {len(payloads)} payloads, {len(fired)} fired")
        _print_provenance([(p["archetype_id"], p["source"]) for p in payloads])
        if not payloads:
            problems.append(f"{target.id}: no payloads returned via run_node")
        if not fired:
            problems.append(f"{target.id}: no payloads were fired at the real target agent")

    print()
    if problems:
        return _fail(problems)

    # Step 3: pull a real trace back for at least one fired payload, proving
    # the whole chain (generate, fire, capture) end to end — not just that it
    # ran without error. Prefer data-exfiltration, same reasoning as
    # run_local_only: it's the one archetype template concrete enough
    # (a real destination address, a specific source->sink instruction) to
    # reliably produce an actual tool call rather than a declined request.
    spot_target_id, spot_session_id = None, None
    for target in FLEET:
        payloads = fleet_payloads.get(target.id) or []
        sessions = fleet_fire_sessions.get(target.id) or []
        for idx, p in enumerate(payloads):
            if p["archetype_id"] == "data-exfiltration" and idx < len(sessions):
                spot_target_id, spot_session_id = target.id, sessions[idx]
                break
        if spot_session_id:
            break
    if spot_session_id is None:
        spot_target_id = FLEET[0].id
        spot_session_id = fleet_fire_sessions[FLEET[0].id][0]

    print(f"  spot-check: {spot_target_id} / session {spot_session_id!r}")
    spans = exporter.get_all_spans_for_session(spot_session_id)
    tool_spans = [s for s in spans if s.name.startswith("execute_tool")]
    print(f"    {len(spans)} spans total, {len(tool_spans)} execute_tool spans")
    for s in tool_spans:
        _print_span(s)

    if not tool_spans:
        return _fail([f"no execute_tool spans captured for session {spot_session_id}"])
    if not any(s.attributes.get("gcp.vertex.agent.tool_call_args") not in (None, "{}") for s in tool_spans):
        return _fail([f"execute_tool spans present but tool_call_args empty for session {spot_session_id}"])

    print()
    print(
        f"SELF-CHECK: PASS — all {len(FLEET)} fleet targets returned at least "
        "one payload via run_node, every target fired at its real agent, and "
        "real execute_tool span content confirmed for at least one firing."
    )
    return 0


async def main() -> int:
    exporter = install_tracer_provider()
    print(f"[trace] TracerProvider installed -> {TRACE_DB_PATH}\n")
    if "--no-gemini" in sys.argv:
        return await run_local_only(exporter)
    return await run_via_marrow(exporter)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
