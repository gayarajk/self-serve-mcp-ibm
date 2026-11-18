#!/usr/bin/env bash
# =============================================================================
# migrate_to_icd.sh
#
# Migrates the local wxodb PostgreSQL database to IBM Cloud Databases (ICD)
# for PostgreSQL, then stores the connection string as a Code Engine secret
# so your deployed tools pick it up automatically via DATABASE_URL.
#
# Prerequisites
#   - ibmcloud CLI with ce (Code Engine) and databases-for-postgresql plugins:
#       ibmcloud plugin install code-engine
#       ibmcloud plugin install cloud-databases
#   - pg_dump / psql installed locally
#   - jq installed locally (for JSON parsing)
#
# Usage
#   chmod +x scripts/migrate_to_icd.sh
#   ./scripts/migrate_to_icd.sh
# =============================================================================
set -euo pipefail

# ── Configuration — edit these before running ─────────────────────────────────
RESOURCE_GROUP="default"
REGION="us-south"

ICD_INSTANCE_NAME="wxo-postgres-icd"   # Name of the new ICD instance
ICD_PLAN="standard"                    # standard | enterprise
ICD_MEMORY_MB=3072                     # Minimum memory per member

CE_PROJECT_NAME="wxo-agentic-workflow" # Your Code Engine project name
CE_SECRET_NAME="postgres-secret"       # Name of the secret to create/update
CE_APP_NAME=""                         # Your Code Engine app name (optional — leave blank to skip)

# Local source database
SRC_HOST="${PG_HOST:-localhost}"
SRC_PORT="${PG_PORT:-5432}"
SRC_DB="${PG_DB:-wxodb}"
SRC_USER="${PG_USER:-wxouser}"
SRC_PASS="${PG_PASS:-wxopass}"

DUMP_FILE="/tmp/${SRC_DB}_$(date +%Y%m%d_%H%M%S).sql"

# ── Helpers ───────────────────────────────────────────────────────────────────
info()  { echo ""; echo "▶ $*"; }
ok()    { echo "  ✓ $*"; }
warn()  { echo "  ⚠ $*"; }
die()   { echo ""; echo "✗ ERROR: $*" >&2; exit 1; }

# ── Step 1: Login check ───────────────────────────────────────────────────────
info "Checking IBM Cloud login …"
ibmcloud account show > /dev/null 2>&1 || die "Not logged in. Run: ibmcloud login --sso"
ok "Logged in."

ibmcloud target -g "${RESOURCE_GROUP}" -r "${REGION}" > /dev/null
ok "Target set: resource-group=${RESOURCE_GROUP}  region=${REGION}"

# ── Step 2: Dump local database ───────────────────────────────────────────────
info "Dumping local database '${SRC_DB}' to ${DUMP_FILE} …"
PGPASSWORD="${SRC_PASS}" pg_dump \
  -h "${SRC_HOST}" -p "${SRC_PORT}" \
  -U "${SRC_USER}" -d "${SRC_DB}" \
  --no-owner --no-acl \
  -f "${DUMP_FILE}"
ok "Dump complete: $(du -sh "${DUMP_FILE}" | cut -f1)"

# ── Step 3: Provision ICD instance (skip if it already exists) ────────────────
info "Checking for existing ICD instance '${ICD_INSTANCE_NAME}' …"
EXISTING=$(ibmcloud resource service-instances --output json 2>/dev/null \
  | jq -r --arg n "${ICD_INSTANCE_NAME}" '.[] | select(.name==$n) | .name' || true)

if [[ -z "${EXISTING}" ]]; then
  info "Provisioning ICD for PostgreSQL — this takes ~10 minutes …"
  ibmcloud resource service-instance-create "${ICD_INSTANCE_NAME}" \
    databases-for-postgresql "${ICD_PLAN}" "${REGION}" \
    --parameters "{\"members_memory_allocation_mb\": ${ICD_MEMORY_MB}}"
  ok "Provisioning started. Waiting for ready state …"
  # Poll until provisioned
  for i in $(seq 1 60); do
    STATE=$(ibmcloud resource service-instance "${ICD_INSTANCE_NAME}" --output json \
      | jq -r '.[0].last_operation.state // "unknown"')
    echo "  … state: ${STATE} (${i}/60)"
    [[ "${STATE}" == "succeeded" ]] && break
    [[ "${STATE}" == "failed" ]]    && die "Provisioning failed."
    sleep 15
  done
  ok "ICD instance ready."
