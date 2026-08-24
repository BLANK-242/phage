# PHAGE — Claude Code brief: SENTINEL ADK wrapper (Stage 2)

> **Build-history record.** Written during construction and left unedited.
> Figures and `file:line` citations here may be superseded. `docs/writeup.md`
> and `README.md` are the current, audited statements.

Scope: **one commit.** Wrap the already-built triage logic (`sentinel/triage.py`, commit `6c32577`) in ADK's `BaseAgent` contract — same shape as VACCINATOR's own `adk_agent.py`. No MARROW integration yet; that's Stage 3, its own commit, same as VACCINATOR's staged build.

## Before you start

Confirm the MODEL LINE reads **Sonnet 5**.

## Step 1 — Read the two things this needs to bridge

- `src/phage/vaccinator/adk_agent.py` in full — this is the pattern to mirror exactly: how `BaseAgent._run_impl`/`_run_async_impl` bridges the node call contract to the underlying engine logic, what it reads from `ctx.session.state` going in, what it writes back going out.
- `src/phage/sentinel/triage.py`'s actual current interface — function signatures, what it needs as input (a firing's session_id + originating payload/archetype from `fleet_payloads`), and what it returns. Quote it, don't assume it matches this brief's own earlier description of what it does.

## Step 2 — Build the wrapper

`src/phage/sentinel/adk_agent.py` — a `BaseAgent` subclass, same construction pattern as VACCINATOR's. One firing per invocation, matching how MARROW already calls VACCINATOR once per target — not a batch. That keeps Stage 3's future orchestrator loop a straightforward extension of a pattern that already exists, rather than a new shape.

Reads whatever `ctx.session.state` seed the caller provides (a single firing to triage), calls into `triage.py`'s actual confirmed interface from Step 1, writes the verdict back to state. Match VACCINATOR's naming convention for state keys if one is established (e.g. how `vaccinator.tool_scope` is scoped) — don't invent a new pattern.

## Step 3 — Self-check

`scripts/run_sentinel_agent.py`, matching `run_vaccinator_agent.py`'s shape: `InMemoryRunner` around the new wrapper, seeded with one real firing (small `--no-gemini` fire-and-capture cycle for the test fixture, same approach `triage.py`'s own self-check already uses), asserting the wrapper produces the same verdict the underlying `triage.py` would produce called directly — proving the bridge doesn't lose or distort anything Step 2 built.

## Step 4 — Verify

`git diff --stat` — new `sentinel/adk_agent.py` and the new self-check script; `sentinel/triage.py`, MARROW, and VACCINATOR untouched.

## Step 5 — Commit

One commit. Suggested message: `sentinel: ADK wrapper — BaseAgent bridge for triage.py`.

## Do NOT touch this commit

MARROW's loop (Stage 3, next). `triage.py`'s own logic — this commit wraps it, doesn't change it.

## Report back

- Step 1's confirmed interface for `triage.py`.
- Self-check output — wrapper's verdict vs. a direct `triage.py` call, same firing.
- `git diff --stat`.
