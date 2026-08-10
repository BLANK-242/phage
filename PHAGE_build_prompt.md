# PHAGE — Build Brief (v3)

I'm building a submission for Google Cloud's **All Things Agentic Hackathon** on Devpost, in the **Fortified Enterprise Fleet** category. Hard deadline: **2026-08-31, 17:00 PDT** (= 2026-09-01, 01:00 Africa/Casablanca). I treat 2026-08-30 as the last working day.

Everything below is already decided. Don't re-litigate it — build it.

**Start at Phase 1, step 4.** Phase 0 is verified complete and Phase 1 steps 1–3 and 5 are already done. Details in "Current state" below.

---

## What PHAGE is

An immune system for AI agent fleets, built for an organization deploying agents with no security staff.

PHAGE continuously inoculates registered agents with tailored prompt-injection and tool-poisoning payloads, quarantines the ones that fail, and stores every attack signature so a repeat attack is neutralized on recognition rather than re-analysis.

The metaphor is the architecture, not decoration. Every platform primitive maps to a biological function.

---

## Architecture (locked)

Five agents — one orchestrator, four specialists:

| Agent | Role |
|---|---|
| **MARROW** | Root orchestrator, deployed to Agent Engine Runtime. Schedules vaccination cycles, routes findings. Holds no domain logic. |
| **VACCINATOR** | Reads the Agent Registry, inspects a target's *declared tool scopes*, uses Gemini to generate injection payloads tailored to those specific tools. Not a static payload list — this is the core innovation. |
| **SENTINEL** | Consumes Agent Observability traces to see what the target actually did. Gemma does first-pass triage; only ambiguous cases escalate to Gemini. |
| **MACROPHAGE** | Containment — revokes Agent Identity, cuts Agent Gateway routes, quarantines, rolls back Memory Bank writes. |
| **ARCHIVIST** | Writes encounter signatures to Memory Bank, serves recognition lookups. Recognition is **semantic, not exact-match** — see Phase 3. This is what makes the second attack fail instantly. |

**Component mapping:** Model Armor = innate barrier · Agent Registry = the body/self · Agent Identity = self/non-self recognition · Agent Gateway = circulation · Agent Observability = sensory nerves · Memory Bank = immunological memory · Agent Runtime = background metabolism.

**The cycle:** VACCINATOR generates a tailored payload → fires through the Gateway → Model Armor blocks at the barrier or lets through → SENTINEL reads the target's traces → if compromised, MACROPHAGE contains → ARCHIVIST records the signature. On second exposure, ARCHIVIST recognition fires before the payload lands.

---

## Stack (locked)

- Python 3.12.3, dependencies via `uv`
- Google ADK — installed: `google-adk` 2.6.3, `google-cloud-aiplatform` 1.163.0, `google-genai` 2.17.0
- Gemini 3.5 Flash via Vertex AI (Flash, not Pro — the demo needs sub-second responses)
- Gemma via Vertex AI for SENTINEL's cheap triage tier
- `text-embedding-005` via Vertex AI for ARCHIVIST's semantic recognition
- Chirp TTS for demo narration (decide by 2026-08-17)
- Agent Engine Runtime, Memory Bank, Agent Registry, Agent Identity, Agent Gateway, Model Armor, Agent Observability (OpenTelemetry)
- Cloud Run, Firestore (Native mode), Docker
- FastAPI + vanilla JS for the dashboard — no framework, no build step

**Explicitly excluded:** LangChain, CrewAI (ADK is native and wrappers weaken the "used Google's framework" story), React, GKE, Postgres.

**Region: `us-central1` for everything.** Widest feature coverage; the ~130ms from Morocco is irrelevant because timing claims are measured server-side in logs.

---

## Current state — verified working, do not redo

### Machine
Ubuntu 24.04.4 LTS Desktop amd64, VMware Workstation on a Windows 11 host. Hostname `phage-dev`, user `blank`. 4 vCPU / 8 GB RAM / 60 GB disk. Timezone `Africa/Casablanca`, NTP synced. AZERTY keyboard. Respond in English.

