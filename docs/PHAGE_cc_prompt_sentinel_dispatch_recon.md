# PHAGE — Claude Code brief: SENTINEL dispatch + trace-capture recon

> **Build-history record.** Written during construction and left unedited.
> Figures and `file:line` citations here may be superseded. `docs/writeup.md`
> and `README.md` are the current, audited statements.

Scope: **read-only.** No file edits, no commits, no new files.

## Before you start

Confirm the MODEL LINE reads **Sonnet 5**.

## Decision made (upstream of this brief — do not re-litigate)

Gateway/Model Armor/Observability cloud integration (Q4) is confirmed genuinely unbuilt — `networkservices.googleapis.com` is disabled on `phage-dev`, cleanly, not a permission ambiguity. It's deferred to its own later checkpoint, not abandoned. SENTINEL builds now against real, locally-captured ADK OpenTelemetry output instead of a cloud-hosted trace. MACROPHAGE gets the same treatment later: its "cut Gateway routes" containment action is deferred the same way; its other actions (revoke Agent Identity, quarantine, roll back Memory Bank writes) don't depend on Gateway at all.

## Why this recon exists

Nothing in this repo currently sends a VACCINATOR-generated payload to a live target agent and captures what it does — Gateway or no Gateway. MARROW generates payloads across the fleet; nothing fires them. SENTINEL has nothing to triage until that exists. This recon exists to find out how small that gap actually is before anything gets built against it.

## Step 1 — Is there already a direct-invocation pattern anywhere?

Grep the repo for anything that calls an ADK agent directly, agent-to-agent, outside of Gateway (search terms: `Runner`, `run_live`, a direct `.run(` against a target's actual endpoint, anything in VACCINATOR or MARROW that reaches toward a target rather than just generating a payload string). Quote what's found, file:line — or confirm plainly that nothing exists yet.

## Step 2 — What does ADK actually emit locally, and how do you capture it?

- Confirm what `google/adk/telemetry/` actually instruments — span names, attributes, what a tool call looks like on the wire.
- Confirm whether ADK's trace exporter needs explicit configuration to write somewhere locally readable (console, file) or is cloud-export-only by default. `PHAGE_build_prompt.md:98`'s "don't re-add it" trap implies the plumbing exists — confirm exactly what "exists" means in practice: already emitting somewhere, or just present as an importable dependency with no active exporter configured.

## Step 3 — Report back

Quote sources, file:line, for everything above. State plainly: what's the smallest correct dispatch mechanism — call the target directly, capture its OpenTelemetry span locally — that would give SENTINEL something real to triage. Not the full Gateway path. Just what's actually needed for an honest local stand-in.
