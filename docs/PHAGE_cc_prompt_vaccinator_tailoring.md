# PHAGE — Claude Code brief: VACCINATOR tailoring patch (checkpoint-1 outcome)

Scope: one commit. Refactor VACCINATOR's Gemini tailoring from **per-target batch** to **per-archetype isolation**, harden the paraphrase contract, and lock in a no-routing guardrail. Do **not** touch the ADK-agent wrapper, the other four agents, or the archetype library contents — that's the next prompt.

These decisions came out of a review checkpoint. They're settled. Implement them; don't re-litigate. But **verify every claim below against the actual current source on disk** — the reasoning references `src/phage/vaccinator/engine.py` and `src/phage/llm.py` as they were at commit `49eb742`; if the working tree has drifted, adapt to what's actually there and say so in your summary. Do not reconstruct the engine from this brief.

Permission mode stays `acceptEdits` / manual approve. Show me the diff before it lands.

---

## Task 1 — Per-archetype tailoring isolation

**Problem (verified):** `generate_payloads` hands the entire list of rendered archetypes to a single `_tailor_with_gemini` call. Inside, any refusal marker or non-list parse does `return {}`, which drops **every** archetype in the batch to `local-fallback` — not just the one Gemini objected to. Observed effect: on targets whose batch contains an objectionable archetype (exfil-class on sink targets; sometimes `tool-coercion`), the *benign* archetypes sitting next to it also lose their Gemini tailoring. The provenance split (14 gemini / 14 local across the fleet) and non-deterministic whole-batch refusals both trace to this.

The partial-fallback path in `generate_payloads` already handles missing ids correctly — any archetype absent from the returned map falls back individually. So the fix is upstream: **make each Gemini call cover exactly one archetype**, so a refusal costs one payload instead of the batch.

**Implement:**

1. Replace `_tailor_with_gemini(client, *, model, tool_scope, rendered: list[...])` with:

   ```
   _tailor_one(client, *, model, tool_scope, arch_id, text) -> Optional[tuple[str, Optional[str]]]
   ```

   - Returns `(injection_text, paraphrase)` on success, `None` on refusal / parse-failure / empty.
   - Same system instruction (`_TAILOR_SYSTEM`) and same JSON contract as today, but the user message carries a **single** template, and the model returns a single object `{"injection_text", "paraphrase"}` (not an array). Keep the tolerant `extract_json` + refusal-marker check; on `None`-equivalent, return `None`.

2. In `generate_payloads`, replace the single batched call with a fan-out over `selected`:

   - Use `concurrent.futures.ThreadPoolExecutor(max_workers=4)`. **Threads, not async** — `llm.py`'s `generate_with_backoff` is synchronous and must stay that way (backoff satisfies trap #6; do not rewrite it to async).
   - `max_workers=4` is a hard cap, not a tunable-up default: it respects the new-project Vertex per-minute rate limit. Do not raise it.
   - Preserve exact provenance semantics: a per-archetype call that returns a value → `source="gemini"`; `None` or any exception on that call → that archetype uses its `local[a.id]` render with `source="local-fallback"`. One archetype failing must not affect any other.
   - Preserve deterministic ordering of the returned `payloads` list (sort by `selected` order after the fan-out completes; don't let executor scheduling reorder them).

3. Leave `render_local`, `_slots`, `classify_scope`, `select_archetypes`, and the `Payload` dataclass untouched. Local instantiation must still produce a tool-tailored payload for every applicable archetype independent of Gemini.

**Why this is the better judging artifact, not just a reliability fix:** per-archetype provenance lets the demo show "6/8 archetypes Gemini-tailored, exfil-class declined and fell to the deterministic local library — here's the tool-specific fallback that stood in." That's more defensible than a clean sweep, because it proves the attack surface doesn't depend on model compliance.

---

## Task 2 — Paraphrase contract hardening (engine side of the ARCHIVIST decision)

The `paraphrase` field is currently unreliable — Gemini sometimes omits it, and when present it may be only a lexical reword. ARCHIVIST (Phase 3) will own a deterministic mutation step and will **not** hard-depend on this field, but the engine should still maximize its usefulness when it is present.

In the single-item `_tailor_one` request, tighten the paraphrase instruction: require the paraphrase to be a **structural** reframe of the injection — a different sentence shape and different framing verbs carrying the *same* intent and the *same* tool references — explicitly **not** a synonym swap. Keep it a required output field. If the model still returns it absent/empty, `None` is fine — the fallback owns that case.

Do not add retries specifically to force a paraphrase; one attempt per archetype, `None` on absence.

---

## Task 3 — Guardrail: no refusal-defeating model routing (do NOT implement a route)

This is a **negative** requirement — a thing to guarantee stays *out*, because a well-meaning refactor might add it.

A diagnostic showed that `gemini-3.5-flash-lite` and `gemini-3.6-flash` will comply with the exact adaptation request that `gemini-3.5-flash` refuses. **Do not route exfil-class (or any) archetypes to a different model to get past a refusal.** That is dodging the classifier, and it's an explicit project red line. When `gemini-3.5-flash` refuses an archetype, the correct behavior is the existing one: fall to `local-fallback`. The default inference model stays `config.GEMINI_MODEL` (`gemini-3.5-flash`) for all archetypes.

If you find any existing code path that selects a model per-archetype-class, flag it — don't "fix" it by adding one.

(Region split is unchanged and already correct: inference → `global`, infra → `us-central1`, per `config.py`. Don't touch it.)

---

## Verify, then commit

1. Run `scripts/vaccinate_demo.py` in **both** `--no-gemini` and Gemini modes. `--no-gemini` must still be `SELF-CHECK PASS` with zero network calls.
2. In Gemini mode, confirm provenance is now **per-archetype**: on a sink target (SUPPLIER-RELAY / QUOTE-BOT), the exfil archetype may show `local-fallback` while the benign archetypes on the *same* target show `gemini`. That mix is the success signal — a whole-target sweep to local means the fan-out didn't isolate.
3. Confirm the differentiation matrix at the end of the demo is unchanged (exfil-class only under sink targets, tool-coercion only under mutators).
4. Add a small print of `paraphrase` presence per gemini payload to the demo output (so the field is inspectable without a separate script) — one line per payload, e.g. `para=yes|no`.
5. Commit with a message describing the isolation change and the no-routing guardrail. One commit.

Report back: the diff summary, the two demo runs' PASS/provenance lines, and anything on disk that contradicted this brief.
