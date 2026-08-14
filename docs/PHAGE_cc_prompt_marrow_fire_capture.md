# PHAGE — Claude Code brief: MARROW fire-and-capture (fleet loop, extended)

Scope: **one commit.** Extend MARROW's existing fleet loop to fire each generated payload at its target and capture the resulting trace locally. No SENTINEL logic — this commit only produces real, queryable trace data for SENTINEL to consume next.

## Before you start

Confirm the MODEL LINE reads **Sonnet 5**.

## What's already proven, don't re-derive

- MARROW's fleet loop already exists (`src/phage/marrow/agent.py`, commit `a134cc4`): sequential loop over `FLEET` from `targets.py`, seeding `vaccinator.tool_scope`, `await ctx.run_node(vaccinator, use_sub_branch=True, run_id=target.id)`, reading `session.state` immediately after each call (required — `use_sub_branch` doesn't isolate state, confirmed Session 6), accumulating into `marrow.fleet_payloads`.
- Direct agent-to-agent invocation via `InMemoryRunner` is proven four times now (`run_local.py`, `run_vaccinator_agent.py`, `run_marrow.py`, `run_fleet_smoke.py`) — same pattern, point it at a real target agent with a payload string as the new message.
- ADK's trace exporter: `google/adk/telemetry/sqlite_span_exporter.py` — `SqliteSpanExporter(db_path=...)`, ADK's own shipped local-dev exporter, `get_all_spans_for_session(session_id) -> list[ReadableSpan]` as the read-back. Needs a `TracerProvider` installed with a span processor wrapping it before any run — confirmed not installed by default.
- Tool-call content is captured by default: `execute_tool` spans carry `gcp.vertex.agent.tool_call_args` / `tool_response` as real JSON (`ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS` defaults `'true'`) — no extra config needed for this.
- The four target agents exist and are real (`agents/order_intake/`, `agents/supplier_relay/`, `agents/stock_keeper/`, `agents/quote_bot/`, commit `a3aad51`) — module names underscored, matching each agent's own `name` field.

## Step 1 — Wire the TracerProvider once, at the entry point

Wherever `run_marrow.py` currently sets up its context, install a `TracerProvider` with a span processor wrapping `SqliteSpanExporter(db_path=...)` before MARROW's loop runs. One provider for the whole run, not per-target.

## Step 2 — Extend the fleet loop

After MARROW collects a target's payloads from VACCINATOR (existing step, don't touch), for each payload: fire it at that target via `InMemoryRunner`, using the payload string as the new message, in a session scoped to that target+payload (so spans can be pulled back per-firing via `session_id`). Store the `session_id` — not the full trace, that's a read-back concern for whoever consumes this next — in a new MARROW-owned key, e.g. `marrow.fleet_fire_sessions`, keyed the same way `fleet_payloads` already is.

Sequential, same as the existing loop. No concurrency — out of scope for this commit.

## Step 3 — Update the self-check

`run_marrow.py`: for at least one target, after the loop, call `get_all_spans_for_session()` on one of the stored session_ids and assert real `execute_tool` spans come back with non-empty `tool_call_args`. This proves the whole chain — generate, fire, capture — actually works end to end, not just that it runs without error.

## Step 4 — Verify

`git diff --stat` — expect `marrow/agent.py` and `scripts/run_marrow.py` modified, nothing else. `uv run python scripts/run_marrow.py --no-gemini` passes, real spans confirmed present for at least one fired payload.

## Step 5 — Commit

One commit. Suggested message: `marrow: fire generated payloads at targets, capture local traces`.

## Do NOT touch this commit

SENTINEL doesn't exist yet — don't start it. VACCINATOR internals, the four target agents' own code, Gateway/Registry/Model Armor (still deferred).

## Report back

- Confirm `get_all_spans_for_session()` output for at least one real fired payload — the actual `tool_call_args`/`tool_response` content, not just a pass/fail.
- `git diff --stat`.
- Self-check output.
