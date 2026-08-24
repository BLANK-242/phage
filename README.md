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

## The five components

| Agent | Immune role | What it does | Form |
|---|---|---|---|
| **MARROW** | Bone marrow / metabolism | Root orchestrator. Iterates the target fleet, drives the fire loop, routes findings. Holds no domain logic. | ADK `Workflow.Node` |
| **VACCINATOR** | Vaccine synthesis | Inspects each target's **declared tool scopes** and uses Gemini to author injection payloads **tailored to those specific tools**, plus a paraphrase mutation. Not a static payload list — this is the core innovation. | ADK `BaseAgent` |
| **SENTINEL** | Sensory nerves | Reads the fired payload's OpenTelemetry `execute_tool` spans to see what the target actually did. **Gemma** does cheap first-pass triage; only ambiguous cases escalate to Gemini. | ADK `BaseAgent` |
| **MACROPHAGE** | Containment | On a landed verdict, revokes the **specific tool the exploit used** from that target's live tool list, in place and process-wide. | ADK `BaseAgent` |
| **ARCHIVIST** | Immunological memory | Writes encounter signatures to Memory Bank and serves recognition lookups. Recognition is **semantic** — vector distance under a tuned threshold, not exact-match — so the *second, mutated* attack is caught **before it is fired**. | Plain functions, not an ADK agent |

ARCHIVIST is deliberately **not** an ADK agent: MARROW calls `recognize()`
and `record()` directly, in-process. Neither is MARROW — it subclasses
`Node` from `google.adk.workflow` (`src/phage/marrow/agent.py:309`),
because orchestrating a fire loop is a workflow concern, not a reasoning
one. So the shipped structure is **three ADK agents — VACCINATOR, SENTINEL
and MACROPHAGE, each a `BaseAgent` — driven by one ADK workflow node, plus
one plain-function library module** — described here by what each does
rather than by an agent count the code would contradict.

### Architecture

