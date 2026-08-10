# PHAGE — Claude Code brief: VACCINATOR ADK-agent wrapper

Scope: **one commit.** Wrap the existing deterministic `generate_payloads` engine in a
single ADK agent that receives a target's `tool_scope` from session state, runs the engine,
and yields the payloads back into session state. **Nothing else** — no registry, no
identity/gateway shims, no Firestore, no MARROW, no other agents. Those are later prompts and
are explicitly out of scope. If you feel the pull to "while I'm here, also wire X" — don't.
A tight, verifiable wrapper is the goal.

`CLAUDE.md` governs. In particular: **verify against installed ADK 2.6.3 source before
writing any ADK code — do not reconstruct APIs from memory.** This brief cites signatures
that a prior recon pass confirmed against installed source, but you must **re-open the cited
files and re-confirm each signature inline as you write it**, because some of the recon
detail is being relayed second-hand. If installed source disagrees with anything below,
**trust installed source and flag the discrepancy in your summary.**

Permission mode: acceptEdits / manual approve. Show the diff before it lands. Read shell
commands before they run.

**Recon is already substantially done** (a prior read-only pass confirmed the API facts below
against installed source). You do NOT need to repeat a full recon sweep — re-confirm only the
specific signatures flagged "re-confirm inline" as you write each one, then build. In
particular, the state-persistence mechanism was already resolved: use `EventActions.state_delta`
(see the interface section), not direct `ctx.session.state` mutation. Go straight to building
against the confirmed facts; don't re-derive them from scratch.

---

## Confirmed API facts from recon (re-verify inline against the cited file:line)

- **Base construct: custom `BaseAgent` subclass** — NOT a tool on an `LlmAgent`. VACCINATOR
  wraps a *deterministic* function and must own no model of its own (putting an LlmAgent in
  the loop would re-invite Gemini refusals at the agent layer, which we deliberately avoid).
- `BaseAgent` is a **pydantic model with `extra='forbid'`** (`base_agent.py:96-99`). Any
  field the subclass stores must be a declared pydantic field. **Preferred: store nothing** —
  call the module-level `generate_payloads` inside the run method and hold no state.
- **`name: str` is required and validated to be a valid Python identifier**
  (`base_agent.py:121`, `:619-634`). Use `name="VACCINATOR"`. Do **not** use hyphenated
  fleet target ids (e.g. `ORDER-INTAKE`) as the agent name — those are registry ids, a
  different namespace, and hyphens are illegal in an ADK agent name.
- **No `model` field on `BaseAgent`** (only `LlmAgent` has `model`/`instruction`). Correct —
  VACCINATOR owns its own Gemini call inside the engine.
- **`_run_async_impl` must be a real async generator** — `yield` at least one `Event`, or a
  bare `yield` (stub shape at `base_agent.py:381-384`). Re-confirm the **exact override name
  and full signature** in installed source before writing it (the recon relayed
  `_run_async_impl(self, ctx: ...)` — confirm the param name and the context type).
- **`Event`** — re-confirm the exact type name, import path, and constructor/usage from
  installed source (recon relayed events via the runner path; read the `Event` definition and
  how existing agents emit one).
- **Session/runner flow is already proven in `scripts/run_local.py`.**
  `InMemorySessionService.create_session(...)` is **async, keyword-only**
  (`in_memory_session_service.py:78-85`); `session.id` is the id; reach the service via
  `runner.session_service`. `InMemoryRunner` supplies the `session_service`. Even a
  deterministic agent must be handed a throwaway `new_message`
  (`types.Content(role="user", parts=[types.Part(text="run")])`) — `runners.py:1056-1058`.
- **Trap #1 does NOT apply to this commit** — confirmed: the agent/runner layer imports no
  Vertex/Agent-Engine client (`grep vertexai|agentplatform|.Client agents/base_agent.py` →
  none). The engine's `genai.Client(**config.gemini_client_kwargs())` is the only client, and
  it already exists. **Add no platform client.** (`vertexai.Client → agentplatform.Client` is
  a MARROW/deploy concern, later.)

If any of the "re-confirm" items above turns out different in installed source, adapt to
source and note it — do not force the relayed version.

---

## Interface: session state (this is the load-bearing design choice)

VACCINATOR receives its input from and returns its output to **session state**, not the
invocation message. This is deliberate: it's the idiomatic ADK pattern for passing structured
data between agents, and it's what lets MARROW (later) iterate the registry and fan out across
the whole fleet cleanly. Do not pack `tool_scope` into the message text.

Define a small, explicit state contract (put these keys somewhere importable — e.g. constants
in the agent module — so MARROW and tests share them, not magic strings):

- **Input key** — `ctx.session.state["vaccinator.tool_scope"]`: `list[str]` of the target's
  declared tool signatures (e.g. `["send_email(to, subject, body)", "read_inventory(sku)"]`).
- **Input key (optional)** — `ctx.session.state["vaccinator.target_id"]`: `str`, the
  registry id of the target (e.g. `"SUPPLIER-RELAY"`), for provenance/labelling only. The
  engine does not need it; carry it through to the output if present.
