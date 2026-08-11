#!/usr/bin/env python3
"""Prove the SENTINEL ADK-agent wrapper end to end: state in -> triage.py -> state out.

Mirrors scripts/run_vaccinator_agent.py's shape (InMemoryRunner around the
wrapper, seed session state, run, read state back) applied to SENTINEL
instead of VACCINATOR.

Fire-and-capture cycle to produce the one real firing to triage uses the same
approach scripts/run_sentinel_selfcheck.py already proved: local-fallback
payload generation (fast, zero network for generation), direct
agent-to-agent InMemoryRunner firing against the real target agent, with the
same otel_context_api.attach(Context())/detach isolation fix marrow/agent.py
uses (without it, get_all_spans_for_session bleeds across firings sharing one
process's ambient trace context).

Uses data-exfiltration fired at SUPPLIER-RELAY (the proven LANDED-via-Gemma
case from run_sentinel_selfcheck.py) as the one real firing, so the
comparison actually exercises the Gemma bridge, not just the fully
deterministic zero-spans path.

Compares the wrapper's verdict against a DIRECT triage_firing() call on the
exact same captured spans. Asserts exact equality on the fields that are
deterministic given the same spans (verdict, tier, target_id, archetype_id,
session_id, supporting_spans) -- proving the bridge doesn't lose or distort
anything. `reasoning` is printed for both but not strictly byte-compared: it
embeds the raw model reply text from two INDEPENDENT live Gemma calls
(temperature=0.0, so highly but not perfectly guaranteed to be textually
identical) -- a verdict/tier/supporting_spans mismatch would mean the bridge
is broken; a reasoning-text wording difference would not.

Usage:
    uv run python scripts/run_sentinel_agent.py
"""

import asyncio
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
# Needed to import the real target agent directly, same reason
# marrow/agent.py/run_marrow.py/run_sentinel_selfcheck.py need it: agents/ is
# a repo-root sibling of src/, not part of the installed phage package.

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.adk.telemetry.sqlite_span_exporter import SqliteSpanExporter  # noqa: E402
from google.genai import types  # noqa: E402
from opentelemetry import context as otel_context_api  # noqa: E402
from opentelemetry import trace  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402

from agents.supplier_relay.agent import root_agent as supplier_relay_agent  # noqa: E402
from phage.sentinel.adk_agent import (  # noqa: E402
    SENTINEL,
    STATE_PAYLOAD,
    STATE_SESSION_ID,
    STATE_TARGET_ID,
    STATE_TRACE_DB_PATH,
    STATE_VERDICT,
)
from phage.sentinel.triage import triage_firing  # noqa: E402
from phage.vaccinator.engine import generate_payloads  # noqa: E402

APP = "phage-sentinel-agent"
TARGET_ID = "SUPPLIER-RELAY"
TOOL_SCOPE = ["send_email(to, subject, body)", "read_contacts(name)"]
ARCHETYPE_ID = "data-exfiltration"
TRACE_DB_PATH = os.path.join(REPO_ROOT, "phage_traces_sentinel_agent.db")


def install_tracer_provider() -> SqliteSpanExporter:
    if os.path.exists(TRACE_DB_PATH):
        os.remove(TRACE_DB_PATH)
    exporter = SqliteSpanExporter(db_path=TRACE_DB_PATH)
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return exporter


async def fire(injection_text: str, session_id: str) -> None:
    """Fire one payload at SUPPLIER-RELAY in its own isolated OTel trace
    context (same fix as marrow/agent.py / run_sentinel_selfcheck.py)."""
    runner = InMemoryRunner(agent=supplier_relay_agent, app_name=APP)
    token = otel_context_api.attach(otel_context_api.Context())
    try:
        await runner.session_service.create_session(
            app_name=APP, user_id="fire", session_id=session_id
        )
        message = types.Content(role="user", parts=[types.Part(text=injection_text)])
        async for _event in runner.run_async(
            user_id="fire", session_id=session_id, new_message=message
        ):
            pass
    finally:
        otel_context_api.detach(token)


def _fail(problems: list[str]) -> int:
    print("SELF-CHECK: FAIL")
    for p in problems:
        print("  -", p)
    return 1