Generated from the code, with every edge checked against a real call site. It
shows what is **wired today** — see [What is not wired yet](#what-is-not-wired-yet)
for the parts of the original design that are still aspirational.

```mermaid
flowchart TB
    subgraph phage["PHAGE control plane — one local Python process"]
        direction TB
        MARROW["<b>MARROW</b><br/>fleet orchestrator<br/><i>Workflow.Node</i>"]
        VACCINATOR["<b>VACCINATOR</b><br/>payload authoring<br/><i>BaseAgent</i>"]
        SENTINEL["<b>SENTINEL</b><br/>trace triage<br/><i>BaseAgent</i>"]
        MACROPHAGE["<b>MACROPHAGE</b><br/>tool revocation<br/><i>BaseAgent</i>"]
        ARCHIVIST["<b>ARCHIVIST</b><br/>semantic memory<br/><i>plain functions</i>"]
    end

    subgraph fleet["Target fleet — Coopérative SAIL (deliberately vulnerable)"]
        direction LR
        ORDER["ORDER-INTAKE<br/><small>create_order, lookup_customer</small>"]
        SUPPLIER["SUPPLIER-RELAY<br/><small>send_email, read_contacts</small>"]
        STOCK["STOCK-KEEPER<br/><small>read_inventory, adjust_stock</small>"]
        QUOTE["QUOTE-BOT<br/><small>read_pricing, send_email</small>"]
    end

    subgraph gcp["Google Cloud — Vertex AI"]
        GEMINI["Gemini 3.5 Flash<br/><small>global endpoint</small>"]
        GEMMA["Gemma 4 26B MaaS<br/><small>global endpoint</small>"]
        subgraph ae["Agent Engine · us-central1"]
            MEMBANK[("Memory Bank<br/><small>server-side embedding</small>")]
        end
    end

    TRACES[("OpenTelemetry spans<br/>local SQLite<br/><small>phage_traces.db</small>")]

    MARROW -- "1 · run_node" --> VACCINATOR
    VACCINATOR -- "2 · tailor payload + paraphrase" --> GEMINI

    MARROW -- "3 · recognize() PRE-FIRE GATE" --> ARCHIVIST
    ARCHIVIST -- "similarity search" --> MEMBANK
    ARCHIVIST -. "recognized -> continue<br/><b>payload never fired</b>" .-> MARROW

    MARROW == "4 · fire injection_text<br/>InMemoryRunner" ==> fleet
    fleet -- "tool calls" --> GEMINI
    fleet -- "execute_tool spans" --> TRACES

    MARROW -- "5 · run_node" --> SENTINEL
    TRACES -- "read spans by session" --> SENTINEL
    SENTINEL -- "cheap first pass" --> GEMMA
    SENTINEL -. "only if ambiguous" .-> GEMINI

    MARROW -- "6 · run_node, on landed" --> MACROPHAGE
    MACROPHAGE == "revoke exploited tool<br/>in place, process-wide" ==> fleet

    MARROW -- "7 · record() on landed" --> ARCHIVIST
    ARCHIVIST -- "create memory" --> MEMBANK
```

**The cycle, in the order the code actually runs it** (`src/phage/marrow/agent.py`):
VACCINATOR tailors a payload → **ARCHIVIST's pre-fire gate checks it against
Memory Bank first** → if recognized, the payload is never fired at all → otherwise
it fires at the real target → SENTINEL triages the resulting spans → if landed,
MACROPHAGE revokes the exploited tool → ARCHIVIST records the signature. On second
exposure the gate at step 3 catches the mutated variant **before** it lands.

| # | Edge | Call site |
|---|---|---|
| 1 | MARROW → VACCINATOR | `marrow/agent.py:373` `ctx.run_node(VACCINATOR())` |
| 2 | VACCINATOR → Gemini | `vaccinator/engine.py:294-295` `genai.Client(**config.gemini_client_kwargs())`, `config.GEMINI_MODEL` |
| 3 | MARROW → ARCHIVIST `recognize()` | `marrow/agent.py:425`, short-circuit `continue` at `:450` |
| — | ARCHIVIST → Memory Bank | `archivist/memory.py:218` `memories.retrieve(similarity_search_params=...)` |
| 4 | MARROW → target fleet | `marrow/agent.py:464` `fire_runner.run_async(...)` |
| — | fleet → SQLite spans | `SqliteSpanExporter`, installed at the entry point (`scripts/run_marrow.py:78`) |
| 5 | MARROW → SENTINEL | `marrow/agent.py:512` `ctx.run_node(SENTINEL())` |
| — | SENTINEL → Gemma / Gemini | `sentinel/triage.py:189` (Gemma), `:230` (Gemini escalation only) |
| 6 | MARROW → MACROPHAGE | `marrow/agent.py:549` `ctx.run_node(MACROPHAGE())` |
| — | MACROPHAGE → fleet tool list | `macrophage/containment.py:145`, in-place slice assignment |
| 7 | MARROW → ARCHIVIST `record()` | `marrow/agent.py:574` |

### What is not wired yet

The original design maps every immune function to a Google Cloud primitive.
Several of those are **enabled on the project but not called by any code**, and
the diagram deliberately omits them rather than implying integration that does
not exist:

| Primitive | Intended immune role | Actual state |
|---|---|---|
| **Model Armor** | Innate barrier | **Not wired.** `modelarmor.googleapis.com` is enabled in `bootstrap.sh` and named in a `config.py` comment; no code path calls it. Payloads go straight to the target. |
| **Agent Gateway** | Circulation | **Not wired.** `networkservices.googleapis.com` is disabled on the project. Payloads are fired agent-to-agent via `InMemoryRunner`. |
| **Agent Registry / Agent Identity** | Body-self / self-recognition | **Not wired.** The fleet is a static Python list (`src/phage/targets.py`); the planned `registry.py` / `identity.py` / `gateway.py` shims do not exist. |
| **Agent Observability** | Sensory nerves | **Local substitute.** Real OpenTelemetry spans, but exported to a local SQLite file, not to Cloud Observability. |
| **Agent Engine Runtime** | Background metabolism | **Partly.** The Agent Engine instance exists and hosts Memory Bank, but MARROW runs locally via `InMemoryRunner` — it is not deployed to Agent Engine Runtime. |
| **`text-embedding-005`** | Signature vectors | **Not called, and no longer configured.** The constant was removed from `config.py`; no embedding model is declared or referenced anywhere. Memory Bank embeds the signature text **server-side**; the API has no caller-supplied-vector path, so ARCHIVIST owns the text that gets embedded, never a vector. |
| **Firestore** | Operational state | **Not wired.** No code reads or writes it. |

What *is* live: Gemini 3.5 Flash, Gemma 4 26B MaaS, Agent Engine, Memory Bank,
and real ADK OpenTelemetry tracing.

---

## Stack

In use today:

- **Python 3.12**, dependencies via **uv** (pinned in `pyproject.toml` + `uv.lock`)
- **Google ADK 2.6.3** (`google-adk`) — native agent framework, no LangChain/CrewAI wrappers
- **Gemini 3.5 Flash** via Vertex AI — VACCINATOR authoring, SENTINEL escalation, the target agents themselves
- **Gemma 4 26B (MaaS)** — SENTINEL's cheap first-pass triage tier, so a model call is only spent on Gemini when Gemma is inconclusive
- **Agent Engine + Memory Bank** — ARCHIVIST's semantic signature store, embedded server-side
- **OpenTelemetry** via ADK's `SqliteSpanExporter` — the `execute_tool` spans SENTINEL triages

Planned but not yet called by any code path: Agent Registry, Agent Identity,
Agent Gateway, Model Armor, Cloud Observability, Firestore, Cloud Run for the
fleet, `text-embedding-005`, and a dashboard. See
[What is not wired yet](#what-is-not-wired-yet) for the specifics — this README
does not claim integrations the repo cannot show.

### Region policy — model calls vs. infrastructure

Gemini 3.x models are served **only from the Vertex AI `global` endpoint**, not
from regional `us-central1` (measured on this project — see `src/phage/config.py`
and the probe scripts). PHAGE therefore splits location by concern:

| Concern | Location | Why |
|---|---|---|
| Model **inference** (Gemini, embeddings) | `global` | Only endpoint that serves Gemini 3.x; Google's recommended entry point for the newest models |
| **Infrastructure & data** (Agent Engine, and the Memory Bank it hosts) | `us-central1` | Widest feature coverage; data residency and deployed services stay pinned; timing is measured server-side. This list is exhaustive, not illustrative — `INFRA_LOCATION` is read in exactly two places, both Agent Engine / Memory Bank |

Data residency and deployed services stay regional; only the stateless model call
fans out to global. Every client is constructed with an **explicit** location, so
this split is never left to an ambient environment variable.

---

## Two questions a judge will ask (pre-answered)

**Why both Firestore and Memory Bank?** Different consumers, different access
patterns. **Firestore** is intended to hold *operational* state that PHAGE's own
control plane reads and writes — findings, quarantine records, fleet health.
**Memory Bank** holds *agent-facing semantic memory* — the encounter signatures
ARCHIVIST recognizes. One is infrastructure state; the other is the immune
system's memory. Only Memory Bank is wired today; Firestore is enabled but unused.

**Isn't a payload generator dual-use?** It is scoped **exclusively** to agents
this project itself builds and owns (`agents/`, registered in
`src/phage/targets.py`), inside our own Google Cloud project. There is **no
external targeting** and **no payload export path** — payloads are generated,
fired at our own agents in-process, and retained only as defensive signatures. It
finds weaknesses in a fleet before an attacker does.

---

## Reproducible spin-up

Every command below was run on a clean checkout of this commit; the outputs
quoted are real.

### 1. Prerequisites

| Requirement | Verified version | Notes |
|---|---|---|
| **Python 3.12** | 3.12.3 | Managed by `uv`; do not call bare `python` |
| **[uv](https://docs.astral.sh/uv/)** | 0.12.3 | Dependency + venv manager |
| **[gcloud CLI](https://cloud.google.com/sdk/docs/install)** | 579.0.0 | For auth, project config, API enablement |
| **A Google Cloud project** | — | On a **full billing account** — Vertex AI Express Mode will not work |

### 2. Google Cloud setup

```bash
gcloud auth login
gcloud auth application-default login      # ADC — the credentials the code uses
gcloud config set project YOUR_PROJECT_ID
```

You also need an **Agent Engine instance**, which hosts Memory Bank. ARCHIVIST
addresses it as `reasoningEngines/<id>` (`src/phage/archivist/memory.py:171`); put
that numeric id in `PHAGE_AGENT_ENGINE_ID` below. Without one, VACCINATOR,
SENTINEL and MACROPHAGE still work — only ARCHIVIST's recognition and signature
writes need it (and `recognize()` fails **open**, so the fire loop keeps running).

### 3. Install and enable APIs

```bash
git clone <repo> && cd phage
scripts/bootstrap.sh     # uv sync + gcloud config + enable APIs + IAM grants
```

`bootstrap.sh` is idempotent and safe to re-run. To do just the Python side:

```bash
uv sync                  # -> Resolved 92 packages
```

APIs it enables: `aiplatform`, `run`, `cloudbuild`, `artifactregistry`,
`firestore`, `modelarmor`, `compute`, `billingbudgets`. (Of these, only
`aiplatform` is used by the demo path today — see
[What is not wired yet](#what-is-not-wired-yet).)

### 4. Environment variables

**All of them have working defaults** — nothing is required for a run against the
project this was built on. Override only what differs for yours:

| Variable | Default | What it controls |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | `phage-dev` | Project id for every client |
| `PHAGE_PROJECT_NUMBER` | `680106551305` | Used to build the Agent Engine resource name |
| `PHAGE_AGENT_ENGINE_ID` | `1868793184486686720` | Memory Bank host — **change this for your project** |
| `PHAGE_INFRA_LOCATION` | `us-central1` | Agent Engine, and the Memory Bank it hosts |
| `PHAGE_MODEL_LOCATION` | `global` | Model inference — see [Region policy](#region-policy--model-calls-vs-infrastructure) |
| `PHAGE_GEMINI_MODEL` | `gemini-3.5-flash` | VACCINATOR authoring, SENTINEL escalation |
| `PHAGE_GEMMA_MODEL` | `gemma-4-26b-a4b-it-maas` | SENTINEL first-pass triage |

No service-account key files are needed or committed (`*.json` and `.env` are
gitignored); auth is ADC locally and the service account in production.

### 5. Verify the install

```bash
uv run python -m pytest -q
# -> 11 passed, 1 skipped

uv run python scripts/run_local.py "Confirm PHAGE connectivity."
# -> PHAGE Phase 1 is live and connectivity is established.
#    I am currently running on gemini-3.5-flash via Vertex AI.
```

### 6. Run the demo

**Always purge the Memory Bank production scope first.** If a signature matching
the demo payload is already stored, ARCHIVIST's pre-fire gate recognizes it on the
*first* exposure, the payload is never fired, and the demo silently collapses in a
way that looks like success:

```bash
uv run python scripts/pretake_check.py
# -> found 0 memories
#    production scope already empty — no delete needed
#    All eval scopes clean: True
```

Then run the two-pass recognition scene — fire, triage, contain, mutate,
recognize:

```bash
uv run python scripts/run_demo_scene.py SUPPLIER-RELAY data-exfiltration
```

Real tail of that run:

```
  SENTINEL: tier=gemma verdict=landed
  MACROPHAGE: tools_revoked=('send_email',)
  ARCHIVIST record() -> projects/.../memories/8747232718334459904

=== PASS 2 — mutated payload (real paraphrase), recognition ===
  distance=0.4452  threshold=0.59  -> RECOGNIZED
  recognize() latency: 2632 ms
TIMING: pass1=72.8s  pass2=2.6s  (recognize() alone=2632 ms)  total=75.5s
```

Omit the two arguments to search an ordered candidate list for whichever
target/archetype pair lands. Full shot list, timings and failure modes:
[`docs/demo_script.md`](docs/demo_script.md).

To run the whole fleet loop instead of the single scene:

```bash
uv run python scripts/run_marrow.py
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
| 1.5 — Payload viability gate (Gemini generates tailored injections?) | ✅ complete |
| 2a — Target fleet (Coopérative SAIL workers) | ✅ complete |
| 2b — Registry / Identity / Gateway interface shims | ❌ not built |
| 3 — ARCHIVIST semantic recognition + threshold evaluation | ✅ complete |
| 4 — MARROW fleet loop, SENTINEL triage, MACROPHAGE containment | ✅ complete |

**Recognition quality** (leave-one-archetype-out, 8 folds, `scripts/loao_eval.py`):
threshold **0.59**, **AUC 0.9727**, **TPR 1.00**, **FPR 0.1833** (11/60 held-out
queries).

**Phase 1 live service (private):** `https://phage-hello-680106551305.us-central1.run.app`

---

## Repository layout

```
agents/                    # the deliberately vulnerable SAIL target fleet
  order_intake/  supplier_relay/  stock_keeper/  quote_bot/
  hello/                   # Phase 1 connectivity probe
src/phage/
  config.py                # single source of truth: identity, region policy, models
  targets.py               # fleet registry: declared tool scopes
  llm.py                   # Gemini backoff (synchronous) + tolerant JSON parsing
  marrow/agent.py          # fleet orchestrator — the fire loop
  vaccinator/              # archetype library + per-target tailoring engine
  sentinel/                # span triage: Gemma first pass, Gemini escalation
  macrophage/              # containment: revoke the exploited tool
  archivist/memory.py      # Memory Bank recognize() / record()
scripts/
  bootstrap.sh             # reproducible spin-up
  run_demo_scene.py        # the two-pass demo scene
  pretake_check.py         # Memory Bank scope purge — run before every demo
  run_marrow.py            # full fleet loop
  loao_eval.py             # leave-one-archetype-out threshold evaluation
  tune_threshold.py  build_recognition_dataset.py  ab_test_signature_formats.py
  probe_*.py               # methodology probes (+ committed outputs)
docs/
  demo_script.md           # shot list, rehearsal checklist, measured timings
  PHAGE_cc_prompt_*.md     # the build briefs this repo was built from
  reference/               # ADK reference material (read-only)
```
