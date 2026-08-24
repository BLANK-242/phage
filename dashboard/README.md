# PHAGE dashboard

A **read-only** viewer for artifacts this repo already produced. It renders
committed files and **computes no evaluation figures of its own** — every number
on the page was produced by a script in `scripts/`, written to disk, and is read
back verbatim. Opening the dashboard fires no agent, calls no model, writes
nothing, and opens every SQLite connection read-only (`file:...?mode=ro`).

## Run it

```bash
uv run uvicorn dashboard.app:app --port 8000
```

Then open <http://127.0.0.1:8000/>. Paths resolve from the repo root, so the
working directory you launch from does not matter.

No new dependencies: `fastapi` and `uvicorn` are already declared in
`pyproject.toml`. There is no build step, no framework, and no CDN or external
font — the charts are hand-written SVG.

## Which file backs each panel

| Panel | Source file |
|---|---|
| ROC curve, AUC, TPR/FPR at 0.59 | `data/loao_eval_result.json` (`pooled_positives_sorted`, `pooled_negatives_sorted`, `auc`, `fpr_at_tpr_1.00`) |
| LOAO fold structure | `data/loao_eval_result.json` (`fold_results`) |
| Distance distributions | `data/tune_threshold_result.json` (`variant_sorted`, `hard_negative_sorted`, `cross_target_sorted`) |
| Probe distances | `scripts/probe_distance_output.txt` (the `=== summary: distances ===` block) |
| Trace replay | `phage_traces.db` |

The AUC shown is the stored `auc` field, not a value recomputed in the browser.
The ROC polyline is drawn from the stored distance arrays; recognition is
`distance < threshold`, so a lower distance is a stronger positive prediction and
the curve is swept in that direction.

**Probe rounding.** The identical-text floor renders at full precision
(`0.3861411047948597`) because it is stable — three consecutive runs agreed to all
16 digits. The paraphrase and unrelated distances render rounded to three decimals
(`0.529`, `0.875`) because they drift from roughly the eighth decimal place
between runs; showing them in full would imply a precision the measurement does
not have.

## What a fresh clone will and will not have

Three of the five artifacts are matched by `.gitignore` and are therefore **not in
the repository**. Cloning and running the dashboard will show errors in those
panels until the relevant script is run locally.

| Artifact | In the repo? | Why |
|---|---|---|
| `data/recognition_pairs.jsonl` | **tracked** | committed dataset |
| `scripts/probe_distance_output.txt` | **tracked** | committed probe evidence |
| `data/loao_eval_result.json` | **not tracked** | ignored by `.gitignore:5` (`*.json`) |
| `data/tune_threshold_result.json` | **not tracked** | ignored by `.gitignore:5` (`*.json`) |
| `phage_traces.db` | **not tracked** | ignored by `.gitignore:29` (`phage_traces*.db`) |

**The trace replay view requires `phage_traces.db`, and that file is not in the
repository.** It is produced locally by running the fire path
(`scripts/run_marrow.py` or `scripts/run_demo_scene.py`); without it, `/api/sessions`
returns 404 with an explanatory message rather than an empty list. The same applies
to the two eval JSONs: the API returns an explicit `error` field for a missing file
instead of substituting a default, so a blank panel is never mistaken for a real
measurement of zero.

Changing `.gitignore` was out of scope for this branch. If the dashboard is meant
to work from a clean clone, that decision needs making separately.

## Endpoints

| Route | Returns |
|---|---|
| `GET /` | the page |
| `GET /api/eval` | parsed `loao_eval_result.json` + `tune_threshold_result.json` + the three probe distances |
| `GET /api/sessions` | distinct `session_id` with span count and time bounds |
| `GET /api/session/{id}` | spans for one session or trace, ordered by start time |

### Spans with no session id

294 of the 1,107 spans in `phage_traces.db` have a NULL `session_id`. They are not
dropped: `/api/sessions` groups them by `trace_id` into 139 groups, returns them
under `trace_groups`, and marks each `grouped_by: "trace_id"`. The picker labels
them with a `trace` badge so a trace is never presented as if it were a session.

## Trace view

Spans render as a vertical timeline ordered by start time and indented by parent
depth. For `execute_tool` spans the recorded `tool_call_args` and `tool_response`
are shown **exactly as captured** — the dashboard applies no heuristic and attaches
no label calling a call malicious, suspicious, or an exfiltration. The arguments
are the evidence; reading them is the viewer's job. For `call_llm` spans it shows
the model and token counts, with the request and response blobs behind an expand
control.
