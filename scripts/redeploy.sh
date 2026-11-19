#!/usr/bin/env bash
# redeploy.sh — Re-activate wxO session and redeploy GSA GRAJ tools + agents.
#
# Usage:
#   bash scripts/redeploy.sh [API_KEY] [--full]
#
#   API_KEY   optional — overrides WXO_API_KEY from .env
#   --full    also redeploy toolkits and Python tools (slow ~5 min)
#             omit for the fast path: agents only (~30 sec)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

FULL=false
API_KEY=""

for arg in "$@"; do
  if [[ "$arg" == "--full" ]]; then
    FULL=true
  else
    API_KEY="$arg"
  fi
done

# ── Resolve API key ────────────────────────────────────────────────────────────
if [[ -z "$API_KEY" && -f ".env" ]]; then
  API_KEY="$(grep -E '^WXO_API_KEY=' .env | cut -d= -f2- | tr -d '[:space:]')"
fi

if [[ -z "${API_KEY:-}" ]]; then
  echo "[ERROR] No API key found. Pass it as argument or set WXO_API_KEY in .env" >&2
  exit 1
fi

# ── Activate ───────────────────────────────────────────────────────────────────
echo "==> Activating gsa-hackathon environment..."
orchestrate env activate gsa-hackathon --api-key "$API_KEY"

# ── Full redeploy (toolkits + Python tools) ────────────────────────────────────
if [[ "$FULL" == true ]]; then
  echo ""
  echo "==> [FULL] Re-importing toolkits..."
  orchestrate toolkits remove -n gsa_graj_tools 2>/dev/null || true
  orchestrate toolkits import -f toolkits/gsa_graj_tools/toolkit_spec.yaml

  orchestrate toolkits remove -n gsa_graj_viz 2>/dev/null || true
  orchestrate toolkits import -f toolkits/gsa_graj_viz/toolkit_spec.yaml

  echo ""
  echo "==> [FULL] Re-importing Python tools..."
  orchestrate tools remove -n gsa_graj_bulk_excel_to_sl       2>/dev/null || true
  orchestrate tools remove -n gsa_graj_load_excel_to_postgres  2>/dev/null || true

  orchestrate tools import -k python \
    -f tools/gsa_graj_bulk_excel_to_sl.py \
    --package-root tools/ \
    -r tools/requirements.txt

  orchestrate tools import -k python \
    -f tools/gsa_graj_load_excel_to_postgres.py \
    --package-root tools/ \
    -r tools/requirements.txt
else
  echo "   (skipping toolkit + Python tool redeploy — pass --full to include)"
fi

# ── Agents (always fast) ───────────────────────────────────────────────────────
echo ""
echo "==> Re-importing agents..."
orchestrate agents import -f agents/gsa_graj_agent.agent.yaml
orchestrate agents import -f agents/gsa_graj_viz_agent.agent.yaml
orchestrate agents import -f agents/gsa_graj_eval_agent.agent.yaml

echo ""
echo "✅  Done. Agents restored with tool bindings."
