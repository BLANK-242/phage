# PHAGE dashboard — read-only viewer, served on Cloud Run.
#
# The image carries only what the dashboard actually reads. It fires no agent,
# calls no model, and opens every SQLite connection read-only.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# fastapi and uvicorn are pinned to the versions pyproject.toml already declares;
# gunicorn and uvicorn-worker are the two additions, resolved with `uv pip compile`
# against those pins rather than recalled. uvicorn-worker is the separate package,
# NOT uvicorn's own `uvicorn.workers` module — that module still ships in 0.52.1
# but raises a DeprecationWarning on import (uvicorn/workers.py:17) and points here.
RUN pip install --no-cache-dir \
        fastapi==0.141.1 \
        uvicorn==0.52.1 \
        gunicorn==26.2.0 \
        uvicorn-worker==0.4.0

# src/ is deliberately absent: the dashboard imports nothing from src/phage — its
# every import is stdlib or fastapi — so the package is not a runtime dependency.
#
# It does read three committed artifacts, resolved from REPO_ROOT, which app.py
# defines as the PARENT of dashboard/. That makes /app the repo root here, so the
# layout below has to mirror the repo's:
#   data/loao_eval_result.json        -> ROC curve, AUC, the TPR/FPR callout
#   data/tune_threshold_result.json   -> the distance distributions
#   scripts/probe_distance_output.txt -> the three probe distances
# Without them every eval panel renders an `error` string instead of a figure.
COPY dashboard/app.py /app/dashboard/
COPY dashboard/static/ /app/dashboard/static/
COPY data/loao_eval_result.json data/tune_threshold_result.json /app/data/
COPY scripts/probe_distance_output.txt /app/scripts/

# The sanitized public fixture: the same 1,107 spans as the live database, with
# the customer's name redacted. The live phage_traces.db never enters the image
# and is excluded from the build context entirely (see .gcloudignore).
COPY dashboard/data/phage_traces_demo.db /app/data/phage_traces_demo.db
ENV PHAGE_TRACES_DB=/app/data/phage_traces_demo.db

RUN useradd --create-home --uid 10001 phage && chown -R phage:phage /app
USER phage

EXPOSE 8080

# Cloud Run injects $PORT; the default covers a bare `docker run`. Binding
# 0.0.0.0 is what makes the container reachable outside its own namespace.
#
# --threads is deliberately absent: it configures gunicorn's *sync* worker pool
# and is ignored by an ASGI worker, which serves concurrent requests on a single
# event loop. Concurrency is capped at the service level (--concurrency=40).
CMD exec gunicorn dashboard.app:app \
        --bind "0.0.0.0:${PORT:-8080}" \
        --workers 1 \
        --worker-class uvicorn_worker.UvicornWorker \
        --access-logfile - \
        --timeout 60
