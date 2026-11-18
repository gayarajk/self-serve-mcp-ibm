---
name: ibm-iaas-deployment
description: >
  Use when the user wants to deploy, provision, configure, or troubleshoot
  IBM Infrastructure as a Service (IaaS) resources — covers IBM Cloud VPC,
  bare metal, virtual server instances, block/object storage, load balancers,
  VPNs, security groups, and Code Engine. Activate for phrases like
  "deploy to IBM Cloud", "provision a VSI", "set up IaaS", "IBM VPC setup",
  "Code Engine deployment", or "IBM infrastructure".
---

# IBM IaaS Deployment

Step-by-step guide for provisioning and deploying workloads on IBM Cloud
Infrastructure as a Service (IaaS). Follow the phases in order; skip phases
that do not apply to the current deployment target.

---

## Phase 0 — Prerequisites

Before any provisioning step, confirm the following are in place.

### 0.1  IBM Cloud CLI installed and authenticated

```bash
# Install (Linux/macOS)
curl -fsSL https://clis.cloud.ibm.com/install/linux | sh

# Log in (interactive SSO — recommended)
ibmcloud login --sso

# Log in with API key (non-interactive / CI)
ibmcloud login --apikey "$IBM_CLOUD_API_KEY" -r us-south

# Confirm active account
ibmcloud account show
```

### 0.2  Required CLI plugins

```bash
ibmcloud plugin install vpc-infrastructure   # VPC, VSIs, subnets, security groups
ibmcloud plugin install code-engine          # Code Engine apps and jobs
ibmcloud plugin install cloud-databases      # ICD PostgreSQL, Redis, etc.
ibmcloud plugin install container-registry   # IBM Container Registry (ICR)
ibmcloud plugin install kubernetes-service   # IKS clusters (optional)

# Verify
ibmcloud plugin list
```

### 0.3  Environment variables to set now

```bash
export IBM_CLOUD_API_KEY="<your-api-key>"
export IC_REGION="ca-tor"           # e.g. us-south, eu-de, ca-tor, jp-tok
export IC_RESOURCE_GROUP="default"  # or your named resource group
```

---

## Phase 1 — Resource Group and Region

```bash
# List available resource groups
ibmcloud resource groups

# Target a resource group and region for all subsequent commands
ibmcloud target -r "$IC_REGION" -g "$IC_RESOURCE_GROUP"
```

---

## Phase 2 — VPC and Network Setup

Skip this phase if deploying to Code Engine (Phase 5) or if a VPC already exists.

### 2.1  Create a VPC

```bash
VPC_NAME="my-vpc"

ibmcloud is vpc-create "$VPC_NAME" \
  --resource-group-name "$IC_RESOURCE_GROUP"

# Capture the VPC ID for subsequent steps
VPC_ID=$(ibmcloud is vpcs --output json | \
  jq -r --arg n "$VPC_NAME" '.[] | select(.name==$n) | .id')
echo "VPC ID: $VPC_ID"
```

### 2.2  Create a subnet

```bash
SUBNET_NAME="my-subnet-1"
ZONE="${IC_REGION}-1"           # e.g. ca-tor-1

ibmcloud is subnet-create "$SUBNET_NAME" "$VPC_ID" \
  --zone "$ZONE" \
  --ipv4-address-count 256

SUBNET_ID=$(ibmcloud is subnets --output json | \
  jq -r --arg n "$SUBNET_NAME" '.[] | select(.name==$n) | .id')
echo "Subnet ID: $SUBNET_ID"
```

### 2.3  Security group rules

```bash
SG_ID=$(ibmcloud is vpc "$VPC_ID" --output json | jq -r '.default_security_group.id')

# Allow inbound SSH (port 22) from your IP only — replace 0.0.0.0/0 with your CIDR
ibmcloud is security-group-rule-add "$SG_ID" inbound tcp \
  --port-min 22 --port-max 22 --remote 0.0.0.0/0

# Allow inbound HTTPS (port 443)
ibmcloud is security-group-rule-add "$SG_ID" inbound tcp \
  --port-min 443 --port-max 443 --remote 0.0.0.0/0

# Allow all outbound
ibmcloud is security-group-rule-add "$SG_ID" outbound all
```

### 2.4  Public gateway (for outbound internet from VSIs)

```bash
GW_NAME="my-public-gw"
ibmcloud is public-gateway-create "$GW_NAME" "$VPC_ID" "$ZONE"

GW_ID=$(ibmcloud is public-gateways --output json | \
  jq -r --arg n "$GW_NAME" '.[] | select(.name==$n) | .id')

# Attach gateway to subnet
ibmcloud is subnet-update "$SUBNET_ID" --public-gateway-id "$GW_ID"
```

---

## Phase 3 — Virtual Server Instance (VSI)

### 3.1  List available profiles and images

```bash
# Profiles (compute shapes)
ibmcloud is instance-profiles --output json | jq '.[].name'

# Images (OS)
ibmcloud is images --output json | \
  jq '.[] | select(.status=="available") | {name:.name, os:.operating_system.name}'
```

### 3.2  Upload an SSH key

```bash
SSH_KEY_NAME="my-ssh-key"
ibmcloud is key-create "$SSH_KEY_NAME" @~/.ssh/id_rsa.pub
SSH_KEY_ID=$(ibmcloud is keys --output json | \
  jq -r --arg n "$SSH_KEY_NAME" '.[] | select(.name==$n) | .id')
```

### 3.3  Provision the VSI

