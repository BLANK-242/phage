"""HELLO — PHAGE Phase 1 connectivity probe.

Deliberately minimal and self-contained (no PHAGE domain logic). Its only job is
to prove the pipe end to end: ADK -> Gemini 3.5 Flash (Vertex *global* endpoint)
-> response, both locally and on Cloud Run.

Self-contained on purpose: `adk deploy cloud_run` ships only this folder into the
container, so the agent must not import the wider `phage` package. The region
split hard-coded here (model calls -> global) is documented centrally for the
real agents in src/phage/config.py.
"""

import os

from google.adk.agents import Agent
from google.adk.models import Gemini

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "phage-dev")
MODEL_ID = os.environ.get("PHAGE_GEMINI_MODEL", "gemini-3.5-flash")
MODEL_LOCATION = os.environ.get("PHAGE_MODEL_LOCATION", "global")

root_agent = Agent(
    name="hello",
    model=Gemini(
        model=MODEL_ID,
        # Pin inference to the Vertex *global* endpoint. Gemini 3.x is not served
        # from regional us-central1 (verified in Phase 1: 404 regional, 200 global).
        client_kwargs={
            "vertexai": True,
            "project": PROJECT_ID,
            "location": MODEL_LOCATION,
        },
    ),
    description="PHAGE Phase-1 connectivity probe.",
    instruction=(
        "You are HELLO, a minimal connectivity probe for PHAGE, an immune system "
        "for AI agent fleets. You are deployed on Google's "
        f"{MODEL_ID} via Vertex AI. Answer in one or two plain sentences. If "
        "asked to confirm connectivity, state that PHAGE Phase 1 is live and "
        f"that you are running on {MODEL_ID}. Do not guess a different model "
        "name — report exactly the model named here."
    ),
)
