#!/usr/bin/env python3
"""Prove the VACCINATOR ADK-agent wrapper end to end: state in -> engine -> state out.

Mirrors the runner/session pattern already proven in scripts/run_local.py
(InMemoryRunner + async create_session + run_async with a throwaway new_message),
applied to a custom BaseAgent instead of an LlmAgent.

Two modes, matching vaccinate_demo.py's --no-gemini convention:

    uv run python scripts/run_vaccinator_agent.py
        Full agent path: InMemoryRunner(VACCINATOR()) -> seeded session state ->
        one run -> read state["vaccinator.payloads"] back. Gemini enabled (the
        agent's calling convention is fixed to generate_payloads(tool_scope)
        with default args — see adk_agent.py). Asserts the per-archetype
        provenance mix.

    uv run python scripts/run_vaccinator_agent.py --no-gemini
        Engine's local-only path, called directly with use_gemini=False —
        bypasses the ADK agent/runner entirely. This is the "seed a scope and
        assert the local path" offline-guarantee check: zero network, every
        applicable archetype still produces a payload.
"""

import asyncio
import sys

from google.adk.runners import InMemoryRunner
from google.genai import types

from phage.vaccinator.adk_agent import (
    STATE_PAYLOADS,
    STATE_TARGET_ID,
    STATE_TOOL_SCOPE,
    VACCINATOR,
)
from phage.vaccinator.engine import generate_payloads

APP = "phage-vaccinator"

# Real SAIL sink target (has an external-sink tool: send_email) — pulled from
# the fleet definition in scripts/vaccinate_demo.py, not hand-typed.
TARGET_ID = "SUPPLIER-RELAY"
TOOL_SCOPE = ["send_email(to, subject, body)", "read_contacts(name)"]


def _print_provenance(entries: list[tuple[str, str]]) -> None:
    for archetype_id, source in entries:
        print(f"    [{source:14}] {archetype_id}")


def _provenance_mix_problems(entries: list[tuple[str, str]]) -> list[str]:
    """Same provenance-mix assertion as scripts/vaccinate_demo.py: on a sink
    target, data-exfiltration must be local-fallback while at least one
    non-exfil archetype is gemini-tailored (per-archetype isolation proof).
    """
    problems = []
    by_id = dict(entries)
    if "data-exfiltration" in by_id and by_id["data-exfiltration"] != "local-fallback":
        problems.append("data-exfiltration should be local-fallback on a sink target")
    if not any(src == "gemini" for aid, src in entries if aid != "data-exfiltration"):
        problems.append("expected at least one non-exfil archetype tailored by gemini")
    return problems


async def run_local_only() -> int:
    """Engine local-only path, direct call — zero network. Proves the offline
    guarantee the agent's fallback depends on."""
    print(f"[local-only] target={TARGET_ID}  tool_scope={TOOL_SCOPE}\n")
    payloads = generate_payloads(TOOL_SCOPE, use_gemini=False)
    entries = [(p.archetype_id, p.source) for p in payloads]
    _print_provenance(entries)

    problems = []
    if not payloads:
        problems.append("no payloads generated")
    if any(src != "local-fallback" for _, src in entries):
        problems.append("expected ALL payloads to be local-fallback with use_gemini=False")

    print()
    if problems:
        print("SELF-CHECK: FAIL")
        for pr in problems:
            print("  -", pr)
        return 1
    print(f"SELF-CHECK: PASS — {len(payloads)} payloads, all local-fallback, zero network.")
    return 0


async def run_via_agent() -> int:
    """Full ADK wrapper path: seed session state -> VACCINATOR -> read state back."""
    print(f"[agent]      target={TARGET_ID}  tool_scope={TOOL_SCOPE}\n")

    runner = InMemoryRunner(agent=VACCINATOR(), app_name=APP)
    session = await runner.session_service.create_session(
        app_name=APP,
        user_id="dev",
        state={STATE_TOOL_SCOPE: TOOL_SCOPE, STATE_TARGET_ID: TARGET_ID},
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
    payloads_raw = (final_session.state if final_session else {}).get(STATE_PAYLOADS)

    print()
    if not payloads_raw:
        print("SELF-CHECK: FAIL")
        print(f"  - session.state[{STATE_PAYLOADS!r}] missing or empty after the run")
        return 1

    print(f"  {len(payloads_raw)} payloads in session.state[{STATE_PAYLOADS!r}]:")
    entries = [(d["archetype_id"], d["source"]) for d in payloads_raw]
    _print_provenance(entries)

    problems = _provenance_mix_problems(entries)

    print()
    if problems:
        print("SELF-CHECK: FAIL")
        for pr in problems:
            print("  -", pr)
        return 1
    print(
        "SELF-CHECK: PASS — state-in/state-out contract works; "
        "per-archetype provenance mix confirmed."
    )
    return 0


async def main() -> int:
    if "--no-gemini" in sys.argv:
        return await run_local_only()
    return await run_via_agent()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
