"""PHAGE dashboard — read-only viewer for artifacts already on disk.

Renders two views: the evaluation figures from `data/*.json`, and a trace
replay from `phage_traces.db`. It computes no evaluation figures of its own —
every number it serves was produced by a committed script and is read back
verbatim. Nothing here fires an agent, calls a model, or writes anything.

All SQLite connections are opened read-only via a `file:...?mode=ro` URI, so
the span database cannot be modified by viewing it.

Run:  uv run uvicorn dashboard.app:app --port 8000
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Repo root resolved from THIS file, not the process working directory, so the
# server behaves identically however it is launched.
REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"

LOAO_PATH = REPO_ROOT / "data" / "loao_eval_result.json"
TUNE_PATH = REPO_ROOT / "data" / "tune_threshold_result.json"
PROBE_PATH = REPO_ROOT / "scripts" / "probe_distance_output.txt"
# `PHAGE_TRACES_DB` overrides where the span database is read from. The container
# image sets it to a sanitized fixture that carries the same 1,107 spans with the
# customer's name redacted; unset — the local case — it resolves exactly as before.
TRACE_DB_PATH = Path(os.environ.get("PHAGE_TRACES_DB") or REPO_ROOT / "phage_traces.db")

app = FastAPI(title="PHAGE dashboard", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _read_json(path: Path) -> dict[str, Any]:
    """Parse a committed result file, or return an explicit error object.

    These files ARE committed — the blanket `*.json` ignore rule carries a
    `!data/*.json` exemption precisely so a fresh clone can verify the reported
    figures — so on a clean checkout this path does not fire. It stays because a
    result file can still be absent mid-regeneration, and naming the missing file
    is more useful than serving zeros that read as a real measurement.
    """
    if not path.exists():
        return {"error": f"{path.relative_to(REPO_ROOT)} not found on disk"}
    try:
        with path.open() as fh:
            return json.load(fh)
    except Exception as exc:  # noqa: BLE001 -- surfaced to the page, not swallowed
        return {"error": f"{path.relative_to(REPO_ROOT)}: {type(exc).__name__}: {exc}"}


_SUMMARY_HEADER = "=== summary: distances ==="
_SUMMARY_LINE = re.compile(r"^\s*(.+?)\s+distance=([0-9.]+)\s*$")

# The three labels the probe emits, mapped to the keys the page consumes.
_PROBE_KEYS = {
    "byte-identical": "identical",
    "paraphrase (same intent, different wording)": "paraphrase",
    "unrelated (different topic)": "unrelated",
}


def _parse_probe_distances() -> dict[str, Any]:
    """Pull the three distances out of the probe output's summary block.

    Returns an object carrying an `error` key if the block is absent or does
    not yield all three labels. It deliberately does NOT fall back to a
    default value: a wrong distance rendered confidently is worse than a
    visible parse failure, and this figure is quoted in docs/writeup.md.
    """
    if not PROBE_PATH.exists():
        return {"error": f"{PROBE_PATH.relative_to(REPO_ROOT)} not found on disk"}
    text = PROBE_PATH.read_text()
    if _SUMMARY_HEADER not in text:
        return {"error": f"summary block {_SUMMARY_HEADER!r} not found in probe output"}

    block = text.split(_SUMMARY_HEADER, 1)[1]
    found: dict[str, str] = {}
    for line in block.splitlines():
        if not line.strip():
            if found:  # blank line after we started collecting ends the block
                break
            continue
        m = _SUMMARY_LINE.match(line)
        if m is None:
            break
        label, value = m.group(1).strip(), m.group(2)
        key = _PROBE_KEYS.get(label)
        if key is not None:
            found[key] = value  # kept as the literal STRING the file holds

    missing = [k for k in _PROBE_KEYS.values() if k not in found]
    if missing:
        return {"error": f"probe summary parsed but missing label(s): {', '.join(missing)}"}
    return found


def _connect_traces() -> sqlite3.Connection:
    if not TRACE_DB_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                f"{TRACE_DB_PATH.name} not found. It is matched by .gitignore, so a "
                "fresh clone does not include it; the trace view needs a local run."
            ),
        )
    con = sqlite3.connect(f"file:{TRACE_DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _ms(start: Optional[int], end: Optional[int]) -> Optional[float]:
    if start is None or end is None:
        return None
    return round((end - start) / 1_000_000, 3)


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/eval")
def api_eval() -> JSONResponse:
    """The evaluation view's entire payload: two committed result files read
    back verbatim, plus the three probe distances."""
    return JSONResponse(
        {
            "loao": _read_json(LOAO_PATH),
            "tune": _read_json(TUNE_PATH),
            "probe": _parse_probe_distances(),
            "sources": {
                "loao": "data/loao_eval_result.json",
                "tune": "data/tune_threshold_result.json",
                "probe": "scripts/probe_distance_output.txt",
            },
        }
    )


@app.get("/api/sessions")
def api_sessions() -> JSONResponse:
    """Sessions available for replay.

    Spans whose `session_id` is NULL are not dropped — they are grouped by
    `trace_id` instead and flagged `grouped_by: "trace_id"`, so the page can
    label them honestly rather than presenting a trace as if it were a
    session.
    """
    con = _connect_traces()
    try:
        rows = con.execute(
            """
            SELECT session_id AS id, COUNT(*) AS span_count,
                   MIN(start_time_unix_nano) AS first_ns,
                   MAX(end_time_unix_nano)   AS last_ns
              FROM spans WHERE session_id IS NOT NULL
             GROUP BY session_id ORDER BY first_ns
            """
        ).fetchall()
        sessions = [
            {
                "id": r["id"],
                "grouped_by": "session_id",
                "span_count": r["span_count"],
                "first_ns": r["first_ns"],
                "last_ns": r["last_ns"],
                "duration_ms": _ms(r["first_ns"], r["last_ns"]),
            }
            for r in rows
        ]

        orphan_rows = con.execute(
            """
            SELECT trace_id AS id, COUNT(*) AS span_count,
                   MIN(start_time_unix_nano) AS first_ns,
                   MAX(end_time_unix_nano)   AS last_ns
              FROM spans WHERE session_id IS NULL
             GROUP BY trace_id ORDER BY first_ns
            """
        ).fetchall()
        orphans = [
            {
                "id": r["id"],
                "grouped_by": "trace_id",
                "span_count": r["span_count"],
                "first_ns": r["first_ns"],
                "last_ns": r["last_ns"],
                "duration_ms": _ms(r["first_ns"], r["last_ns"]),
            }
            for r in orphan_rows
        ]
        null_span_count = sum(o["span_count"] for o in orphans)
    finally:
        con.close()

    return JSONResponse(
        {
            "sessions": sessions,
            "trace_groups": orphans,
            "null_session_id_spans": null_span_count,
            "null_session_id_trace_groups": len(orphans),
            "source": "phage_traces.db",
        }
    )


@app.get("/api/session/{ident}")
def api_session(ident: str) -> JSONResponse:
    """Spans for one session id, or — if none match — one trace id."""
    con = _connect_traces()
    try:
        rows = con.execute(
            "SELECT * FROM spans WHERE session_id = ? ORDER BY start_time_unix_nano",
            (ident,),
        ).fetchall()
        grouped_by = "session_id"
        if not rows:
            rows = con.execute(
                "SELECT * FROM spans WHERE session_id IS NULL AND trace_id = ?"
                " ORDER BY start_time_unix_nano",
                (ident,),
            ).fetchall()
            grouped_by = "trace_id"
    finally:
        con.close()

    if not rows:
        raise HTTPException(status_code=404, detail=f"no spans for {ident!r}")

    spans = []
    for r in rows:
        raw = r["attributes_json"]
        try:
            attrs = json.loads(raw) if raw else {}
        except Exception:  # noqa: BLE001 -- show the raw text rather than nothing
            attrs = {"_unparsed_attributes_json": raw}
        spans.append(
            {
                "span_id": r["span_id"],
                "parent_span_id": r["parent_span_id"],
                "trace_id": r["trace_id"],
                "name": r["name"],
                "start_ns": r["start_time_unix_nano"],
                "duration_ms": _ms(r["start_time_unix_nano"], r["end_time_unix_nano"]),
                "attributes": attrs,
            }
        )

    return JSONResponse(
        {"id": ident, "grouped_by": grouped_by, "span_count": len(spans),
         "spans": spans, "source": "phage_traces.db"}
    )
