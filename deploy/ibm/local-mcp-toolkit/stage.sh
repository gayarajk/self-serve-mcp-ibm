#!/usr/bin/env bash
# deploy/ibm/local-mcp-toolkit/stage.sh
#
# Stage a minimal package root for the gsa_graj_tools local stdio toolkit.
#
# watsonx Orchestrate uploads the package_root directory, installs its
# requirements.txt, and executes `python server.py` over stdio.  Uploading the
# whole repo causes a 413; this script copies only what the server needs.
#
# Usage:
#   bash deploy/ibm/local-mcp-toolkit/stage.sh
#
# After staging, register in watsonx Orchestrate:
#   orchestrate env activate gsa-hackathon --api-key "<API_KEY>"
#   orchestrate toolkits remove --name gsa_graj_tools_local || true
#   orchestrate toolkits import -f deploy/ibm/local-mcp-toolkit/toolkit_local.yaml

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
STAGE="${REPO_ROOT}/deploy/ibm/local-mcp-toolkit/_stage"
SRC="${REPO_ROOT}/toolkits/gsa_graj_tools"

echo "→ Staging gsa_graj_tools to ${STAGE}"
rm -rf "${STAGE}"
mkdir -p "${STAGE}"

# Flat copy — no src/ prefix; files must be importable at runtime root.
cp "${SRC}/server.py"       "${STAGE}/server.py"
cp "${SRC}/db_config.py"    "${STAGE}/db_config.py"
cp "${SRC}/requirements.txt" "${STAGE}/requirements.txt"

echo "   Staged files:"
ls -1 "${STAGE}"

echo ""
echo "✓ Stage complete.  Next steps:"
echo "   1. orchestrate env activate gsa-hackathon --api-key \"<API_KEY>\""
echo "   2. orchestrate toolkits remove --name gsa_graj_tools_local || true"
echo "   3. orchestrate toolkits import -f deploy/ibm/local-mcp-toolkit/toolkit_local.yaml"
echo "   4. orchestrate toolkits list"
