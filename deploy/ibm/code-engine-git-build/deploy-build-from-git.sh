#!/usr/bin/env bash
# deploy-build-from-git.sh — Build and deploy an MCP server to IBM Code Engine
# directly from a public Git repo (no local Docker required).
#
# Flow (all server-side):
#   1. Ensure the IBM Container Registry (ICR) namespace exists (create-or-reuse).
#   2. Create / update a Code Engine registry-access secret from an IBM Cloud
#      API key so Code Engine can PUSH the built image to that namespace.
#   3. Ensure the Code Engine project exists and is selected.
#   4. `ce app create/update --build-source <git> --image <icr-ref>`:
#      Code Engine clones the repo, builds the Dockerfile, pushes the image to
#      ICR, then deploys it.
#
# Apps deployed by this script:
#   gsa-graj-tools  →  toolkits/gsa_graj_tools/Dockerfile
#   gsa-graj-viz    →  toolkits/gsa_graj_viz/Dockerfile
#
# Usage — deploy both apps:
#   set -a; source deploy/ibm/code-engine-git-build/.env; set +a
#   export IBMCLOUD_API_KEY="<your-iam-api-key>"
#   bash deploy/ibm/code-engine-git-build/deploy-build-from-git.sh
#
# Usage — deploy one app only (override CE_APP_NAME + GIT_CONTEXT_DIR):
#   export CE_APP_NAME=gsa-graj-viz
#   export GIT_CONTEXT_DIR=toolkits/gsa_graj_viz
#   export GIT_DOCKERFILE=toolkits/gsa_graj_viz/Dockerfile
#   bash deploy/ibm/code-engine-git-build/deploy-build-from-git.sh
#
# Idempotent: creates resources on first run, updates on later runs.
set -euo pipefail

# --- Validate required config ------------------------------------------------
: "${IBMCLOUD_REGION:?set IBMCLOUD_REGION (source .env)}"
: "${IBMCLOUD_RESOURCE_GROUP:?set IBMCLOUD_RESOURCE_GROUP}"
: "${CE_PROJECT:?set CE_PROJECT}"
: "${CE_PORT:?set CE_PORT}"
: "${GIT_REPO_URL:?set GIT_REPO_URL}"
: "${ICR_REGION:?set ICR_REGION}"
: "${ICR_DOMAIN:?set ICR_DOMAIN}"
: "${ICR_NAMESPACE:?set ICR_NAMESPACE}"
: "${IMAGE_TAG:?set IMAGE_TAG}"
: "${CE_REGISTRY_SECRET:?set CE_REGISTRY_SECRET}"

GIT_BRANCH="${GIT_BRANCH:-main}"

# --- Confirm we are logged in ------------------------------------------------
if ! ibmcloud target >/dev/null 2>&1; then
  echo "FATAL: not logged in. Run 'ibmcloud login --sso' first." >&2
  exit 1
fi

# --- Select region + resource group ------------------------------------------
echo "=== Targeting region '${IBMCLOUD_REGION}' / resource group '${IBMCLOUD_RESOURCE_GROUP}' ==="
ibmcloud target -r "${IBMCLOUD_REGION}" -g "${IBMCLOUD_RESOURCE_GROUP}"

# --- Obtain the API key for the ICR push secret ------------------------------
API_KEY="${IBMCLOUD_API_KEY:-}"
if [[ -z "${API_KEY}" ]]; then
  echo ""
  echo "=== IBMCLOUD_API_KEY is not set ==="
  echo "  Enter an IBM Cloud API key with ICR write access (input hidden)."
  echo "  Create one with:"
  echo "    ibmcloud iam api-key-create ce-icr-push -d 'Code Engine ICR push'"
  read -r -s -p "  IBM Cloud API key: " API_KEY
  echo ""
  if [[ -z "${API_KEY}" ]]; then
    echo "FATAL: no API key provided." >&2
    exit 1
  fi
fi

# --- Ensure the ICR namespace exists -----------------------------------------
echo ""
echo "=== Ensuring ICR namespace '${ICR_NAMESPACE}' in '${ICR_REGION}' ==="
ibmcloud cr region-set "${ICR_REGION}" >/dev/null
if ibmcloud cr namespace-list --output json 2>/dev/null | grep -q "\"${ICR_NAMESPACE}\""; then
  echo "  namespace exists — reusing."
else
  echo "  namespace not found — creating '${ICR_NAMESPACE}'..."
  ibmcloud cr namespace-add "${ICR_NAMESPACE}"
fi

# --- Ensure the Code Engine project exists -----------------------------------
echo ""
echo "=== Selecting Code Engine project '${CE_PROJECT}' ==="
if ibmcloud ce project select --name "${CE_PROJECT}" >/dev/null 2>&1; then
  echo "  project exists — selected."
else
  echo "  project not found — creating '${CE_PROJECT}'..."
  ibmcloud ce project create --name "${CE_PROJECT}"
  ibmcloud ce project select --name "${CE_PROJECT}"
fi

# --- Ensure the CE registry-access secret ------------------------------------
echo ""
echo "=== Ensuring registry secret '${CE_REGISTRY_SECRET}' ==="
if ibmcloud ce registry get --name "${CE_REGISTRY_SECRET}" >/dev/null 2>&1; then
  echo "  secret exists — updating credentials."
  ibmcloud ce registry update \
    --name    "${CE_REGISTRY_SECRET}" \
    --server  "${ICR_DOMAIN}" \
    --username iamapikey \
    --password "${API_KEY}"
