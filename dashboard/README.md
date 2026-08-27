# PHAGE dashboard

A **read-only** viewer for artifacts this repo already produced. It renders
committed files and **computes no evaluation figures of its own** — every number
on the page was produced by a script in `scripts/`, written to disk, and is read
back verbatim. Opening the dashboard fires no agent, calls no model, writes
nothing, and opens every SQLite connection read-only (`file:...?mode=ro`).

## Run it

```bash
PHAGE_TRACES_DB=$PWD/dashboard/data/phage_traces_demo.db uv run uvicorn dashboard.app:app --port 8000
```

Then open <http://127.0.0.1:8000/>. Paths resolve from the repo root, so the
working directory you launch from does not matter — but `$PWD` in the line above
does, so run it from the repo root or write the path out in full.

**Both views work from a fresh clone with no Google Cloud credentials.** The
evaluation view reads the committed `data/*.json`; the trace view reads the
committed span fixture named above.

`PHAGE_TRACES_DB` selects the span database (`dashboard/app.py`, `TRACE_DB_PATH`):

| Value | Reads |
|---|---|
| `dashboard/data/phage_traces_demo.db` | The **committed, redacted fixture** — 1,107 real spans. Works on any clone. |
| unset | `phage_traces.db` at the repo root — your own local spans, written by running the fire path. Gitignored, so a fresh clone does not have it and the trace view returns an explanatory 404. |
| any other path | That database. |

The deployed Cloud Run service sets it to the fixture (`Dockerfile`), which is
what the live dashboard serves.

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
| Trace replay | whatever `PHAGE_TRACES_DB` points at — `dashboard/data/phage_traces_demo.db` (committed) or your local `phage_traces.db` |

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

**Every artifact the dashboard needs is committed.** A fresh clone renders both
views in full — the evaluation figures and the trace replay — with no local run
and no Google Cloud credentials, provided `PHAGE_TRACES_DB` points at the
committed fixture as shown in [Run it](#run-it).

| Artifact | In the repo? | Why |
|---|---|---|
| `data/recognition_pairs.jsonl` | **tracked** | committed dataset |
| `scripts/probe_distance_output.txt` | **tracked** | committed probe evidence |
| `data/loao_eval_result.json` | **tracked** | shipped in `50d34fd`; the blanket `*.json` ignore rule was narrowed by `!data/*.json` in `26669b0` |
| `data/tune_threshold_result.json` | **tracked** | shipped in `50d34fd`; same exemption |
| `dashboard/data/phage_traces_demo.db` | **tracked** | the redacted span fixture; the `phage_traces*.db` ignore rule matched it by name, so it carries an explicit `!` exemption |
| `phage_traces.db` | **not tracked** | your own local spans — matched by the `phage_traces*.db` ignore rule, and it accumulates every run |

The two span databases differ only in scope and redaction. The fixture is a
point-in-time, redacted copy: the same 1,107 spans, with the customer name in
the exfiltration payload replaced. The root `phage_traces.db` is a working file
that grows with every fire — it holds more spans than the fixture on any machine
that has run the demo.

**The trace view only 404s if you leave `PHAGE_TRACES_DB` unset on a clone that
has never run the fire path.** In that case `/api/sessions` returns 404 with an
explanatory message rather than an empty list. Point it at the fixture and the
view renders; run `scripts/run_marrow.py` or `scripts/run_demo_scene.py` and the
root database appears with your own spans.

The evaluation view has no such dependency at all. Both eval JSONs ship, so every
figure on that tab renders from a clean clone however `PHAGE_TRACES_DB` is set.

For any missing file the API returns an explicit `error` field rather than
substituting a default, so a blank panel is never mistaken for a real measurement
of zero.

## Endpoints

| Route | Returns |
|---|---|
| `GET /` | the page |
| `GET /api/eval` | parsed `loao_eval_result.json` + `tune_threshold_result.json` + the three probe distances |
| `GET /api/sessions` | distinct `session_id` with span count and time bounds |
| `GET /api/session/{id}` | spans for one session or trace, ordered by start time |

### Spans with no session id

294 of the 1,107 spans in the committed fixture have a NULL `session_id`. They are
not dropped: `/api/sessions` groups them by `trace_id` into 139 groups alongside
36 real sessions, returns them under `trace_groups`, and marks each
`grouped_by: "trace_id"`. The picker labels them with a `trace` badge so a trace
is never presented as if it were a session. (The counts above are the fixture's,
which is what a fresh clone sees; a local `phage_traces.db` will report higher
numbers as it accumulates runs.)

## Trace view

Spans render as a vertical timeline ordered by start time and indented by parent
depth. For `execute_tool` spans the recorded `tool_call_args` and `tool_response`
are shown **exactly as captured** — the dashboard applies no heuristic and attaches
no label calling a call malicious, suspicious, or an exfiltration. The arguments
are the evidence; reading them is the viewer's job. For `call_llm` spans it shows
the model and token counts, with the request and response blobs behind an expand
control.