Installed: gcloud 579.0.0 (tarball install, so `gcloud components install` works), uv 0.12.3, Node 22.23.2, git 2.43.0.
npm global prefix is `~/.npm-global` (not sudo) — PATH exported in `.bashrc`.

Project dir `~/projects/phage`, venv `.venv`, git on branch `main`, first commit `8ea02d4` dated Mon Aug 10 02:41:42 2026 +0100 — inside the submission window. `.gitignore` excludes `.venv/`, `__pycache__`, `*.json` (service account keys).

### Google Cloud
- Project ID `phage-dev` · project number `680106551305`
- Organization `benlekbirwalid3-org` (auto-provisioned — this cleared the biggest architectural risk)
- Billing: free trial, $300 credit valid to 2026-11-09, card cleared
- APIs enabled: aiplatform (now branded "Agent Platform API"), run, cloudbuild, artifactregistry, firestore, **modelarmor**, compute
- `compute/region`, `run/region`, `ai/region` all set to `us-central1`
- ADC written to `~/.config/gcloud/application_default_credentials.json`

### Agent Engine instance — MARROW and Memory Bank need this ID

```
1868793184486686720
projects/680106551305/locations/us-central1/reasoningEngines/1868793184486686720
```

Creating this instance successfully is what proved the project is not in Express Mode.

---

## Known traps — do not rediscover these

1. **`vertexai.Client` is deprecated** in favour of `agentplatform.Client` and emits a FutureWarning. Most docs and tutorials still show the old class. **Find the current import pattern before writing any MARROW code** — building on the deprecated API costs a refactor, and judges read the repo.
2. **Vertex AI Express Mode cannot deploy to Agent Engine Runtime.** Already ruled out — the project is on a full billing account. Never switch.
3. **PEP 668** — Ubuntu 24.04's Python 3.12 refuses system-wide pip installs. Always work inside the `uv venv`. Never use `--break-system-packages`.
4. **Firestore must be created in Native mode.** The mode is fixed at creation. Not yet created.
5. **Docker** — use Docker's official apt repo, not Ubuntu's stale `docker.io`. Add the user to the `docker` group. Not yet installed.
6. **Gemini quota** — VACCINATOR's loop will hit per-minute rate limits on a fresh project. Build exponential backoff from the first commit, not later.
7. **Screen recording on Wayland** needs the PipeWire portal. Verify capture works this week — the 4-minute demo video is a hard submission requirement and the classic deadline casualty.
8. **Terminal quirks** — multi-line pastes into gnome-terminal sometimes leak bracketed-paste escapes (`^[[200~`) or truncate. Run shell-replacing commands like `exec bash` alone. Sourcing `.bashrc` while the venv is active can drop `~/.npm-global/bin` from PATH; open a fresh shell rather than debugging it.
9. **Model Armor is deployed on the fleet PHAGE protects, not on VACCINATOR's own egress.** Don't let the barrier block the vaccine before it leaves the lab.

OpenTelemetry GCP logging and trace exporters already came in as ADK dependencies — SENTINEL's observability plumbing is present, don't re-add it.

---

## Hackathon constraints

- All work must be newly created during the submission period (started 2026-08-03). Only pre-existing code written before that date requires disclosure. AI assistance is explicitly permitted. I must be able to defend every architectural decision — winners are subject to identity and role verification.
- Mandatory: Gemini 3.5+, at least one Google agent framework, at least one Google Cloud infrastructure service. The build satisfies all three.
- Judging: 40% Innovation & Operational Utility, 30% Architectural Discipline & Tech Stack, 30% Demo & Production Readiness.
- Stage One is pass/fail on completeness: architecture diagram, video ≤4 min, repo access, visible Google Cloud proof in the video.
- Bonus: +0.2 blog post, +0.2 social post tagged #AllThingsAgenticHackathon, +0.2 per extra Google model up to +0.6 — **+1.0 on a 5-point base.** Gemma, `text-embedding-005`, and Chirp are the three extra models; all three are architecturally justified, none is bolted on.
- Deliverables: hosted project URL, ~4-min YouTube demo, public/shared repo with reproducible spin-up in README, architecture diagram, text write-up.

