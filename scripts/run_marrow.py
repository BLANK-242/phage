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
                 zero network, a payload per applicable archetype, all
                 local-fallback, for the whole fleet.
"""

import asyncio
import sys

from google.adk.runners import InMemoryRunner
from google.genai import types

from phage.marrow.agent import MARROW, STATE_FLEET_PAYLOADS
from phage.targets import FLEET
from phage.vaccinator.engine import generate_payloads

APP = "phage-marrow"


def _print_provenance(entries: list[tuple[str, str]]) -> None:
    for archetype_id, source in entries:
        print(f"    [{source:14}] {archetype_id}")


def _fail(problems: list[str]) -> int:
    print("SELF-CHECK: FAIL")
    for pr in problems:
        print("  -", pr)
    return 1


async def run_local_only() -> int:
    """Engine local-only path, direct call per FLEET target — zero network."""
    problems: list[str] = []
    for target in FLEET:
        print(f"[local-only] target={target.id}  tool_scope={target.tool_scope}")
        payloads = generate_payloads(target.tool_scope, use_gemini=False)
        entries = [(p.archetype_id, p.source) for p in payloads]
        _print_provenance(entries)
        print()

        if not payloads:
            problems.append(f"{target.id}: no payloads generated")
        if any(src != "local-fallback" for _, src in entries):
            problems.append(f"{target.id}: expected ALL payloads local-fallback with use_gemini=False")

    if problems:
        return _fail(problems)
    print(
        f"SELF-CHECK: PASS — all {len(FLEET)} targets produced local-fallback "
        "payloads, zero network."
    )
    return 0


async def run_via_marrow() -> int:
    """Full ADK wrapper path: MARROW loops FLEET, seeding state + run_node -> VACCINATOR per target."""
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
    fleet_payloads = (final_session.state if final_session else {}).get(STATE_FLEET_PAYLOADS)

    print()
    if not fleet_payloads:
        return _fail([f"session.state[{STATE_FLEET_PAYLOADS!r}] missing/empty after the run"])

    problems: list[str] = []
    expected_ids = {t.id for t in FLEET}
    seen_ids = set(fleet_payloads.keys())
    if seen_ids != expected_ids:
        problems.append(f"target mismatch: expected {sorted(expected_ids)}, got {sorted(seen_ids)}")

    for target in FLEET:
        payloads = fleet_payloads.get(target.id) or []
        print(f"  {target.id}: {len(payloads)} payloads")
        _print_provenance([(p["archetype_id"], p["source"]) for p in payloads])
        if not payloads:
            problems.append(f"{target.id}: no payloads returned via run_node")

    print()
    if problems:
        return _fail(problems)
    print(
        f"SELF-CHECK: PASS — all {len(FLEET)} fleet targets returned at least "
        "one payload via run_node."
    )
    return 0


async def main() -> int:
    if "--no-gemini" in sys.argv:
        return await run_local_only()
    return await run_via_marrow()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