else
  ok "ICD instance '${ICD_INSTANCE_NAME}' already exists — skipping creation."
fi

# ── Step 4: Get the connection string ─────────────────────────────────────────
info "Retrieving ICD connection string …"
CONN_JSON=$(ibmcloud cdb deployment-connections "${ICD_INSTANCE_NAME}" \
  --user ibm_cloud_admin --output json 2>/dev/null)

ICD_HOST=$(echo "${CONN_JSON}" | jq -r '.connection.postgres.hosts[0].hostname')
ICD_PORT=$(echo "${CONN_JSON}" | jq -r '.connection.postgres.hosts[0].port')
ICD_DB=$(echo   "${CONN_JSON}" | jq -r '.connection.postgres.database')
ICD_USER=$(echo "${CONN_JSON}" | jq -r '.connection.postgres.authentication.username')
ICD_PASS=$(echo "${CONN_JSON}" | jq -r '.connection.postgres.authentication.password')
ICD_CERT=$(echo "${CONN_JSON}" | jq -r '.connection.postgres.certificate.certificate_base64 // ""')

DATABASE_URL="postgresql://${ICD_USER}:${ICD_PASS}@${ICD_HOST}:${ICD_PORT}/${ICD_DB}?sslmode=verify-full"
ok "Connection string assembled."
echo "  Host : ${ICD_HOST}:${ICD_PORT}"
echo "  DB   : ${ICD_DB}"

# Save CA cert if provided
if [[ -n "${ICD_CERT}" ]]; then
  CERT_PATH="/tmp/icd_postgresql.crt"
  echo "${ICD_CERT}" | base64 -d > "${CERT_PATH}"
  ok "CA certificate saved to ${CERT_PATH}"
  warn "Copy this cert to your project and set PGSSLROOTCERT in your Code Engine secret."
fi

# ── Step 5: Restore dump into ICD ─────────────────────────────────────────────
info "Restoring dump into ICD database '${ICD_DB}' …"
warn "If prompted for a password, use the ICD admin password shown above."
PGPASSWORD="${ICD_PASS}" psql \
  "postgresql://${ICD_USER}:${ICD_PASS}@${ICD_HOST}:${ICD_PORT}/${ICD_DB}?sslmode=require" \
  -f "${DUMP_FILE}"
ok "Restore complete."

# ── Step 6: Store DATABASE_URL as a Code Engine secret ───────────────────────
info "Storing DATABASE_URL in Code Engine secret '${CE_SECRET_NAME}' …"
ibmcloud ce project select --name "${CE_PROJECT_NAME}"

# Create or update the secret
if ibmcloud ce secret get --name "${CE_SECRET_NAME}" > /dev/null 2>&1; then
  ibmcloud ce secret update --name "${CE_SECRET_NAME}" \
    --from-literal "DATABASE_URL=${DATABASE_URL}"
  ok "Secret updated."
else
  ibmcloud ce secret create --name "${CE_SECRET_NAME}" \
    --from-literal "DATABASE_URL=${DATABASE_URL}"
  ok "Secret created."
fi

# ── Step 7: Bind secret to Code Engine app (optional) ─────────────────────────
if [[ -n "${CE_APP_NAME}" ]]; then
  info "Binding secret to Code Engine app '${CE_APP_NAME}' …"
  ibmcloud ce application update \
    --name "${CE_APP_NAME}" \
    --env-from-secret "${CE_SECRET_NAME}"
  ok "App updated — it will pick up DATABASE_URL on next start."
else
  warn "CE_APP_NAME is empty — skipping app binding."
  warn "Run manually:  ibmcloud ce application update --name <APP> --env-from-secret ${CE_SECRET_NAME}"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════════"
echo " Migration complete!"
echo ""
echo " LOCAL  → ${SRC_HOST}:${SRC_PORT}/${SRC_DB}  (still running, unchanged)"
echo " REMOTE → ${ICD_HOST}:${ICD_PORT}/${ICD_DB}"
echo ""
echo " Next steps:"
echo "   1. Update your local .env:  DATABASE_URL=${DATABASE_URL}"
echo "   2. Test locally:            orchestrate env activate <env>"
echo "   3. Re-import tools:         orchestrate tools import ..."
echo "   4. Verify agent:            orchestrate agent chat gsa_graj_agent"
echo "════════════════════════════════════════════════════════════════"
echo ""