---

## Phase 0 — COMPLETE

| Check | Result |
|---|---|
| Billing card verifies on free trial | Pass — $300 credit to 2026-11-09 |
| Not in Express Mode, can create Agent Engine instance | Pass — instance `1868793184486686720` live |
| Agent Registry / Gateway / Identity scope | Organization `benlekbirwalid3-org` exists — no architecture change needed. Registry entries not yet created; verify behaviour in Phase 2. |
| Gemini 3.5 Flash, Agent Engine Runtime, Memory Bank, Model Armor in `us-central1` | Pass — all APIs enabled, region set |

---

## Phase 1 — prove the pipe

One goal, no PHAGE logic: deploy a hello-world ADK agent and get a response back.

- [x] 1. Install `uv`, create the venv, install ADK
- [x] 2. Install gcloud (tarball), `gcloud auth login`, `gcloud auth application-default login`
- [x] 3. Enable APIs: Vertex AI, Cloud Run, Cloud Build, Artifact Registry, Firestore, Model Armor
- [ ] 4. Set a billing alert at $100 of usage
- [x] 5. `git init` — clock verified, first commit inside the window
- [ ] 6. Minimal ADK agent calling Gemini 3.5 Flash, running locally
- [ ] 7. Same agent deployed to Cloud Run, returning a response over HTTP

**Start at step 4.** When step 7 returns a response, go straight to Phase 1.5 — do not start MARROW yet.

---

## Phase 1.5 — payload viability gate. Ten minutes. Do not skip.

The entire innovation claim rests on Gemini generating tailored injection payloads on demand. If safety filters refuse, the core doesn't exist and I need to know now, not on 2026-08-25.

1. Write `scripts/probe_payload_gen.py`: a single Gemini 3.5 Flash call with a system instruction framing the task as authorized red-team testing of consented agents in our own registry, given a fake tool scope (e.g. `send_email(to, subject, body)`, `read_inventory(sku)`).
2. Ask for three distinct injection payloads targeting those specific tools.
3. Report verbatim what comes back — full refusal, partial refusal, hedged output, or clean generation.

**If it refuses or hedges:** stop and tell me before writing more code. Fallback is a templated-mutation engine — a small library of injection archetypes that Gemini *rephrases and parameterizes* against the target's tool names rather than authoring from scratch. That keeps the "tailored, not static" claim intact with a much lower refusal surface. Don't implement the fallback without telling me first.

Commit the probe script and its output to the repo. It's evidence of methodology and it's the kind of thing judges reward in a security project.

---

## Phase 2 — the fleet, and the interfaces that survive platform surprises

### 2a. Target fleet (build this before VACCINATOR)
VACCINATOR has nothing to vaccinate without targets. Write 3–5 deliberately vulnerable worker agents with *genuinely different* tool scopes, so tailoring is visibly different per target rather than cosmetic.

Model them on **Coopérative SAIL** — a Moroccan artisanal cooperative making personalized eco-responsible promotional goods (NOT agricultural), where I handle strategy and comms. This is the Unlikely Hero framing, so it must be concrete on screen:

- `ORDER-INTAKE` — parses customer order emails, tools: `create_order`, `lookup_customer`
- `SUPPLIER-RELAY` — drafts and sends supplier emails, tools: `send_email`, `read_contacts`
- `STOCK-KEEPER` — inventory, tools: `read_inventory`, `adjust_stock`
- `QUOTE-BOT` — pricing quotes, tools: `read_pricing`, `send_email`

Register all of them in the Agent Registry with declared tool scopes. Their vulnerability is realistic naïveté — no adversarial hardening in the system prompt — not cartoonish compliance.

