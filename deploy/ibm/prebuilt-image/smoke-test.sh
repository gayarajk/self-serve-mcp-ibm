#!/usr/bin/env bash
# deploy/ibm/prebuilt-image/smoke-test.sh
#
# Verify that the two deployed apps are healthy and speaking MCP JSON-RPC.
#
# Usage:
#   # Test both apps (reads URLs from CE)
#   bash deploy/ibm/prebuilt-image/smoke-test.sh
#
#   # Test a specific URL directly
#   bash deploy/ibm/prebuilt-image/smoke-test.sh \
#     https://gsa-graj-tools.2h721savdmhn.ca-tor.codeengine.appdomain.cloud
#
# Returns exit code 0 if all checks pass, non-zero otherwise.

set -euo pipefail

PASS=0
FAIL=0

check_app() {
  local base="$1"
  local label="${2:-${base}}"

  echo ""
  echo "── Checking: ${label}"
  echo "   URL: ${base}"

  # ── /health ──────────────────────────────────────────────────────────────
  local http_code
  http_code="$(curl -s -o /dev/null -w '%{http_code}' \
                 --max-time 15 "${base}/health")"
  if [[ "${http_code}" == "200" ]]; then
    echo "   PASS: /health → HTTP ${http_code}"
    (( PASS++ )) || true
  else
    echo "   FAIL: /health → HTTP ${http_code}  (expected 200)"
    (( FAIL++ )) || true
  fi

  # ── /mcp ─────────────────────────────────────────────────────────────────
  local mcp_body
  mcp_body="$(curl -s --max-time 15 \
                -H 'Content-Type: application/json' \
                -H 'Accept: application/json, text/event-stream' \
                -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
                "${base}/mcp")" || mcp_body=""

  if echo "${mcp_body}" | grep -qE '"jsonrpc"|"error"|session'; then
    echo "   PASS: /mcp is reachable and speaking JSON-RPC."
    (( PASS++ )) || true
  else
    echo "   FAIL: /mcp response did not look like JSON-RPC."
    echo "         Response: ${mcp_body:0:200}"
    (( FAIL++ )) || true
  fi
}

# ── Determine URLs ────────────────────────────────────────────────────────────
if [[ "${1:-}" == http* ]]; then
  # Explicit URL passed — test just that one app
  check_app "$1" "custom"
else
  # Auto-detect from CE (requires ibmcloud login + project selected)
  CE_PROJECT="${CE_PROJECT:-gsa-graj-ce}"
  TOOLS_APP_NAME="${TOOLS_APP_NAME:-gsa-graj-tools}"
  VIZ_APP_NAME="${VIZ_APP_NAME:-gsa-graj-viz}"

  get_url() {
    ibmcloud ce app get --name "$1" --output json 2>/dev/null \
      | python3 -c "import sys,json; d=json.load(sys.stdin); \
          print(d.get('status',{}).get('url',''))" 2>/dev/null || true
  }

  echo "→ Looking up URLs from CE project: ${CE_PROJECT}"
  ibmcloud ce project select --name "${CE_PROJECT}" -q 2>/dev/null || true

  TOOLS_URL="$(get_url "${TOOLS_APP_NAME}")"
  VIZ_URL="$(get_url "${VIZ_APP_NAME}")"

  [[ -z "${TOOLS_URL}" ]] && TOOLS_URL="https://gsa-graj-tools.2h721savdmhn.ca-tor.codeengine.appdomain.cloud"
  [[ -z "${VIZ_URL}" ]]   && VIZ_URL="https://gsa-graj-viz.2h721savdmhn.ca-tor.codeengine.appdomain.cloud"

  check_app "${TOOLS_URL}" "${TOOLS_APP_NAME}"
  check_app "${VIZ_URL}"   "${VIZ_APP_NAME}"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "──────────────────────────────────────────"
echo "  Results: ${PASS} passed / ${FAIL} failed"
echo "──────────────────────────────────────────"

if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