- **Output key** — `ctx.session.state["vaccinator.payloads"]`: the generated payloads as a
  list of plain dicts (serialize each `Payload` dataclass — `archetype_id`, `category`,
  `intent`, `target_tools`, `injection_text`, `paraphrase`, `source`). Dicts, not the
  dataclass, so the state stays JSON-friendly for later persistence.

Behavior of `_run_async_impl`:

1. Read `tool_scope` from state. If missing or not a non-empty `list[str]`, yield a single
   Event carrying a clear error/skip signal (don't raise into the runner) and return.
2. Call `generate_payloads(tool_scope)` — module-level, default args (Gemini enabled). Do
   **not** re-implement or alter the engine; import and call it. Provenance and the no-routing
   guardrail already live in the engine and must remain untouched.
3. **Write results via `EventActions.state_delta`, NOT by mutating `ctx.session.state`
   directly.** (Source-confirmed: `EventActions.state_delta: dict[str, Any]` at
   `event_actions.py:94` is the persistence mechanism the runner applies; direct mutation of
   `ctx.session.state` may not survive the round-trip.) So: build a `state_delta` dict
   containing `{"vaccinator.payloads": <serialized payloads>}` (and echo
   `"vaccinator.target_id"` through if it was provided), and attach it to the Event you yield
   via `EventActions`. **Re-confirm inline against installed source**: the exact
   `EventActions` import path and constructor, how `state_delta` is attached to an `Event`
   (i.e. the `Event(actions=EventActions(state_delta=...))` shape or equivalent), and — the
   piece recon didn't finish confirming before it was interrupted — that the runner actually
   **applies** `state_delta` back to the session so a subsequent `get_session`/state read sees
   the payloads. Read `run_local.py` and the runner source for the apply path; if any agent in
   the installed examples writes state, mirror that idiom exactly.
4. The single yielded Event both **carries the `state_delta`** (the structured result) and
   **summarizes the run** (e.g. author=name, a short text like
   `"VACCINATOR: N payloads for <target_id> (<k> gemini / <m> local-fallback)"`). The Event is
   how ADK surfaces the step *and* how the state change propagates — one Event does both.

Note on the read-back in the test/consumer: confirm the correct way to read the resulting
state after the run (the `get_session` signature / `runner.session_service` accessor recon was
mid-confirming when interrupted). The round-trip only counts as working if a fresh state read
after the run returns the payloads — prove that, don't assume it.

Keep the engine call synchronous inside the async generator (it is sync; that's fine — do not
wrap it in async or a thread here; `llm.py` backoff stays synchronous per `CLAUDE.md`).

---

## Local test (prove one invocation end-to-end)

Add `scripts/run_vaccinator_agent.py` (mirror the proven pattern in `scripts/run_local.py` —
read that file first and follow its runner/session setup, don't invent a new one):

1. Build an `InMemoryRunner` around a `VACCINATOR()` instance.
2. Create a session (async, keyword-only), seed
   `state["vaccinator.tool_scope"]` with one SAIL sink target's real tool signatures
   (SUPPLIER-RELAY or QUOTE-BOT — pull the actual signatures from the archetype/fleet
   definitions, don't hand-type guesses) and `state["vaccinator.target_id"]`.
3. Run one turn with the throwaway `new_message`.
4. After the run, read `state["vaccinator.payloads"]` back and print:
   - total payload count,
   - per-payload `source` (gemini | local-fallback) and `archetype_id`,
   - the same **provenance-mix assertion** as the engine demo: on a sink target,
     data-exfiltration must be `local-fallback` while at least one non-exfil archetype is
     `gemini`. Print `SELF-CHECK PASS` / `FAIL` accordingly.

Run it in **both** modes to keep the offline guarantee:
- Force local-only (thread the engine's `use_gemini=False` through a script flag, or seed a
  scope and assert the local path) → must show the deterministic library producing a payload
  per applicable archetype, **zero network**.
- Gemini mode → must show the per-archetype provenance mix.

---

## Verify, then commit

1. `py_compile` the new agent module + the new script.
2. Confirm the agent imports cleanly and `VACCINATOR().name == "VACCINATOR"`.
3. Run `scripts/run_vaccinator_agent.py` → `SELF-CHECK PASS`, and the state round-trip
   actually returns payloads (proves the state-in/state-out contract works, not just that the
   engine runs).
4. Confirm you added **no** new client, **no** model field, **no** registry/Firestore/other-
   agent code, and did **not** modify `engine.py`, `llm.py`, or `config.py`
   (`git diff --stat` should show only the new agent module + new script, nothing under the
   engine).
5. Grep the diff: no `flash-lite`/`3.6`, no per-archetype model selection, no `vertexai`/
   `agentplatform` import in the wrapper. The no-routing red line still holds.
6. Commit as one commit — descriptive message. Use the Write tool for the commit message if
   it's multi-line (no terminal heredoc, per `CLAUDE.md`).

**If the commit step trips an API error** (it has twice this session on payload-heavy diffs):
the edits are already on disk. Complete the commit manually —
`git add -A && git commit -m "..."` — rather than losing the work. Report if this happens.

Report back: the diff `--stat`, the two run modes' PASS/provenance lines, the confirmed
override signatures you re-verified inline (with file:line), and anything in installed source
that contradicted this brief.
