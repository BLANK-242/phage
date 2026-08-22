#!/usr/bin/env python3
"""Runs the two-pass ARCHIVIST recognition scene end to end. This is BOTH
the rehearsal tool (docs/PHAGE_cc_prompt_demo_script.md Task 2) and the
actual script the operator runs live on 2026-08-26 (docs/demo_script.md).

Pass 1: generate a real payload via VACCINATOR's engine (one target, one
        archetype, real _tailor_one() adaptation) -> fire it at the real
        target agent -> triage via SENTINEL -> contain via MACROPHAGE if
        landed -> record the signature via ARCHIVIST if landed.
Pass 2: recognize() the SAME payload's real paraphrase — the "same intent,
        different wording" mutation _tailor_one() already produced
        alongside the fired injection_text (PHAGE_build_prompt.md:181).

Tries an ORDERED list of (target, archetype) candidates, stopping at the
first one that actually lands (SENTINEL returns verdict=landed) — decision
4 of docs/PHAGE_cc_prompt_demo_script.md: the target/archetype is picked by
which rehearsal run lands cleanest, not pre-committed. data-exfiltration is
tried first: run_marrow.py's own module comments already document it as
the empirically reliable choice (a concrete destination + source->sink
instruction gives the target enough to construct a real tool call, unlike
e.g. instruction-override's bare "call {action}", confirmed there to
produce 0 execute_tool spans).
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
# Same requirement as run_marrow.py: agents.* is a repo-root sibling of
# src/, not part of the installed phage package.

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.adk.telemetry.sqlite_span_exporter import SqliteSpanExporter  # noqa: E402
from google.genai import types  # noqa: E402
from opentelemetry import context as otel_context_api  # noqa: E402
from opentelemetry import trace  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402

from phage.archivist.memory import RECOGNITION_DISTANCE_THRESHOLD, record, recognize  # noqa: E402
from phage.macrophage.containment import contain  # noqa: E402
from phage.sentinel.triage import triage_firing  # noqa: E402
from phage.targets import FLEET  # noqa: E402
from phage.vaccinator.engine import MutationRefused, generate_payloads  # noqa: E402

APP = "phage-demo-scene"
TRACE_DB_PATH = os.path.join(REPO_ROOT, "phage_traces.db")

# Ordered candidates: (target_id, archetype_id). data-exfiltration first —
# see module docstring. Only targets with a SINK_EXTERNAL tool support it
# (SUPPLIER-RELAY, QUOTE-BOT). SUPPLIER-RELAY repeated (candidates 1 and 5):
# real rehearsal evidence shows it produces genuine execute_tool evidence
# (2 real spans, well-formed args) — a prior "ambiguous" outcome there was a
# triage-parsing artifact (Gemini's escalation reply "VERDICT: LAND" didn't
# contain the exact substring "LANDED"), not the attack failing to work, so
# it is worth a second, independent attempt (temperature=0.7 throughout
# means a retry is not the same draw) before moving on.
_CANDIDATES = [
    ("SUPPLIER-RELAY", "data-exfiltration"),
    ("QUOTE-BOT", "data-exfiltration"),
    ("ORDER-INTAKE", "tool-coercion"),
    ("STOCK-KEEPER", "tool-coercion"),
    ("SUPPLIER-RELAY", "data-exfiltration"),
    ("QUOTE-BOT", "data-exfiltration"),
]


def install_tracer_provider() -> SqliteSpanExporter:
    exporter = SqliteSpanExporter(db_path=TRACE_DB_PATH)
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return exporter


def _target_agents() -> dict:
    from agents.order_intake.agent import root_agent as order_intake_agent
    from agents.quote_bot.agent import root_agent as quote_bot_agent
    from agents.stock_keeper.agent import root_agent as stock_keeper_agent
    from agents.supplier_relay.agent import root_agent as supplier_relay_agent

    return {
        "ORDER-INTAKE": order_intake_agent,
        "SUPPLIER-RELAY": supplier_relay_agent,
        "STOCK-KEEPER": stock_keeper_agent,
        "QUOTE-BOT": quote_bot_agent,
    }


async def run_pass1(target_id: str, archetype_id: str, exporter: SqliteSpanExporter, agent) -> dict:
    target = next(t for t in FLEET if t.id == target_id)
    print(f"=== PASS 1 — target={target_id} archetype={archetype_id} ===")

    payloads = generate_payloads(target.tool_scope, target_id=target_id)
    payload = next((p for p in payloads if p.archetype_id == archetype_id), None)
    if payload is None:
        print(f"  {archetype_id} not applicable to {target_id} (not in this target's selected archetypes)")
        return {"landed": False}

    print(f"  source={payload.source}")
    print(f"  injection_text: {payload.injection_text}")
    print(f"  paraphrase:     {payload.paraphrase}")

    if not payload.paraphrase:
        print("  NO PARAPHRASE on this payload — cannot run pass 2 with this candidate")
        return {"landed": False, "payload": payload, "no_paraphrase": True}

    session_id = f"demo-{target_id}-{archetype_id}"
    otel_token = otel_context_api.attach(otel_context_api.Context())
    fire_runner = InMemoryRunner(agent=agent, app_name=APP)
    try:
        await fire_runner.session_service.create_session(app_name=APP, user_id="fire", session_id=session_id)
        message = types.Content(role="user", parts=[types.Part(text=payload.injection_text)])
        async for _event in fire_runner.run_async(user_id="fire", session_id=session_id, new_message=message):
            pass
    finally:
        otel_context_api.detach(otel_token)

    spans = exporter.get_all_spans_for_session(session_id)
    tool_spans = [s for s in spans if s.name.startswith("execute_tool")]
    print(f"  {len(spans)} spans total, {len(tool_spans)} execute_tool spans")
    for s in tool_spans:
        args = s.attributes.get("gcp.vertex.agent.tool_call_args", "<none>")
        print(f"    span: {s.name}  args={args}")

    payload_dict = {"archetype_id": payload.archetype_id, "target_tools": list(payload.target_tools)}
    result = triage_firing(target_id=target_id, payload=payload_dict, session_id=session_id, spans=tool_spans)
    print(f"  SENTINEL: tier={result.tier.value} verdict={result.verdict.value}")
    print(f"  reasoning: {result.reasoning}")

    landed = result.verdict.value == "landed"
    record_name = None
    if landed:
        contain_result = contain(
            target_id=target_id,
            verdict=result.verdict.value,
            supporting_spans=result.supporting_spans,
            target_tools=agent.tools,
        )
        print(f"  MACROPHAGE: tools_revoked={contain_result.tools_revoked}")
        print(f"  MACROPHAGE reasoning: {contain_result.reasoning}")
        record_name = record(
            target_id=target_id,
            archetype_id=archetype_id,
            target_tools=list(payload.target_tools),
            injection_text=payload.injection_text,
            verdict=result.verdict.value,
        )
        print(f"  ARCHIVIST record() -> {record_name}")

    return {"landed": landed, "payload": payload, "record_name": record_name, "verdict": result.verdict.value}


def run_pass2(target_id: str, archetype_id: str, payload) -> float:
    """Returns the ISOLATED recognize() latency in seconds.

    Timed around the recognize() call alone, not the whole pass: the pass
    also prints the paraphrase and the matched fact, and on the demo take
    the number the narration claims must be the one recognition actually
    costs. Returned so the TIMING line can report it beside the full
    pass-2 wall time rather than letting the two be conflated.
    """
    print("\n=== PASS 2 — mutated payload (real paraphrase), recognition ===")
    print(f"  query (paraphrase): {payload.paraphrase}")
    recognize_start = time.monotonic()
    result = recognize(
        target_id=target_id,
        archetype_id=archetype_id,
        target_tools=list(payload.target_tools),
        injection_text=payload.paraphrase,
    )
    recognize_elapsed = time.monotonic() - recognize_start
    banner = "RECOGNIZED" if result.recognized else "MISS"
    print(f"  distance={result.distance:.4f}  threshold={RECOGNITION_DISTANCE_THRESHOLD}  -> {banner}")
    print(f"  recognize() latency: {recognize_elapsed * 1000:.0f} ms")
    if result.error:
        print(f"  error: {result.error}")
    print(f"  matched_fact: {result.matched_fact}")
    return recognize_elapsed


async def main() -> int:
    exporter = install_tracer_provider()
    print(f"[trace] TracerProvider installed -> {TRACE_DB_PATH}\n")
    agents = _target_agents()

    # Direct mode: `run_demo_scene.py TARGET_ID ARCHETYPE_ID` skips the
    # candidate search entirely and goes straight at the chosen pair — this
    # is what the actual 2026-08-26 take runs, once decision 4 is resolved;
    # re-searching candidates live on camera is not the plan. No argv ->
    # falls back to the candidate search (for future rehearsals if the
    # chosen pair ever stops landing reliably).
    if len(sys.argv) >= 3:
        candidates = [(sys.argv[1], sys.argv[2])]
    else:
        candidates = _CANDIDATES

    start = time.monotonic()
    for target_id, archetype_id in candidates:
        agent = agents[target_id]
        try:
            outcome = await run_pass1(target_id, archetype_id, exporter, agent)
        except MutationRefused as exc:
            # This is exactly the checklist's named failure mode (measured
            # 3.8% refusal rate) — during the REAL take it voids the take
            # (re-run, don't salvage). Here, in the CANDIDATE SEARCH, it
            # just rules out this one candidate; the script keeps looking
            # rather than crashing, so one refused draw doesn't cost the
            # whole rehearsal pass.
            print(f"  MutationRefused: {exc}")
            print(f"--- {target_id}/{archetype_id} refused mutation, trying next candidate ---\n")
            continue
        pass1_done = time.monotonic()
        print()
        if outcome.get("landed"):
            recognize_elapsed = run_pass2(target_id, archetype_id, outcome["payload"])
            pass2_done = time.monotonic()
            print(f"\nCHOSEN CANDIDATE: target={target_id} archetype={archetype_id}")
            print(
                f"TIMING: pass1={pass1_done - start:.1f}s  pass2={pass2_done - pass1_done:.1f}s  "
                f"(recognize() alone={recognize_elapsed * 1000:.0f} ms)  "
                f"total={pass2_done - start:.1f}s"
            )
            return 0
        print(f"--- {target_id}/{archetype_id} did not land, trying next candidate ---\n")

    print("NO CANDIDATE LANDED — none of the tried (target, archetype) pairs produced a landed verdict")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
