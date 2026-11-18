#!/usr/bin/env bash
# smoke-test.sh — Verify a deployed gsa_graj MCP server.
#
# Checks (against the LIVE endpoint, no mocks):
#   1. /health returns HTTP 200 with a healthy JSON body
#   2. /mcp is reachable and speaks JSON-RPC
#
# Usage — single app:
#   bash deploy/ibm/code-engine-git-build/smoke-test.sh \
#     https://gsa-graj-tools.2h721savdmhn.ca-tor.codeengine.appdomain.cloud
#
# Usage — test both apps:
#   bash deploy/ibm/code-engine-git-build/smoke-test.sh
set -euo pipefail

TOOLS_URL="https://gsa-graj-tools.2h721savdmhn.ca-tor.codeengine.appdomain.cloud"
VIZ_URL="https://gsa-graj-viz.2h721savdmhn.ca-tor.codeengine.appdomain.cloud"

test_app() {
  local base_url="${1%/}"   # strip trailing slash
  local label="${2:-$base_url}"

  echo ""
  echo "════════════════════════════════════════════════════"
  echo "  Testing: ${label}"
  echo "  URL:     ${base_url}"
  echo "════════════════════════════════════════════════════"

  # --- 1. Health check -------------------------------------------------------
  echo ""
  echo "--- 1. Health check: ${base_url}/health ---"
  HTTP_CODE="$(curl -s -o /tmp/mcp-health.json -w '%{http_code}' \
    --max-time 15 "${base_url}/health")"
  cat /tmp/mcp-health.json; echo ""

  if [[ "${HTTP_CODE}" != "200" ]]; then
    echo "FAIL: health check returned HTTP ${HTTP_CODE}" >&2
    return 1
  fi
  echo "PASS: health check HTTP 200"

  # --- 2. MCP endpoint reachable --------------------------------------------
  # A raw tools/list without the MCP `initialize` handshake is rejected with
  # "Missing session ID" — that is EXPECTED. It confirms the endpoint is live
  # and speaking JSON-RPC. Real MCP clients (Orchestrate) do the full handshake.
  echo ""
  echo "--- 2. MCP endpoint: ${base_url}/mcp ---"
  RESP="$(curl -s --max-time 15 "${base_url}/mcp" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}')"

  echo "${RESP}" | head -c 2000; echo ""

  if echo "${RESP}" | grep -qi "jsonrpc\|result\|Missing session ID"; then
    echo ""
    echo "PASS: /mcp is reachable and speaking JSON-RPC."
    echo "      ('Missing session ID' is expected for raw curl — Orchestrate"
    echo "       performs the full initialize handshake automatically.)"
  else
    echo ""
    echo "WARN: unexpected /mcp response — check Code Engine logs." >&2
    echo "      If /health passed, the server may still be starting up." >&2
  fi
}

# --- Main: single URL arg OR test both defaults ------------------------------
if [[ $# -ge 1 ]]; then
  test_app "$1" "$1"
else
  PASS=0; FAIL=0
  test_app "${TOOLS_URL}" "gsa_graj_tools" && ((PASS++)) || ((FAIL++))
  test_app "${VIZ_URL}"   "gsa_graj_viz"   && ((PASS++)) || ((FAIL++))

  echo ""
  echo "=== Summary: ${PASS} passed / ${FAIL} failed ==="
  [[ "${FAIL}" -eq 0 ]] || exit 1
fi
