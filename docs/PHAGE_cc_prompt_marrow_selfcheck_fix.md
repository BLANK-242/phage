# PHAGE — Fix MARROW Self-Check (build)

> **Build-history record.** Written during construction and left unedited.
> Figures and `file:line` citations here may be superseded. `docs/writeup.md`
> and `README.md` are the current, audited statements.

## Purpose

Wiring SENTINEL into MARROW's fire loop just exposed a pre-existing
assumption in `run_marrow.py`'s Step-3 spot-check (from commit `b11a879`,
written before SENTINEL existed): it hardcodes SUPPLIER-RELAY's
data-exfiltration firing and asserts it always produces `execute_tool`
spans. Tonight's live run had that exact payload Gemini-sourced (not the
fixed local-fallback template), and the target declined — SENTINEL
correctly triaged it `declined` (0 relevant spans, exactly its documented
behavior), but the old spot-check still failed the whole script (exit
code 1) on an outcome that was never actually a failure.

The real problem: a single fixed target/archetype was never going to
survive real model non-determinism, and now that SENTINEL exists,
re-deriving pass/fail from raw span counts on one hardcoded session does
SENTINEL's job worse than SENTINEL does it.

## Scope

Replace the SUPPLIER-RELAY-specific assertion in `run_via_marrow()`'s
Step-3 with two checks that don't depend on which specific payloads
happen to land on a given run:

1. **Capture floor** — total trace spans across the full fired set > 0
   (proves OTel capture is active at all; this held even in tonight's
   failing case — 4 spans, just 0 of type `execute_tool`).
2. **Self-consistency** — for every verdict SENTINEL classifies as
   `landed`, confirm its `supporting_spans` are non-empty and are
   actually present as `execute_tool` spans in the trace DB. This is
   deterministic regardless of how many payloads land on a given run
   (vacuously true if none land), and it catches a real regression —
   SENTINEL claiming `landed` without evidence — that the old check
   never could.

Confirm `TriageResult`'s exact field names and how verdicts are retrieved
post-run by reading `triage.py` and the session-state key directly —
don't take field names from this brief.

## Explicitly out of scope

- Don't touch `marrow/agent.py`'s fire loop or the SENTINEL wiring just
  landed.
- Don't add a requirement that at least one payload must land this run —
  that re-imposes the same non-determinism problem one level up instead
  of removing it.

## Verification

Re-run the same live fire cycle used to verify the wiring. Confirm exit
code 0. Separately, reason through — don't need to fabricate a run to
prove it — whether the self-consistency check would still correctly pass
(vacuously — nothing to check) if SENTINEL reported zero `landed`
verdicts for an entire run, rather than false-failing. Confirm yes.

## Output

Diff + confirmation of exit code 0 on the same class of run, cited
file:line. No other changes.