else
  echo "  secret not found — creating."
  ibmcloud ce registry create \
    --name    "${CE_REGISTRY_SECRET}" \
    --server  "${ICR_DOMAIN}" \
    --username iamapikey \
    --password "${API_KEY}"
fi

# --- Inner function: deploy one app ------------------------------------------
deploy_app() {
  local app_name="$1"
  local context_dir="$2"
  local dockerfile="$3"
  local image_ref="${ICR_DOMAIN}/${ICR_NAMESPACE}/${app_name}:${IMAGE_TAG}"

  echo ""
  echo "════════════════════════════════════════════════════"
  echo "  App:         ${app_name}"
  echo "  Git repo:    ${GIT_REPO_URL} (branch: ${GIT_BRANCH})"
  echo "  Context dir: ${context_dir}"
  echo "  Dockerfile:  ${dockerfile}"
  echo "  Image (ICR): ${image_ref}"
  echo "════════════════════════════════════════════════════"

  SOURCE_ARGS=(
    --build-source      "${GIT_REPO_URL}"
    --build-commit      "${GIT_BRANCH}"
    --build-context-dir "${context_dir}"
    --build-dockerfile  "${dockerfile}"
    --build-strategy    dockerfile
    --image             "${image_ref}"
    --registry-secret   "${CE_REGISTRY_SECRET}"
  )

  # --min-scale 1: keep one instance warm — prevents cold-start timeouts during
  # eval runs or demo sessions.
  COMMON_ARGS=(
    --name        "${app_name}"
    --port        "${CE_PORT}"
    --min-scale   1
    --cpu         0.5
    --memory      1G
    --env-from-secret postgres-secret
  )

  if ibmcloud ce app get --name "${app_name}" >/dev/null 2>&1; then
    echo "  Updating existing app (rebuild from Git) ..."
    ibmcloud ce app update "${COMMON_ARGS[@]}" "${SOURCE_ARGS[@]}"
  else
    echo "  Creating new app (first build may take a few minutes) ..."
    ibmcloud ce app create "${COMMON_ARGS[@]}" "${SOURCE_ARGS[@]}"
  fi

  local url
  url="$(ibmcloud ce app get --name "${app_name}" --output url 2>/dev/null || echo '<pending>')"
  echo ""
  echo "  ✓ App URL:      ${url}"
  echo "  ✓ MCP endpoint: ${url}/mcp"
  echo "  ✓ Health:       ${url}/health"
  echo "  ✓ Image in ICR: ${image_ref}"
}

# --- Decide which apps to deploy ---------------------------------------------
# If CE_APP_NAME is set to a specific app (not the default), deploy only that
# one. Otherwise deploy both.
if [[ -n "${CE_APP_NAME:-}" && "${CE_APP_NAME}" != "gsa-graj-tools" ]]; then
  # Single-app override mode (caller exported CE_APP_NAME + GIT_CONTEXT_DIR)
  : "${GIT_CONTEXT_DIR:?set GIT_CONTEXT_DIR for single-app mode}"
  : "${GIT_DOCKERFILE:?set GIT_DOCKERFILE for single-app mode}"
  deploy_app "${CE_APP_NAME}" "${GIT_CONTEXT_DIR}" "${GIT_DOCKERFILE}"
else
  # Default: deploy both toolkits
  deploy_app "gsa-graj-tools" \
    "toolkits/gsa_graj_tools" \
    "toolkits/gsa_graj_tools/Dockerfile"

  deploy_app "gsa-graj-viz" \
    "toolkits/gsa_graj_viz" \
    "toolkits/gsa_graj_viz/Dockerfile"
fi

# --- Final summary -----------------------------------------------------------
echo ""
echo "=== All deployments complete ==="
echo ""
echo "Smoke-test each app:"
echo "  bash deploy/ibm/code-engine-git-build/smoke-test.sh \\"
echo "    https://gsa-graj-tools.2h721savdmhn.ca-tor.codeengine.appdomain.cloud"
echo "  bash deploy/ibm/code-engine-git-build/smoke-test.sh \\"
echo "    https://gsa-graj-viz.2h721savdmhn.ca-tor.codeengine.appdomain.cloud"
echo ""
echo "Then re-register the toolkits in watsonx Orchestrate:"
echo "  source .venv/bin/activate"
echo "  orchestrate env activate gsa-hackathon --api-key \"\$WXO_API_KEY\""
echo "  orchestrate toolkits remove --name gsa_graj_tools || true"
echo "  orchestrate toolkits remove --name gsa_graj_viz   || true"
echo "  orchestrate toolkits import -f toolkits/gsa_graj_tools/toolkit_spec.yaml"
echo "  orchestrate toolkits import -f toolkits/gsa_graj_viz/toolkit_spec.yaml"
echo "  orchestrate agents import -f agents/gsa_graj_agent.agent.yaml"
echo "  orchestrate agents import -f agents/gsa_graj_viz_agent.agent.yaml"
echo "  orchestrate agents import -f agents/gsa_graj_eval_agent.agent.yaml"
