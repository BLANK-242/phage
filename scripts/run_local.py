#!/usr/bin/env python3
"""Run the HELLO agent locally for one turn and print its reply (Phase 1, step 6).

Non-interactive on purpose: proves ADK -> Gemini 3.5 Flash -> response without
the `adk run` interactive prompt, so it can be scripted and re-run.

Usage:
    uv run python scripts/run_local.py ["your prompt"]
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
# Load the agent's non-secret config so env overrides work when run directly
# (ADK's CLI loads this automatically; a bare python invocation does not).
load_dotenv(os.path.join(REPO_ROOT, "agents", "hello", ".env"))

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from agents.hello.agent import root_agent  # noqa: E402

APP = "phage-hello"


async def main(prompt: str) -> int:
    runner = InMemoryRunner(agent=root_agent, app_name=APP)
    session = await runner.session_service.create_session(app_name=APP, user_id="dev")
    message = types.Content(role="user", parts=[types.Part(text=prompt)])

    reply = ""
    async for event in runner.run_async(
        user_id="dev", session_id=session.id, new_message=message
    ):
        if event.is_final_response() and event.content and event.content.parts:
            reply = "".join(part.text or "" for part in event.content.parts)

    print(reply.strip())
    return 0 if reply.strip() else 1


if __name__ == "__main__":
    user_prompt = sys.argv[1] if len(sys.argv) > 1 else "Confirm PHAGE Phase 1 connectivity."
    raise SystemExit(asyncio.run(main(user_prompt)))
