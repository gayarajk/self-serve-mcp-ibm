#!/usr/bin/env bash
# redeploy.sh — Re-activate wxO session and redeploy all GSA GRAJ tools + agents.
# Usage:  bash scripts/redeploy.sh [API_KEY]
#   API_KEY  optional — overrides WXO_API_KEY from .env

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

# ── Resolve API key ────────────────────────────────────────────────────────────
if [[ -n "${1:-}" ]]; then
  API_KEY="$1"
elif [[ -f ".env" ]]; then
  API_KEY="$(grep -E '^WXO_API_KEY=' .env | cut -d= -f2- | tr -d '[:space:]')"
fi

if [[ -z "${API_KEY:-}" ]]; then
  echo "[ERROR] No API key found. Pass it as argument or set WXO_API_KEY in .env" >&2
  exit 1
fi

echo "==> Activating gsa-hackathon environment..."
orchestrate env activate gsa-hackathon --api-key "$API_KEY"

# ── Toolkits ───────────────────────────────────────────────────────────────────
echo ""
echo "==> Re-importing toolkits..."
orchestrate toolkits remove -n gsa_graj_tools 2>/dev/null || true
orchestrate toolkits import -f toolkits/gsa_graj_tools/toolkit_spec.yaml

orchestrate toolkits remove -n gsa_graj_viz 2>/dev/null || true
orchestrate toolkits import -f toolkits/gsa_graj_viz/toolkit_spec.yaml

# ── Python tools ───────────────────────────────────────────────────────────────
echo ""
echo "==> Re-importing Python tools..."
orchestrate tools remove -n gsa_graj_bulk_excel_to_sl    2>/dev/null || true
orchestrate tools remove -n gsa_graj_load_excel_to_postgres 2>/dev/null || true

orchestrate tools import -k python \
  -f tools/gsa_graj_bulk_excel_to_sl.py \
  --package-root tools/ \
  -r tools/requirements.txt

orchestrate tools import -k python \
  -f tools/gsa_graj_load_excel_to_postgres.py \
  --package-root tools/ \
  -r tools/requirements.txt

# ── Agents ─────────────────────────────────────────────────────────────────────
echo ""
echo "==> Re-importing agents..."
orchestrate agents import -f agents/gsa_graj_agent.agent.yaml
orchestrate agents import -f agents/gsa_graj_viz_agent.agent.yaml
orchestrate agents import -f agents/gsa_graj_eval_agent.agent.yaml

# ── Verify ─────────────────────────────────────────────────────────────────────
echo ""
echo "==> Verification — tools registered:"
orchestrate tools list 2>&1 | grep "gsa_graj" | awk -F'│' '{print $2}' | tr -d ' ' | grep -v '^$' | sort -u

echo ""
echo "==> Verification — toolkits:"
orchestrate toolkits list 2>&1 | grep "gsa_graj" | awk -F'│' '{print $2}' | tr -d ' ' | grep -v '^$' | sort -u

echo ""
echo "✅  Redeploy complete."