```bash
VSI_NAME="my-vsi-1"
PROFILE="bx2-2x8"           # 2 vCPU, 8 GB RAM — adjust as needed
IMAGE_ID="<image-id>"        # from step 3.1

ibmcloud is instance-create "$VSI_NAME" "$VPC_ID" "$ZONE" "$PROFILE" "$SUBNET_ID" \
  --image-id "$IMAGE_ID" \
  --key-ids "$SSH_KEY_ID" \
  --resource-group-name "$IC_RESOURCE_GROUP"

# Wait for running state
ibmcloud is instance "$VSI_NAME" --output json | jq '.status'
```

### 3.4  Attach a floating IP (public access)

```bash
FIP_NAME="my-fip"
ibmcloud is floating-ip-reserve "$FIP_NAME" --zone "$ZONE"

FIP_ID=$(ibmcloud is floating-ips --output json | \
  jq -r --arg n "$FIP_NAME" '.[] | select(.name==$n) | .id')

VNIC_ID=$(ibmcloud is instance "$VSI_NAME" --output json | \
  jq -r '.primary_network_interface.id')

ibmcloud is instance-network-interface-floating-ip-add \
  "$VSI_NAME" "$VNIC_ID" "$FIP_ID"

echo "Connect: ssh root@$(ibmcloud is floating-ip $FIP_ID --output json | jq -r '.address')"
```

---

## Phase 4 — Block Storage Volume (optional)

```bash
VOL_NAME="my-data-vol"
ibmcloud is volume-create "$VOL_NAME" general-purpose "$ZONE" \
  --capacity 100       # GB

VOL_ID=$(ibmcloud is volumes --output json | \
  jq -r --arg n "$VOL_NAME" '.[] | select(.name==$n) | .id')

# Attach to VSI
ibmcloud is instance-volume-attachment-add \
  "$VSI_NAME" "$VOL_ID" --delete-volume-on-instance-delete false
```

---

## Phase 5 — Code Engine (serverless containers)

Use Code Engine for containerised workloads without managing VMs.

### 5.1  Select or create a project

```bash
CE_PROJECT="my-ce-project"

# Create (once per project)
ibmcloud ce project create --name "$CE_PROJECT"

# Select for all subsequent ce commands
ibmcloud ce project select --name "$CE_PROJECT"
```

### 5.2  Push image to IBM Container Registry (ICR)

```bash
ICR_NAMESPACE="my-namespace"
ICR_REGION="icr.io"            # or us.icr.io, uk.icr.io, etc.
IMAGE_TAG="${ICR_REGION}/${ICR_NAMESPACE}/my-app:latest"

# Log Docker into ICR
ibmcloud cr login

# Create namespace (once)
ibmcloud cr namespace-add "$ICR_NAMESPACE"

# Build and push
docker build -t "$IMAGE_TAG" .
docker push "$IMAGE_TAG"
```

### 5.3  Deploy a Code Engine application

```bash
APP_NAME="my-ce-app"

ibmcloud ce application create \
  --name "$APP_NAME" \
  --image "$IMAGE_TAG" \
  --port 8080 \
  --min-scale 1 \
  --max-scale 5 \
  --cpu 1 \
  --memory 2G \
  --env MY_ENV_VAR="value"

# Get the public URL
ibmcloud ce application get --name "$APP_NAME" --output json | jq -r '.status.url'
```

### 5.4  Inject a secret or configmap

```bash
# Create a secret from literal values
ibmcloud ce secret create --name "db-secret" \
  --from-literal PG_HOST="myhost.neon.tech" \
  --from-literal PG_PASS="$DB_PASSWORD"

# Bind the secret to the application
ibmcloud ce application update --name "$APP_NAME" \
  --env-from-secret "db-secret"
```

### 5.5  Redeploy after a code change

```bash
docker build -t "$IMAGE_TAG" . && docker push "$IMAGE_TAG"

ibmcloud ce application update \
  --name "$APP_NAME" \
  --image "$IMAGE_TAG"
```

---

## Phase 6 — Validation Checklist

Run through these checks after every deployment:

- [ ] `ibmcloud is instances` — VSI status is `running` (if applicable)
- [ ] `ibmcloud ce application get --name "$APP_NAME"` — `Ready: True` (if Code Engine)
- [ ] Public URL returns HTTP 200 (use `curl -I <url>`)
- [ ] SSH into VSI succeeds: `ssh root@<floating-ip>`
- [ ] Environment variables / secrets are visible inside the container
- [ ] Outbound internet access works from the instance (`curl https://wttr.in` or similar)
- [ ] Security group rules permit only intended ingress ports
- [ ] Logs are accessible: `ibmcloud ce application logs --name "$APP_NAME" --follow`

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ssh: Connection refused` | No floating IP or wrong SG rule | Check FIP and inbound port 22 rule |
| Code Engine app stuck `Deploying` | Bad image or registry auth | `ibmcloud ce application events --name $APP_NAME` |
| `ibmcloud cr login` fails | Plugin not installed | `ibmcloud plugin install container-registry` |
| VSI unreachable after attach | Missing public gateway on subnet | Attach public gateway (Phase 2.4) |
| `Error: profile not found` | Wrong region targeted | Re-run `ibmcloud target -r <region>` |
| Secret not injected | App not updated after secret create | `ibmcloud ce application update --env-from-secret <name>` |

---

## Reference Links

- IBM Cloud CLI reference — https://cloud.ibm.com/docs/cli
- VPC infrastructure — https://cloud.ibm.com/docs/vpc
- Code Engine — https://cloud.ibm.com/docs/codeengine
- IBM Container Registry — https://cloud.ibm.com/docs/Registry
- ICD for PostgreSQL — https://cloud.ibm.com/docs/databases-for-postgresql
