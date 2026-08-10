#!/usr/bin/env python3
"""End-to-end self-check for MARROW's run_node seam into VACCINATOR.

Mirrors scripts/run_vaccinator_agent.py. Two modes:

  (default)      Runs MARROW via InMemoryRunner. MARROW seeds the target's
                 tool_scope into session state and fans out into VACCINATOR via
                 ctx.run_node; we then read state["vaccinator.payloads"] back and
                 assert the per-archetype provenance mix — proving payloads came
                 back THROUGH the node seam, not by a direct engine call. Gemini on.

  --no-gemini    Offline guarantee: calls the engine directly with
                 use_gemini=False for the same target. VACCINATOR's engine call
                 is fixed to default args, so (as in run_vaccinator_agent.py) this
                 leg bypasses the agent to prove the deterministic path — zero
                 network, a payload per applicable archetype.
"""

import asyncio
import sys

from google.adk.runners import InMemoryRunner
from google.genai import types

from phage.marrow.agent import _DEMO_TARGET, MARROW
from phage.vaccinator.adk_agent import STATE_PAYLOADS
from phage.vaccinator.engine import generate_payloads

APP = "phage-marrow"
TARGET_ID = _DEMO_TARGET["target_id"]
TOOL_SCOPE = _DEMO_TARGET["tool_scope"]


def _print_provenance(entries: list[tuple[str, str]]) -> None:
    for archetype_id, source in entries:
        print(f"    [{source:14}] {archetype_id}")


def _fail(problems: list[str]) -> int:
    print("SELF-CHECK: FAIL")
    for pr in problems:
        print("  -", pr)
    return 1


def _provenance_mix_problems(entries: list[tuple[str, str]]) -> list[str]:
    """Same provenance-mix assertion as run_vaccinator_agent.py: on this sink
    target, data-exfiltration must be local-fallback while at least one non-exfil
    archetype is gemini-tailored — proof the per-archetype mix survived run_node.
    """
    problems: list[str] = []
    by_id = dict(entries)
    if by_id.get("data-exfiltration") != "local-fallback":
        problems.append("data-exfiltration should be local-fallback on a sink target")
    if not any(src == "gemini" for aid, src in entries if aid != "data-exfiltration"):
        problems.append("expected at least one non-exfil archetype tailored by gemini")
    return problems


async def run_local_only() -> int:
    print(f"[local-only] target={TARGET_ID}  tool_scope={TOOL_SCOPE}\n")
    payloads = generate_payloads(TOOL_SCOPE, use_gemini=False)
    entries = [(p.archetype_id, p.source) for p in payloads]
    _print_provenance(entries)

    problems: list[str] = []
    if not payloads:
        problems.append("no payloads generated")
    if any(src != "local-fallback" for _, src in entries):
        problems.append("expected ALL payloads local-fallback with use_gemini=False")

    print()
    if problems:
        return _fail(problems)
    print(f"SELF-CHECK: PASS — {len(payloads)} payloads, all local-fallback, zero network.")
    return 0


async def run_via_marrow() -> int:
    print(f"[marrow]     target={TARGET_ID}  (MARROW seeds state + run_node -> VACCINATOR)\n")

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

    final = await runner.session_service.get_session(
        app_name=APP, user_id="dev", session_id=session.id
    )
    payloads_raw = (final.state if final else {}).get(STATE_PAYLOADS)

    print()
    if not payloads_raw:
        return _fail([f"session.state[{STATE_PAYLOADS!r}] missing/empty after run_node"])

    print(f"  {len(payloads_raw)} payloads returned THROUGH run_node into session.state[{STATE_PAYLOADS!r}]:")
    entries = [(d["archetype_id"], d["source"]) for d in payloads_raw]
    _print_provenance(entries)

    problems = _provenance_mix_problems(entries)
    print()
    if problems:
        return _fail(problems)
    print("SELF-CHECK: PASS — payloads returned via run_node; per-archetype provenance mix intact.")
    return 0


async def main() -> int:
    if "--no-gemini" in sys.argv:
        return await run_local_only()
    return await run_via_marrow()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