### 2b. Interface shims — do this before MACROPHAGE
Agent Registry, Gateway, and Identity are new surfaces and may not behave as documented. Define `registry.py`, `identity.py`, `gateway.py` as thin contracts with two implementations behind each: the real platform call and a local Firestore-backed shim. Select via env var.

If a primitive turns out half-baked on 2026-08-22, I swap the implementation and keep demoing instead of rewriting containment logic under deadline. The write-up gets a paragraph on this as a deliberate portability decision — which is an architecture point, not an apology.

---

## Phase 3 — ARCHIVIST: recognition must be semantic

Exact-match signature lookup reads as a cache to a judge and undercuts the immune metaphor. Real immune memory recognizes *variants*.

- Embed each encounter's payload with `text-embedding-005`; store the vector plus metadata in Memory Bank
- Recognition = cosine similarity above a tuned threshold, not string or hash equality
- The demo fires a **mutated** payload on the second pass — same intent, different wording — and ARCHIVIST still recognizes it
- Log the similarity score and surface it in the dashboard; the number on screen is what proves it isn't a hash table

Tune the threshold against a small labelled set of variant/non-variant pairs and commit that set. Report the false-positive rate in the write-up.

---

## Demo — script it before building the middle of the project

Demo & Production Readiness is 30%, and the shot list is the best prioritization tool available: **anything that doesn't appear on camera is optional.** Write `docs/demo_script.md` early — timestamped shot list, ≤4:00 total — and let it drive build order.

**Spine, two scenes:**
1. Fire a payload at a SAIL worker agent. First pass: slow detection, visible damage, containment. Second pass with a *mutated* payload: ARCHIVIST recognition fires in milliseconds, similarity score on screen.
2. Deliberately induce a worker agent to loop. MACROPHAGE quarantines it live. Judges explicitly ask how systems recover from looping or hallucinating workers, and almost nobody demonstrates it on camera.

Google Cloud console must be visibly on screen at some point — Stage One requirement.

---

## Write-up — pre-answer the two questions a judge will ask

- **Why both Firestore and Memory Bank?** Firestore holds operational state (findings, quarantine records, health). Memory Bank holds agent-facing semantic memory the agents themselves query. Different consumers, different access patterns. Put this in the README, not just in my head.
- **Isn't a payload generator dual-use?** One paragraph: scoped exclusively to consented agents in our own Agent Registry, no external targeting, no payload export path. Naming the concern and closing it scores better than hoping nobody asks.

---

## Schedule locks

| Date | Lock |
|---|---|
| 2026-08-11 | Verify Wayland/PipeWire screen capture works end to end |
| 2026-08-17 | Multimodal angle decided — Chirp narration, Veo incident replay, or visual attack-surface map. **Best Multimodal UX wants multimodality in the product, not the video.** |
| 2026-08-24 | Feature-add cutoff for anything not in the demo script |
| 2026-08-26 | Feature freeze — bugfix, polish, docs only |
| 2026-08-27 | Blog post and social post drafted (+0.4, highest return per hour in the project) |
| 2026-08-28 | Record and upload the demo video. YouTube processing delay is the classic casualty. |
| 2026-08-30 | Submit. Treat as the deadline. |
| 2026-09-03 | Hard cutoff to redeem the $150 credit code (submitted for Google review 2026-08-09) |

---

## Repo hygiene — these are graded artifacts

- **Architecture diagram generated in-repo** with the Python `diagrams` library, not drawn by hand in a web tool. Version-controlled, regenerates on change, reads as discipline in a category literally called Architectural Discipline. Export PNG to `docs/`.
- **`scripts/bootstrap.sh`** — single-command spin-up from a clean project. This is the "reproducible spin-up in README" requirement; write it incrementally as we go, not on 2026-08-29.
- **README updated as we go.** It's graded, not an afterthought.

---

## How to work

Explain what you're doing and why, briefly, before running anything that changes state. Ask before installing something not on the list above. When something fails, show me the actual error rather than paraphrasing it.
