"""Central configuration for PHAGE.

Region policy (decided in Phase 1; evidence lives in the probe scripts):

    Gemini 3.x models are served ONLY from the Vertex AI *global* endpoint.
    Measured on this project, us-central1:

        gemini-3.5-flash @ us-central1  ->  404 NOT_FOUND
        gemini-3.5-flash @ global       ->  200 OK
        gemini-2.5-flash @ us-central1  ->  200 OK   (pre-3.x is regional)

    So PHAGE splits location by concern:

        MODEL_LOCATION = "global"       -> all Gemini / embedding *inference*
        INFRA_LOCATION = "us-central1"  -> Cloud Run, Firestore, Agent Engine,
                                           Memory Bank, Model Armor, Registry

    The spec pins us-central1 for widest feature coverage and server-side
    timing; that governs where services and data live. Model inference is a
    stateless call that goes through Google's recommended global entry point
    for the newest Gemini models. The two concerns are orthogonal: data
    residency and deployed services stay regional; only the model call fans
    out to global. Every client is constructed with an *explicit* location so
    this split can never be decided by an ambient env var.
"""

import os

# --- Identity -----------------------------------------------------------------
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "phage-dev")
PROJECT_NUMBER = os.environ.get("PHAGE_PROJECT_NUMBER", "680106551305")

# --- Locations (see module docstring) -----------------------------------------
INFRA_LOCATION = os.environ.get("PHAGE_INFRA_LOCATION", "us-central1")
MODEL_LOCATION = os.environ.get("PHAGE_MODEL_LOCATION", "global")

# --- Models (all Google; the extra three earn the multi-model bonus) ----------
# Gemini 3.5 Flash: VACCINATOR payload authoring, SENTINEL escalation tier,
# MARROW routing. Flash (not Pro) for sub-second demo responses.
GEMINI_MODEL = os.environ.get("PHAGE_GEMINI_MODEL", "gemini-3.5-flash")

# text-embedding-005: ARCHIVIST semantic recognition (cosine similarity). Regional.
EMBEDDING_MODEL = os.environ.get("PHAGE_EMBEDDING_MODEL", "text-embedding-005")

# Gemma: SENTINEL cheap first-pass triage tier. Provisional id — the exact
# Vertex model string is resolved empirically when SENTINEL is built (Phase 2),
# same discipline as the Gemini id above.
GEMMA_MODEL = os.environ.get("PHAGE_GEMMA_MODEL", "gemma-3-27b-it")

# --- Agent Engine (MARROW orchestrator + Memory Bank) -------------------------
AGENT_ENGINE_ID = os.environ.get("PHAGE_AGENT_ENGINE_ID", "1868793184486686720")
AGENT_ENGINE_RESOURCE = (
    f"projects/{PROJECT_NUMBER}/locations/{INFRA_LOCATION}"
    f"/reasoningEngines/{AGENT_ENGINE_ID}"
)


def gemini_client_kwargs() -> dict:
    """kwargs for ``google.genai.Client(...)`` / ADK ``Gemini(client_kwargs=...)``.

    Pins Gemini inference to the Vertex *global* endpoint explicitly, so model
    calls never depend on an ambient GOOGLE_CLOUD_LOCATION that infra clients
    also read.
    """
    return {"vertexai": True, "project": PROJECT_ID, "location": MODEL_LOCATION}
