# PHAGE — Claude Code brief: SAIL target fleet (Phase 2a)

> **Build-history record.** Written during construction and left unedited.
> Figures and `file:line` citations here may be superseded. `docs/writeup.md`
> and `README.md` are the current, audited statements.

Scope: **one commit.** Build the four target agents the spec always called for building before VACCINATOR — SUPPLIER-RELAY, QUOTE-BOT, ORDER-INTAKE, STOCK-KEEPER. This step was skipped when VACCINATOR jumped the queue for the Phase 1.5 payload-viability gate; it's due now, not new scope.

## Before you start

Confirm the MODEL LINE reads **Sonnet 5**.

## What confirms this, so nothing here is guessed

`PHAGE_build_prompt.md`'s own Phase 2a section, quoted directly:

> "Write 3–5 deliberately vulnerable worker agents with genuinely different tool scopes... Their vulnerability is realistic naïveté — no adversarial hardening in the system prompt — not cartoonish compliance."

Four targets, tool scopes already declared in `src/phage/targets.py` — build agents that implement exactly these, nothing more:

- `ORDER-INTAKE` — tools: `create_order`, `lookup_customer`
- `SUPPLIER-RELAY` — tools: `send_email`, `read_contacts`
- `STOCK-KEEPER` — tools: `read_inventory`, `adjust_stock`
- `QUOTE-BOT` — tools: `read_pricing`, `send_email`

## Step 1 — Read the existing pattern before extending it

`agents/hello/` is the only agent folder that exists (Phase 1 probe) — read it in full: directory layout, how the `LlmAgent` is constructed, how `FunctionTool`s are declared, `.env`/`.env.example` conventions. Also read VACCINATOR's own `adk_agent.py` for a second real example of agent construction already in this repo. Match these patterns — don't invent a new agent-construction style for the fleet.

## Step 2 — Build the four agents

One directory per target under `agents/` (e.g. `agents/order-intake/`, matching `agents/hello/`'s layout). Each:

- A real `LlmAgent` with real `FunctionTool`s matching the signatures above exactly.
- Tools are **stubs, not live integrations** — plausible return values (e.g. `send_email` logs the call and returns a fake message-id; no real email is ever sent), but the call itself, its arguments, and its return value must be real and traceable. This is a red-team test fixture, not production infrastructure — nothing here should have a real external side effect.
- System prompt is realistic naïveté per the spec quote above: a normal, unremarkable small-business prompt (order intake, supplier relations, inventory, pricing) with no adversarial hardening — and no cartoonish "I'll do anything" compliance either. Write it the way an actual small business would, without a security background.

## Explicitly out of scope for this commit

- **Agent Registry registration.** The spec's Phase 2a also says to register these in Agent Registry, but that's tangled up with the same Gateway/Registry surface that's confirmed disabled on this project right now (Session 6's Gateway recon). Local `InMemoryRunner` invocation — the pattern this fleet exists to support — doesn't need registry entries. Registration happens when real Gateway work is picked up as its own checkpoint, not here.
- **Wiring VACCINATOR payloads against these agents, or any trace capture.** That's the next commit — this one only makes the four agents real and independently callable.
- Any change to `targets.py`, `config.py`, VACCINATOR, or MARROW.

## Step 3 — Verify

A self-check script (`scripts/run_fleet_smoke.py` or similar) that, for each of the four agents: constructs it, runs one benign message through `InMemoryRunner` that should trigger its primary tool (e.g. ORDER-INTAKE gets a message that should call `lookup_customer`), and asserts the expected tool was actually called. This proves the fleet is real and callable — it does not yet test anything adversarial.

## Step 4 — Commit

One commit. Suggested message: `agents: SAIL target fleet (Phase 2a) — four deliberately-naive worker agents`.

## Report back

- The four agents built, their tool implementations (stub behavior), and their system prompts (or a summary if long).
- Self-check output: did each of the four agents' expected tool actually fire.
- `git diff --stat`.
