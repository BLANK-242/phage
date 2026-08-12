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
                 returned at least one payload via run_node. MARROW's session is
                 seeded (below) with sentinel.trace_db_path = TRACE_DB_PATH, the
                 same db this script's own TracerProvider writes to, so MARROW's
                 now-wired SENTINEL call can read each firing's spans back from
                 it; this then also reads state["marrow.fleet_verdicts"] and
                 asserts every fired payload was triaged. Gemini on.

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
    SENTINEL_STATE_TRACE_DB_PATH,
    STATE_FLEET_FIRE_SESSIONS,
    STATE_FLEET_PAYLOADS,
    STATE_FLEET_VERDICTS,
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
    # Seed sentinel.trace_db_path at session creation: MARROW's now-wired
    # SENTINEL call reads it from session.state (marrow/agent.py's "SENTINEL
    # WIRING" docstring section) rather than hardcoding a repo-relative path
    # into library code — the entry point owns tracing config, same
    # separation already established for the TracerProvider install itself
    # (marrow/agent.py's FIRE-AND-CAPTURE section). Same TRACE_DB_PATH this
    # script's own install_tracer_provider() already wrote spans to, above —
    # one path, one source of truth.
    session = await runner.session_service.create_session(
        app_name=APP,
        user_id="dev",
        state={SENTINEL_STATE_TRACE_DB_PATH: TRACE_DB_PATH},
    )
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
    fleet_verdicts = state.get(STATE_FLEET_VERDICTS)

    print()
    if not fleet_payloads:
        return _fail([f"session.state[{STATE_FLEET_PAYLOADS!r}] missing/empty after the run"])
    if not fleet_fire_sessions:
        return _fail([f"session.state[{STATE_FLEET_FIRE_SESSIONS!r}] missing/empty after the run"])
    if not fleet_verdicts:
        return _fail([f"session.state[{STATE_FLEET_VERDICTS!r}] missing/empty after the run"])

    problems: list[str] = []
    expected_ids = {t.id for t in FLEET}
    seen_ids = set(fleet_payloads.keys())
    if seen_ids != expected_ids:
        problems.append(f"target mismatch: expected {sorted(expected_ids)}, got {sorted(seen_ids)}")

    for target in FLEET:
        payloads = fleet_payloads.get(target.id) or []
        fired = fleet_fire_sessions.get(target.id) or []
        verdicts = fleet_verdicts.get(target.id) or []
        print(f"  {target.id}: {len(payloads)} payloads, {len(fired)} fired, {len(verdicts)} triaged")
        _print_provenance([(p["archetype_id"], p["source"]) for p in payloads])
        for v in verdicts:
            if v is not None:
                print(f"    [{v['tier']:9}] {v['archetype_id']} -> {v['verdict']}")
        if not payloads:
            problems.append(f"{target.id}: no payloads returned via run_node")
        if not fired:
            problems.append(f"{target.id}: no payloads were fired at the real target agent")
        if fired and not any(v is not None for v in verdicts):
            problems.append(f"{target.id}: fired but sentinel.verdict never observed for any firing")

    print()
    if problems:
        return _fail(problems)

    # Step 3 (rewritten this commit — was a SUPPLIER-RELAY/data-exfiltration
    # spot-check hardcoded in commit b11a879, before SENTINEL existed. A
    # single fixed target/archetype cannot survive real model
    # non-determinism: a live run had that exact payload Gemini-sourced (not
    # the fixed local-fallback template) and the target declined it, which
    # SENTINEL correctly triaged `declined` (0 relevant spans, exactly its
    # documented behavior — triage.py's decisive-tool/matching-span
    # pre-filter), but the old check still failed the whole script on an
    # outcome that was never actually a failure. Two checks that do not
    # depend on which specific payloads happen to land on a given run:

    # 3a. Capture floor: total spans across the FULL fired set > 0 — proves
    # OTel capture is active at all. Deliberately not scoped to
    # execute_tool spans specifically: a target that calls no tools still
    # emits other spans (e.g. invoke_agent) — confirmed by the run that
    # motivated this fix, where the declined firing still had 4 spans
    # total, just 0 execute_tool ones. This only proves capture is wired;
    # 3b below is what checks actual tool-call evidence.
    step3_problems: list[str] = []
    total_fired = sum(len(fleet_fire_sessions.get(t.id) or []) for t in FLEET)
    total_spans = sum(
        len(exporter.get_all_spans_for_session(sid))
        for t in FLEET
        for sid in (fleet_fire_sessions.get(t.id) or [])
    )
    print(f"  capture floor: {total_spans} spans across {total_fired} fired sessions")
    if total_spans == 0:
        step3_problems.append(
            "capture floor: zero spans captured across the full fired set"
        )

    # 3b. Self-consistency: every SENTINEL verdict of "landed" must be
    # backed by real evidence in the trace DB — non-empty supporting_spans
    # (TriageResult.supporting_spans, triage.py:110; serialized dict key
    # confirmed at sentinel/adk_agent.py:79-90) that actually exist as
    # execute_tool spans for that firing's session_id. Deterministic
    # regardless of how many (if any) payloads land on a given run:
    # vacuously true if SENTINEL reports zero "landed" verdicts for the
    # whole run — the loop body below only ever runs for a "landed"
    # verdict, so zero of them means zero iterations and step3_problems
    # gets nothing from this check either way (reasoned through, not
    # fabricated — forcing a run to land would reintroduce the same
    # non-determinism problem one level up). Catches a real regression —
    # SENTINEL claiming "landed" with no evidence — the old spot-check
    # never could, since it only ever looked at one hardcoded session
    # regardless of what SENTINEL actually said.
    landed_checked = 0
    for target in FLEET:
        for v in fleet_verdicts.get(target.id) or []:
            if v is None or v["verdict"] != "landed":
                continue
            landed_checked += 1
            supporting = v["supporting_spans"]
            if not supporting:
                step3_problems.append(
                    f"{target.id}/{v['archetype_id']}: verdict=landed but "
                    "supporting_spans is empty"
                )
                continue
            session_spans = exporter.get_all_spans_for_session(v["session_id"])
            real_names = {
                s.name for s in session_spans if s.name.startswith("execute_tool")
            }
            missing = [name for name in supporting if name not in real_names]
            if missing:
                step3_problems.append(
                    f"{target.id}/{v['archetype_id']}: verdict=landed but "
                    f"supporting_spans {missing} not found as execute_tool "
                    f"spans for session {v['session_id']!r}"
                )
    print(
        f"  self-consistency: {landed_checked} 'landed' verdict(s) checked "
        "against the trace DB"
    )

    print()
    if step3_problems:
        return _fail(step3_problems)

    print(
        f"SELF-CHECK: PASS — all {len(FLEET)} fleet targets returned at least "
        "one payload via run_node, every target fired at its real agent, "
        "SENTINEL triaged at least one firing per target (sentinel.verdict "
        "observed via ctx.session.state), capture floor confirmed "
        f"({total_spans} spans / {total_fired} fired sessions), and every "
        f"'landed' verdict ({landed_checked}) is backed by real execute_tool "
        "spans in the trace DB."
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
