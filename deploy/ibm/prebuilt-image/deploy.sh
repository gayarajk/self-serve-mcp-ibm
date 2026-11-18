#!/usr/bin/env bash
# deploy/ibm/prebuilt-image/deploy.sh
#
# Deploy gsa_graj_tools and gsa_graj_viz to IBM Code Engine from a pre-built
# public image on GHCR (no ICR auth or local Docker required).
#
# Usage:
#   # 1. Set env vars (from .env or manually)
#   set -a; source deploy/ibm/prebuilt-image/.env; set +a
#
#   # 2. Log in to IBM Cloud
#   ibmcloud login --sso        # or: ibmcloud login --apikey "$IBMCLOUD_API_KEY"
#
#   # 3. Run
#   bash deploy/ibm/prebuilt-image/deploy.sh
#
# Required env vars (set in .env):
#   IBM_CLOUD_REGION, IBM_RESOURCE_GROUP, CE_PROJECT
#   TOOLS_IMAGE, VIZ_IMAGE
#   TOOLS_APP_NAME, VIZ_APP_NAME
#   APP_PORT, APP_CPU, APP_MEMORY, APP_MIN_SCALE
#   CE_PG_SECRET_NAME

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
IBM_CLOUD_REGION="${IBM_CLOUD_REGION:-ca-tor}"
IBM_RESOURCE_GROUP="${IBM_RESOURCE_GROUP:-Default}"
CE_PROJECT="${CE_PROJECT:-gsa-graj-ce}"
TOOLS_APP_NAME="${TOOLS_APP_NAME:-gsa-graj-tools}"
VIZ_APP_NAME="${VIZ_APP_NAME:-gsa-graj-viz}"
APP_PORT="${APP_PORT:-8000}"
APP_CPU="${APP_CPU:-0.25}"
APP_MEMORY="${APP_MEMORY:-500M}"
APP_MIN_SCALE="${APP_MIN_SCALE:-1}"
CE_PG_SECRET_NAME="${CE_PG_SECRET_NAME:-postgres-secret}"

if [[ -z "${TOOLS_IMAGE:-}" ]] || [[ -z "${VIZ_IMAGE:-}" ]]; then
  echo "ERROR: TOOLS_IMAGE and VIZ_IMAGE must be set."
  echo "  Example: ghcr.io/<GITHUB_USER>/gsa-graj-tools:latest"
  exit 1
fi

# ── IBM Cloud login check ─────────────────────────────────────────────────────
echo "→ Verifying IBM Cloud login…"
ibmcloud account show > /dev/null 2>&1 || {
  echo "ERROR: Not logged in. Run: ibmcloud login --sso"
  exit 1
}

# ── Target region / resource group ────────────────────────────────────────────
echo "→ Targeting ${IBM_CLOUD_REGION} / ${IBM_RESOURCE_GROUP}"
ibmcloud target -r "${IBM_CLOUD_REGION}" -g "${IBM_RESOURCE_GROUP}" -q

# ── Select CE project ─────────────────────────────────────────────────────────
echo "→ Selecting CE project: ${CE_PROJECT}"
ibmcloud ce project select --name "${CE_PROJECT}"

# ── Helper: create or update a CE app ─────────────────────────────────────────
deploy_app() {
  local app_name="$1"
  local image="$2"

  echo ""
  echo "── Deploying ${app_name}  (image: ${image})"

  if ibmcloud ce app get --name "${app_name}" > /dev/null 2>&1; then
    echo "   App exists — updating image…"
    ibmcloud ce app update \
      --name "${app_name}" \
      --image "${image}"
  else
    echo "   App not found — creating…"
    ibmcloud ce app create \
      --name    "${app_name}" \
      --image   "${image}" \
      --port    "${APP_PORT}" \
      --cpu     "${APP_CPU}" \
      --memory  "${APP_MEMORY}" \
      --min-scale "${APP_MIN_SCALE}" \
      --env-from-secret "${CE_PG_SECRET_NAME}"
    # Note: PORT is injected by Knative — do not pass --env PORT here.
  fi

  local url
  url="$(ibmcloud ce app get --name "${app_name}" --output json \
         | python3 -c "import sys,json; d=json.load(sys.stdin); \
             print(d.get('status',{}).get('url','<unknown>'))")"
  echo "   ✓ ${app_name}  → ${url}"
}

# ── Deploy both apps ──────────────────────────────────────────────────────────
deploy_app "${TOOLS_APP_NAME}" "${TOOLS_IMAGE}"
deploy_app "${VIZ_APP_NAME}"   "${VIZ_IMAGE}"

echo ""
echo "✓ Deployment complete."
echo ""
echo "Next: smoke-test with:"
echo "  bash deploy/ibm/prebuilt-image/smoke-test.sh"
echo ""
echo "Then re-register in watsonx Orchestrate:"
echo "  orchestrate env activate gsa-hackathon --api-key \"<WXO_API_KEY>\""
echo "  orchestrate toolkits remove --name gsa_graj_tools || true"
echo "  orchestrate toolkits remove --name gsa_graj_viz   || true"
echo "  orchestrate toolkits import -f toolkits/gsa_graj_tools/toolkit_spec.yaml"
echo "  orchestrate toolkits import -f toolkits/gsa_graj_viz/toolkit_spec.yaml"
echo "  orchestrate agents import  -f agents/gsa_graj_agent.agent.yaml"
echo "  orchestrate agents import  -f agents/gsa_graj_viz_agent.agent.yaml"
