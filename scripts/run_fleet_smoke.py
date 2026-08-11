#!/usr/bin/env python3
"""Fleet smoke test — proves the four SAIL target agents are real and callable.

For each of the four Phase 2a target agents (agents/order_intake,
agents/supplier_relay, agents/stock_keeper, agents/quote_bot): construct it,
run ONE benign message through InMemoryRunner crafted to trigger its primary
(read-side) tool, and assert that tool was actually called — via ADK's own
Event.get_function_calls() (models/llm_response.py:169-176, inherited by
Event), not a side-channel tracking hack. This proves the fleet is real and
callable. It does not test anything adversarial — that's the next commit.

Mirrors the runner/session pattern already proven in scripts/run_local.py.

Usage:
    uv run python scripts/run_fleet_smoke.py
"""

import asyncio
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from agents.order_intake.agent import root_agent as order_intake_agent  # noqa: E402
from agents.quote_bot.agent import root_agent as quote_bot_agent  # noqa: E402
from agents.stock_keeper.agent import root_agent as stock_keeper_agent  # noqa: E402
from agents.supplier_relay.agent import root_agent as supplier_relay_agent  # noqa: E402

APP = "phage-fleet-smoke"

# One benign message per target, each crafted to trigger exactly its primary
# (read-side) tool without requiring a multi-tool chain — so a single clean
# function call proves the agent is real and wired correctly.
CASES = [
    (
        "ORDER-INTAKE",
        order_intake_agent,
        "Hi, it's Amina — my email is amina@example.com. Can you check if "
        "you have my customer record on file?",
        "lookup_customer",
    ),
    (
        "SUPPLIER-RELAY",
        supplier_relay_agent,
        "What's the contact info you have on file for our supplier, Atlas Textiles?",
        "read_contacts",
    ),
    (
        "STOCK-KEEPER",
        stock_keeper_agent,
        "How many units of SKU TOTE-001 do we currently have in stock?",
        "read_inventory",
    ),
    (
        "QUOTE-BOT",
        quote_bot_agent,
        "What's the price for SKU TOTE-001?",
        "read_pricing",
    ),
]


async def run_one(target_id: str, agent, message_text: str, expected_tool: str) -> bool:
    runner = InMemoryRunner(agent=agent, app_name=APP)
    session = await runner.session_service.create_session(app_name=APP, user_id="dev")
    message = types.Content(role="user", parts=[types.Part(text=message_text)])

    called_tools: list[str] = []
    final_text = ""
    async for event in runner.run_async(
        user_id="dev", session_id=session.id, new_message=message
    ):
        for fc in event.get_function_calls():
            called_tools.append(fc.name)
        if event.is_final_response() and event.content and event.content.parts:
            final_text = "".join(part.text or "" for part in event.content.parts)

    fired = expected_tool in called_tools
    status = "PASS" if fired else "FAIL"
    print(f"[{status}] {target_id:16} expected={expected_tool:16} called={called_tools}")
    if final_text:
        print(f"         reply: {final_text.strip()[:160]}")
    return fired


async def main() -> int:
    print(f"Fleet smoke test — {len(CASES)} targets\n")
    results = []
    for target_id, agent, message_text, expected_tool in CASES:
        ok = await run_one(target_id, agent, message_text, expected_tool)
        results.append((target_id, ok))
        print()

    problems = [tid for tid, ok in results if not ok]
    if problems:
        print("SELF-CHECK: FAIL")
        for tid in problems:
            print(f"  - {tid}: expected tool did not fire")
        return 1
    print(f"SELF-CHECK: PASS — all {len(results)} target agents are real and callable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
