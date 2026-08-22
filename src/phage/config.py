"""Central configuration for PHAGE.

Region policy (decided in Phase 1; evidence lives in the probe scripts):

    Gemini 3.x models are served ONLY from the Vertex AI *global* endpoint.
    Measured on this project, us-central1:

        gemini-3.5-flash @ us-central1  ->  404 NOT_FOUND
        gemini-3.5-flash @ global       ->  200 OK
        gemini-2.5-flash @ us-central1  ->  200 OK   (pre-3.x is regional)

    So PHAGE splits location by concern:

        MODEL_LOCATION = "global"       -> all Gemini / Gemma *inference*
        INFRA_LOCATION = "us-central1"  -> Cloud Run, Firestore, Agent Engine,
                                           Memory Bank, Model Armor, Registry

    No embedding location appears in that split: PHAGE never calls an embedding
    model. Memory Bank embeds server-side from the signature text, and its API
    has no caller-supplied-vector path, so there is no embedding inference for
    this module to route.

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

# --- Models (all Google) ------------------------------------------------------
# Gemini 3.5 Flash: VACCINATOR payload authoring, SENTINEL escalation tier,
# MARROW routing. Flash (not Pro) for sub-second demo responses.
GEMINI_MODEL = os.environ.get("PHAGE_GEMINI_MODEL", "gemini-3.5-flash")

# No embedding model is configured here, deliberately. Memory Bank embeds
# server-side from the plain signature TEXT; its API exposes no
# caller-supplied-vector path, so PHAGE never computes or supplies a vector.
# A constant naming an embedding model would imply a capability this project
# does not have.

# Gemma: SENTINEL cheap first-pass triage tier. Resolved empirically when
# SENTINEL was built, same discipline as the Gemini id above: "gemma-3-27b-it"
# 404s at both us-central1 and global on this project (Publisher model not
# found). "gemma-4-26b-a4b-it-maas" is the verified-working id, global only —
# confirmed via a direct generate_content call, same routing pattern as
# Gemini 3.x.
GEMMA_MODEL = os.environ.get("PHAGE_GEMMA_MODEL", "gemma-4-26b-a4b-it-maas")

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