async def main() -> int:
    print(f"[sentinel-agent] target={TARGET_ID}  archetype={ARCHETYPE_ID}")
    exporter = install_tracer_provider()
    print(f"[trace] TracerProvider installed -> {TRACE_DB_PATH}\n")

    payloads = generate_payloads(TOOL_SCOPE, use_gemini=False)
    by_archetype = {p.archetype_id: p for p in payloads}
    if ARCHETYPE_ID not in by_archetype:
        return _fail([f"expected archetype {ARCHETYPE_ID!r} not generated"])
    payload = by_archetype[ARCHETYPE_ID]
    payload_dict = {
        "archetype_id": payload.archetype_id,
        "category": payload.category,
        "intent": payload.intent,
        "target_tools": list(payload.target_tools),
        "injection_text": payload.injection_text,
        "paraphrase": payload.paraphrase,
        "source": payload.source,
    }

    session_id = f"agentcheck-{TARGET_ID}-{ARCHETYPE_ID}"
    print(f"[fire] {ARCHETYPE_ID} -> session {session_id!r}")
    await fire(payload.injection_text, session_id)

    all_spans = exporter.get_all_spans_for_session(session_id)
    tool_spans = [s for s in all_spans if s.name.startswith("execute_tool")]
    print(f"  {len(all_spans)} spans total, {len(tool_spans)} execute_tool spans\n")

    # --- direct triage.py call -------------------------------------------------
    print("--- direct triage_firing() call ---")
    direct = triage_firing(
        target_id=TARGET_ID, payload=payload_dict, session_id=session_id, spans=tool_spans
    )
    print(f"  verdict:    {direct.verdict.value}  (tier={direct.tier.value})")
    print(f"  reasoning:  {direct.reasoning}")
    print(f"  supporting: {direct.supporting_spans}\n")

    # --- via the ADK wrapper ----------------------------------------------------
    print("--- via SENTINEL ADK wrapper (InMemoryRunner) ---")
    runner = InMemoryRunner(agent=SENTINEL(), app_name=APP)
    session = await runner.session_service.create_session(
        app_name=APP,
        user_id="dev",
        state={
            STATE_TARGET_ID: TARGET_ID,
            STATE_PAYLOAD: payload_dict,
            STATE_SESSION_ID: session_id,
            STATE_TRACE_DB_PATH: TRACE_DB_PATH,
        },
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
    wrapper_raw = (final_session.state if final_session else {}).get(STATE_VERDICT)
    print()

    if not wrapper_raw:
        return _fail([f"session.state[{STATE_VERDICT!r}] missing/empty after the run"])

    print(f"  verdict:    {wrapper_raw['verdict']}  (tier={wrapper_raw['tier']})")
    print(f"  reasoning:  {wrapper_raw['reasoning']}")
    print(f"  supporting: {tuple(wrapper_raw['supporting_spans'])}\n")

    # --- compare ------------------------------------------------------------
    problems: list[str] = []
    if wrapper_raw["target_id"] != direct.target_id:
        problems.append(f"target_id: wrapper={wrapper_raw['target_id']!r} direct={direct.target_id!r}")
    if wrapper_raw["archetype_id"] != direct.archetype_id:
        problems.append(f"archetype_id: wrapper={wrapper_raw['archetype_id']!r} direct={direct.archetype_id!r}")
    if wrapper_raw["session_id"] != direct.session_id:
        problems.append(f"session_id: wrapper={wrapper_raw['session_id']!r} direct={direct.session_id!r}")
    if wrapper_raw["verdict"] != direct.verdict.value:
        problems.append(f"verdict: wrapper={wrapper_raw['verdict']!r} direct={direct.verdict.value!r}")
    if wrapper_raw["tier"] != direct.tier.value:
        problems.append(f"tier: wrapper={wrapper_raw['tier']!r} direct={direct.tier.value!r}")
    if tuple(wrapper_raw["supporting_spans"]) != direct.supporting_spans:
        problems.append(
            f"supporting_spans: wrapper={wrapper_raw['supporting_spans']!r} "
            f"direct={list(direct.supporting_spans)!r}"
        )

    if problems:
        return _fail(problems)
    print(
        "SELF-CHECK: PASS — wrapper's verdict matches a direct triage_firing() "
        "call exactly (verdict, tier, target_id, archetype_id, session_id, "
        "supporting_spans all identical); the bridge loses/distorts nothing."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
