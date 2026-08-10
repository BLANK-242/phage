# PHAGE — an immune system for AI agent fleets

PHAGE continuously **inoculates** the AI agents an organization deploys with
tailored prompt-injection and tool-poisoning payloads, **quarantines** the ones
that fail, and **remembers** every attack signature so a repeat attack is
neutralized on recognition rather than re-analysis. It is built for an
organization deploying agents with **no security staff**.

The biological metaphor is the architecture, not decoration — every platform
primitive maps to an immune function.

> Google Cloud **All Things Agentic Hackathon** — *Fortified Enterprise Fleet*.
> Built entirely within the submission window with AI assistance (permitted).

---

## The five agents

| Agent | Immune role | What it does |
|---|---|---|
| **MARROW** | Bone marrow / metabolism | Root orchestrator on Agent Engine Runtime. Schedules vaccination cycles, routes findings. Holds no domain logic. |
| **VACCINATOR** | Vaccine synthesis | Reads the Agent Registry, inspects each target's **declared tool scopes**, and uses Gemini to author injection payloads **tailored to those specific tools**. Not a static payload list — this is the core innovation. |
| **SENTINEL** | Sensory nerves | Reads Agent Observability traces to see what the target actually did. **Gemma** does cheap first-pass triage; only ambiguous cases escalate to Gemini. |
| **MACROPHAGE** | Containment | Revokes Agent Identity, cuts Agent Gateway routes, quarantines, rolls back Memory Bank writes. |
| **ARCHIVIST** | Immunological memory | Writes encounter signatures to Memory Bank and serves recognition lookups. Recognition is **semantic** (cosine similarity over `text-embedding-005` vectors), not exact-match — so the *second, mutated* attack fails instantly. |

**Component mapping:** Model Armor = innate barrier · Agent Registry = the
body / self · Agent Identity = self/non-self recognition · Agent Gateway =
circulation · Agent Observability = sensory nerves · Memory Bank =
immunological memory · Agent Runtime = background metabolism.

**The cycle:** VACCINATOR generates a tailored payload → fires it through the
Gateway → Model Armor blocks at the barrier or lets it through → SENTINEL reads
the target's traces → if compromised, MACROPHAGE contains → ARCHIVIST records the
signature. On second exposure, ARCHIVIST recognition fires **before** the payload
lands.

---

## Stack

- **Python 3.12**, dependencies via **uv** (pinned in `pyproject.toml` + `uv.lock`)
- **Google ADK** (`google-adk`) — native agent framework, no LangChain/CrewAI wrappers
- **Gemini 3.5 Flash** via Vertex AI — VACCINATOR authoring, SENTINEL escalation, MARROW routing
- **Gemma** (SENTINEL triage), **`text-embedding-005`** (ARCHIVIST recognition), **Chirp TTS** (demo) — three extra Google models, each architecturally justified
- Agent Engine Runtime, Memory Bank, Agent Registry, Agent Identity, Agent Gateway, Model Armor, Agent Observability (OpenTelemetry)
- Cloud Run, Firestore (Native mode), FastAPI + vanilla JS dashboard (no build step)

### Region policy — model calls vs. infrastructure

Gemini 3.x models are served **only from the Vertex AI `global` endpoint**, not
from regional `us-central1` (measured on this project — see `src/phage/config.py`
and the probe scripts). PHAGE therefore splits location by concern:

| Concern | Location | Why |
|---|---|---|
| Model **inference** (Gemini, embeddings) | `global` | Only endpoint that serves Gemini 3.x; Google's recommended entry point for the newest models |
| **Infrastructure & data** (Cloud Run, Firestore, Agent Engine, Memory Bank, Model Armor, Registry) | `us-central1` | Widest feature coverage; data residency and deployed services stay pinned; timing is measured server-side |

Data residency and deployed services stay regional; only the stateless model call
fans out to global. Every client is constructed with an **explicit** location, so
this split is never left to an ambient environment variable.

---

## Two questions a judge will ask (pre-answered)

**Why both Firestore and Memory Bank?** Different consumers, different access
patterns. **Firestore** holds *operational* state that PHAGE's own control plane
reads and writes — findings, quarantine records, fleet health. **Memory Bank**
holds *agent-facing semantic memory* that the agents themselves query — the
encounter signatures ARCHIVIST recognizes. One is infrastructure state; the other
is the immune system's memory.

**Isn't a payload generator dual-use?** It is scoped **exclusively** to consented
agents in our **own** Agent Registry, inside our own Google Cloud project. There
is **no external targeting** and **no payload export path** — payloads are
generated, fired at our own agents through our own Gateway, and retained only as
defensive signatures. It finds weaknesses in a fleet before an attacker does.

---

## Reproducible spin-up

Prerequisites: `uv`, the `gcloud` CLI, a Google Cloud project on a full billing
account (not Vertex AI Express Mode), and ADC (`gcloud auth application-default
login`).

```bash
git clone <repo> && cd phage
scripts/bootstrap.sh                 # uv sync + gcloud config + enable APIs + IAM

# Local smoke test (Phase 1, step 6): ADK -> Gemini 3.5 Flash -> response
uv run python scripts/run_local.py "Confirm PHAGE Phase 1 connectivity."

# Deploy the same agent to Cloud Run (Phase 1, step 7) — private/authenticated
uv run adk deploy cloud_run --project=phage-dev --region=us-central1 \
  --service_name=phage-hello --app_name=hello agents/hello \
  -- --no-allow-unauthenticated

# Verify the private service over HTTP (authenticated via a local proxy)
gcloud run services proxy phage-hello --region us-central1 --port 8080 &
curl -s http://127.0.0.1:8080/list-apps            # -> ["hello"]
```

**Auth & secrets:** authentication is via Application Default Credentials locally
and the Cloud Run service account in production. No service-account key files are
committed (`*.json` and `.env` are gitignored); agent config carries safe
defaults, so nothing breaks without a local `.env`. Source-based Cloud Run
deploys additionally need the Compute Engine default service account to hold
`roles/cloudbuild.builds.builder` (build) and `roles/aiplatform.user` (runtime
Gemini access); `bootstrap.sh` grants both, since new orgs withhold the automatic
Editor grant from default service accounts.

---

## Status

| Phase | State |
|---|---|
| 0 — Foundations (billing, project, Agent Engine instance, APIs, region) | ✅ complete |
| 1 — Prove the pipe (ADK → Gemini local + Cloud Run, billing alert) | ✅ complete |
| 1.5 — Payload viability gate (Gemini generates tailored injections?) | ⏳ next |
| 2 — Target fleet (Coopérative SAIL workers) + interface shims | ⏳ |
| 3 — ARCHIVIST semantic recognition | ⏳ |

**Phase 1 live service (private):** `https://phage-hello-680106551305.us-central1.run.app`

---

## Repository layout

```
agents/
  hello/            # Phase 1 connectivity probe (self-contained ADK agent)
src/phage/
  config.py         # single source of truth: identity, region policy, models
scripts/
  bootstrap.sh      # reproducible spin-up
  run_local.py      # non-interactive local runner (Phase 1 step 6)
  probe_payload_gen.py   # Phase 1.5 payload-viability probe (+ committed output)
docs/               # architecture diagram, demo script (generated in-repo)
```
