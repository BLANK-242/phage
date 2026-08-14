# PHAGE — Claude Code brief: MARROW recon pass (READ-ONLY)

## Mode

**READ-ONLY RECON.** This pass writes nothing.

- Do NOT create, edit, or patch any file.
- Do NOT run `git add`, `git commit`, or any git write command.
- Do NOT propose or draft MARROW code in this pass. Not even a sketch.
- No network, no `gcloud`, no Vertex calls.
- Allowed: `ls`, `cat`, `grep`, `rg`, `sed -n`, `git log`, `git status`, `git diff`, `uv run python -c` for import-path resolution only.

Output is **one written report in the chat**. Then stop.

## Why this pass exists

MARROW is the fleet orchestrator. Before a line of it is written, the driving
idiom has to be confirmed against **installed ADK 2.6.3 source**, not against
model recall of the ADK. Recon-first-then-build is the standard loop on this
repo.

The build decision that hangs on this report: **is MARROW a composed
`SequentialAgent`, or a custom `BaseAgent` with its own fan-out loop?**

## Step 0 — locate the installed source

```
uv run python -c "import google.adk, pathlib; print(pathlib.Path(google.adk.__file__).parent)"
```

Every file:line citation below must come from that tree (or from
`docs/reference/adk-llms-full.txt` by grep). State the resolved root path at
the top of your report.

Known-good anchors already verified on this repo last session — use them as
entry points, and re-confirm the line numbers still hold:

- `agents/base_agent.py:283` — child entry `run_async(parent_context=...)`
- `agents/sequential_agent.py` — the workflow driving idiom
- `sessions/base_session_service.py:154, 204-209` — `append_event` →
  `_update_session_state`
- `sessions/state.py:64-66` — reserved state prefixes are colon-delimited
- `agents/langgraph_agent.py:105-114` — Event-construction precedent

## Questions

Answer all six. Each gets its own block in the report format below.

### R1 — Workflow agent inventory

Which workflow agents ship in this ADK build (`SequentialAgent`,
`ParallelAgent`, `LoopAgent`, any others)? For each: module path, constructor
signature, and — critically — **is the `sub_agents` list fixed at construction
time, or can a parent add/iterate children discovered at runtime?**

PHAGE fans out across a registered target list whose length is known only at
run time. Report whether the shipped workflow agents can express that, or
whether it requires a custom `BaseAgent`.

### R2 — Child invocation contract

Confirm `BaseAgent.run_async(parent_context=...)` at `base_agent.py:283`:
exact signature, what it constructs from the parent context (does it derive a
child `InvocationContext`? does it set a `branch`?), and what a custom parent
is obligated to pass.

Then paste `SequentialAgent._run_async_impl` **verbatim** as the reference
idiom, and state in one sentence what a custom orchestrator must replicate
from it.

### R3 — State visibility timing *(highest value question in this pass)*

VACCINATOR's contract is state-in/state-out: it reads
`state["vaccinator.tool_scope"]` and writes `state["vaccinator.payloads"]` via
`EventActions.state_delta`.

So MARROW must set `vaccinator.tool_scope` and then invoke VACCINATOR **within
the same invocation**. The open question:

> If MARROW yields an Event carrying `state_delta` and then, after that yield
> resumes, invokes VACCINATOR via `run_async(parent_context=ctx)` — will
> VACCINATOR see the new value when it reads session state?

Trace it in source. Specifically: in `Runner.run_async`, where does the
`append_event` call sit **relative to the consumer's resumption of the agent
generator**? If `append_event` runs before the generator resumes, the delta is
applied in time; if not, it isn't.

Report the answer as one of:
- **HOLDS** — cite the exact lines proving the ordering.
- **DOES NOT HOLD** — cite the lines, then report what the source shows as the
  working alternative (direct `ctx.session.state` write alongside the delta,
  constructor-arg passing, per-child context, etc.).
- **NOT DETERMINABLE FROM SOURCE** — say so plainly.

Do not guess this one. The whole MARROW↔VACCINATOR seam rests on it.

### R4 — `sub_agent` vs `AgentTool`

Read `tools/agent_tool.py`. Answer:

- Does `AgentTool` require the calling agent to be an `LlmAgent` — i.e. is it
  only reachable through model function-calling?
- How does it pass input to and read output from the wrapped agent (own
  `Runner`? `input_schema`? a state key)?
- Does it work with a non-LLM custom `BaseAgent` child like VACCINATOR?

Then give a verdict with reasoning tied to source: which mechanism fits a
**deterministic** orchestrator that must not reintroduce a model in the
invocation path.

### R5 — Fan-out isolation

If two targets are processed concurrently, both children write
`vaccinator.payloads` — the same key.

From source: how does `ParallelAgent` isolate concurrent children? What is the
`branch` field on `InvocationContext` actually used for — event filtering for
LLM context assembly, or genuine state isolation? **Do parallel branches share
one `session.state` dict?**

If state is shared, say so directly and report what the source implies:
sequential per-target iteration, or per-target namespaced keys
(`vaccinator.payloads.<target_id>`).

### R6 — Termination and escalation

How does a child signal "stop the run" upward — `EventActions.escalate`? Where
is it consumed in source (which agents check it, and what do they do)? One
paragraph; this is cheap now and MACROPHAGE will need it.

## Report format

For each question:

```
R<n> — <title>
ANSWER:     <2-5 sentences, direct>
EVIDENCE:   <path:line> — <short paraphrase or ≤15-word quote>
            <path:line> — <...>
CONFIDENCE: confirmed-from-source | inferred-from-source | NOT FOUND
```

## Hard rules for this pass

1. **`CONFIDENCE: confirmed-from-source` requires a file:line citation.** No
   citation, no confirmation.
2. If you cannot find something in the installed tree, write **NOT FOUND**.
   Do not fill the gap from general ADK knowledge and present it as source.
   An honest NOT FOUND is a useful result; a confident wrong answer costs a
   rebuild.
3. If a known-good anchor line number above has drifted, say so and give the
   corrected line.
4. No code. No commits. Report, then stop.

## Closing line of your report

End with one sentence: **your recommendation for the MARROW driving idiom
(`SequentialAgent` composition vs. custom `BaseAgent` loop), and the single
piece of evidence that decides it.**
