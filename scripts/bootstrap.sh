#!/usr/bin/env bash
# PHAGE bootstrap — reproducible spin-up from a clean checkout.
#
# Incremental by design: it grows as phases land. Phase 1 covers the Python
# environment, gcloud project/region config, ADC, and required-API enablement.
# Deploy and data-plane setup are added in later phases.
set -euo pipefail

# Project id, in precedence order: GOOGLE_CLOUD_PROJECT (the variable the PHAGE
# code itself reads, src/phage/config.py) first, then PROJECT_ID as an alias.
# There is deliberately NO default: this script sets gcloud config, enables APIs
# and grants IAM, and a default would aim all three at the project PHAGE was
# built on — a project you almost certainly cannot touch. Failing loudly with
# the fix in the message beats a silent PERMISSION_DENIED three commands later.
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-${PROJECT_ID:-}}"
INFRA_REGION="${INFRA_REGION:-us-central1}"

if [[ -z "${PROJECT_ID}" ]]; then
  cat >&2 <<'ERR'
ERROR: no Google Cloud project set.

  Set the project this should bootstrap, then re-run:

      export GOOGLE_CLOUD_PROJECT=your-project-id
      scripts/bootstrap.sh

  GOOGLE_CLOUD_PROJECT is the same variable src/phage/config.py reads at
  runtime, so exporting it configures the bootstrap AND the code. Note that
  `gcloud config set project` alone does NOT reach the code: every client is
  built with an explicit project= from that variable.

  To run PHAGE with no Google Cloud account at all, skip this script entirely —
  see "Run it with no Google Cloud account" in README.md.
ERR
  exit 1
fi

echo "==> PHAGE bootstrap (project=${PROJECT_ID}, infra region=${INFRA_REGION})"

# 1. Toolchain --------------------------------------------------------------
command -v uv >/dev/null     || { echo "ERROR: uv not found — https://docs.astral.sh/uv/"; exit 1; }
command -v gcloud >/dev/null || { echo "ERROR: gcloud not found — install the Cloud SDK"; exit 1; }

# 2. Python environment (pinned via pyproject.toml + uv.lock) ---------------
echo "==> Syncing Python environment (uv sync)"
uv sync

# 3. gcloud project + region ------------------------------------------------
echo "==> Configuring gcloud"
gcloud config set project "${PROJECT_ID}" >/dev/null
gcloud config set compute/region "${INFRA_REGION}" >/dev/null
gcloud config set run/region "${INFRA_REGION}" >/dev/null
gcloud config set ai/region "${INFRA_REGION}" >/dev/null

# 4. Application Default Credentials ----------------------------------------
if ! gcloud auth application-default print-access-token >/dev/null 2>&1; then
  echo "!!  No ADC found. Run:  gcloud auth application-default login"
fi

# 5. Required APIs ----------------------------------------------------------
echo "==> Enabling required APIs (idempotent)"
gcloud services enable \
  aiplatform.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  firestore.googleapis.com \
  modelarmor.googleapis.com \
  compute.googleapis.com \
  billingbudgets.googleapis.com

# 6. IAM for source-based Cloud Run deploys --------------------------------
# New orgs withhold the automatic Editor grant from default service accounts.
# The Compute Engine default SA is BOTH the Cloud Build identity (source deploys)
# and the Cloud Run runtime identity, so without explicit roles the deploy 403s
# reading the source bucket and the agent 403s when it calls Gemini.
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
echo "==> Granting build + Vertex roles to ${COMPUTE_SA}"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${COMPUTE_SA}" \
  --role="roles/cloudbuild.builds.builder" --condition=None >/dev/null
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${COMPUTE_SA}" \
  --role="roles/aiplatform.user" --condition=None >/dev/null

echo "==> Bootstrap (Phase 1) complete."
echo "    Local smoke test : uv run python scripts/run_local.py"
echo "    Deploy HELLO      : uv run adk deploy cloud_run --project=${PROJECT_ID} \\"
echo "                          --region=${INFRA_REGION} --service_name=phage-hello \\"
echo "                          --app_name=hello agents/hello -- --no-allow-unauthenticated"
